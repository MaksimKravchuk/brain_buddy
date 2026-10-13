import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

#if canImport(Darwin)
    import Darwin
#elseif canImport(Glibc)
    import Glibc
#endif
#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The Apple host against the real application (`backend/app.main` on a loopback port, the same
/// server `rust/crates/bb-client/tests/hints_backend.rs` and `e2e_backend.rs` start). Opt-in, because
/// it needs a Python environment with the backend's dependencies:
///
///     BB_BACKEND_PYTHON=/path/to/venv/bin/python swift test --filter RustSyncHostBackend
///
/// Unset, the test is skipped (and says why in its name); nothing here is mocked.
@Suite("Rust sync host against the real backend (026-FR-004, 026-FR-005, 026-FR-007)")
struct RustSyncHostBackendTests {
    static let python = ProcessInfo.processInfo.environment["BB_BACKEND_PYTHON"]

    @Test(
        "026-FR-005 026-FR-007: a Workspace edit reaches the server and a web write arrives (opt-in: set BB_BACKEND_PYTHON)",
        .enabled(if: Self.python != nil, "BB_BACKEND_PYTHON is unset: the real backend is not exercised"))
    @MainActor
    func editGoesOutAndWebWriteComesIn() async throws {
        let backend = try RealBackend.start(python: try #require(Self.python))
        defer { backend.stop() }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        let account = LinkedAccount(id: backend.owner, email: "bb-client@example.com", serverURL: backend.serverURL,
            linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
        let source = root.appendingPathComponent("document.json")
        try StoreDocumentCoding.makeEncoder().encode(StoreDocument(base: .empty, account: account)).write(to: source)
        let database = root.appendingPathComponent("store.sqlite3")
        let bridge = try RustBridgeRuntime()
        _ = try await bridge.importLegacyStore(.init(workspaceID: backend.owner, databasePath: database.path,
            sourcePath: source.path, now: "2026-09-21T00:00:00Z"))
        let runtime = try await bridge.openStore(workspaceID: backend.owner, databaseURL: database)

        let instant = Date()
        let policy = Data(#"{"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8)
        let host = try await RustSyncHost.start(
            workspaceID: backend.owner, databaseURL: database,
            binding: .init(accountID: backend.owner, scopeID: backend.owner, deviceID: "device-swift", freshAuthentication: true),
            context: RustWorkspaceContext(now: instant, timeZone: "UTC", actorID: backend.owner, policy: policy),
            serverURL: backend.serverURL, tokenStore: InMemorySessionTokenStore(tokens: [backend.serverURL: backend.token]))
        let selection = RustWorkspaceSelection(runtime: runtime,
            facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
            transport: host, account: account, startup: .prepared)
        let workspace = Workspace(store: ControlledStore(), sync: nil, rust: selection, now: { Date() })
        await workspace.load()
        await workspace.syncNow()
        #expect(workspace.syncStatus != .needsSignIn)

        // The edit made here is on the server.
        _ = try await workspace.capture(CaptureDraft(text: "Written in the app"), editorID: "scene:backend:capture")
        #expect(await backend.eventually { try backend.titles().contains("Written in the app") })
        await workspace.syncNow()
        await workspace.refreshRustStatus()
        #expect(workspace.pendingChangeCount == 0)

        // A write made on the web comes in (the hint stream wakes the loop; the 30 s poll backs it).
        try backend.createTask("Written on the web")
        var titles = Set<String>()
        for _ in 0..<600 where !titles.contains("Written on the web") {
            await workspace.prepareList(.list(.inbox))
            titles = Set(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title))
            try? await Task.sleep(for: .milliseconds(100))
        }
        #expect(titles == ["Written in the app", "Written on the web"])
        await workspace.closeRuntime()
    }
}

/// The real application as a child process (`rust/crates/bb-client/tests/support/sse_backend.py`).
private final class RealBackend: @unchecked Sendable {
    // Safe: set once in `start`, read-only afterwards.
    let process: Process
    let port: Int
    let owner: String
    let token: String
    let scratch: URL

    var serverURL: URL { URL(string: "http://127.0.0.1:\(port)/api")! }

    private init(process: Process, port: Int, owner: String, token: String, scratch: URL) {
        self.process = process
        self.port = port
        self.owner = owner
        self.token = token
        self.scratch = scratch
    }

    static func start(python: String) throws -> RealBackend {
        // …/ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/<this file> → the repository root.
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let backendDirectory = repo.appendingPathComponent("backend")
        let script = repo.appendingPathComponent("rust/crates/bb-client/tests/support/sse_backend.py")
        let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("bb-swift-backend-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        let port = try freePort()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [script.path, scratch.appendingPathComponent("data").path, String(port)]
        process.currentDirectoryURL = backendDirectory
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = backendDirectory.path
        process.environment = environment
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle(forWritingAtPath: scratch.appendingPathComponent("backend.log").path)
            ?? { FileManager.default.createFile(atPath: scratch.appendingPathComponent("backend.log").path, contents: nil)
                 return FileHandle(forWritingAtPath: scratch.appendingPathComponent("backend.log").path)! }()
        try process.run()

        // The first JSON line announces the signed-in owner and its session cookie.
        var announced = Data()
        let deadline = Date().addingTimeInterval(120)
        let handle = output.fileHandleForReading
        while Date() < deadline, !announced.contains(UInt8(ascii: "\n")) {
            let chunk = handle.availableData
            if chunk.isEmpty { break }
            announced.append(chunk)
        }
        guard let line = String(decoding: announced, as: UTF8.self).split(separator: "\n").first(where: { $0.hasPrefix("{") }),
              let info = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
              let owner = info["owner"] as? String, let cookie = info["cookie"] as? String,
              let value = cookie.split(separator: "=", maxSplits: 1).last
        else {
            process.terminate()
            throw BackendError.noAnnouncement(log: scratch.appendingPathComponent("backend.log").path)
        }
        let backend = RealBackend(process: process, port: port, owner: owner, token: String(value), scratch: scratch)
        guard backend.waitUntilHealthy() else {
            backend.stop()
            throw BackendError.notHealthy(log: scratch.appendingPathComponent("backend.log").path)
        }
        return backend
    }

    enum BackendError: Error { case noAnnouncement(log: String), notHealthy(log: String) }

    func stop() {
        if process.isRunning { process.terminate() }
        process.waitUntilExit()
        try? FileManager.default.removeItem(at: scratch)
    }

    private func waitUntilHealthy() -> Bool {
        let deadline = Date().addingTimeInterval(120)
        while Date() < deadline {
            if let (status, _) = try? request("GET", "/health", authorized: false), status == 200 { return true }
            Thread.sleep(forTimeInterval: 0.1)
        }
        return false
    }

    /// Blocking REST as the signed-in owner (the web client's side).
    func request(_ method: String, _ path: String, body: Data? = nil, authorized: Bool = true) throws -> (Int, Data) {
        var request = URLRequest(url: URL(string: "http://127.0.0.1:\(port)\(path)")!)
        request.httpMethod = method
        request.httpBody = body
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if authorized {
            request.setValue("brainbuddy_session=\(token)", forHTTPHeaderField: "Cookie")
            request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "Idempotency-Key")
        }
        let done = DispatchSemaphore(value: 0)
        nonisolated(unsafe) var result: (Int, Data)?
        nonisolated(unsafe) var failure: (any Error)?
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let http = response as? HTTPURLResponse { result = (http.statusCode, data ?? Data()) } else { failure = error }
            done.signal()
        }.resume()
        done.wait()
        if let result { return result }
        throw failure ?? URLError(.badServerResponse)
    }

    func titles() throws -> [String] {
        let (status, body) = try request("GET", "/api/tasks?limit=200")
        guard status == 200, let page = try JSONSerialization.jsonObject(with: body) as? [String: Any],
              let items = page["items"] as? [[String: Any]] else { return [] }
        return items.compactMap { $0["title"] as? String }
    }

    func createTask(_ title: String) throws {
        let (status, _) = try request("POST", "/api/tasks", body: try JSONSerialization.data(withJSONObject: ["title": title]))
        #expect(status == 201)
    }

    func eventually(timeout: TimeInterval = 30, _ check: @Sendable () throws -> Bool) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if (try? check()) == true { return true }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return false
    }

    private static func freePort() throws -> Int {
        #if canImport(Darwin)
            let stream = SOCK_STREAM
        #else
            let stream = Int32(SOCK_STREAM.rawValue)
        #endif
        let socket = socket(AF_INET, stream, 0)
        defer { close(socket) }
        var address = sockaddr_in()
        address.sin_family = sa_family_t(AF_INET)
        address.sin_addr.s_addr = inet_addr("127.0.0.1")
        address.sin_port = 0
        let bound = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(socket, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
        }
        guard bound == 0 else { throw URLError(.cannotConnectToHost) }
        var length = socklen_t(MemoryLayout<sockaddr_in>.size)
        let named = withUnsafeMutablePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { getsockname(socket, $0, &length) }
        }
        guard named == 0 else { throw URLError(.cannotConnectToHost) }
        return Int(UInt16(bigEndian: address.sin_port))
    }
}
