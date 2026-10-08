import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Synchronization

@testable import BrainBuddyMacCore

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// A folder of its own for one test, removed afterwards. `path` lets a test put it under a
/// sentinel home folder (the privacy tests).
final class TemporaryFolder {
    let root: URL
    let url: URL

    init(_ path: String = "BrainBuddyMac") {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("bb-mac-\(UUID().uuidString)", isDirectory: true)
        url = root.appendingPathComponent(path, isDirectory: true)
        try? FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    deinit { try? FileManager.default.removeItem(at: root) }

    func file(_ name: String) -> URL { url.appendingPathComponent(name) }
    var legacy: URL { file(LegacyFileNames.legacy) }
    var store: URL { file(LegacyFileNames.store) }
    var sidecar: URL { file(MacLocalStateStore.fileName) }
    var names: [String] { MacFiles.names(in: url) }
    func bytes(_ name: String) -> Data? { try? Data(contentsOf: file(name)) }
}

/// The synthetic fixtures (design example data only; constitution I).
enum Fixture {
    static func data(_ name: String) throws -> Data {
        guard let url = Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Resources") else {
            throw CocoaError(.fileNoSuchFile)
        }
        return try Data(contentsOf: url)
    }

    static func snapshot(_ name: String) throws -> LegacySnapshot { try LegacySnapshot.read(data(name)) }

    /// Puts a fixture where the previous version kept its store.
    @discardableResult
    static func install(_ name: String, in folder: TemporaryFolder) throws -> Data {
        let data = try data(name)
        try data.write(to: folder.legacy)
        return data
    }
}

/// The repository checkout, for the golden artifact the kit's tests read.
enum Repository {
    static func root(file: String = #filePath) -> URL {
        if let root = ProcessInfo.processInfo.environment["BRAINBUDDY_REPO_ROOT"] { return URL(fileURLWithPath: root) }
        // macos/Tests/BrainBuddyMacTests/<file>.swift
        return URL(fileURLWithPath: file).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }

    static var goldenImport: URL {
        root().appendingPathComponent("ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json")
    }
}

/// Deterministic ids: 00000000-0000-0000-<namespace>-<n>.
final class SequentialIDs: Sendable {
    private let namespace: Int
    private let count = Mutex(0)

    init(namespace: Int = 0) { self.namespace = namespace }

    func next() -> UUID {
        let value = count.withLock { count in
            count += 1
            return count
        }
        func pad(_ number: Int, _ width: Int) -> String {
            let digits = String(number)
            return String(repeating: "0", count: max(0, width - digits.count)) + digits
        }
        return UUID(uuidString: "00000000-0000-0000-\(pad(namespace, 4))-\(pad(value, 12))")!
    }

    var provider: @Sendable () -> UUID { { self.next() } }
}

/// A clock a test moves.
final class TestClock: Sendable {
    private let current: Mutex<Date>

    init(_ date: Date = TestClock.importTime) { current = Mutex(date) }

    /// Tue 6 Oct 2026, 14:34 UTC: the design's "today".
    static let importTime = Date(timeIntervalSince1970: 1_791_297_240)
    static let day: TimeInterval = 24 * 60 * 60

    var now: Date { current.withLock { $0 } }
    func advance(_ interval: TimeInterval) { current.withLock { $0 = $0.addingTimeInterval(interval) } }
    func set(_ date: Date) { current.withLock { $0 = date } }
    var provider: @Sendable () -> Date { { self.now } }
}

/// Records every request; answers 200 `{}` unless told otherwise. Nothing leaves the test.
final class CountingTransport: HTTPTransport {
    private let sent = Mutex<[HTTPRequest]>([])

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        sent.withLock { $0.append(request) }
        return HTTPResponse(statusCode: 200, headers: ["Content-Type": "application/json"], body: Data("{}".utf8))
    }

    var requests: [HTTPRequest] { sent.withLock { $0 } }
}

/// A token store that records each call, and whether it ran on the main thread.
final class SpyTokenStore: SessionTokenStore {
    struct Call: Hashable, Sendable {
        var name: String
        var onMainThread: Bool
    }

    private struct State {
        var tokens: [String: String] = [:]
        var pending: [PendingLogout] = []
        var calls: [Call] = []
    }

    private let state = Mutex(State())

    init(token: String? = nil, for server: URL? = nil, pending: [PendingLogout] = []) {
        state.withLock { state in
            if let token, let server { state.tokens[BrainBuddyAPI.sessionScope(for: server)] = token }
            state.pending = pending
        }
    }

