import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Synchronization
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

        try await device.engine.signOut(removingLocalDataWith: {})
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

        try await device.engine.signOut(removingLocalDataWith: {})
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

        try await device.engine.signOut(removingLocalDataWith: {})
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

    // MARK: Words per device, and the Keychain

    @Test("021-FR-004 the Mac's refusal names the Mac, and the error itself carries no text")
    func refusalNamesTheDevice() async throws {
        let harness = SyncHarness()
        harness.server.addAccount(email: Self.bob.email, password: Self.bob.password)
        let store = InMemoryDocumentStore()
        let transport = harness.server.makeTransport()
        let engine = SyncEngine(
            store: store, tokenStore: InMemorySessionTokenStore(), transport: transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"),
            identity: .macOS(version: "0.1.0"))
        _ = try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
        let date = harness.clock.now()
        _ = try await store.update { doc in
            let command = GTDCommand.createTask(.init(taskID: "x", title: "Waiting", list: .inbox))
            doc.outbox = OutboxCompactor.appending(PendingOperation(command: command, issuedAt: date), to: doc.outbox)
        }

        await #expect(
            throws: SignInFailure(
                message: "Sign out first to use another account. Changes from the other account are still waiting on this Mac.")
        ) {
            _ = try await engine.signIn(
                serverURL: FakeBrainBuddyServer.baseURL, email: Self.bob.email, password: Self.bob.password)
        }
        #expect(Mirror(reflecting: AccountSwitchRefused()).children.isEmpty, "the text comes from the catalogue")
        #expect(transport.requests.allSatisfy { $0.header("X-Client") == "brainbuddy-macos/test" })
    }

    @Test("021-FR-005 021-FR-015 a session the Keychain can't keep is ended at once, and the sign-in fails with a reference id")
    func unsavedSessionIsEnded() async throws {
        let harness = SyncHarness()
        let tokens = SpyTokenStore(failingWrites: true)
        let store = InMemoryDocumentStore()
        let transport = harness.server.makeTransport()
        let engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"))

        do {
            _ = try await engine.signIn(
                serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
            Issue.record("Expected the sign-in to fail")
        } catch {
            #expect(error.message == "Brain Buddy couldn't save your sign-in on this device. Try again.")
            #expect(error.referenceID?.isEmpty == false)
            #expect(error.referenceID == transport.requests.first?.header("X-Correlation-ID"))
        }
        let logouts = transport.requests.filter { $0.route == "POST /auth/logout" }
        #expect(logouts.count == 1)
        let cookie = try #require(logouts.first?.header("Cookie"))
        let issued = try #require(transport.exchanges.first?.response?.header("Set-Cookie"))
        #expect(issued.contains(String(cookie.dropFirst("brainbuddy_session=".count))), "it carries the issued token")
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(try await store.load() == nil, "no linked account")
        #expect(await engine.status == .localOnly)
    }

    @Test("021-FR-005 only a sign-in the person started stores interactively; sync and sign-out never do")
    func onlySignInIsInteractive() async throws {
        let harness = SyncHarness()
        let tokens = SpyTokenStore()
        let engine = SyncEngine(
            store: InMemoryDocumentStore(), tokenStore: tokens, transport: harness.server.makeTransport(),
            now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"))
        _ = try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
        await engine.syncNow()
        await engine.request(.periodic)
        await engine.request(.foreground)
        await engine.waitUntilIdle()
        try await engine.signOut(removingLocalDataWith: {})

        #expect(tokens.writes == [true], "the sign-in's own write, and nothing else, may prompt")
        #expect(tokens.reads > 0, "every read goes through the call that never prompts")
    }

    @Test("021-FR-005 021-FR-017 a session this Mac build may not read asks to sign in again, and the waiting change stays")
    func deniedKeychainAsksToSignInAgain() async throws {
        let harness = SyncHarness()
        let rig = FaultyDevice(harness)
        let account = try await rig.signIn()
        try await rig.queueTask(titled: "Waiting for the next sign-in")
        rig.tokens.failReads(with: TokenStoreError.accessDenied)
        rig.transport.clearLog()

        #expect(await rig.engine.syncNow() == .needsSignIn)
        #expect(rig.transport.requests.isEmpty, "nothing goes out without a readable session")
        let document = try #require(try await rig.store.load())
        #expect(document.account == account)
        #expect(document.outbox.count == 1, "the change waits for the sign-in that replaces the item")
        #expect(rig.tokens.storedToken != nil, "the item is left for that sign-in to replace")
    }

    @Test("021-FR-014 any other unreadable session is a failure to retry, not an ended session")
    func otherKeychainFailureIsRetried() async throws {
        let harness = SyncHarness()
        let rig = FaultyDevice(harness)
        try await rig.signIn()
        try await rig.queueTask(titled: "Sent once the Keychain answers")
        rig.tokens.failReads(with: FaultyTokenStore.Refused())

        #expect(await rig.engine.syncNow() != .needsSignIn)
        #expect(try await rig.store.load()?.outbox.count == 1)

        rig.tokens.failReads(with: nil)
        #expect(await rig.engine.syncNow() == .idle(lastSyncedAt: harness.clock.now()))
        #expect(harness.snapshot.task(titled: "Sent once the Keychain answers") != nil)
    }

    // MARK: Signing out

    @Test("021-FR-005 021-FR-018 sign-out records the logout first, removes the data, then the token, then logs out")
    func signOutOrder() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        let url = FakeBrainBuddyServer.baseURL
        let seen = Seen()

        try await device.engine.signOut {
            seen.record(
                token: (try? device.tokens.token(for: url)) != nil, pending: (try? device.tokens.pendingLogouts().count) ?? -1,
                logouts: device.transport.requests.filter { $0.route == "POST /auth/logout" }.count)
        }
        #expect(seen.value?.token == true, "the session is still there while the data goes")
        #expect(seen.value?.pending == 1, "and its logout is already on record")
        #expect(seen.value?.logouts == 0, "and the server has not been told")
        #expect(try device.tokens.token(for: url) == nil)
        #expect(try device.tokens.pendingLogouts().isEmpty)
        #expect(device.transport.requests.filter { $0.route == "POST /auth/logout" }.count == 1)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(await device.status == .localOnly)
    }

    @Test("021-FR-018 a removal that fails leaves the session, token and account as they were, and sync resumes")
    func failedRemovalChangesNothing() async throws {
        struct DiskFull: Error {}
        let harness = SyncHarness()
        let device = await harness.device()
        let account = try await device.signIn()
        device.transport.clearLog()

        await #expect(throws: DiskFull.self) { try await device.engine.signOut { throw DiskFull() } }
        await device.engine.waitUntilIdle()

        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) != nil)
        #expect(try device.tokens.pendingLogouts().isEmpty, "the logout on record was withdrawn")
        #expect(device.transport.requests.allSatisfy { $0.route != "POST /auth/logout" })
        #expect(device.transport.requests.contains { $0.route == "GET /tasks" }, "syncing resumed")
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
        #expect(try await device.document().account == account)
        #expect(await device.status != .needsSignIn)
        #expect(await device.sync() == .idle(lastSyncedAt: harness.clock.now()))
    }

    @Test("021-FR-005 021-FR-018 offline, a sign-out whose logout can't be recorded fails and removes nothing")
    func unrecordedOfflineLogoutKeepsEverything() async throws {
        let harness = SyncHarness()
        let rig = FaultyDevice(harness)
        let account = try await rig.signIn()
        await rig.engine.setNetworkAvailable(false)
        rig.tokens.failPendingLogouts()
        rig.transport.clearLog()
        let removal = Removal()

        await #expect(throws: FaultyTokenStore.Refused.self) { try await rig.engine.signOut { removal.run() } }

        #expect(!removal.ran, "the device's data stays")
        #expect(rig.tokens.storedToken != nil, "and so does the session")
        #expect(try rig.tokens.pendingLogouts().isEmpty)
        #expect(try await rig.store.load()?.account == account)
        #expect(rig.transport.requests.isEmpty)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
        #expect(await rig.engine.status != .localOnly, "still signed in")
    }

    @Test("021-FR-005 021-FR-018 a sign-out that can't read the session fails and removes nothing")
    func unreadableSessionSignOutKeepsEverything() async throws {
        let harness = SyncHarness()
        let rig = FaultyDevice(harness)
        let account = try await rig.signIn()
        rig.tokens.failReads(with: FaultyTokenStore.Refused())
        rig.transport.clearLog()
        let removal = Removal()

        await #expect(throws: FaultyTokenStore.Refused.self) { try await rig.engine.signOut { removal.run() } }
        await rig.engine.waitUntilIdle()

        #expect(!removal.ran, "the device's data stays")
        #expect(rig.tokens.storedToken != nil, "and so does the session")
        #expect(try rig.tokens.pendingLogouts().isEmpty)
        #expect(try await rig.store.load()?.account == account)
        #expect(rig.transport.requests.allSatisfy { $0.route != "POST /auth/logout" })
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
        #expect(await rig.engine.status != .localOnly, "still signed in")

        rig.tokens.failReads(with: nil)
        #expect(await rig.engine.syncNow() == .idle(lastSyncedAt: harness.clock.now()), "and syncing carries on")
    }
}

