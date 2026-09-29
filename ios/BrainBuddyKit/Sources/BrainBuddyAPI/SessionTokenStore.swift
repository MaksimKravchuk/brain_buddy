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
}

/// Process-local store for tests, previews and extensions that never sign in.
public final class InMemorySessionTokenStore: SessionTokenStore {
    private let tokens: Mutex<[String: String]>

    public init(tokens: [URL: String] = [:]) {
        var initial: [String: String] = [:]
        for (url, token) in tokens { initial[BrainBuddyAPI.sessionScope(for: url)] = token }
        self.tokens = Mutex(initial)
    }

    public func token(for serverURL: URL) throws -> String? {
        let scope = BrainBuddyAPI.sessionScope(for: serverURL)
        return tokens.withLock { $0[scope] }
    }

    public func setToken(_ token: String, for serverURL: URL) throws {
        let scope = BrainBuddyAPI.sessionScope(for: serverURL)
        tokens.withLock { $0[scope] = token }
    }

    public func removeToken(for serverURL: URL) throws {
        let scope = BrainBuddyAPI.sessionScope(for: serverURL)
        _ = tokens.withLock { $0.removeValue(forKey: scope) }
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
    /// `app.brainbuddy.session`, readable after first unlock so widgets and
    /// App Intents can sync in the background. Pass the shared keychain access
    /// group to share the session with the widget extension.
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
    }
#endif
