import BrainBuddyAPI
import BrainBuddySync
import Foundation

#if canImport(Darwin)
    import Darwin
#endif
#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The server a rehearsal runs against: the real application as a child process on a loopback port
/// with two synthetic owners (`local`), or the deployed one with the two rehearsal owners (`prod`).
/// Also the harness's own REST client, used to read what the server holds.
final class RehearsalSession: @unchecked Sendable {
    // Safe: set once in `start`, read-only afterwards.
    let target: RehearsalTarget
    let serverURL: URL
    let accounts: [String: RehearsalAccount]
    private let process: Process?
    private let scratch: URL?

    private init(target: RehearsalTarget, serverURL: URL, accounts: [RehearsalAccount], process: Process?, scratch: URL?) {
        self.target = target
        self.serverURL = serverURL
        self.accounts = Dictionary(uniqueKeysWithValues: accounts.map { ($0.label, $0) })
        self.process = process
        self.scratch = scratch
    }

    func account(_ label: String) -> RehearsalAccount { accounts[label]! }

    /// Everything above `/api`: the base the REST helper resolves absolute paths against.
    private var origin: URL { RustSyncURLSession.origin(of: serverURL) }

    static func start() throws -> RehearsalSession {
        switch RehearsalTarget.selected {
        case .prod:
            return RehearsalSession(
                target: .prod, serverURL: RehearsalTarget.prodAPI, accounts: try RehearsalCredentials.prod(),
                process: nil, scratch: nil)
        default:
            return try startLocal()
        }
    }

