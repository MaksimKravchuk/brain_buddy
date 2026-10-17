import BrainBuddyAgents
import BrainBuddyAPI
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The workspace's step commands as the agent feature sees them: every call is recorded.
@MainActor
final class FakeStepCommands: StepCommands {
    private(set) var calls: [String] = []
    var completeFails = false

    func completeStep(serverID: String) async throws {
        if completeFails { throw HandoffFixture.offline }
        calls.append("complete:\(serverID)")
    }

    func createNextAction(title: String, projectID: String?) async throws {
        calls.append("create:\(title)@\(projectID ?? "none")")
    }
}

@MainActor
@Suite("030 Agent run actions")
struct AgentRunActionsTests {
    @MainActor
    private struct Rig {
        let actions: AgentRunActions
        let remote: FakeHandoffRemote
        let steps = FakeStepCommands()
        let availability: AgentAvailability
        let refreshes = RefreshCount()

        init(online: Bool = true) async {
            let remote = FakeHandoffRemote()
            let me: Result<MeDTO, APIError>? = online ? nil : .failure(HandoffFixture.offline)
            let flag = FakeAvailabilityRemote(me: me)
            let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in flag })
            await availability.refresh()
            let (stepFake, counter) = (self.steps, self.refreshes)
            (self.remote, self.availability) = (remote, availability)
            actions = AgentRunActions(
                remote: remote, availability: availability, steps: stepFake, refresh: { counter.count += 1 })
        }
    }

    @MainActor
    final class RefreshCount {
        var count = 0
    }

    @Test("030_FR_012 030_SC_002 hand-off, polling, reply, stop, check again and every run label issue no step command")
    func noStepCommandFromAnyAgentSurface() async {
        let labels = [
            "Not sent", "Queued", "Sent", "Delivery unconfirmed", "Accepted", "Running", "Needs you",
            "Cancellation requested", "Agent reported complete", "Failed", "Cancelled", "Stopped reporting",
            "Agent no longer reports this run", "Connection disconnected", "Content expired under retention policy",
        ]
        let rig = await Rig()
        let polling = AgentRunsStoreTests.Rig()
        polling.seed(labels)
        let flow = HandoffFlow(
            taskServerID: "task_0", projectName: "Admin", remote: rig.remote, availability: rig.availability)
        rig.remote.script(
            connections: [HandoffFixture.connection(id: "conn_a", name: "Hermes")], manifests: [HandoffFixture.manifest()])
        await flow.start()
        await flow.send()
        await polling.store.refresh()
        polling.clock.advance(120)
        await polling.store.pollDue()
        let run = HandoffFixture.run()
        await rig.actions.reply(to: run, message: "Use the blue one")
        await rig.actions.stop(run)
        await rig.actions.checkAgain(run)
        let shown = polling.store.items.map(\.state)
        #expect(flow.phase == .sent(runID: "run_1"))
        #expect(shown.count == labels.count)
        #expect(rig.steps.calls.isEmpty)
    }

    @Test("030_FR_022 030_SC_002 Mark step done completes the step only, or completes and creates in the same project")
    func markStepDoneIssuesCompleteAndOptionalCreate() async {
        let rig = await Rig()
        await rig.actions.markStepDone(taskServerID: "task_1", projectID: "proj_1", nextStep: "   ")
        #expect(rig.steps.calls == ["complete:task_1"])
        await rig.actions.markStepDone(taskServerID: "task_2", projectID: "proj_1", nextStep: "Book the van")
        #expect(rig.steps.calls == ["complete:task_1", "complete:task_2", "create:Book the van@proj_1"])
        await rig.actions.markStepDone(taskServerID: "task_3", projectID: nil, nextStep: "Call back")
        #expect(Array(rig.steps.calls.suffix(2)) == ["complete:task_3", "create:Call back@none"])
        #expect(rig.actions.phase == .done)
    }

    @Test("030_FR_022 a failed complete creates nothing and the failure shows")
    func failedCompleteCreatesNothing() async {
        let rig = await Rig()
        rig.steps.completeFails = true
        await rig.actions.markStepDone(taskServerID: "task_1", projectID: nil, nextStep: "Next")
        #expect(rig.steps.calls.isEmpty)
        #expect(rig.actions.phase == .failed(.other(reference: nil)))
    }

    @Test("030_FR_020 Reply sends the message with the revision the person saw and shows the pending run")
    func replyPending() async {
        let rig = await Rig()
        rig.remote.script(runs: [.success(HandoffFixture.run(revision: 5, replyPending: true))])
        await rig.actions.reply(to: HandoffFixture.run(label: "Needs you", revision: 4), message: "  Use the blue one ")
        #expect(rig.remote.runCalls == ["reply:run_1:4:Use the blue one"])
        #expect(rig.actions.updated?.replyPending == true)
        #expect(rig.actions.phase == .done)
        #expect(rig.refreshes.count == 1)
    }

    @Test("030_FR_020 a reply over 4,000 characters, or an empty one, is never sent")
    func replyLimit() async {
        let rig = await Rig()
        let run = HandoffFixture.run()
        await rig.actions.reply(to: run, message: String(repeating: "a", count: 4_000))
        await rig.actions.reply(to: run, message: String(repeating: "a", count: 4_001))
        #expect(rig.remote.runCalls.count == 1)
        #expect(rig.actions.phase == .failed(.tooLong))
        await rig.actions.reply(to: run, message: "   ")
        #expect(rig.remote.runCalls.count == 1)
    }

    @Test("030_FR_020 030_FR_023 a withdrawn Reply or Stop control is refused without a call")
    func withdrawnControls() async {
        let rig = await Rig()
        let run = HandoffFixture.run(reply: false, cancel: false)
        await rig.actions.reply(to: run, message: "Hi")
        #expect(rig.actions.phase == .failed(.controlWithdrawn))
        await rig.actions.stop(run)
        #expect(rig.actions.phase == .failed(.controlWithdrawn))
        #expect(rig.remote.runCalls.isEmpty)
    }

    @Test("030_FR_020 a stale revision on reply is shown in words and the runs are read again")
    func staleRevisionOnReply() async {
        let rig = await Rig()
        rig.remote.script(runs: [.failure(HandoffFixture.error(.staleRevision(resource: "Run", id: "run_1"), status: 409))])
        await rig.actions.reply(to: HandoffFixture.run(), message: "Hi")
        #expect(rig.actions.phase == .failed(.staleRevision))
        #expect(AgentActionFailure.staleRevision.text() == "This agent changed elsewhere. Check and try again.")
        #expect(rig.refreshes.count == 1)
    }

    @Test("030_FR_023 Stop run sends one cancel and re-reads the runs")
    func stopRun() async {
        let rig = await Rig()
        await rig.actions.stop(HandoffFixture.run())
        #expect(rig.remote.runCalls == ["stop:run_1"])
        #expect(rig.refreshes.count == 1)
    }

    @Test("030_FR_025 offline, Reply, Stop run and Check again refuse and nothing is queued")
    func offlineRefusesWithoutQueueing() async {
        let rig = await Rig(online: false)
        let run = HandoffFixture.run()
        await rig.actions.reply(to: run, message: "Hi")
        #expect(rig.actions.phase == .failed(.offline))
        await rig.actions.stop(run)
        await rig.actions.checkAgain(run, password: "secret")
        #expect(rig.remote.runCalls.isEmpty)
        #expect(AgentActionFailure.offline.text() == "Needs a connection.")
    }

    @Test("030_FR_023 Check again sends the password only when one was typed, and a retry keeps its key")
    func checkAgainPasswordPath() async {
        let rig = await Rig()
        rig.remote.script(runs: [.failure(HandoffFixture.offline), .success(HandoffFixture.run()), .failure(HandoffFixture.wrongPassword)])
        let run = HandoffFixture.run(label: "Delivery unconfirmed")
        await rig.actions.checkAgain(run)
        await rig.actions.checkAgain(run)
        #expect(rig.remote.runCalls == ["check:run_1:4:-", "check:run_1:4:-"])
        #expect(rig.remote.runKeys[0] == rig.remote.runKeys[1])
        await rig.actions.checkAgain(run, password: "secret")
        #expect(rig.remote.runCalls.last == "check:run_1:4:secret")
        #expect(rig.remote.runKeys[2] != rig.remote.runKeys[1])
        #expect(rig.actions.phase == .failed(.wrongPassword))
    }

    @Test("030_FR_020 one Reply keeps one key through a retry and a different reply gets another")
    func replyKeyReuse() async {
        let rig = await Rig()
        rig.remote.script(runs: [.failure(HandoffFixture.error(.server, status: 503)), .success(HandoffFixture.run())])
        let run = HandoffFixture.run()
        await rig.actions.reply(to: run, message: "Yes")
        await rig.actions.reply(to: run, message: "Yes")
        await rig.actions.reply(to: run, message: "No")
        let keys = rig.remote.runKeys
        #expect(keys[0] == keys[1])
        #expect(keys[2] != keys[1])
    }
}
