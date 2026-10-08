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
    /// A routine write, for example a renewed cookie; never prompts either, and never goes past a
    /// session this build may not use (it throws `TokenStoreError.accessDenied`).
    func setToken(_ token: String, for serverURL: URL) throws
    /// The write of a sign-in the person started: the one place the system may ask (for example to
    /// unlock the keychain), and the one write that puts a new session in place of one this build
    /// can no longer use. `setToken(_:for:)` is for the rest.
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
    /// was rebuilt or re-signed). Only a sign-in the person starts can put a new session in its
    /// place, so the client
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
    ///
    /// **Session items on macOS.** On the file-based login keychain any app may overwrite an item's
    /// data, but only the apps its access list trusts may read it, and only the app that created it
    /// may delete it (any other gets `errSecInvalidOwnerEdit`, -25244, with no prompt). An ad-hoc
    /// rebuilt app is a new client, so the item an earlier build left can be neither used nor
    /// removed. The store therefore writes past it instead of into it: a server's session items are
    /// accounts `<host>`, `<host>#1`, `<host>#2`, … and the **highest generation is the session**.
    /// Items under it are ignored: never read, never written, and left by removals that macOS
    /// refuses. A routine read of a highest item this build may not read is `accessDenied` ("sign in
    /// again"); a person's sign-in then adds the next generation, which this build created and so
    /// reads without a prompt. iOS keeps one item per server, `<host>`, and none of this.
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
            try sessionToken(BrainBuddyAPI.sessionScope(for: serverURL))
        }

        /// The session of one server: on macOS the highest generation's item, on iOS the one item.
        private func sessionToken(_ scope: String) throws -> String? {
            #if os(macOS)
                guard let current = try sessionItems(scope).first else { return nil }
                return try readToken(account: current.account)
            #else
                return try readToken(account: scope)
            #endif
        }

        /// One session item's token, never prompting.
        private func readToken(account: String) throws -> String? {
            let (status, data) = readData(service, account: account)
            switch status {
            case errSecSuccess:
                return data.flatMap { String(data: $0, encoding: .utf8) }
            case errSecItemNotFound:
                return nil
            default:
                #if os(macOS)
                    // The item is there, but this build may not read it without asking (a rebuilt
                    // app is a new client of it): only the person's next sign-in can write past it.
                    // A refused access reads as either status.
                    if Self.isRefusal(status) { throw TokenStoreError.accessDenied }
                #endif
                throw KeychainError(status: status)
            }
        }

        /// One item's data, read without a prompt on macOS.
        private func readData(_ service: String, account: String) -> (OSStatus, Data?) {
            var query = searchQuery(service, account: account)
            query[kSecReturnData as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitOne
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            return (status, result as? Data)
        }

        public func setToken(_ token: String, for serverURL: URL) throws {
            try store(token, for: serverURL, interactive: false)
        }

        public func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws {
            try store(token, for: serverURL, interactive: interactive)
        }

        private func store(_ token: String, for serverURL: URL, interactive: Bool) throws {
            let scope = BrainBuddyAPI.sessionScope(for: serverURL)
            #if os(macOS)
                try storeOnMac(token, scope: scope, interactive: interactive)
            #else
                try upsert(Data(token.utf8), account: scope, interactive: interactive)
            #endif
        }

        /// Overwrites the item's data, or adds the item when there is none.
        private func upsert(_ data: Data, account: String, interactive: Bool) throws {
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
            let scope = BrainBuddyAPI.sessionScope(for: serverURL)
            #if os(macOS)
                try delete(service, accounts: sessionItems(scope).map(\.account))
            #else
                try Self.deleteAll(searchQuery(service, account: scope))
            #endif
        }

        /// Every item of `service` (all servers); pending logouts live under
        /// another service and stay.
        public func removeAllTokens() throws {
            #if os(macOS)
                try delete(service, accounts: accounts(of: service))
            #else
                try Self.deleteAll(searchQuery(service))
            #endif
        }

        #if os(macOS)
            /// One of a server's session items on macOS (see the type's documentation).
            private struct SessionItem {
                var account: String
                var generation: Int
            }

            /// The session items of one server, highest generation first. Their attributes are listed
            /// without reading any item's data, which needs no access to it.
            private func sessionItems(_ scope: String) throws -> [SessionItem] {
                try accounts(of: service)
                    .compactMap { account in
                        Self.generation(of: account, scope: scope).map { SessionItem(account: account, generation: $0) }
                    }
                    .sorted { $0.generation > $1.generation }
            }

            /// `<host>` is generation 0, `<host>#<n>` (n ≥ 1, written as `String(n)`) generation n;
            /// any other account is not this server's session.
            private static func generation(of account: String, scope: String) -> Int? {
                if account == scope { return 0 }
                let prefix = scope + "#"
                guard account.hasPrefix(prefix) else { return nil }
                let suffix = String(account.dropFirst(prefix.count))
                guard let generation = Int(suffix), generation > 0, String(generation) == suffix else { return nil }
                return generation
            }

            private static func account(scope: String, generation: Int) -> String {
                generation == 0 ? scope : "\(scope)#\(generation)"
            }

            /// The highest item, when this build may read it, is the one to write; a routine write
            /// never goes past one it may not read ("sign in again" stays). A person's sign-in writes
            /// past it: a new item of the next generation, which only this build created and so is the
            /// one it may read. It never writes into an item another build created (that build could
            /// read the new session), and it checks without a prompt that the token reads back.
            private func storeOnMac(_ token: String, scope: String, interactive: Bool) throws {
                let data = Data(token.utf8)
                if let current = try sessionItems(scope).first {
                    if isRefused(service, account: current.account) {
                        guard interactive else { throw TokenStoreError.accessDenied }
                        let next = Self.account(scope: scope, generation: current.generation + 1)
                        try upsert(data, account: next, interactive: true)
                    } else {
                        try upsert(data, account: current.account, interactive: interactive)
                    }
                } else {
                    try upsert(data, account: scope, interactive: interactive)
                }
                if interactive, (try? sessionToken(scope)) != token {
                    throw KeychainError(status: errSecAuthFailed)
                }
            }

            /// Whether this build may not read the item without asking.
            private func isRefused(_ service: String, account: String) -> Bool {
                Self.isRefusal(readData(service, account: account).0)
            }

            private static func isRefusal(_ status: OSStatus) -> Bool {
                status == errSecInteractionNotAllowed || status == errSecAuthFailed
            }

            /// Deletes each item, never prompting, and tries every one before it reports a failure. An
            /// item this build may not read and macOS won't let it delete (another build created it:
            /// `errSecInvalidOwnerEdit`, or a refusal without a prompt) is left: nothing reads it, and
            /// its server session ends by expiring. Any other failure is reported.
            private func delete(_ service: String, accounts: [String]) throws {
                var failure: KeychainError?
                for account in accounts {
                    let status = SecItemDelete(searchQuery(service, account: account) as CFDictionary)
                    if status == errSecSuccess || status == errSecItemNotFound { continue }
                    let refusedDeletion = status == errSecInvalidOwnerEdit || Self.isRefusal(status)
                    if refusedDeletion, isRefused(service, account: account) { continue }
                    failure = failure ?? KeychainError(status: status)
                }
                if let failure { throw failure }
            }
        #endif

        /// The accounts of every item of `service`, from their attributes: the macOS file-based
        /// keychain (the Mac's login keychain) refuses `kSecReturnData` together with
        /// `kSecMatchLimitAll` with `errSecParam` (-50), which the data-protection keychain of iOS
        /// accepts, so data is read one item at a time.
        private func accounts(of service: String) throws -> [String] {
            var query = searchQuery(service)
            query[kSecReturnAttributes as String] = true
            query[kSecMatchLimit as String] = kSecMatchLimitAll
            var result: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &result)
            switch status {
            case errSecSuccess:
                return ((result as? [[String: Any]]) ?? []).compactMap { $0[kSecAttrAccount as String] as? String }
            case errSecItemNotFound:
                return []
            default:
                throw KeychainError(status: status)
            }
        }

        // MARK: Pending logouts

        /// Pending logouts are generic passwords of `<service>.pending-logout`,
        /// one per logout (account = its id), holding the JSON of `PendingLogout`.
        public var pendingLogoutService: String { service + ".pending-logout" }

        /// Lists the items' accounts first, then reads each one's data (`accounts(of:)`). Each
        /// logout is an item of its own (account = its id), so a new one never meets an earlier
        /// build's item: one this build may not read is skipped, never sent and never removed, and
        /// its session ends by expiring on the server.
        public func pendingLogouts() throws -> [PendingLogout] {
            let decoder = JSONDecoder()
            return try Set(accounts(of: pendingLogoutService)).compactMap { account in
                try pendingLogoutData(account).flatMap { try? decoder.decode(PendingLogout.self, from: $0) }
            }
            .sorted { ($0.signedOutAt, $0.id.uuidString) < ($1.signedOutAt, $1.id.uuidString) }
        }

        /// One pending logout's JSON, never prompting: nil when it went meanwhile, or when this build
        /// may not read it (an older build's; its session then ends by expiring on the server).
        private func pendingLogoutData(_ account: String) throws -> Data? {
            let (status, data) = readData(pendingLogoutService, account: account)
            switch status {
            case errSecSuccess:
                return data
            case errSecItemNotFound, errSecInteractionNotAllowed, errSecAuthFailed:
                return nil
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
