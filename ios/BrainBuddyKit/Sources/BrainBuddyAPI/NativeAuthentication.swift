import Foundation

public enum NativeAuthProvider: String, Sendable, Codable { case google, apple }
public enum NativeEmailPurpose: String, Sendable, Codable {
    case login, recover, reauth
    case verifyEmail = "verify_email", changeEmail = "change_email", providerMailbox = "provider_mailbox"
}

public struct AuthMethodsDTO: Decodable, Hashable, Sendable {
    public let password: Bool
    public let google: Bool
    public let apple: Bool
    public let email: Bool
    public let webAccountOrigin: String?
    enum CodingKeys: String, CodingKey {
        case password, google, apple, email
        case webAccountOrigin = "web_account_origin"
    }
}

public struct AuthChallengeDTO: Decodable, Hashable, Sendable {
    public let challengeID: String
    public let expiresAt: Date
    public let resendAt: Date
    public let message: String
    enum CodingKeys: String, CodingKey {
        case challengeID = "challenge_id", expiresAt = "expires_at", resendAt = "resend_at", message
    }
}

public struct ProviderStartDTO: Decodable, Sendable, CustomStringConvertible {
    public let attemptID: String
    public let state: String
    public let nonce: String
    public let authorizationURL: String?
    public var description: String { "Provider start (redacted)" }
    enum CodingKeys: String, CodingKey {
        case attemptID = "attempt_id", state, nonce, authorizationURL = "authorization_url"
    }
}

/// The opaque, single-use handoff of `403 INVITE_REQUIRED` (027 invite-handoff contract).
/// Nothing exists on the server yet; the token only lets the invite step resubmit.
public struct InviteHandoff: Hashable, Sendable, CustomStringConvertible {
    public let pending: String
    public let expiresIn: Int
    public var description: String { "Invite handoff (redacted)" }
    public init(pending: String, expiresIn: Int) {
        self.pending = pending
        self.expiresIn = expiresIn
    }
    /// Nil unless `error` is exactly the contract's 403 with a usable token.
    init?(_ error: APIError) {
        guard error.statusCode == 403, error.detail?["code"]?.stringValue == "INVITE_REQUIRED",
            let pending = error.detail?["pending"]?.stringValue, !pending.isEmpty
        else { return nil }
        var seconds = 600
        if case .number(let value)? = error.detail?["expires_in"], value > 0, value < 86_400 { seconds = Int(value) }
        self.init(pending: pending, expiresIn: seconds)
    }
}

/// Copy of design M-03 (.03, .04, .07). Invalid and used codes share one message.
public enum InviteStepCopy {
    public static let invalid = "That invite code isn't valid or has already been used. Check it and try again."
    public static let expired = "This sign-in has expired. Start again to create your account."
    public static let tooManyAttempts = "Too many requests. Try again in a few minutes."
}

/// Each outcome grants exactly the authority named by its discriminator.
public enum AuthCompletionDTO: Decodable, Hashable, Sendable, CustomStringConvertible {
    case signedIn(MeDTO, deletionCancelled: Bool)
    case linked(MeDTO), verifiedEmail(MeDTO), changedEmail(MeDTO)
    case resetReady(grant: String, expiresAt: Date)
    case reauthenticated(proof: String, expiresAt: Date)
    case verifyMailbox(AuthChallengeDTO)
    case existingAccountRequired(message: String)
    /// A verified identity with no account: ask for an invite code (design M-03).
    case inviteRequired(InviteHandoff)

    public var description: String { "Authentication completion (redacted)" }
    enum CodingKeys: String, CodingKey {
        case status, user, message
        case deletionCancelled = "deletion_cancelled", resetGrant = "reset_grant"
        case recentProof = "recent_proof", expiresAt = "expires_at"
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        switch try c.decode(String.self, forKey: .status) {
        case "signed_in": self = .signedIn(try c.decode(MeDTO.self, forKey: .user), deletionCancelled: try c.decodeIfPresent(Bool.self, forKey: .deletionCancelled) ?? false)
        case "linked": self = .linked(try c.decode(MeDTO.self, forKey: .user))
        case "verified_email": self = .verifiedEmail(try c.decode(MeDTO.self, forKey: .user))
        case "changed_email": self = .changedEmail(try c.decode(MeDTO.self, forKey: .user))
        case "reset_ready": self = .resetReady(grant: try c.decode(String.self, forKey: .resetGrant), expiresAt: try c.decode(Date.self, forKey: .expiresAt))
        case "reauthenticated": self = .reauthenticated(proof: try c.decode(String.self, forKey: .recentProof), expiresAt: try c.decode(Date.self, forKey: .expiresAt))
        case "verify_mailbox": self = .verifyMailbox(try AuthChallengeDTO(from: decoder))
        case "existing_account_required": self = .existingAccountRequired(message: try c.decode(String.self, forKey: .message))
        default: throw DecodingError.dataCorruptedError(forKey: .status, in: c, debugDescription: "Unknown authentication outcome")
        }
    }
}

