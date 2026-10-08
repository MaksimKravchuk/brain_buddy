import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

/// The golden project archive traces (spec 021, contracts/kit-commands.md §7)
/// replayed against `BrainBuddyFakeServer`: lossless archive, a repeat archive,
/// unarchive, `GET /projects?state=`, the tolerant task PATCH and the desired
/// outcome. `project_archive_traces.json` is a byte-identical copy of
/// `backend/tests/fixtures/project_archive_traces.json` (checked by
/// `test_project_archive_traces.py` on every landing), which the same file
/// passes against the real API, so the fake server cannot drift from the backend
/// on these paths. An expected `null` also matches an absent key, because the
/// fake encodes its responses with Swift's synthesized `Codable`, which omits nil.
@Suite("Project archive trace replay (spec 021)")
struct ProjectArchiveTraceReplayTests {
    struct Trace: Sendable, CustomTestStringConvertible {
        var id: String
        var title: String
        var requirements: [String]
        var steps: [JSONValue]

        var testDescription: String { "\(id) \(title)" }
    }

    static let emails = ["first@example.com", "second@example.com"]
    static let password = "trace-secret"
    static let origin = "https://fake.brainbuddy.test"

    /// The whole file; a missing copy stops the suite instead of letting it pass with nothing replayed.
    static let file: JSONValue = {
        guard
            let url = Bundle.module.url(
                forResource: "project_archive_traces", withExtension: "json", subdirectory: "Resources"
            ),
            let data = try? Data(contentsOf: url),
            let value = try? JSONDecoder().decode(JSONValue.self, from: data)
        else { fatalError("Missing or unreadable test resource Resources/project_archive_traces.json") }
        return value
    }()

    static let traces: [Trace] = {
        guard case .array(let items)? = file["traces"] else { fatalError("project_archive_traces.json has no traces") }
        return items.map { item in
            guard let id = item["id"]?.stringValue, let title = item["title"]?.stringValue,
                case .array(let requirements)? = item["requirements"], case .array(let steps)? = item["steps"]
            else { fatalError("Malformed trace \(item)") }
            return Trace(id: id, title: title, requirements: requirements.compactMap(\.stringValue), steps: steps)
        }
    }()

    @Test("021-FR-024 the trace file declares its schema and every trace names feature-qualified ids")
    func traceFileDeclaresItsSchema() {
        #expect(Self.file["schema"]?.stringValue == "brainbuddy-project-archive-traces/v1")
        let ids = Self.traces.map(\.id)
        #expect(!ids.isEmpty && Set(ids).count == ids.count)
        for trace in Self.traces {
            #expect(!trace.requirements.isEmpty, "\(trace.id) names no requirement")
            #expect(trace.requirements.allSatisfy { $0.hasPrefix("021-") }, "\(trace.id) names a bare id")
        }
    }

    @Test(
        "021-FR-024 021-FR-026 021-FR-027 021-FR-028 each golden trace replays against the fake server with the recorded statuses and responses",
        arguments: traces
    )
    func traceReplaysAgainstTheFakeServer(_ trace: Trace) throws {
        let replay = try Replay(trace)
        for (index, step) in trace.steps.enumerated() {
            replay.run(step, index: index)
        }
    }
}

// MARK: - Replay

/// One trace against a fresh server with two signed-in accounts, run step by step as
/// `backend/tests/test_project_archive_traces.py` runs it against the backend.
private final class Replay {
    let trace: ProjectArchiveTraceReplayTests.Trace
    let server: FakeBrainBuddyServer
    private let cookies: [String]
    private var captured: [String: String] = [:]

    init(_ trace: ProjectArchiveTraceReplayTests.Trace) throws {
        self.trace = trace
        let server = FakeBrainBuddyServer(now: ManualClock().provider)
        self.server = server
        var cookies: [String] = []
        for email in ProjectArchiveTraceReplayTests.emails {
            server.addAccount(email: email, password: ProjectArchiveTraceReplayTests.password)
            let login = try JSONEncoder().encode(
                JSONValue.object(["email": .string(email), "password": .string(ProjectArchiveTraceReplayTests.password)])
            )
            let response = server.respond(
                to: HTTPRequest(
                    method: .post, url: URL(string: ProjectArchiveTraceReplayTests.origin + "/api/auth/login")!,
                    headers: ["Content-Type": "application/json"], body: login
                )
            )
            let setCookie = try #require(response.header("set-cookie"), "the fake server's login set no cookie")
            cookies.append(String(setCookie.prefix { $0 != ";" }))
        }
        self.cookies = cookies
    }

