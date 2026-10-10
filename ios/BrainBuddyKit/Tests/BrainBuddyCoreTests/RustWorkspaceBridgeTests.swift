import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Durable Rust workspace bridge (026-FR-001, 026-FR-025, 026-FR-026)")
struct RustWorkspaceBridgeTests {
    private let date = Date(timeIntervalSince1970: 1_790_000_000)

    private func context() throws -> RustWorkspaceContext {
        RustWorkspaceContext(now: date, timeZone: "UTC", actorID: "device", policy: try RustJSON.data([
            "weekly_review": false, "navigator_provider": NSNull(),
            "navigator_available": false, "consent_text_version": 1,
        ]))
    }

    @Test("026-FR-001: the real Swift bridge saves once and adopts an owned bootstrap image")
    func durableCompletionAndBootstrap() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let taskID = TaskID(UUID().uuidString.lowercased())
        let command = try facade.workspaceCommand(.createTask(.init(taskID: taskID, title: "Keep my draft", list: .inbox)),
            commandID: UUID(), at: date, in: .empty)
        let saved = try await runtime.execute([command], context: context())
        let retried = try await runtime.execute([command], context: context())
        guard case .saved(let first) = saved, case .saved(let second) = retried else {
            Issue.record("valid command must save"); return
        }
        #expect(first[0].commandID == command.commandID)
        #expect(second[0].replayed)
        #expect(first[0].localSequence == second[0].localSequence)
        let snapshot = try await runtime.snapshot()
        #expect(snapshot.pending == "1")
        let state = try facade.workspaceState(from: snapshot, keeping: .empty, at: date)
        #expect(state.tasks[taskID]?.title == "Keep my draft")
        let subscription = try await runtime.subscribe()
        let initial = try #require(try await subscription.next(after: nil, timeoutMilliseconds: 0))
        #expect(initial.projectionGeneration == snapshot.projectionGeneration)
        subscription.cancel()
        try await runtime.close()
        try await runtime.close()
    }

    @Test("026-FR-001: a cancelled Swift caller saves nothing and keeps its authored command")
    func cancellationBeforeCommit() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let runtime = try await RustBridgeRuntime().openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let command = RustWorkspaceCommand(commandID: UUID().uuidString.lowercased(), commandType: "task.create",
            entityID: nil, payload: Data("{\"title\":\"Keep my draft\"}".utf8))
        let context = try context()
        let cancelled = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await runtime.execute([command], context: context)
        }
        do {
            _ = try await cancelled.value
            Issue.record("cancel must win before execute")
        } catch let error as RustBridgeError {
            #expect(error.code == "CANCELLED")
        }
        #expect(try await runtime.snapshot().pending == "0")
        #expect(String(data: command.payload, encoding: .utf8)?.contains("Keep my draft") == true)
        try await runtime.close()
    }

    @Test("026-FR-025: bootstrap ID mapping strips UUID prefixes and preserves opaque IDs")
    func bootstrapIdentifiers() {
        let ids = RustIDTable(stripsUUIDPrefixes: true)
        let uuid = "00000000-0000-4000-8000-000000000001"
        #expect(ids.swift("task_" + uuid) == uuid)
        #expect(ids.swift("task_opaque") == "task_opaque")
        #expect(ids.swift("unknown_" + uuid) == "unknown_" + uuid)
    }
}
