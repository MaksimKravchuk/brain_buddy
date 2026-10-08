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
    /// Never shows a system prompt (the sync engine and the launch cleanup read through it): an
    /// item this build may not use throws `TokenStoreError.accessDenied`, which the engine treats
    /// as "sign in again".
    func token(for serverURL: URL) throws -> String?
    /// A routine write, for example a renewed cookie; never prompts either.
    func setToken(_ token: String, for serverURL: URL) throws
    /// The write of a sign-in the person started: the one place the system may ask for access, and
    /// where an item this build can no longer use is replaced. `setToken(_:for:)` is for the rest.
    func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws
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
    public func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws {
        try setToken(token, for: serverURL)
    }

    /// Stores that keep one session and never wait for a logout (test
    /// doubles) have nothing to enumerate or remember.
    public func removeAllTokens() throws {}
    public func pendingLogouts() throws -> [PendingLogout] { [] }
    public func addPendingLogout(_ logout: PendingLogout) throws {}
    public func removePendingLogout(_ logout: PendingLogout) throws {}
}

/// A token store failure that means something beyond "try again later", whatever keeps the tokens.
public enum TokenStoreError: Error, Hashable, Sendable {
    /// The session is stored but this build may not read it without asking (macOS, after the app
    /// was rebuilt or re-signed). Only a sign-in the person starts can replace it, so the client
    /// reports it as an ended session (`.unauthorized`) and the engine asks to sign in again.
    case accessDenied
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
    /// `app.brainbuddy.session`. On iOS it is readable after first unlock, so the app's own
    /// background refresh can sync while the device is locked, and never leaves the device. On macOS
    /// it lives in the login keychain, which cannot promise "this device only", so no accessibility
    /// is set; it is only kept out of iCloud Keychain, and every call but a person's sign-in fails
    /// instead of showing macOS's access prompt. The widgets and App Intents never sync and never
    /// read the session, and there is no keychain sharing, so `accessGroup` stays nil.
    public final class KeychainSessionTokenStore: SessionTokenStore {
        public static let defaultService = "app.brainbuddy.session"

        public let service: String
        public let accessGroup: String?
        #if os(macOS)
            // Set only by the test initializer and never changed, so sharing the reference is safe.
            private nonisolated(unsafe) let keychain: SecKeychain?
        #endif

        public init(service: String = KeychainSessionTokenStore.defaultService, accessGroup: String? = nil) {
            self.service = service
            self.accessGroup = accessGroup
            #if os(macOS)
                keychain = nil
            #endif
        }

        #if os(macOS)
            /// For tests: searches and writes only `keychain`, a temporary one, never the login keychain.
            public init(service: String = KeychainSessionTokenStore.defaultService, keychain: SecKeychain) {
                self.service = service
                accessGroup = nil
                self.keychain = keychain
            }
        #endif

        /// What identifies an item, for adding and for searching.
        private func baseQuery(_ service: String, account: String? = nil) -> [String: Any] {
            var query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
            ]
            if let account { query[kSecAttrAccount as String] = account }
            if let accessGroup { query[kSecAttrAccessGroup as String] = accessGroup }
            #if os(macOS)
                query[kSecAttrSynchronizable as String] = false
            #endif
            return query
        }

        /// `baseQuery` for finding, updating and deleting; on macOS it fails rather than prompts
        /// unless `interactive`.
        private func searchQuery(_ service: String, account: String? = nil, interactive: Bool = false) -> [String: Any] {
            var query = baseQuery(service, account: account)
            #if os(macOS)
                if !interactive { query[kSecUseAuthenticationUI as String] = kSecUseAuthenticationUIFail }
                if let keychain { query[kSecMatchSearchList as String] = [keychain] }
            #endif
            return query
        }

