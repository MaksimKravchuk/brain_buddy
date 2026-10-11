import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddySync
import Foundation
import Testing
import Synchronization

@Suite("026 T044 authenticated owner candidate producer")
struct NativeCandidateAuthenticationTests {
    private let credential = NativeSignInCredential.password(email: SyncHarness.email, password: SyncHarness.password)

    private func accepted(_ outcome: NativeCandidateCompletion) throws -> NativeAcceptedCandidate {
        guard case .accepted(let candidate) = outcome else {
            throw SignInFailure(message: "Expected an accepted candidate")
        }
        return candidate
    }

    @Test("Actual authentication verifies an immutable owner without changing the real Rust binding")
    func verifiedOwnerWithoutLinking() async throws {
        let harness = SyncHarness()
        let transport = harness.server.makeTransport()
        let auth = NativeCandidateAuthentication(transport: transport)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        defer { bridge.close() }
        let runtime = try await bridge.openStore(workspaceID: "candidate-local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        try await runtime.establishAccountless()
        let before = try await runtime.syncStatus()
        let snapshot = try await runtime.snapshot()
        let attempt = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL, expectedAccountID: harness.accountID)
        let candidate = try accepted(try await auth.complete(attempt, credential: credential))
        #expect(candidate.ownerID == harness.accountID)
        #expect(candidate.serverURL == FakeBrainBuddyServer.baseURL && candidate.attemptID == attempt.id)
        #expect(candidate.isCurrent)
        #expect(String(describing: candidate) == "Native accepted candidate (redacted)")
        #expect(try await runtime.syncStatus() == before)
        #expect(try await runtime.snapshot() == snapshot)
        #expect(transport.requests.map(\.url.path) == ["/api/auth/login"])
        if case .complete = await auth.cancel(attempt) {} else { Issue.record("Expected acknowledged cleanup") }
        #expect(!candidate.isCurrent)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(try await runtime.syncStatus() == before)
        try await runtime.close()
    }

