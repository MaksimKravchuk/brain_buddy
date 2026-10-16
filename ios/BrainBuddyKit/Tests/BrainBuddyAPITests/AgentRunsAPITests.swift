import Foundation
import Testing

@testable import BrainBuddyAPI

/// Fixtures are `AgentRunResponse`, `AgentManifestResponse`, `AgentRunSummaryResponse` field for field
/// (`backend/app/schemas/agents.py`).
private enum RunFixture {
    static let observation =
        #"{"id":"evt_1","type":"running","run_version":2,"received_at":"2026-10-16T08:30:00.250000Z","summary":"Reading sources","trigger":"schedule","kind":"observation","previous_agent_task_id":null,"new_agent_task_id":null}"#
    static let succession =
        #"{"id":"evt_2","type":"running","run_version":3,"received_at":"2026-10-16T08:45:00Z","summary":null,"trigger":"push","kind":"task_succession","previous_agent_task_id":"agent_task_old","new_agent_task_id":"agent_task_new"}"#
    static let replyCommand =
        #"{"id":"cmd_1","kind":"reply","body":"Use the 2025 figures","delivery":"confirmed","outcome_code":"accepted","created_at":"2026-10-16T08:50:00Z","confirmed_at":"2026-10-16T08:50:02Z"}"#