    private func record(_ name: String) {
        let main = Thread.isMainThread
        state.withLock { $0.calls.append(Call(name: name, onMainThread: main)) }
    }

    var calls: [Call] { state.withLock { $0.calls } }
    var storedTokens: [String: String] { state.withLock { $0.tokens } }
    var storedPending: [PendingLogout] { state.withLock { $0.pending } }

    func token(for serverURL: URL) throws -> String? {
        record("token")
        return state.withLock { $0.tokens[BrainBuddyAPI.sessionScope(for: serverURL)] }
    }

    func setToken(_ token: String, for serverURL: URL) throws {
        record("setToken")
        state.withLock { $0.tokens[BrainBuddyAPI.sessionScope(for: serverURL)] = token }
    }

    func setToken(_ token: String, for serverURL: URL, interactive: Bool) throws {
        record(interactive ? "setTokenInteractive" : "setToken")
        state.withLock { $0.tokens[BrainBuddyAPI.sessionScope(for: serverURL)] = token }
    }

    func removeToken(for serverURL: URL) throws {
        record("removeToken")
        _ = state.withLock { $0.tokens.removeValue(forKey: BrainBuddyAPI.sessionScope(for: serverURL)) }
    }

    func removeAllTokens() throws {
        record("removeAllTokens")
        state.withLock { $0.tokens.removeAll() }
    }

    func pendingLogouts() throws -> [PendingLogout] {
        record("pendingLogouts")
        return state.withLock { $0.pending }
    }

    func addPendingLogout(_ logout: PendingLogout) throws {
        record("addPendingLogout")
        state.withLock { $0.pending.append(logout) }
    }

    func removePendingLogout(_ logout: PendingLogout) throws {
        record("removePendingLogout")
        state.withLock { $0.pending.removeAll { $0.id == logout.id } }
    }
}

/// The pre-021 app's cookie storage, in memory.
final class FakeCookieJar: LegacyCookieJar {
    private(set) var cookies: [HTTPCookie]

    init(_ cookies: [HTTPCookie] = []) { self.cookies = cookies }

    var allCookies: [HTTPCookie] { cookies }
    func delete(_ cookie: HTTPCookie) { cookies.removeAll { $0 === cookie || ($0.name == cookie.name && $0.domain == cookie.domain) } }

    static func session(_ value: String, domain: String, secure: Bool = true, name: String = "brainbuddy_session") -> HTTPCookie {
        var properties: [HTTPCookiePropertyKey: Any] = [.name: name, .value: value, .domain: domain, .path: "/"]
        if secure { properties[.secure] = "TRUE" }
        return HTTPCookie(properties: properties)!
    }
}

final class FakeResponseCache: LegacyResponseCache {
    private(set) var cleared = 0
    var entries = 1

    func removeAllCachedResponses() {
        cleared += 1
        entries = 0
    }
}

/// A legacy lock that a test holds and releases: the import must wait for it.
final class GateLegacyLocking: LegacyStoreLocking {
    private let gate = Mutex(false)
    private let acquiredFlag = Mutex(false)

    func open() { gate.withLock { $0 = true } }
    var acquired: Bool { acquiredFlag.withLock { $0 } }

    func acquire(_ lockURL: URL) throws -> any LegacyStoreLockHold {
        while !gate.withLock({ $0 }) { usleep(1_000) }
        acquiredFlag.withLock { $0 = true }
        return Hold()
    }

    private struct Hold: LegacyStoreLockHold {
        func release() {}
    }
}

extension LegacyImportCoordinator {
    /// A coordinator for a test folder with the fixed clock and seeded ids.
    static func forTest(
        _ folder: TemporaryFolder, clock: TestClock = TestClock(), ids: SequentialIDs = SequentialIDs(),
        log: any MacLogSink = CapturingMacLog(), hooks: LegacyImportTestHooks = LegacyImportTestHooks(),
        locking: any LegacyStoreLocking = LockfLegacyStoreLocking(), importerVersion: Int = LegacyStoreImporter.version
    ) -> LegacyImportCoordinator {
        LegacyImportCoordinator(
            directory: folder.url, now: clock.provider, makeID: ids.provider, log: log, legacyLocking: locking, hooks: hooks,
            importerVersion: importerVersion
        )
    }
}

/// The document the folder's `store.json` holds, replayed as the workspace shows it.
func storedState(_ folder: TemporaryFolder) throws -> GTDState {
    guard let data = folder.bytes(LegacyFileNames.store) else { throw CocoaError(.fileNoSuchFile) }
    return try StoreDocumentCoding.decode(data).replayed().state
}