    private static func startLocal() throws -> RehearsalSession {
        guard let python = ProcessInfo.processInfo.environment["BB_BACKEND_PYTHON"] else {
            throw RehearsalError.backend("BB_BACKEND_PYTHON is unset: no backend to rehearse against")
        }
        // …/ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Rehearsal/<this file> → the repository root.
        var repo = URL(fileURLWithPath: #filePath)
        for _ in 0..<6 { repo.deleteLastPathComponent() }
        let backendDirectory = repo.appendingPathComponent("backend")
        let script = repo.appendingPathComponent("ios/scripts/rehearsal_backend.py")
        let scratch = FileManager.default.temporaryDirectory.appendingPathComponent("bb-rehearsal-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: scratch, withIntermediateDirectories: true)
        let log = scratch.appendingPathComponent("backend.log")
        FileManager.default.createFile(atPath: log.path, contents: nil)
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
            throw RehearsalError.backend("the backend did not announce its accounts; log: \(log.path)")
        }
        let accounts = rows.compactMap { row -> RehearsalAccount? in
            guard let label = row["label"], let email = row["email"], let password = row["password"] else { return nil }
            return RehearsalAccount(label: label, email: email, password: password, id: row["id"])
        }
        // `localhost`, not `127.0.0.1`: the kit accepts plain http only for that host.
        let session = RehearsalSession(
            target: .local, serverURL: URL(string: "http://localhost:\(port)/api")!, accounts: accounts,
            process: process, scratch: scratch)
        guard session.waitUntilHealthy() else {
            session.stop()
            throw RehearsalError.backend("the backend never became healthy; log: \(log.path)")
        }
        return session
    }

    func stop() {
        if let process, process.isRunning { process.terminate() }
        process?.waitUntilExit()
        if let scratch { try? FileManager.default.removeItem(at: scratch) }
    }

    private func waitUntilHealthy() -> Bool {
        let deadline = Date().addingTimeInterval(120)
        while Date() < deadline {
            if let result = try? rest("GET", "/health", token: nil), result.status == 200 { return true }
            Thread.sleep(forTimeInterval: 0.1)
        }
        return false
    }

    struct Reply { let status: Int; let data: Data; let correlationID: String?; let setCookie: String? }

    /// Blocking REST. `token` is the session a device holds; nil is anonymous.
    func rest(_ method: String, _ path: String, token: String?, body: Data? = nil) throws -> Reply {
        try RehearsalRoutes.check(path)
        guard RehearsalBudget.shared.spend() else { throw RehearsalError.budgetExhausted }
        var request = URLRequest(url: URL(string: origin.absoluteString + path)!)
        request.httpMethod = method
        request.httpBody = body
        let correlation = UUID().uuidString.lowercased()
        request.setValue(correlation, forHTTPHeaderField: "X-Correlation-ID")
        request.setValue("brainbuddy-rehearsal/1", forHTTPHeaderField: "X-Client")
        if body != nil { request.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token {
            request.setValue("brainbuddy_session=\(token)", forHTTPHeaderField: "Cookie")
            if method != "GET" { request.setValue(UUID().uuidString.lowercased(), forHTTPHeaderField: "Idempotency-Key") }
        }
        let done = DispatchSemaphore(value: 0)
        nonisolated(unsafe) var result: Reply?  // Safe: written once by the completion, read after `done`.
        nonisolated(unsafe) var failure: (any Error)?
        URLSession.shared.dataTask(with: request) { data, response, error in
            if let http = response as? HTTPURLResponse {
                result = Reply(status: http.statusCode, data: data ?? Data(),
                               correlationID: http.value(forHTTPHeaderField: "X-Correlation-ID") ?? correlation,
                               setCookie: http.value(forHTTPHeaderField: "Set-Cookie"))
            } else { failure = error }
            done.signal()
        }.resume()
        done.wait()
        if let result { return result }
        throw failure ?? URLError(.badServerResponse)
    }

    /// The titles of every task the session's owner has on the server (Inbox to Someday, and done).
    func titles(token: String) throws -> [String] {
        var all: [String] = []
        var path = "/api/tasks?limit=200"
        for _ in 0..<20 {
            let reply = try rest("GET", path, token: token)
            guard reply.status == 200, let page = try JSONSerialization.jsonObject(with: reply.data) as? [String: Any],
                  let items = page["items"] as? [[String: Any]] else { throw RehearsalError.backend("GET tasks answered \(reply.status) \(String(decoding: reply.data.prefix(300), as: UTF8.self))") }
            all += items.compactMap { $0["title"] as? String }
            guard let next = page["next_cursor"] as? String, !next.isEmpty else { break }
            path = "/api/tasks?limit=200&cursor=\(next.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? next)"
        }
        return all
    }

    /// A fresh session for the account (the harness's own, never a device's), e.g. to read an account's data
    /// after a device signed its session out.
    func login(_ label: String) throws -> String {
        let account = account(label)
        let body = try JSONSerialization.data(withJSONObject: ["email": account.email, "password": account.password])
        let reply = try rest("POST", "/api/auth/login", token: nil, body: body)
        guard reply.status == 200, let cookie = reply.setCookie, let range = cookie.range(of: "brainbuddy_session=") else {
            throw RehearsalError.backend("login answered \(reply.status)")
        }
        return String(cookie[range.upperBound...].prefix { $0 != ";" })
    }

    /// Title → state of every task the owner has on the server (for a result record).
    func states(token: String) throws -> [String: String] {
        let reply = try rest("GET", "/api/tasks?limit=200", token: token)
        guard reply.status == 200, let page = try JSONSerialization.jsonObject(with: reply.data) as? [String: Any],
              let items = page["items"] as? [[String: Any]] else { return [:] }
        return Dictionary(items.compactMap { item in (item["title"] as? String).map { ($0, item["state"] as? String ?? "?") } },
                          uniquingKeysWith: { first, _ in first })
    }

    /// The email the session belongs to (`/auth/me`).
    func email(token: String) throws -> (email: String, correlationID: String?) {
        let reply = try rest("GET", "/api/auth/me", token: token)
        guard reply.status == 200, let object = try JSONSerialization.jsonObject(with: reply.data) as? [String: Any],
              let email = object["email"] as? String else { throw RehearsalError.backend("GET auth/me answered \(reply.status)") }
        return (email, reply.correlationID)
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