    static func run(
        label: String = "Running", revision: Int = 4, resultText: String? = nil, resultLink: String? = nil,
        resultAvailability: String? = nil, contentExpired: Bool = false, events: String = "[]", commands: String = "[]"
    ) -> String {
        let text = resultText.map { "\"\($0)\"" } ?? "null"
        let link = resultLink.map { "\"\($0)\"" } ?? "null"
        let availability = resultAvailability.map { "\"\($0)\"" } ?? "null"
        return #"""
            {"id":"agent_run_1","task_id":"task_1a2b3c4d5e6f","connection_id":"agent_conn_1","agent_name":"Research agent",\#
            "dispatch_state":"sent","dispatch_error_code":null,"reported_state":"running","run_version":2,\#
            "stopped_reporting":false,"connection_disconnected":false,"reply_pending":false,"cancel_requested":false,\#
            "needs_user":false,"primary_state_label":"\#(label)","progress_text":"Reading sources","question_text":null,\#
            "result_text":\#(text),"result_link":\#(link),"result_link_interactive":false,"failure_reason":null,\#
            "content_expired":\#(contentExpired),"content_expires_at":"2026-11-15T09:00:00Z",\#
            "last_contact_at":"2026-10-16T09:00:00Z","reporting_window_seconds":86400,\#
            "capabilities":{"reply":true,"cancel":true},"guarantee_tier":"best_effort","exchange_state":"open",\#
            "exchange_kind":"start","push_registration":"unregistered","agent_task_missing":false,"cancel_outcome":"none",\#
            "blocked_reason":null,"artifacts_summary":[],"result_availability":\#(availability),\#
            "last_observed_at":"2026-10-16T09:00:00Z","observation_interval_seconds":60,"identifiers_expired":false,\#
            "manifest":null,"events":\#(events),"commands":\#(commands),"created_at":"2026-10-16T08:00:00Z",\#
            "revision":\#(revision)}
            """#
    }

    static func summary(task: String, label: String = "Running") -> String {
        #"{"id":"agent_run_\#(task)","task_id":"\#(task)","agent_name":"Research agent","primary_state_label":"\#(label)","needs_user":false,"stopped_reporting":false,"last_contact_at":"2026-10-16T09:00:00Z","guarantee_tier":"best_effort","cancel_outcome":"none","agent_task_missing":false}"#
    }

    static let manifest =
        #"{"token":"\#(String(repeating: "a", count: 64))","run_id":"agent_run_1","task_id":"task_1a2b3c4d5e6f","connection_id":"agent_conn_1","agent_name":"Research agent","title":"Renew passport","details":"Photos first","supporting_items":[{"label":"Passport","body":"Expires 2031"}],"message_id":"msg_1","correlation_id":"corr_1","destination_interface":"https://agent.example.org/a2a","protocol_version":"0.3.0","guarantee_tier":"best_effort","tier_disclosure":"Updates may be delayed.","tier_disclosure_url":"https://brainbuddy.example/tiers","acknowledgement_required":true,"cancellation_disclosure":"Stopping asks the agent to stop.","push_callback":null,"external_copy_notice":"Text you send leaves BrainBuddy.","reauthentication_required":true,"parts_preview":["Renew passport"]}"#
}

@Suite("030 agent runs API")
struct AgentRunsAPITests {
    private func client(_ steps: [ScriptedTransport.Step]) -> (BrainBuddyAPIClient, ScriptedTransport) {
        let transport = ScriptedTransport(steps)
        return (Fixture.client(transport, store: Fixture.signedInStore()), transport)
    }

    private func decodeRun(_ json: String) throws -> AgentRunDTO {
        try BrainBuddyAPI.makeDecoder().decode(AgentRunDTO.self, from: Data(json.utf8))
    }

    private func taskIDs(in request: HTTPRequest) -> [String] {
        URLComponents(url: request.url, resolvingAgainstBaseURL: false)?.queryItems?
            .compactMap { $0.name == "task_id" ? $0.value : nil } ?? []
    }

    // MARK: decoding

    @Test("030-FR-023 every server label decodes to its own case and a newer label reads as unknown")
    func primaryStateLabels_030_FR_023() throws {
        let cases: [(String, AgentPrimaryState)] = [
            ("Not sent", .notSent), ("Queued", .queued), ("Sent", .sent),
            ("Delivery unconfirmed", .deliveryUnconfirmed), ("Accepted", .accepted), ("Running", .running),
            ("Needs you", .needsYou), ("Cancellation requested", .cancellationRequested),
            ("Agent reported complete", .agentReportedComplete), ("Failed", .failed), ("Cancelled", .cancelled),
            ("Stopped reporting", .stoppedReporting), ("Agent no longer reports this run", .agentNoLongerReportsThisRun),
            ("Connection disconnected", .connectionDisconnected),
            ("Content expired under retention policy", .contentExpired),
        ]
        #expect(cases.count == 15)
        for (label, state) in cases {
            let run = try decodeRun(RunFixture.run(label: label))
            #expect(run.primaryState == state, "\(label)")
        }
        let newer = try decodeRun(RunFixture.run(label: "Archived by the agent"))
        #expect(newer.primaryState == .unknown("Archived by the agent"))
    }

    @Test("030-FR-019 a run decodes its timeline, a reply command, controls and the observation interval")
    func decodesRunTimeline_030_FR_019() throws {
        let run = try decodeRun(
            RunFixture.run(
                label: "Needs you", events: "[\(RunFixture.observation)]", commands: "[\(RunFixture.replyCommand)]"))
        #expect(run.id == "agent_run_1")
        #expect(run.taskID == "task_1a2b3c4d5e6f")
        #expect(run.agentName == "Research agent")
        #expect(run.primaryState == .needsYou)
        #expect(run.controls == AgentControlsDTO(reply: true, cancel: true))
        #expect(run.observationIntervalSeconds == 60)
        #expect(run.exchangeState == "open")
        #expect(run.cancelOutcome == "none")
        #expect(run.revision == 4)
        #expect(run.contentExpiresAt == Fixture.utc(2026, 11, 15, 9))
        #expect(run.events.map(\.kind) == ["observation"])
        #expect(run.events.first?.summary == "Reading sources")
        #expect(run.commands.map(\.delivery) == ["confirmed"])
        #expect(run.commands.first?.body == "Use the 2025 figures")
        #expect(run.commands.first?.outcomeCode == "accepted")
    }

    @Test("030-FR-019 a task succession event names the previous and the new agent task")
    func decodesSuccessionEvent_030_FR_019() throws {
        let run = try decodeRun(RunFixture.run(events: "[\(RunFixture.observation),\(RunFixture.succession)]"))
        let succession = try #require(run.events.last)
        #expect(succession.kind == "task_succession")
        #expect(succession.previousAgentTaskID == "agent_task_old")
        #expect(succession.newAgentTaskID == "agent_task_new")
        #expect(succession.summary == nil)
        #expect(succession.receivedAt == Fixture.utc(2026, 10, 16, 8, 45))
    }

    @Test("030-FR-019 a result link and a too-large result decode as the server sent them")
    func decodesResultLinkAndTooLarge_030_FR_019() throws {
        let linked = try decodeRun(
            RunFixture.run(
                label: "Agent reported complete", resultText: "Done.", resultLink: "https://agent.example.org/r/1",
                resultAvailability: "available"))
        #expect(linked.primaryState == .agentReportedComplete)
        #expect(linked.resultText == "Done.")
        #expect(linked.resultLink == "https://agent.example.org/r/1")
        #expect(linked.resultAvailability == "available")
        let tooLarge = try decodeRun(
            RunFixture.run(label: "Agent reported complete", resultAvailability: "too_large"))
        #expect(tooLarge.resultAvailability == "too_large")
        #expect(tooLarge.resultText == nil)
        #expect(tooLarge.resultLink == nil)
    }

    @Test("030-FR-023 an expired run decodes with its content gone and its last contact kept")
    func decodesExpiredRun_030_FR_023() throws {
        let run = try decodeRun(RunFixture.run(label: "Content expired under retention policy", contentExpired: true))
        #expect(run.primaryState == .contentExpired)
        #expect(run.contentExpired)
        #expect(run.resultText == nil)
        #expect(run.lastContactAt == Fixture.utc(2026, 10, 16, 9))
    }

    @Test("030-FR-005 a summary decodes its label and flags, and stays sparse by task id")
    func decodesSummary_030_FR_005() throws {
        let json = #"{"task_1":\#(RunFixture.summary(task: "task_1", label: "Queued"))}"#
        let summaries = try BrainBuddyAPI.makeDecoder().decode(
            [String: AgentRunSummaryDTO].self, from: Data(json.utf8))
        #expect(Set(summaries.keys) == ["task_1"])
        #expect(summaries["task_1"]?.primaryState == .queued)
        #expect(summaries["task_1"]?.taskID == "task_1")
        #expect(summaries["task_1"]?.agentTaskMissing == false)
    }

    // MARK: hand-off

    @Test("030-FR-017 preview posts the connection, details and items with no key and decodes the manifest")
    func previewHandoffRequest_030_FR_017() async throws {
        let (api, transport) = client([Fixture.json(200, RunFixture.manifest)])
        let manifest = try await api.previewAgentHandoff(
            taskID: "task_1a2b3c4d5e6f", connectionID: "agent_conn_1", includeDetails: true,
            supportingItems: [AgentContextItemDTO(label: "Passport", body: "Expires 2031")])
        let request = try #require(transport.lastRequest)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/tasks/task_1a2b3c4d5e6f/agent-runs/preview")
        #expect(request.header("Idempotency-Key") == nil)
        #expect(
            request.bodyText
                == #"{"connection_id":"agent_conn_1","include_details":true,"supporting_items":[{"body":"Expires 2031","label":"Passport"}]}"#
        )
        #expect(manifest.token == String(repeating: "a", count: 64))
        #expect(manifest.runID == "agent_run_1")
        #expect(manifest.details == "Photos first")
        #expect(manifest.supportingItems == [AgentContextItemDTO(label: "Passport", body: "Expires 2031")])
        #expect(manifest.guaranteeTier == .bestEffort)
        #expect(manifest.acknowledgementRequired)
        #expect(manifest.reauthenticationRequired)
        #expect(manifest.externalCopyNotice == "Text you send leaves BrainBuddy.")
        #expect(!String(describing: manifest).contains(String(repeating: "a", count: 64)))
    }

    @Test("030-FR-017 send posts the reviewed token and the acknowledgement with the key and returns the run")
    func sendHandoffRequest_030_FR_017() async throws {
        let (api, transport) = client([Fixture.json(201, RunFixture.run(label: "Queued"))])
        let run = try await api.sendAgentHandoff(
            taskID: "task_1a2b3c4d5e6f", connectionID: "agent_conn_1", manifestToken: String(repeating: "a", count: 64),
            acknowledgeDuplicateRisk: true, idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(run.primaryState == .queued)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/tasks/task_1a2b3c4d5e6f/agent-runs")
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
        #expect(
            request.bodyText
                == #"{"acknowledge_duplicate_risk":true,"connection_id":"agent_conn_1","include_details":true,"manifest_token":"\#(String(repeating: "a", count: 64))","supporting_items":[]}"#
        )
    }

    @Test("030-FR-017 a stale manifest is a 400 that needs review, and no other failure does")
    func needsManifestReview_030_FR_017() async {
        let (api, _) = client([
            Fixture.error(400, "Review it again.", detail: #"{"reason":"manifest_not_reserved"}"#),
            Fixture.error(400, "Changed.", detail: #"{"reason":"manifest_token_mismatch"}"#),
            Fixture.error(400, "Acknowledge.", detail: #"{"reason":"acknowledgement_required"}"#),
            Fixture.error(409, "Changed.", detail: #"{"reason":"manifest_token_mismatch"}"#),
            Fixture.error(400, "Plain refusal."),
        ])
        func send() async -> APIError? {
            await expectAPIError {
                _ = try await api.sendAgentHandoff(
                    taskID: "task_1a2b3c4d5e6f", connectionID: "agent_conn_1",
                    manifestToken: String(repeating: "a", count: 64), idempotencyKey: Fixture.key)
            }
        }
        var errors: [APIError?] = []
        for _ in 0..<5 { errors.append(await send()) }
        #expect(errors.map { $0?.needsManifestReview } == [true, true, false, false, false])
        #expect(errors.allSatisfy { $0?.kind == .rejected || $0?.statusCode == 409 })
        #expect(errors.first??.reason == "manifest_not_reserved")
    }

    // MARK: reads

    @Test("030-FR-019 the step's runs and one run are read with GET and no body or key")
    func readRunsRequests_030_FR_019() async throws {
        let (api, transport) = client([
            Fixture.json(200, "[\(RunFixture.run(label: "Failed"))]"), Fixture.json(200, RunFixture.run(label: "Sent")),
        ])
        let runs = try await api.agentRuns(taskID: "task_1a2b3c4d5e6f")
        let one = try await api.agentRun(id: "agent_run_1")
        let requests = transport.requests
        #expect(runs.map(\.primaryState) == [.failed])
        #expect(one.primaryState == .sent)
        #expect(requests.map(\.method) == [.get, .get])
        #expect(requests.map(\.url.path) == ["/api/tasks/task_1a2b3c4d5e6f/agent-runs", "/api/agent-runs/agent_run_1"])
        #expect(requests.allSatisfy { $0.body == nil && $0.header("Idempotency-Key") == nil })
    }

    // MARK: reply, check again, stop

    @Test("030-FR-020 reply posts the message and the revision the person saw, with the key")
    func replyRequest_030_FR_020() async throws {
        let (api, transport) = client([Fixture.json(200, RunFixture.run(label: "Running", revision: 5))])
        let run = try await api.replyToAgentRun(
            id: "agent_run_1", message: "Use the 2025 figures", expectedRevision: 4, idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(run.revision == 5)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/agent-runs/agent_run_1/reply")
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
        #expect(request.bodyText == #"{"expected_revision":4,"message":"Use the 2025 figures"}"#)
    }

    @Test("030-FR-020 check again sends the password only when the server needs it")
    func checkDeliveryRequest_030_FR_020() async throws {
        let (api, transport) = client([
            Fixture.json(200, RunFixture.run(label: "Sent")), Fixture.json(200, RunFixture.run(label: "Sent")),
        ])
        _ = try await api.checkAgentRunDelivery(
            id: "agent_run_1", currentPassword: nil, expectedRevision: 4, idempotencyKey: Fixture.key)
        _ = try await api.checkAgentRunDelivery(
            id: "agent_run_1", currentPassword: "hunter2-pw", expectedRevision: 4, idempotencyKey: Fixture.key)
        let requests = transport.requests
        #expect(requests.map(\.url.path) == Array(repeating: "/api/agent-runs/agent_run_1/check-delivery", count: 2))
        #expect(requests.allSatisfy { $0.method == .post && $0.header("Idempotency-Key") == Fixture.keyHeader })
        #expect(requests[0].bodyText == #"{"expected_revision":4}"#)
        #expect(requests[1].bodyText == #"{"current_password":"hunter2-pw","expected_revision":4}"#)
    }

    @Test("030-FR-020 stop posts with the key and no body")
    func cancelRequest_030_FR_020() async throws {
        let (api, transport) = client([Fixture.json(200, RunFixture.run(label: "Cancellation requested"))])
        let run = try await api.cancelAgentRun(id: "agent_run_1", idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(run.primaryState == .cancellationRequested)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/agent-runs/agent_run_1/cancel")
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
        #expect(request.body == nil)
    }

    @Test("030-FR-042 bodies carrying a password never print it")
    func passwordBodiesAreRedacted_030_FR_042() {
        let secret = "hunter2-pw"
        let bodies: [any RedactedRequestBody] = [
            AgentHandoffConfirmBody(
                connectionID: "agent_conn_1", includeDetails: true, supportingItems: [],
                manifestToken: String(repeating: "a", count: 64), currentPassword: secret,
                acknowledgeDuplicateRisk: false),
            AgentCheckDeliveryBody(currentPassword: secret, expectedRevision: 1),
        ]
        for body in bodies {
            var dumped = ""
            dump(body, to: &dumped)
            for text in [String(describing: body), String(reflecting: body), body.debugDescription, dumped] {
                #expect(!text.contains(secret), "\(text)")
            }
        }
    }

    // MARK: summaries in 200-id batches

    @Test("030-FR-005 no task ids send no summary request")
    func emptySummariesMakeNoRequest_030_FR_005() async throws {
        let (api, transport) = client([])
        let summaries = try await api.agentRunSummaries(taskIDs: [])
        #expect(summaries.isEmpty)
        #expect(transport.requests.isEmpty)
    }

    @Test("030-FR-005 200 task ids send one summary request naming all of them")
    func oneBatchOf200_030_FR_005() async throws {
        let ids = (1...200).map { "task_\($0)" }
        let (api, transport) = client([Fixture.json(200, #"{"task_7":\#(RunFixture.summary(task: "task_7"))}"#)])
        let summaries = try await api.agentRunSummaries(taskIDs: ids)
        let requests = transport.requests
        #expect(requests.count == 1)
        #expect(requests.first?.url.path == "/api/agent-run-summaries")
        #expect(requests.first.map(taskIDs(in:)) == ids)
        #expect(Set(summaries.keys) == ["task_7"])
    }

    @Test("030-SC-007 030-FR-005 450 task ids send three requests of 200, 200 and 50 in order and merge sparse maps")
    func threeBatchesOf450_030_FR_005() async throws {
        let ids = (1...450).map { "task_\($0)" }
        let (api, transport) = client([
            Fixture.json(200, #"{"task_1":\#(RunFixture.summary(task: "task_1"))}"#),
            Fixture.json(200, "{}"),
            Fixture.json(200, #"{"task_450":\#(RunFixture.summary(task: "task_450", label: "Needs you"))}"#),
        ])
        let summaries = try await api.agentRunSummaries(taskIDs: ids)
        let requests = transport.requests
        #expect(requests.count == 3)
        #expect(requests.map { taskIDs(in: $0).count } == [200, 200, 50])
        #expect(requests.flatMap { taskIDs(in: $0) } == ids)
        #expect(Set(summaries.keys) == ["task_1", "task_450"])
        #expect(summaries["task_450"]?.primaryState == .needsYou)
    }

    @Test("030-FR-005 the first failing batch throws its error and no later batch is sent")
    func firstFailingBatchThrows_030_FR_005() async {
        let ids = (1...450).map { "task_\($0)" }
        let (api, transport) = client([
            Fixture.json(200, "{}"),
            Fixture.error(500, "Boom"),
            Fixture.json(200, "{}"),
        ])
        let error = await expectAPIError { _ = try await api.agentRunSummaries(taskIDs: ids) }
        #expect(error?.statusCode == 500)
        #expect(transport.requests.count == 2)
    }
}
