import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Sessions through the real stack: what stays on the device, and what the
/// server still accepts, after signing out, starting fresh or reinstalling.
@MainActor
@Suite("Workspace end to end: sessions")
struct WorkspaceSessionEndToEndTests {
    @Test("Signing out offline removes the session here at once and ends it on the server once back online")
    func offlineSignOutEndsTheSessionLater() async throws {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        #expect(world.server.liveSessionCount(email: World.email) == 1)

        await phone.networkChanged(isAvailable: false)
        try await phone.workspace.signOut(discardUnsyncedChanges: false)
        await phone.settle()
        #expect(phone.workspace.account == nil)
        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try phone.tokens.pendingLogouts().count == 1)
        #expect(world.server.liveSessionCount(email: World.email) == 1, "the server hasn't heard yet")

        await phone.networkChanged(isAvailable: true)
        #expect(world.server.liveSessionCount(email: World.email) == 0)
        #expect(try phone.tokens.pendingLogouts().isEmpty)
        #expect(phone.workspace.syncStatus == .localOnly)
    }

    @Test("Signing in during the deletion grace period cancels the deletion and the app is told")
    func signInCancellingDeletionIsReported() async throws {
        let world = World()
        world.server.scheduleDeletion(email: World.email)
        let phone = await world.device()

        try await phone.signIn()
        #expect(phone.workspace.signInCancelledAccountDeletion)
        phone.workspace.acknowledgeAccountDeletionNotice()
        #expect(!phone.workspace.signInCancelledAccountDeletion)
        #expect(phone.workspace.syncStatus == .idle(lastSyncedAt: world.clock.now()))
    }

    @Test("Starting fresh after an unreadable document ends its account's session; signing out later removes the copy")
    func startingFreshEndsTheSetAsideAccountsSession() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("BrainBuddy/store.json")
        let world = World()
        let phone = await world.device(store: FileDocumentStore(fileURL: url))
        try await phone.signIn()
        _ = try phone.workspace.capture(CaptureDraft(text: "Plan the trip"))
        await phone.workspace.syncNow()

        // A newer app version rewrote the file, then the person went back.
        var json = try #require(try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
        json["version"] = 99
        try JSONSerialization.data(withJSONObject: json).write(to: url)
        await phone.relaunch()
        #expect(phone.workspace.loadError != nil)
        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) != nil, "kept while the document can't be read")

        let aside = try #require(await phone.workspace.resetUnreadableStore())
        await phone.settle()
        #expect(phone.workspace.account == nil)
        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(world.server.liveSessionCount(email: World.email) == 0)
        #expect(FileManager.default.fileExists(atPath: aside.path))

        // Signing in and out again removes the set-aside copy with the rest.
        try await phone.signIn()
        try await phone.workspace.signOut(discardUnsyncedChanges: false)
        #expect(!FileManager.default.fileExists(atPath: aside.path))
    }

    @Test("Opening the app with no account forgets a session a previous install left in the Keychain")
    func launchWithoutAccountForgetsStaleSession() async throws {
        let world = World()
        let phone = await world.device()
        try phone.tokens.setToken("left-by-an-earlier-install", for: FakeBrainBuddyServer.baseURL)

        await phone.relaunch()
        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(phone.transport.requests.isEmpty)
    }
}
