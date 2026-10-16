import BrainBuddyAPI
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// Fixtures shaped like the kit's own decoding tests (`AgentConnectionResponse`, `AgentManifestResponse`, `AgentRunResponse`).
enum HandoffFixture {
    static func decode<T: Decodable>(_ type: T.Type, _ json: String) -> T {
        try! BrainBuddyAPI.makeDecoder().decode(type, from: Data(json.utf8))
    }

    static func connection(id: String, name: String, ready: Bool = true, tier: String = "best_effort", skills: [String] = []) -> AgentConnectionDTO {
        let list = skills.map { #"{"id":"\#($0)","name":"\#($0)","description":null}"# }.joined(separator: ",")
        let card = #"{"name":"\#(name)","version":"1","description":null,"protocol_version":"1.0","interface_url":"https://a.example","skills":[\#(list)]}"#
        return decode(
            AgentConnectionDTO.self,
            #"""
            {"id":"\#(id)","name":"\#(name)","agent_address":"https://a.example","auth_scheme":"bearer","auth_header_name":null,\#
            "status":"ready","stale":false,"ready_for_handoff":\#(ready),"capabilities":{"streaming":true,"push_notifications":false},\#
            "controls_offered":{"reply":true,"cancel":true},"card":\#(card),"guarantee_tier":"\#(tier)","tier_disclosure":null,\#
            "cancellation_disclosure":null,"agent_changed":false,"last_test_error_code":null,"last_contact_at":null,\#
            "last_tested_at":null,"stale_after_seconds":900,"created_at":"2026-10-01T08:00:00Z","revision":3}
            """#)
    }

    static func manifest(token: String = "tok_1", password: Bool = false, acknowledge: Bool = false) -> AgentManifestDTO {
        decode(
            AgentManifestDTO.self,
            #"""
            {"token":"\#(token)","run_id":"run_1","task_id":"task_1","connection_id":"conn_a","agent_name":"Hermes","title":"Renew passport",\#
            "details":"Photos first","supporting_items":[{"label":"Project","body":"Admin"}],"guarantee_tier":"best_effort",\#
            "tier_disclosure":"Updates may be delayed.","acknowledgement_required":\#(acknowledge),\#
            "cancellation_disclosure":"Stopping asks the agent to stop.","external_copy_notice":"Text you send leaves BrainBuddy.",\#
            "reauthentication_required":\#(password)}
            """#)
    }

    static func run(
        id: String = "run_1", label: String = "Sent", revision: Int = 4, reply: Bool = true, cancel: Bool = true,
        replyPending: Bool = false
    ) -> AgentRunDTO {
        decode(
            AgentRunDTO.self,
            #"""
            {"id":"\#(id)","task_id":"task_1","connection_id":"conn_a","agent_name":"Hermes","dispatch_state":"sent",\#
            "dispatch_error_code":null,"reported_state":"running","run_version":2,"stopped_reporting":false,\#
            "connection_disconnected":false,"reply_pending":\#(replyPending),"cancel_requested":false,"needs_user":false,\#
            "primary_state_label":"\#(label)","progress_text":null,"question_text":null,"result_text":null,"result_link":null,\#
            "result_link_interactive":false,"failure_reason":null,"content_expired":false,\#
            "content_expires_at":"2099-01-01T00:00:00Z","last_contact_at":"2026-10-16T09:00:00Z",\#
            "reporting_window_seconds":86400,"capabilities":{"reply":\#(reply),"cancel":\#(cancel)},"guarantee_tier":"best_effort",\#
            "exchange_state":"open","exchange_kind":"start","push_registration":"unregistered","agent_task_missing":false,\#
            "cancel_outcome":"none","blocked_reason":null,"artifacts_summary":[],"result_availability":null,\#
            "last_observed_at":"2026-10-16T09:00:00Z","observation_interval_seconds":60,"identifiers_expired":false,\#
            "manifest":null,"events":[],"commands":[],"created_at":"2026-10-16T08:00:00Z","revision":\#(revision)}
            """#)
    }

    static func error(_ kind: APIError.Kind, status: Int? = nil, reason: String? = nil, message: String = "server words") -> APIError {
        APIError(
            kind: kind, message: message, referenceID: "ref_9", statusCode: status,
            detail: reason.map { .object(["reason": .string($0)]) })
    }

    static let staleManifest = error(.rejected, status: 400, reason: "manifest_not_reserved")
    static let wrongPassword = error(.rejected, status: 403)
    static let offline = error(.network("offline"))
    static let relayOff = error(.notFound(resource: nil, id: nil), status: 404, message: APIError.agentRelayUnavailableMessage)
}

/// One send the fake saw, secrets included so a test can assert what left and what did not.
struct RecordedSend: Equatable {
    var token: String
    var password: String?
    var acknowledged: Bool
    var key: UUID
    var items: [AgentContextItemDTO]
}

/// A scripted relay that records every call. Replies, stops and checks are in `AgentRunActionsTests`.
final class FakeAgentRemote: HandoffRemote, AgentRunActionsRemote {
    private struct State {
        var connections: [AgentConnectionDTO] = []
        var manifests: [AgentManifestDTO] = []
        var sendResults: [Result<AgentRunDTO, APIError>] = []
        var previews: [[AgentContextItemDTO]] = []
        var sends: [RecordedSend] = []
        var runResults: [Result<AgentRunDTO, APIError>] = []
        var runCalls: [String] = []
        var runKeys: [UUID] = []
        var previewFailure: APIError?
    }

    private let state = Mutex(State())

    func script(connections: [AgentConnectionDTO]? = nil, manifests: [AgentManifestDTO]? = nil, sends: [Result<AgentRunDTO, APIError>]? = nil, runs: [Result<AgentRunDTO, APIError>]? = nil) {
        state.withLock {
            if let connections { $0.connections = connections }
            if let manifests { $0.manifests = manifests }
            if let sends { $0.sendResults = sends }
            if let runs { $0.runResults = runs }
        }
    }

    func failPreview(_ error: APIError?) { state.withLock { $0.previewFailure = error } }
    var previews: [[AgentContextItemDTO]] { state.withLock { $0.previews } }
    var sends: [RecordedSend] { state.withLock { $0.sends } }
    var runCalls: [String] { state.withLock { $0.runCalls } }
    var runKeys: [UUID] { state.withLock { $0.runKeys } }

    func agentConnections() async throws(APIError) -> [AgentConnectionDTO] { state.withLock { $0.connections } }

    func previewAgentHandoff(taskID: String, connectionID: String, includeDetails: Bool, supportingItems: [AgentContextItemDTO]) async throws(APIError) -> AgentManifestDTO {
        let result: Result<AgentManifestDTO, APIError> = state.withLock { state in
            state.previews.append(includeDetails ? supportingItems : [])
            if let failure = state.previewFailure { return .failure(failure) }
            return .success(state.manifests.count > 1 ? state.manifests.removeFirst() : state.manifests[0])
        }
        return try result.get()
    }

    func sendAgentHandoff(
        taskID: String, connectionID: String, includeDetails: Bool, supportingItems: [AgentContextItemDTO],
        manifestToken: String, currentPassword: String?, acknowledgeDuplicateRisk: Bool, idempotencyKey: UUID
    ) async throws(APIError) -> AgentRunDTO {
        let result: Result<AgentRunDTO, APIError> = state.withLock { state in
            state.sends.append(RecordedSend(token: manifestToken, password: currentPassword, acknowledged: acknowledgeDuplicateRisk, key: idempotencyKey, items: supportingItems))
            return state.sendResults.isEmpty ? .success(HandoffFixture.run()) : state.sendResults.removeFirst()
        }
        return try result.get()
    }

    private func answerRun(_ call: String, _ key: UUID) -> Result<AgentRunDTO, APIError> {
        state.withLock { state in
            state.runCalls.append(call)
            state.runKeys.append(key)
            return state.runResults.isEmpty ? .success(HandoffFixture.run()) : state.runResults.removeFirst()
        }
    }

    func replyToAgentRun(id: String, message: String, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
        try answerRun("reply:\(id):\(expectedRevision):\(message)", idempotencyKey).get()
    }

    func checkAgentRunDelivery(id: String, currentPassword: String?, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
        try answerRun("check:\(id):\(expectedRevision):\(currentPassword ?? "-")", idempotencyKey).get()
    }

    func cancelAgentRun(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
        try answerRun("stop:\(id)", idempotencyKey).get()
    }
}

/// The run ids `onSent` was given; the flow calls it on the main actor.
@MainActor
final class SentLog {
    var ids: [String] = []
}

@MainActor
@Suite("030 Hand-off flow")
struct HandoffFlowTests {
    private struct Rig {
        let flow: HandoffFlow
        let remote: FakeAgentRemote
        let availability: AgentAvailability
        let sent: SentLog
    }

    private func make(
        project: String? = "Admin", connections: [AgentConnectionDTO]? = nil, manifests: [AgentManifestDTO]? = nil
    ) -> Rig {
        let remote = FakeAgentRemote()
        remote.script(
            connections: connections ?? [
                HandoffFixture.connection(id: "conn_a", name: "Hermes", tier: "guaranteed", skills: ["Web research", "Email drafts"]),
                HandoffFixture.connection(id: "conn_b", name: "Claude"),
            ],
            manifests: manifests ?? [HandoffFixture.manifest()])
        let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in FakeAvailabilityRemote() })
        let sent = SentLog()
        let flow = HandoffFlow(
            taskServerID: "task_1", projectName: project, remote: remote, availability: availability,
            onSent: { run in sent.ids.append(run.id) })
        return Rig(flow: flow, remote: remote, availability: availability, sent: sent)
    }

    @Test("030_FR_014 030_FR_015 only ready agents are listed, the first is selected and previewed with the project item")
    func listsReadyAgentsAndPreviews() async {
        let rig = make(connections: [
            HandoffFixture.connection(id: "conn_x", name: "Offline", ready: false),
            HandoffFixture.connection(id: "conn_a", name: "Hermes", tier: "guaranteed", skills: ["Web research", "Email drafts"]),
            HandoffFixture.connection(id: "conn_b", name: "Claude"),
        ])
        await rig.flow.start()
        let names = rig.flow.agents.map(\.name)
        let detail = rig.flow.agents.first?.detail
        let second = rig.flow.agents.last?.detail
        #expect(names == ["Hermes", "Claude"])
        #expect(detail == "Web research, Email drafts · Guaranteed single start")
        #expect(second == "Best-effort single start")
        #expect(rig.flow.selectedID == "conn_a")
        #expect(rig.flow.phase == .ready)
        let items = rig.remote.previews
        #expect(items == [[AgentContextItemDTO(label: "Project", body: "Admin")]])
        #expect(rig.sent.ids.isEmpty)
    }

    @Test("030_FR_014 030_FR_015 a step with no project previews without a project item; none ready says so")
    func noProjectAndNoReadyAgent() async {
        let bare = make(project: nil)
        await bare.flow.start()
        #expect(bare.remote.previews == [[]])
        let none = make(connections: [HandoffFixture.connection(id: "conn_x", name: "Offline", ready: false)])
        await none.flow.start()
        #expect(none.flow.phase == .noReadyAgent)
        #expect(none.remote.previews.isEmpty)
    }

    @Test("030_FR_016 the password and acknowledgement gate Send only when the preview requires them")
    func fieldsOnlyWhenRequired() async {
        let plain = make()
        await plain.flow.start()
        #expect(!plain.flow.needsPassword)
        #expect(!plain.flow.needsAcknowledgement)
        #expect(plain.flow.canSend)
        let strict = make(manifests: [HandoffFixture.manifest(password: true, acknowledge: true)])
        await strict.flow.start()
        #expect(strict.flow.needsPassword)
        #expect(strict.flow.needsAcknowledgement)
        #expect(!strict.flow.canSend)
        strict.flow.password = "secret"
        #expect(!strict.flow.canSend)
        strict.flow.acknowledged = true
        #expect(strict.flow.canSend)
    }

    @Test("030_FR_017 030_SC_001 Send names the token, key, password and acknowledgement, adds the run, and clears the secret")
    func sendSucceeds() async {
        let rig = make(manifests: [HandoffFixture.manifest(token: "tok_1", password: true, acknowledge: true)])
        await rig.flow.start()
        rig.flow.password = "secret"
        rig.flow.acknowledged = true
        await rig.flow.send()
        let sends = rig.remote.sends
        #expect(sends.count == 1)
        #expect(sends.first?.token == "tok_1")
        #expect(sends.first?.password == "secret")
        #expect(sends.first?.acknowledged == true)
        #expect(sends.first?.items == [AgentContextItemDTO(label: "Project", body: "Admin")])
        #expect(rig.flow.phase == .sent(runID: "run_1"))
        #expect(rig.sent.ids == ["run_1"])
        #expect(rig.flow.password.isEmpty)
        #expect(!rig.flow.acknowledged)
    }

    @Test("030_FR_017 a password and acknowledgement the preview did not ask for are never sent")
    func unrequestedSecretsAreNotSent() async {
        let rig = make()
        await rig.flow.start()
        rig.flow.password = "stray"
        rig.flow.acknowledged = true
        await rig.flow.send()
        #expect(rig.remote.sends.first?.password == nil)
        #expect(rig.remote.sends.first?.acknowledged == false)
    }

    @Test("030_FR_017 Try again reuses the key after an uncertain outcome; a refused password gets a new key and an empty field")
    func keyLifecycle() async {
        let rig = make(manifests: [HandoffFixture.manifest(password: true)])
        rig.remote.script(sends: [.failure(HandoffFixture.offline), .failure(HandoffFixture.wrongPassword)])
        await rig.flow.start()
        rig.flow.password = "one"
        await rig.flow.send()
        #expect(rig.flow.phase == .failed(.offline))
        #expect(rig.flow.password.isEmpty)
        #expect(!rig.flow.canSend)
        rig.flow.password = "one"
        await rig.flow.tryAgain()
        #expect(rig.flow.phase == .failed(.wrongPassword))
        rig.flow.password = "two"
        await rig.flow.tryAgain()
        let keys = rig.remote.sends.map(\.key)
        #expect(keys.count == 3)
        #expect(keys[0] == keys[1])
        #expect(keys[2] != keys[1])
        #expect(rig.flow.phase == .sent(runID: "run_1"))
    }

    @Test("030_FR_017 a stale manifest (400 manifest_not_reserved) is previewed again and never resent")
    func staleManifestIsRePreviewed() async {
        let rig = make(manifests: [HandoffFixture.manifest(token: "old"), HandoffFixture.manifest(token: "new")])
        rig.remote.script(sends: [.failure(HandoffFixture.staleManifest)])
        await rig.flow.start()
        await rig.flow.send()
        #expect(rig.remote.sends.map(\.token) == ["old"])
        #expect(rig.remote.previews.count == 2)
        #expect(rig.flow.phase == .ready)
        #expect(rig.flow.manifest?.token == "new")
        await rig.flow.send()
        #expect(rig.remote.sends.map(\.token) == ["old", "new"])
        let keys = rig.remote.sends.map(\.key)
        #expect(keys[0] != keys[1])
    }

    @Test("030_FR_017 a mismatched token is previewed again, but a 409 never is")
    func onlyA400ReviewsTheManifest() async {
        let mismatch = make()
        mismatch.remote.script(sends: [.failure(HandoffFixture.error(.rejected, status: 400, reason: "manifest_token_mismatch"))])
        await mismatch.flow.start()
        await mismatch.flow.send()
        #expect(mismatch.remote.previews.count == 2)
        for status in [409, 410] {
            let rig = make()
            let error = status == 409 ? HandoffFixture.error(.staleRevision(resource: "Run", id: "run_1"), status: 409) : HandoffFixture.error(.rejected, status: 410)
            rig.remote.script(sends: [.failure(error)])
            await rig.flow.start()
            await rig.flow.send()
            #expect(rig.remote.previews.count == 1)
            #expect(rig.remote.sends.count == 1)
        }
    }

    @Test("030_FR_018 failures keep the sheet open in words and nothing is retried automatically")
    func failuresInWords() async {
        let cases: [(APIError, AgentActionFailure, String)] = [
            (HandoffFixture.wrongPassword, .wrongPassword, "That password isn't right."),
            (HandoffFixture.error(.rateLimited, status: 429), .rateLimited, "Too many attempts. Try again in a few minutes."),
            (HandoffFixture.offline, .offline, "Handing off needs a connection."),
            (HandoffFixture.error(.server, status: 500), .other(reference: "ref_9"), "Handing off isn't available right now."),
        ]
        for (error, failure, words) in cases {
            let rig = make()
            rig.remote.script(sends: [.failure(error)])
            await rig.flow.start()
            await rig.flow.send()
            #expect(rig.flow.phase == .failed(failure))
            #expect(failure.text(offline: AgentsCopy.handOffOffline) == words)
            #expect(rig.remote.sends.count == 1)
            #expect(rig.sent.ids.isEmpty)
        }
        #expect(AgentActionFailure.other(reference: "ref_9").reference == "Reference: ref_9")
    }

    @Test("030_FR_018 030_FR_002 a flag-off answer hides the relay by reading availability again")
    func relayOffHidesAgents() async {
        let flag = FakeAvailabilityRemote(flag: true)
        let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in flag })
        await availability.refresh()
        let remote = FakeAgentRemote()
        remote.script(connections: [HandoffFixture.connection(id: "conn_a", name: "Hermes")], manifests: [HandoffFixture.manifest()], sends: [.failure(HandoffFixture.relayOff)])
        let flow = HandoffFlow(taskServerID: "task_1", projectName: nil, remote: remote, availability: availability)
        await flow.start()
        flag.setFlag(false)
        await flow.send()
        #expect(flow.phase == .failed(.unavailable))
        #expect(!availability.relayEnabled)
    }

    @Test("030_FR_018 offline, nothing is requested and nothing is queued")
    func offlineRefuses() async {
        let flag = FakeAvailabilityRemote(me: .failure(HandoffFixture.offline))
        let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in flag })
        await availability.refresh()
        let remote = FakeAgentRemote()
        remote.script(connections: [HandoffFixture.connection(id: "conn_a", name: "Hermes")], manifests: [HandoffFixture.manifest()])
        let flow = HandoffFlow(taskServerID: "task_1", projectName: nil, remote: remote, availability: availability)
        await flow.start()
        #expect(flow.phase == .failed(.offline))
        #expect(remote.previews.isEmpty)
        #expect(remote.sends.isEmpty)
    }

    @Test("030_FR_015 choosing another agent previews it again and drops the earlier token, key and fields")
    func changingAgentPreviewsAgain() async {
        let rig = make(manifests: [HandoffFixture.manifest(token: "a", password: true), HandoffFixture.manifest(token: "b")])
        await rig.flow.start()
        rig.flow.password = "typed"
        await rig.flow.select("conn_b")
        #expect(rig.flow.manifest?.token == "b")
        #expect(rig.flow.password.isEmpty)
        #expect(!rig.flow.needsPassword)
        await rig.flow.send()
        #expect(rig.remote.sends.map(\.token) == ["b"])
    }
}
