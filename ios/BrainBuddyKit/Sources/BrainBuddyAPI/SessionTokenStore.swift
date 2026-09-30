import Foundation
import Synchronization

#if canImport(Security)
    import Security
#endif

/// Where the opaque `brainbuddy_session` cookie value is kept, one per server
/// (keyed by `BrainBuddyAPI.sessionScope(for:)`, the lowercased host). The
/// client sends it as a `Cookie` header itself instead of using a cookie jar.
///
/// Reads throw rather than return nil on failure: a Keychain read that fails
/// (for example before first unlock) must not look like "signed out", or the
/// next 401 handling would wipe a valid session.
public protocol SessionTokenStore: Sendable {
    func token(for serverURL: URL) throws -> String?
    func setToken(_ token: String, for serverURL: URL) throws
    func removeToken(for serverURL: URL) throws
    /// Removes the session token of every server: with no account linked on
    /// the device, any session left over (for example from an earlier
    /// install; the Keychain survives deleting the app) is stale. Pending
    /// logouts stay.
    func removeAllTokens() throws
    /// Sessions this device signed out of while the server could not be
    /// told, oldest first. They are kept apart from the current sessions, so
    /// no request uses them, until their logout goes through.
    func pendingLogouts() throws -> [PendingLogout]
    func addPendingLogout(_ logout: PendingLogout) throws
    func removePendingLogout(_ logout: PendingLogout) throws
}

extension SessionTokenStore {
    /// Stores that keep one session and never wait for a logout (test
    /// doubles) have nothing to enumerate or remember.
    public func removeAllTokens() throws {}
    public func pendingLogouts() throws -> [PendingLogout] { [] }
    public func addPendingLogout(_ logout: PendingLogout) throws {}
    public func removePendingLogout(_ logout: PendingLogout) throws {}
}

/// A server session signed out on this device whose `POST /auth/logout` has
/// not reached the server yet (it was offline). `token` is the session
/// cookie value the logout must carry.
public struct PendingLogout: Identifiable, Codable, Hashable, Sendable {
    public var id: UUID
    public var serverURL: URL
    public var token: String
    public var signedOutAt: Date

    public init(id: UUID = UUID(), serverURL: URL, token: String, signedOutAt: Date) {
        self.id = id
        self.serverURL = serverURL
        self.token = token
        self.signedOutAt = signedOutAt
    }
}

/// Process-local store for tests, previews and extensions that never sign in.
public final class InMemorySessionTokenStore: SessionTokenStore {
    private struct State {
        var tokens: [String: String] = [:]
        var pendingLogouts: [PendingLogout] = []
    }

    private let state: Mutex<State>

    public init(tokens: [URL: String] = [:]) {
        var initial = State()
        for (url, token) in tokens { initial.tokens[BrainBuddyAPI.sessionScope(for: url)] = token }
        state = Mutex(initial)
    }

    public func token(for serverURL: URL) throws -> String? {
        let scope = BrainBuddyAPI.sessionScope(for: serverURL)
        return state.withLock { $0.tokens[scope] }
    }

    public func setToken(_ token: String, for serverURL: URL) throws {
        let scope = BrainBuddyAPI.sessionScope(for: serverURL)
        state.withLock { $0.tokens[scope] = token }
    }

    public func removeToken(for serverURL: URL) throws {
        let scope = BrainBuddyAPI.sessionScope(for: serverURL)
        _ = state.withLock { $0.tokens.removeValue(forKey: scope) }
    }

    public func removeAllTokens() throws {
        state.withLock { $0.tokens.removeAll() }
    }

    public func pendingLogouts() throws -> [PendingLogout] {
        state.withLock { $0.pendingLogouts }
    }

    public func addPendingLogout(_ logout: PendingLogout) throws {
        state.withLock { state in
            state.pendingLogouts.removeAll { $0.id == logout.id }
            state.pendingLogouts.append(logout)
        }
    }

    public func removePendingLogout(_ logout: PendingLogout) throws {
        state.withLock { $0.pendingLogouts.removeAll { $0.id == logout.id } }
    }
}

