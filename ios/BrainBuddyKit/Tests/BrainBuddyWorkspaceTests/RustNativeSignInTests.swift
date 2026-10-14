import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

/// The two-phase sign-in the sheet uses (`beginSignIn` / `completeSignIn`) on a Rust-selected
/// Workspace: a fresh install on the pilot runtime can sign in, merge its account-less work, and
/// renew its session, with the legacy sheet's semantics (026-FR-003, 026-FR-011).
@Suite("Two-phase sign-in on the Rust runtime (026-FR-003, 026-FR-011)")
struct RustNativeSignInTests {
    private static let password = NativeSignInCredential.password(email: "a@example.com", password: "secret")

    @Test("026-FR-003: begin then complete links the account and merges the account-less work")
    @MainActor
    func beginThenComplete() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        _ = try await app.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:life:pre")

        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)
        #expect(attempt.expectedAccountID == nil)
        #expect(await lane.server.logins == 0, "begin opens no session")
        let outcome = try await app.completeSignIn(attempt, credential: Self.password)

        guard case .signedIn(let result) = outcome else { Issue.record("expected a signed-in outcome"); return }
        #expect(result.account == lane.accountA)
        #expect(app.account == lane.accountA)
        #expect(try lane.selections.load()?.account == lane.accountA)
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 1, "the record is now a command waiting to be sent")
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Written before the account"])
        await app.closeRuntime()
    }

    @Test("026-FR-011: cancelling between the phases links nothing and opens no session")
    @MainActor
    func cancelBetweenPhases() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)
        await app.cancelSignIn(attempt)

        await #expect(throws: WorkspaceError.signInFailed(message: "Start a fresh sign-in. Your local tasks are kept.", referenceID: nil)) {
            _ = try await app.completeSignIn(attempt, credential: Self.password)
        }
        #expect(await lane.server.logins == 0)
        #expect(app.account == nil)
        #expect(try lane.selections.load()?.account == nil)
        await app.closeRuntime()
    }

    @Test("026-FR-011: a Cancel while the login runs ends that session and links nothing")
    @MainActor
    func cancelDuringCompletion() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let gate = Gate()
        let server = ScriptedAccountServer(account: lane.accountA, loginGate: gate)
        let app = try await Self.app(lane, server: server)
        _ = try await app.capture(CaptureDraft(text: "Kept"), editorID: "scene:life:kept")
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)

        let completing = Task { try await app.completeSignIn(attempt, credential: Self.password) }
        await gate.waitUntilReached()
        await app.cancelSignIn(attempt)
        await gate.open()

        await #expect(throws: WorkspaceError.signInFailed(message: "This sign-in was cancelled.", referenceID: nil)) {
            _ = try await completing.value
        }
        #expect(await server.abandoned == [lane.accountA.id], "the session the server opened is ended")
        #expect(app.account == nil)
        #expect(try lane.selections.load()?.account == nil)
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Kept"])
        await app.closeRuntime()
    }

    @Test("026-FR-003: a wrong password is reported in the server's words, keeps the work, and can be retried")
    @MainActor
    func wrongPassword() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let server = ScriptedAccountServer(account: lane.accountA, failure: SignInFailure(message: "Wrong email or password.", referenceID: "ref-1"))
        let app = try await Self.app(lane, server: server)
        _ = try await app.capture(CaptureDraft(text: "Kept"), editorID: "scene:life:kept")
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)

        await #expect(throws: WorkspaceError.signInFailed(message: "Wrong email or password.", referenceID: "ref-1")) {
            _ = try await app.completeSignIn(attempt, credential: Self.password)
        }
        #expect(app.account == nil)
        #expect(try lane.selections.load()?.account == nil)
        #expect(app.isRustBound)

        await server.succeed()
        let outcome = try await app.completeSignIn(attempt, credential: Self.password)
        guard case .signedIn = outcome else { Issue.record("the retry on the same attempt must sign in"); return }
        #expect(app.account == lane.accountA)
        await app.closeRuntime()
    }

    @Test("026-FR-003: signing in again as the linked account queues no second merge, another account is refused")
    @MainActor
    func signInAgainAfterExpiry() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        _ = try await app.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:life:pre")
        let first = try await app.beginSignIn(serverURL: lane.serverURL)
        _ = try await app.completeSignIn(first, credential: Self.password)
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 1)

        // The session expired: the sheet's "Sign in again".
        let again = try await app.beginSignIn(serverURL: lane.serverURL)
        #expect(again.expectedAccountID == lane.accountA.id)
        let outcome = try await app.completeSignIn(again, credential: Self.password)
        guard case .signedIn(let result) = outcome else { Issue.record("expected a signed-in outcome"); return }
        #expect(result.account == lane.accountA)
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 1, "the same account is a no-op, not a second import")
        #expect(app.account == lane.accountA)

        await lane.server.next(lane.accountB)
        let other = try await app.beginSignIn(serverURL: lane.serverURL)
        await #expect(throws: WorkspaceError.signInFailed(message: HostRustAccountLifecycle.differentAccountMessage, referenceID: nil)) {
            _ = try await app.completeSignIn(other, credential: Self.password)
        }
        #expect(app.account == lane.accountA)
        await app.closeRuntime()
    }

    @Test("026-FR-003: sign out then sign in as another account works on the runtime")
    @MainActor
    func accountSwitch() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let app = try await lane.app()
        let first = try await app.beginSignIn(serverURL: lane.serverURL)
        _ = try await app.completeSignIn(first, credential: Self.password)
        try await app.signOut(removing: app.pendingChanges)
        #expect(app.account == nil)

        await lane.server.next(lane.accountB)
        let second = try await app.beginSignIn(serverURL: lane.serverURL)
        #expect(second.expectedAccountID == nil)
        let outcome = try await app.completeSignIn(second, credential: .password(email: "b@example.com", password: "secret"))
        guard case .signedIn(let result) = outcome else { Issue.record("expected a signed-in outcome"); return }
        #expect(result.account == lane.accountB)
        #expect(app.account == lane.accountB)
        await app.closeRuntime()
    }

    // MARK: Email code and browser grant (the sheet's primary path)

    private static let signed = #"{"status":"signed_in","user":{"id":"owner-a","email":"a@example.com"},"deletion_cancelled":false}"#
    private static let mailbox = #"{"status":"verify_mailbox","challenge_id":"challenge","expires_at":"2026-10-06T12:00:00Z","resend_at":"2026-10-06T11:51:00Z","message":"neutral"}"#
    private static let code = NativeSignInCredential.emailCode(challengeID: "challenge", code: "123456", verifier: String(repeating: "v", count: 43))

    @MainActor
    private static func nativeApp(_ lane: SelectionLane, transport: AuthTransport, tokens: InMemorySessionTokenStore) async throws -> Workspace {
        try await app(lane, server: APIRustAccountServer(tokenStore: tokens, transport: transport))
    }

    @Test("026-FR-003: an email code signs in a fresh pilot install, merges its work, and keeps the session only in the token store")
    @MainActor
    func emailCodeSignIn() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let transport = AuthTransport([.init(200, Self.signed, cookie: "accepted-candidate")])
        let tokens = InMemorySessionTokenStore()
        let app = try await Self.nativeApp(lane, transport: transport, tokens: tokens)
        _ = try await app.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:life:pre")

        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)
        #expect(try tokens.token(for: lane.serverURL) == nil)
        let outcome = try await app.completeSignIn(attempt, credential: Self.code)

        guard case .signedIn(let result) = outcome else { Issue.record("expected a signed-in outcome"); return }
        #expect(result.account.id == lane.accountA.id)
        #expect(app.account?.id == lane.accountA.id)
        #expect(try lane.selections.load()?.account?.id == lane.accountA.id)
        #expect(try tokens.token(for: lane.serverURL) == "accepted-candidate")
        #expect(transport.requests.map(\.url.path) == ["/api/auth/email/verify"])
        #expect(transport.requests.allSatisfy { $0.headers["Cookie"] == nil })
        await app.refreshRustStatus()
        #expect(app.pendingChangeCount == 1, "the account-less record is now a command waiting to be sent")
        await app.closeRuntime()
    }

    @Test("026-FR-003: a browser grant that needs a mailbox check links nothing, and the code then finishes the same attempt")
    @MainActor
    func browserGrantThenCode() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let transport = AuthTransport([.init(200, Self.mailbox), .init(200, Self.signed, cookie: "accepted-candidate")])
        let tokens = InMemorySessionTokenStore()
        let app = try await Self.nativeApp(lane, transport: transport, tokens: tokens)
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)
        let verifier = String(repeating: "v", count: 43)

        let staged = try await app.completeSignIn(attempt, credential: .browserGrant(attemptID: verifier, state: verifier, handoffCode: verifier, verifier: verifier))
        guard case .continuation(.verifyMailbox) = staged else { Issue.record("expected mailbox staging"); return }
        #expect(app.account == nil)
        #expect(try tokens.token(for: lane.serverURL) == nil)
        #expect(try lane.selections.load()?.account == nil)

        let finished = try await app.completeSignIn(attempt, credential: Self.code)
        guard case .signedIn = finished else { Issue.record("expected a signed-in outcome"); return }
        #expect(app.account?.id == lane.accountA.id)
        #expect(transport.requests.map(\.url.path) == ["/api/auth/providers/complete", "/api/auth/email/verify"])
        await app.closeRuntime()
    }

    @Test("026-FR-003: a wrong or expired code is reported in the server's words, leaves no session, and can be retried")
    @MainActor
    func wrongCode() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let transport = AuthTransport([
            .init(400, #"{"message":"That code is wrong or expired.","detail":null,"reference_id":"ref-9"}"#),
            .init(200, Self.signed, cookie: "accepted-candidate"),
        ])
        let tokens = InMemorySessionTokenStore()
        let app = try await Self.nativeApp(lane, transport: transport, tokens: tokens)
        _ = try await app.capture(CaptureDraft(text: "Kept"), editorID: "scene:life:kept")
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)

        do {
            _ = try await app.completeSignIn(attempt, credential: Self.code)
            Issue.record("a wrong code must fail")
        } catch let error as WorkspaceError {
            guard case .signInFailed(let message, let reference) = error else { Issue.record("unexpected \(error)"); return }
            #expect(message.contains("wrong or expired"))
            #expect(reference == "ref-9")
        }
        #expect(app.account == nil)
        #expect(try tokens.token(for: lane.serverURL) == nil)
        #expect(try lane.selections.load()?.account == nil)

        let outcome = try await app.completeSignIn(attempt, credential: Self.code)
        guard case .signedIn = outcome else { Issue.record("the retry on the same attempt must sign in"); return }
        #expect(app.account?.id == lane.accountA.id)
        await app.closeRuntime()
    }

    @Test("026-FR-011: cancelling between the code request and its verification sends nothing and links nothing")
    @MainActor
    func cancelBeforeVerify() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let transport = AuthTransport([])
        let tokens = InMemorySessionTokenStore()
        let app = try await Self.nativeApp(lane, transport: transport, tokens: tokens)
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)
        await app.cancelSignIn(attempt)

        await #expect(throws: WorkspaceError.signInFailed(message: "Start a fresh sign-in. Your local tasks are kept.", referenceID: nil)) {
            _ = try await app.completeSignIn(attempt, credential: Self.code)
        }
        #expect(transport.requests.isEmpty)
        #expect(app.account == nil)
        #expect(try tokens.token(for: lane.serverURL) == nil)
        await app.closeRuntime()
    }

    @Test("026-FR-011: a Cancel while the code is verified keeps no session and ends the one the server opened")
    @MainActor
    func cancelDuringVerify() async throws {
        let lane = try SelectionLane()
        defer { lane.cleanup() }
        let gate = Gate()
        let transport = AuthTransport([.init(200, Self.signed, cookie: "late-candidate")], gate: gate)
        let tokens = InMemorySessionTokenStore()
        let app = try await Self.nativeApp(lane, transport: transport, tokens: tokens)
        _ = try await app.capture(CaptureDraft(text: "Kept"), editorID: "scene:life:kept")
        let attempt = try await app.beginSignIn(serverURL: lane.serverURL)

        let completing = Task { try await app.completeSignIn(attempt, credential: Self.code) }
        await gate.waitUntilReached()
        await app.cancelSignIn(attempt)
        await gate.open()

        await #expect(throws: WorkspaceError.self) { _ = try await completing.value }
        #expect(app.account == nil)
        #expect(try lane.selections.load()?.account == nil)
        #expect(try tokens.token(for: lane.serverURL) == nil, "the late session is not kept")
        let ended = transport.requests.contains { $0.url.path == "/api/auth/logout" }
        let waiting = try tokens.pendingLogouts().map(\.token) == ["late-candidate"]
        #expect(ended || waiting, "the session the server opened is ended now or left as a pending logout")
        await app.prepareList(.list(.inbox))
        #expect(app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Kept"])
        await app.closeRuntime()
    }

    @Test(
        "026-FR-003 026-FR-005 026-FR-007: against the real backend a fresh pilot install signs in, merges, and sends (opt-in: set BB_BACKEND_PYTHON)",
        .enabled(if: RustSyncHostBackendTests.python != nil, "BB_BACKEND_PYTHON is unset: the real backend is not exercised"))
    @MainActor
    func realBackendSignIn() async throws {
        let backend = try RealBackend.start(python: try #require(RustSyncHostBackendTests.python))
        defer { backend.stop() }
        // The sign-in sheet accepts http only for localhost, the address the pilot rehearsal uses.
        let serverURL = URL(string: "http://localhost:\(backend.port)/api")!
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("native-signin-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let suite = "native-signin-\(UUID().uuidString)"
        defer { UserDefaults(suiteName: suite)?.removePersistentDomain(forName: suite) }
        let tokens = InMemorySessionTokenStore()
        let pilot = RustRuntimePilotSwitch(suiteName: suite)
        pilot.set(true)
        let environment = RustRuntimeEnvironment(
            location: .directory(root), legacyStoreURL: root.appendingPathComponent("store.json"), bridge: try RustBridgeRuntime(),
            transports: RustSyncTransportProvider(tokenStore: tokens), server: APIRustAccountServer(tokenStore: tokens),
            reviewEnabled: false)
        guard case .rust(let selection, let lifecycle) = await RustRuntimeLauncher(environment: environment, pilot: pilot).resolve() else {
            Issue.record("the fresh install must select the Rust runtime")
            return
        }
        let app = Workspace.selected(selection, lifecycle: lifecycle)
        await app.load()
        _ = try await app.capture(CaptureDraft(text: "Written before the account"), editorID: "scene:life:pre")

        let attempt = try await app.beginSignIn(serverURL: serverURL)
        #expect(try tokens.token(for: serverURL) == nil, "begin keeps no session")
        await #expect(throws: WorkspaceError.self) {
            _ = try await app.completeSignIn(attempt, credential: .password(email: "bb-client@example.com", password: "not the password"))
        }
        #expect(app.account == nil)
        #expect(try tokens.token(for: serverURL) == nil, "a wrong password leaves no token")

        let outcome = try await app.completeSignIn(attempt, credential: .password(email: "bb-client@example.com", password: "correct-horse-battery-staple"))
        guard case .signedIn(let result) = outcome else { Issue.record("expected a signed-in outcome"); return }
        #expect(result.account.id == backend.owner)
        #expect(try tokens.token(for: serverURL) != nil)
        await app.syncNow()
        #expect(await backend.eventually { try backend.titles().contains("Written before the account") })
        await app.closeRuntime()
    }

    @MainActor
    private static func app(_ lane: SelectionLane, server: any RustAccountServer) async throws -> Workspace {
        let instant = lane.instant
        let environment = RustRuntimeEnvironment(
            location: lane.location, legacyStoreURL: lane.legacyURL, bridge: lane.bridge, server: server, now: { instant })
        let pilot = RustRuntimePilotSwitch(suiteName: lane.suite)
        pilot.set(true)
        guard case .rust(let selection, let lifecycle) = await RustRuntimeLauncher(environment: environment, pilot: pilot).resolve() else {
            throw SelectionLaneError.notSelected
        }
        let workspace = Workspace.selected(selection, lifecycle: lifecycle)
        await workspace.load()
        return workspace
    }
}

