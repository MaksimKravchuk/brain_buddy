import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyAgents

/// The server shapes the session reads, decoded the way the client decodes them.
enum SessionFixture {
    static let server = URL(string: "https://bb.example")!

    static func account(_ id: String = "user_max") -> LinkedAccount {
        LinkedAccount(id: id, email: "max@example.com", serverURL: server, linkedAt: Date(timeIntervalSince1970: 0))
    }

    static func methods(id: String, password: Bool) -> AccountAuthMethodsDTO {
        let json = """
            {"account_id":"\(id)","email":"max@example.com","email_verified":true,\
            "email_delivery":"available","has_password":\(password),"methods":[]}
            """
        return try! BrainBuddyAPI.makeDecoder().decode(AccountAuthMethodsDTO.self, from: Data(json.utf8))
    }

    static func summary(task: String, label: String) -> AgentRunSummaryDTO {
        let json = #"{"id":"run_\#(task)","task_id":"\#(task)","agent_name":"Hermes","primary_state_label":"\#(label)","needs_user":false,"stopped_reporting":false,"last_contact_at":"1970-01-12T13:46:40Z","guarantee_tier":"best_effort","cancel_outcome":"none","agent_task_missing":false}"#
        return try! BrainBuddyAPI.makeDecoder().decode(AgentRunSummaryDTO.self, from: Data(json.utf8))
    }

