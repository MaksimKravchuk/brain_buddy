import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Synchronization
import Testing
@testable import BrainBuddySync

@Suite("022 isolated native session finalization")
struct ModernAuthSessionTests {
    @Test("023-FR-016: An owner changed after begin is rechecked under the document lock")
    func ownerChangedBeforeCommit() async throws {
        let url = URL(string: "https://api.example.test/api")!
        let ownerA = LinkedAccount(id: "owner_a", email: "a@example.com", serverURL: url, linkedAt: .distantPast)
        let ownerB = LinkedAccount(id: "owner_b", email: "b@example.com", serverURL: url, linkedAt: .distantPast)
        let store = InMemoryDocumentStore(document: StoreDocument(account: ownerA))
        let tokens = InMemorySessionTokenStore(tokens: [url: "owner-a-token"])
        let body = #"{"status":"signed_in","user":{"id":"owner_a","email":"a@example.com"}}"#
        let transport = ModernResponseTransport([HTTPResponse(statusCode: 200, headers: ["Set-Cookie": "brainbuddy_session=candidate-a; Path=/"], body: Data(body.utf8))])
        let engine = SyncEngine(store: store, tokenStore: tokens, transport: transport)
        await engine.setNetworkAvailable(false)
        let attempt = try await engine.beginSignIn(serverURL: url)
        _ = try await store.update { $0.account = ownerB }
        try tokens.setToken("new-owner-b-token", for: url)
        await #expect(throws: SignInFailure.self) {
            try await engine.completeSignIn(attempt, credential: .emailCode(challengeID: "challenge", code: "123456", verifier: String(repeating: "v", count: 43)))
        }
        #expect(try await store.load()?.account == ownerB)
        #expect(try tokens.token(for: url) == "new-owner-b-token")
        #expect(try tokens.pendingLogouts().map(\.token) == ["candidate-a"])
    }

    @Test("023-FR-016: Cancel during persistence preserves the prior owner and live cookie", arguments: [false, true])
    func cancelDuringPersistence(afterWrite: Bool) async throws {
        let harness = SyncHarness()
        let store = HeldNativeStore(afterWrite: afterWrite)
        let tokens = InMemorySessionTokenStore()
        let engine = SyncEngine(store: store, tokenStore: tokens, transport: harness.server.makeTransport())
        await engine.setNetworkAvailable(false)
        let attempt = try await engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let finishing = Task { try await engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password)) }
        await store.gate.waitForArrival()
        await engine.cancelSignIn(attempt)
        // Cancel must invalidate proof promptly even while the store is
        // delayed. Releasing persistence is a separate deterministic event.
        await store.gate.open()
        await #expect(throws: SignInFailure.self) { try await finishing.value }
        #expect(try await store.load()?.account == nil)
        #expect(try tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
    }
    @Test("023-FR-016: Malformed/error cookies are candidate-only; a continuation never installs one", arguments: [400, 200, 201])
    func invalidResponse(status: Int) async throws {
        let url = URL(string: "https://api.example.test/api")!
        let owner = LinkedAccount(id: "owner_a", email: "ada@example.com", serverURL: url, linkedAt: .distantPast)
        let document = StoreDocument(account: owner)
        let store = InMemoryDocumentStore(document: document)
        let tokens = InMemorySessionTokenStore(tokens: [url: "current-owner-token"])
        let body = status == 400 ? #"{"message":"Invalid proof","reference_id":"safe-ref"}"# : (status == 201 ? #"{"status":"existing_account_required","message":"neutral"}"# : "{broken")
        let transport = ModernResponseTransport([HTTPResponse(statusCode: status, headers: ["Set-Cookie": "brainbuddy_session=abandoned-candidate; Path=/"], body: Data(body.utf8))])
        let engine = SyncEngine(store: store, tokenStore: tokens, transport: transport)
        await engine.setNetworkAvailable(false)
        let attempt = try await engine.beginSignIn(serverURL: url)
        await #expect(throws: SignInFailure.self) {
            try await engine.completeSignIn(attempt, credential: .emailCode(challengeID: String(repeating: "c", count: 43), code: "123456", verifier: String(repeating: "v", count: 43)))
        }
        #expect(try tokens.token(for: url) == "current-owner-token")
        #expect(try await store.load()?.account == owner)
        #expect(try tokens.pendingLogouts().map(\.token) == ["abandoned-candidate"])
    }

    @Test("Mailbox staging consumes the browser handoff once; code verification directly finalizes the same candidate")
    func mailboxContinuation() async throws {
        let url = URL(string: "https://api.example.test/api")!
        let challenge = #"{"status":"verify_mailbox","challenge_id":"challenge","expires_at":"2026-10-06T12:00:00Z","resend_at":"2026-10-06T11:51:00Z","message":"neutral"}"#
        let signed = #"{"status":"signed_in","user":{"id":"owner_a","email":"ada@example.com"},"deletion_cancelled":true}"#
        let transport = ModernResponseTransport([
            HTTPResponse(statusCode: 200, body: Data(challenge.utf8)),
            HTTPResponse(statusCode: 200, headers: ["Set-Cookie": "brainbuddy_session=accepted-candidate; Path=/"], body: Data(signed.utf8)),
        ])
        let store = InMemoryDocumentStore()
        let tokens = InMemorySessionTokenStore()
        let engine = SyncEngine(store: store, tokenStore: tokens, transport: transport)
        await engine.setNetworkAvailable(false)
        let attempt = try await engine.beginSignIn(serverURL: url)
        let verifier = String(repeating: "v", count: 43)
        let staged = try await engine.completeSignIn(attempt, credential: .browserGrant(attemptID: verifier, state: verifier, handoffCode: verifier, verifier: verifier))
        guard case .continuation(.verifyMailbox) = staged else { Issue.record("Expected mailbox staging"); return }
        #expect(try tokens.token(for: url) == nil)
        #expect(try await store.load()?.account == nil)
        let finished = try await engine.completeSignIn(attempt, credential: .emailCode(challengeID: "challenge", code: "123456", verifier: verifier))
        guard case .signedIn(let result) = finished else { Issue.record("Expected atomic signed_in"); return }
        #expect(result.account.id == "owner_a" && result.deletionCancelled)
        #expect(try tokens.token(for: url) == "accepted-candidate")
        #expect(transport.requests.map(\.url.path) == ["/api/auth/providers/complete", "/api/auth/email/verify"])
        #expect(transport.requests.last?.body.map { String(decoding: $0, as: UTF8.self).contains("handoff_code") } == false)
    }

    @Test("023-FR-024: Local-only work goes through the existing first-pull merge and push")
    func localMerge() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.apply(.createTask(.init(taskID: "local", title: "Keep local work", list: .inbox)))
        let attempt = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let outcome = try await device.engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        guard case .signedIn(let result) = outcome else { Issue.record("Expected linked session"); return }
        #expect(result.account.id == harness.accountID)
        #expect(harness.snapshot.task(titled: "Keep local work") != nil)
        #expect(try await device.document().outbox.isEmpty)
    }

    @Test("023-FR-016: A late failed request cannot invalidate a newer successful attempt")
    func lateFailure() async throws {
        let harness = SyncHarness()
        let device = HeldDevice(harness: harness, matches: { $0.url.path.hasSuffix("/auth/login") })
        try await device.signIn()
        device.inner.inject(.status(401), matching: { $0.url.path.hasSuffix("/auth/login") })
        let first = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let pending = Task { try await device.engine.completeSignIn(first, credential: .password(email: SyncHarness.email, password: "wrong password")) }
        await device.transport.gate.waitForArrival()
        let second = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        _ = try await device.engine.completeSignIn(second, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        let accepted = try device.tokens.token(for: FakeBrainBuddyServer.baseURL)
        await device.transport.gate.open()
        await #expect(throws: SignInFailure.self) { try await pending.value }
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == accepted)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
    }

    @Test("023-FR-016 / 023-SC-006: Failed Keychain installation restores durable owner, token and pending work; offline cleanup owns only the candidate")
    func keychainFailure() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        let owner = try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "pending", title: "Waiting privately", list: .inbox)))
        let before = try await device.document()
        let token = try #require(try device.tokens.token(for: FakeBrainBuddyServer.baseURL))
        let tokens = RefusingCandidateTokenStore(inner: device.tokens, accepted: token)
        let engine = SyncEngine(store: device.store, tokenStore: tokens, transport: device.transport)
        await engine.setNetworkAvailable(false)
        let attempt = try await engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        await #expect(throws: SignInFailure.self) {
            try await engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        }
        let after = try await device.document()
        #expect(after.account == owner)
        #expect(after.outbox == before.outbox)
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == token)
        let queued = try device.tokens.pendingLogouts()
        #expect(queued.count == 1 && queued.first?.token != token)
    }

    @Test("Same immutable ID with changed email remains the owner")
    func changedEmail() async throws {
        let harness = SyncHarness()
        let device = await harness.device()
        try await device.signIn()
        _ = try await device.store.update { doc in doc.account?.email = "old-address@example.com" }
        let attempt = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let result = try await device.engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        guard case .signedIn(let linked) = result else { Issue.record("Expected same owner"); return }
        #expect(linked.account.id == harness.accountID)
        #expect(linked.account.email == SyncHarness.email)
    }
    @Test("A linked device cannot start an attempt on another server")
    func wrongServer() async throws {
        let device = await SyncHarness().device()
        try await device.signIn()
        await #expect(throws: SignInFailure.self) {
            try await device.engine.beginSignIn(serverURL: URL(string: "https://other.example.test/api")!)
        }
    }

    @Test("023-FR-016 / 023-SC-006: Wrong owner with pending work preserves every operation")
    func pendingWrongOwner() async throws {
        let harness = SyncHarness()
        harness.server.addAccount(email: "bob@example.com", password: "bob long password")
        let device = await harness.device()
        try await device.signIn()
        try await device.apply(.createTask(.init(taskID: "private", title: "Private local work", list: .inbox)))
        let before = try await device.document()
        let attempt = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        await #expect(throws: SignInFailure.self) {
            try await device.engine.completeSignIn(attempt, credential: .password(email: "bob@example.com", password: "bob long password"))
        }
        #expect(try await device.document().outbox == before.outbox)
        #expect(harness.server.snapshot(email: "bob@example.com").tasks.isEmpty)
    }

    @Test("023-FR-016: A newer attempt supersedes late success without revoking its accepted session")
    func overlap() async throws {
        let harness = SyncHarness()
        let device = HeldDevice(harness: harness, matches: { $0.url.path.hasSuffix("/auth/login") })
        try await device.signIn()
        let first = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let pending = Task { try await device.engine.completeSignIn(first, credential: .password(email: SyncHarness.email, password: SyncHarness.password)) }
        await device.transport.gate.waitForArrival()
        let second = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        _ = try await device.engine.completeSignIn(second, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        let accepted = try device.tokens.token(for: FakeBrainBuddyServer.baseURL)
        await device.transport.gate.open()
        await #expect(throws: SignInFailure.self) { try await pending.value }
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == accepted)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
    }

    @Test("Explicit sign-out invalidates a response already issued by the server")
    func signOutDuringCompletion() async throws {
        let harness = SyncHarness()
        let device = HeldDevice(harness: harness, matches: { $0.url.path.hasSuffix("/auth/login") })
        try await device.signIn()
        let attempt = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let pending = Task { try await device.engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password)) }
        await device.transport.gate.waitForArrival()
        try await device.engine.signOut(removingLocalDataWith: {})
        await device.transport.gate.open()
        await #expect(throws: SignInFailure.self) { try await pending.value }
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(await device.engine.status == .localOnly)
    }

    @Test("023-FR-016: Wrong owner is refused even with an empty outbox; legacy switch still works")
    func wrongOwner() async throws {
        let harness = SyncHarness()
        harness.server.addAccount(email: "bob@example.com", password: "bob long password")
        let device = await harness.device()
        let original = try await device.signIn()
        let token = try device.tokens.token(for: FakeBrainBuddyServer.baseURL)
        let attempt = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        await #expect(throws: SignInFailure.self) {
            try await device.engine.completeSignIn(attempt, credential: .password(email: "bob@example.com", password: "bob long password"))
        }
        #expect(try await device.document().account == original)
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == token)
        #expect(harness.server.liveSessionCount(email: "bob@example.com") == 0)
    }

    @Test("023-FR-016: Cancelled late success cannot replace the linked cookie or local outbox")
    func cancelledLateSuccess() async throws {
        let harness = SyncHarness()
        let device = HeldDevice(harness: harness, matches: { $0.url.path.hasSuffix("/auth/login") })
        try await device.signIn()
        let token = try device.tokens.token(for: FakeBrainBuddyServer.baseURL)
        let attempt = try await device.engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        let completion = Task {
            try await device.engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        }
        await device.transport.gate.waitForArrival()
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == token, "A candidate response never replaces the live cookie")
        await device.engine.cancelSignIn(attempt)
        await device.transport.gate.open()
        await #expect(throws: SignInFailure.self) { try await completion.value }
        #expect(try device.tokens.token(for: FakeBrainBuddyServer.baseURL) == token)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
    }

    @Test("Candidate is revoked when durable link cannot be saved")
    func storageFailure() async throws {
        let harness = SyncHarness()
        let tokens = InMemorySessionTokenStore()
        let engine = SyncEngine(store: UnwritableStore(), tokenStore: tokens, transport: harness.server.makeTransport())
        let attempt = try await engine.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL)
        await #expect(throws: SignInFailure.self) {
            try await engine.completeSignIn(attempt, credential: .password(email: SyncHarness.email, password: SyncHarness.password))
        }
        #expect(try tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
    }
}

