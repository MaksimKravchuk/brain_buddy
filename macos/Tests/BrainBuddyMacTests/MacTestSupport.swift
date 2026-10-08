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

/// Where a held response waits: the test learns that the request arrived, then lets it go.
actor ResponseGate {
    private var isOpen = false
    private var arrived = false
    private var waiters: [CheckedContinuation<Void, Never>] = []
    private var arrivalWaiters: [CheckedContinuation<Void, Never>] = []

    func arrive() {
        arrived = true
        arrivalWaiters.forEach { $0.resume() }
        arrivalWaiters = []
    }

    func waitForArrival() async {
        if arrived { return }
        await withCheckedContinuation { arrivalWaiters.append($0) }
    }

    func wait() async {
        if isOpen { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        waiters.forEach { $0.resume() }
        waiters = []
    }
}

/// A Brain Buddy server in miniature for the Mac's sync-flow tests (the kit's fake server is not a
/// product of the package): password sessions on any host, an empty account to pull, logouts, and a
/// session that can end. Every request is recorded; nothing leaves the test.
final class StubServer: HTTPTransport {
    struct Account: Sendable {
        var id: String
        var email: String
        var password: String
    }

    private struct State {
        var accounts: [String: Account] = [:]
        var sessions: [String: String] = [:]
        var minted = 0
        var requests: [HTTPRequest] = []
        var offline = false
        var deletionScheduled: Set<String> = []
        var holdNextLogin = false
        var holdNextSync = false
        var holdNextLogout = false
    }

    private let state = Mutex(State())
    let loginGate = ResponseGate()
    let syncGate = ResponseGate()
    let logoutGate = ResponseGate()

    init(_ accounts: [Account] = [StubServer.ada]) {
        state.withLock { state in for account in accounts { state.accounts[account.email.lowercased()] = account } }
    }

    static let ada = Account(id: "user_ada", email: "alex@example.com", password: "correct horse battery")
    static let bob = Account(id: "user_bob", email: "bob@example.com", password: "hunter2 hunter2")
    /// Alex's account id on another server: the same owner id, another address.
    static let server = URL(string: "https://api.example.com/api")!
    static let otherServer = URL(string: "https://other.example.org/api")!

    var requests: [HTTPRequest] { state.withLock { $0.requests } }
    var routes: [String] { requests.map { "\($0.method.rawValue.uppercased()) \(Self.route($0.url))" } }
    func clearLog() { state.withLock { $0.requests.removeAll() } }
    var liveSessions: Int { state.withLock { $0.sessions.count } }
    func setOffline(_ offline: Bool) { state.withLock { $0.offline = offline } }
    /// Every session ends, as an expiry would: the next authenticated request is a 401.
    func endSessions() { state.withLock { $0.sessions.removeAll() } }
    func scheduleDeletion(_ email: String) { _ = state.withLock { $0.deletionScheduled.insert(email.lowercased()) } }
    /// The next login's reply waits for `loginGate` (the session is opened at once).
    func holdNextLogin() { state.withLock { $0.holdNextLogin = true } }
    /// The next request a session sends (the first sync's first request) waits for `syncGate`.
    func holdNextSync() { state.withLock { $0.holdNextSync = true } }
    /// The next logout waits for `logoutGate` (a sign-out's, after the local removal).
    func holdNextLogout() { state.withLock { $0.holdNextLogout = true } }
    /// The email now belongs to another account id (deleted and created again).
    func reassign(_ email: String, to id: String) { state.withLock { $0.accounts[email.lowercased()]?.id = id } }

    /// "/auth/login" for "https://api.example.com/api/auth/login".
    static func route(_ url: URL) -> String {
        let path = url.path
        guard let range = path.range(of: "/api") else { return path }
        return String(path[range.upperBound...])
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let offline = state.withLock { state -> Bool in
            state.requests.append(request)
            return state.offline
        }
        if offline { throw TransportError(description: "Offline.", requestMayHaveBeenSent: false) }
        let route = Self.route(request.url)
        switch (request.method, route) {
        case (.post, "/auth/login"):
            return await login(request)
        case (.post, "/auth/logout"):
            let hold = state.withLock { state -> Bool in
                defer { state.holdNextLogout = false }
                return state.holdNextLogout
            }
            if hold {
                await logoutGate.arrive()
                await logoutGate.wait()
            }
            if let token = Self.session(request) { _ = state.withLock { $0.sessions.removeValue(forKey: token) } }
            return HTTPResponse(statusCode: 204)
        default:
            guard let token = Self.session(request), state.withLock({ $0.sessions[token] != nil }) else {
                return Self.error(401, "Authentication required.", request)
            }
            let hold = state.withLock { state -> Bool in
                defer { state.holdNextSync = false }
                return state.holdNextSync
            }
            if hold {
                await syncGate.arrive()
                await syncGate.wait()
            }
            switch (request.method, route) {
            case (.get, "/tasks"): return Self.json(try BrainBuddyAPI.makeEncoder().encode(TaskPageDTO(items: [])))
            case (.get, "/projects"), (.get, "/tags"): return Self.json(Data("[]".utf8))
            case (.get, _): return Self.error(404, "Not found.", request)
            default: return Self.error(503, "Storage is temporarily unavailable; please retry.", request)
            }
        }
    }

    private func login(_ request: HTTPRequest) async -> HTTPResponse {
        struct Credentials: Decodable {
            var email: String
            var password: String
        }
        guard let body = request.body, let credentials = try? JSONDecoder().decode(Credentials.self, from: body) else {
            return Self.error(422, "Request validation failed.", request)
        }
        let opened = state.withLock { state -> (Account, String, Bool, Bool)? in
            guard let account = state.accounts[credentials.email.lowercased()], account.password == credentials.password else {
                return nil
            }
            state.minted += 1
            let token = "stub-session-\(state.minted)"
            state.sessions[token] = account.id
            let cancelled = state.deletionScheduled.remove(account.email.lowercased()) != nil
            let hold = state.holdNextLogin
            state.holdNextLogin = false
            return (account, token, cancelled, hold)
        }
        guard let (account, token, cancelled, hold) = opened else {
            return Self.error(401, "Check your email and password.", request)
        }
        if hold {
            await loginGate.arrive()
            await loginGate.wait()
        }
        let me = MeDTO(id: account.id, email: account.email, deletionCancelled: cancelled)
        var response = Self.json((try? JSONEncoder().encode(me)) ?? Data())
        response.headers["Set-Cookie"] = "brainbuddy_session=\(token); Path=/; HttpOnly; Secure; SameSite=Lax"
        return response
    }

    private static func session(_ request: HTTPRequest) -> String? {
        guard let cookie = request.header("Cookie"), cookie.hasPrefix("brainbuddy_session=") else { return nil }
        return String(cookie.dropFirst("brainbuddy_session=".count))
    }

    private static func json(_ body: Data) -> HTTPResponse {
        HTTPResponse(statusCode: 200, headers: ["Content-Type": "application/json"], body: body)
    }

    private static func error(_ status: Int, _ message: String, _ request: HTTPRequest) -> HTTPResponse {
        let reference = request.header("X-Correlation-ID") ?? "stub"
        let body = Data("{\"message\":\"\(message)\",\"detail\":null,\"reference_id\":\"\(reference)\"}".utf8)
        return HTTPResponse(
            statusCode: status, headers: ["Content-Type": "application/json", "X-Correlation-ID": reference], body: body
        )
    }
}

/// A path monitor a test drives.
final class FakePathMonitor: NetworkPathMonitoring {
    private let report = Mutex<(@Sendable (Bool) -> Void)?>(nil)
    private let stopped = Mutex(false)

    func start(_ report: @escaping @Sendable (Bool) -> Void) { self.report.withLock { $0 = report } }
    func stop() { stopped.withLock { $0 = true } }
    var isStopped: Bool { stopped.withLock { $0 } }
    var isStarted: Bool { report.withLock { $0 != nil } }
}

/// Records the App Nap activity.
@MainActor
final class FakeActivity: SyncActivityHolding {
    private(set) var held = false
    private(set) var begins = 0
    private(set) var ends = 0

    func begin() {
        held = true
        begins += 1
    }

    func end() {
        held = false
        ends += 1
    }
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
