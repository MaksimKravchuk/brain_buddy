import Foundation

// Account management on the iPhone (spec 033): the signed-in session changes its own
// account. Every change but the name first needs a recent proof (`POST /auth/confirm/password`,
// an email code with purpose `reauth`, or a connected provider), bound to the account id the
// screen shows and to one action. All requests carry the device's session.

/// The one change a recent proof authorizes (`Action` in the backend contract).
public enum AccountAction: String, Sendable, Hashable, CaseIterable {
    case verifyEmail = "verify_email"
    case changeEmail = "change_email"
    case linkGoogle = "link:google"
    case linkApple = "link:apple"
    case unlinkGoogle = "unlink:google"
    case unlinkApple = "unlink:apple"
    case password
    case export
    case delete

    public static func link(_ provider: NativeAuthProvider) -> AccountAction {
        provider == .google ? .linkGoogle : .linkApple
    }

    public static func unlink(_ provider: NativeAuthProvider) -> AccountAction {
        provider == .google ? .unlinkGoogle : .unlinkApple
    }
}

/// A short-lived proof that the person just confirmed it is them. Redacted: it authorizes a change.
public struct RecentProof: Hashable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    public let value: String
    public let expiresAt: Date

    public init(value: String, expiresAt: Date) {
        self.value = value
        self.expiresAt = expiresAt
    }

    public var description: String { "Recent proof (redacted)" }
    public var debugDescription: String { description }
}

/// `POST /account/auth-methods/{provider}/unlink` → the methods left and whether this session ended.
public struct AccountUnlinkDTO: Decodable, Hashable, Sendable {
    public let methods: AccountAuthMethodsDTO
    public let signedOut: Bool
    enum CodingKeys: String, CodingKey { case methods, signedOut = "signed_out" }
}

/// `POST /account/auth-delete` → when the account is erased for good.
public struct AccountDeletionDTO: Decodable, Hashable, Sendable {
    public let deletionRequestedAt: Date
    public let purgeAt: Date
    enum CodingKeys: String, CodingKey {
        case deletionRequestedAt = "deletion_requested_at", purgeAt = "purge_at"
    }
}

extension BrainBuddyAPIClient {
    /// `PATCH /account/profile`; an empty name clears it. Bound to `expectedOwner`.
    public func updateProfile(displayName: String, expectedOwner: String) async throws(APIError) -> AccountSummaryDTO {
        let body = try encode(["display_name": displayName])
        let endpoint = Endpoint(.patch, ["account", "profile"], body: body, headers: [Self.expectedOwnerHeader: expectedOwner])
        return try decode(try await exchange(endpoint))
    }

    /// `POST /auth/confirm/password` → a proof for `action`.
    public func confirmPassword(
        _ currentPassword: String, action: AccountAction, expectedAccountID: String
    ) async throws(APIError) -> RecentProof {
        let body = ["current_password": currentPassword, "action": action.rawValue, "expected_account_id": expectedAccountID]
        return try Self.proof(from: try decode(try await nativePost(["auth", "confirm", "password"], body, status: 200)))
    }

    /// `POST /auth/email/verify` on the signed-in session: a `reauth`, `change_email` or
    /// `verify_email` code. `recentProof` is the proof a change or verification was started with.
    public func verifyAccountEmailCode(
        challengeID: String, code: String, verifier: String, recentProof: RecentProof? = nil
    ) async throws(APIError) -> AuthCompletionDTO {
        var body = ["challenge_id": challengeID, "code": code, "client_verifier": verifier]
        body["recent_proof"] = recentProof?.value
        return try await accountCompletion(["auth", "email", "verify"], body)
    }

    /// Finishes a provider `link` or `reauth` started with `startProvider` on the signed-in session.
    public func completeAccountProvider(_ credential: NativeSignInCredential) async throws(APIError) -> AuthCompletionDTO {
        switch credential {
        case .browserGrant(let attemptID, let state, let grant, let verifier):
            return try await accountCompletion(
                ["auth", "providers", "complete"],
                ["attempt_id": attemptID, "state": state, "handoff_code": grant, "client_verifier": verifier])
        case .apple(let attemptID, let state, let code, let token, let verifier):
            return try await accountCompletion(
                ["auth", "providers", "apple", "native", "complete"],
                ["attempt_id": attemptID, "state": state, "authorization_code": code, "identity_token": token,
                 "client_verifier": verifier])
        case .password, .emailCode, .invite:
            throw Self.unexpectedAccountResponse()
        }
    }

    /// `POST /account/auth-methods/{provider}/unlink`.
    public func unlinkProvider(
        _ provider: NativeAuthProvider, proof: RecentProof, expectedAccountID: String
    ) async throws(APIError) -> AccountUnlinkDTO {
        let body = ["recent_proof": proof.value, "expected_account_id": expectedAccountID]
        return try decode(try await nativePost(["account", "auth-methods", provider.rawValue, "unlink"], body, status: 200))
    }

    /// `POST /account/auth-password`: adds or replaces the password; other sessions end.
    public func setAccountPassword(
        _ newPassword: String, proof: RecentProof, expectedAccountID: String
    ) async throws(APIError) {
        let body = ["new_password": newPassword, "recent_proof": proof.value, "expected_account_id": expectedAccountID]
        _ = try await nativePost(["account", "auth-password"], body, status: 204)
    }

    /// `POST /account/auth-export` → the ZIP and the server's suggested name.
    public func exportAccount(proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountExport {
        let body = ["recent_proof": proof.value, "expected_account_id": expectedAccountID]
        let exchange = try await nativePost(["account", "auth-export"], body, status: 200)
        let name = AccountExport.fileName(fromContentDisposition: exchange.response.header("Content-Disposition"))
        return AccountExport(suggestedFileName: name, data: exchange.response.body)
    }

    /// `POST /account/auth-delete` (202): every session ends; the account is erased at `purgeAt`.
    public func deleteAccount(proof: RecentProof, expectedAccountID: String) async throws(APIError) -> AccountDeletionDTO {
        let body = ["recent_proof": proof.value, "expected_account_id": expectedAccountID]
        return try decode(try await nativePost(["account", "auth-delete"], body, status: 202))
    }

    static let expectedOwnerHeader = "X-BrainBuddy-Expected-Owner"

    /// An account flow's completion. It never starts or replaces a session, so a cookie set
    /// beside it is a contract breach.
    private func accountCompletion(_ path: [String], _ body: [String: String]) async throws(APIError) -> AuthCompletionDTO {
        let exchange = try await nativePost(path, body, status: 200)
        guard exchange.sessionUpdate == nil else { throw Self.unexpectedAccountResponse() }
        let completion: AuthCompletionDTO = try decode(exchange)
        if case .signedIn = completion { throw Self.unexpectedAccountResponse() }
        return completion
    }

    static func proof(from completion: AuthCompletionDTO) throws(APIError) -> RecentProof {
        guard case .reauthenticated(let value, let expiresAt) = completion else { throw unexpectedAccountResponse() }
        return RecentProof(value: value, expiresAt: expiresAt)
    }

    static func unexpectedAccountResponse() -> APIError {
        APIError(
            kind: .decoding("Unexpected account response"),
            message: "The server returned an unexpected account response.", requestMayHaveBeenSent: true)
    }
}
