import BrainBuddyAgents
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The Agents sidebar section, All runs and Waiting for as the window reads them from `BrainBuddyModel`
/// (G-01 – G-03). The views draw exactly these values.
@MainActor
@Suite("030 Agents scene")
struct AgentsSceneTests {
    @MainActor
    struct Rig {
        let model: BrainBuddyModel
        let remote = FakeRunsRemote()
        let folder = TemporaryFolder()

        /// `labels` are the run labels of steps `step_0…`; steps 0 and 1 wait on a person when `waiting` is set.
        static func make(
            signedIn: Bool = true, flag: Bool = true, password: Bool = true, labels: [String] = [], waiting: Bool = false
        ) async -> Rig {
            let created = Date(timeIntervalSince1970: 0)
            var tasks: [TaskID: TaskRecord] = [:]
            for index in labels.indices {
                let id = TaskID("step_\(index)")
                tasks[id] = TaskRecord(
                    id: id, serverID: "task_\(index)", title: "Step \(index)", state: waiting && index < 2 ? .waiting : .next,
                    waitingFor: waiting && index < 2 ? "Sam" : nil, orderKey: index, createdAt: created, updatedAt: created)
            }
            let document = StoreDocument(
                generation: 1, base: GTDState(tasks: tasks), account: signedIn ? AccountFixtures.account() : nil)
            let workspace = Workspace(store: InMemoryDocumentStore(document: document), sync: nil)
            await workspace.load()
            let rig = Rig(workspace: workspace, flag: flag, password: password)
            for (index, label) in labels.enumerated() { rig.remote.set(task: "task_\(index)", label: label) }
            await rig.model.refreshAgents()
            return rig
        }

        private init(workspace: Workspace, flag: Bool, password: Bool) {
            model = BrainBuddyModel(
                workspace: workspace, localStateStore: MacLocalStateStore(directory: folder.url),
                now: { Date(timeIntervalSince1970: 1_000_000) },
                agentAvailabilityRemote: { _ in FakeAvailabilityRemote(flag: flag, password: password) },
                agentRunsRemote: remote)
        }
    }

    @Test("030_FR_001 signed out there is no Agents section, no run and no read")
    func signedOut() async {
        let rig = await Rig.make(signedIn: false, labels: ["Running"])
        #expect(!rig.model.showsAgentsSection)
        #expect(!rig.model.canAddAgent)
        #expect(rig.model.listedRuns.isEmpty)
        #expect(rig.remote.summaryCalls.isEmpty)
    }

    @Test("030_FR_002 030_FR_004 030_FR_036 the section and Add new agent follow the flag and the password state")
    func sectionFollowsFlagAndPassword() async {
        let on = await Rig.make()
        #expect(on.model.showsAgentsSection, "flag on shows the section with no run")
        #expect(on.model.canAddAgent)

        let noPassword = await Rig.make(password: false)
        #expect(noPassword.model.showsAgentsSection)
        #expect(!noPassword.model.canAddAgent, "an account without a password cannot add an agent")

        let off = await Rig.make(flag: false)
        #expect(!off.model.showsAgentsSection, "flag off, no agent and no run")
        #expect(!off.model.canAddAgent)

        let offWithRuns = await Rig.make(flag: false, labels: ["Needs you"])
        #expect(offWithRuns.model.showsAgentsSection, "existing runs stay readable with the flag off")
        #expect(!offWithRuns.model.canAddAgent)
        #expect(offWithRuns.model.listedRuns.count == 1)
    }

    @Test("030_FR_004 030_FR_008 All runs counts every listed run and an agent row counts its own")
    func countsAndFilter() async {
        let rig = await Rig.make(labels: ["Needs you", "Running", "Failed"])
        #expect(rig.model.listedRuns.count == 3)
        #expect(rig.model.agentRuns.perAgentCounts == ["conn_hermes": 3])
        #expect(WorkspaceDestination.agentRuns(.all) != .agentRuns(.agent("conn_hermes")))
        #expect(WorkspaceDestination.agentRuns(.all).isAgentRuns)
        #expect(!WorkspaceDestination.list(.waiting).isAgentRuns)
    }

    @Test("030_FR_009 Waiting for lists the agent runs without moving a step")
    func waitingForGroupsAndCount() async {
        let rig = await Rig.make(labels: ["Needs you", "Running", "Queued"], waiting: true)
        let before = rig.model.workspace.state
        await rig.model.workspace.prepareCounts()
        let people = rig.model.sidebarCounts.count(for: .waiting)
        #expect(people == 2)
        #expect(rig.model.listedRuns.count == 3)
        #expect(AgentsCopy.waitingHeader(people: people, agents: rig.model.listedRuns.count) == "2 people, 3 agents")
        #expect(rig.model.workspace.state == before, "grouping is on the client; no step moved")
        #expect(rig.model.agentRuns.sections.map(\.group) == [.needsYou, .running, .queued])
    }

    @Test("030_FR_009 with no listed run Waiting for is unchanged")
    func waitingForUnchangedWithoutRuns() async {
        let rig = await Rig.make(labels: [], waiting: true)
        #expect(rig.model.listedRuns.isEmpty)
        #expect(AgentsCopy.waitingHeader(people: 1, agents: 1) == "1 person, 1 agent")
    }

    @Test("030_FR_011 030_SC_006 a run row selects its step and changes nothing")
    func runRowSelectsTheStep() async {
        let rig = await Rig.make(flag: false, labels: ["Needs you", "Running"])
        let before = rig.model.workspace.state
        let run = rig.model.listedRuns.first { $0.stepTitle == "Step 1" }
        #expect(rig.model.stepID(forServerID: run?.taskServerID ?? "") == TaskID("step_1"))
        #expect(rig.model.workspace.state == before)
        #expect(!rig.model.canAddAgent)
    }

    @Test("030_FR_026 sign-out drops every listed run")
    func signOutClearsRuns() async {
        let rig = await Rig.make(labels: ["Running"])
        #expect(rig.model.listedRuns.count == 1)
        rig.model.didSignOut()
        #expect(rig.model.listedRuns.isEmpty)
        #expect(!rig.model.showsAgentsSection)
        #expect(rig.model.stepID(forServerID: "task_0") == nil)
    }
}
