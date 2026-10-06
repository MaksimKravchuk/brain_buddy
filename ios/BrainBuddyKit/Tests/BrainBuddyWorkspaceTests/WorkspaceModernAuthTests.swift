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
    @Test("022-FR-024: Modern sign-in flushes capture before linking and retains the existing merge")
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
}
