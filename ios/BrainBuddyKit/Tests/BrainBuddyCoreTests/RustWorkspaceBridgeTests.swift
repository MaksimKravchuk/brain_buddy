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
        #expect(state.tasks[TaskID(command.entityID!)]?.title == "Keep my draft")
        let inputs = try facade.workspaceQueryInputs(at: date, zone: "UTC", reviewExposed: false)
        let query = try RustJSON.data(["kind": "task_detail", "task_id": command.entityID!])
        guard case .answered(let detail) = try await runtime.query(query, inputs: inputs) else {
            Issue.record("saved task must have a canonical detail answer"); return
        }
        var stale = try #require(state.tasks[TaskID(command.entityID!)])
        stale.title = "A stale Swift title"
        stale.subtasks = [SubtaskRecord(id: SubtaskID("stale-child"), title: "Removed", orderKey: 1)]
        let canonical = try facade.workspaceTask(from: detail.result, keeping: stale, detail: true, at: date)
        #expect(canonical.title == "Keep my draft")
        #expect(canonical.subtasks.isEmpty)
        #expect(ShownTask(canonical).childrenKnown)
        let summary = try facade.workspaceTask(from: detail.result, keeping: stale, detail: false, at: date)
        #expect(summary.title == "Keep my draft")
        #expect(summary.subtasks.isEmpty)
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
        let canonicalTask = TaskID("task_00000000-0000-4000-8000-000000000033")
        let canonicalTag = TagID("tag_00000000-0000-4000-8000-000000000034")
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
        #expect(state.tasks[TaskID("task_" + task.rawValue)]?.tagIDs == [TagID("tag_" + second.rawValue)])
        try await runtime.close()
    }
}


extension RustWorkspaceBridgeTests {
    @Test("026-FR-025: an existing source formulation stays verbatim while a new formulation is explicitly minted")
    func existingFormulationIdentity() throws {
        let bare = "00000000-0000-4000-8000-000000000091"
        let task = TaskID("task_existing")
        var record = Fixture.task(task)
        record.formulation = FormulationClock(id: FormulationID(bare), startedAt: date)
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        let encoded = try facade.workspaceCommand(.autoParkTask(.init(taskID: task, formulationID: FormulationID(bare))),
            commandID: UUID(), at: date, in: Fixture.state(tasks: [record]))
        #expect(try RustJSON.object(encoded.payload).string("formulation_id") == bare)
        let created = try facade.workspaceCommand(.createTask(.init(taskID: TaskID(UUID().uuidString.lowercased()),
            title: "A new wording", list: .next, newFormulationID: FormulationID(bare))), commandID: UUID(), at: date, in: .empty)
        #expect(try RustJSON.object(created.payload).string("new_formulation_id") == "form_" + bare)
    }

    @Test("026-FR-025: the canonical decision's public produced revision survives without a cached task")
    func decisionPublicGuard() throws {
        var root = URL(fileURLWithPath: #filePath)
        for _ in 0..<5 { root.deleteLastPathComponent() }
        let fixture = try RustJSON.object(Data(contentsOf: root.appendingPathComponent("rust/crates/bb-client/tests/fixtures/legacy-review-activation.json")))
        let decisions = try fixture.object("expected_read_set").object("decisions")
        let row = try #require(decisions.values.first as? WireObject)
        let id = try row.string("id")
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        var owned = GTDState.empty
        let request = RustWorkspaceRecordRequest(entityType: "review_decision", recordKey: [id])
        try facade.workspaceApplyRecords(from: RustJSON.data(["kind": "records", "value": [["entity_type": "review_decision", "value": row]]]),
            requests: [request], to: &owned, at: date)
        #expect(owned.tasks.isEmpty)
        #expect(owned.review.decisions[DecisionID(id)]?.taskAfter.serverRevision == Int(try row.string("task_revision_after")))
        let command = try facade.workspaceCommand(.undoDecision(DecisionID(id)), commandID: UUID(), at: date, in: owned)
        let guardRow = try #require(try RustJSON.array(command.preconditions).first as? WireObject)
        #expect(try guardRow.string("edit_revision") == row.string("task_revision_after"))
    }
}

extension RustWorkspaceBridgeTests {
    @Test("A batch refusal crosses the bridge with the exact original failing command ID")
    func exactBatchRefusal() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let first = try facade.workspaceCommand(.createProject(.init(projectID: .random(), name: "First")),
            commandID: UUID(), at: date, in: .empty)
        let second = try facade.workspaceCommand(.createProject(.init(projectID: .random(), name: "")),
            commandID: UUID(), at: date, in: .empty)
        guard case .refused(let refusal, let failedID) = try await runtime.execute([first, second], context: context()) else {
            Issue.record("The empty second name must reject the batch"); return
        }
        #expect(failedID == second.commandID)
        #expect(refusal.reason == "invalid_payload")
        let query = try facade.workspaceReadQuery("projects", filter: "active")
        let inputs = try facade.workspaceQueryInputs(at: date, zone: "UTC", reviewExposed: false)
        guard case .answered(let page) = try await runtime.query(query, inputs: inputs) else {
            Issue.record("The canonical bounded project page must answer"); return
        }
        #expect(try facade.workspaceProjects(from: page.result, keeping: .empty, at: date).isEmpty)
        try await runtime.close()
    }
}


