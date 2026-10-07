import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

/// The golden decision and park traces of slice PR-15 replayed against
/// `BrainBuddyFakeServer` (spec 020, tasks.md T173): decide, decide stale,
/// auto-park `applied: false`, yield after a queued notes edit, settings 409,
/// flag off with queued writes, and a decision retried after the 24 h
/// idempotency retention answered as already applied. The same file runs
/// against the real API in `backend/tests/test_review_traces.py`, so the fake
/// server cannot drift from the backend on these paths (020-FR-011,
/// 020-FR-013, 020-SC-007).
///
/// `review_traces_tasks.json` is a byte-identical copy of
/// `backend/tests/fixtures/review_traces_tasks.json` (drift guard in
/// `backend/tests/test_review_formulation_vectors.py`). Its `conventions` are
/// followed as the backend test follows them, with two stated differences:
/// an expected `null` also matches an absent key, because the fake server
/// encodes its responses with Swift's synthesized `Codable`, which omits nil
/// values, and the Swift client decodes an absent key and `null` the same
/// way; and a formulation's display-only derived instants are derived with
/// Core's rule instead of read from the fake (`withDerivedInstants`).
@Suite("Review task trace replay (spec 020)")
struct ReviewTaskTraceReplayTests {
    struct Trace: Sendable, CustomTestStringConvertible {
        var id: String
        var title: String
        var requirements: [String]
        var start: Date
        var flagOn: Bool
        var steps: [JSONValue]

        var testDescription: String { "\(id) \(title)" }
    }

    static let email = "trace@example.com"
    static let password = "trace-secret"
    static let origin = "https://fake.brainbuddy.test"

    /// The whole file; a missing or unreadable copy stops the suite instead of
    /// letting it pass with nothing replayed.
    static let file: JSONValue = {
        guard
            let url = Bundle.module.url(
                forResource: "review_traces_tasks", withExtension: "json", subdirectory: "Resources"
            ),
            let data = try? Data(contentsOf: url),
            let value = try? JSONDecoder().decode(JSONValue.self, from: data)
        else { fatalError("Missing or unreadable test resource Resources/review_traces_tasks.json") }
        return value
    }()

    static let traces: [Trace] = {
        guard case .array(let items)? = file["traces"] else { fatalError("review_traces_tasks.json has no traces") }
        return items.map { item in
            guard let id = item["id"]?.stringValue, let title = item["title"]?.stringValue,
                case .array(let requirements)? = item["requirements"],
                let start = item["start"]?.stringValue.flatMap(WireDate.parse),
                let flag = item["flag"]?.stringValue, case .array(let steps)? = item["steps"]
            else { fatalError("Malformed trace \(item)") }
            return Trace(
                id: id, title: title, requirements: requirements.compactMap(\.stringValue), start: start,
                flagOn: flag == "on", steps: steps
            )
        }
    }()

    // MARK: - Tests

    @Test("020-SC-007: the trace file declares its schema and seven traces naming feature-qualified ids")
    func traceFileDeclaresItsSchema() {
        #expect(Self.file["schema"]?.stringValue == "brainbuddy-review-traces/v1")
        let ids = Self.traces.map(\.id)
        #expect(ids.count == 7)
        #expect(Set(ids).count == ids.count)
        for trace in Self.traces {
            #expect(!trace.requirements.isEmpty, "\(trace.id) names no requirement")
            #expect(trace.requirements.allSatisfy { $0.hasPrefix("020-") }, "\(trace.id) names a bare id")
        }
    }

    @Test(
        "020-SC-007 020-FR-013 020-FR-011: each golden trace replays against the fake server with the recorded statuses and responses",
        arguments: traces
    )
    func traceReplaysAgainstTheFakeServer(_ trace: Trace) throws {
        let replay = try Replay(trace)
        for (index, step) in trace.steps.enumerated() {
            replay.run(step, index: index)
        }
    }

    @Test("020-FR-011 020-SC-007: the retried decision of TR-007 is applied once on the fake server")
    func retriedDecisionIsAppliedOnce() throws {
        let trace = try #require(Self.traces.first { $0.id == "TR-007" })
        let replay = try Replay(trace)
        for (index, step) in trace.steps.enumerated() {
            replay.run(step, index: index)
        }
        let review = replay.server.reviewSnapshot(email: Self.email)
        #expect(review.decisionIDs == ["decision_0b0e1f30-0000-4000-8000-000000000071"])
        let tasks = replay.server.snapshot(email: Self.email).tasks.values
        #expect(tasks.count == 1)
        #expect(tasks.first?.revision == 2)
    }
}

// MARK: - Replay

/// One trace against a fresh server with its own manual clock and one
/// signed-in session, run step by step as `backend/tests/test_review_traces.py`
/// runs it against the backend.
private final class Replay {
    let trace: ReviewTaskTraceReplayTests.Trace
    let clock: ManualClock
    let server: FakeBrainBuddyServer
    private let cookie: String
    private var captured: [String: String] = [:]

    init(_ trace: ReviewTaskTraceReplayTests.Trace) throws {
        self.trace = trace
        clock = ManualClock(trace.start)
        server = FakeBrainBuddyServer(now: clock.provider)
        server.addAccount(email: ReviewTaskTraceReplayTests.email, password: ReviewTaskTraceReplayTests.password)
        server.setWeeklyReview(email: ReviewTaskTraceReplayTests.email, enabled: trace.flagOn)
        let login = try JSONEncoder().encode(
            JSONValue.object([
                "email": .string(ReviewTaskTraceReplayTests.email),
                "password": .string(ReviewTaskTraceReplayTests.password),
            ])
        )
        let response = server.respond(
            to: HTTPRequest(
                method: .post, url: URL(string: ReviewTaskTraceReplayTests.origin + "/api/auth/login")!,
                headers: ["Content-Type": "application/json"], body: login
            )
        )
        let setCookie = try #require(response.header("set-cookie"), "the fake server's login set no cookie")
        cookie = String(setCookie.prefix { $0 != ";" })
    }

