import BrainBuddyAPI
import Foundation
import Observation

// The iPhone Account screens (spec 033, design boards 25–28): who you are, how you sign in and
// your data. The screens render this model and call its actions; every rule about proofs, the
// account they belong to and what a change may do is here, where it runs on Linux.

/// What the model needs from the server; `BrainBuddyAPIClient` conforms.
public protocol AccountSecurityRemote: Sendable {
    func accountSummary() async throws(APIError) -> AccountSummaryDTO
    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO
    func authMethods() async throws(APIError) -> AuthMethodsDTO
    func updateProfile(displayName: String, expectedOwner: String) async throws(APIError) -> AccountSummaryDTO
    func confirmPassword(_ currentPassword: String, action: AccountAction, expectedAccountID: String) async throws(APIError) -> RecentProof
    func requestEmailCode(
        email: String, purpose: NativeEmailPurpose, clientChallenge: String,
        expectedAccountID: String?, action: String?, recentProof: String?, providerAttemptID: String?
    ) async throws(APIError) -> AuthChallengeDTO
    func resendEmailCode(challengeID: String, verifier: String) async throws(APIError) -> AuthChallengeDTO
    func verifyAccountEmailCode(challengeID: String, code: String, verifier: String, recentProof: RecentProof?) async throws(APIError) -> AuthCompletionDTO
    func startProvider(
        _ provider: NativeAuthProvider, clientChallenge: String, purpose: String,
        expectedAccountID: String?, action: String?, recentProof: String?
    ) async throws(APIError) -> ProviderStartDTO
    func completeAccountProvider(_ credential: NativeSignInCredential) async throws(APIError) -> AuthCompletionDTO
    func unlinkProvider(_ provider: NativeAuthProvider, proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountUnlinkDTO
    func setAccountPassword(_ newPassword: String, proof: RecentProof, expectedAccountID: String) async throws(APIError)
    func exportAccount(proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountExport
    func deleteAccount(proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountDeletionDTO
}

extension BrainBuddyAPIClient: AccountSecurityRemote {}

/// A PKCE pair: the verifier stays on the device, the challenge goes to the server.
public struct AccountClientProof: Sendable, CustomStringConvertible {
    public let verifier: String
    public let challenge: String
    public init(verifier: String, challenge: String) {
        self.verifier = verifier
        self.challenge = challenge
    }
    public var description: String { "Client proof (redacted)" }
}

/// One emailed code in flight: to confirm it is you, to verify the address or to change it.
public struct AccountEmailCode: Sendable, Equatable {
    public enum Purpose: Sendable, Equatable { case confirm(AccountAction), verify, change }
    public let purpose: Purpose
    /// Where the code went.
    public let email: String
    public let challenge: AuthChallengeDTO
    let verifier: String
    /// The proof the verification or change was started with.
    let proof: RecentProof?

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.purpose == rhs.purpose && lhs.email == rhs.email && lhs.challenge == rhs.challenge
    }
}

/// A provider sign-in in flight; the app shows Apple's or Google's own sheet in between.
public struct AccountProviderAttempt: Sendable {
    public let provider: NativeAuthProvider
    public let start: ProviderStartDTO
    public let verifier: String
}

/// A failed action, in words the screen shows as they are.
public struct AccountActionFailure: Error, Equatable, Sendable {
    public let message: String
    public let referenceID: String?
    /// The request may have changed the account; the screen reloads before anything else.
    public let isUncertain: Bool

    public init(message: String, referenceID: String? = nil, isUncertain: Bool = false) {
        self.message = message
        self.referenceID = referenceID
        self.isUncertain = isUncertain
    }

    public static let wrongAccount = AccountActionFailure(
        message: "Use the account linked to this iPhone. Sign in again before continuing.")
    public static let proofExpired = AccountActionFailure(
        message: "Your confirmation expired. Confirm it's you again.")
    public static let notConfirmed = AccountActionFailure(
        message: "That didn't confirm it's you. Try again or use another connected method.")
    public static let uncertain = AccountActionFailure(
        message: "We couldn't confirm whether this finished. Check your account before trying again.",
        isUncertain: true)

    init(_ error: APIError) {
        if error.isUncertainOutcome {
            self.init(message: Self.uncertain.message, referenceID: error.referenceID, isUncertain: true)
        } else {
            self.init(message: error.message, referenceID: error.referenceID)
        }
    }
}

/// One row of the "Ways to sign in" group (board 26) or of its summary on the Account screen (board 25).
public struct AccountMethodRow: Sendable, Equatable, Identifiable {
    public enum Kind: String, Sendable { case email, apple, google, password }
    public enum Action: Sendable, Equatable { case change, verify, connect, reconnect, remove, add }
    public let kind: Kind
    public let title: String
    /// Board 25's short state: "Verified", "Connected", "Not connected", "Set".
    public let summary: String
    /// Board 26's line under the title.
    public let detail: String
    /// The one thing you can do to it, if any.
    public let action: Action?
    public var id: Kind { kind }

    public var actionTitle: String? {
        switch action {
        case .change: "Change"
        case .verify: "Verify"
        case .connect: "Connect"
        case .reconnect: "Reconnect"
        case .remove: "Remove"
        case .add: "Add"
        case nil: nil
        }
    }
}

/// How the person can confirm it is them: only methods already connected to this account.
public struct AccountConfirmationOptions: Sendable, Equatable {
    public let password: Bool
    public let emailCode: Bool
    public let providers: [NativeAuthProvider]
    public var isEmpty: Bool { !password && !emailCode && providers.isEmpty }
}

@MainActor
@Observable
public final class AccountSecurityModel {
    public enum Phase: Equatable, Sendable {
        case loading
        case ready
        case failed(AccountActionFailure)
    }

    /// The account the screen shows; every proof and change is bound to it.
    public let accountID: String
    public private(set) var phase: Phase = .loading
    public private(set) var summary: AccountSummaryDTO?
    public private(set) var methods: AccountAuthMethodsDTO?
    public private(set) var availability: AuthMethodsDTO?

    /// The password rule the server enforces (`password_policy`), checked before a round trip.
    public static let minimumPasswordLength = 12

    @ObservationIgnored private let remote: any AccountSecurityRemote
    @ObservationIgnored private let makeClientProof: @Sendable () throws -> AccountClientProof
    @ObservationIgnored private let now: @Sendable () -> Date

    public init(
        accountID: String, remote: any AccountSecurityRemote,
        clientProof: @escaping @Sendable () throws -> AccountClientProof,
        now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.accountID = accountID
        self.remote = remote
        self.makeClientProof = clientProof
        self.now = now
    }

    // MARK: Loading

    /// Reads the account, its methods and what the server offers. A response for another
    /// account is never shown.
    public func load() async {
        if summary == nil { phase = .loading }
        do {
            async let summary = remote.accountSummary()
            async let methods = remote.accountAuthMethods()
            async let availability = remote.authMethods()
            let loaded = try await (summary, methods, availability)
            guard loaded.0.id == accountID, loaded.1.accountID == accountID else {
                self.summary = nil
                self.methods = nil
                phase = .failed(.wrongAccount)
                return
            }
            self.summary = loaded.0
            self.methods = loaded.1
            self.availability = loaded.2
            phase = .ready
        } catch let error as APIError {
            phase = .failed(AccountActionFailure(error))
        } catch {
            phase = .failed(AccountActionFailure(message: "Couldn't load your account. Try again."))
        }
    }

    // MARK: What the screens show

    /// Board 25's large name: the name, else the email.
    public var title: String {
        let name = trimmedName
        return name.isEmpty ? (summary?.email ?? methods?.email ?? "") : name
    }

    /// Board 25's line under it: "max@example.com · 214 steps taken".
    public var subtitle: String {
        guard let summary else { return methods?.email ?? "" }
        let count = summary.completedTaskCount
        return "\(summary.email) · \(count) \(count == 1 ? "step" : "steps") taken"
    }

    public var displayName: String { trimmedName }

    private var trimmedName: String {
        summary?.displayName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    /// Board 26's email row on its own, above the ways to sign in.
    public var emailRow: AccountMethodRow? {
        guard let methods else { return nil }
        let verified = methods.emailVerified
        return AccountMethodRow(
            kind: .email, title: methods.email,
            summary: verified ? "Verified" : "Not verified",
            detail: verified
                ? "Verified · codes and password recovery work"
                : "Not verified · verify it to use codes and password recovery",
            action: verified || availability?.email != true ? .change : .verify)
    }

    /// Board 26's ways to sign in: Apple, Google, Password. A provider the server does not offer
    /// and this account never connected is left out.
    public var signInRows: [AccountMethodRow] {
        guard let methods else { return [] }
        var rows: [AccountMethodRow] = []
        for provider in [NativeAuthProvider.apple, .google] {
            let connected = methods.methods.first { $0.method.rawValue == provider.rawValue }
            let offered = provider == .apple ? availability?.apple == true : availability?.google == true
            guard connected != nil || offered else { continue }
            let title = provider == .apple ? "Apple" : "Google"
            let row: AccountMethodRow
            switch connected {
            case let method? where method.state == .active:
                row = AccountMethodRow(
                    kind: provider == .apple ? .apple : .google, title: title, summary: "Connected",
                    detail: method.usable ? "Connected to your account" : "Connected · unavailable right now",
                    action: .remove)
            case .some:
                row = AccountMethodRow(
                    kind: provider == .apple ? .apple : .google, title: title, summary: "Not connected",
                    detail: "Disconnected", action: offered ? .reconnect : nil)
            case nil:
                row = AccountMethodRow(
                    kind: provider == .apple ? .apple : .google, title: title, summary: "Not connected",
                    detail: "Not connected", action: .connect)
            }
            rows.append(row)
        }
        rows.append(
            AccountMethodRow(
                kind: .password, title: "Password", summary: methods.hasPassword ? "Set" : "Not set",
                detail: methods.hasPassword ? "Set · also used for Mac sign-in" : "Not set · the Mac signs in with a password",
                action: methods.hasPassword ? .change : .add))
        return rows
    }

    /// Board 25's "Sign in" group: the email first, then the ways to sign in.
    public var summaryRows: [AccountMethodRow] {
        [emailRow].compactMap { $0 } + signInRows
    }

    public var confirmationOptions: AccountConfirmationOptions {
        guard let methods else { return AccountConfirmationOptions(password: false, emailCode: false, providers: []) }
        let usable = Set(methods.methods.filter { $0.usable && $0.state == .active }.map(\.method))
        let emailCode = methods.emailVerified && methods.emailDelivery == .available
            && availability?.email == true && usable.contains(.email)
        let providers = [NativeAuthProvider.apple, .google].filter { provider in
            let offered = provider == .apple ? availability?.apple == true : availability?.google == true
            return offered && usable.contains(provider == .apple ? .apple : .google)
        }
        return AccountConfirmationOptions(password: methods.hasPassword, emailCode: emailCode, providers: providers)
    }

    /// Why a new password can't be saved yet, or nil.
    public static func passwordProblem(_ password: String, repeated: String) -> String? {
        if password.count < minimumPasswordLength { return "At least \(minimumPasswordLength) characters. Longer is better." }
        if password != repeated { return "New passwords don't match." }
        return nil
    }

    // MARK: Profile

    /// Saves the name; an empty one clears it, so the account goes by its email.
    public func saveName(_ name: String) async throws(AccountActionFailure) {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let updated = try await call { () throws(APIError) in
            try await remote.updateProfile(displayName: trimmed, expectedOwner: accountID)
        }
        guard updated.id == accountID else { throw .wrongAccount }
        summary = updated
    }

    // MARK: Confirm it's you

    public func confirm(password: String, for action: AccountAction) async throws(AccountActionFailure) -> RecentProof {
        let proof: RecentProof
        do throws(APIError) {
            proof = try await remote.confirmPassword(password, action: action, expectedAccountID: accountID)
        } catch {
            // A wrong password is a coarse 400/403; say what it means here.
            if error.statusCode == 400 || error.statusCode == 403 {
                throw AccountActionFailure(message: AccountActionFailure.notConfirmed.message, referenceID: error.referenceID)
            }
            throw AccountActionFailure(error)
        }
        return try fresh(proof)
    }

    /// Sends a code to the account's own address to confirm `action`.
    public func sendConfirmationCode(for action: AccountAction) async throws(AccountActionFailure) -> AccountEmailCode {
        guard let email = methods?.email else { throw .wrongAccount }
        return try await sendCode(.confirm(action), to: email, purpose: .reauth, action: action, proof: nil)
    }

    /// Starts Apple or Google to confirm `action` (`reauth`) or to connect the provider (`link`,
    /// which needs `proof`).
    public func startProvider(
        _ provider: NativeAuthProvider, linking: Bool, action: AccountAction, proof: RecentProof?
    ) async throws(AccountActionFailure) -> AccountProviderAttempt {
        if linking { guard let proof else { throw .proofExpired }; _ = try fresh(proof) }
        let clientProof = try newClientProof()
        let start = try await call { () throws(APIError) in
            try await remote.startProvider(
                provider, clientChallenge: clientProof.challenge, purpose: linking ? "link" : "reauth",
                expectedAccountID: accountID, action: action.rawValue, recentProof: proof?.value)
        }
        return AccountProviderAttempt(provider: provider, start: start, verifier: clientProof.verifier)
    }

    /// The proof from a provider confirmation.
    public func finishProviderConfirmation(_ credential: NativeSignInCredential) async throws(AccountActionFailure) -> RecentProof {
        let completion = try await call { () throws(APIError) in try await remote.completeAccountProvider(credential) }
        guard case .reauthenticated(let value, let expiresAt) = completion else {
            throw AccountActionFailure(message: "Couldn't confirm with this method. Try another connected method.")
        }
        return try fresh(RecentProof(value: value, expiresAt: expiresAt))
    }

    // MARK: Email

    /// Board 27, step 1: sends a code to `newEmail`. The current address stays until step 2 succeeds.
    public func startEmailChange(to newEmail: String, proof: RecentProof) async throws(AccountActionFailure) -> AccountEmailCode {
        let address = newEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        guard address.contains("@") else { throw AccountActionFailure(message: "Enter an email address.") }
        return try await sendCode(.change, to: address, purpose: .changeEmail, action: .changeEmail, proof: try fresh(proof))
    }

    /// Sends a code to the account's own unverified address.
    public func startEmailVerification(proof: RecentProof) async throws(AccountActionFailure) -> AccountEmailCode {
        guard let email = methods?.email else { throw .wrongAccount }
        return try await sendCode(.verify, to: email, purpose: .verifyEmail, action: .verifyEmail, proof: try fresh(proof))
    }

    public func resend(_ code: AccountEmailCode) async throws(AccountActionFailure) -> AccountEmailCode {
        let challenge = try await call { () throws(APIError) in
            try await remote.resendEmailCode(challengeID: code.challenge.challengeID, verifier: code.verifier)
        }
        return AccountEmailCode(purpose: code.purpose, email: code.email, challenge: challenge, verifier: code.verifier, proof: code.proof)
    }

    public enum EmailCodeResult: Sendable, Equatable {
        /// A confirmation code: the proof for its action.
        case confirmed(RecentProof)
        /// The address is verified.
        case verified
        /// The account now uses this address.
        case changed(email: String)
    }

    /// Checks a six-digit code for any purpose.
    public func submit(code: String, for step: AccountEmailCode) async throws(AccountActionFailure) -> EmailCodeResult {
        let digits = code.filter(\.isNumber)
        guard digits.count == 6 else { throw AccountActionFailure(message: "Enter the 6-digit code.") }
        if let proof = step.proof { _ = try fresh(proof) }
        let completion = try await call { () throws(APIError) in
            try await remote.verifyAccountEmailCode(
                challengeID: step.challenge.challengeID, code: digits, verifier: step.verifier, recentProof: step.proof)
        }
        switch (step.purpose, completion) {
        case (.confirm, .reauthenticated(let value, let expiresAt)):
            return .confirmed(try fresh(RecentProof(value: value, expiresAt: expiresAt)))
        case (.verify, .verifiedEmail(let user)) where user.id == accountID:
            await load()
            return .verified
        case (.change, .changedEmail(let user)) where user.id == accountID:
            await load()
            return .changed(email: user.email)
        default:
            throw .wrongAccount
        }
    }

    // MARK: Ways to sign in

    /// Connects Apple or Google after its own sheet returned `credential`.
    public func finishLink(_ credential: NativeSignInCredential) async throws(AccountActionFailure) {
        let completion = try await call { () throws(APIError) in try await remote.completeAccountProvider(credential) }
        guard case .linked(let user) = completion, user.id == accountID else {
            if case .existingAccountRequired(let message) = completion { throw AccountActionFailure(message: message) }
            throw .wrongAccount
        }
        await load()
    }

    /// Removes Apple or Google. True when it ended this device's session too: the app then asks to
    /// sign in again with what is left, and keeps local work.
    public func remove(_ provider: NativeAuthProvider, proof: RecentProof) async throws(AccountActionFailure) -> Bool {
        let checked = try fresh(proof)
        let result = try await call { () throws(APIError) in
            try await remote.unlinkProvider(provider, proof: checked, expectedAccountID: accountID)
        }
        guard result.methods.accountID == accountID else { throw .wrongAccount }
        methods = result.methods
        return result.signedOut
    }

    /// Adds or replaces the password. Other devices are signed out; this one stays.
    public func setPassword(_ password: String, repeated: String, proof: RecentProof) async throws(AccountActionFailure) {
        if let problem = Self.passwordProblem(password, repeated: repeated) { throw AccountActionFailure(message: problem) }
        let checked = try fresh(proof)
        try await call { () throws(APIError) in
            try await remote.setAccountPassword(password, proof: checked, expectedAccountID: accountID)
        }
        await load()
    }

    // MARK: Your data

    /// A ZIP of everything the account owns, without auth secrets.
    public func export(proof: RecentProof) async throws(AccountActionFailure) -> AccountExport {
        let checked = try fresh(proof)
        return try await call { () throws(APIError) in
            try await remote.exportAccount(proof: checked, expectedAccountID: accountID)
        }
    }

    /// Requests deletion: every session ends now and the account is erased at the returned date.
    /// Signing in before then cancels it. Nothing on this device is removed.
    public func delete(proof: RecentProof) async throws(AccountActionFailure) -> Date {
        let checked = try fresh(proof)
        let result = try await call { () throws(APIError) in
            try await remote.deleteAccount(proof: checked, expectedAccountID: accountID)
        }
        return result.purgeAt
    }

    // MARK: Plumbing

    private func sendCode(
        _ purpose: AccountEmailCode.Purpose, to email: String, purpose wire: NativeEmailPurpose,
        action: AccountAction, proof: RecentProof?
    ) async throws(AccountActionFailure) -> AccountEmailCode {
        let clientProof = try newClientProof()
        let challenge = try await call { () throws(APIError) in
            try await remote.requestEmailCode(
                email: email, purpose: wire, clientChallenge: clientProof.challenge, expectedAccountID: accountID,
                action: action.rawValue, recentProof: proof?.value, providerAttemptID: nil)
        }
        return AccountEmailCode(purpose: purpose, email: email, challenge: challenge, verifier: clientProof.verifier, proof: proof)
    }

    private func newClientProof() throws(AccountActionFailure) -> AccountClientProof {
        do { return try makeClientProof() } catch {
            throw AccountActionFailure(message: "Couldn't start a secure confirmation. Try again.")
        }
    }

    /// A proof is used only before it expires.
    private func fresh(_ proof: RecentProof) throws(AccountActionFailure) -> RecentProof {
        guard proof.expiresAt > now() else { throw .proofExpired }
        return proof
    }

    private func call<T>(_ body: () async throws(APIError) -> T) async throws(AccountActionFailure) -> T {
        do throws(APIError) { return try await body() } catch { throw AccountActionFailure(error) }
    }
}