/// An engine over `FaultyTokenStore`, for the Keychain failures a `Device` can't stage.
private struct FaultyDevice {
    let harness: SyncHarness
    let store = InMemoryDocumentStore()
    let tokens = FaultyTokenStore()
    let transport: FakeServerTransport
    let engine: SyncEngine

    init(_ harness: SyncHarness) {
        self.harness = harness
        transport = harness.server.makeTransport()
        engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport, now: harness.clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), jitter: { 0.5 }, clientVersion: "test"))
    }

    @discardableResult
    func signIn() async throws -> LinkedAccount {
        try await engine.signIn(
            serverURL: FakeBrainBuddyServer.baseURL, email: SyncHarness.email, password: SyncHarness.password)
    }

    /// Queues a new Inbox task the way the workspace does, without syncing it.
    func queueTask(titled title: String) async throws {
        let date = harness.clock.now()
        _ = try await store.update { doc in
            let command = GTDCommand.createTask(.init(taskID: "queued", title: title, list: .inbox))
            doc.outbox = OutboxCompactor.appending(PendingOperation(command: command, issuedAt: date), to: doc.outbox)
        }
    }
}

/// Whether a sign-out ran its removal step.
private final class Removal: Sendable {
    private let state = Mutex(false)
    func run() { state.withLock { $0 = true } }
    var ran: Bool { state.withLock { $0 } }
}