/// A server that can refuse the login or hold it until the test lets it go.
actor ScriptedAccountServer: RustAccountServer {
    private let account: LinkedAccount
    private var failure: SignInFailure?
    private let loginGate: Gate?
    private(set) var abandoned: [String] = []

    init(account: LinkedAccount, failure: SignInFailure? = nil, loginGate: Gate? = nil) {
        self.account = account
        self.failure = failure
        self.loginGate = loginGate
    }

    func succeed() { failure = nil }

    func login(serverURL: URL, email: String, password: String) async throws -> RustServerLogin {
        await loginGate?.reach()
        if let failure { throw failure }
        return RustServerLogin(account: account)
    }

    func abandon(_ login: RustServerLogin) async { abandoned.append(login.account.id) }
    func beginSignOut(of account: LinkedAccount) async throws -> RustSignOutTicket { RustSignOutTicket(logout: nil) }
    func finishSignOut(_ ticket: RustSignOutTicket, of account: LinkedAccount) async {}
    func cancelSignOut(_ ticket: RustSignOutTicket) async {}
}

/// Scripted HTTP answers for the API-backed account server; an optional gate holds every reply.
final class AuthTransport: HTTPTransport {
    struct Reply: Sendable {
        let status: Int
        let body: String
        let cookie: String?
        init(_ status: Int, _ body: String, cookie: String? = nil) {
            self.status = status
            self.body = body
            self.cookie = cookie
        }
    }
    private struct State { var replies: [Reply]; var requests: [HTTPRequest] = [] }
    private let state: Mutex<State>
    private let gate: Gate?

    init(_ replies: [Reply], gate: Gate? = nil) {
        state = Mutex(State(replies: replies))
        self.gate = gate
    }

    var requests: [HTTPRequest] { state.withLock { $0.requests } }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let reply: Reply? = state.withLock { state in
            state.requests.append(request)
            return state.replies.isEmpty ? nil : state.replies.removeFirst()
        }
        await gate?.reach()
        guard let reply else { throw TransportError(description: "No response scripted", requestMayHaveBeenSent: false) }
        var headers = ["Content-Type": "application/json"]
        if let cookie = reply.cookie { headers["Set-Cookie"] = "brainbuddy_session=\(cookie); HttpOnly; Path=/; SameSite=lax; Secure" }
        return HTTPResponse(statusCode: reply.status, headers: headers, body: Data(reply.body.utf8))
    }
}
