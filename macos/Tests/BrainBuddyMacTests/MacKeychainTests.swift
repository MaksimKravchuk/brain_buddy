#if os(macOS)
    import BrainBuddyAPI
    import Foundation
    import Security
    import Testing

    @testable import BrainBuddyMacCore

    /// The Mac's session token store on a real keychain (contracts/mac-app-host.md §8; FR-005; review
    /// c2, G34, G47): each test creates and unlocks a temporary keychain in its own folder with a random
    /// password, points `KeychainSessionTokenStore` at it through the macOS-only test initializer, and
    /// deletes it afterwards. The login keychain is never touched and nothing prompts, so the hosted
    /// runner runs it. A keychain that can't be created fails the test; it never skips.
    ///
    /// Serialized: the "user interaction not allowed" switch these tests set is process-wide.
    @Suite("Keychain on macOS", .serialized)
    struct MacKeychainTests {
        static let server = URL(string: "https://api.example.com/api")!

        struct KeychainFailure: Error, CustomStringConvertible {
            var step: String
            var status: OSStatus
            var description: String { "\(step) failed with OSStatus \(status)" }
        }

        /// A temporary, unlocked keychain, deleted with its folder at the end of the test.
        final class TemporaryKeychain {
            let keychain: SecKeychain
            let folder: URL

            init() throws {
                folder = FileManager.default.temporaryDirectory.appendingPathComponent("bb-keychain-\(UUID().uuidString)")
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                let path = folder.appendingPathComponent("test.keychain-db").path
                let password = Array(UUID().uuidString.utf8)
                var created: SecKeychain?
                let status = SecKeychainCreate(path, UInt32(password.count), password, false, nil, &created)
                guard status == errSecSuccess, let created else { throw KeychainFailure(step: "SecKeychainCreate", status: status) }
                let unlocked = SecKeychainUnlock(created, UInt32(password.count), password, true)
                guard unlocked == errSecSuccess else {
                    _ = SecKeychainDelete(created)
                    throw KeychainFailure(step: "SecKeychainUnlock", status: unlocked)
                }
                keychain = created
            }

            deinit {
                _ = SecKeychainDelete(keychain)
                try? FileManager.default.removeItem(at: folder)
            }
        }

        /// Runs `body` with system prompts refused process-wide, so a test can never hang on one.
        static func withoutPrompts<T>(_ body: () throws -> T) rethrows -> T {
            _ = SecKeychainSetUserInteractionAllowed(false)
            defer { _ = SecKeychainSetUserInteractionAllowed(true) }
            return try body()
        }

        /// A service of its own per test, so nothing collides with a real item.
        static func service() -> String { "\(MacHostConfiguration.keychainService).test-\(UUID().uuidString)" }

        /// An item for `service` that no application may read: what a rebuilt, re-signed app meets.
        static func addRefusedItem(service: String, in keychain: SecKeychain) throws {
            var access: SecAccess?
            let made = SecAccessCreate("Brain Buddy test item" as CFString, [] as CFArray, &access)
            guard made == errSecSuccess, let access else { throw KeychainFailure(step: "SecAccessCreate", status: made) }
            let item: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecAttrAccount as String: BrainBuddyAPI.sessionScope(for: server),
                kSecValueData as String: Data("old-session".utf8),
                kSecAttrAccess as String: access,
                kSecUseKeychain as String: keychain,
            ]
            let added = SecItemAdd(item as CFDictionary, nil)
            guard added == errSecSuccess else { throw KeychainFailure(step: "SecItemAdd", status: added) }
        }

        /// The item's attributes, read from the temporary keychain only.
        static func attributes(service: String, in keychain: SecKeychain) -> [String: Any]? {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecMatchSearchList as String: [keychain],
                kSecReturnAttributes as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
                kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail,
            ]
            var result: CFTypeRef?
            guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
            return result as? [String: Any]
        }

        /// Whether any keychain in the default search list (the login keychain) has an item of `service`.
        static func defaultKeychainHas(service: String) -> Bool {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecMatchLimit as String: kSecMatchLimitOne,
                kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail,
            ]
            return SecItemCopyMatching(query as CFDictionary, nil) == errSecSuccess
        }

        @Test("021-FR-005 a token is set, read, updated and removed in the given keychain only")
        func setReadUpdateRemove() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            try Self.withoutPrompts {
                #expect(try store.token(for: Self.server) == nil)
                try store.setToken("session-one", for: Self.server)
                #expect(try store.token(for: Self.server) == "session-one")
                try store.setToken("session-two", for: Self.server)
                #expect(try store.token(for: Self.server) == "session-two")
                #expect(!Self.defaultKeychainHas(service: service), "the login keychain is never touched")
                try store.removeToken(for: Self.server)
                #expect(try store.token(for: Self.server) == nil)
            }
        }

        @Test("021-FR-005 a pending logout is added, listed and removed")
        func pendingLogouts() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            let logout = PendingLogout(serverURL: Self.server, token: "session-ended", signedOutAt: TestClock.importTime)
            try Self.withoutPrompts {
                #expect(try store.pendingLogouts().isEmpty)
                try store.addPendingLogout(logout)
                #expect(try store.pendingLogouts() == [logout])
                #expect(!Self.defaultKeychainHas(service: store.pendingLogoutService))
                try store.removePendingLogout(logout)
                #expect(try store.pendingLogouts().isEmpty)
            }
        }

        @Test("021-FR-005 the stored item is not synchronizable")
        func notSynchronizable() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            try Self.withoutPrompts {
                try store.setToken("session-one", for: Self.server, interactive: true)
                let attributes = try #require(Self.attributes(service: service, in: temporary.keychain))
                #expect((attributes[kSecAttrSynchronizable as String] as? Bool) != true, "never in iCloud Keychain")
                #expect(attributes[kSecAttrAccount as String] as? String == "api.example.com")
            }
        }

        @Test(
            "021-FR-005 021-FR-017 a non-interactive read of an item this build may not read asks to sign in again, with no prompt",
            .timeLimit(.minutes(1))
        )
        func refusedReadIsSignInAgain() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            try Self.addRefusedItem(service: service, in: temporary.keychain)
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            // The engine maps `accessDenied` to an ended session ("Sign in again to sync"); it is never
            // read as a token.
            Self.withoutPrompts {
                #expect(throws: TokenStoreError.accessDenied) { try store.token(for: Self.server) }
            }
        }

        @Test("021-FR-005 a person's sign-in replaces an item it may not write: deleted and added again", .timeLimit(.minutes(1)))
        func refusedInteractiveWriteIsReplaced() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            try Self.addRefusedItem(service: service, in: temporary.keychain)
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            try Self.withoutPrompts {
                try store.setToken("fresh-session", for: Self.server, interactive: true)
                #expect(try store.token(for: Self.server) == "fresh-session", "the new item is this build's own")
                #expect(!Self.defaultKeychainHas(service: service))
            }
        }

        @Test("021-FR-005 the Mac's service name is the one the host's token store uses")
        func macServiceName() {
            #expect(MacHostConfiguration.keychainService == "app.brainbuddy.mac.session")
            let store = WorkspaceHost.systemTokenStore() as? KeychainSessionTokenStore
            #expect(store?.service == "app.brainbuddy.mac.session")
            #expect(store?.pendingLogoutService == "app.brainbuddy.mac.session.pending-logout")
        }
    }
#endif
