import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// A scripted `AgentAvailabilityRemote` that counts its calls and can hold `me()`.
final class FakeAvailabilityRemote: AgentAvailabilityRemote {
    private struct State {
        var me: Result<MeDTO, APIError>
        var methods: Result<AccountAuthMethodsDTO, APIError>
        var meCalls = 0
    }

    private let state: Mutex<State>
    private let gate: AccountReadGate?

    init(
        flag: Bool = true, owner: String = "user_max", password: Bool = true,
        me: Result<MeDTO, APIError>? = nil, methods: Result<AccountAuthMethodsDTO, APIError>? = nil,
        gate: AccountReadGate? = nil
    ) {
        let dto = MeDTO(id: owner, email: "max@example.com", featureFlags: ["external_agent_relay": flag])
        state = Mutex(State(me: me ?? .success(dto), methods: methods ?? .success(AccountFixtures.methods(id: owner, password: password))))
        self.gate = gate
    }

    var meCalls: Int { state.withLock { $0.meCalls } }

    func setFlag(_ flag: Bool) {
        state.withLock { $0.me = .success(MeDTO(id: "user_max", email: "max@example.com", featureFlags: ["external_agent_relay": flag])) }
    }

    func setMe(_ result: Result<MeDTO, APIError>) { state.withLock { $0.me = result } }

    func me() async throws(APIError) -> MeDTO {
        let result = state.withLock { state in
            state.meCalls += 1
            return state.me
        }
        await gate?.pass()
        return try result.get()
    }

    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO {
        try state.withLock { $0.methods }.get()
    }
}

/// A clock the test moves by hand.
@MainActor
final class AgentTestClock {
    var date = Date(timeIntervalSince1970: 1_000_000)
    func advance(_ seconds: TimeInterval) { date = date.addingTimeInterval(seconds) }
}

@MainActor
@Suite("030 Agent availability")
struct AgentAvailabilityTests {
    private func make(
        _ remote: FakeAvailabilityRemote, account: LinkedAccount? = AccountFixtures.account(),
        clock: AgentTestClock = AgentTestClock(), log: CapturingMacLog = CapturingMacLog()
    ) -> AgentAvailability {
        AgentAvailability(account: account, remote: { _ in remote }, now: { clock.date }, log: log)
    }

    @Test("030_FR_002 the relay flag and the password state are read at sign-in")
    func readsFlagAndPassword() async {
        let on = make(FakeAvailabilityRemote(flag: true, password: true))
        await on.refresh()
        #expect(on.relayEnabled)
        #expect(on.passwordState == .has)
        let off = make(FakeAvailabilityRemote(flag: false, password: false))
        await off.refresh()
        #expect(!off.relayEnabled)
        #expect(off.passwordState == .none)
    }

    @Test("030_FR_036 an unreadable password state is unknown, so controls stay")
    func unreadablePasswordIsUnknown() async {
        let remote = FakeAvailabilityRemote(methods: .failure(AccountFixtures.failure(.network("offline"))))
        let model = make(remote)
        await model.refresh()
        #expect(model.relayEnabled)
        #expect(model.passwordState == AgentPasswordState.unknown)
    }

    @Test("030_FR_001 a signed-out Mac has no owner, no flag and reads nothing")
    func signedOutReadsNothing() async {
        let remote = FakeAvailabilityRemote()
        let model = make(remote, account: nil)
        await model.refresh()
        #expect(model.ownerID == nil)
        #expect(!model.relayEnabled)
        #expect(remote.meCalls == 0)
    }

    @Test("030_FR_002 activation reads at most once every five minutes")
    func activationIsThrottled() async {
        let remote = FakeAvailabilityRemote()
        let clock = AgentTestClock()
        let model = make(remote, clock: clock)
        await model.refresh()
        clock.advance(299)
        await model.activate()
        #expect(remote.meCalls == 1)
        clock.advance(1)
        await model.activate()
        #expect(remote.meCalls == 2)
    }

    @Test("030_FR_002 a relay-unavailable answer hides the controls, then reads again")
    func relayUnavailableRefreshes() async {
        let remote = FakeAvailabilityRemote(flag: false)
        let model = make(remote)
        await model.refresh()
        remote.setFlag(true)
        await model.relayUnavailable()
        #expect(remote.meCalls == 2)
        #expect(model.relayEnabled, "the fresh read decides, not the failed route")
    }

    @Test("030_FR_002 a failed read keeps the last flag and a network failure marks the Mac offline")
    func failedReadKeepsFlag() async {
        let remote = FakeAvailabilityRemote()
        let model = make(remote)
        await model.refresh()
        remote.setMe(.failure(AccountFixtures.failure(.network("offline"))))
        await model.refresh()
        #expect(model.relayEnabled, "the last known flag stays while the read fails")
        #expect(!model.isOnline)
    }

    @Test("030_FR_026 a late answer for the previous account is discarded")
    func lateAnswerIsDiscarded() async {
        let gate = AccountReadGate()
        let model = make(FakeAvailabilityRemote(gate: gate))
        let pending = Task { await model.refresh() }
        await gate.waitForArrival()
        model.update(account: AccountFixtures.account(id: "user_other"))
        await gate.release()
        await pending.value
        #expect(model.ownerID == "user_other")
        #expect(!model.relayEnabled, "nothing of the old account shows")
        #expect(model.passwordState == AgentPasswordState.unknown)
    }

    @Test("030_FR_036 the Add new agent request is consumed once")
    func addAgentRequestIsOneShot() {
        let model = make(FakeAvailabilityRemote())
        let idle = model.consumeAddAgentRequest()
        model.requestAddAgent()
        let first = model.consumeAddAgentRequest()
        let second = model.consumeAddAgentRequest()
        #expect(!idle && first && !second)
    }

    @Test("030_FR_036 the hand-off Open Settings request is one-shot and never asks for the Add sheet")
    func agentsTabRequestIsOneShot() {
        let model = make(FakeAvailabilityRemote())
        let idle = model.consumeAgentsTabRequest()
        model.requestAgentsTab()
        let addAsked = model.addAgentRequested
        let first = model.consumeAgentsTabRequest()
        let second = model.consumeAgentsTabRequest()
        model.requestAgentsTab()
        let again = model.consumeAgentsTabRequest()
        #expect(!idle && first && !second && again, "each request is seen once, a later one again")
        #expect(!addAsked, "Add new agent is not requested")
    }
}
