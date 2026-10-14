import Foundation
import XCTest

/// Everything the rehearsal needs from outside the app: the local backend (reached through a fault
/// proxy, see scripts/rehearsal/ui_backend.py), the synthetic accounts, and where results go.
/// Values come from `TEST_RUNNER_BB_REHEARSAL_*` environment variables set by
/// scripts/rehearsal/run_ios_ui.sh; the defaults match that script's default port.
enum Rehearsal {
    static let environment = ProcessInfo.processInfo.environment
    /// What the app is given as its "Server address". `localhost`, never a literal loopback IP: ATS.
    static let api = environment["BB_REHEARSAL_API"] ?? "http://localhost:18700/api"
    /// The real server, behind the proxy: the runner's own REST calls (the "other device") never see injected faults.
    static let direct = environment["BB_REHEARSAL_DIRECT"] ?? "http://localhost:18701/api"
    static let control = environment["BB_REHEARSAL_CONTROL"] ?? "http://localhost:18702"
    static let screensDirectory = environment["BB_REHEARSAL_SCREENS"] ?? "/tmp/bb-rehearsal/screens"
    static let resultsFile = environment["BB_REHEARSAL_RESULTS"] ?? "/tmp/bb-rehearsal/results.tsv"

    static let accountA = Account(email: "rehearsal-a@example.com", password: "rehearsal-a-password-1")
    static let accountB = Account(email: "rehearsal-b@example.com", password: "rehearsal-b-password-1")

    struct Account {
        let email: String
        let password: String
    }

    enum Mode: String { case up, down, unauth }

    typealias ServerTask = (title: String, state: String, completed: Bool)

    /// Flips the fault proxy: `down` refuses every connection, `unauth` answers 401.
    static func setServer(_ mode: Mode) async throws {
        let (_, response) = try await URLSession.shared.data(from: URL(string: "\(control)/mode/\(mode.rawValue)")!)
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
    }

    /// Asks the backend script to create a Next task for account A whose wording clock started
    /// `days` ago, so Weekly Review's decision step asks about it. Returns the server's reply.
    static func seedStalled(_ title: String, days: Int = 30) async throws -> String {
        let query = title.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? title
        let (data, _) = try await URLSession.shared.data(from: URL(string: "\(control)/seed-stalled?owner=a&days=\(days)&title=\(query)")!)
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// A control call on the backend script (`hold/on`, `hold/off`, `mode/up` ...): the JSON body.
    @discardableResult
    static func controlCall(_ path: String) async throws -> String {
        let (data, _) = try await URLSession.shared.data(from: URL(string: "\(control)/\(path)")!)
        return String(data: data, encoding: .utf8) ?? ""
    }

    /// `METHOD /path` lines the proxy forwarded since the server started (for "nothing was sent" checks).
    static func forwardedRequests() async throws -> [String] {
        let data = try await controlCall("requests")
        let object = try JSONSerialization.jsonObject(with: Data(data.utf8)) as? [String: Any]
        return object?["requests"] as? [String] ?? []
    }

    static func suggestionRequestCount() async throws -> Int {
        try await forwardedRequests().filter { $0.contains("/review/navigator/suggestions") }.count
    }

    /// One line per checked item: `id<TAB>PASS|FAIL|NOT_AUTOMATED<TAB>note`.
    static func record(_ id: String, _ status: String, _ note: String) {
        let line = "\(id)\t\(status)\t\(note.replacingOccurrences(of: "\n", with: " "))\n"
        let url = URL(fileURLWithPath: resultsFile)
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let handle = try? FileHandle(forWritingTo: url) {
            handle.seekToEndOfFile()
            handle.write(Data(line.utf8))
            try? handle.close()
        } else {
            try? Data(line.utf8).write(to: url)
        }
    }

    /// The server's own view of an account's tasks (REST, as the web client sees them).
    final class Server: @unchecked Sendable {  // only used from one test at a time
        private let session = URLSession(configuration: .ephemeral)

        func login(_ account: Account) async throws {
            var request = URLRequest(url: URL(string: "\(Rehearsal.direct)/auth/login")!)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["email": account.email, "password": account.password])
            let (_, response) = try await session.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.userAuthenticationRequired) }
        }

        func tasks() async throws -> [ServerTask] {
            let url = URL(string: "\(Rehearsal.direct)/tasks?include_completed=true&include_cancelled=true&limit=200")!
            let (data, _) = try await session.data(from: url)
            let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            let items = object?["items"] as? [[String: Any]] ?? []
            return items.map { ($0["title"] as? String ?? "", $0["state"] as? String ?? "", $0["completed_at"] is String) }
        }

        /// The other device: renames a task on the server directly (REST needs the current revision).
        func rename(taskTitled old: String, to title: String) async throws {
            let url = URL(string: "\(Rehearsal.direct)/tasks?include_completed=true&limit=200")!
            let (data, _) = try await session.data(from: url)
            let items = (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["items"] as? [[String: Any]] ?? []
            guard let task = items.first(where: { $0["title"] as? String == old }),
                  let id = task["id"] as? String, let revision = task["revision"] as? Int else { throw URLError(.fileDoesNotExist) }
            var request = URLRequest(url: URL(string: "\(Rehearsal.direct)/tasks/\(id)")!)
            request.httpMethod = "PATCH"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
            request.httpBody = try JSONSerialization.data(withJSONObject: ["title": title, "expected_revision": revision])
            let (body, response) = try await session.data(for: request)
            guard (200..<300).contains((response as? HTTPURLResponse)?.statusCode ?? 0) else {
                throw NSError(domain: "rename", code: (response as? HTTPURLResponse)?.statusCode ?? 0, userInfo: [NSLocalizedDescriptionKey: String(data: body, encoding: .utf8) ?? ""])
            }
        }

        /// Polls until `check` holds for the server's tasks or the time runs out; returns the last read.
        func waitFor(timeout: TimeInterval = 30, _ check: ([ServerTask]) -> Bool) async -> [ServerTask] {
            let deadline = Date().addingTimeInterval(timeout)
            var latest: [ServerTask] = []
            while Date() < deadline {
                if let tasks = try? await tasks() {
                    latest = tasks
                    if check(tasks) { return tasks }
                }
                try? await Task.sleep(for: .seconds(1))
            }
            return latest
        }
    }
}

extension XCTestCase {
    /// Records one rehearsal item and fails the test (without stopping it) when `condition` is false.
    func check(_ id: String, _ condition: Bool, pass: String, fail: String, line: UInt = #line) {
        // A FINDING-* item "passes" by reproducing the defect it documents.
        Rehearsal.record(id, condition ? (id.hasPrefix("FINDING") ? "FINDING" : "PASS") : "FAIL", condition ? pass : fail)
        XCTAssertTrue(condition, "\(id): \(fail)", line: line)
    }

    /// Saves a screenshot under the rehearsal evidence folder and attaches it to the result bundle.
    @MainActor func shot(_ app: XCUIApplication, _ name: String) {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
        let directory = URL(fileURLWithPath: Rehearsal.screensDirectory)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? screenshot.pngRepresentation.write(to: directory.appendingPathComponent("\(name).png"))
    }

    /// The accessibility tree as text, for working out what a screen exposes.
    @MainActor func dump(_ app: XCUIApplication, _ name: String) {
        let directory = URL(fileURLWithPath: "/tmp/bb-rehearsal/dumps")
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? app.debugDescription.write(to: directory.appendingPathComponent("\(name).txt"), atomically: true, encoding: .utf8)
    }
}