    func run(_ step: JSONValue, index: Int) {
        let name = "\(trace.id) step \(index + 1): \(step["name"]?.stringValue ?? "?")"
        if let seed = step["seed"].map(substitute) {
            guard let kind = seed["kind"]?.stringValue, let project = seed["project"]?.stringValue else {
                Issue.record("\(name): a seed without a kind and a project")
                return
            }
            server.seedArchive(
                project: project, email: ProjectArchiveTraceReplayTests.emails[0],
                keepingMembers: kind == "archive_keeping_members"
            )
            return
        }
        guard let request = step["request"].map(substitute), let expect = step["expect"].map(substitute) else {
            Issue.record("\(name): neither a request nor a seed")
            return
        }
        let response = server.respond(to: httpRequest(request))
        let body: JSONValue? =
            response.body.isEmpty ? nil : try? JSONDecoder().decode(JSONValue.self, from: response.body)
        let expectedStatus = expect["status"].flatMap(Self.number).map(Int.init)
        let text = String(decoding: response.body, as: UTF8.self)
        #expect(response.statusCode == expectedStatus, "\(name): status \(response.statusCode), body \(text)")
        if let expectedBody = expect["body"] {
            for mismatch in Self.mismatches(expected: expectedBody, actual: body, at: "body") {
                Issue.record("\(name): \(mismatch); body \(text)")
            }
        }
        if case .object(let captures)? = step["capture"] {
            for (variable, path) in captures {
                guard let path = path.stringValue, let value = Self.value(at: path, in: body),
                    let rendered = Self.render(value)
                else {
                    Issue.record("\(name): nothing to capture as \(variable)")
                    continue
                }
                captured[variable] = rendered
            }
        }
    }

    private func httpRequest(_ request: JSONValue) -> HTTPRequest {
        let method = HTTPMethod(rawValue: request["method"]?.stringValue ?? "GET") ?? .get
        let path = request["path"]?.stringValue ?? "/"
        let account = request["as"]?.stringValue == "second" ? 1 : 0
        var headers = ["Cookie": cookies[account], "X-Correlation-ID": "trace-\(trace.id)"]
        if let key = request["key"]?.stringValue { headers["Idempotency-Key"] = key }
        var body: Data?
        if let payload = request["body"] {
            headers["Content-Type"] = "application/json"
            body = try? JSONEncoder().encode(payload)
        }
        return HTTPRequest(
            method: method, url: URL(string: ProjectArchiveTraceReplayTests.origin + path)!, headers: headers, body: body
        )
    }

    /// `{name}` in any string replaced by the captured value.
    private func substitute(_ value: JSONValue) -> JSONValue {
        switch value {
        case .string(let text):
            var result = text
            for (name, captured) in captured { result = result.replacingOccurrences(of: "{\(name)}", with: captured) }
            return .string(result)
        case .array(let items):
            return .array(items.map(substitute))
        case .object(let members):
            return .object(members.mapValues(substitute))
        case .null, .bool, .number:
            return value
        }
    }

    // MARK: Matching (the file's `expect` convention)

    static func mismatches(expected: JSONValue, actual: JSONValue?, at path: String) -> [String] {
        if expected == .string("$present") {
            return actual == nil || actual == .null ? ["\(path) is missing or null"] : []
        }
        switch expected {
        case .object(let members):
            guard case .object(let actualMembers)? = actual else { return ["\(path) is not an object"] }
            return members.keys.sorted().flatMap { key -> [String] in
                guard let item = members[key] else { return [] }
                guard let actualItem = actualMembers[key] else { return item == .null ? [] : ["\(path).\(key) missing"] }
                return mismatches(expected: item, actual: actualItem, at: "\(path).\(key)")
            }
        case .array(let items):
            guard case .array(let actualItems)? = actual, actualItems.count == items.count else {
                return ["\(path) is not a list of \(items.count)"]
            }
            return zip(items, actualItems).enumerated().flatMap { index, pair in
                mismatches(expected: pair.0, actual: pair.1, at: "\(path)[\(index)]")
            }
        case .null, .bool, .number, .string:
            guard let actual else { return expected == .null ? [] : ["\(path) missing"] }
            return expected == actual ? [] : ["\(path) is \(actual), expected \(expected)"]
        }
    }

    static func value(at path: String, in body: JSONValue?) -> JSONValue? {
        path.split(separator: ".").reduce(body) { value, part in value?[String(part)] }
    }

    static func render(_ value: JSONValue) -> String? {
        switch value {
        case .string(let text): text
        case .number(let number): number.rounded() == number ? String(Int(number)) : String(number)
        case .bool(let flag): String(flag)
        case .null, .array, .object: nil
        }
    }

    static func number(_ value: JSONValue) -> Double? {
        if case .number(let number) = value { return number }
        return nil
    }
}