#if canImport(Security)
    /// A Keychain failure, with the `OSStatus` from `SecItem*`.
    public struct KeychainError: Error, Hashable, Sendable, CustomStringConvertible {
        public let status: OSStatus
        public init(status: OSStatus) { self.status = status }
        public var description: String {
            let message = SecCopyErrorMessageString(status, nil) as String?
            return "Keychain error \(status)" + (message.map { ": \($0)" } ?? "")
        }
    }

    /// Keychain-backed store: a generic password per server host, service
    /// `app.brainbuddy.session`, readable after first unlock so the app's own
    /// background refresh can sync while the device is locked. Only the app
    /// uses it: widgets and App Intents never sync and never read the session,
    /// and there is no keychain sharing, so `accessGroup` stays nil.
    public final class KeychainSessionTokenStore: SessionTokenStore {
        public static let defaultService = "app.brainbuddy.session"

        public let service: String
        public let accessGroup: String?

        public init(service: String = KeychainSessionTokenStore.defaultService, accessGroup: String? = nil) {
            self.service = service
            self.accessGroup = accessGroup
        }

        private func query(for serverURL: URL) -> [String: Any] {
            var query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecAttrAccount as String: BrainBuddyAPI.sessionScope(for: serverURL),
            ]
            if let accessGroup { query[kSecAttrAccessGroup as String] = accessGroup }
            return query
        }

        public func token(for serverURL: URL) throws -> String? {
            var query = query(for: serverURL)
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitOne
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            switch status {
            case errSecSuccess:
                guard let data = result as? Data else { return nil }
                return String(data: data, encoding: .utf8)
            case errSecItemNotFound:
                return nil
            default:
                throw KeychainError(status: status)
            }
        }

        public func setToken(_ token: String, for serverURL: URL) throws {
            let data = Data(token.utf8)
            let attributes: [String: Any] = [
                kSecValueData as String: data,
                // Background sync needs it after first unlock; a 30-day
                // session must not travel to another device in a backup.
                kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
            ]
            let status = SecItemUpdate(query(for: serverURL) as CFDictionary, attributes as CFDictionary)
            switch status {
            case errSecSuccess:
                return
            case errSecItemNotFound:
                var item = query(for: serverURL)
                item.merge(attributes) { _, new in new }
                let added = SecItemAdd(item as CFDictionary, nil)
                guard added == errSecSuccess else { throw KeychainError(status: added) }
            default:
                throw KeychainError(status: status)
            }
        }

        public func removeToken(for serverURL: URL) throws {
            let status = SecItemDelete(query(for: serverURL) as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
        }

        /// Every item of `service` (all servers); pending logouts live under
        /// another service and stay.
        public func removeAllTokens() throws {
            try Self.deleteAll(serviceQuery(service))
        }

        // MARK: Pending logouts

        /// Pending logouts are generic passwords of `<service>.pending-logout`,
        /// one per logout (account = its id), holding the JSON of `PendingLogout`.
        public var pendingLogoutService: String { service + ".pending-logout" }

        public func pendingLogouts() throws -> [PendingLogout] {
            var query = serviceQuery(pendingLogoutService)
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitAll
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            switch status {
            case errSecSuccess:
                let items = (result as? [Data]) ?? []
                let decoder = JSONDecoder()
                return items.compactMap { try? decoder.decode(PendingLogout.self, from: $0) }
                    .sorted { ($0.signedOutAt, $0.id.uuidString) < ($1.signedOutAt, $1.id.uuidString) }
            case errSecItemNotFound:
                return []
            default:
                throw KeychainError(status: status)
            }
        }

        public func addPendingLogout(_ logout: PendingLogout) throws {
            var item = serviceQuery(pendingLogoutService)
            item[kSecAttrAccount as String] = logout.id.uuidString
            item[kSecValueData as String] = try JSONEncoder().encode(logout)
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            let status = SecItemAdd(item as CFDictionary, nil)
            guard status == errSecSuccess || status == errSecDuplicateItem else { throw KeychainError(status: status) }
        }

        public func removePendingLogout(_ logout: PendingLogout) throws {
            var query = serviceQuery(pendingLogoutService)
            query[kSecAttrAccount as String] = logout.id.uuidString
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
        }

        private func serviceQuery(_ service: String) -> [String: Any] {
            var query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
            ]
            if let accessGroup { query[kSecAttrAccessGroup as String] = accessGroup }
            return query
        }

        private static func deleteAll(_ query: [String: Any]) throws {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
        }
    }
#endif
