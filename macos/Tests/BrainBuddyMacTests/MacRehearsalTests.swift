import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore

#if canImport(Darwin)
    import Darwin
#endif
#if canImport(FoundationModels)
    import FoundationModels
#endif

// The Mac half of the automated pilot rehearsal (spec 026, slice S3): the
// Mac launch with its Rust host against a local backend (Q01/Q09 probe). Opt-in, like the kit's
// `Rehearsal` suites:
//
//     BB_REHEARSAL_TARGET=local BB_BACKEND_PYTHON=/path/to/venv/bin/python swift test --filter MacRehearsal
//
// Results are rehearsal results, never reference-device evidence. They are written as JSON to
// $BB_REHEARSAL_OUT (default /tmp); `python3 ios/scripts/rehearsal_report.py` merges them into the
// "S3 Swift driver" section of specs/026-rust-core-sync/evidence/rehearsal-<date>.md.

private let rehearsalEnabled = ProcessInfo.processInfo.environment["BB_REHEARSAL_TARGET"] != nil

private struct MacRecord: Codable {
    var id: String
    var title: String
    var target = "local"
    var verdict: String
    var observed: [String: String]
    var correlationIDs: [String] = []
    var failures: [String]
    var note = ""
    var seconds: Double
    var configuration: String
}

/// Collects a scenario's observations and failed checks, and writes its record.
private final class MacRecorder {
    let id: String
    let title: String
    private var observed: [String: String] = [:]
    private var failures: [String] = []
    private var correlation: [String] = []
    private let started = Date()

    init(_ id: String, _ title: String) {
        self.id = id
        self.title = title
    }

    func observe(_ key: String, _ value: Any) { observed[key] = String(describing: value) }
    func correlate(_ id: String?) { if let id { correlation.append(id) } }

    func expect(_ condition: Bool, _ message: String, sourceLocation: SourceLocation = #_sourceLocation) {
        if !condition { failures.append(message) }
        #expect(condition, Comment(rawValue: message), sourceLocation: sourceLocation)
    }

    func finish(note: String = "", verdict: String? = nil) {
        #if DEBUG
            let configuration = "debug"
        #else
            let configuration = "release"
        #endif
        let record = MacRecord(
            id: id, title: title, verdict: verdict ?? (failures.isEmpty ? "PASS" : "FAIL"), observed: observed,
            correlationIDs: correlation, failures: failures, note: note, seconds: Date().timeIntervalSince(started),
            configuration: configuration)
        let out = URL(fileURLWithPath: ProcessInfo.processInfo.environment["BB_REHEARSAL_OUT"] ?? "/tmp", isDirectory: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
        try? encoder.encode(record).write(to: out.appendingPathComponent("rehearsal-s3-local-\(id)-\(configuration).json"))
    }
}

@Suite("Mac pilot rehearsal (026 Q01, Q06, Q09 probe)", .enabled(if: rehearsalEnabled, "opt-in rehearsal: set BB_REHEARSAL_TARGET"), .serialized)
@MainActor
struct MacRehearsalTests {
    // MARK: Launch helpers

