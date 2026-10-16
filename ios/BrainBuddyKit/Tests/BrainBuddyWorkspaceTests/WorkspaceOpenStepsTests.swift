import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// `Workspace.openStepServerIDs()`: every open step with its server id, on both workspaces.
@MainActor
@Suite("Open steps with server ids (030-FR-005, 030-FR-013)")
struct WorkspaceOpenStepsTests {
    @Test("030_FR_005 030_FR_013: the legacy workspace lists open steps with their server ids and skips finished ones")
    func legacyOpenSteps() async throws {
        let document = StoreDocument(base: Fixture.base([
            Fixture.serverTask("one", "Open next", state: .next),
            Fixture.serverTask("two", "Done", state: .completed),
            Fixture.serverTask("three", "Maybe later", state: .someday),
        ]))
        let workspace = await loadedWorkspace(store: InMemoryDocumentStore(document: document))

        let steps = try await workspace.openStepServerIDs()

        #expect(steps == [
            OpenStepServerID(taskID: "one", serverID: "task_one"),
            OpenStepServerID(taskID: "three", serverID: "task_three"),
        ])
    }

    @Test("030_FR_005 030_FR_013: a Rust-selected workspace returns every synced open step's server id, not only the rendered window")
    func rustSelectedOpenSteps() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let instant = Date(timeIntervalSince1970: 1_790_000_000)
        let open = "task_00000000-0000-4000-8000-000000000041"
        let finished = "task_00000000-0000-4000-8000-000000000042"
        let inbox = "task_00000000-0000-4000-8000-000000000043"
        var source = GTDState.empty
        source.tasks[TaskID("00000000-0000-4000-8000-000000000041")] = TaskRecord(
            id: TaskID("00000000-0000-4000-8000-000000000041"), serverID: open, serverRevision: 1,
            title: "Open next", state: .next, orderKey: 1, createdAt: instant, updatedAt: instant)
        source.tasks[TaskID("00000000-0000-4000-8000-000000000042")] = TaskRecord(
            id: TaskID("00000000-0000-4000-8000-000000000042"), serverID: finished, serverRevision: 1,
            title: "Finished", state: .completed, completedAt: instant, orderKey: 2, createdAt: instant,
            updatedAt: instant)
        source.tasks[TaskID("00000000-0000-4000-8000-000000000043")] = TaskRecord(
            id: TaskID("00000000-0000-4000-8000-000000000043"), serverID: inbox, serverRevision: 1,
            title: "Open inbox", state: .inbox, orderKey: 3, createdAt: instant, updatedAt: instant)
        let json = directory.appendingPathComponent("document.json")
        let database = directory.appendingPathComponent("store.sqlite3")
        try StoreDocumentCoding.makeEncoder().encode(StoreDocument(base: source)).write(to: json)
        let bridge = try RustBridgeRuntime()
        _ = try await bridge.importLegacyStore(.init(workspaceID: "local", databasePath: database.path,
            sourcePath: json.path, now: "2026-09-21T00:00:00Z"))
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: database)
        let workspace = Workspace(store: ControlledStore(), sync: nil, rust: RustWorkspaceSelection(
            runtime: runtime, facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))),
            now: { instant })
        await workspace.load()

        let steps = try await workspace.openStepServerIDs()
        let serverIDs = Set(steps.compactMap(\.serverID))

        #expect(steps.count == 2)
        #expect(serverIDs == [open, inbox])
        await workspace.closeRuntime()
    }

    @Test("030_FR_005: a Rust-selected workspace lists a new open step and drops it once completed")
    func rustSelectedFollowsCompletion() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let workspace = Workspace(store: ControlledStore(), sync: nil, rust: RustWorkspaceSelection(
            runtime: runtime, facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
            startup: .freshAccountless), now: { Date(timeIntervalSince1970: 1_790_000_000) })
        await workspace.load()
        _ = try await workspace.capture(CaptureDraft(text: "Keep open"), editorID: "scene:open-steps:keep")
        let done = try await workspace.capture(CaptureDraft(text: "Finish me"), editorID: "scene:open-steps:done")
        try await workspace.completeTask(done, editorID: "scene:open-steps:complete")
        await workspace.settleRustWork()

        let steps = try await workspace.openStepServerIDs()

        #expect(steps.count == 1)
        #expect(steps.first?.serverID?.isEmpty == false)
        await workspace.closeRuntime()
    }
}
