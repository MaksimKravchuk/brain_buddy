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

    @Test("026-FR-025: the established Review codec matches the independently authored migration oracle")
    func reviewMigrationFieldParity() throws {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let fixture = try RustJSON.object(Data(contentsOf: root.appendingPathComponent(
            "rust/crates/bb-client/tests/fixtures/legacy-review-activation.json")))
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        var source = GTDState.empty
        source.review = try decoder.decode(ReviewState.self, from: RustJSON.data(fixture.object("source_review")))
        source.tasks = try decoder.decode([TaskID: TaskRecord].self, from: RustJSON.data(fixture.object("source_tasks")))
        let bindings = source.tasks.values.compactMap { task -> RustWorkspaceIdentityBinding? in
            guard let server = task.serverID else { return nil }
            return RustWorkspaceIdentityBinding(entityType: "task", localID: task.id.rawValue, canonicalID: server)
        }
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        let prepared = try facade.workspacePrepareLegacyReview(source, bindings: bindings)
        let actual = try JSONSerialization.jsonObject(with: prepared.readSet) as? NSDictionary
        #expect(actual == (try fixture.object("expected_read_set") as NSDictionary))
        let counts = try fixture.object("expected_derived_counts")
        #expect(prepared.decisionQueues == UInt64(try counts.int("decision_queues")))
        #expect(prepared.unseenParkAcknowledgements == UInt64(try counts.int("unseen_park_acks")))
        #expect(actual?["tasks"] == nil)
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
        let inputs = try facade.workspaceQueryInputs(at: date, zone: "UTC", reviewExposed: false)
        let query = try RustJSON.data(["kind": "task_detail", "task_id": command.entityID!])
        guard case .answered(let detail) = try await runtime.query(query, inputs: inputs) else {
            Issue.record("saved task must have a canonical detail answer"); return
        }
        var stale = try #require(state.tasks[taskID])
        stale.title = "A stale Swift title"
        stale.subtasks = [SubtaskRecord(id: SubtaskID("stale-child"), title: "Removed", orderKey: 1)]
        let canonical = try facade.workspaceTask(from: detail.result, keeping: stale, detail: true, at: date)
        #expect(canonical.title == "Keep my draft")
        #expect(canonical.subtasks.isEmpty)
        #expect(ShownTask(canonical).childrenKnown)
        let summary = try facade.workspaceTask(from: detail.result, keeping: stale, detail: false, at: date)
        #expect(summary.title == "Keep my draft")
        #expect(summary.subtasks == stale.subtasks)
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

    @Test("026-FR-025: proved imported aliases preserve shown revisions and compare canonical memberships")
    func commandIdentityAliases() throws {
        let localTask = TaskID("00000000-0000-4000-8000-000000000031")
        let localTag = TagID("00000000-0000-4000-8000-000000000032")
        let canonicalTask = TaskID("task_proved_server")
        let canonicalTag = TagID("tag_proved_server")
        let shown = Fixture.state(tasks: [Fixture.task(canonicalTask, tagIDs: [canonicalTag])])
        let bindings = [RustWorkspaceIdentityBinding(entityType: "task", localID: localTask.rawValue,
            canonicalID: canonicalTask.rawValue), RustWorkspaceIdentityBinding(entityType: "tag",
            localID: localTag.rawValue, canonicalID: canonicalTag.rawValue)]
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        let intent = GTDCommand.updateTask(.init(taskID: localTask, changes: TaskChanges(tagIDs: .set([localTag]))))
        let command = try facade.workspaceCommand(intent, commandID: UUID(), at: date, in: shown, bindings: bindings)
        #expect(command.entityID == canonicalTask.rawValue)
        let check = try #require(try RustJSON.array(command.preconditions).first as? WireObject)
        #expect(try check.string("entity_id") == canonicalTask.rawValue)
        #expect(try check.string("edit_revision") == "3")
        let changes = try RustJSON.object(command.payload).object("tag_changes")
        #expect(try changes.strings("add_tag_ids").isEmpty)
        #expect(try changes.strings("remove_tag_ids").isEmpty)
        let touched = try facade.workspaceIdentityRequests(for: [intent], in: shown, at: date)
        #expect(touched.contains(RustWorkspaceIdentityRequest(entityType: "task", localID: localTask.rawValue)))
        #expect(touched.contains(RustWorkspaceIdentityRequest(entityType: "tag", localID: localTag.rawValue)))
        #expect(!touched.contains { $0.entityType == "form" || $0.entityType == "progress" })
    }

    @Test("026-FR-001: atomic gesture membership encoding removes an earlier intended tag")
    func absoluteMembershipWithinBatch() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let task = TaskID(UUID().uuidString.lowercased())
        let first = TagID(UUID().uuidString.lowercased())
        let second = TagID(UUID().uuidString.lowercased())
        let intents: [GTDCommand] = [.createTag(.init(tagID: first, name: "First")),
            .createTag(.init(tagID: second, name: "Second")),
            .createTask(.init(taskID: task, title: "Keep only the last tag", list: .inbox, tagIDs: [first])),
            .updateTask(.init(taskID: task, changes: TaskChanges(tagIDs: .set([second]))))]
        let commands = try facade.workspaceCommands(intents, commandIDs: intents.map { _ in UUID() },
            at: intents.map { _ in date }, in: .empty)
        let update = try RustJSON.object(commands[3].payload)
        #expect((try update.object("tag_changes")["remove_tag_ids"] as? [String]) == ["tag_" + first.rawValue])
        guard case .saved = try await runtime.execute(commands, context: context()) else {
            Issue.record("the complete gesture must save"); return
        }
        let state = try facade.workspaceState(from: await runtime.snapshot(), keeping: .empty, at: date)
        #expect(state.tasks[task]?.tagIDs == [second])
        try await runtime.close()
    }
}
