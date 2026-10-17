import BrainBuddyAPI
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Scripted server for the Account screens. Every call is recorded; answers are set per test.
final class FakeAccountRemote: AccountSecurityRemote, @unchecked Sendable {  // @unchecked: every field is guarded by `lock`
    private let lock = NSLock()
    private var _calls: [String] = []
    private var _summary: AccountSummaryDTO
    private var _methods: AccountAuthMethodsDTO
    private var _availability: AuthMethodsDTO
    private var _failure: APIError?
    private var _completion: AuthCompletionDTO?
    private var _unlink: AccountUnlinkDTO?

    init(summary: AccountSummaryDTO = AccountFixture.summary(), methods: AccountAuthMethodsDTO = AccountFixture.methods(),
         availability: AuthMethodsDTO = AccountFixture.availability()) {
        _summary = summary
        _methods = methods
        _availability = availability
    }

    var calls: [String] { lock.withLock { _calls } }
    func fail(with error: APIError?) { lock.withLock { _failure = error } }
    func complete(with completion: AuthCompletionDTO) { lock.withLock { _completion = completion } }
    func setMethods(_ methods: AccountAuthMethodsDTO) { lock.withLock { _methods = methods } }
    func setUnlink(_ result: AccountUnlinkDTO) { lock.withLock { _unlink = result } }

    private func record(_ call: String) throws(APIError) {
        let failure: APIError? = lock.withLock {
            _calls.append(call)
            return _failure
        }
        if let failure { throw failure }
    }

    func accountSummary() async throws(APIError) -> AccountSummaryDTO { try record("summary"); return lock.withLock { _summary } }
    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO { try record("methods"); return lock.withLock { _methods } }
    func authMethods() async throws(APIError) -> AuthMethodsDTO { try record("availability"); return lock.withLock { _availability } }

    func updateProfile(displayName: String, expectedOwner: String) async throws(APIError) -> AccountSummaryDTO {
        try record("profile:\(displayName):\(expectedOwner)")
        return lock.withLock {
            _summary = AccountSummaryDTO(id: _summary.id, email: _summary.email, displayName: displayName.isEmpty ? nil : displayName,
                                         completedTaskCount: _summary.completedTaskCount)
            return _summary
        }
    }

    func confirmPassword(_ currentPassword: String, action: AccountAction, expectedAccountID: String) async throws(APIError) -> RecentProof {
        try record("confirm:\(action.rawValue):\(expectedAccountID)")
        return AccountFixture.proof
    }

    func requestEmailCode(
        email: String, purpose: NativeEmailPurpose, clientChallenge: String,
        expectedAccountID: String?, action: String?, recentProof: String?, providerAttemptID: String?
    ) async throws(APIError) -> AuthChallengeDTO {
        try record("code:\(purpose.rawValue):\(email):\(action ?? "-"):\(recentProof == nil ? "no-proof" : "proof"):\(expectedAccountID ?? "-")")
        return AccountFixture.challenge
    }

    func resendEmailCode(challengeID: String, verifier: String) async throws(APIError) -> AuthChallengeDTO {
        try record("resend:\(verifier)")
        return AccountFixture.challenge
    }

    func verifyAccountEmailCode(challengeID: String, code: String, verifier: String, recentProof: RecentProof?) async throws(APIError) -> AuthCompletionDTO {
        try record("verify:\(code):\(verifier):\(recentProof == nil ? "no-proof" : "proof")")
        return lock.withLock { _completion } ?? .reauthenticated(proof: AccountFixture.proof.value, expiresAt: AccountFixture.proof.expiresAt)
    }

    func startProvider(
        _ provider: NativeAuthProvider, clientChallenge: String, purpose: String,
        expectedAccountID: String?, action: String?, recentProof: String?
    ) async throws(APIError) -> ProviderStartDTO {
        try record("provider:\(provider.rawValue):\(purpose):\(action ?? "-"):\(recentProof == nil ? "no-proof" : "proof")")
        return AccountFixture.providerStart
    }