private final class RefusingCandidateTokenStore: SessionTokenStore {
    struct Locked: Error {}
    let inner: InMemorySessionTokenStore
    let accepted: String
    init(inner: InMemorySessionTokenStore, accepted: String) { self.inner = inner; self.accepted = accepted }
    func token(for serverURL: URL) throws -> String? { try inner.token(for: serverURL) }
    func setToken(_ token: String, for serverURL: URL) throws {
        guard token == accepted else { throw Locked() }
        try inner.setToken(token, for: serverURL)
    }
    func removeToken(for serverURL: URL) throws { try inner.removeToken(for: serverURL) }
    func pendingLogouts() throws -> [PendingLogout] { try inner.pendingLogouts() }
    func addPendingLogout(_ logout: PendingLogout) throws { try inner.addPendingLogout(logout) }
    func removePendingLogout(_ logout: PendingLogout) throws { try inner.removePendingLogout(logout) }
}

private final class ModernResponseTransport: HTTPTransport {
    private struct State { var responses: [HTTPResponse]; var requests: [HTTPRequest] = [] }
    private let state: Mutex<State>
    init(_ responses: [HTTPResponse]) { state = Mutex(State(responses: responses)) }
    var requests: [HTTPRequest] { state.withLock { $0.requests } }
    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        try state.withLock { state in
            state.requests.append(request)
            guard !state.responses.isEmpty else { throw TransportError(description: "No response scripted", requestMayHaveBeenSent: false) }
            return state.responses.removeFirst()
        }
    }
}

private actor HeldNativeStore: DocumentStore {
    let base = InMemoryDocumentStore()
    let gate = ResponseGate()
    let afterWrite: Bool
    init(afterWrite: Bool) { self.afterWrite = afterWrite }
    func load() async throws(DocumentStoreError) -> StoreDocument? { try await base.load() }
    func update(_ transform: @Sendable (inout StoreDocument) throws -> Void) async throws -> StoreDocument {
        if afterWrite {
            let result = try await base.update(transform)
            await gate.arrive()
            await gate.wait()
            return result
        }
        await gate.arrive()
        await gate.wait()
        return try await base.update(transform)
    }
    func generation() async throws(DocumentStoreError) -> Int? { try await base.generation() }
    func destroy() async throws(DocumentStoreError) { try await base.destroy() }
}
