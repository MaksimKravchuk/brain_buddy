#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAPI
    import BrainBuddyMacCore
    import Foundation
    import Synchronization
    import Testing

    @testable import BrainBuddyMac

    /// `AgentRunResponse` JSON with the fields the run section reads; the clock is fixed in 2026.
    private enum SectionFixture {
        static let now = Date(timeIntervalSince1970: 1_792_314_000)  // 2026-10-18T09:00:00Z

        static func run(
            id: String = "run_1", label: String, created: String = "2026-10-16T08:00:00Z", question: String? = nil,
            progress: String? = nil, result: String? = nil, link: String? = nil, failure: String? = nil,
            resultAvailability: String? = nil, reply: Bool = true, cancel: Bool = true, replyPending: Bool = false,
            expires: String = "2099-01-01T00:00:00Z", events: String = "[]"
        ) -> AgentRunDTO {
            func quoted(_ text: String?) -> String {
                text.map { String(data: try! JSONEncoder().encode($0), encoding: .utf8)! } ?? "null"
            }
            let json = #"""
                {"id":"\#(id)","task_id":"task_1","connection_id":"conn_a","agent_name":"Hermes","dispatch_state":"sent",\#
                "dispatch_error_code":null,"reported_state":"running","run_version":2,"stopped_reporting":false,\#
                "connection_disconnected":false,"reply_pending":\#(replyPending),"cancel_requested":false,"needs_user":false,\#
                "primary_state_label":\#(quoted(label)),"progress_text":\#(quoted(progress)),"question_text":\#(quoted(question)),\#
                "result_text":\#(quoted(result)),"result_link":\#(quoted(link)),"result_link_interactive":true,\#
                "failure_reason":\#(quoted(failure)),"content_expired":false,"content_expires_at":"\#(expires)",\#
                "last_contact_at":"2026-10-16T09:00:00Z","reporting_window_seconds":86400,\#
                "capabilities":{"reply":\#(reply),"cancel":\#(cancel)},"guarantee_tier":"guaranteed","exchange_state":"open",\#
                "exchange_kind":"start","push_registration":"unregistered","agent_task_missing":false,"cancel_outcome":"none",\#
                "blocked_reason":null,"artifacts_summary":[],"result_availability":\#(quoted(resultAvailability)),\#
                "last_observed_at":"2026-10-16T09:00:00Z","observation_interval_seconds":60,"identifiers_expired":false,\#
                "manifest":null,"events":\#(events),"commands":[],"created_at":"\#(created)","revision":4}
                """#
            return try! BrainBuddyAPI.makeDecoder().decode(AgentRunDTO.self, from: Data(json.utf8))
        }

        static func block(_ run: AgentRunDTO, relay: Bool = true) -> AgentRunBlock {
            AgentRunBlock(run, now: now, relay: relay)
        }

        static func time(_ iso: String) -> String {
            ISO8601DateFormatter().date(from: iso)!.formatted(date: .omitted, time: .shortened)
        }

        /// The Mac app's source, for the checks that guard how agent text is drawn.
        static func source() -> String {
            let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
                .deletingLastPathComponent().appendingPathComponent("Sources/BrainBuddyMac/Agents/AgentRunSection.swift")
            return try! String(contentsOf: url, encoding: .utf8)
        }
    }

    /// The run list of one step, plus the three action calls the fake relay records.
    private final class FakeSectionRemote: AgentRunSectionRemote {
        let relay = FakeAgentRemote()
        private let listed = Mutex<[AgentRunDTO]>([])

        func set(_ runs: [AgentRunDTO]) { listed.withLock { $0 = runs } }

        func agentRuns(taskID: String) async throws(APIError) -> [AgentRunDTO] { listed.withLock { $0 } }

        func replyToAgentRun(id: String, message: String, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
            try await relay.replyToAgentRun(id: id, message: message, expectedRevision: expectedRevision, idempotencyKey: idempotencyKey)
        }

        func checkAgentRunDelivery(id: String, currentPassword: String?, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
            try await relay.checkAgentRunDelivery(id: id, currentPassword: currentPassword, expectedRevision: expectedRevision, idempotencyKey: idempotencyKey)
        }

        func cancelAgentRun(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentRunDTO {
            try await relay.cancelAgentRun(id: id, idempotencyKey: idempotencyKey)
        }
    }

    @Suite("030 Agent run section")
    @MainActor
    struct AgentRunSectionTests {
        @MainActor
        private struct Rig {
            let model: AgentRunSectionModel
            let remote = FakeSectionRemote()
            let steps = FakeStepCommands()

            init(online: Bool = true) async {
                let me: Result<MeDTO, APIError>? = online ? nil : .failure(HandoffFixture.offline)
                let flag = FakeAvailabilityRemote(me: me)
                let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in flag })
                await availability.refresh()
                let (remote, steps) = (self.remote, self.steps)
                model = AgentRunSectionModel(
                    taskServerID: "task_1", projectID: "proj_1", remote: remote, availability: availability, steps: steps,
                    now: { SectionFixture.now })
            }
        }

        @Test("030_FR_020 030_FR_021 030_FR_023 each label shows its block and only the controls it offers")
        func eachLabelShowsItsBlock() {
            let needs = SectionFixture.block(SectionFixture.run(label: "Needs you", question: "Which colour?"))
            #expect(needs.question == "Which colour?")
            #expect((needs.reply, needs.stop, needs.markDone, needs.handOffAgain) == (true, true, false, false))

            let running = SectionFixture.block(SectionFixture.run(label: "Running", progress: "Searching"))
            #expect(running.detail == "Searching")
            #expect(running.contact == "Last contact \(SectionFixture.time("2026-10-16T09:00:00Z"))")
            #expect((running.reply, running.stop, running.handOffAgain) == (false, true, false))

            let queued = SectionFixture.block(SectionFixture.run(label: "Queued"))
            #expect(queued.detail == AgentsCopy.queued)
            #expect(queued.stop)

            let cancelling = SectionFixture.block(SectionFixture.run(label: "Cancellation requested"))
            #expect(cancelling.label == "Cancellation requested")
            #expect(!cancelling.stop && !cancelling.reply && !cancelling.check && !cancelling.handOffAgain)

            let complete = SectionFixture.block(SectionFixture.run(label: "Agent reported complete", result: "Booked"))
            #expect(complete.label == "\(AgentsCopy.reportedComplete) · \(SectionFixture.time("2026-10-16T09:00:00Z"))")
            #expect(complete.showsResult && complete.result == "Booked")
            #expect((complete.markDone, complete.handOffAgain, complete.stop) == (true, true, false))

            let tooLarge = SectionFixture.block(
                SectionFixture.run(label: "Agent reported complete", result: "partial", resultAvailability: "too_large"))
            #expect(tooLarge.result == AgentsCopy.resultTooLarge)

            let failed = SectionFixture.block(SectionFixture.run(label: "Failed", failure: "Out of stock"))
            #expect(failed.detail == "Out of stock" && failed.tone == .danger && failed.handOffAgain)

            let stopped = SectionFixture.block(SectionFixture.run(label: "Stopped reporting"))
            #expect(stopped.label == "Stopped reporting · last contact 2 days ago")
            #expect(stopped.tone == .warning && stopped.stop && stopped.handOffAgain)

            for other in ["Cancelled", "Agent no longer reports this run", "Connection disconnected"] {
                let block = SectionFixture.block(SectionFixture.run(label: other))
                #expect(block.label == other)
                #expect((block.handOffAgain, block.stop, block.reply) == (true, false, false))
            }

            let unconfirmed = SectionFixture.block(SectionFixture.run(label: "Delivery unconfirmed"))
            #expect(unconfirmed.check && !unconfirmed.reply && !unconfirmed.markDone)
        }

        @Test("030_FR_020 030_FR_023 030_FR_002 withdrawn controls are absent, and Hand off again follows the flag")
        func withdrawnControlsAreAbsent() {
            let needs = SectionFixture.block(SectionFixture.run(label: "Needs you", question: "?", reply: false, cancel: false))
            #expect(!needs.reply && !needs.stop)
            let running = SectionFixture.block(SectionFixture.run(label: "Running", cancel: false))
            #expect(!running.stop)
            let flagOff = SectionFixture.block(SectionFixture.run(label: "Failed", failure: "x"), relay: false)
            #expect(!flagOff.handOffAgain, "030-FR-002 flag off: no Hand off again")
            let done = SectionFixture.block(SectionFixture.run(label: "Agent reported complete", result: "ok"), relay: false)
            #expect(done.markDone && !done.handOffAgain)
        }

        @Test("030_FR_021 030_FR_028 a result link is carried as text and the view draws no link")
        func resultLinkIsNotALink() {
            let run = SectionFixture.run(label: "Agent reported complete", result: "ok", link: "https://evil.example/pay")
            #expect(run.resultLinkInteractive, "even when the server calls it interactive")
            #expect(SectionFixture.block(run).resultLink == "https://evil.example/pay")
            let source = SectionFixture.source()
            for forbidden in ["Link(", "openURL", "NSWorkspace", "AttributedString", "LocalizedStringKey", "Text(\"\\("] {
                #expect(!source.contains(forbidden), "\(forbidden)")
            }
        }

        @Test("030_FR_028 Markdown and HTML in agent text show literally")
        func agentTextIsLiteral() {
            let hostile = "**bold** <b>x</b> [a](https://x.example) <script>alert(1)</script>"
            let block = SectionFixture.block(SectionFixture.run(label: "Needs you", question: hostile, progress: hostile))
            #expect(block.question == hostile)
            let done = SectionFixture.block(SectionFixture.run(label: "Agent reported complete", result: hostile))
            #expect(done.result == hostile)
            let source = SectionFixture.source()
            #expect(source.contains("Text(verbatim: text)"), "plain() draws agent text")
            #expect(!source.contains("Text(text)") && !source.contains("Text(block."))
        }

        @Test("030_FR_027 expired content never renders and no control is offered")
        func expiredContentNeverRenders() {
            let past = SectionFixture.run(
                label: "Agent reported complete", question: "Q", progress: "P", result: "secret result", link: "https://a.example",
                failure: "F", expires: "2026-10-17T00:00:00Z")
            let block = SectionFixture.block(past)
            #expect(block.isExpired && block.label == AgentsCopy.expired)
            #expect(block.question == nil && block.detail == nil && block.result == nil && block.resultLink == nil)
            #expect(!block.showsResult && !block.reply && !block.stop && !block.check && !block.markDone && !block.handOffAgain)
            let labelled = SectionFixture.block(SectionFixture.run(label: "Content expired under retention policy", result: "x"))
            #expect(labelled.isExpired && labelled.result == nil)
            let live = SectionFixture.block(SectionFixture.run(label: "Agent reported complete", result: "kept"))
            #expect(!live.isExpired && live.result == "kept")
        }

        @Test("030_FR_019 the timeline starts with Sent and the start guarantee, then the events, and names a continued task")
        func timeline() {
            let events = #"""
                [{"id":"e1","type":"running","run_version":2,"received_at":"2026-10-16T08:10:00Z","summary":"s","trigger":"push","kind":"observation"},
                {"id":"e2","type":"blocked","run_version":3,"received_at":"2026-10-16T08:20:00Z","summary":null,"trigger":"push","kind":"task_succession","previous_agent_task_id":"a","new_agent_task_id":"b"}]
                """#
            let rows = AgentTimelineRow.rows(SectionFixture.run(label: "Running", events: events))
            #expect(rows.map(\.word) == ["Sent", "Running", AgentsCopy.succession])
            #expect(rows[0].meta == "\(SectionFixture.time("2026-10-16T08:00:00Z")) · \(AgentsCopy.guaranteed)")
            #expect(rows[1].meta == SectionFixture.time("2026-10-16T08:10:00Z"))
        }

        @Test("030_FR_019 earlier runs list under the latest and choosing one shows it, choosing it again goes back")
        func earlierRuns() async {
            let rig = await Rig()
            rig.remote.set([
                SectionFixture.run(id: "run_old", label: "Failed", created: "2026-10-01T08:00:00Z"),
                SectionFixture.run(id: "run_new", label: "Running", created: "2026-10-16T08:00:00Z"),
            ])
            await rig.model.load()
            #expect(rig.model.shown?.id == "run_new")
            #expect(rig.model.runs.dropFirst().map(\.id) == ["run_old"])
            rig.model.choose(rig.model.runs[1])
            #expect(rig.model.shown?.id == "run_old")
            rig.model.choose(rig.model.runs[1])
            #expect(rig.model.shown?.id == "run_new")
        }

        @Test("030_FR_020 030_FR_025 Reply sends once online and clears the draft, and offline sends nothing")
        func replyOnlineAndOffline() async {
            let online = await Rig()
            online.remote.set([SectionFixture.run(label: "Needs you", question: "Which?")])
            await online.model.load()
            online.model.answer = "  The blue one "
            await online.model.sendReply()
            #expect(online.remote.relay.runCalls == ["reply:run_1:4:The blue one"])
            #expect(online.model.answer.isEmpty)

            let offline = await Rig(online: false)
            offline.remote.set([SectionFixture.run(label: "Needs you", question: "Which?")])
            await offline.model.load()
            offline.model.answer = "Blue"
            await offline.model.sendReply()
            #expect(offline.remote.relay.runCalls.isEmpty, "nothing is queued offline")
            #expect(offline.model.answer == "Blue")
            #expect(offline.model.actions.phase == .failed(.offline))
        }

        @Test("030_FR_023 Check again asks for the password only after the server refused it for want of one")
        func checkAgainPassword() async {
            let rig = await Rig()
            rig.remote.set([SectionFixture.run(label: "Delivery unconfirmed")])
            rig.remote.relay.script(runs: [.failure(HandoffFixture.wrongPassword), .success(HandoffFixture.run())])
            await rig.model.load()
            #expect(!rig.model.asksPassword)
            await rig.model.checkAgain()
            #expect(rig.model.asksPassword)
            rig.model.password = "pw"
            await rig.model.checkAgain()
            #expect(rig.remote.relay.runCalls == ["check:run_1:4:-", "check:run_1:4:pw"])
            #expect(!rig.model.asksPassword && rig.model.password.isEmpty)
        }

        @Test("030_FR_022 030_FR_012 the step stays until Mark step done, which completes it and makes the next step")
        func markStepDone() async {
            let rig = await Rig()
            rig.remote.set([SectionFixture.run(label: "Agent reported complete", result: "ok")])
            await rig.model.load()
            #expect(rig.steps.calls.isEmpty, "showing a result changes no step")
            await rig.model.actions.markStepDone(
                taskServerID: rig.model.taskServerID, projectID: rig.model.projectID, nextStep: "Book the van")
            #expect(rig.steps.calls == ["complete:task_1", "create:Book the van@proj_1"])
        }

        @Test("030_FR_040 keyboard order follows the screen and the controls carry their visible names")
        func keyboardOrderAndNames() {
            let source = SectionFixture.source()
            func position(_ text: String) -> Int { source.range(of: text)!.lowerBound.utf16Offset(in: source) }
            let reply = ["AgentsCopy.yourAnswer", "Button(AgentsCopy.reply)", "Button(AgentsCopy.stopRun)"]
            #expect(reply.map(position) == reply.map(position).sorted(), "answer, Reply, Stop run")
            let tail = String(source[source.range(of: "func resultBlock")!.lowerBound...])
            let result = ["AgentsCopy.makeNextStep", "Button(AgentsCopy.markDone)", "AgentsCopy.handOffAgain"]
            let offsets = result.map { tail.range(of: $0)!.lowerBound.utf16Offset(in: tail) }
            #expect(offsets == offsets.sorted(), "next step, Mark step done, Hand off again")
            #expect(source.contains(".accessibilityLabel(name)"), "fields are named for what they are")
            #expect(source.contains(".accessibilityLabel(block.label)"))
            #expect([AgentsCopy.reply, AgentsCopy.stopRun, AgentsCopy.checkAgain, AgentsCopy.markDone] == ["Reply", "Stop run", "Check again", "Mark step done"])
        }
    }
#endif