    func completeAccountProvider(_ credential: NativeSignInCredential) async throws(APIError) -> AuthCompletionDTO {
        try record("provider-complete")
        return lock.withLock { _completion } ?? .reauthenticated(proof: AccountFixture.proof.value, expiresAt: AccountFixture.proof.expiresAt)
    }

    func unlinkProvider(_ provider: NativeAuthProvider, proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountUnlinkDTO {
        try record("unlink:\(provider.rawValue):\(expectedAccountID)")
        return lock.withLock { _unlink }!
    }

    func setAccountPassword(_ newPassword: String, proof: RecentProof, expectedAccountID: String) async throws(APIError) {
        try record("password:\(expectedAccountID)")
    }

    func exportAccount(proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountExport {
        try record("export:\(expectedAccountID)")
        return AccountExport(suggestedFileName: "brainbuddy-export.zip", data: Data([0x50, 0x4b]))
    }

    func deleteAccount(proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountDeletionDTO {
        try record("delete:\(expectedAccountID)")
        return try! BrainBuddyAPI.makeDecoder().decode(
            AccountDeletionDTO.self,
            from: Data(#"{"deletion_requested_at":"2026-10-16T12:00:00Z","purge_at":"2026-10-30T12:00:00Z"}"#.utf8))
    }
}

enum AccountFixture {
    static let owner = "user_owner"
    static let now = Date(timeIntervalSince1970: 1_800_000_000)
    static let proof = RecentProof(value: String(repeating: "p", count: 43), expiresAt: now.addingTimeInterval(300))
    static let expired = RecentProof(value: String(repeating: "p", count: 43), expiresAt: now.addingTimeInterval(-1))

    static func summary(id: String = owner, name: String? = "Max", completed: Int = 214) -> AccountSummaryDTO {
        AccountSummaryDTO(id: id, email: "max@example.com", displayName: name, completedTaskCount: completed)
    }

    static func methods(
        id: String = owner, verified: Bool = true, hasPassword: Bool = true, extra: String = #",{"method":"apple","state":"active","usable":true,"connected_at":null}"#
    ) -> AccountAuthMethodsDTO {
        let methods = #"[{"method":"email","state":"active","usable":true,"connected_at":null}"# + extra + "]"
        let json = #"{"account_id":"\#(id)","email":"max@example.com","email_verified":\#(verified),"email_delivery":"available","has_password":\#(hasPassword),"methods":\#(methods)}"#
        return try! BrainBuddyAPI.makeDecoder().decode(AccountAuthMethodsDTO.self, from: Data(json.utf8))
    }

    static func availability(google: Bool = true, apple: Bool = true, email: Bool = true) -> AuthMethodsDTO {
        let json = #"{"password":true,"google":\#(google),"apple":\#(apple),"email":\#(email),"web_account_origin":null}"#
        return try! BrainBuddyAPI.makeDecoder().decode(AuthMethodsDTO.self, from: Data(json.utf8))
    }

    static let challenge = try! BrainBuddyAPI.makeDecoder().decode(
        AuthChallengeDTO.self,
        from: Data(#"{"challenge_id":"challenge","expires_at":"2026-10-16T12:10:00Z","resend_at":"2026-10-16T12:01:00Z","message":"neutral"}"#.utf8))

    static let providerStart = try! BrainBuddyAPI.makeDecoder().decode(
        ProviderStartDTO.self,
        from: Data(#"{"attempt_id":"attempt","state":"state","nonce":"nonce","authorization_url":null}"#.utf8))

    static func user(_ id: String = owner, email: String = "max@example.com") -> MeDTO { MeDTO(id: id, email: email) }

    @MainActor
    static func model(_ remote: FakeAccountRemote, now: Date = now) -> AccountSecurityModel {
        AccountSecurityModel(
            accountID: owner, remote: remote,
            clientProof: { AccountClientProof(verifier: "verifier", challenge: "challenge") },
            now: { now })
    }
}

@MainActor
@Suite("033 iPhone account screens")
struct AccountSecurityModelTests {
    @Test("033-FR-001 the Account header reads the linked account: name, email and steps taken")
    func header() async {
        let model = AccountFixture.model(FakeAccountRemote())
        await model.load()
        #expect(model.phase == .ready)
        #expect(model.title == "Max")
        #expect(model.subtitle == "max@example.com · 214 steps taken")
    }

    @Test("033-FR-001 without a name the header goes by the email; one step is singular")
    func headerWithoutName() async {
        let model = AccountFixture.model(FakeAccountRemote(summary: AccountFixture.summary(name: "  ", completed: 1)))
        await model.load()
        #expect(model.title == "max@example.com")
        #expect(model.subtitle == "max@example.com · 1 step taken")
    }

    @Test("033-FR-012 another account's answer is never shown")
    func wrongAccount() async {
        let model = AccountFixture.model(FakeAccountRemote(methods: AccountFixture.methods(id: "someone_else")))
        await model.load()
        #expect(model.phase == .failed(.wrongAccount))
        #expect(model.summary == nil)
        #expect(model.methods == nil)
    }

    @Test("033-FR-012 a lost answer reads as uncertain and keeps its reference ID")
    func uncertain() async {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        remote.fail(with: APIError(kind: .network("lost"), message: "x", referenceID: "ref-1", requestMayHaveBeenSent: true))
        await #expect(throws: AccountActionFailure(message: AccountActionFailure.uncertain.message, referenceID: "ref-1", isUncertain: true)) {
            _ = try await model.export(proof: AccountFixture.proof)
        }
    }

    @Test("033-FR-002 saving the name trims it and binds it to the shown account")
    func saveName() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        try await model.saveName("  Ada  ")
        #expect(remote.calls.last == "profile:Ada:\(AccountFixture.owner)")
        #expect(model.title == "Ada")
        try await model.saveName("")
        #expect(model.title == "max@example.com")
    }

    @Test("033-FR-003 rows: verified email, Apple connected, Google not connected, password set")
    func rows() async {
        let model = AccountFixture.model(FakeAccountRemote())
        await model.load()
        #expect(model.emailRow == AccountMethodRow(
            kind: .email, title: "max@example.com", summary: "Verified",
            detail: "Verified · codes and password recovery work", action: .change))
        #expect(model.signInRows.map(\.kind) == [.apple, .google, .password])
        #expect(model.signInRows.map(\.summary) == ["Connected", "Not connected", "Set"])
        #expect(model.signInRows.map(\.actionTitle) == ["Remove", "Connect", "Change"])
        #expect(model.signInRows[2].detail == "Set · also used for Mac sign-in")
        #expect(model.summaryRows.map(\.kind) == [.email, .apple, .google, .password])
    }

    @Test("033-FR-003 a provider the server doesn't offer and the account never connected is left out")
    func unofferedProvider() async {
        let remote = FakeAccountRemote(methods: AccountFixture.methods(hasPassword: false, extra: ""), availability: AccountFixture.availability(google: false, apple: false))
        let model = AccountFixture.model(remote)
        await model.load()
        #expect(model.signInRows.map(\.kind) == [.password])
        #expect(model.signInRows[0].actionTitle == "Add")
    }

    @Test("033-FR-006 an unverified address offers Verify")
    func unverified() async {
        let model = AccountFixture.model(FakeAccountRemote(methods: AccountFixture.methods(verified: false)))
        await model.load()
        #expect(model.emailRow?.action == .verify)
        #expect(model.emailRow?.summary == "Not verified")
        #expect(model.confirmationOptions.emailCode == false)
    }

    @Test("033-FR-004 only methods already connected can confirm it's you")
    func confirmationOptions() async {
        let model = AccountFixture.model(FakeAccountRemote())
        await model.load()
        #expect(model.confirmationOptions == AccountConfirmationOptions(password: true, emailCode: true, providers: [.apple]))
    }

    @Test("033-FR-004 033-SC-002 confirming by password binds the proof to the action and the account")
    func confirmPassword() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let proof = try await model.confirm(password: "secret", for: .delete)
        #expect(proof == AccountFixture.proof)
        #expect(remote.calls.last == "confirm:delete:\(AccountFixture.owner)")
        remote.fail(with: APIError(kind: .rejected, message: "Authentication could not be completed.", referenceID: "ref-2", statusCode: 403))
        await #expect(throws: AccountActionFailure(message: AccountActionFailure.notConfirmed.message, referenceID: "ref-2")) {
            _ = try await model.confirm(password: "wrong", for: .delete)
        }
    }

    @Test("033-FR-004 033-SC-002 an expired proof is refused before anything is sent")
    func expiredProof() async {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let before = remote.calls
        await #expect(throws: AccountActionFailure.proofExpired) { _ = try await model.delete(proof: AccountFixture.expired) }
        await #expect(throws: AccountActionFailure.proofExpired) { _ = try await model.export(proof: AccountFixture.expired) }
        await #expect(throws: AccountActionFailure.proofExpired) {
            try await model.setPassword("long new password", repeated: "long new password", proof: AccountFixture.expired)
        }
        await #expect(throws: AccountActionFailure.proofExpired) { _ = try await model.remove(.apple, proof: AccountFixture.expired) }
        await #expect(throws: AccountActionFailure.proofExpired) {
            _ = try await model.startEmailChange(to: "new@example.com", proof: AccountFixture.expired)
        }
        #expect(remote.calls == before)
    }

    @Test("033-FR-004 an emailed code to the account's own address confirms it's you")
    func confirmByCode() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let step = try await model.sendConfirmationCode(for: .export)
        #expect(remote.calls.last == "code:reauth:max@example.com:export:no-proof:\(AccountFixture.owner)")
        await #expect(throws: AccountActionFailure(message: "Enter the 6-digit code.")) { _ = try await model.submit(code: "12", for: step) }
        let result = try await model.submit(code: "123 456", for: step)
        #expect(result == .confirmed(AccountFixture.proof))
        #expect(remote.calls.last == "verify:123456:verifier:no-proof")
    }

