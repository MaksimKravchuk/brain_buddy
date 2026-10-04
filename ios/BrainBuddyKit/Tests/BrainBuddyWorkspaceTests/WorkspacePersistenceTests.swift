import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// How applied commands reach the store: in order, compacted, retried after a
/// failure, and how writes by other processes are picked up.
@MainActor
@Suite struct WorkspacePersistenceTests {
    // MARK: Ordering

    @Test func manyRapidCommandsArePersistedInOrder() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)

        var ids: [TaskID] = []
        for index in 0..<120 { ids.append(try workspace.capture(CaptureDraft(text: "Task \(index)"))) }
        for id in ids.prefix(30) { try workspace.completeTask(id) }
        await workspace.flush()

        let stored = try #require(try await store.load())
        #expect(createdTaskIDs(in: stored.outbox) == ids)
        #expect(stored.outbox.count == 150)
        #expect(stored.outbox.suffix(30).map(\.command) == ids.prefix(30).map { .transitionTask(.init(taskID: $0, action: .complete)) })
        #expect(OutboxReplayer.replay(stored.outbox, onto: stored.base).state == workspace.state)
        #expect(workspace.pendingChangeCount == 150)
    }

    @Test func writesNeverOverlapOrReorderAndQueuedChangesAreBatched() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.holdWrites()

        let first = try workspace.capture(CaptureDraft(text: "First"))
        await store.waitForHeldWrite()
        // While the first write waits for the lock, more changes arrive.
        var later: [TaskID] = []
        for index in 0..<25 { later.append(try workspace.capture(CaptureDraft(text: "Later \(index)"))) }
        try workspace.completeTask(first)
        #expect(workspace.unpersisted.count == 27)
        await store.releaseWrites()
        await workspace.flush()

        let written = await store.written
        // The first write carried only the first capture; the rest went in one batch after it.
        #expect(written.count == 2)
        #expect(written.map(\.generation) == [1, 2])
        #expect(createdTaskIDs(in: written[0].outbox) == [first])
        #expect(createdTaskIDs(in: written[1].outbox) == [first] + later)
        #expect(written[1].outbox.last?.command == .transitionTask(.init(taskID: first, action: .complete)))
        #expect(workspace.unpersisted.isEmpty)
        #expect(workspace.state == workspace.replayedState)
    }

    @Test func flushWaitsForEveryAppliedChange() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)
        try workspace.capture(CaptureDraft(text: "One"))
        try workspace.capture(CaptureDraft(text: "Two"))

        #expect(workspace.unpersisted.count == 2)
        await workspace.flush()

        #expect(try await store.load()?.outbox.count == 2)
        #expect(workspace.unpersisted.isEmpty)
        #expect(workspace.document == (try await store.load()))
        // Nothing to do: flushing again writes nothing.
        await workspace.flush()
        #expect(try await store.generation() == 1)
    }

    // MARK: Compaction

    @Test func anEditOfAnUnsentTaskFoldsIntoItsCreation() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)
        let id = try workspace.capture(CaptureDraft(text: "Call Ana"))
        await workspace.flush()

        try workspace.updateTask(id, TaskChanges(title: .set("Call Ana back"), priority: .set(.high)))
        #expect(workspace.pendingChangeCount == 2)
        try workspace.moveTask(id, to: .next)
        await workspace.flush()

        let outbox = try #require(try await store.load()).outbox
        #expect(outbox.count == 1)
        guard case .createTask(let create)? = outbox.first?.command else {
            Issue.record("Expected one createTask, got \(outbox.map(\.command))")
            return
        }
        #expect(create.title == "Call Ana back")
        #expect(create.priority == .high)
        #expect(create.list == .next)
        #expect(workspace.pendingChangeCount == 1)
        #expect(workspace.task(id)?.title == "Call Ana back")
        #expect(workspace.task(id)?.state == .next)
    }

    @Test func aSentOperationIsNeverRewritten() async throws {
        let id: TaskID = "task-sent"
        let sent = PendingOperation(
            command: .createTask(.init(taskID: id, title: "Call Ana", list: .inbox)), issuedAt: Fixture.epoch,
            attempts: 1, firstAttemptAt: Fixture.epoch
        )
        let store = InMemoryDocumentStore(document: StoreDocument(generation: 3, outbox: [sent]))
        let workspace = await loadedWorkspace(store: store)

        try workspace.updateTask(id, TaskChanges(title: .set("Call Ana back")))
        await workspace.flush()

        let outbox = try #require(try await store.load()).outbox
        #expect(outbox.count == 2)
        #expect(outbox.first == sent)
    }

    // MARK: Failures

    @Test func aFailedWriteKeepsTheChangesAndRetriesOnFlush() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        let persisted = CallCounter()
        workspace.didPersist = { persisted.record() }
        await store.failWrites(with: .io("No space left on device"))

        let id = try workspace.capture(CaptureDraft(text: "Keep me"))
        await workspace.flush()

        #expect(workspace.storageError == DocumentStoreError.io("No space left on device").message)
        #expect(workspace.unpersisted.count == 1)
        #expect(workspace.pendingChangeCount == 1)
        #expect(workspace.task(id)?.title == "Keep me")
        #expect(persisted.count == 0)

        await store.failWrites(with: nil)
        await workspace.flush()

        #expect(workspace.storageError == nil)
        #expect(workspace.unpersisted.isEmpty)
        #expect(createdTaskIDs(in: try #require(try await store.base.load()).outbox) == [id])
        #expect(persisted.count == 1)
    }

    @Test func aFailedWriteIsRetriedWithTheNextChangeInOrder() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.failWrites(with: .io("Disk busy"))
        let first = try workspace.capture(CaptureDraft(text: "First"))
        await workspace.flush()
        #expect(workspace.storageError != nil)

        await store.failWrites(with: nil)
        let second = try workspace.capture(CaptureDraft(text: "Second"))
        await workspace.flush()

        #expect(createdTaskIDs(in: try #require(try await store.base.load()).outbox) == [first, second])
        #expect(workspace.storageError == nil)
    }

    @Test func storageErrorsOtherThanTheStoresHaveAGenericMessage() {
        struct Unexpected: Error {}
        #expect(Workspace.storageMessage(for: Unexpected()).contains("couldn't be saved on this device"))
        #expect(WorkspaceError.storage("Disk full").message == "Disk full")
    }

    // MARK: didPersist and pending counts

    @Test func didPersistRunsAfterEachSuccessfulWrite() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)
        let persisted = CallCounter()
        workspace.didPersist = { persisted.record() }

        try workspace.capture(CaptureDraft(text: "One"))
        await workspace.flush()
        #expect(persisted.count == 1)

        try workspace.capture(CaptureDraft(text: "Two"))
        try workspace.capture(CaptureDraft(text: "Three"))
        await workspace.flush()
        #expect(persisted.count == 2)
        #expect(try await store.generation() == 2)
    }

    @Test func pendingChangeCountCountsQueuedAndStoredOperations() async throws {
        let store = InMemoryDocumentStore()
        let workspace = await loadedWorkspace(store: store)
        #expect(workspace.pendingChangeCount == 0)

        let id = try workspace.capture(CaptureDraft(text: "Plan @Offsite"))
        #expect(workspace.pendingChangeCount == 2)
        await workspace.flush()
        #expect(workspace.pendingChangeCount == 2)

        try workspace.completeTask(id)
        #expect(workspace.pendingChangeCount == 3)
        await workspace.flush()
        #expect(workspace.pendingChangeCount == 3)
    }

    // MARK: Consistency

    @Test func stateAlwaysEqualsTheReplayOfDocumentAndQueuedChanges() async throws {
        let workspace = await loadedWorkspace()
        let task = try workspace.capture(CaptureDraft(text: "Draft agenda @Offsite #computer", list: .next))
        #expect(workspace.state == workspace.replayedState)

        let subtask = try workspace.addSubtask(to: task, title: "List sessions")
        try workspace.transitionSubtask(subtask, in: task, .complete)
        try workspace.addComment(to: task, body: "Keep Friday free.")
        #expect(workspace.state == workspace.replayedState)

        await workspace.flush()
        #expect(workspace.state == workspace.replayedState)

        let other = try workspace.capture(CaptureDraft(text: "Waiting on the venue", list: .waiting, waitingFor: "Harbour Hall"))
        try workspace.cancelTask(other)
        let tag = try workspace.createTag(name: "calls")
        try workspace.deleteTag(tag)
        #expect(workspace.state == workspace.replayedState)
        await workspace.flush()
        #expect(workspace.state == workspace.replayedState)
    }

    @Test func ownWritesSkipTheFullReplay() async throws {
        let workspace = await loadedWorkspace()
        let replays = workspace.fullReplayCount

        for index in 0..<10 { try workspace.capture(CaptureDraft(text: "Task \(index)")) }
        await workspace.flush()
        try workspace.capture(CaptureDraft(text: "One more"))
        await workspace.flush()

        #expect(workspace.fullReplayCount == replays)
    }

    // MARK: Other processes

    @Test func reloadPicksUpAWriteFromAnotherProcess() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("BrainBuddy/store.json")
        let app = await loadedWorkspace(store: FileDocumentStore(fileURL: url))
        let appTask = try app.capture(CaptureDraft(text: "From the app"))
        await app.flush()

        // A widget or App Intent: another store instance on the same file.
        let intent = await loadedWorkspace(store: FileDocumentStore(fileURL: url), ids: IDSequence(namespace: 2))
        #expect(intent.task(appTask) != nil)
        let intentTask = try intent.capture(CaptureDraft(text: "From Siri #calls"))
        await intent.flush()

        let replays = app.fullReplayCount
        await app.reloadIfChangedExternally()

        #expect(app.task(intentTask)?.title == "From Siri")
        #expect(app.task(appTask) != nil)
        #expect(app.state == intent.state)
        #expect(app.pendingChangeCount == 3)
        #expect(app.fullReplayCount == replays + 1)
    }

    @Test func reloadKeepsChangesNotWrittenYet() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let appStore = ControlledStore(FileDocumentStore(fileURL: url))
        let app = await loadedWorkspace(store: appStore)
        let intent = await loadedWorkspace(store: FileDocumentStore(fileURL: url), ids: IDSequence(namespace: 2))
        let intentTask = try intent.capture(CaptureDraft(text: "From the widget"))
        await intent.flush()

        await appStore.failWrites(with: .io("locked"))
        let appTask = try app.capture(CaptureDraft(text: "Typed in the app"))
        await app.flush()
        #expect(app.unpersisted.count == 1)
        await app.reloadIfChangedExternally()

        #expect(app.task(intentTask) != nil)
        #expect(app.task(appTask) != nil)
        #expect(app.state == app.replayedState)

        await appStore.failWrites(with: nil)
        await app.flush()
        let reader = await loadedWorkspace(store: FileDocumentStore(fileURL: url))
        #expect(Set(reader.state.tasks.keys) == [intentTask, appTask])
    }

    @Test func reloadDoesNothingWhenNobodyElseWrote() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        try workspace.capture(CaptureDraft(text: "Mine"))
        await workspace.flush()
        let loads = await store.loadCount

        await workspace.reloadIfChangedExternally()

        #expect(await store.loadCount == loads)
    }

    @Test func aReadOvertakenByOurOwnWriteIsNotAdopted() async throws {
        let store = ControlledStore()
        let app = await loadedWorkspace(store: store)
        let widget = await loadedWorkspace(store: store.base, ids: IDSequence(namespace: 2))
        let widgetTask = try widget.capture(CaptureDraft(text: "From the widget"))
        await widget.flush()

        // The app starts reading the widget's write (generation 1)…
        await store.holdLoads()
        let reload = Task { await app.reloadIfChangedExternally() }
        await store.waitForLoads(2)
        // …and writes its own change (generation 2) before that read returns.
        let appTask = try app.capture(CaptureDraft(text: "From the app"))
        await app.flush()
        #expect(app.document.generation == 2)
        await store.releaseLoads()
        await reload.value

        #expect(app.document.generation == 2)
        #expect(app.task(appTask) != nil)
        #expect(app.task(widgetTask) != nil)
        #expect(app.state == app.replayedState)
    }

    @Test func aWriteByAnotherProcessDuringOurWriteIsReplayed() async throws {
        let store = ControlledStore()
        let app = await loadedWorkspace(store: store)
        let other = await loadedWorkspace(store: store.base, ids: IDSequence(namespace: 2))
        await store.holdWrites()

        let appTask = try app.capture(CaptureDraft(text: "Mine"))
        await store.waitForHeldWrite()
        let otherTask = try other.capture(CaptureDraft(text: "Theirs"))
        await other.flush()
        await store.releaseWrites()
        await app.flush()

        // The generation skipped one, so the app replayed the whole document.
        #expect(app.document.generation == 2)
        #expect(app.task(otherTask) != nil)
        #expect(app.task(appTask) != nil)
        #expect(app.state == app.replayedState)
    }
}
