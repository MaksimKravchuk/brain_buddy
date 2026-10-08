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
            let path: String

            init() throws {
                folder = FileManager.default.temporaryDirectory.appendingPathComponent("bb-keychain-\(UUID().uuidString)")
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
                path = folder.appendingPathComponent("test.keychain-db").path
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

        /// A session item as an earlier build left it: created by another program, so its access list
        /// trusts that program and not this one. `/usr/bin/security` writes it into the temporary
        /// keychain, the way the previous, differently signed build of the app created its item: this
        /// process may not read it without asking, and macOS refuses to let it delete the item
        /// (`errSecInvalidOwnerEdit`, -25244).
        static func addOtherBuildsItem(service: String, account: String, password: String, in keychain: TemporaryKeychain) throws {
            _ = try runSecurity(["add-generic-password", "-s", service, "-a", account, "-w", password, keychain.path])
        }

        /// The other build's item as that build reads it: proves the item was left as it was.
        static func otherBuildsPassword(service: String, account: String, in keychain: TemporaryKeychain) throws -> String {
            try runSecurity(["find-generic-password", "-s", service, "-a", account, "-w", keychain.path])
                .trimmingCharacters(in: .newlines)
        }

        /// Runs `/usr/bin/security` with `arguments` and returns what it printed.
        static func runSecurity(_ arguments: [String]) throws -> String {
            let tool = Process()
            let output = Pipe()
            tool.executableURL = URL(fileURLWithPath: "/usr/bin/security")
            tool.arguments = arguments
            tool.standardOutput = output
            try tool.run()
            let printed = output.fileHandleForReading.readDataToEndOfFile()
            tool.waitUntilExit()
            guard tool.terminationStatus == 0 else {
                throw KeychainFailure(step: "security \(arguments[0])", status: OSStatus(tool.terminationStatus))
            }
            return String(decoding: printed, as: UTF8.self)
        }

        /// The accounts of every item of `service` in the temporary keychain, sorted.
        static func accounts(service: String, in keychain: SecKeychain) -> [String] {
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
                kSecMatchSearchList as String: [keychain],
                kSecReturnAttributes as String: true,
                kSecMatchLimit as String: kSecMatchLimitAll,
                kSecUseAuthenticationUI as String: kSecUseAuthenticationUIFail,
            ]
            var result: CFTypeRef?
            guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return [] }
            return ((result as? [[String: Any]]) ?? []).compactMap { $0[kSecAttrAccount as String] as? String }.sorted()
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
            let earlier = PendingLogout(
                serverURL: URL(string: "https://brain.example.org/api")!, token: "legacy-session",
                signedOutAt: TestClock.importTime.addingTimeInterval(-60)
            )
            try Self.withoutPrompts {
                #expect(try store.pendingLogouts().isEmpty)
                try store.addPendingLogout(logout)
                #expect(try store.pendingLogouts() == [logout])
                // Several at once (a sign-out offline beside the pre-021 sessions the cleanup queued):
                // the listing that the engine's retry reads, oldest first.
                try store.addPendingLogout(earlier)
                #expect(try store.pendingLogouts() == [earlier, logout])
                #expect(!Self.defaultKeychainHas(service: store.pendingLogoutService))
                try store.removePendingLogout(logout)
                #expect(try store.pendingLogouts() == [earlier])
                try store.removePendingLogout(earlier)
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

        @Test(
            "021-FR-005 a person's sign-in writes past an item an earlier build left, so this build can read its session",
            .timeLimit(.minutes(1))
        )
        func otherBuildsItemIsWrittenPastAtSignIn() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            let host = BrainBuddyAPI.sessionScope(for: Self.server)
            try Self.addOtherBuildsItem(service: service, account: host, password: "old-session", in: temporary)
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            try Self.withoutPrompts {
                #expect(throws: TokenStoreError.accessDenied, "before: routine sync can't read it and asks to sign in again") {
                    try store.token(for: Self.server)
                }
                #expect(throws: TokenStoreError.accessDenied, "a routine write never goes past it") {
                    try store.setToken("routine-session", for: Self.server)
                }
                try store.setToken("fresh-session", for: Self.server, interactive: true)
                #expect(try store.token(for: Self.server) == "fresh-session", "the new item is this build's own")
                #expect(Self.accounts(service: service, in: temporary.keychain) == [host, "\(host)#1"])
                #expect(
                    try Self.otherBuildsPassword(service: service, account: host, in: temporary) == "old-session",
                    "the earlier build's item is never written: that build can't read the new session"
                )
                // Renewals go to this build's item; the earlier build's is ignored.
                try store.setToken("renewed-session", for: Self.server)
                #expect(try store.token(for: Self.server) == "renewed-session")
                #expect(Self.accounts(service: service, in: temporary.keychain) == [host, "\(host)#1"])
                // Sign-out removes this build's item and does not fail on the one macOS won't let it
                // delete. That one alone is "sign in again" once more, and the next sign-in works too.
                try store.removeToken(for: Self.server)
                #expect(Self.accounts(service: service, in: temporary.keychain) == [host])
                #expect(throws: TokenStoreError.accessDenied) { try store.token(for: Self.server) }
                try store.setToken("next-session", for: Self.server, interactive: true)
                #expect(try store.token(for: Self.server) == "next-session")
                // The launch cleanup with no account linked: likewise.
                try store.removeAllTokens()
                #expect(Self.accounts(service: service, in: temporary.keychain) == [host])
                #expect(!Self.defaultKeychainHas(service: service))
            }
        }

        @Test(
            "021-FR-005 the newest item decides: this build's older session is never used under an earlier build's newer one",
            .timeLimit(.minutes(1))
        )
        func newestItemDecides() throws {
            let temporary = try TemporaryKeychain()
            let service = Self.service()
            let host = BrainBuddyAPI.sessionScope(for: Self.server)
            let store = KeychainSessionTokenStore(service: service, keychain: temporary.keychain)
            try Self.withoutPrompts {
                try store.setToken("older-session", for: Self.server, interactive: true)
            }
            // Another build signed in since (this one is an older build run again).
            try Self.addOtherBuildsItem(service: service, account: "\(host)#1", password: "newer-session", in: temporary)
            try Self.withoutPrompts {
                #expect(throws: TokenStoreError.accessDenied, "never the stale session of this build") {
                    try store.token(for: Self.server)
                }
                try store.setToken("fresh-session", for: Self.server, interactive: true)
                #expect(try store.token(for: Self.server) == "fresh-session")
                #expect(Self.accounts(service: service, in: temporary.keychain) == [host, "\(host)#1", "\(host)#2"])
                try store.removeToken(for: Self.server)
                #expect(
                    Self.accounts(service: service, in: temporary.keychain) == ["\(host)#1"],
                    "both of this build's items go; the other build's stays"
                )
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