    private func launch(_ folder: TemporaryFolder, pilot: Bool, tokenStore: any SessionTokenStore = SpyTokenStore(),
                        transports: (any RustTransportProvider)? = nil) throws -> MacLaunch {
        let switchBox = RustRuntimePilotSwitch(suiteName: "mac-rehearsal-\(UUID().uuidString)")
        switchBox.set(pilot)
        let configuration = MacHostConfiguration(directory: folder.url, isDryRun: false)
        return MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: configuration, tokenStore: tokenStore, transport: CountingTransport(),
                now: TestClock().provider,
                makeID: SequentialIDs().provider, log: CapturingMacLog(),
                rustRuntime: try .mac(configuration, tokenStore: tokenStore, transports: transports), rustPilot: switchBox))
    }

    // MARK: Q06: faults

    @Test("Q06 not automated here: low disk and a competing widget writer during the import")
    func q06FaultsNotAutomated() {
        MacRecorder("Q06-faults", "low disk and a competing widget writer during the import").finish(
            note: "Needs a full volume and a second process holding the document lock mid-import; covered by the kit's RustStoreImporter tests and bb-client import.rs, not driven from this headless run.",
            verdict: "NOT_AUTOMATED")
    }

    // MARK: Mac launch with the Rust host on a local backend

    @Test("Q01 the Mac selects the Rust runtime, signs in and syncs through the Rust host against a local backend")
    func macHostLaunchSyncsToLocalBackend() async throws {
        let recorder = MacRecorder("Mac-host", "Mac launch: WorkspaceHost selection, sign-in and Rust host against a local backend")
        guard let python = ProcessInfo.processInfo.environment["BB_BACKEND_PYTHON"] else {
            recorder.expect(false, "BB_BACKEND_PYTHON is unset")
            recorder.finish()
            return
        }
        let backend = try LocalBackend.start(python: python)
        defer { backend.stop() }
        let folder = TemporaryFolder()
        let tokens = InMemorySessionTokenStore()
        let account = backend.accounts[0]

        // Pilot off: the legacy runtime, no selection written (WorkspaceHost selection, FR-025).
        let off = try launch(TemporaryFolder(), pilot: false)
        await off.run()
        recorder.expect(off.host?.workspace.isRustSelected == false, "the pilot-off launch selected the Rust runtime")

        let run = try launch(folder, pilot: true, tokenStore: tokens,
                             transports: RustSyncTransportProvider(tokenStore: tokens, identity: WorkspaceHost.clientIdentity))
        await run.run()
        guard let host = run.host, host.workspace.isRustSelected else {
            recorder.expect(false, "the pilot-on launch did not select the Rust runtime")
            recorder.finish()
            return
        }
        recorder.expect(host.workspace.isRustBound, "the Rust runtime is not bound")
        recorder.observe("clientIdentity", WorkspaceHost.clientIdentity.name)
        try await host.workspace.signIn(serverURL: backend.serverURL, email: account.email, password: account.password)
        recorder.expect(host.workspace.account?.email == account.email, "the Mac is not signed in as the account")
        let title = "Mac rehearsal \(UUID().uuidString.prefix(6))"
        _ = try await host.workspace.capture(CaptureDraft(text: title), editorID: "scene:mac:capture")
        var onServer = false
        for _ in 0..<150 where !onServer {
            await host.workspace.syncNow()
            let token = try tokens.token(for: backend.serverURL) ?? ""
            let reply = try backend.get("/api/tasks?limit=200", token: token)
            recorder.correlate(reply.correlationID)
            onServer = String(decoding: reply.data, as: UTF8.self).contains(title)
            if !onServer { try? await Task.sleep(for: .milliseconds(100)) }
        }
        await host.workspace.syncNow()  // also refreshes the status the next lines read
        recorder.observe("syncStatus", String(describing: host.workspace.syncStatus).prefix(80))
        recorder.observe("pendingAfterSync", host.workspace.pendingChangeCount)
        recorder.expect(onServer, "the Mac's capture never reached the server through the Rust host")
        recorder.expect(host.workspace.pendingChangeCount == 0, "changes are still waiting after the server accepted them")
        await host.workspace.closeRuntime()
        recorder.finish()
    }

    // MARK: On-device model probe (availability only)

    @Test("Q09 probe: report SystemLanguageModel availability only; no request is made")
    func onDeviceModelProbe() {
        let recorder = MacRecorder("Q09-probe", "on-device model availability (no request)")
        #if canImport(FoundationModels)
            let availability = SystemLanguageModel.default.availability
            switch availability {
            case .available: recorder.observe("systemLanguageModel", "available")
            case .unavailable(let reason): recorder.observe("systemLanguageModel", "unavailable: \(reason)")
            }
        #else
            recorder.observe("systemLanguageModel", "FoundationModels is not importable on this toolchain")
        #endif
        recorder.finish(note: "Availability only: no prompt was sent. Suitable/absent/failed local-model paths of Q09 need a reference device.")
    }
}