        /// Added with every item. Background sync needs iOS items after first unlock, and a 30-day
        /// session must not travel to another device in a backup; macOS claims neither.
        private static var storageAttributes: [String: Any] {
            #if os(macOS)
                return [:]
            #else
                return [kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
            #endif
        }

        private func newItem(_ service: String, account: String, data: Data) -> [String: Any] {
            var item = baseQuery(service, account: account)
            item[kSecValueData as String] = data
            item.merge(Self.storageAttributes) { _, new in new }
            #if os(macOS)
                if let keychain { item[kSecUseKeychain as String] = keychain }
            #endif
            return item
        }

        public func token(for serverURL: URL) throws -> String? {
            var query = searchQuery(service, account: BrainBuddyAPI.sessionScope(for: serverURL))
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
                #if os(macOS)
                    // The item is there, but this build may not read it without asking (a rebuilt
                    // app is a new client of it): only the person's next sign-in can replace it. A
                    // refused access reads as either status, as the interactive write below treats them.
                    if status == errSecInteractionNotAllowed || status == errSecAuthFailed {
                        throw TokenStoreError.accessDenied
                    }
                #endif
                throw KeychainError(status: status)
            }
        }

        public func setToken(_ token: String, for serverURL: URL) throws {
            try store(token, for: serverURL, interactive: false)
        }

        public func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws {
            #if os(macOS)
                do {
                    try store(token, for: serverURL, interactive: interactive)
                } catch let error as KeychainError
                    where interactive && (error.status == errSecAuthFailed || error.status == errSecInteractionNotAllowed)
                {
                    // The item is there but this build may not use it (a rebuilt app is a new client of
                    // it): replace it, which only a sign-in the person started may do.
                    try remove(serverURL, interactive: true)
                    try store(token, for: serverURL, interactive: true)
                }
            #else
                try store(token, for: serverURL, interactive: interactive)
            #endif
        }

        private func store(_ token: String, for serverURL: URL, interactive: Bool) throws {
            let account = BrainBuddyAPI.sessionScope(for: serverURL)
            let data = Data(token.utf8)
            var attributes: [String: Any] = [kSecValueData as String: data]
            attributes.merge(Self.storageAttributes) { _, new in new }
            let query = searchQuery(service, account: account, interactive: interactive)
            let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
            switch status {
            case errSecSuccess:
                return
            case errSecItemNotFound:
                let added = SecItemAdd(newItem(service, account: account, data: data) as CFDictionary, nil)
                guard added == errSecSuccess else { throw KeychainError(status: added) }
            default:
                throw KeychainError(status: status)
            }
        }

        public func removeToken(for serverURL: URL) throws {
            try remove(serverURL, interactive: false)
        }

        private func remove(_ serverURL: URL, interactive: Bool) throws {
            let query = searchQuery(service, account: BrainBuddyAPI.sessionScope(for: serverURL), interactive: interactive)
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
        }

        /// Every item of `service` (all servers); pending logouts live under
        /// another service and stay.
        public func removeAllTokens() throws {
            try Self.deleteAll(searchQuery(service))
        }

        // MARK: Pending logouts

        /// Pending logouts are generic passwords of `<service>.pending-logout`,
        /// one per logout (account = its id), holding the JSON of `PendingLogout`.
        public var pendingLogoutService: String { service + ".pending-logout" }

        public func pendingLogouts() throws -> [PendingLogout] {
            var query = searchQuery(pendingLogoutService)
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
            let item = newItem(pendingLogoutService, account: logout.id.uuidString, data: try JSONEncoder().encode(logout))
            let status = SecItemAdd(item as CFDictionary, nil)
            guard status == errSecSuccess || status == errSecDuplicateItem else { throw KeychainError(status: status) }
        }

        public func removePendingLogout(_ logout: PendingLogout) throws {
            let status = SecItemDelete(searchQuery(pendingLogoutService, account: logout.id.uuidString) as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
        }

        private static func deleteAll(_ query: [String: Any]) throws {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw KeychainError(status: status) }
        }
    }
#endif
