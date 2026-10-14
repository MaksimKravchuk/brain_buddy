import Foundation
import Synchronization
import Testing

#if canImport(Security)
    import Security
#endif

// The automated rehearsal of the Apple pilot scenarios Q01-Q12 (spec 026, quickstart.md), slice S3: a
// headless Swift driver. It is an OPT-IN harness, not a product test: every suite carries `.rehearsal`,
// which keeps a normal `swift test` from running it. Its results are rehearsal results, never
// reference-device evidence (evidence/apple-pilot.md is not touched).
//
//     BB_REHEARSAL_TARGET=local BB_BACKEND_PYTHON=/path/to/venv/bin/python swift test --filter Rehearsal
//
// `prod` additionally needs BB_REHEARSAL_CONFIRM_PROD=brain-buddy-frontend.fly.dev, the Keychain items
// (service `brainbuddy-rehearsal`, accounts `A` and `B`, the password as the item's data) and the
// emails in BB_REHEARSAL_EMAIL_A / BB_REHEARSAL_EMAIL_B. Results go to $BB_REHEARSAL_OUT (default /tmp) as one
// JSON file per scenario; `python3 ios/scripts/rehearsal_report.py` writes the "S3 Swift driver" section of
// specs/026-rust-core-sync/evidence/rehearsal-<date>.md from them. SC-003 is judged in a release build:
// `swift test -c release -Xswiftc -enable-testing --filter RehearsalPerformanceTests/sc003`.

enum RehearsalTarget: String, Sendable {
    case local, prod

    static let selected: RehearsalTarget? = ProcessInfo.processInfo.environment["BB_REHEARSAL_TARGET"]
        .flatMap(RehearsalTarget.init(rawValue:))
    static let prodHost = "brain-buddy-frontend.fly.dev"
    static let prodAPI = URL(string: "https://\(prodHost)/api")!
    /// Requests one run may send to the deployed server (sync transport and REST helper together).
    static let prodRequestBudget = 300
    static let keychainService = "brainbuddy-rehearsal"
    static var isProd: Bool { selected == .prod }

    /// Run-unique text so a repeated prod run never collides with an earlier one's content.
    static let runTag = String(UUID().uuidString.lowercased().prefix(6))
}

extension Trait where Self == ConditionTrait {
    /// The rehearsal is opt-in: nothing runs unless BB_REHEARSAL_TARGET names a target.
    static var rehearsal: Self {
        .enabled(if: RehearsalTarget.selected != nil, "opt-in rehearsal: set BB_REHEARSAL_TARGET=local|prod")
    }
}

enum RehearsalError: Error, CustomStringConvertible {
    case prodNotConfirmed
    case keychain(account: String, status: Int32)
    case missingEmail(String)
    case unexpectedIdentity
    case refusedRoute(String)
    case budgetExhausted
    case backend(String)

    var description: String {
        switch self {
        case .prodNotConfirmed: "BB_REHEARSAL_CONFIRM_PROD must equal \(RehearsalTarget.prodHost)"
        case .keychain(let account, let status): "no Keychain item for account \(account) (status \(status))"
        case .missingEmail(let name): "\(name) is not set"
        case .unexpectedIdentity: "the signed-in email is not one of the rehearsal accounts"
        case .refusedRoute(let path): "refused route on prod: \(path)"
        case .budgetExhausted: "the request budget of this run is spent"
        case .backend(let message): message
        }
    }
}

/// The request budget of one run. Counted by the fault-injecting transport and the REST helper; only
/// the deployed server is limited.
final class RehearsalBudget: Sendable {
    static let shared = RehearsalBudget()
    private let spentCount = Mutex(0)

    var spent: Int { spentCount.withLock { $0 } }

    /// False when the request must not go out.
    func spend() -> Bool {
        spentCount.withLock { count in
            if RehearsalTarget.isProd, count >= RehearsalTarget.prodRequestBudget { return false }
            count += 1
            return true
        }
    }
}

/// Routes a prod run never touches: AI suggestion requests (they cost provider money) and admin.
enum RehearsalRoutes {
    static func check(_ path: String) throws {
        guard RehearsalTarget.isProd else { return }
        let lowered = path.lowercased()
        let banned = ["suggest", "/admin", "/ai/", "/navigator", "/voice", "/transcri"]
        if banned.contains(where: { lowered.contains($0) }) { throw RehearsalError.refusedRoute(path) }
    }
}

// MARK: - Credentials

struct RehearsalAccount: Sendable {
    let label: String
    let email: String
    let password: String
    /// The server's id for the owner, where the harness knows it (local).
    let id: String?
}

