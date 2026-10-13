import Foundation

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The session cookie for a host that performs HTTP itself (the Rust sync transport, spec 026).
///
/// `BrainBuddyAPIClient` keeps its credential rules inside `exchange`; a second HTTP adapter must
/// follow the same ones, so they live here too: the opaque token comes from the
/// `SessionTokenStore` and is sent as `Cookie: brainbuddy_session=…` (never given to the core, never
/// logged), a renewed cookie in `Set-Cookie` is stored, a deleted one removed, and a `401` to a
/// request that carried the stored token forgets exactly that token (a sign-in that finished
/// meanwhile may already have stored a newer one).
public struct SessionCookieCredential: Sendable {
    /// What `authorize` did to a request.
    public enum Attachment: Equatable, Sendable {
        /// The cookie is on the request; `observe` needs this token back.
        case attached(token: String)
        /// No session is stored: the request goes out bare and the server answers `401`.
        case anonymous
        /// This build may not read the stored session (macOS after a re-sign): the person must
        /// sign in again, so nothing is sent.
        case denied
        /// The store could not be read (for example before first unlock). Not a sign-out:
        /// the call fails as a lost connection and is retried.
        case unavailable
    }

    public let serverURL: URL
    private let tokenStore: any SessionTokenStore

    public init(serverURL: URL, tokenStore: any SessionTokenStore) {
        self.serverURL = serverURL
        self.tokenStore = tokenStore
    }

    /// Adds the stored session cookie to `request`.
    public func authorize(_ request: inout URLRequest) -> Attachment {
        request.httpShouldHandleCookies = false
        let token: String?
        do {
            token = try tokenStore.token(for: serverURL)
        } catch TokenStoreError.accessDenied {
            return .denied
        } catch {
            return .unavailable
        }
        guard let token else { return .anonymous }
        request.setValue("\(BrainBuddyAPI.sessionCookieName)=\(token)", forHTTPHeaderField: "Cookie")
        return .attached(token: token)
    }

    /// Applies what the answer says about the session. `sentToken` is the token `authorize` attached.
    public func observe(statusCode: Int, setCookie: String?, sentToken: String?) {
        let update = setCookie.flatMap { SetCookieParser.update(for: BrainBuddyAPI.sessionCookieName, in: $0) }
        switch update {
        case .set(let token):
            // A renewal of the session this device already holds: never an interactive write.
            try? tokenStore.setToken(token, for: serverURL)
        case .removed:
            try? tokenStore.removeToken(for: serverURL)
        case nil:
            break
        }
        if statusCode == 401, let sentToken, update == nil {
            if (try? tokenStore.token(for: serverURL)) == sentToken { try? tokenStore.removeToken(for: serverURL) }
        }
    }
}
