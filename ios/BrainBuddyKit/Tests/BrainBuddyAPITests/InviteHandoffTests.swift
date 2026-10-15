import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("027 invite handoff (design M-03)")
struct InviteHandoffTests {
    private let token = String(repeating: "p", count: 43)
    private let state = String(repeating: "s", count: 43)
    private let required = #"{"code":"INVITE_REQUIRED","pending":"PENDING-TOKEN","expires_in":600}"#

    private func session(_ steps: [ScriptedTransport.Step]) -> (NativeAuthenticationSession, ScriptedTransport) {
        let transport = ScriptedTransport(steps)
        return (NativeAuthenticationSession(serverURL: Fixture.baseURL, transport: transport), transport)
    }

    private func requiredStep(headers: [String: String] = [:]) -> ScriptedTransport.Step {
        Fixture.error(403, "An invite code is required to create an account.", detail: required, headers: headers)
    }

    @Test("027-FR-007: INVITE_REQUIRED on email, browser and Apple completion yields the handoff")
    func handoffOnEveryProvider() async throws {
        let (candidate, _) = session([requiredStep(), requiredStep(), requiredStep()])
        let credentials: [NativeSignInCredential] = [
            .emailCode(challengeID: token, code: "123456", verifier: state),
            .browserGrant(attemptID: token, state: state, handoffCode: token, verifier: state),
            .apple(attemptID: token, state: state, authorizationCode: "c", identityToken: "t", verifier: state),
        ]
        for credential in credentials {
            let outcome = try await candidate.complete(credential)
            #expect(outcome == .inviteRequired(InviteHandoff(pending: "PENDING-TOKEN", expiresIn: 600)))
            #expect(candidate.candidateToken == nil)
        }
    }

    @Test("027-FR-007: a cookie beside INVITE_REQUIRED is refused, and the token never prints")
    func noSessionForAHandoff() async throws {
        let (candidate, _) = session([requiredStep(headers: ["Set-Cookie": Fixture.loginSetCookie])])
        let error = await expectAPIError {
            _ = try await candidate.complete(.emailCode(challengeID: token, code: "123456", verifier: state))
        }
        #expect(error != nil)
        #expect(!"\(InviteHandoff(pending: "PENDING-TOKEN", expiresIn: 600))".contains("PENDING"))
    }

    @Test("027-FR-007: other 403s and a password login are not handoffs")
    func otherRefusals() async throws {
        let (candidate, _) = session([
            Fixture.error(403, "Forbidden", detail: #"{"code":"OTHER","pending":"x"}"#),
            Fixture.error(403, "Forbidden", detail: #"{"code":"INVITE_REQUIRED"}"#),
            requiredStep(),
        ])
        let email = NativeSignInCredential.emailCode(challengeID: token, code: "123456", verifier: state)
        for _ in 0..<2 {
            let error = await expectAPIError { _ = try await candidate.complete(email) }
            #expect(error?.statusCode == 403)
        }
        let password = await expectAPIError {
            _ = try await candidate.complete(.password(email: "a@example.com", password: "pw"))
        }
        #expect(password?.statusCode == 403)
    }

    @Test("027-FR-007: signupComplete posts the pending token and code, then installs the session")
    func resubmit() async throws {
        let signedIn = "{\"status\":\"signed_in\",\"user\":\(Fixture.me)}"
        let (candidate, transport) = session([Fixture.json(200, signedIn, headers: ["Set-Cookie": Fixture.loginSetCookie])])
        let outcome = try await candidate.signupComplete(pending: "PENDING-TOKEN", inviteCode: "ABC-123")
        guard case .signedIn = outcome else { Issue.record("Expected signed_in"); return }
        #expect(transport.lastRequest?.url.path == "/api/auth/signup/complete")
        #expect(transport.lastRequest?.bodyText?.contains("\"pending\":\"PENDING-TOKEN\"") == true)
        #expect(transport.lastRequest?.bodyText?.contains("\"invite_code\":\"ABC-123\"") == true)
        #expect(candidate.candidateToken == Fixture.token)
    }

    @Test("027-FR-016: invalid and used codes share one message and keep the reference id")
    func invalidCode() async throws {
        let (candidate, _) = session([
            Fixture.error(400, "Invite code not found.", detail: #"{"code":"INVITE_INVALID"}"#),
            Fixture.error(400, "Invite code already used.", detail: #"{"code":"INVITE_INVALID"}"#),
        ])
        for _ in 0..<2 {
            let error = await expectAPIError { _ = try await candidate.complete(.invite(pending: "p", inviteCode: "x")) }
            #expect(error?.message == InviteStepCopy.invalid)
            #expect(error?.referenceID == "ref-server-1")
            #expect(error?.isUncertainOutcome == false)
        }
    }

    @Test("027-FR-007: an expired handoff and a rate limit are told apart by wording")
    func expiredAndThrottled() async throws {
        let (candidate, _) = session([
            Fixture.error(410, "gone", detail: #"{"code":"SIGNUP_EXPIRED"}"#),
            Fixture.error(429, "slow down", headers: ["Retry-After": "30"]),
        ])
        let expired = await expectAPIError { _ = try await candidate.complete(.invite(pending: "p", inviteCode: "x")) }
        #expect(expired?.message == InviteStepCopy.expired)
        let throttled = await expectAPIError { _ = try await candidate.complete(.invite(pending: "p", inviteCode: "x")) }
        #expect(throttled?.message == InviteStepCopy.tooManyAttempts)
        #expect(throttled?.isUncertainOutcome == false)
        #expect(throttled?.retryAfter == 30)
    }
}