// MARK: - A local backend (the kit rehearsal's, for this package)

private final class LocalBackend: @unchecked Sendable {
    // Safe: set once in `start`, read-only afterwards.
    struct Account { let email: String; let password: String }
    struct Reply { let status: Int; let data: Data; let correlationID: String? }
    let process: Process
    let port: Int
    let accounts: [Account]
    let scratch: URL

    var serverURL: URL { URL(string: "http://localhost:\(port)/api")! }

    private init(process: Process, port: Int, accounts: [Account], scratch: URL) {
        self.process = process
        self.port = port
        self.accounts = accounts
        self.scratch = scratch
    }

    static func start(python: String) throws -> LocalBackend {
        // macos/Tests/BrainBuddyMacTests/<this file> → the repository root.
        var repo = URL(fileURLWithPath: #filePath)
        for _ in 0..<4 { repo.deleteLastPathComponent() }
        let backendDirectory = repo.appendingPathComponent("backend")
        let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("bb-mac-rehearsal-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        let log = scratch.appendingPathComponent("backend.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
        let port = try freePort()
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [repo.appendingPathComponent("ios/scripts/rehearsal_backend.py").path, scratch.appendingPathComponent("data").path, String(port)]
        process.currentDirectoryURL = backendDirectory
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = backendDirectory.path
        process.environment = environment
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle(forWritingAtPath: log.path)
        try process.run()
        var announced = Data()
        let deadline = Date().addingTimeInterval(120)
        while Date() < deadline, !announced.contains(UInt8(ascii: "\n")) {
            let chunk = output.fileHandleForReading.availableData
            if chunk.isEmpty { break }
            announced.append(chunk)
        }
        guard let line = String(decoding: announced, as: UTF8.self).split(separator: "\n").first(where: { $0.hasPrefix("{") }),
              let info = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
              let rows = info["accounts"] as? [[String: String]]
        else {
            process.terminate()
            throw URLError(.cannotConnectToHost)
        }
        let accounts = rows.compactMap { row in row["email"].flatMap { email in row["password"].map { Account(email: email, password: $0) } } }
        let backend = LocalBackend(process: process, port: port, accounts: accounts, scratch: scratch)
        let healthy = Date().addingTimeInterval(120)
        while Date() < healthy {
            if let reply = try? backend.get("/health", token: nil), reply.status == 200 { return backend }
            Thread.sleep(forTimeInterval: 0.1)
        }
        backend.stop()
        throw URLError(.timedOut)
    }

    func stop() {
        if process.isRunning { process.terminate() }
        process.waitUntilExit()
        try? FileManager.default.removeItem(at: scratch)
    }

    func get(_ path: String, token: String?) throws -> Reply {
        var request = URLRequest(url: URL(string: "http://localhost:\(port)\(path)")!)
        let correlation = UUID().uuidString.lowercased()
        request.setValue(correlation, forHTTPHeaderField: "X-Correlation-ID")
        if let token { request.setValue("brainbuddy_session=\(token)", forHTTPHeaderField: "Cookie") }
        let done = DispatchSemaphore(value: 0)
        nonisolated(unsafe) var result: Reply?  // Safe: written once by the completion, read after `done`.
        URLSession.shared.dataTask(with: request) { data, response, _ in
            if let http = response as? HTTPURLResponse { result = Reply(status: http.statusCode, data: data ?? Data(), correlationID: correlation) }
            done.signal()
        }.resume()
        done.wait()
        guard let result else { throw URLError(.badServerResponse) }
        return result
    }

    private static func freePort() throws -> Int {
        let socket = socket(AF_INET, SOCK_STREAM, 0)
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
