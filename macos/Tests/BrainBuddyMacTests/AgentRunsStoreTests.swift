import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// Fixtures are `AgentRunResponse` and `AgentRunSummaryResponse` shaped like the kit's own decoding tests.
private enum RunsFixture {
    static func isoDate(_ interval: TimeInterval) -> String {
        Date(timeIntervalSince1970: interval).formatted(.iso8601)
    }

    static func summary(task: String, label: String, agent: String = "Hermes") -> AgentRunSummaryDTO {
        let json = #"{"id":"run_\#(task)","task_id":"\#(task)","agent_name":"\#(agent)","primary_state_label":"\#(label)","needs_user":false,"stopped_reporting":false,"last_contact_at":"1970-01-12T13:46:40Z","guarantee_tier":"best_effort","cancel_outcome":"none","agent_task_missing":false}"#
        return try! BrainBuddyAPI.makeDecoder().decode(AgentRunSummaryDTO.self, from: Data(json.utf8))
    }

    static func run(
        task: String, label: String, connection: String = "conn_hermes", interval: Int = 60, question: String? = nil,
        expires: TimeInterval = 5_000_000
    ) -> AgentRunDTO {
        let asks = question.map { "\"\($0)\"" } ?? "null"
        let json = #"""
            {"id":"run_\#(task)","task_id":"\#(task)","connection_id":"\#(connection)","agent_name":"Hermes",\#
            "dispatch_state":"sent","dispatch_error_code":null,"reported_state":"running","run_version":2,\#
            "stopped_reporting":false,"connection_disconnected":false,"reply_pending":false,"cancel_requested":false,\#
            "needs_user":false,"primary_state_label":"\#(label)","progress_text":null,"question_text":\#(asks),\#
            "result_text":null,"result_link":null,"result_link_interactive":false,"failure_reason":null,\#
            "content_expired":false,"content_expires_at":"\#(isoDate(expires))",\#
            "last_contact_at":"1970-01-12T13:46:40Z","reporting_window_seconds":86400,\#
            "capabilities":{"reply":true,"cancel":true},"guarantee_tier":"best_effort","exchange_state":"open",\#
            "exchange_kind":"start","push_registration":"unregistered","agent_task_missing":false,"cancel_outcome":"none",\#
            "blocked_reason":null,"artifacts_summary":[],"result_availability":null,\#
            "last_observed_at":"1970-01-12T13:46:40Z","observation_interval_seconds":\#(interval),"identifiers_expired":false,\#
            "manifest":null,"events":[],"commands":[],"created_at":"1970-01-12T13:40:00Z","revision":4}
            """#
        return try! BrainBuddyAPI.makeDecoder().decode(AgentRunDTO.self, from: Data(json.utf8))
    }
}

/// Answers the two reads from a table and counts them. Like the kit's client, it splits a summaries
/// call into requests of at most 200 ids, so `summaryRequests` is what the server would have seen.
final class FakeRunsRemote: AgentRunsRemote {
    private struct State {
        var summaries: [String: AgentRunSummaryDTO] = [:]
        var runs: [String: AgentRunDTO] = [:]
        var summaryCalls: [[String]] = []
        var runCalls: [String] = []
        var summaryFailure: APIError?
        var runFailure: APIError?
    }

    private let state = Mutex(State())
    private let gate: AccountReadGate?

    init(gate: AccountReadGate? = nil) { self.gate = gate }

    func set(task: String, label: String, interval: Int = 60, question: String? = nil, expires: TimeInterval = 5_000_000) {
        state.withLock {
            $0.summaries[task] = RunsFixture.summary(task: task, label: label)
            $0.runs["run_\(task)"] = RunsFixture.run(task: task, label: label, interval: interval, question: question, expires: expires)
        }
    }

    func failSummaries(_ error: APIError?) { state.withLock { $0.summaryFailure = error } }
    func failRuns(_ error: APIError?) { state.withLock { $0.runFailure = error } }
    var summaryCalls: [[String]] { state.withLock { $0.summaryCalls } }
    var summaryRequests: Int { summaryCalls.reduce(0) { $0 + ($1.count + 199) / 200 } }
    var runCalls: [String] { state.withLock { $0.runCalls } }
    func resetCalls() { state.withLock { ($0.summaryCalls, $0.runCalls) = ([], []) } }

    func agentRunSummaries(taskIDs: [String]) async throws(APIError) -> [String: AgentRunSummaryDTO] {
        let result: Result<[String: AgentRunSummaryDTO], APIError> = state.withLock { state in
            state.summaryCalls.append(taskIDs)
            if let failure = state.summaryFailure { return .failure(failure) }
            return .success(state.summaries.filter { taskIDs.contains($0.key) })
        }
        await gate?.pass()
        return try result.get()
    }

    func agentRun(id: String) async throws(APIError) -> AgentRunDTO {
        let result: Result<AgentRunDTO, APIError> = state.withLock { state in
            state.runCalls.append(id)
            if let failure = state.runFailure { return .failure(failure) }
            guard let run = state.runs[id] else { return .failure(APIError(kind: .notFound(resource: nil, id: nil), message: "none")) }
            return .success(run)
        }
        return try result.get()
    }
}

@MainActor
final class StepsBox { var steps: [AgentOpenStep] = [] }

@MainActor
@Suite("030 Agent runs store")
struct AgentRunsStoreTests {
    @MainActor
    struct Rig {
        let remote: FakeRunsRemote
        let box = StepsBox()
        let clock = AgentTestClock()
        let log = CapturingMacLog()
        let availability: AgentAvailability
        let cache = AgentMemoryCache()
        let store: AgentRunsStore

        init(gate: AccountReadGate? = nil) {
            remote = FakeRunsRemote(gate: gate)
            let clock = clock
            availability = AgentAvailability(
                account: AccountFixtures.account(), remote: { _ in FakeAvailabilityRemote() }, now: { clock.date })
            let box = box
            store = AgentRunsStore(
                remote: remote, steps: { box.steps }, availability: availability, cache: cache, now: { clock.date }, log: log)
        }

        /// `count` open steps with runs, one label for all.
        func seed(_ labels: [String], interval: Int = 60) {
            for (index, label) in labels.enumerated() {
                remote.set(task: "task_\(index)", label: label, interval: interval)
                box.steps.append(AgentOpenStep(title: "Step \(index)", serverID: "task_\(index)"))
            }
        }
    }

    @Test("030_FR_040 Return on a run row asks the inspector's run section for focus once")
    func inspectorFocusRequestIsConsumedOnce() {
        let rig = Rig()
        #expect(!rig.store.consumeInspectorFocus())
        rig.store.requestInspectorFocus()
        #expect(rig.store.inspectorFocusPending)
        #expect(rig.store.consumeInspectorFocus())
        #expect(!rig.store.consumeInspectorFocus())
    }

    @Test("030_FR_005 030_FR_006 030_FR_009 the latest run of each open step is grouped, counted and listed for Waiting for")
    func assemblesGroups() async {
        let rig = Rig()
        rig.seed(["Failed", "Needs you", "Running", "Stopped reporting", "Queued", "Delivery unconfirmed"])
        await rig.store.refresh()
        let sections = rig.store.sections
        #expect(sections.map(\.group) == [.needsYou, .running, .queued, .toReview, .lostContact])
        #expect(sections[0].items.map(\.stepTitle) == ["Step 1", "Step 5"])
        #expect(rig.store.items.count == 6)
        #expect(rig.store.waitingForRows.map(\.runID) == rig.store.items.map(\.runID))
        #expect(rig.store.perAgentCounts == ["conn_hermes": 6])
        #expect(rig.store.phase == .loaded)
        #expect(rig.store.lastUpdated == rig.clock.date)
    }

    @Test("030_FR_005 steps without a run, and steps with no server id, list nothing")
    func sparseSummaries() async {
        let rig = Rig()
        rig.seed(["Running"])
        rig.box.steps.append(AgentOpenStep(title: "No run yet", serverID: "task_none"))
        await rig.store.refresh()
        #expect(rig.store.items.map(\.stepTitle) == ["Step 0"])
    }

    @Test("030_FR_005 030_SC_007 450 open steps are one list for the kit's three summary requests plus one run read each")
    func fourHundredFiftySteps() async {
        let rig = Rig()
        rig.seed(Array(repeating: "Running", count: 450))
        await rig.store.refresh()
        #expect(rig.remote.summaryCalls.count == 1, "the store hands the kit the whole list; the kit splits it")
        #expect(rig.remote.summaryCalls.first?.count == 450)
        #expect(rig.remote.summaryRequests == 3)
        #expect(rig.remote.runCalls.count == 450)
        #expect(Set(rig.remote.runCalls).count == 450)
        #expect(rig.store.items.count == 450)
    }

    @Test("030_FR_005 clarification (c): a step that is no longer open leaves All runs and Waiting for")
    func openStepsOnly() async {
        let rig = Rig()
        rig.seed(["Running", "Failed"])
        await rig.store.refresh()
        rig.box.steps.removeAll { $0.serverID == "task_1" }
        rig.store.stepsChanged()
        #expect(rig.store.items.map(\.stepTitle) == ["Step 0"])
        #expect(rig.store.waitingForRows.count == 1)
        #expect(rig.store.perAgentCounts == ["conn_hermes": 1])
    }

    @Test("030_FR_025 a failed summaries read keeps the last-read runs and says they are stale")
    func staleNotice() async {
        let rig = Rig()
        rig.seed(["Running"])
        await rig.store.refresh()
        let read = rig.store.lastUpdated
        rig.clock.advance(120)
        rig.remote.failSummaries(AccountFixtures.failure(.network("offline"), reference: "ref_1"))
        await rig.store.refresh()
        #expect(rig.store.phase == .stale)
        #expect(rig.store.items.count == 1)
        #expect(rig.store.lastUpdated == read, "Last updated keeps the time of the last good read")
    }

    @Test("030_FR_025 the last-read run stays available to a reopened inspector while reads fail")
    func cachedRunSurvivesFailedReads() async {
        let rig = Rig()
        rig.seed(["Needs you"])
        #expect(rig.store.cachedRun(taskServerID: "task_0") == nil)
        await rig.store.refresh()
        rig.remote.failSummaries(AccountFixtures.failure(.network("offline"), reference: "ref_1"))
        rig.remote.failRuns(AccountFixtures.failure(.network("offline"), reference: "ref_1"))
        await rig.store.refresh()
        #expect(rig.store.cachedRun(taskServerID: "task_0")?.id == "run_task_0")
        #expect(rig.store.cachedRun(taskServerID: "task_other") == nil)
    }

    @Test("030_FR_025 a first read that fails shows the reference and no runs")
    func firstReadFails() async {
        let rig = Rig()
        rig.seed(["Running"])
        rig.remote.failSummaries(AccountFixtures.failure(.server, reference: "ref_9"))
        await rig.store.refresh()
        #expect(rig.store.phase == .failed(reference: "ref_9"))
        #expect(rig.store.items.isEmpty)
    }

    @Test("030_FR_025 a failed run read keeps the run from the last read and marks the list stale")
    func failedRunRead() async {
        let rig = Rig()
        rig.seed(["Running"])
        await rig.store.refresh()
        rig.remote.failRuns(AccountFixtures.failure(.server))
        await rig.store.refresh()
        #expect(rig.store.phase == .stale)
        #expect(rig.store.items.first?.connectionID == "conn_hermes")
    }

    @Test("030_FR_024 030_SC_004 a run is re-read at its own interval and the change shows")
    func pollsAtRunInterval() async {
        let rig = Rig()
        rig.seed(["Running"], interval: 30)
        await rig.store.refresh()
        rig.remote.resetCalls()
        rig.remote.set(task: "task_0", label: "Needs you", interval: 30, question: "Which card?")
        rig.clock.advance(29)
        await rig.store.pollDue()
        #expect(rig.remote.runCalls.isEmpty)
        #expect(rig.store.items.first?.state == .running)
        rig.clock.advance(1)
        await rig.store.pollDue()
        #expect(rig.remote.runCalls == ["run_task_0"])
        #expect(rig.store.items.first?.state == .needsYou)
        #expect(rig.store.items.first?.questionText == "Which card?")
        rig.clock.advance(29)
        await rig.store.pollDue()
        #expect(rig.remote.runCalls.count == 1, "the next read is a full interval later")
    }

    @Test("030_FR_024 summaries are re-read every 60 seconds and a changed label reads that run")
    func summaryTick() async {
        let rig = Rig()
        rig.seed(["Running", "Running"], interval: 3_600)
        await rig.store.refresh()
        rig.remote.resetCalls()
        rig.remote.set(task: "task_1", label: "Failed", interval: 3_600)
        rig.clock.advance(59)
        await rig.store.pollDue()
        #expect(rig.remote.summaryCalls.isEmpty)
        rig.clock.advance(1)
        await rig.store.pollDue()
        #expect(rig.remote.summaryCalls.count == 1)
        #expect(rig.remote.runCalls == ["run_task_1"], "only the run whose label changed is read")
        #expect(rig.store.sections.map(\.group) == [.running, .toReview])
    }

    @Test("030_FR_024 polling pauses while the window is hidden or the Mac is offline, then resumes")
    func pausesHiddenAndOffline() async {
        let rig = Rig()
        rig.seed(["Running"], interval: 30)
        await rig.store.refresh()
        rig.remote.resetCalls()
        rig.clock.advance(120)
        rig.store.isWindowVisible = false
        await rig.store.pollDue()
        rig.store.isWindowVisible = true
        rig.store.isOnline = false
        await rig.store.pollDue()
        #expect(rig.remote.summaryCalls.isEmpty && rig.remote.runCalls.isEmpty)
        rig.store.isOnline = true
        await rig.store.pollDue()
        #expect(rig.remote.summaryCalls.count == 1)
        #expect(rig.remote.runCalls == ["run_task_0"])
    }

    @Test("030_FR_024 ended runs are read once and not polled")
    func endedRunsAreNotPolled() async {
        let rig = Rig()
        rig.seed(["Failed", "Agent reported complete", "Running"], interval: 30)
        await rig.store.refresh()
        #expect(rig.remote.runCalls.count == 3)
        rig.remote.resetCalls()
        rig.clock.advance(30)
        await rig.store.pollDue()
        #expect(rig.remote.runCalls == ["run_task_2"])
    }

    @Test("030_FR_026 a read that finishes after the account changed is dropped")
    func lateAnswerIsDropped() async {
        let gate = AccountReadGate()
        let rig = Rig(gate: gate)
        rig.seed(["Running"])
        let store = rig.store
        let pending = Task { await store.refresh() }
        await gate.waitForArrival()
        rig.availability.update(account: AccountFixtures.account(id: "user_other"))
        await gate.release()
        await pending.value
        #expect(rig.store.items.isEmpty)
        #expect(rig.store.lastUpdated == nil)
        #expect(rig.remote.runCalls.isEmpty)
    }

    @Test("030_FR_026 reset drops everything that was listed")
    func resetDropsRuns() async {
        let rig = Rig()
        rig.seed(["Running"])
        await rig.store.refresh()
        rig.store.reset()
        #expect(rig.store.items.isEmpty && rig.store.sections.isEmpty && rig.store.perAgentCounts.isEmpty)
        #expect(rig.store.phase == .loading)
        #expect(rig.store.lastUpdated == nil)
    }

    @Test("030_FR_026 030_FR_027 run content past its expiry is replaced by the expired label, online or not")
    func contentExpires() async {
        let rig = Rig()
        rig.remote.set(task: "task_0", label: "Needs you", question: "Which card?", expires: 1_000_100)
        rig.box.steps = [AgentOpenStep(title: "Step 0", serverID: "task_0")]
        await rig.store.refresh()
        #expect(rig.store.items.first?.questionText == "Which card?")
        rig.clock.advance(100)
        rig.store.stepsChanged()
        #expect(rig.store.items.first?.state == .contentExpired)
        #expect(rig.store.items.first?.questionText == nil)
        #expect(rig.store.sections.map(\.group) == [.toReview])
    }

    @Test("030_FR_039 the log lines carry counts and stages, never a title or an agent name")
    func logsHoldNoContent() async {
        let rig = Rig()
        rig.seed(["Needs you"])
        await rig.store.refresh()
        let lines = rig.log.messages()
        #expect(!lines.isEmpty)
        for line in lines {
            #expect(!line.contains("Step 0") && !line.contains("Hermes") && !line.contains("task_0"))
        }
    }
}
