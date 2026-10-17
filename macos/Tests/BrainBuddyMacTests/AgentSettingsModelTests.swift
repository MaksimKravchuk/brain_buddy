import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// `AgentConnectionResponse` as the server sends it, reduced to what the Mac reads.
enum AgentFixtures {
    static func connection(
        id: String = "agent_1", name: String = "Hermes", address: String = "https://hermes.myhost.dev",
        status: String = "ready", scheme: String = "bearer", header: String? = nil, stale: Bool = false,
        ready: Bool = true, revision: Int = 3, errorCode: String? = nil
    ) -> AgentConnectionDTO {
        let headerJSON = header.map { "\"\($0)\"" } ?? "null"
        let errorJSON = errorCode.map { "\"\($0)\"" } ?? "null"
        let json = #"""
            {"id":"\#(id)","name":"\#(name)","agent_address":"\#(address)","auth_scheme":"\#(scheme)",\#
            "auth_header_name":\#(headerJSON),"status":"\#(status)","stale":\#(stale),"ready_for_handoff":\#(ready),\#
            "capabilities":{"streaming":true,"push_notifications":false},"controls_offered":{"reply":true,"cancel":true},\#
            "card":{"name":"Hermes","version":"2.3","description":null,"protocol_version":"1.0","interface_url":null,\#
            "skills":[{"id":"s1","name":"Web research","description":null},{"id":"s2","name":"bookings","description":null}]},\#
            "guarantee_tier":"guaranteed","tier_disclosure":null,"cancellation_disclosure":null,"agent_changed":false,\#
            "last_test_error_code":\#(errorJSON),"last_contact_at":"2026-10-16T09:00:00Z",\#
            "last_tested_at":"2026-10-16T08:00:00Z","stale_after_seconds":900,"created_at":"2026-10-01T08:00:00Z",\#
            "revision":\#(revision)}
            """#
        do { return try BrainBuddyAPI.makeDecoder().decode(AgentConnectionDTO.self, from: Data(json.utf8)) } catch {
            preconditionFailure("fixture does not decode: \(error)")
        }
    }

    static let wrongPassword = APIError(kind: .rejected, message: "Reauthentication failed.", referenceID: "ref_403", statusCode: 403)
    static let stale = APIError(kind: .staleRevision(resource: "agent", id: "agent_1"), message: "changed", statusCode: 409)
    static let rateLimited = APIError(kind: .rateLimited, message: "slow down", statusCode: 429)
    static let offline = APIError(kind: .network("offline"), message: "No connection")
    static let relayOff = APIError(
        kind: .notFound(resource: nil, id: nil), message: APIError.agentRelayUnavailableMessage, statusCode: 404)
}

/// Records every call; mutations answer from a queue, in order.
final class FakeAgentRemote: AgentSettingsRemote {
    struct Call: Equatable {
        var op: String
        var id: String?
        var name: String?
        var address: String?
        var scheme: String?
        var credential: String?
        var password: String?
        var revision: Int?
        var key: UUID?
    }

    private struct State {
        var calls: [Call] = []
        var list: Result<[AgentConnectionDTO], APIError>
        var responses: [Result<AgentConnectionDTO, APIError>] = []
        var reread: Result<AgentConnectionDTO, APIError>
    }

    private let state: Mutex<State>
    private let gate: AccountReadGate?

    init(
        list: Result<[AgentConnectionDTO], APIError> = .success([]), reread: Result<AgentConnectionDTO, APIError> = .success(
            AgentFixtures.connection()), gate: AccountReadGate? = nil
    ) {
        state = Mutex(State(list: list, reread: reread))
        self.gate = gate
    }

    var calls: [Call] { state.withLock { $0.calls } }
    func queue(_ result: Result<AgentConnectionDTO, APIError>) { state.withLock { $0.responses.append(result) } }

    private func record(_ call: Call) -> Result<AgentConnectionDTO, APIError> {
        state.withLock { state in
            state.calls.append(call)
            return state.responses.isEmpty ? .failure(AgentFixtures.offline) : state.responses.removeFirst()
        }
    }

    func agentConnections() async throws(APIError) -> [AgentConnectionDTO] {
        let result = state.withLock { state in
            state.calls.append(Call(op: "list"))
            return state.list
        }
        await gate?.pass()
        return try result.get()
    }

    func agentConnection(id: String) async throws(APIError) -> AgentConnectionDTO {
        try state.withLock { state in
            state.calls.append(Call(op: "read", id: id))
            return state.reread
        }.get()
    }

    func createAgentConnection(
        name: String, address: String, scheme: AgentAuthScheme, credential: String, currentPassword: String,
        idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        try record(
            Call(
                op: "create", name: name, address: address, scheme: scheme.wireValue, credential: credential,
                password: currentPassword, key: idempotencyKey)
        ).get()
    }

    func updateAgentConnection(
        id: String, name: String?, address: String?, scheme: AgentAuthScheme?, currentPassword: String?,
        expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        try record(
            Call(
                op: "update", id: id, name: name, address: address, scheme: scheme?.wireValue, password: currentPassword,
                revision: expectedRevision, key: idempotencyKey)
        ).get()
    }

    func testAgentConnection(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentConnectionDTO {
        try record(Call(op: "test", id: id, key: idempotencyKey)).get()
    }

    func replaceAgentCredential(
        id: String, credential: String, currentPassword: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        try record(
            Call(op: "replace", id: id, credential: credential, password: currentPassword, revision: expectedRevision, key: idempotencyKey)
        ).get()
    }

    func disconnectAgentConnection(
        id: String, currentPassword: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO {
        try record(Call(op: "disconnect", id: id, password: currentPassword, revision: expectedRevision, key: idempotencyKey)).get()
    }
}

@MainActor
@Suite("030 Agent settings model")
struct AgentSettingsModelTests {
    /// A model with the account's password state read; `password: nil` leaves it unread.
    private func make(
        _ remote: FakeAgentRemote, password: Bool? = true, log: CapturingMacLog = CapturingMacLog()
    ) async -> AgentSettingsModel {
        let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in FakeAvailabilityRemote(password: password ?? true) })
        if password != nil { await availability.refresh() }
        return AgentSettingsModel(account: AccountFixtures.account(), availability: availability, remote: { _ in remote }, log: log)
    }

    private let three = [
        AgentFixtures.connection(),
        AgentFixtures.connection(id: "agent_2", name: "Claude", address: "https://claude.example.org"),
        AgentFixtures.connection(id: "agent_3", name: "Home server", stale: true),
    ]

    @Test("030_FR_029 the list leaves disconnected agents out and selects the first")
    func listOmitsDisconnected() async {
        let gone = AgentFixtures.connection(id: "agent_x", name: "Old", status: "disconnected", ready: false)
        let model = await make(FakeAgentRemote(list: .success([three[0], gone, three[1], three[2]])))
        await model.reload()
        #expect(model.phase == .loaded)
        #expect(model.rows.map(\.name) == ["Hermes", "Claude", "Home server"])
        #expect(model.rows.map(\.status) == ["Tested ready", "Tested ready", "Stale"])
        #expect(model.selectedID == "agent_1")
    }

    @Test("030_FR_029 the detail rows read the connection as design G-06.01 does")
    func detailRows() async throws {
        let model = await make(FakeAgentRemote(list: .success(three)))
        await model.reload()
        let rows = try #require(model.details)
        #expect(rows.statusLine == "Tested ready · Ready to receive a hand-off.")
        #expect(rows.address == "https://hermes.myhost.dev")
        #expect(rows.credential == "Bearer token · stored sealed")
        #expect(rows.card == "2.3 · protocol 1.0")
        #expect(rows.skills == "Web research, bookings")
        #expect(rows.updates == "Streaming · no push")
        #expect(rows.guarantee == "Guaranteed single start")
        #expect(rows.lastContact != nil)
    }

    @Test("030_FR_029 an API key shows its header name")
    func apiKeyCredential() {
        let rows = AgentSettingsModel.details(AgentFixtures.connection(scheme: "api_key", header: "X-Api-Key"))
        #expect(rows.credential == "API key in X-Api-Key · stored sealed")
    }

    @Test("030_FR_030 status words and sentences are the web's for the same connection")
    func statusParity() {
        let cases: [(AgentConnectionDTO, String, String)] = [
            (AgentFixtures.connection(status: "untested", ready: false), "Not tested", AgentsCopy.statusDetail(.init(status: "untested"))),
            (AgentFixtures.connection(status: "unreachable", ready: false), "Unreachable", AgentsCopy.statusDetail(.init(status: "unreachable"))),
            (AgentFixtures.connection(status: "invalid_credentials", ready: false), "Invalid credentials", AgentsCopy.statusDetail(.init(status: "invalid_credentials"))),
            (AgentFixtures.connection(stale: true), "Stale", AgentsCopy.statusDetail(.init(status: "ready", stale: true, staleAfterSeconds: 900))),
            (AgentFixtures.connection(status: "unsupported", ready: false, errorCode: "a2a_not_an_agent"), "Unsupported", AgentsCopy.statusDetail(.init(status: "unsupported", errorCode: "a2a_not_an_agent"))),
        ]
        for (dto, word, sentence) in cases {
            #expect(AgentSettingsModel.status(of: dto) == word)
            #expect(AgentSettingsModel.details(dto).statusLine == "\(word) · \(sentence)")
        }
    }

    @Test("030_FR_030 Test again sends no password, one key, and shows the new status")
    func testAgainShowsNewStatus() async throws {
        let remote = FakeAgentRemote(list: .success(three))
        let model = await make(remote)
        await model.reload()
        remote.queue(.success(AgentFixtures.connection(status: "unreachable", ready: false, revision: 4)))
        await model.testAgain()
        let calls = remote.calls.filter { $0.op == "test" }
        #expect(calls.count == 1)
        #expect(calls.first?.id == "agent_1")
        #expect(calls.first?.password == nil)
        #expect(calls.first?.key != nil)
        #expect(model.rows.first?.status == "Unreachable")
        #expect(model.isTesting == false)
    }

    @Test("030_FR_030 a failed Test again says so in words and keeps the list")
    func testAgainFailure() async {
        let remote = FakeAgentRemote(list: .success(three))
        let model = await make(remote)
        await model.reload()
        remote.queue(.failure(AgentFixtures.offline))
        await model.testAgain()
        #expect(model.notice?.message == AgentsCopy.needsConnection)
        #expect(model.rows.count == 3)
        #expect(model.phase == .loaded)
    }

    @Test("030_FR_036 an account with no password gets no Add; an unread state keeps the controls")
    func passwordless() async {
        let none = await make(FakeAgentRemote(list: .success(three)), password: false)
        await none.reload()
        #expect(none.isPasswordless)
        #expect(!none.canAdd)
        #expect(none.canTest, "Test again needs no password")
        let unread = await make(FakeAgentRemote(list: .success(three)), password: nil)
        await unread.reload()
        #expect(!unread.isPasswordless)
        #expect(unread.canAdd)
    }

    @Test("030_FR_038 offline, failed and session-ended reads are told apart, with the reference")
    func readFailures() async {
        let offline = await make(FakeAgentRemote(list: .failure(AgentFixtures.offline)))
        await offline.reload()
        #expect(offline.phase == .offline)
        #expect(!offline.controlsEnabled)
        let server = APIError(kind: .server, message: "boom", referenceID: "ref_9", statusCode: 500)
        let failed = await make(FakeAgentRemote(list: .failure(server)))
        await failed.reload()
        #expect(failed.phase == .failed(AgentNotice(message: AgentsCopy.agentsFailed, reference: "ref_9", canRetry: true)))
        let ended = await make(FakeAgentRemote(list: .failure(APIError(kind: .unauthorized, message: "no", statusCode: 401))))
        await ended.reload()
        #expect(ended.phase == .sessionEnded)
    }

    @Test("030_FR_029 a late answer for the previous account is dropped")
    func lateAnswerIsDropped() async {
        let gate = AccountReadGate()
        let model = await make(FakeAgentRemote(list: .success(three), gate: gate))
        let pending = Task { await model.reload() }
        await gate.waitForArrival()
        model.update(account: AccountFixtures.account(id: "user_other"))
        await gate.release()
        await pending.value
        #expect(model.account?.id == "user_other")
        #expect(model.rows.isEmpty)
        #expect(model.phase == .loading)
    }

    @Test("030_FR_040 Up and Down change the selected agent and stop at the ends")
    func arrowsMoveSelection() async {
        let model = await make(FakeAgentRemote(list: .success(three)))
        await model.reload()
        #expect(model.selectedID == "agent_1")
        #expect(model.moveSelection(by: -1) == "agent_1")
        #expect(model.moveSelection(by: 1) == "agent_2")
        #expect(model.moveSelection(by: 1) == "agent_3")
        #expect(model.moveSelection(by: 1) == "agent_3")
        #expect(model.moveSelection(by: -1) == "agent_2")
        #expect(model.selected?.name == "Claude")
    }

    @Test("030_FR_040 arrows with no agents select nothing")
    func arrowsWithNoAgents() async {
        let model = await make(FakeAgentRemote(list: .success([])))
        await model.reload()
        #expect(model.moveSelection(by: 1) == nil)
    }

    @Test("030_FR_039 reads and tests log stage and outcome, never a name or address")
    func logsCarryNoContent() async {
        let log = CapturingMacLog()
        let remote = FakeAgentRemote(list: .success(three))
        let model = await make(remote, log: log)
        await model.reload()
        remote.queue(.success(three[0]))
        await model.testAgain()
        let text = log.messages().joined(separator: "\n")
        #expect(text.contains("agent-settings stage=reload outcome=loaded"))
        #expect(!text.contains("Hermes") && !text.contains("hermes.myhost.dev"))
    }
}
