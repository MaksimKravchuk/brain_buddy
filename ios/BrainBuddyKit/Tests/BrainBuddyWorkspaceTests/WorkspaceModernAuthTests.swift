import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing
@testable import BrainBuddyWorkspace

@MainActor
@Suite("022 Workspace native authentication")
struct WorkspaceModernAuthTests {
    @Test("023-FR-024: Modern sign-in flushes capture before linking and retains the existing merge")
    func flushAndFinalize() async throws {
        let server = FakeBrainBuddyServer()
        let id = server.addAccount(email: "ada@example.com", password: "a long secure password")
        let store = InMemoryDocumentStore()
        let tokens = InMemorySessionTokenStore()
        let engine = SyncEngine(store: store, tokenStore: tokens, transport: server.makeTransport())
        let workspace = await loadedWorkspace(store: store, sync: engine)
        let localID = try workspace.capture(CaptureDraft(text: "Keep this local task"))
        let attempt = try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        #expect(try await store.load()?.outbox.count == 1)
        let outcome = try await workspace.completeSignIn(attempt, credential: .password(email: "ada@example.com", password: "a long secure password"))
        guard case .signedIn = outcome else { Issue.record("Expected signed in"); return }
        #expect(workspace.account?.id == id)
        #expect(workspace.task(localID) != nil)
        #expect(workspace.pendingChangeCount == 0)
        #expect(server.snapshot(email: "ada@example.com").task(titled: "Keep this local task") != nil)
    }

    @Test("Older sync services fail closed without invoking their legacy password sign-in")
    func protocolDefaults() async throws {
        let sync = FakeSyncService()
        let workspace = await loadedWorkspace(sync: sync)
        await #expect(throws: WorkspaceError.self) {
            try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        }
        #expect(await sync.calls.isEmpty)
        #expect(workspace.account == nil)
    }

    @Test("023-FR-024: Modern sign-in preserves account-less Weekly Review parks on the server")
    func preservesLocalReviewParks() async throws {
        let server = FakeBrainBuddyServer()
        _ = server.addAccount(email: "ada@example.com", password: "a long secure password")
        let store = InMemoryDocumentStore()
        let engine = SyncEngine(store: store, tokenStore: InMemorySessionTokenStore(), transport: server.makeTransport())
        let (workspace, taskID) = try await parkedWorkspace(store: store, sync: engine)
        let attempt = try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let outcome = try await workspace.completeSignIn(attempt, credential: .password(email: "ada@example.com", password: "a long secure password"))
        guard case .signedIn = outcome else { Issue.record("Expected signed in"); return }
        #expect(workspace.task(taskID)?.state == .someday)
        #expect(workspace.issues.isEmpty)
        #expect(server.snapshot(email: "ada@example.com").task(titled: "Keep this parked task")?.state == .someday)
    }

    @Test("023-FR-024: Failed local Review preparation prevents credential submission and retains the outbox")
    func reviewPreparationFailureStopsSignIn() async throws {
        let server = FakeBrainBuddyServer()
        _ = server.addAccount(email: "ada@example.com", password: "a long secure password")
        let transport = server.makeTransport()
        let store = ControlledStore()
        let engine = SyncEngine(store: store, tokenStore: InMemorySessionTokenStore(), transport: transport)
        let (workspace, taskID) = try await parkedWorkspace(store: store, sync: engine)
        let attempt = try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let before = try #require(try await store.load())
        transport.clearLog()
        await store.failWrites(with: .io("disk full"))
        await #expect(throws: WorkspaceError.self) {
            try await workspace.completeSignIn(attempt, credential: .password(email: "ada@example.com", password: "a long secure password"))
        }
        #expect(transport.requests.isEmpty, "Preparation fails before credentials or tasks leave the device")
        #expect(workspace.account == nil)
        await store.failWrites(with: nil)
        #expect(try await store.load()?.outbox == before.outbox)
        #expect(workspace.task(taskID)?.state == .someday)
        #expect(workspace.state == workspace.replayedState)
    }

    @Test("023-FR-024: Cancelling while local Review preparation waits prevents credential submission")
    func cancellationDuringReviewPreparation() async throws {
        let server = FakeBrainBuddyServer()
        _ = server.addAccount(email: "ada@example.com", password: "a long secure password")
        let transport = server.makeTransport()
        let store = ControlledStore()
        let engine = SyncEngine(store: store, tokenStore: InMemorySessionTokenStore(), transport: transport)
        let (workspace, taskID) = try await parkedWorkspace(store: store, sync: engine)
        let attempt = try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        transport.clearLog()
        await store.holdWrites()
        let completion = Task {
            try await workspace.completeSignIn(attempt, credential: .password(email: "ada@example.com", password: "a long secure password"))
        }
        await store.waitForHeldWrite()
        await workspace.cancelSignIn(attempt)
        await store.releaseWrites()
        await #expect(throws: WorkspaceError.self) { try await completion.value }
        #expect(transport.requests.isEmpty)
        #expect(workspace.account == nil)
        #expect(workspace.task(taskID)?.state == .someday)
    }

    private func parkedWorkspace(store: any DocumentStore, sync: any SyncService) async throws -> (Workspace, TaskID) {
        let clock = TestClock()
        let workspace = await loadedWorkspace(store: store, sync: sync, clock: clock)
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { TimeZone(identifier: "Europe/Berlin")! }
        try workspace.acknowledgeExplainer()
        let taskID = try workspace.capture(CaptureDraft(text: "Keep this parked task", list: .next))
        clock.advance(by: 20 * 86_400 + 3_600)
        #expect(workspace.applyDueAutoParks() == 0)
        clock.advance(by: 86_400)
        #expect(workspace.applyDueAutoParks() == 1)
        await workspace.flush()
        return (workspace, taskID)
    }
}