public struct AccountAuthMethodsDTO: Decodable, Hashable, Sendable {
    public struct Method: Decodable, Hashable, Sendable {
        public enum Kind: String, Decodable, Sendable { case password, email, google, apple }
        public enum State: String, Decodable, Sendable { case active, disabled }
        public let method: Kind
        public let state: State
        public let usable: Bool
        public let connectedAt: Date?
        enum CodingKeys: String, CodingKey { case method, state, usable, connectedAt = "connected_at" }
    }
    public enum Delivery: String, Decodable, Sendable { case available, disabled, unconfigured }
    public let accountID: String
    public let email: String
    public let emailVerified: Bool
    public let emailDelivery: Delivery
    public let hasPassword: Bool
    public let methods: [Method]
    enum CodingKeys: String, CodingKey {
        case accountID = "account_id", email, emailVerified = "email_verified"
        case emailDelivery = "email_delivery", hasPassword = "has_password", methods
    }
}

/// Secrets stay in active memory and are never serializable or printable.
public enum NativeSignInCredential: Sendable, CustomStringConvertible {
    case password(email: String, password: String)
    case emailCode(challengeID: String, code: String, verifier: String)
    case browserGrant(attemptID: String, state: String, handoffCode: String, verifier: String)
    case apple(attemptID: String, state: String, authorizationCode: String, identityToken: String, verifier: String)
    /// Resubmits an `INVITE_REQUIRED` handoff with the person's invite code.
    case invite(pending: String, inviteCode: String)
    public var description: String { "Native sign-in credential (redacted)" }
}

extension BrainBuddyAPIClient {
    public func authMethods() async throws(APIError) -> AuthMethodsDTO {
        try await get(["auth", "methods"], query: [("client", "ios")])
    }
    public func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO {
        try await get(["account", "auth-methods"])
    }
    public func requestEmailCode(
        email: String, purpose: NativeEmailPurpose, clientChallenge: String,
        expectedAccountID: String? = nil, action: String? = nil, recentProof: String? = nil,
        providerAttemptID: String? = nil
    ) async throws(APIError) -> AuthChallengeDTO {
        var body = ["email": email, "purpose": purpose.rawValue, "client_challenge": clientChallenge, "client": "ios"]
        body["expected_account_id"] = expectedAccountID
        body["action"] = action
        body["recent_proof"] = recentProof
        body["provider_attempt_id"] = providerAttemptID
        return try decode(try await nativePost(["auth", "email", "request"], body, status: 202))
    }
    public func resendEmailCode(challengeID: String, verifier: String) async throws(APIError) -> AuthChallengeDTO {
        try decode(try await nativePost(["auth", "email", "resend"], ["challenge_id": challengeID, "client_verifier": verifier], status: 202))
    }
    public func startProvider(
        _ provider: NativeAuthProvider, clientChallenge: String, purpose: String = "login",
        expectedAccountID: String? = nil, action: String? = nil, recentProof: String? = nil
    ) async throws(APIError) -> ProviderStartDTO {
        var body = ["purpose": purpose, "client": "ios", "client_challenge": clientChallenge]
        body["expected_account_id"] = expectedAccountID
        body["action"] = action
        body["recent_proof"] = recentProof
        return try decode(try await nativePost(["auth", "providers", provider.rawValue, "start"], body, status: 200))
    }
    public func resetPassword(grant: String, verifier: String, newPassword: String) async throws(APIError) {
        _ = try await nativePost(["auth", "recovery", "reset"], ["reset_grant": grant, "client_verifier": verifier, "new_password": newPassword], status: 204)
    }

    func nativePost(_ path: [String], _ body: [String: String], status: Int, sendsSession: Bool = true) async throws(APIError) -> Exchange {
        let result = try await exchange(Endpoint(.post, path, body: try encode(body), sendsSession: sendsSession))
        guard result.response.statusCode == status else {
            throw APIError(kind: .decoding("Unexpected authentication HTTP status"), message: "The server returned an unexpected sign-in response.", statusCode: result.response.statusCode)
        }
        return result
    }
}