    func run(_ step: JSONValue, index: Int) {
        let name = "\(trace.id) step \(index + 1): \(step["name"]?.stringValue ?? "?")"
        if let advance = step["advance"] {
            let days = advance["days"].flatMap(Self.number) ?? 0
            let hours = advance["hours"].flatMap(Self.number) ?? 0
            let minutes = advance["minutes"].flatMap(Self.number) ?? 0
            clock.advance(by: days * 86_400 + hours * 3_600 + minutes * 60)
            return
        }
        if step["sweep"] == .bool(true) {
            server.runAutoParkSweep()
            return
        }
        if let flag = step["flag"]?.stringValue {
            server.setWeeklyReview(email: ReviewTaskTraceReplayTests.email, enabled: flag == "on")
            return
        }
        guard let request = step["request"].map(substitute), let expect = step["expect"].map(substitute) else {
            Issue.record("\(name): neither a request nor a known control step")
            return
        }
        let response = server.respond(to: httpRequest(request))
        let body: JSONValue? =
            response.body.isEmpty
            ? nil : (try? JSONDecoder().decode(JSONValue.self, from: response.body)).map(withDerivedInstants)
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

    // MARK: Requests

    private func httpRequest(_ request: JSONValue) -> HTTPRequest {
        let method = HTTPMethod(rawValue: request["method"]?.stringValue ?? "GET") ?? .get
        let path = request["path"]?.stringValue ?? "/"
        var headers = ["Cookie": cookie, "X-Correlation-ID": "trace-\(trace.id)"]
        if let key = request["key"]?.stringValue { headers["Idempotency-Key"] = key }
        var body: Data?
        if let payload = request["body"] {
            headers["Content-Type"] = "application/json"
            body = try? JSONEncoder().encode(payload)
        }
        return HTTPRequest(
            method: method, url: URL(string: ReviewTaskTraceReplayTests.origin + path)!, headers: headers, body: body
        )
    }

    // MARK: Derived instants

    /// The fake server leaves the display-only derived instants (`ageing_at`,
    /// `ask_at`, `park_due_at`, `paused_until`) out of a task's formulation
    /// (`TaskRow.dto` in `FakeServerRecords.swift`), and the Swift client
    /// never reads them: the device derives them itself. So the replay derives
    /// them here with Core's `FormulationRule`, from the clock the fake
    /// answered with and the owner's settings on the fake, and the recorded
    /// backend values then check the rule the device uses. Before activation
    /// the rule derives nothing, which matches the backend's nulls.
    private func withDerivedInstants(_ value: JSONValue) -> JSONValue {
        switch value {
        case .object(var members):
            for (key, member) in members { members[key] = withDerivedInstants(member) }
            guard members["state"]?.stringValue == "next", case .object(var formulation)? = members["formulation"],
                formulation["ask_at"] == nil, let id = formulation["id"]?.stringValue,
                let started = formulation["started_at"]?.stringValue.flatMap(WireDate.parse)
            else { return .object(members) }
            let clock = FormulationClock(
                id: FormulationID(id), startedAt: started,
                extendedAt: formulation["extended_at"]?.stringValue.flatMap(WireDate.parse),
                extensionReason: formulation["extension_reason"]?.stringValue,
                parkFloorAt: formulation["park_floor_at"]?.stringValue.flatMap(WireDate.parse)
            )
            let task = ClockedTask(
                state: .next, title: members["title"]?.stringValue,
                revision: members["revision"].flatMap(Self.number).map(Int.init) ?? 1, formulation: clock,
                consecutiveStalledFormulations: formulation["consecutive_stalled"].flatMap(Self.number).map(Int.init) ?? 0,
                dueDate: members["due_date"]?.stringValue.flatMap { CalendarDay(isoString: $0) }
            )
            let settings = server.reviewSnapshot(email: ReviewTaskTraceReplayTests.email).settings.clockSettings()
            guard let instants = FormulationRule.derivedInstants(of: task, settings: settings) else {
                return .object(members)
            }
            formulation["ageing_at"] = .string(WireDate.format(instants.ageingAt))
            formulation["ask_at"] = .string(WireDate.format(instants.askAt))
            formulation["park_due_at"] = .string(WireDate.format(instants.parkDueAt))
            formulation["paused_until"] = instants.pausedUntil.map { .string(WireDate.format($0)) } ?? .null
            members["formulation"] = .object(formulation)
            return .object(members)
        case .array(let items):
            return .array(items.map(withDerivedInstants))
        case .null, .bool, .number, .string:
            return value
        }
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
                guard let actualItem = actualMembers[key] else {
                    // An omitted optional is the fake's spelling of null.
                    return item == .null ? [] : ["\(path).\(key) missing"]
                }
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
            return equal(expected, actual) ? [] : ["\(path) is \(actual), expected \(expected)"]
        }
    }

    /// Instants compare as instants, whatever their spelling.
    private static func equal(_ expected: JSONValue, _ actual: JSONValue) -> Bool {
        if case .string(let lhs) = expected, case .string(let rhs) = actual,
            lhs.wholeMatch(of: /\d{4}-\d{2}-\d{2}T.*/) != nil,
            let left = WireDate.parse(lhs), let right = WireDate.parse(rhs)
        {
            return left == right
        }
        return expected == actual
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
