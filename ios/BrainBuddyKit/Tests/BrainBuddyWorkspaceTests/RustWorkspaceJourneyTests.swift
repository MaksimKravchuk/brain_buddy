import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

@Suite("Selected runtime Workspace journey (026-FR-001, 026-FR-025, 026-FR-026)")
struct RustWorkspaceJourneyTests {
    @Test("026-FR-001: capture, validation and edits use the durable runtime without reading or writing the retired document")
    @MainActor
    func oneAuthority() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let retired = ControlledStore()
        let legacySync = FakeSyncService(store: retired)
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let workspace = Workspace(store: retired, sync: legacySync,
            rust: RustWorkspaceSelection(runtime: runtime, facade: facade),
            now: { Date(timeIntervalSince1970: 1_790_000_000) })
        await workspace.load()
        #expect(workspace.isRustBound)
        let id = try await workspace.capture(CaptureDraft(text: "Canonical capture"), editorID: "scene:journey:capture")
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Canonical capture"])
        #expect(workspace.counts().inbox == 1)
        try await workspace.updateTask(id, TaskChanges(title: .set("Durably edited")), editorID: "scene:journey:edit")
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.task(id)?.title == "Durably edited")
        do {
            _ = try await workspace.capture(CaptureDraft(text: "Waiting draft", list: .waiting),
                editorID: "scene:journey:invalid")
            Issue.record("Waiting requires the same validation as the legacy UI")
        } catch {
            #expect(Workspace.saveMessage(for: error) == GTDValidationError.waitingForRequired.message)
        }
        let synchronous: (TaskID, TaskChanges) throws(GTDValidationError) -> Void = workspace.updateTask
        #expect(throws: GTDValidationError.asynchronousSaveRequired) {
            try synchronous(id, TaskChanges(title: .set("Refused synchronous edit")))
        }
        await workspace.flush()
        await workspace.syncNow()
        #expect(await retired.loadCount == 0)
        #expect(await retired.written.isEmpty)
        #expect(await legacySync.calls.isEmpty)
        #expect(workspace.fullReplayCount == 0)
        #expect(workspace.runtimeTransportUnavailable)
        await workspace.closeRuntime()
    }
}


extension RustWorkspaceJourneyTests {
    @Test("026-FR-025: a proved alias with a different UUID suffix cannot adopt or edit the colliding source task")
    @MainActor
    func provedAliasCollision() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let instant = Date(timeIntervalSince1970: 1_790_000_000)
        let sourceID = TaskID("00000000-0000-4000-8000-000000000031")
        let collidingID = TaskID("00000000-0000-4000-8000-000000000033")
        let canonical = "task_" + collidingID.rawValue
        let otherCanonical = "task_00000000-0000-4000-8000-000000000034"
        var source = GTDState.empty
        source.tasks[sourceID] = TaskRecord(id: sourceID, serverID: canonical, serverRevision: 3,
            title: "Proved source", state: .inbox, orderKey: 1, createdAt: instant, updatedAt: instant)
        source.tasks[collidingID] = TaskRecord(id: collidingID, serverID: otherCanonical, serverRevision: 4,
            title: "Keep this separate", state: .inbox, orderKey: 2, createdAt: instant, updatedAt: instant)
        let json = directory.appendingPathComponent("document.json")
        let database = directory.appendingPathComponent("store.sqlite3")
        try StoreDocumentCoding.makeEncoder().encode(StoreDocument(base: source)).write(to: json)
        let bridge = try RustBridgeRuntime()
        _ = try await bridge.importLegacyStore(.init(workspaceID: "local", databasePath: database.path,
            sourcePath: json.path, now: "2026-09-21T00:00:00Z"))
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: database)
        let retired = ControlledStore()
        let workspace = Workspace(store: retired, sync: nil, rust: RustWorkspaceSelection(runtime: runtime,
            facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))), now: { instant })
        await workspace.load()
        await workspace.prepareList(.list(.inbox))
        #expect(Set(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map { $0.id.rawValue }) == [canonical, otherCanonical])
        await workspace.refreshTaskDetails(sourceID)
        #expect(workspace.task(sourceID)?.id.rawValue == canonical)
        try await workspace.updateTask(sourceID, TaskChanges(title: .set("Only the proved task")), editorID: "scene:alias:edit")
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.task(TaskID(canonical))?.title == "Only the proved task")
        #expect(workspace.task(TaskID(otherCanonical))?.title == "Keep this separate")
        #expect(await retired.loadCount == 0)
        #expect(await retired.written.isEmpty)
        await workspace.closeRuntime()
    }
}


extension RustWorkspaceJourneyTests {
    @Test("A rolled-back batch uses the exact earlier holder's authored casing in its validation message")
    @MainActor
    func duplicateBatchPresentation() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let workspace = Workspace(store: ControlledStore(), sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))))
        await workspace.load()
        do {
            try await workspace.apply([
                .createProject(.init(projectID: .random(), name: "First Case")),
                .createProject(.init(projectID: .random(), name: "first case"))
            ], editorID: "scene:batch:projects")
            Issue.record("The duplicate name must reject the whole batch")
        } catch {
            #expect(Workspace.saveMessage(for: error) == GTDValidationError.duplicateProjectName("First Case").message)
        }
        await workspace.prepareProjects()
        #expect(workspace.projects().isEmpty)
        await workspace.closeRuntime()
    }
}