/// A candidate owns a jar of its own. Nothing here touches the live Keychain.
/// Even malformed/error responses remain available only for candidate cleanup.
public final class NativeAuthenticationSession: Sendable {
    private let jar = InMemorySessionTokenStore()
    private let client: BrainBuddyAPIClient
    public let serverURL: URL

    public init(serverURL: URL, transport: any HTTPTransport = URLSessionTransport(), clientVersion: String = BrainBuddyAPI.bundleVersion) {
        self.serverURL = serverURL
        client = BrainBuddyAPIClient(baseURL: serverURL, transport: transport, tokenStore: jar, clientVersion: clientVersion)
    }

    /// For the owner/generation finalizer or candidate-specific revocation only.
    public var candidateToken: String? { try? jar.token(for: serverURL) }
    public func forgetCandidate() { try? jar.removeToken(for: serverURL) }

    /// `POST /api/auth/signup/complete`: resubmits an `INVITE_REQUIRED` handoff with the invite code.
    public func signupComplete(pending: String, inviteCode: String) async throws(APIError) -> AuthCompletionDTO {
        try await complete(.invite(pending: pending, inviteCode: inviteCode))
    }

    public func complete(_ credential: NativeSignInCredential) async throws(APIError) -> AuthCompletionDTO {
        let path: [String]
        let body: [String: String]
        let passwordResponse: Bool
        switch credential {
        case .password(let email, let password):
            path = ["auth", "login"]
            body = ["email": email, "password": password]
            passwordResponse = true
        case .emailCode(let challengeID, let code, let verifier):
            path = ["auth", "email", "verify"]
            body = ["challenge_id": challengeID, "code": code, "client_verifier": verifier]
            passwordResponse = false
        case .browserGrant(let attemptID, let state, let grant, let verifier):
            path = ["auth", "providers", "complete"]
            body = ["attempt_id": attemptID, "state": state, "handoff_code": grant, "client_verifier": verifier]
            passwordResponse = false
        case .apple(let attemptID, let state, let code, let token, let verifier):
            path = ["auth", "providers", "apple", "native", "complete"]
            body = ["attempt_id": attemptID, "state": state, "authorization_code": code, "identity_token": token, "client_verifier": verifier]
            passwordResponse = false
        case .invite(let pending, let inviteCode):
            path = ["auth", "signup", "complete"]
            body = ["pending": pending, "invite_code": inviteCode]
            passwordResponse = false
        }
        let response: BrainBuddyAPIClient.Exchange
        do {
            response = try await client.nativePost(path, body, status: 200, sendsSession: false)
        } catch {
            if case .invite = credential { throw Self.inviteStepError(error) }
            if !passwordResponse, let handoff = InviteHandoff(error) {
                // No account, no session: a cookie beside this answer is a contract breach.
                guard candidateToken == nil else { throw Self.invalidSession() }
                return .inviteRequired(handoff)
            }
            throw error
        }
        let completion: AuthCompletionDTO
        if passwordResponse {
            let me: MeDTO = try client.decode(response)
            completion = .signedIn(me, deletionCancelled: me.deletionCancelled)
        } else { completion = try client.decode(response) }
        if case .signedIn = completion {
            guard case .set = response.sessionUpdate, candidateToken != nil else { throw Self.invalidSession() }
        } else {
            guard response.sessionUpdate == nil, candidateToken == nil else { throw Self.invalidSession() }
        }
        return completion
    }

    /// Pins the invite resubmission's failures to the design's single wording, so
    /// the sheet can tell them apart after the layers above keep only the text.
    /// A 429 stops being "uncertain": nothing was created and the handoff stays usable.
    static func inviteStepError(_ error: APIError) -> APIError {
        var mapped = error
        switch (error.statusCode, error.detail?["code"]?.stringValue) {
        case (400?, "INVITE_INVALID"):
            mapped.message = InviteStepCopy.invalid
        case (410?, _):
            mapped.message = InviteStepCopy.expired
        case (429?, _):
            mapped.kind = .rejected
            mapped.message = InviteStepCopy.tooManyAttempts
        default:
            break
        }
        return mapped
    }

    private static func invalidSession() -> APIError {
        APIError(kind: .decoding("Authentication outcome and candidate cookie disagree"), message: "The server returned an unexpected sign-in response.", statusCode: 200)
    }
}