    static func run(task: String, label: String, question: String? = nil) -> AgentRunDTO {
        let asks = question.map { "\"\($0)\"" } ?? "null"
        let json = #"""
            {"id":"run_\#(task)","task_id":"\#(task)","connection_id":"conn_hermes","agent_name":"Hermes",\#
            "dispatch_state":"sent","dispatch_error_code":null,"reported_state":"running","run_version":2,\#
            "stopped_reporting":false,"connection_disconnected":false,"reply_pending":false,"cancel_requested":false,\#
            "needs_user":false,"primary_state_label":"\#(label)","progress_text":null,"question_text":\#(asks),\#
            "result_text":null,"result_link":null,"result_link_interactive":false,"failure_reason":null,\#
            "content_expired":false,"content_expires_at":"2099-01-01T00:00:00Z",\#
            "last_contact_at":"1970-01-12T13:46:40Z","reporting_window_seconds":86400,\#
            "capabilities":{"reply":true,"cancel":true},"guarantee_tier":"best_effort","exchange_state":"open",\#
            "exchange_kind":"start","push_registration":"unregistered","agent_task_missing":false,"cancel_outcome":"none",\#
            "blocked_reason":null,"artifacts_summary":[],"result_availability":null,\#
            "last_observed_at":"1970-01-12T13:46:40Z","observation_interval_seconds":60,"identifiers_expired":false,\#
            "manifest":null,"events":[],"commands":[],"created_at":"1970-01-12T13:40:00Z","revision":4}
            """#
        return try! BrainBuddyAPI.makeDecoder().decode(AgentRunDTO.self, from: Data(json.utf8))
    }
}

/// `/auth/me` and `/account/auth-methods`, scripted; counts the flag reads.
final class ScriptedAvailability: AgentAvailabilityRemote {
    private let state: Mutex<(flag: Bool, password: Bool, owner: String, meCalls: Int)>

    init(flag: Bool = true, password: Bool = true, owner: String = "user_max") {
        state = Mutex((flag, password, owner, 0))
    }

    var meCalls: Int { state.withLock { $0.meCalls } }

    func me() async throws(APIError) -> MeDTO {
        let s = state.withLock { s in
            s.meCalls += 1
            return s
        }
        return MeDTO(id: s.owner, email: "max@example.com", featureFlags: ["external_agent_relay": s.flag])
    }

    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO {
        let s = state.withLock { $0 }
        return SessionFixture.methods(id: s.owner, password: s.password)
    }
}

/// Summaries and runs from a table.
final class ScriptedRuns: AgentRunsRemote {
    private let table = Mutex<[String: (AgentRunSummaryDTO, AgentRunDTO)]>([:])

    func set(task: String, label: String, question: String? = nil) {
        table.withLock {
            $0[task] = (SessionFixture.summary(task: task, label: label), SessionFixture.run(task: task, label: label, question: question))
        }
    }

    func agentRunSummaries(taskIDs: [String]) async throws(APIError) -> [String: AgentRunSummaryDTO] {
        table.withLock { t in t.filter { taskIDs.contains($0.key) }.mapValues(\.0) }
    }

    func agentRun(id: String) async throws(APIError) -> AgentRunDTO {
        let found = table.withLock { t in t.values.first { $0.1.id == id }?.1 }
        guard let found else { throw APIError(kind: .notFound(resource: nil, id: nil), message: "none") }
        return found
    }
}

/// A log that keeps its lines, for the privacy check.
final class KeptAgentLog: AgentLogSink {
    private let lines = Mutex<[String]>([])
    func log(_ message: String) { lines.withLock { $0.append(message) } }
    var all: [String] { lines.withLock { $0 } }
}

@MainActor
final class SessionHarness {
    var account: LinkedAccount? = SessionFixture.account()
    var steps: [AgentStepRef]? = [
        AgentStepRef(taskID: TaskID("local_van"), serverID: "task_van", title: "Compare van hire prices"),
        AgentStepRef(taskID: TaskID("local_toast"), serverID: "task_toast", title: "Draft the toast for Ana"),
    ]
    var date = Date(timeIntervalSince1970: 1_000_000)
    let availability: ScriptedAvailability
    let runs = ScriptedRuns()
    let log = KeptAgentLog()
    lazy var session = AgentsSession(
        account: { [unowned self] in self.account }, steps: { [unowned self] in self.steps },
        availabilityRemote: { [availability] _ in availability }, runsRemote: runs,
        now: { [unowned self] in self.date }, log: log)

    init(flag: Bool = true, password: Bool = true) {
        availability = ScriptedAvailability(flag: flag, password: password)
    }
}

@MainActor
@Suite("034 iPhone agents session")
struct AgentsSessionTests {
    @Test("034_FR_002 a signed-out phone shows no agent surface and reads nothing")
    func signedOutShowsNothing() async {
        let h = SessionHarness()
        h.account = nil
        h.runs.set(task: "task_van", label: "Needs you")
        await h.session.refresh()
        #expect(!h.session.showsSettings)
        #expect(!h.session.canHandOff)
        #expect(h.session.waitingRows.isEmpty)
        #expect(h.session.waitingHeader(people: 2) == nil)
        #expect(h.availability.meCalls == 0)
    }

    @Test("034_FR_003 the flag gates hand-off and adding; the password state gates adding")
    func flagAndPasswordGateControls() async {
        let on = SessionHarness(flag: true, password: true)
        await on.session.refresh()
        #expect(on.session.canHandOff && on.session.canAddAgent && on.session.showsSettings)

        let off = SessionHarness(flag: false)
        await off.session.refresh()
        #expect(!off.session.canHandOff && !off.session.canAddAgent)
        #expect(off.session.showsSettings)

        let passwordless = SessionHarness(flag: true, password: false)
        await passwordless.session.refresh()
        #expect(passwordless.session.canHandOff && !passwordless.session.canAddAgent)
    }

    @Test("034_FR_003 coming to the foreground reads the flag at most once every five minutes")
    func foregroundThrottlesTheFlagRead() async {
        let h = SessionHarness()
        await h.session.refresh()
        await h.session.refresh()
        #expect(h.availability.meCalls == 1)
        h.date = h.date.addingTimeInterval(AgentAvailability.activationThrottle)
        await h.session.refresh()
        #expect(h.availability.meCalls == 2)
    }

    @Test("034_FR_003 polling pauses in the background and offline")
    func pollingFollowsForegroundAndNetwork() async {
        let h = SessionHarness()
        h.session.setForeground(false)
        h.session.setOnline(false)
        #expect(!h.session.runs.isWindowVisible && !h.session.runs.isOnline)
        h.session.setForeground(true)
        h.session.setOnline(true)
        #expect(h.session.runs.isWindowVisible && h.session.runs.isOnline)
    }

    @Test("034_FR_004 Waiting for lists the runs of open steps, Needs you first, with the people and agents count")
    func waitingRowsAndHeader() async throws {
        let h = SessionHarness()
        h.runs.set(task: "task_toast", label: "Running")
        h.runs.set(task: "task_van", label: "Needs you", question: "Card or cash?")
        await h.session.refresh()
        let rows = h.session.waitingRows
        #expect(rows.map(\.stepTitle) == ["Compare van hire prices", "Draft the toast for Ana"])
        #expect(rows.first?.group == .needsYou)
        #expect(h.session.waitingHeader(people: 2) == "2 people, 2 agents")
        #expect(h.session.waitingHeader(people: 1) == "1 person, 2 agents")
        let van = try #require(h.session.item(forStep: "task_van"))
        #expect(van.subtitle(now: h.date) == "Hermes · Card or cash?")
        #expect(h.session.stepID(forServerID: "task_van") == TaskID("local_van"))
        #expect(h.session.item(forStep: nil) == nil)
    }

    @Test("034_FR_004 a step that is no longer open drops out of Waiting for")
    func closedStepDropsOut() async {
        let h = SessionHarness()
        h.runs.set(task: "task_van", label: "Agent reported complete")
        h.runs.set(task: "task_toast", label: "Running")
        await h.session.refresh()
        #expect(h.session.waitingRows.count == 2)
        h.steps = [AgentStepRef(taskID: TaskID("local_toast"), serverID: "task_toast", title: "Draft the toast for Ana")]
        await h.session.refreshSteps()
        #expect(h.session.waitingRows.map(\.taskServerID) == ["task_toast"])
        #expect(h.session.stepID(forServerID: "task_van") == nil)
    }

    @Test("034_FR_002 signing out or switching account drops every listed run")
    func accountChangeDropsRuns() async {
        let h = SessionHarness()
        h.runs.set(task: "task_van", label: "Needs you")
        await h.session.refresh()
        #expect(!h.session.waitingRows.isEmpty)
        h.account = SessionFixture.account("user_other")
        h.session.syncAccount()
        #expect(h.session.waitingRows.isEmpty)
        #expect(h.session.stepID(forServerID: "task_van") == nil)
        h.account = nil
        h.session.syncAccount()
        #expect(!h.session.showsSettings && h.session.waitingRows.isEmpty)
    }

    @Test("034_FR_001 a failed steps read keeps the last list instead of emptying it")
    func failedStepsReadKeepsList() async {
        let h = SessionHarness()
        h.runs.set(task: "task_van", label: "Running")
        await h.session.refresh()
        h.steps = nil
        await h.session.refreshSteps()
        #expect(h.session.waitingRows.map(\.taskServerID) == ["task_van"])
    }

    @Test("034_FR_001 the session's log lines carry no title, agent name or question")
    func logsCarryNoContent() async {
        let h = SessionHarness()
        h.runs.set(task: "task_van", label: "Needs you", question: "Card or cash?")
        await h.session.refresh()
        let joined = h.log.all.joined(separator: "\n")
        #expect(!h.log.all.isEmpty)
        for secret in ["Compare van", "Hermes", "Card or cash", "max@example.com"] { #expect(!joined.contains(secret)) }
    }
}