    @Test("033-FR-004 Apple or Google confirms through reauth; connecting needs a proof first")
    func providerConfirmation() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let attempt = try await model.startProvider(.apple, linking: false, action: .delete, proof: nil)
        #expect(attempt.verifier == "verifier")
        #expect(remote.calls.last == "provider:apple:reauth:delete:no-proof")
        let proof = try await model.finishProviderConfirmation(.apple(attemptID: "a", state: "s", authorizationCode: "c", identityToken: "t", verifier: "v"))
        #expect(proof == AccountFixture.proof)
        await #expect(throws: AccountActionFailure.proofExpired) { _ = try await model.startProvider(.google, linking: true, action: .linkGoogle, proof: nil) }
        _ = try await model.startProvider(.google, linking: true, action: .linkGoogle, proof: AccountFixture.proof)
        #expect(remote.calls.last == "provider:google:link:link:google:proof")
    }

    @Test("033-FR-005 changing the email sends a code to the new address and reloads after it lands")
    func changeEmail() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        await #expect(throws: AccountActionFailure(message: "Enter an email address.")) {
            _ = try await model.startEmailChange(to: "nope", proof: AccountFixture.proof)
        }
        let step = try await model.startEmailChange(to: " new@example.com ", proof: AccountFixture.proof)
        #expect(step.email == "new@example.com")
        #expect(remote.calls.last == "code:change_email:new@example.com:change_email:proof:\(AccountFixture.owner)")
        _ = try await model.resend(step)
        #expect(remote.calls.last == "resend:verifier")
        remote.complete(with: .changedEmail(AccountFixture.user(email: "new@example.com")))
        let result = try await model.submit(code: "482913", for: step)
        #expect(result == .changed(email: "new@example.com"))
        #expect(remote.calls.suffix(4).first == "verify:482913:verifier:proof")
        #expect(remote.calls.suffix(3).contains("summary"))
    }

    @Test("033-FR-005 a change confirmed for another account is refused")
    func changeEmailWrongAccount() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let step = try await model.startEmailChange(to: "new@example.com", proof: AccountFixture.proof)
        remote.complete(with: .changedEmail(AccountFixture.user("someone_else")))
        await #expect(throws: AccountActionFailure.wrongAccount) { _ = try await model.submit(code: "482913", for: step) }
    }

    @Test("033-FR-006 verifying the address sends a code to it with the proof")
    func verifyEmail() async throws {
        let remote = FakeAccountRemote(methods: AccountFixture.methods(verified: false))
        let model = AccountFixture.model(remote)
        await model.load()
        let step = try await model.startEmailVerification(proof: AccountFixture.proof)
        #expect(remote.calls.last == "code:verify_email:max@example.com:verify_email:proof:\(AccountFixture.owner)")
        remote.complete(with: .verifiedEmail(AccountFixture.user()))
        #expect(try await model.submit(code: "111111", for: step) == .verified)
    }

    @Test("033-FR-007 removing a provider updates the rows and reports when this session ended")
    func removeProvider() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        remote.setUnlink(try BrainBuddyAPI.makeDecoder().decode(
            AccountUnlinkDTO.self,
            from: Data(#"{"methods":{"account_id":"user_owner","email":"max@example.com","email_verified":true,"email_delivery":"available","has_password":true,"methods":[]},"signed_out":true}"#.utf8)))
        let signedOut = try await model.remove(.apple, proof: AccountFixture.proof)
        #expect(signedOut)
        #expect(remote.calls.last == "unlink:apple:\(AccountFixture.owner)")
        #expect(model.signInRows.first?.kind == .apple)
        #expect(model.signInRows.first?.actionTitle == "Connect")
    }

    @Test("033-FR-007 connecting finishes only for the shown account")
    func link() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let credential = NativeSignInCredential.browserGrant(attemptID: "a", state: "s", handoffCode: "h", verifier: "v")
        remote.complete(with: .linked(AccountFixture.user("someone_else")))
        await #expect(throws: AccountActionFailure.wrongAccount) { try await model.finishLink(credential) }
        remote.complete(with: .existingAccountRequired(message: "Sign in to your existing account."))
        await #expect(throws: AccountActionFailure(message: "Sign in to your existing account.")) { try await model.finishLink(credential) }
        remote.complete(with: .linked(AccountFixture.user()))
        try await model.finishLink(credential)
        #expect(remote.calls.suffix(3).contains("methods"))
    }

    @Test("033-FR-008 the password needs 12 characters and a matching repeat before anything is sent")
    func password() async throws {
        #expect(AccountSecurityModel.passwordProblem("short", repeated: "short") == "At least 12 characters. Longer is better.")
        #expect(AccountSecurityModel.passwordProblem("long enough pw", repeated: "long enough pX") == "New passwords don't match.")
        #expect(AccountSecurityModel.passwordProblem("long enough pw", repeated: "long enough pw") == nil)
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let before = remote.calls
        await #expect(throws: AccountActionFailure(message: "New passwords don't match.")) {
            try await model.setPassword("long enough pw", repeated: "other", proof: AccountFixture.proof)
        }
        #expect(remote.calls == before)
        try await model.setPassword("long enough pw", repeated: "long enough pw", proof: AccountFixture.proof)
        #expect(remote.calls.contains("password:\(AccountFixture.owner)"))
    }

    @Test("033-FR-009 export returns the ZIP for the shown account")
    func export() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let export = try await model.export(proof: AccountFixture.proof)
        #expect(export.suggestedFileName == "brainbuddy-export.zip")
        #expect(remote.calls.last == "export:\(AccountFixture.owner)")
    }

    @Test("033-FR-010 deleting returns the purge date, 14 days on")
    func delete() async throws {
        let remote = FakeAccountRemote()
        let model = AccountFixture.model(remote)
        await model.load()
        let purgeAt = try await model.delete(proof: AccountFixture.proof)
        #expect(remote.calls.last == "delete:\(AccountFixture.owner)")
        #expect(purgeAt == Date(timeIntervalSince1970: 1_793_361_600))
    }
}
