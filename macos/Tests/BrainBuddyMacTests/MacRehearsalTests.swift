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

// The Mac half of the automated pilot rehearsal (spec 026, slice S3): the legacy-fixture import (Q06), the
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
                cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(), now: TestClock().provider,
                makeID: SequentialIDs().provider, log: CapturingMacLog(),
                rustRuntime: try .mac(configuration, tokenStore: tokenStore, transports: transports), rustPilot: switchBox))
    }

    // MARK: Q06: field-by-field import of the legacy fixtures

    private struct Shape: Hashable {
        var text: String
    }

    /// One task as a comparable line: every field the import must carry, projects and tags by name.
    private static func line(_ task: TaskRecord, projects: [ProjectID: ProjectRecord], tags: [TagID: TagRecord]) -> String {
        func instant(_ date: Date?) -> String { date.map { String(Int($0.timeIntervalSince1970)) } ?? "-" }
        let fields: [String] = [
            task.title, task.details ?? "-", task.state.rawValue, task.lastOpenList?.rawValue ?? "-", task.priority.rawValue,
            task.waitingFor ?? "-", task.dueDate?.isoString ?? "-", task.projectID.flatMap { projects[$0]?.name } ?? "-",
            task.tagIDs.compactMap { tags[$0]?.name }.sorted().joined(separator: ","),
            task.subtasks.sorted { $0.orderKey < $1.orderKey }.map { "\($0.title):\($0.state.rawValue)" }.joined(separator: ";"),
            task.comments.map(\.body).joined(separator: ";"), instant(task.createdAt), instant(task.waitingSince),
            instant(task.completedAt), instant(task.cancelledAt),
        ]
        return fields.joined(separator: " | ")
    }

    /// What the Rust-backed workspace shows: every task with its children, projects and tags.
    private static func read(_ workspace: Workspace) async -> (tasks: [String], orders: [String: [String]], projects: [String], tags: [String]) {
        var projectRecords: [ProjectID: ProjectRecord] = [:]
        for archived in [false, true] {
            await workspace.prepareProjects(archived: archived)
            var guardPages = 0
            repeat {
                for summary in workspace.projects(archived: archived) { projectRecords[summary.id] = summary.project }
                if workspace.projectsPageState(archived: archived).hasNext { await workspace.nextProjectsPage(archived: archived) } else { break }
                guardPages += 1
            } while guardPages < 50
        }
        var tagRecords: [TagID: TagRecord] = [:]
        await workspace.prepareTags()
        var tagPages = 0
        repeat {
            for summary in workspace.tags() { tagRecords[summary.id] = summary.tag }
            if workspace.tagsPageState().hasNext { await workspace.nextTagsPage() } else { break }
            tagPages += 1
        } while tagPages < 50

        var seen: [TaskID: TaskRecord] = [:]
        var orders: [String: [String]] = [:]
        let destinations: [(String, Destination)] = OpenList.allCases.map { ($0.rawValue, .list($0)) }
            + HistoryKind.allCases.map { ($0.rawValue, .history($0)) }
            // Inbox shows only projectless tasks: a task in a project is reached through its project.
            + projectRecords.keys.map { ("project:\($0.rawValue)", .project($0)) }
        for (name, destination) in destinations {
            await workspace.prepareList(destination)
            var order: [String] = []
            var pages = 0
            repeat {
                for task in workspace.list(destination).sections.flatMap(\.tasks) {
                    seen[task.id] = task
                    order.append(task.title)
                }
                if workspace.listPageState(destination).hasNext { await workspace.nextListPage(destination) } else { break }
                pages += 1
            } while pages < 200
            orders[name] = order
        }
        var lines: [String] = []
        for id in seen.keys {
            await workspace.prepareTaskDetail(id)
            let detailed = workspace.taskDetail(id) ?? seen[id]!
            lines.append(line(detailed, projects: projectRecords, tags: tagRecords))
        }
        let projectLines = projectRecords.values.map { "\($0.name) | \($0.state.rawValue) | \($0.color ?? "-") | \($0.desiredOutcome ?? "-")" }
        let tagLines = tagRecords.values.map { "\($0.name) | \($0.state.rawValue)" }
        return (lines.sorted(), orders, projectLines.sorted(), tagLines.sorted())
    }

    @Test("Q06 legacy fixtures import into the Rust store field by field (populated, awkward)")
    func q06LegacyImportFieldByField() async throws {
        let recorder = MacRecorder("Q06-import", "legacy-populated and legacy-awkward import, field by field")
        for fixture in ["legacy-populated", "legacy-awkward"] {
            // The oracle: the Mac's own 021 importer on the same bytes with the same clock and ids.
            let oracleFolder = TemporaryFolder()
            try Fixture.install(fixture, in: oracleFolder)
            _ = try LegacyImportCoordinator.forTest(oracleFolder).run()
            let expectedState = try storedState(oracleFolder)
            let expected = expectedState.tasks.values
                .map { Self.line($0, projects: expectedState.projects, tags: expectedState.tags) }.sorted()
            let expectedProjects = expectedState.projects.values
                .map { "\($0.name) | \($0.state.rawValue) | \($0.color ?? "-") | \($0.desiredOutcome ?? "-")" }.sorted()
            let expectedTags = expectedState.tags.values.map { "\($0.name) | \($0.state.rawValue)" }.sorted()

            let folder = TemporaryFolder()
            let original = try Fixture.install(fixture, in: folder)
            let run = try launch(folder, pilot: true)
            await run.run { _ in }
            guard let host = run.host, host.workspace.isRustSelected, host.workspace.isRustBound else {
                recorder.expect(false, "\(fixture): the launch did not select the Rust runtime (importFailed=\(run.importFailed))")
                continue
            }
            let actual = await Self.read(host.workspace)
            recorder.observe("\(fixture).tasks", "expected=\(expected.count) actual=\(actual.tasks.count)")
            recorder.observe("\(fixture).projects", "expected=\(expectedProjects.count) actual=\(actual.projects.count)")
            recorder.observe("\(fixture).tags", "expected=\(expectedTags.count) actual=\(actual.tags.count)")
            let missing = Set(expected).subtracting(actual.tasks)
            let extra = Set(actual.tasks).subtracting(expected)
            recorder.observe("\(fixture).taskMismatches", "missing=\(missing.count) extra=\(extra.count)")
            // Synthetic fixture content only: title, state and last open list identify a task.
            let brief = { (lines: Set<String>) in lines.map { $0.components(separatedBy: " | ").prefix(4).joined(separator: "/") }.sorted().joined(separator: "; ") }
            if !missing.isEmpty { recorder.observe("\(fixture).missing", brief(missing)) }
            if !extra.isEmpty { recorder.observe("\(fixture).extra", brief(extra)) }
            if let first = missing.first, let other = extra.first {
                let a = first.components(separatedBy: " | "), b = other.components(separatedBy: " | ")
                let names = ["title", "details", "state", "lastOpenList", "priority", "waitingFor", "due", "project", "tags", "subtasks", "comments", "created", "waitingSince", "completed", "cancelled"]
                let differing = zip(zip(a, b), names).filter { $0.0.0 != $0.0.1 }.map(\.1)
                recorder.observe("\(fixture).firstMismatchFields", differing.joined(separator: ","))
            }
            recorder.expect(missing.isEmpty && extra.isEmpty && expected.count == actual.tasks.count, "\(fixture): tasks differ field by field")
            recorder.expect(expectedProjects == actual.projects, "\(fixture): projects differ")
            recorder.expect(expectedTags == actual.tags, "\(fixture): tags differ")
            // Order inside each list (manual order) survives the import.
            for list in OpenList.allCases {
                let want = GTDQueries.list(.list(list), options: ListOptions(), in: expectedState, today: CalendarDay(date: TestClock.importTime))
                    .sections.flatMap(\.tasks).map(\.title)
                recorder.expect(want == actual.orders[list.rawValue], "\(fixture): the \(list.rawValue) list order changed")
            }
            // The retired files are kept, never modified.
            recorder.expect(folder.bytes(LegacyFileNames.legacy) == nil || folder.bytes(LegacyFileNames.legacy) == original,
                            "\(fixture): the previous version's file was changed")
            await host.workspace.closeRuntime()
        }
        recorder.finish()
    }

    @Test("Q06 corrupt and newer-version fixtures leave the original untouched and open an empty Rust workspace")
    func q06UnreadableFixturesStayIntact() async throws {
        let recorder = MacRecorder("Q06-unreadable", "legacy-corrupt and legacy-newer: failure leaves the original intact")
        for fixture in ["legacy-corrupt", "legacy-newer"] {
            let folder = TemporaryFolder()
            let original = try Fixture.install(fixture, in: folder)
            let run = try launch(folder, pilot: true)
            await run.run { _ in }
            recorder.expect(folder.bytes(LegacyFileNames.legacy) == original, "\(fixture): the original was modified")
            recorder.observe("\(fixture).phase", run.host == nil ? (run.importFailed ? "importFailed" : "launching") : "ready")
            if let host = run.host {
                await host.workspace.prepareList(.list(.inbox))
                let tasks = OpenList.allCases.reduce(0) { $0 + host.workspace.list(.list($1)).sections.flatMap(\.tasks).count }
                recorder.observe("\(fixture).tasksShown", tasks)
                recorder.expect(tasks == 0, "\(fixture): tasks appeared from an unreadable file")
                await host.workspace.closeRuntime()
            }
        }
        recorder.finish()
    }

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
        await off.run { _ in }
        recorder.expect(off.host?.workspace.isRustSelected == false, "the pilot-off launch selected the Rust runtime")

        let run = try launch(folder, pilot: true, tokenStore: tokens,
                             transports: RustSyncTransportProvider(tokenStore: tokens, identity: WorkspaceHost.clientIdentity))
        await run.run { _ in }
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
