import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddySync

/// Sessions: switching accounts, what a sign-in reports, and logging out
/// when the server can't be told right away.
@Suite("SyncEngine: sessions and accounts")
struct SyncEngineSessionTests {
    static let bob = (email: "bob@example.com", password: "hunter2 hunter2")
    static let refusal =
        "Sign out first to use another account. Changes from the other account are still waiting on this iPhone."

    private func signInAsBob(_ device: Device) async throws(SignInFailure) -> LinkedAccount {
        try await device.engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: Self.bob.email, password: Self.bob.password
        )
    }

    // MARK: Switching accounts

    @Test("Another account can't sign in while the linked one's changes wait; they go to their own account later")
    func refusesAnotherAccountWhileChangesWait() async throws {
        let harness = SyncHarness()
        harness.server.addAccount(email: Self.bob.email, password: Self.bob.password, displayName: "Bob")
        let device = await harness.device()
        let ada = try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "secret", title: "Ada's private task", list: .inbox)))
        device.transport.inject(.status(401))
        #expect(await device.sync() == .needsSignIn)

        await #expect(throws: SignInFailure(message: Self.refusal)) { try await signInAsBob(device) }
        #expect(harness.server.snapshot(email: Self.bob.email).tasks.isEmpty, "nothing reached Bob's account")
        #expect(harness.server.liveSessionCount(email: Self.bob.email) == 0, "the session it created was ended")
        let document = try await device.document()
        #expect(document.account == ada)
        #expect(document.outbox.count == 1)
        #expect(await device.status == .needsSignIn)
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)

        // Ada signs in again: her change goes to her account.
        try await device.signIn()
        #expect(harness.snapshot.task(titled: "Ada's private task") != nil)
        #expect(harness.server.snapshot(email: Self.bob.email).tasks.isEmpty)
        #expect(try await device.document().outbox.isEmpty)
    }

    @Test("Sync issues of the linked account also keep another account from signing in")
    func refusesAnotherAccountWhileIssuesWait() async throws {
        let harness = SyncHarness()
        harness.server.addAccount(email: Self.bob.email, password: Self.bob.password)
        let device = await harness.device()
        try await device.signIn()
        let date = harness.clock.now()
        _ = try await device.store.update { doc in
            doc.issues.append(SyncIssue(command: .deleteTag("t"), message: "This tag no longer exists.", occurredAt: date))
        }

        await #expect(throws: SignInFailure(message: Self.refusal)) { try await signInAsBob(device) }
        #expect(try await device.document().account?.email == SyncHarness.email)
        #expect(try await device.document().issues.count == 1)
        #expect(harness.server.liveSessionCount(email: Self.bob.email) == 0)
        #expect(
            try device.tokens.token(for: FakeBrainBuddyServer.baseURL) != nil,
            "the linked account's session is put back"
        )
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()), "and it carries on")
    }

    @Test("With nothing waiting another account signs in: the first one's data and session leave the device")
    func switchesAccountsWhenNothingWaits() async throws {
        let harness = SyncHarness()
        harness.server.addAccount(email: Self.bob.email, password: Self.bob.password, displayName: "Bob")
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "t", title: "Ada's task", list: .inbox)))
        await device.sync()
        #expect(try await device.document().outbox.isEmpty)

        let bob = try await signInAsBob(device)
        let document = try await device.document()
        #expect(document.account == bob)
        #expect(document.base.tasks.values.map(\.title).isEmpty, "Ada's server data is gone")
        #expect(document.issues.isEmpty)
        #expect(harness.server.snapshot(email: Self.bob.email).tasks.isEmpty)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0, "Ada's session was ended")
        #expect(harness.server.liveSessionCount(email: Self.bob.email) == 1)
    }

    // MARK: What a sign-in reports

    @Test("A sign-in that cancelled the account's scheduled deletion says so, once")
    func reportsCancelledDeletion() async throws {
        let harness = SyncHarness()
        harness.server.scheduleDeletion(email: SyncHarness.email)
        let device = await harness.device()

        let first = try await device.engine.signInWithResult(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password
        )
        #expect(first.deletionCancelled)
        #expect(first.account.email == SyncHarness.email)
        #expect(try await device.document().account == first.account)

        await device.engine.signOut()
        let second = try await device.engine.signInWithResult(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password
        )
        #expect(!second.deletionCancelled)
    }

    @Test("A sign-in whose link can't be saved ends the session it created")
    func unsavedSignInEndsItsSession() async throws {
        let harness = SyncHarness()
        let tokens = InMemorySessionTokenStore()
        let transport = harness.server.makeTransport()
        let engine = SyncEngine(
            store: UnwritableStore(), tokenStore: tokens, transport: transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )

        await #expect(throws: SignInFailure(message: "Brain Buddy couldn't save your sign-in on this device.")) {
            _ = try await engine.signIn(
                serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password
            )
        }
        #expect(transport.requests.map(\.route) == ["POST /auth/login", "POST /auth/logout"])
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(try tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(await engine.status == .localOnly)
    }

    // MARK: Logging out

    @Test("Signing out offline signs out here at once and logs out on the server when the network is back")
    func offlineSignOutLogsOutLater() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
        await device.engine.setNetworkAvailable(false)
        device.transport.clearLog()

        await device.engine.signOut()
        #expect(device.transport.requests.isEmpty, "nothing is attempted offline")
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try device.tokens.pendingLogouts().map(\.serverURL) == [FakeBrainBuddyServer.baseURL])
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
        #expect(await device.status == .localOnly)

        await device.engine.setNetworkAvailable(true)
        await device.engine.waitUntilIdle()
        #expect(device.transport.requests.map(\.route) == ["POST /auth/logout"])
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(try device.tokens.pendingLogouts().isEmpty)
    }

    @Test("A logout the server didn't get is sent again at the next sync trigger")
    func failedLogoutIsRetried() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        device.transport.inject(.timeout)

        await device.engine.signOut()
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try device.tokens.pendingLogouts().count == 1)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)

        await device.engine.request(.foreground)
        await device.engine.waitUntilIdle()
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(try device.tokens.pendingLogouts().isEmpty)
        #expect(await device.status == .localOnly)
    }

    @Test("With no account linked, stale sessions are forgotten; a set-aside account's is logged out first")
    func discardsStaleSessions() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        let account = try await device.signIn()
        let other = URL(string: "https://other.example/api")!
        try device.tokens.setToken("left-by-an-earlier-install", for: other)

        // Its document was set aside (or the app was installed again): a new engine, no account.
        let fresh = SyncEngine(
            store: InMemoryDocumentStore(), tokenStore: device.tokens, transport: device.transport,
            now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test")
        )
        await fresh.discardStaleSessions(loggingOut: account)
        await fresh.waitUntilIdle()

        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try device.tokens.token(for: other) == nil)
    }

    @Test("A signed-in engine keeps its session when asked to discard stale ones")
    func keepsTheLinkedSession() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()

        await device.engine.discardStaleSessions(loggingOut: nil)
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) != nil)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
    }
}

/// A store whose every write fails, like a full disk.
actor UnwritableStore: DocumentStore {
    func load() async throws(DocumentStoreError) -> StoreDocument? { nil }

    func update(_ transform: @Sendable (inout StoreDocument) throws -> Void) async throws -> StoreDocument {
        throw DocumentStoreError.io("disk full")
    }

    func generation() async throws(DocumentStoreError) -> Int? { nil }

    func destroy() async throws(DocumentStoreError) {}
}