enum RehearsalCredentials {
    /// Prod credentials come from the Keychain only (never from the environment, a file or a log).
    static func prod() throws -> [RehearsalAccount] {
        guard ProcessInfo.processInfo.environment["BB_REHEARSAL_CONFIRM_PROD"] == RehearsalTarget.prodHost else {
            throw RehearsalError.prodNotConfirmed
        }
        return try ["A", "B"].map { label in
            guard let email = ProcessInfo.processInfo.environment["BB_REHEARSAL_EMAIL_\(label)"], !email.isEmpty else {
                throw RehearsalError.missingEmail("BB_REHEARSAL_EMAIL_\(label)")
            }
            return RehearsalAccount(label: label, email: email, password: try keychainPassword(account: label), id: nil)
        }
    }

    static func keychainPassword(account: String) throws -> String {
        #if canImport(Security)
            let query: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: RehearsalTarget.keychainService,
                kSecAttrAccount as String: account, kSecReturnData as String: true,
                kSecMatchLimit as String: kSecMatchLimitOne,
            ]
            var item: CFTypeRef?
            let status = SecItemCopyMatching(query as CFDictionary, &item)
            guard status == errSecSuccess, let data = item as? Data, let password = String(data: data, encoding: .utf8)
            else { throw RehearsalError.keychain(account: account, status: status) }
            return password
        #else
            throw RehearsalError.keychain(account: account, status: -1)
        #endif
    }
}

// MARK: - Results

/// One scenario's outcome. It carries no credentials and no user content: ids, counts, timings.
struct RehearsalRecord: Codable, Sendable {
    enum Verdict: String, Codable, Sendable { case pass = "PASS", fail = "FAIL", notAutomated = "NOT_AUTOMATED" }

    var id: String
    var title: String
    var target: String
    var verdict: Verdict
    var observed: [String: String]
    var correlationIDs: [String]
    var failures: [String]
    var note: String
    var seconds: Double
    var configuration: String
}

/// Collects what a scenario saw; `expect` is a `#expect` that also lands in the record.
final class RehearsalRecorder: @unchecked Sendable {
    // Safe: used from the scenario's own task only.
    let id: String
    let title: String
    private(set) var observed: [String: String] = [:]
    private(set) var correlationIDs: [String] = []
    private(set) var failures: [String] = []
    private let started = Date()
    private(set) var lastStage = "start"

    init(_ id: String, _ title: String) {
        self.id = id
        self.title = title
    }

    func observe(_ key: String, _ value: Any) { observed[key] = String(describing: value) }
    func correlation(_ id: String?) { if let id, !id.isEmpty, !correlationIDs.contains(id) { correlationIDs.append(id) } }

    func expect(_ condition: Bool, _ message: String, sourceLocation: SourceLocation = #_sourceLocation) {
        if !condition { failures.append(message) }
        #expect(condition, Comment(rawValue: message), sourceLocation: sourceLocation)
    }

    /// Marks where the scenario is, so a throw says where.
    func stage(_ name: String) { lastStage = name }

    func fail(_ message: String) { failures.append(message) }

    func record(note: String = "", configuration: String) -> RehearsalRecord {
        RehearsalRecord(
            id: id, title: title, target: RehearsalTarget.selected?.rawValue ?? "local",
            verdict: failures.isEmpty ? .pass : .fail, observed: observed, correlationIDs: correlationIDs,
            failures: failures, note: note, seconds: Date().timeIntervalSince(started), configuration: configuration)
    }
}

enum RehearsalReport {
    static let section = "S3 Swift driver"

    static var outDirectory: URL {
        URL(fileURLWithPath: ProcessInfo.processInfo.environment["BB_REHEARSAL_OUT"] ?? "/tmp", isDirectory: true)
    }

    /// Runs `body`, turning a throw into a FAIL, then writes the scenario's JSON file and refreshes the
    /// markdown section.
    static func run(
        _ id: String, _ title: String, note: String = "", _ body: @MainActor (RehearsalRecorder) async throws -> Void
    ) async {
        let recorder = RehearsalRecorder(id, title)
        do { try await body(recorder) } catch {
            recorder.fail("threw after stage '\(recorder.lastStage)': \(error)")
            Issue.record("rehearsal \(id) threw after stage '\(recorder.lastStage)': \(error)")
        }
        #if DEBUG
            let configuration = "debug"
        #else
            let configuration = "release"
        #endif
        write(recorder.record(note: note, configuration: configuration))
    }

    /// A scenario (or part of one) this driver cannot run, with the reason. Never a pass.
    static func notAutomated(_ id: String, _ title: String, reason: String) {
        write(RehearsalRecord(
            id: id, title: title, target: RehearsalTarget.selected?.rawValue ?? "local", verdict: .notAutomated,
            observed: [:], correlationIDs: [], failures: [], note: reason, seconds: 0, configuration: "-"))
    }

    private static let lock = NSLock()

    static func write(_ record: RehearsalRecord) {
        lock.lock()
        defer { lock.unlock() }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let name = "rehearsal-s3-\(record.target)-\(record.id)-\(record.configuration).json"
        try? FileManager.default.createDirectory(at: outDirectory, withIntermediateDirectories: true)
        if let data = try? encoder.encode(record) { try? data.write(to: outDirectory.appendingPathComponent(name)) }
    }
}
