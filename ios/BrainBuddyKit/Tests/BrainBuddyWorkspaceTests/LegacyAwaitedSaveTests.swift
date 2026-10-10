import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing
@testable import BrainBuddyWorkspace

@Suite("Legacy awaited saves", .serialized)
@MainActor
struct LegacyAwaitedSaveTests {
    @Test("A failed creation stages nothing; retry and reopen contain one task")
    func failedCreationRetry() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.failWrites(with: .io("Disk full"))
        do {
            _ = try await workspace.capture(CaptureDraft(text: "Keep entered text"), editorID: "scene:capture")
            Issue.record("Storage failure must refuse the save")
        } catch { #expect(error is WorkspaceError) }
        #expect(workspace.state.tasks.isEmpty)
        #expect(workspace.unpersisted.isEmpty)
        #expect(try await store.base.load()?.outbox.isEmpty != false)
        await store.failWrites(with: nil)
        let id = try await workspace.capture(CaptureDraft(text: "Keep entered text"), editorID: "scene:capture")
        let reopened = await loadedWorkspace(store: store)
        #expect(reopened.state.tasks.count == 1)
        #expect(reopened.task(id)?.title == "Keep entered text")
    }

    @Test("Validation rejects the whole durable batch without staging its first command")
    func batchRollback() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        do {
            try await workspace.apply([
                .createProject(.init(projectID: "project", name: "Project")),
                .transitionTask(.init(taskID: "missing", action: .complete))
            ], editorID: "scene:batch")
            Issue.record("The absent task must reject the batch")
        } catch { #expect(error as? GTDValidationError == .taskNotFound) }
        #expect(workspace.state.projects.isEmpty)
        #expect(workspace.unpersisted.isEmpty)
        #expect(await store.written.isEmpty)
    }

    @Test("An earlier failed optimistic write remains pending and blocks a new save")
    func earlierPendingFailure() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.failWrites(with: .io("Disk full"))
        let older = try workspace.capture(CaptureDraft(text: "Older"))
        await workspace.flush()
        do {
            _ = try await workspace.capture(CaptureDraft(text: "New"), editorID: "scene:capture")
            Issue.record("The earlier failed write must block this attempt")
        } catch { #expect(error is WorkspaceError) }
        #expect(workspace.state.tasks.count == 1)
        #expect(workspace.task(older) != nil)
        #expect(workspace.unpersisted.count == 1)
    }

    @Test("A held save owns the writer; a second submit is busy and later sync edits survive")
    func concurrentSave() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.holdWrites()
        let saving = Task { try await workspace.capture(CaptureDraft(text: "Awaited"), editorID: "scene:capture") }
        await store.waitForHeldWrite()
        #expect(workspace.state.tasks.isEmpty)
        do {
            _ = try await workspace.capture(CaptureDraft(text: "Awaited"), editorID: "scene:capture")
            Issue.record("The same editor cannot submit twice")
        } catch { #expect((error as? RustBridgeError)?.code == "STORE_BUSY") }
        let later = try workspace.capture(CaptureDraft(text: "Later sync"))
        await store.releaseWrites()
        let committed = try await saving.value
        await workspace.flush()
        let reopened = await loadedWorkspace(store: store)
        #expect(reopened.task(committed) != nil)
        #expect(reopened.task(later) != nil)
        #expect(reopened.state.tasks.count == 2)
    }

    @Test("Sign-out waits for the save and refuses to erase a newly committed unconfirmed task")
    func signOutWaits() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.holdWrites()
        let saving = Task { try await workspace.capture(CaptureDraft(text: "Committed"), editorID: "scene:capture") }
        await store.waitForHeldWrite()
        let removing = Task { try await workspace.signOut(discardUnsyncedChanges: true) }
        await Task.yield()
        await store.releaseWrites()
        let task = try await saving.value
        do { try await removing.value; Issue.record("The new task was never confirmed for removal") }
        catch { #expect(error as? WorkspaceError == .unsyncedChanges(count: 1)) }
        #expect(workspace.task(task) != nil)
        #expect(try await store.base.load() != nil)
    }
    @Test("The latest locked document is checked against the original rendered decision card")
    func latestDocumentAndShownFrame() async throws {
        let task = Fixture.serverTask("task", "Original")
        let store = ControlledStore(InMemoryDocumentStore(document: StoreDocument(base: Fixture.base([task]))))
        let workspace = await loadedWorkspace(store: store)
        workspace.accountlessReviewEnabled = true
        try await workspace.acknowledgeExplainer(editorID: "scene:explainer")
        let shown = workspace.shownTask(of: try #require(workspace.task(task.id)))
        await store.holdWrites()
        let saving = Task {
            try await workspace.decide(.waiting, on: task.id, waitingFor: "Quote", expectedTask: shown,
                editorID: "scene:decision")
        }
        await store.waitForHeldWrite()
        _ = try await store.base.update { $0.base.tasks[task.id]?.details = "Changed in another process" }
        await store.releaseWrites()
        do { _ = try await saving.value; Issue.record("A changed original card must be refused") }
        catch { #expect(error as? GTDValidationError == .formulationChanged) }
        #expect(workspace.unpersisted.isEmpty)
        let stored = try #require(try await store.base.load())
        #expect(stored.base.tasks[task.id]?.details == "Changed in another process")
        #expect(!stored.outbox.contains { if case .decideTask = $0.command { return true }; return false })
    }

    @Test("Cancellation after the store receives the transaction preserves the known saved result")
    func committedBoundary() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.holdWrites()
        let saving = Task { try await workspace.capture(CaptureDraft(text: "Saved"), editorID: "scene:capture") }
        await store.waitForHeldWrite()
        saving.cancel()
        await store.releaseWrites()
        let id = try await saving.value
        #expect(workspace.task(id)?.title == "Saved")
        let reopened = await loadedWorkspace(store: store)
        #expect(reopened.task(id)?.title == "Saved")
    }

}
