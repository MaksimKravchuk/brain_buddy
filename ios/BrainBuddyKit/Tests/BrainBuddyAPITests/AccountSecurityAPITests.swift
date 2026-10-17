import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("033 iPhone account management wire")
struct AccountSecurityAPITests {
    private let proof = RecentProof(value: String(repeating: "p", count: 43), expiresAt: Date(timeIntervalSince1970: 0))
    private let grant = String(repeating: "g", count: 43)

    @Test("033-FR-002 the name is a PATCH bound to the shown owner")
    func profile() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, #"{"id":"owner","email":"max@example.com","display_name":"Max","completed_task_count":3}"#)
        ])
        let summary = try await Fixture.client(transport, store: Fixture.signedInStore()).updateProfile(displayName: "Max", expectedOwner: "owner")
        #expect(summary.displayName == "Max")
        #expect(transport.lastRequest?.method == .patch)
        #expect(transport.lastRequest?.url.path == "/api/account/profile")
        #expect(transport.lastRequest?.headers["X-BrainBuddy-Expected-Owner"] == "owner")
        #expect(transport.lastRequest?.headers["Cookie"] == "brainbuddy_session=\(Fixture.token)")
        #expect(transport.lastRequest?.bodyText == #"{"display_name":"Max"}"#)
    }

    @Test("033-FR-004 confirming by password sends the action and owner and returns a redacted proof")
    func confirmPassword() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, #"{"status":"reauthenticated","recent_proof":"\#(grant)","expires_at":"2026-10-16T12:05:00Z"}"#)
        ])
        let result = try await Fixture.client(transport, store: Fixture.signedInStore())
            .confirmPassword("secret", action: .unlinkApple, expectedAccountID: "owner")
        #expect(result.value == grant)
        #expect(!String(describing: result).contains(grant))
        #expect(transport.lastRequest?.url.path == "/api/auth/confirm/password")
        let body = try #require(transport.lastRequest?.bodyText)
        #expect(body.contains(#""action":"unlink:apple""#))
        #expect(body.contains(#""expected_account_id":"owner""#))
        #expect(transport.lastRequest?.headers["Cookie"] != nil)
    }

    @Test("033-FR-005 an account email code carries the session and the change's proof; a cookie beside it is refused")
    func emailCode() async throws {
        let changed = #"{"status":"changed_email","user":\#(Fixture.me)}"#
        let transport = ScriptedTransport([
            Fixture.json(200, changed),
            Fixture.json(200, changed, headers: ["Set-Cookie": Fixture.loginSetCookie]),
        ])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let completion = try await client.verifyAccountEmailCode(challengeID: grant, code: "123456", verifier: grant, recentProof: proof)
        guard case .changedEmail(let user) = completion else { Issue.record("Expected changed_email"); return }
        #expect(user.email == "ada@example.com")
        #expect(transport.lastRequest?.bodyText?.contains(#""recent_proof":"\#(proof.value)""#) == true)
        #expect(transport.lastRequest?.headers["Cookie"] != nil)
        _ = await expectAPIError { _ = try await client.verifyAccountEmailCode(challengeID: grant, code: "123456", verifier: grant) }
    }

    @Test("033-FR-007 provider link completes on the session; a sign-in result is refused")
    func providerLink() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, #"{"status":"linked","user":\#(Fixture.me)}"#),
            Fixture.json(200, #"{"status":"signed_in","user":\#(Fixture.me)}"#),
        ])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let credential = NativeSignInCredential.apple(attemptID: grant, state: grant, authorizationCode: "code", identityToken: "token", verifier: grant)
        guard case .linked = try await client.completeAccountProvider(credential) else { Issue.record("Expected linked"); return }
        #expect(transport.lastRequest?.url.path == "/api/auth/providers/apple/native/complete")
        #expect(transport.lastRequest?.headers["Cookie"] != nil)
        _ = await expectAPIError { _ = try await client.completeAccountProvider(credential) }
        _ = await expectAPIError { _ = try await client.completeAccountProvider(.password(email: "a", password: "b")) }
    }

    @Test("033-FR-007 033-FR-008 unlink and password send the proof and owner")
    func unlinkAndPassword() async throws {
        let methods = #"{"account_id":"owner","email":"max@example.com","email_verified":true,"email_delivery":"available","has_password":true,"methods":[]}"#
        let transport = ScriptedTransport([Fixture.json(200, #"{"methods":\#(methods),"signed_out":false}"#), Fixture.noContent()])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let result = try await client.unlinkProvider(.google, proof: proof, expectedAccountID: "owner")
        #expect(!result.signedOut)
        #expect(transport.lastRequest?.url.path == "/api/account/auth-methods/google/unlink")
        try await client.setAccountPassword("long new password", proof: proof, expectedAccountID: "owner")
        #expect(transport.lastRequest?.url.path == "/api/account/auth-password")
        #expect(transport.lastRequest?.bodyText?.contains(#""new_password":"long new password""#) == true)
    }

    @Test("033-FR-009 033-FR-010 export returns the named ZIP and delete the purge date")
    func exportAndDelete() async throws {
        let zip = HTTPResponse(
            statusCode: 200,
            headers: ["content-type": "application/zip", "content-disposition": #"attachment; filename="brainbuddy-export-2026.zip""#],
            body: Data([0x50, 0x4b]))
        let transport = ScriptedTransport([
            .respond(zip),
            Fixture.json(202, #"{"deletion_requested_at":"2026-10-16T12:00:00Z","purge_at":"2026-10-30T12:00:00Z"}"#),
        ])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let export = try await client.exportAccount(proof: proof, expectedAccountID: "owner")
        #expect(export.suggestedFileName == "brainbuddy-export-2026.zip")
        #expect(transport.lastRequest?.url.path == "/api/account/auth-export")
        let deletion = try await client.deleteAccount(proof: proof, expectedAccountID: "owner")
        #expect(deletion.purgeAt == Fixture.utc(2026, 10, 30, 12))
        #expect(transport.lastRequest?.url.path == "/api/account/auth-delete")
    }
}
