import Foundation
import Testing
@testable import BrainBuddyAPI

@Suite("022 modern authentication wire boundaries")
struct ModernAuthTests {
    private let state = String(repeating: "s", count: 43)
    private let grant = String(repeating: "g", count: 43)

    @Test("All completion variants match the backend discriminators")
    func variants() throws {
        let user = #""user":{"id":"owner","email":"ada@example.com"}"#
        for status in ["linked", "verified_email", "changed_email"] {
            _ = try BrainBuddyAPI.makeDecoder().decode(AuthCompletionDTO.self, from: Data("{\"status\":\"\(status)\",\(user)}".utf8))
        }
        for (status, key) in [("reset_ready", "reset_grant"), ("reauthenticated", "recent_proof")] {
            _ = try BrainBuddyAPI.makeDecoder().decode(AuthCompletionDTO.self, from: Data("{\"status\":\"\(status)\",\"\(key)\":\"\(grant)\",\"expires_at\":\"2026-10-06T12:00:00Z\"}".utf8))
        }
        let mailbox = try BrainBuddyAPI.makeDecoder().decode(AuthCompletionDTO.self, from: Data(#"{"status":"verify_mailbox","challenge_id":"challenge","expires_at":"2026-10-06T12:00:00Z","resend_at":"2026-10-06T11:51:00Z","message":"neutral"}"#.utf8))
        guard case .verifyMailbox(let challenge) = mailbox else { Issue.record("Expected mailbox staging"); return }
        #expect(challenge.challengeID == "challenge")
        let collision = try BrainBuddyAPI.makeDecoder().decode(AuthCompletionDTO.self, from: Data(#"{"status":"existing_account_required","message":"Sign in to your existing account"}"#.utf8))
        #expect(collision == .existingAccountRequired(message: "Sign in to your existing account"))
    }

    @Test("Original Apple assertion/code and browser handoff/verifier are POST bodies")
    func credentialWire() async throws {
        let signedIn = "{\"status\":\"signed_in\",\"user\":\(Fixture.me)}"
        let transport = ScriptedTransport([
            Fixture.json(200, signedIn, headers: ["Set-Cookie": Fixture.loginSetCookie]),
            Fixture.json(200, signedIn, headers: ["Set-Cookie": Fixture.loginSetCookie]),
            Fixture.json(200, signedIn, headers: ["Set-Cookie": Fixture.loginSetCookie]),
        ])
        let candidate = NativeAuthenticationSession(serverURL: Fixture.baseURL, transport: transport)
        _ = try await candidate.complete(.apple(attemptID: grant, state: state, authorizationCode: "original+code", identityToken: "original.assertion", verifier: grant))
        #expect(transport.lastRequest?.url.path == "/api/auth/providers/apple/native/complete")
        #expect(transport.lastRequest?.bodyText?.contains("\"authorization_code\":\"original+code\"") == true)
        #expect(transport.lastRequest?.bodyText?.contains("\"identity_token\":\"original.assertion\"") == true)
        candidate.forgetCandidate()
        _ = try await candidate.complete(.browserGrant(attemptID: grant, state: state, handoffCode: grant, verifier: state))
        #expect(transport.lastRequest?.bodyText?.contains("\"handoff_code\":") == true)
        #expect(transport.lastRequest?.bodyText?.contains("\"client_verifier\":") == true)
        candidate.forgetCandidate()
        _ = try await candidate.complete(.emailCode(challengeID: grant, code: "123456", verifier: state))
        #expect(transport.lastRequest?.url.path == "/api/auth/email/verify")
        #expect(transport.lastRequest?.bodyText?.contains("\"code\":\"123456\"") == true)
        #expect(transport.requests.allSatisfy { $0.url.query == nil && $0.headers["Cookie"] == nil })
    }

    @Test("022-FR-016: Continuations and malformed/error responses never authorize a cookie")
    func cookieBoundary() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, #"{"status":"existing_account_required","message":"neutral"}"#, headers: ["Set-Cookie": Fixture.loginSetCookie]),
            Fixture.json(200, "{broken", headers: ["Set-Cookie": Fixture.loginSetCookie]),
            Fixture.error(400, "invalid", headers: ["Set-Cookie": Fixture.loginSetCookie]),
            Fixture.json(200, "{\"status\":\"signed_in\",\"user\":\(Fixture.me)}"),
        ])
        let candidate = NativeAuthenticationSession(serverURL: Fixture.baseURL, transport: transport)
        let credential = NativeSignInCredential.emailCode(challengeID: grant, code: "123456", verifier: state)
        for _ in 0..<3 {
            _ = await expectAPIError { _ = try await candidate.complete(credential) }
        }
        // A cookie from a rejected earlier response cannot satisfy a later
        // signed_in which omitted its own cookie.
        _ = await expectAPIError { _ = try await candidate.complete(credential) }
    }

    @Test("Email resend and recovery use the frozen fields and reset stays signed out")
    func recoveryWire() async throws {
        let challenge = #"{"challenge_id":"challenge","expires_at":"2026-10-06T12:00:00Z","resend_at":"2026-10-06T11:51:00Z","message":"neutral"}"#
        let transport = ScriptedTransport([Fixture.json(202, challenge), Fixture.json(202, challenge), Fixture.noContent()])
        let api = Fixture.client(transport)
        _ = try await api.requestEmailCode(email: "ada@example.com", purpose: .recover, clientChallenge: grant)
        #expect(transport.lastRequest?.bodyText?.contains("\"purpose\":\"recover\"") == true)
        #expect(transport.lastRequest?.bodyText?.contains("\"client\":\"ios\"") == true)
        _ = try await api.resendEmailCode(challengeID: grant, verifier: state)
        #expect(transport.lastRequest?.bodyText == "{\"challenge_id\":\"\(grant)\",\"client_verifier\":\"\(state)\"}")
        try await api.resetPassword(grant: grant, verifier: state, newPassword: "long new password")
        #expect(transport.lastRequest?.url.path == "/api/auth/recovery/reset")
        #expect(try !api.hasStoredSession())
    }

    @Test("Callback requires the exact active endpoint, state and one grant")
    func callback() throws {
        let valid = "brainbuddy://auth/callback?attempt=attempt_1&state=\(state)&grant=\(grant)"
        #expect(try NativeAuthCallback.parse(URL(string: valid)!, attemptID: "attempt_1", state: state).handoffCode == grant)
        for text in [valid + "&grant=x", valid + "#fragment", valid.replacingOccurrences(of: "auth/callback", with: "evil/callback"), valid.replacingOccurrences(of: "brainbuddy://", with: "https://"), valid.replacingOccurrences(of: "auth/callback", with: "person@auth/callback"), valid + "&token=secret"] {
            #expect(throws: NativeAuthCallback.InvalidCallback.self) {
                try NativeAuthCallback.parse(URL(string: text)!, attemptID: "attempt_1", state: state)
            }
        }
        #expect(throws: NativeAuthCallback.InvalidCallback.self) {
            try NativeAuthCallback.parse(URL(string: valid)!, attemptID: "other", state: state)
        }
        #expect(throws: NativeAuthCallback.InvalidCallback.self) {
            try NativeAuthCallback.parse(URL(string: valid)!, attemptID: "attempt_1", state: grant)
        }
    }

    @Test("Discovery decodes actual snake case fields and sends ios")
    func discovery() async throws {
        let transport = ScriptedTransport([Fixture.json(200, #"{"password":true,"google":true,"apple":false,"email":true,"web_account_origin":"https://web.example.test"}"#)])
        let result = try await Fixture.client(transport).authMethods()
        #expect(result.google && !result.apple && result.email)
        #expect(result.webAccountOrigin == "https://web.example.test")
        #expect(transport.lastRequest?.url.query == "client=ios")
    }

    @Test("Completion is a discriminated union; unknown statuses fail closed")
    func completion() throws {
        let data = Data(#"{"status":"signed_in","user":{"id":"owner","email":"ada@example.com"},"deletion_cancelled":true}"#.utf8)
        let decoded = try BrainBuddyAPI.makeDecoder().decode(AuthCompletionDTO.self, from: data)
        guard case .signedIn(let me, let cancelled) = decoded else { Issue.record("Expected signed_in"); return }
        #expect(me.id == "owner" && cancelled)
        #expect(throws: (any Error).self) {
            try BrainBuddyAPI.makeDecoder().decode(AuthCompletionDTO.self, from: Data(#"{"status":"ready"}"#.utf8))
        }
    }

    @Test("Owner links use only configured origin and a nonsecret owner")
    func webLinks() throws {
        #expect(NativeAccountDestination.url(origin: "https://web.example.test", ownerID: "user_1", deleting: true)?.absoluteString == "https://web.example.test/settings/account/delete?expected_owner=user_1")
        for origin in ["https://person@web.example.test", "https://web.example.test/api", "https://web.example.test?token=x", "http://remote.example.test"] {
            #expect(NativeAccountDestination.url(origin: origin, ownerID: "user_1", deleting: false) == nil)
        }
    }
}
