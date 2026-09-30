import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// `load()`, what it makes of each kind of stored file, and recovery.
@MainActor
@Suite struct WorkspaceLoadTests {
    @Test func aMissingDocumentIsAnEmptyLocalWorkspaceAndNoFileIsCreated() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let folder = directory.appendingPathComponent("BrainBuddy", isDirectory: true)
        let workspace = makeWorkspace(store: FileDocumentStore(fileURL: folder.appendingPathComponent("store.json")))
        #expect(!workspace.isLoaded)

        await workspace.load()

        #expect(workspace.isLoaded)
        #expect(workspace.loadError == nil)
        #expect(workspace.state == .empty)
        #expect(workspace.account == nil)
        #expect(workspace.syncStatus == .localOnly)
        #expect(workspace.pendingChangeCount == 0)
        // Widgets load too; they must never create the file.
        #expect(!FileManager.default.fileExists(atPath: folder.path))
    }

    @Test func aStoredDocumentIsShownAsBasePlusReplayedOutbox() async throws {
        let issue = Fixture.issue("This tag no longer exists.")
        let document = StoreDocument(
            generation: 12,
            base: Fixture.base([Fixture.serverTask("server-1", "Plan the offsite")]),
            outbox: [
                PendingOperation(
                    command: .createTask(.init(taskID: "local-1", title: "Call Ana", list: .inbox)),
                    issuedAt: Fixture.epoch
                ),
                PendingOperation(
                    command: .transitionTask(.init(taskID: "server-1", action: .complete)), issuedAt: Fixture.epoch
                ),
            ],
            issues: [issue], account: Fixture.account, sync: SyncMetadata(lastPullAt: Fixture.epoch)
        )
        // Without sync, as in a widget.
        let workspace = await loadedWorkspace(store: InMemoryDocumentStore(document: document))

        #expect(workspace.task("local-1")?.title == "Call Ana")
        #expect(workspace.task("server-1")?.state == .completed)
        #expect(workspace.state == OutboxReplayer.replay(document.outbox, onto: document.base).state)
        #expect(workspace.pendingChangeCount == 2)
        #expect(workspace.issues == [issue])
        #expect(workspace.account == Fixture.account)
        #expect(workspace.syncStatus == .idle(lastSyncedAt: Fixture.epoch))
        #expect(workspace.document == document)
    }

    @Test func anUnreadableDocumentSetsLoadErrorAndIsNeverOverwritten() async throws {
        let store = InMemoryDocumentStore(contents: Fixture.garbage)
        let workspace = await loadedWorkspace(store: store)

        #expect(workspace.isLoaded)
        #expect(workspace.loadError == DocumentStoreError.unreadable("any").message)
        #expect(workspace.state == .empty)

        // A write is refused by the store; the change stays in memory.
        try workspace.capture(CaptureDraft(text: "Typed anyway"))
        await workspace.flush()
        #expect(workspace.storageError == DocumentStoreError.unreadable("any").message)
        #expect(workspace.unpersisted.count == 1)
        await #expect(throws: DocumentStoreError.self) { try await store.load() }
    }

    @Test func aDocumentFromANewerVersionAsksForAnUpdate() async {
        let workspace = await loadedWorkspace(store: InMemoryDocumentStore(contents: Fixture.newerVersion))

        #expect(workspace.isLoaded)
        #expect(workspace.loadError == DocumentStoreError.unsupportedVersion(99).message)
    }

    @Test func resetUnreadableStoreSetsTheOldDocumentAsideAndStartsFresh() async throws {
        let store = InMemoryDocumentStore(contents: Fixture.garbage)
        let workspace = await loadedWorkspace(store: store)
        #expect(workspace.loadError != nil)

        let quarantined = await workspace.resetUnreadableStore()

        #expect(quarantined != nil)
        #expect(await store.quarantinedContents == [Fixture.garbage])
        #expect(workspace.loadError == nil)
        #expect(workspace.isLoaded)
        #expect(workspace.state == .empty)

        let id = try workspace.capture(CaptureDraft(text: "A fresh start"))
        await workspace.flush()
        #expect(workspace.storageError == nil)
        #expect(createdTaskIDs(in: try #require(try await store.load()).outbox) == [id])
    }

    @Test func resetUnreadableStoreAlsoSetsANewerVersionAside() async {
        let store = InMemoryDocumentStore(contents: Fixture.newerVersion)
        let workspace = await loadedWorkspace(store: store)

        await workspace.resetUnreadableStore()

        #expect(workspace.loadError == nil)
        #expect(await store.quarantinedContents == [Fixture.newerVersion])
    }

    @Test func resetUnreadableStoreLogsOutTheAccountOfTheDocumentSetAside() async throws {
        var json = try #require(
            try JSONSerialization.jsonObject(with: StoreDocumentCoding.encode(WorkspaceSyncTests.linkedDocument()))
                as? [String: Any]
        )
        json["version"] = 99
        let store = InMemoryDocumentStore(contents: try JSONSerialization.data(withJSONObject: json))
        let sync = FakeSyncService(store: store)
        let workspace = await loadedWorkspace(store: store, sync: sync)
        #expect(workspace.loadError != nil)
        #expect(await sync.discardedSessions.isEmpty, "an unreadable document may belong to an account")

        #expect(await workspace.resetUnreadableStore() != nil)
        #expect(await sync.discardedSessions == [Fixture.account, nil], "its session, then any stale one")
        #expect(workspace.loadError == nil)
        #expect(workspace.account == nil)
        #expect(await sync.calls.isEmpty)
    }

    @Test func resetUnreadableStoreLeavesAReadableDocumentAlone() async throws {
        let store = InMemoryDocumentStore(document: StoreDocument(generation: 2, outbox: [
            PendingOperation(command: .createTag(.init(tagID: "t", name: "home")), issuedAt: Fixture.epoch)
        ]))
        let workspace = await loadedWorkspace(store: store)

        #expect(await workspace.resetUnreadableStore() == nil)
        #expect(workspace.tag("t")?.name == "home")
    }

    @Test func reloadRetriesALoadThatFailed() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        try Fixture.garbage.write(to: url)
        let workspace = await loadedWorkspace(store: FileDocumentStore(fileURL: url))
        #expect(workspace.loadError != nil)

        // Something repaired the file (for example the device was unlocked).
        let document = StoreDocument(generation: 4, outbox: [
            PendingOperation(command: .createTag(.init(tagID: "t", name: "calls")), issuedAt: Fixture.epoch)
        ])
        try StoreDocumentCoding.encode(document).write(to: url)
        await workspace.reloadIfChangedExternally()

        #expect(workspace.loadError == nil)
        #expect(workspace.tag("t")?.name == "calls")
    }

    @Test func loadingAgainKeepsChangesNotWrittenYet() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        await store.failWrites(with: .io("busy"))
        let id = try workspace.capture(CaptureDraft(text: "Unsaved"))
        await workspace.flush()

        await workspace.load()

        #expect(workspace.task(id) != nil)
        #expect(workspace.pendingChangeCount == 1)
    }
}