/// An in-memory token store whose reads, or pending-logout writes, can be made to fail mid-test.
final class FaultyTokenStore: SessionTokenStore {
    struct Refused: Error {}
    private struct Faults {
        var read: (any Error & Sendable)?
        var pendingLogouts = false
    }

    private let inner = InMemorySessionTokenStore()
    private let faults = Mutex(Faults())

    /// Every read throws `error` from now on; nil reads normally again.
    func failReads(with error: (any Error & Sendable)?) { faults.withLock { $0.read = error } }
    /// Recording a pending logout throws `Refused` from now on.
    func failPendingLogouts() { faults.withLock { $0.pendingLogouts = true } }
    /// The token for the fake server, read past any fault.
    var storedToken: String? { try? inner.token(for: FakeBrainBuddyServer.baseURL) }

    func token(for serverURL: URL) throws -> String? {
        if let error = faults.withLock({ $0.read }) { throw error }
        return try inner.token(for: serverURL)
    }

    func setToken(_ token: String, for serverURL: URL) throws { try inner.setToken(token, for: serverURL) }
    func removeToken(for serverURL: URL) throws { try inner.removeToken(for: serverURL) }
    func removeAllTokens() throws { try inner.removeAllTokens() }
    func pendingLogouts() throws -> [PendingLogout] { try inner.pendingLogouts() }

    func addPendingLogout(_ logout: PendingLogout) throws {
        if faults.withLock({ $0.pendingLogouts }) { throw Refused() }
        try inner.addPendingLogout(logout)
    }

    func removePendingLogout(_ logout: PendingLogout) throws { try inner.removePendingLogout(logout) }
}

/// What a sign-out's removal step saw.
private final class Seen: Sendable {
    private let observation = Mutex<(token: Bool, pending: Int, logouts: Int)?>(nil)
    func record(token: Bool, pending: Int, logouts: Int) { observation.withLock { $0 = (token, pending, logouts) } }
    var value: (token: Bool, pending: Int, logouts: Int)? { observation.withLock { $0 } }
}

/// A token store that remembers how it was used, and can refuse every write like a locked Keychain.
final class SpyTokenStore: SessionTokenStore {
    struct Locked: Error {}
    private let inner = InMemorySessionTokenStore()
    private let log = Mutex<(writes: [Bool], reads: Int)>(([], 0))
    private let failingWrites: Bool

    init(failingWrites: Bool = false) { self.failingWrites = failingWrites }

    /// The `interactive` flag of every `setToken`, oldest first (`setToken(_:for:)` counts as false).
    var writes: [Bool] { log.withLock { $0.writes } }
    var reads: Int { log.withLock { $0.reads } }

    func token(for serverURL: URL) throws -> String? {
        log.withLock { $0.reads += 1 }
        return try inner.token(for: serverURL)
    }

    func setToken(_ token: String, for serverURL: URL) throws {
        try setToken(token, for: serverURL, interactive: false)
    }

    func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws {
        log.withLock { $0.writes.append(interactive) }
        if failingWrites { throw Locked() }
        try inner.setToken(token, for: serverURL)
    }

    func removeToken(for serverURL: URL) throws { try inner.removeToken(for: serverURL) }
    func removeAllTokens() throws { try inner.removeAllTokens() }
    func pendingLogouts() throws -> [PendingLogout] { try inner.pendingLogouts() }
    func addPendingLogout(_ logout: PendingLogout) throws { try inner.addPendingLogout(logout) }
    func removePendingLogout(_ logout: PendingLogout) throws { try inner.removePendingLogout(logout) }
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