extension RustWorkspaceBridgeTests {
    @Test("026-FR-025: native whole counts and scoped catalog requests do not derive totals from loaded rows")
    func nativeQueryMetadata() throws {
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        let page = RustWorkspacePage(projectionGeneration: "7", result: try RustJSON.data([
            "kind": "list_mode", "value": ["open_count": 230, "total_count": 255,
                "completed_count": 20, "cancelled_count": 5,
                "sections": [["id": "open", "title": NSNull(), "kind": ["type": "open"],
                              "items": [], "total_count": 230]], "next_cursor": "continuation"]
        ]), collectionNextCursor: "continuation")
        let decoded = try facade.workspaceList(from: page, keeping: .empty, at: date)
        #expect(decoded.list.sections.first?.tasks.isEmpty == true)
        #expect(decoded.list.sections.first?.totalCount == 230)
        #expect(decoded.list.openCount == 230)
        #expect(decoded.list.totalCount == 255)
        #expect(decoded.list.completedCount == 20)
        #expect(decoded.list.cancelledCount == 5)
        let scoped = try RustJSON.object(facade.workspaceListQuery(.list(.next), options: ListOptions(search: "cafe")))
        #expect(try scoped.object("options").string("search") == "cafe")
        let project = ProjectID("project_exact")
        let exact = try RustJSON.object(facade.workspaceProjectsQuery(projectID: project))
        #expect(try exact.string("kind") == "native_projects")
        #expect(try exact.string("filter") == "all")
        #expect(try exact.string("project_id") == project.rawValue)
        let top = try RustJSON.object(facade.workspaceTagsQuery(search: "home", sort: .openCount))
        #expect(try top.string("kind") == "native_tags")
        #expect(try top.string("sort") == "open_count")
        #expect(try top.string("search") == "home")
        let exactTasks = try RustJSON.object(facade.workspaceTaskViewsQuery([TaskID("task_exact")]))
        #expect(try exactTasks.string("kind") == "native_task_views")
        #expect(try exactTasks.strings("task_ids") == ["task_exact"])
    }

    @Test("026-FR-025: formulation metadata belongs only to its returned task and preserves unavailable facts")
    func nativeRowFormulation() throws {
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        let id = TaskID("task_row")
        let page = RustWorkspacePage(projectionGeneration: "7", result: try RustJSON.data([
            "kind": "task_list", "value": ["items": [["id": id.rawValue, "formulation_state": [
                "task_id": id.rawValue, "class": "none", "derived": NSNull(), "third_stall": false,
                "extension": NSNull(), "parked_after_days": NSNull(),
                "unavailable_local_facts": ["weekly_review_unavailable"]
            ]]]]
        ]))
        let facts = try #require(try facade.workspaceTaskFormulation(id, from: page))
        #expect(facts.classification == .none)
        #expect(facts.derived == nil)
        #expect(facts.unavailableLocalFacts == ["weekly_review_unavailable"])
        #expect(try facade.workspaceTaskFormulation(TaskID("task_elsewhere"), from: page) == nil)
        let explicit = RustWorkspacePage(projectionGeneration: "7", result: try RustJSON.data([
            "kind": "task_formulation", "value": ["task_id": id.rawValue, "class": "none",
                "derived": NSNull(), "third_stall": false, "extension": NSNull(), "parked_after_days": NSNull(),
                "unavailable_local_facts": ["weekly_review_unavailable"]]
        ]))
        #expect(try facade.workspaceTaskFormulation(id, from: explicit)?.classification == FormulationClass.none)
        #expect(throws: RustDomainError.self) { try facade.workspaceTaskFormulation(TaskID("task_elsewhere"), from: explicit) }

    }
}


extension RustWorkspaceBridgeTests {
    @Test("026-FR-025: keyed content facts decode scalar whole-project counts and exact lookup names")
    func nativeContentStampsDecode() throws {
        let facade = RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
        let task = TaskID("task_content"), project = ProjectID("project_content")
        let page = RustWorkspacePage(projectionGeneration: "9", result: try RustJSON.data([
            "kind": "review_content_stamps", "value": ["tasks": [["task_id": task.rawValue,
                "stamp": String(repeating: "a", count: 64), "record_keys": ["s:task_content", "c:original"],
                "primary_record_key": "s:task_content"]], "projects": [["project_id": project.rawValue,
                "signature": String(repeating: "b", count: 64), "record_keys": ["c:original-project"],
                "primary_record_key": "c:original-project", "counts_by_state": ["inbox": 0, "next": 0,
                    "waiting": 1, "someday": 2, "completed": 202, "cancelled": 3]]]]
        ]))
        let value = try facade.workspaceReviewContentStamps(from: page)
        #expect(value.generation == 9)
        #expect(value.tasks[task]?.recordKeys == ["s:task_content", "c:original"])
        #expect(value.projects[project]?.countsByState[.completed] == 202)
        #expect(value.projects[project]?.countsByState[.cancelled] == 3)
        let key = Data([0, 255, 7])
        let request = try RustJSON.object(facade.workspaceReviewContentStampsQuery(key: key, tasks: [task], projects: [project]))
        #expect(Data(base64Encoded: try request.string("key")) == key)
        #expect(throws: RustBridgeError.self) {
            try facade.workspaceReviewContentStampsQuery(key: key, tasks: Array(repeating: task, count: 201))
        }
    }
}