    @Test("Wrong expected owner fails closed and revokes only the candidate")
    func wrongOwner() async throws {
        let harness = SyncHarness()
        let auth = NativeCandidateAuthentication(transport: harness.server.makeTransport())
        let attempt = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL, expectedAccountID: "other-owner")
        await #expect(throws: SignInFailure.self) { try await auth.complete(attempt, credential: credential) }
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(await auth.pendingCleanupCount == 0)
    }

    @Test("Cancel or supersede a held actual response: late success cannot mint current proof", arguments: [false, true])
    func lateResponse(replace: Bool) async throws {
        let harness = SyncHarness()
        let transport = HoldingTransport(inner: harness.server.makeTransport(), matches: { $0.url.path.hasSuffix("/auth/login") })
        transport.arm()
        let auth = NativeCandidateAuthentication(transport: transport)
        let first = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL)
        let finishing = Task { try await auth.complete(first, credential: credential) }
        await transport.gate.waitForArrival()
        var newest: NativeAcceptedCandidate?
        if replace {
            let second = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL)
            newest = try accepted(try await auth.complete(second, credential: credential))
        } else {
            if case .awaitingResponse = await auth.cancel(first) {} else { Issue.record("Cleanup must report the in-flight response") }
            if case .awaitingResponse = await auth.cancel(first) {} else { Issue.record("Repeated cancellation still awaits the response") }
        }
        await transport.gate.open()
        await #expect(throws: SignInFailure.self) { try await finishing.value }
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == (replace ? 1 : 0))
        #expect(newest?.isCurrent == (replace ? true : nil))
        if let newest {
            let current = NativeSignInAttempt(id: newest.attemptID, serverURL: newest.serverURL, expectedAccountID: nil)
            _ = await auth.cancel(current)
        }
    }

    @Test("Task cancellation while an actual response is held cannot publish proof")
    func cancelledTask() async throws {
        let harness = SyncHarness()
        let transport = HoldingTransport(inner: harness.server.makeTransport(), matches: { $0.url.path.hasSuffix("/auth/login") })
        transport.arm()
        let auth = NativeCandidateAuthentication(transport: transport)
        let attempt = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL)
        let finishing = Task { try await auth.complete(attempt, credential: credential) }
        await transport.gate.waitForArrival()
        finishing.cancel()
        await transport.gate.open()
        await #expect(throws: SignInFailure.self) { try await finishing.value }
        // Cleanup may need retry because the completing task itself is cancelled.
        _ = await auth.retryCleanup()
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
        #expect(await auth.pendingCleanupCount == 0)
    }

    @Test("Failed logout retains a private candidate and explicit retry revokes it")
    func retryFailedCleanup() async throws {
        let harness = SyncHarness()
        let transport = harness.server.makeTransport()
        let auth = NativeCandidateAuthentication(transport: transport)
        let attempt = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL)
        let candidate = try accepted(try await auth.complete(attempt, credential: credential))
        transport.inject(.offline, matching: { $0.url.path.hasSuffix("/auth/logout") })
        if case .pending = await auth.cancel(attempt) {} else { Issue.record("Expected a truthful pending cleanup result") }
        #expect(!candidate.isCurrent)
        #expect(await auth.pendingCleanupCount == 1)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 1)
        if case .complete = await auth.retryCleanup() {} else { Issue.record("Expected successful retry") }
        #expect(await auth.pendingCleanupCount == 0)
        #expect(harness.server.liveSessionCount(email: SyncHarness.email) == 0)
    }

    @Test("Missing or malformed candidate cookies never produce an accepted owner", arguments: [false, true])
    func invalidCandidate(cookie: Bool) async throws {
        let body = cookie ? "{broken" : #"{"id":"owner","email":"ada@example.com"}"#
        let transport = CandidateResponseTransport([HTTPResponse(statusCode: 200, headers: cookie ? ["Set-Cookie": "brainbuddy_session=temporary; Path=/"] : [:], body: Data(body.utf8))])
        let auth = NativeCandidateAuthentication(transport: transport)
        let attempt = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL)
        await #expect(throws: SignInFailure.self) { try await auth.complete(attempt, credential: credential) }
        #expect(transport.requests.map(\.url.path) == (cookie ? ["/api/auth/login", "/api/auth/logout"] : ["/api/auth/login"]))
    }

    @Test("Mailbox continuation stays on the same attempt and supplies no owner until verification")
    func continuation() async throws {
        let body = #"{"status":"verify_mailbox","challenge_id":"challenge","expires_at":"2026-10-06T12:00:00Z","resend_at":"2026-10-06T11:51:00Z","message":"neutral"}"#
        let signed = #"{"status":"signed_in","user":{"id":"owner","email":"ada@example.com"}}"#
        let transport = CandidateResponseTransport([
            HTTPResponse(statusCode: 200, body: Data(body.utf8)),
            HTTPResponse(statusCode: 200, headers: ["Set-Cookie": "brainbuddy_session=temporary; Path=/"], body: Data(signed.utf8)),
        ])
        let auth = NativeCandidateAuthentication(transport: transport)
        let attempt = try await auth.begin(serverURL: FakeBrainBuddyServer.baseURL)
        let stage = try await auth.complete(attempt, credential: .browserGrant(attemptID: "browser", state: "state", handoffCode: "code", verifier: "verifier"))
        if case .continuation(.verifyMailbox) = stage {} else { Issue.record("Expected mailbox staging") }
        let candidate = try accepted(try await auth.complete(attempt, credential: .emailCode(challengeID: "challenge", code: "123456", verifier: "verifier")))
        #expect(candidate.isCurrent && candidate.ownerID == "owner" && candidate.attemptID == attempt.id)
        await #expect(throws: SignInFailure.self) { try await auth.complete(attempt, credential: credential) }
        _ = await auth.cancel(attempt)
    }
}

private final class CandidateResponseTransport: HTTPTransport {
    private struct State { var responses: [HTTPResponse]; var requests: [HTTPRequest] = [] }
    private let state: Mutex<State>
    init(_ responses: [HTTPResponse]) { state = Mutex(State(responses: responses)) }
    var requests: [HTTPRequest] { state.withLock { $0.requests } }
    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        state.withLock {
            $0.requests.append(request)
            return $0.responses.isEmpty ? HTTPResponse(statusCode: 204) : $0.responses.removeFirst()
        }
    }
}
