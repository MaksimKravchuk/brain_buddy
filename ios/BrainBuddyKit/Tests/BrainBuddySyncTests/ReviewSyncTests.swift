import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Testing

@testable import BrainBuddySync

/// The weekly review through the sync engine against `FakeBrainBuddyServer`
/// (contracts/ios-commands.md §4 – §5; tasks.md T055, T089, T108, T135, T151).
@Suite("Review sync (spec 020)")
struct ReviewSyncTests {
    static let day: TimeInterval = 86_400

    static func uuid(_ n: Int) -> UUID { UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", n))! }
    static func form(_ n: Int) -> FormulationID { FormulationID.make(uuid(n)) }
    static func decision(_ n: Int) -> DecisionID { DecisionID.make(uuid(1_000 + n)) }
    static func session(_ n: Int) -> ReviewSessionID { ReviewSessionID.make(uuid(2_000 + n)) }
    static func progress(_ n: Int) -> ProgressID { ProgressID.make(uuid(3_000 + n)) }
    static func bulk(_ n: Int) -> BulkID { BulkID.make(uuid(4_000 + n)) }

    /// A server with the flag on and one signed-in, activated device.
    private func activated() async throws -> (SyncHarness, Device) {
        let harness = SyncHarness()
        harness.server.setWeeklyReview(email: SyncHarness.email, enabled: true)
        let phone = await harness.device()
        try await phone.signIn()
        try await phone.review(.review(.acknowledgeExplainer(timeZone: "UTC")))
        await phone.sync()
        return (harness, phone)
    }

    /// Creates `title` in Next on `device` with formulation `form` and syncs.
    private func nextTask(_ title: String, id: TaskID, form: Int, on device: Device) async throws {
        try await device.review(.createTask(.init(taskID: id, title: title, list: .next, newFormulationID: Self.form(form))))
        await device.sync()
    }

    /// The server applies the matching request and its answer is lost; the
    /// device then stays offline for the rest of the cycle, so its retry
    /// comes only with the next sync (after the test moved the clock).
    private func loseResponse(on device: Device, matching: @escaping FakeServerTransport.Matcher) async throws {
        device.transport.inject(.dropResponse, matching: matching)
        device.transport.inject(.offline, times: 1_000)
        await device.sync()
        device.transport.clearFaults()
        let dropped = device.transport.exchanges.filter { $0.droppedResponse != nil }
        #expect(dropped.count == 1, "the server applied the request and its answer was lost")
        #expect((200..<300).contains(dropped.first?.droppedResponse?.statusCode ?? 0))
        #expect(try await device.document().outbox.isEmpty == false, "the outcome is unknown: kept with its key")
    }

    private func decide(
        _ type: DecisionType, _ task: TaskID, _ n: Int, formulation: FormulationID? = nil, title: String? = nil,
        session: ReviewSessionID? = nil, newFormulation: FormulationID? = nil
    ) -> GTDCommand {
        .decideTask(
            .init(
                decisionID: Self.decision(n), taskID: task, type: type, formulationID: formulation,
                newFormulationID: newFormulation, title: title, sessionID: session
            )
        )
    }

    // MARK: - Decisions (T055)

    @Test("020-FR-011 a decision on a formulation that changed elsewhere is set aside naming the current list, with its Ref")
    func setAsideNamesCurrentList() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        let tablet = await harness.device()
        try await tablet.signIn()
        let onTablet = try #require(try await tablet.current().task(titled: "Renovate the bathroom"))
        try await tablet.review(
            .updateTask(.init(taskID: onTablet.id, changes: TaskChanges(title: .set("Call the plumber")), newFormulationID: Self.form(2)))
        )
        await tablet.sync()

        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        await phone.sync()
        let document = try await phone.document()
        #expect(document.outbox.isEmpty)
        let issue = try #require(document.issues.first)
        #expect(document.issues.count == 1)
        #expect(issue.message == ReviewCopy.decisionNotSaved(.someday, title: "Call the plumber", list: .next))
        #expect(issue.message.contains("Next actions"))
        #expect(issue.referenceID != nil)
        #expect(harness.snapshot.task(titled: "Call the plumber")?.state == .next)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs.isEmpty)
    }

    @Test("020-FR-011 a decision on an unchanged formulation goes through the stale-revision refetch and is applied")
    func staleDecisionRefetches() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        let tablet = await harness.device()
        try await tablet.signIn()
        let onTablet = try #require(try await tablet.current().task(titled: "Renovate the bathroom"))
        try await tablet.review(.updateTask(.init(taskID: onTablet.id, changes: TaskChanges(details: .set("Tiles first")))))
        await tablet.sync()

        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        let server = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        #expect(server.state == .someday && server.details == "Tiles first")
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs == [Self.decision(1).rawValue])
    }

    @Test("020-FR-011 020-FR-045 a decision retried after the 24 h retention with a stale revision is a success, applied once")
    func decisionRetriedAfterRetention() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 15 * Self.day)
        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("tasks/", method: .post))
        #expect(try await phone.document().outbox.count == 1, "the outcome is unknown: kept with its key")

        harness.clock.advance(by: FakeBrainBuddyServer.idempotencyRetention + 3_600)
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs == [Self.decision(1).rawValue])
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .someday)
        #expect(try await phone.current().task(titled: "Renovate the bathroom")?.state == .someday)
    }

    @Test("020-FR-048 an undo retried after its first delivery applied gets 404 and is a success, never set aside")
    func undoRetriedIsSuccess() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        await phone.sync()
        try await phone.review(.undoDecision(Self.decision(1)))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("review/decisions/", method: .post))
        harness.clock.advance(by: FakeBrainBuddyServer.idempotencyRetention + 3_600)
        await phone.sync()

        let document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .next)
        #expect(try await phone.current().task(titled: "Renovate the bathroom")?.state == .next)
        let undoes = phone.transport.exchanges.filter { $0.request.url.path.hasSuffix("/undo") }
        #expect(undoes.compactMap(\.statusCode).contains(404))
    }

    @Test("020-SC-007 a decision naming a review the server does not know is kept, without a review")
    func decisionWithUnknownSession() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await phone.review(decide(.complete, "t1", 1, formulation: Self.form(1), session: Self.session(9)))
        await phone.sync()
        #expect(try await phone.document().issues.isEmpty)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs == [Self.decision(1).rawValue])
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .completed)
    }

    // MARK: - Auto-park (T089)

    @Test("020-FR-012 020-FR-013 two devices park the same formulation offline: one server park, no sync issue")
    func twoDevicesPark() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        let tablet = await harness.device()
        try await tablet.signIn()
        let onTablet = try #require(try await tablet.current().task(titled: "Renovate the bathroom"))
        harness.clock.advance(by: 22 * Self.day)
        let now = harness.clock.now()
        try await phone.review(.autoParkTask(.init(taskID: "t1", formulationID: Self.form(1), observedAt: now)))
        try await tablet.review(.autoParkTask(.init(taskID: onTablet.id, formulationID: Self.form(1), observedAt: now)))
        await phone.sync()
        await tablet.sync()
        await phone.sync()

        #expect(try await phone.document().issues.isEmpty)
        #expect(try await tablet.document().issues.isEmpty)
        let server = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        #expect(server.state == .someday)
        #expect(server.parked?.formulationID == Self.form(1).rawValue)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).unseenParks.count == 1)
        for device in [phone, tablet] {
            let task = try #require(try await device.current().task(titled: "Renovate the bathroom"))
            #expect(task.state == .someday && task.parked?.formulationID == Self.form(1))
        }
    }

    @Test("020-FR-013 a park the server does not apply is acknowledged; the task stays in Next")
    func parkNotApplied() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 2 * Self.day)
        // A device clock days ahead observed the park; the server's own
        // evaluation is not park_due.
        try await phone.review(
            .autoParkTask(
                .init(taskID: "t1", formulationID: Self.form(1), observedAt: harness.clock.now().addingTimeInterval(30 * Self.day), optimistic: false)
            )
        )
        #expect(try await phone.current().task(titled: "Renovate the bathroom")?.state == .next, "online: not parked before the answer")
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        #expect(try await phone.current().task(titled: "Renovate the bathroom")?.state == .next)
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .next)
    }

    @Test("020-FR-012 an offline notes edit and an offline decision with a server park between: decision applied, 0 issues")
    func yieldAfterServerPark() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 20 * Self.day)
        try await phone.review(.updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("Tiles first")))))
        try await phone.review(
            decide(.firstStep, "t1", 1, formulation: Self.form(1), title: "Measure the wall", newFormulation: Self.form(2))
        )
        harness.clock.advance(by: 1 * Self.day + 3_600)
        #expect(harness.server.runAutoParkSweep() == 1)
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .someday)

        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        let server = try #require(harness.snapshot.task(titled: "Measure the wall"))
        #expect(server.state == .next)
        #expect(server.details?.contains("Tiles first") == true)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs == [Self.decision(1).rawValue])
    }

    @Test("020-FR-040 the flag turned off with 3 queued review commands: 0 set-asides, 0 reverted decisions")
    func flagTurnedOff() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.server.setWeeklyReview(email: SyncHarness.email, enabled: false)
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        try await phone.review(decide(.complete, "t1", 1, formulation: Self.form(1), session: Self.session(1)))
        try await phone.review(.review(.grantNavigatorConsent(provider: "openai", consentTextVersion: 1)))
        await phone.sync()

        var document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.base.review.server?.exposed == false, "the gated read said the flag is off")
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .completed)
        #expect(try await phone.current().task(titled: "Renovate the bathroom")?.state == .completed, "not reverted")
        #expect(document.outbox.allSatisfy { if case .review(.grantNavigatorConsent) = $0.command { true } else { false } })

        harness.server.setWeeklyReview(email: SyncHarness.email, enabled: true)
        harness.clock.advance(by: 3_600)
        await phone.sync()
        document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        #expect(document.base.review.server?.exposed == true)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).consents["openai"]?.allowsCloud == true)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs == [Self.decision(1).rawValue])
    }

    @Test("020-FR-051 a queued edit survives activation")
    func editSurvivesActivation() async throws {
        let harness = SyncHarness()
        harness.server.setWeeklyReview(email: SyncHarness.email, enabled: true)
        let phone = await harness.device()
        try await phone.signIn()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await phone.review(.updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("Tiles first")))))
        try await phone.review(.review(.acknowledgeExplainer(timeZone: "Europe/Berlin")))
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.details == "Tiles first")
        let settings = harness.server.reviewSnapshot(email: SyncHarness.email).settings
        #expect(settings.activatedAt != nil && settings.timeZone == "Europe/Berlin")
        #expect(document.base.review.settings.activatedAt == settings.activatedAt)
    }

    // MARK: - Runs (T135)

    @Test("020-FR-029 two devices start a review offline: 0 decisions lost, the other review ended elsewhere")
    func twoDevicesStartReviews() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await nextTask("Clean the gutter", id: "t2", form: 2, on: phone)
        let tablet = await harness.device()
        try await tablet.signIn()
        let gutter = try #require(try await tablet.current().task(titled: "Clean the gutter"))
        harness.clock.advance(by: 15 * Self.day)
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        try await phone.review(decide(.complete, "t1", 1, formulation: Self.form(1), session: Self.session(1)))
        harness.clock.advance(by: 60)
        try await tablet.review(.review(.startSession(StartSession(sessionID: Self.session(2), mode: .quick, entry: .list))))
        try await tablet.review(decide(.someday, gutter.id, 2, formulation: Self.form(2), session: Self.session(2)))
        await phone.sync()
        await tablet.sync()
        await phone.sync()

        #expect(try await phone.document().issues.isEmpty)
        #expect(try await tablet.document().issues.isEmpty)
        let review = harness.server.reviewSnapshot(email: SyncHarness.email)
        #expect(review.decisionIDs == [Self.decision(1).rawValue, Self.decision(2).rawValue])
        #expect(review.sessions[Self.session(1).rawValue]?.status == .partial)
        #expect(review.sessions[Self.session(2).rawValue]?.status == .open)
        let mine = try #require(try await phone.current().review.sessions[Self.session(1)])
        #expect(mine.endedElsewhere)
        #expect(mine.status != .open)
    }

    @Test("020-SC-007 an offline quick review with 3 decisions syncs with its counts on the server; finish is idempotent")
    func offlineQuickReview() async throws {
        let (harness, phone) = try await activated()
        for (index, title) in ["Renovate the bathroom", "Clean the gutter", "Sell the bike"].enumerated() {
            try await phone.review(
                .createTask(.init(taskID: TaskID("t\(index)"), title: title, list: .next, newFormulationID: Self.form(index + 1)))
            )
        }
        await phone.sync()
        harness.clock.advance(by: 15 * Self.day)
        phone.transport.inject(.offline, times: 100)
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        try await phone.review(decide(.complete, "t0", 1, formulation: Self.form(1), session: Self.session(1)))
        try await phone.review(decide(.someday, "t1", 2, formulation: Self.form(2), session: Self.session(1)))
        try await phone.review(decide(.cancel, "t2", 3, formulation: Self.form(3), session: Self.session(1)))
        try await phone.review(.review(.finishSession(FinishSession(sessionID: Self.session(1), clearStart: .yes))))
        await phone.sync()
        phone.transport.clearFaults()
        harness.clock.advance(by: 3_600)
        await phone.sync()

        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        let session = try #require(harness.server.reviewSnapshot(email: SyncHarness.email).sessions[Self.session(1).rawValue])
        #expect(session.status == .completed)
        #expect(session.counts[.done] == 1 && session.counts[.someday] == 1 && session.counts[.cancelled] == 1)
        #expect(session.clearStart == .yes)
        // A second finish changes nothing.
        try await phone.review(.review(.finishSession(FinishSession(sessionID: Self.session(1)))))
        await phone.sync()
        #expect(try await phone.document().issues.isEmpty)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).sessions[Self.session(1).rawValue]?.clearStart == .yes)
    }

    @Test("020-SC-004 a progress change retried after the 24 h retention is merged once and is a success")
    func progressRetriedAfterRetention() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .full, entry: .list))))
        await phone.sync()
        try await phone.review(
            .review(
                .progressSession(
                    SessionProgress(
                        sessionID: Self.session(1), progressID: Self.progress(1), activeStep: .wins, activeSeconds: 42,
                        inboxProcessedDelta: 2
                    )
                )
            )
        )
        try await loseResponse(on: phone, matching: FakeServerTransport.path("review/sessions/", method: .patch))
        harness.clock.advance(by: FakeBrainBuddyServer.idempotencyRetention + 3_600)
        await phone.sync()

        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        let session = try #require(harness.server.reviewSnapshot(email: SyncHarness.email).sessions[Self.session(1).rawValue])
        #expect(session.activeSecondsByStep[.wins] == 42, "active time not doubled")
        #expect(session.counts[.inboxProcessed] == 2, "Inbox processed not doubled")
    }

    @Test("020-FR-017 a retried bulk-release undo answered with the stored result is a success; clocks come back exactly")
    func bulkUndoRetried() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 29 * Self.day)
        let before = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        try await phone.review(.bulkRelease(.init(bulkID: Self.bulk(1), kind: .restart, taskIDs: ["t1"])))
        await phone.sync()
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .someday)
        try await phone.review(.undoBulkRelease(Self.bulk(1)))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("review/bulk-releases/", method: .post))
        harness.clock.advance(by: FakeBrainBuddyServer.idempotencyRetention + 3_600)
        await phone.sync()

        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        let after = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        #expect(after.state == .next)
        #expect(after.formulation?.id == before.formulation?.id && after.formulation?.startedAt == before.formulation?.startedAt)
    }

    // MARK: - Pulls between a lost answer and its retry (review round on 3e0f799)

    /// The answer to the matching request is lost, the device stays offline
    /// for the rest of that cycle, then its next cycle meets one 503 on the
    /// same route, so it pulls while the operation is still queued.
    private func loseResponseThenPull(on device: Device, matching: @escaping FakeServerTransport.Matcher) async throws {
        try await loseResponse(on: device, matching: matching)
        device.transport.inject(.status(503), times: 1, matching: matching)
        await device.sync()
        device.transport.clearFaults()
    }

    @Test(
        "020-FR-011 020-SC-007 a decision applied on the server, answer lost, then a pull: no sync issue, the decision is kept",
        arguments: [DecisionType.someday, .complete, .reformulate]
    )
    func appliedDecisionThenPull(_ type: DecisionType) async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        await phone.sync()
        harness.clock.advance(by: 15 * Self.day)
        try await phone.review(
            decide(
                type, "t1", 1, formulation: Self.form(1), title: type == .reformulate ? "Call the tiler" : nil,
                session: Self.session(1), newFormulation: type == .reformulate ? Self.form(2) : nil
            )
        )
        try await loseResponseThenPull(on: phone, matching: FakeServerTransport.path("tasks/", method: .post))
        harness.clock.advance(by: 60)
        await phone.sync()

        let document = try await phone.document()
        #expect(document.issues.isEmpty, "the server applied the decision; no sync issue")
        #expect(document.outbox.isEmpty)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs == [Self.decision(1).rawValue])
        let decision = try #require(document.base.review.decisions[Self.decision(1)], "the decision record is kept")
        #expect(decision.type == type && decision.sessionID == Self.session(1))
        #expect(document.base.review.sessions[Self.session(1)]?.counts[type.countsAs] == 1)
    }

    @Test("020-FR-048 an Undo queued behind a decision whose answer was lost, with a pull between, reaches the server")
    func undoBehindLostDecision() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 15 * Self.day)
        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("tasks/", method: .post))
        try await phone.review(.undoDecision(Self.decision(1)))
        #expect(try await phone.current().tasks["t1"]?.state == .next, "undone on the device")
        phone.transport.inject(.status(503), times: 1, matching: FakeServerTransport.path("tasks/", method: .post))
        for _ in 0..<4 {
            harness.clock.advance(by: 60)
            await phone.sync()
        }
        let document = try await phone.document()
        #expect(document.issues.isEmpty, "\(document.issues.map(\.message))")
        #expect(document.outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .next, "the Undo reached the server")
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).decisionIDs.isEmpty)
        #expect(try await phone.current().tasks["t1"]?.state == .next)
    }

    @Test("020-FR-048 that queued Undo, when the task changed on another device meanwhile, is refused by the server with its Ref")
    func undoBehindLostDecisionRefusedByServer() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 15 * Self.day)
        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("tasks/", method: .post))
        try await phone.review(.undoDecision(Self.decision(1)))
        let tablet = await harness.device()
        try await tablet.signIn()
        let onTablet = try #require(try await tablet.current().task(titled: "Renovate the bathroom"))
        try await tablet.review(.updateTask(.init(taskID: onTablet.id, changes: TaskChanges(details: .set("Tiles first")))))
        await tablet.sync()
        phone.transport.inject(.status(503), times: 1, matching: FakeServerTransport.path("tasks/", method: .post))
        for _ in 0..<4 {
            harness.clock.advance(by: 60)
            await phone.sync()
        }
        let document = try await phone.document()
        let issue = try #require(document.issues.first)
        #expect(document.issues.count == 1)
        guard case .undoDecision(Self.decision(1)) = issue.command else {
            Issue.record("expected the Undo to be set aside, got \(issue.command)")
            return
        }
        #expect(issue.referenceID != nil, "the server's refusal, not the device's")
        #expect(document.outbox.isEmpty)
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .someday)
        #expect(try await phone.current().tasks["t1"]?.state == .someday)
    }

    @Test("020-FR-029 an open review the server sends in a shape this build cannot read is not ended on the device")
    func unreadableOpenSession() throws {
        let epoch = Date(timeIntervalSince1970: 1_790_000_000)
        let id = Self.session(1)
        let session = ReviewSession(id: id, mode: .quick, entry: .list, origin: .ios, startedAt: epoch)
        var state = ReviewStateDTO(
            settings: ReviewSettingsDTO(
                thresholdDays: 14, reviewWeekday: 7, reviewTime: "18:00", timeZone: "UTC", onboardedAt: epoch,
                activatedAt: epoch, ownerParkFloorAt: nil, revision: 1
            ),
            explainerSeen: true, graceUntil: nil, lastCountedReviewAt: nil, lastCountedReview: nil,
            nextReviewAt: epoch.addingTimeInterval(7 * Self.day), restartMode: false, openSession: nil, unseenParks: [],
            counts: ReviewStateCountsDTO(asksForDecision: 0, movesTomorrow: 0), receipts: [], serverNow: epoch
        )
        state.unreadableOpenSessionID = id.rawValue
        var document = StoreDocument()
        document.base.review.sessions[id] = session
        document.mergeReviewState(state, now: epoch.addingTimeInterval(60))
        #expect(document.base.review.sessions[id] == session, "kept open, not ended elsewhere")
        #expect(document.base.review.server?.openSessionID == id)

        // Another unreadable run is open on the server: this device's was replaced.
        state.unreadableOpenSessionID = Self.session(2).rawValue
        document.mergeReviewState(state, now: epoch.addingTimeInterval(120))
        #expect(document.base.review.sessions[id]?.endedElsewhere == true)
        #expect(document.base.review.sessions[Self.session(2)] == nil, "nothing to show for a run this build cannot read")
    }

    @Test(
        "020-FR-009 020-FR-012 an offline Keep 7 more days, then a server park, then sync (with and without a pull first)",
        arguments: [false, true]
    )
    func extensionYieldsToServerPark(_ pullFirst: Bool) async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 20 * Self.day)
        try await phone.review(
            .decideTask(.init(decisionID: Self.decision(1), taskID: "t1", type: .extend, formulationID: Self.form(1), reason: "Still right"))
        )
        harness.clock.advance(by: Self.day + 3_600)
        #expect(harness.server.runAutoParkSweep() == 1)
        if pullFirst {
            phone.transport.inject(.status(503), times: 1, matching: FakeServerTransport.path("tasks/", method: .post))
            await phone.sync()
            phone.transport.clearFaults()
            #expect(try await phone.document().issues.isEmpty, "the pulled park does not refuse the queued extension")
            harness.clock.advance(by: 60)
        }
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty)
        #expect(document.outbox.isEmpty)
        let server = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        #expect(server.state == .next && server.formulation?.extendedAt != nil)
        #expect(document.base.review.decisions[Self.decision(1)]?.yieldedAutoPark == true)
    }

    @Test("020-FR-017 a bulk release applied on the server, answer lost, then a pull: Undo still restores every task")
    func bulkReleaseThenPull() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 29 * Self.day)
        let before = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        try await phone.review(.bulkRelease(.init(bulkID: Self.bulk(1), kind: .restart, taskIDs: ["t1"])))
        try await loseResponseThenPull(on: phone, matching: FakeServerTransport.path("review/bulk-releases", method: .post))
        harness.clock.advance(by: 60)
        await phone.sync()
        var document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        #expect(document.base.review.bulkReleases[Self.bulk(1)]?.released.map(\.taskID) == ["t1"], "taken from the server's answer")

        try await phone.review(.undoBulkRelease(Self.bulk(1)))
        await phone.sync()
        document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        let after = try #require(harness.snapshot.task(titled: "Renovate the bathroom"))
        #expect(after.state == .next && after.formulation?.id == before.formulation?.id)
        #expect(after.formulation?.startedAt == before.formulation?.startedAt)
    }

    @Test("020-FR-029 020-FR-045 a review start retried after the 24 h retention is a success; one review on the server")
    func startSessionRetriedAfterRetention() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("review/sessions", method: .post))
        harness.clock.advance(by: FakeBrainBuddyServer.idempotencyRetention + 3_600)
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        let sessions = harness.server.reviewSnapshot(email: SyncHarness.email).sessions
        #expect(Array(sessions.keys) == [Self.session(1).rawValue])
        #expect(sessions[Self.session(1).rawValue]?.status == .open, "the retry replaced nothing")
    }

    @Test("020-FR-017 020-FR-045 a bulk release retried after the 24 h retention is a success, applied once")
    func bulkReleaseRetriedAfterRetention() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: 29 * Self.day)
        try await phone.review(.bulkRelease(.init(bulkID: Self.bulk(1), kind: .restart, taskIDs: ["t1"])))
        try await loseResponse(on: phone, matching: FakeServerTransport.path("review/bulk-releases", method: .post))
        harness.clock.advance(by: FakeBrainBuddyServer.idempotencyRetention + 3_600)
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.isEmpty && document.outbox.isEmpty)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).bulkReleaseIDs == [Self.bulk(1).rawValue])
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .someday)
        #expect(document.base.review.bulkReleases[Self.bulk(1)]?.released.map(\.taskID) == ["t1"])
    }

    @Test("020-FR-011 a decision the server refuses is set aside with the M-03 copy naming where the task is, and its Ref")
    func refusedDecisionCopy() async throws {
        let (_, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        phone.transport.inject(.status(400), times: 1, matching: FakeServerTransport.path("tasks/", method: .post))
        await phone.sync()
        let issue = try #require(try await phone.document().issues.first)
        #expect(issue.message == ReviewCopy.decisionNotSaved(.someday, title: "Renovate the bathroom", list: .next))
        #expect(issue.referenceID != nil)
    }

    @Test("020-FR-048 an undo answered 404 for something other than the decision is not taken as success")
    func undoNotFoundOtherResource() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        try await phone.review(decide(.someday, "t1", 1, formulation: Self.form(1)))
        await phone.sync()
        try await phone.review(.undoDecision(Self.decision(1)))
        phone.transport.inject(.status(404), times: 1, matching: FakeServerTransport.path("review/decisions/", method: .post))
        await phone.sync()
        let document = try await phone.document()
        #expect(document.issues.count == 1, "a 404 without the decision named is a real failure")
        #expect(harness.snapshot.task(titled: "Renovate the bathroom")?.state == .someday)
    }

    // MARK: - The fake server against the golden invalid bodies (I4, I5)

    /// The API test target's copy of the golden wire fixtures (PR-02), read
    /// in place so no further copy is made.
    static let invalidRequests: [(id: String, model: String, body: Data)] = {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("BrainBuddyAPITests/Resources/review_wire_fixtures.json")
        guard let data = try? Data(contentsOf: url),
            let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let entries = root["entries"] as? [[String: Any]]
        else { fatalError("Missing \(url.path)") }
        return entries.compactMap { entry in
            guard entry["valid"] as? Bool == false, entry["kind"] as? String == "request",
                let id = entry["id"] as? String, let model = entry["model"] as? String, let body = entry["body"],
                let encoded = try? JSONSerialization.data(withJSONObject: body)
            else { return nil }
            return (id, model, encoded)
        }
    }()

    @Test("020-FR-045 the fake server refuses every invalid golden request body with 422, as the backend does")
    func fakeServerRefusesInvalidBodies() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        let task = try #require(harness.snapshot.task(titled: "Renovate the bathroom")).id
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        await phone.sync()
        let navigator: Set = ["W-R04", "W-R13"]
        #expect(
            Set(Self.invalidRequests.map(\.id)) == ["W-R01", "W-R02", "W-R03", "W-R04", "W-R05", "W-R06", "W-R07", "W-R08", "W-R10", "W-R12", "W-R13", "W-R14", "W-R15"]
        )
        for entry in Self.invalidRequests where !navigator.contains(entry.id) {
            let path: [String] =
                switch entry.model {
                case "DecisionRequest": ["tasks", task, "decisions"]
                case "SessionProgressRequest": ["review", "sessions", Self.session(1).rawValue]
                case "ReviewSettingsUpdateRequest": ["review", "settings"]
                default: []
                }
            #expect(!path.isEmpty, "\(entry.id): no route for \(entry.model)")
            let method: HTTPMethod =
                switch entry.model {
                case "SessionProgressRequest": .patch
                case "ReviewSettingsUpdateRequest": .put
                default: .post
                }
            let status = try await raw(phone, method, path, entry.body)
            #expect(status == 422, "\(entry.id) \(entry.model)")
        }
    }

    /// Sends `body` as the signed-in device, bypassing the client's own checks.
    private func raw(_ device: Device, _ method: HTTPMethod, _ path: [String], _ body: Data) async throws -> Int {
        try await rawResponse(device, method, path, body).statusCode
    }

    private func rawResponse(_ device: Device, _ method: HTTPMethod, _ path: [String], _ body: Data) async throws -> HTTPResponse {
        let token = try #require(try device.tokens.token(for: FakeBrainBuddyServer.baseURL))
        var url = FakeBrainBuddyServer.baseURL
        for segment in path { url.appendPathComponent(segment) }
        let request = HTTPRequest(
            method: method, url: url,
            headers: [
                "Cookie": "\(BrainBuddyAPI.sessionCookieName)=\(token)", "Idempotency-Key": UUID().uuidString.lowercased(),
                "Content-Type": "application/json",
            ],
            body: body
        )
        return try await device.transport.send(request)
    }

    @Test("020-FR-028 the fake server refuses progress naming a step outside a quick review's mode with 422, as the backend does")
    func fakeServerRefusesStepsOutsideTheMode() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .quick, entry: .list))))
        await phone.sync()
        let path = ["review", "sessions", Self.session(1).rawValue]
        for (n, change) in [#""step":{"code":"dates","status":"finished"}"#, #""active_seconds":{"code":"rest_of_next","seconds":5}"#]
            .enumerated()
        {
            let body = Data(#"{"progress_id":"\#(Self.progress(10 + n).rawValue)",\#(change)}"#.utf8)
            let response = try await rawResponse(phone, .patch, path, body)
            #expect(response.statusCode == 422, "\(change)")
            let detail = try #require(try JSONSerialization.jsonObject(with: response.body) as? [String: Any])["detail"] as? [[String: Any]]
            #expect(detail?.first?["loc"] as? [String] == ["body", n == 0 ? "step" : "active_seconds", "code"])
        }
        let session = harness.server.reviewSnapshot(email: SyncHarness.email).sessions[Self.session(1).rawValue]
        #expect(session?.qualifyingActivity == false)
        let own = Data(#"{"progress_id":"\#(Self.progress(20).rawValue)","step":{"code":"wins","status":"finished"}}"#.utf8)
        #expect(try await raw(phone, .patch, path, own) == 200)
    }

    @Test("020-FR-045 the fake server names an unknown review record in its 404 as the backend does")
    func fakeServerNamesUnknownReviewRecords() async throws {
        let (_, phone) = try await activated()
        let session = Self.session(9).rawValue
        let cases: [(HTTPMethod, [String], String, String)] = [
            (.get, ["review", "sessions", session], "{}", "Review session"),
            (.patch, ["review", "sessions", session], #"{"progress_id":"\#(Self.progress(9).rawValue)"}"#, "Review session"),
            (.post, ["review", "sessions", session, "finish"], "{}", "Review session"),
            (.post, ["review", "bulk-releases", Self.bulk(9).rawValue, "undo"], "{}", "Review bulk release"),
            (.post, ["review", "decisions", Self.decision(9).rawValue, "undo"], #"{"expected_task_revision":1}"#, "Review decision"),
        ]
        for (method, path, body, resource) in cases {
            let response = try await rawResponse(phone, method, path, Data(body.utf8))
            #expect(response.statusCode == 404, "\(path)")
            let detail = try #require(try JSONSerialization.jsonObject(with: response.body) as? [String: Any])["detail"] as? [String: Any]
            #expect(detail?["resource"] as? String == resource, "\(path)")
        }
    }

    @Test("020-FR-029 finishing a step qualifies the review only when the step had nothing to decide (E3), on the server too")
    func qualifyingOnServer() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.createTask(.init(taskID: "i1", title: "Idea", list: .inbox)))
        try await phone.review(.review(.startSession(StartSession(sessionID: Self.session(1), mode: .full, entry: .list))))
        try await phone.review(
            .review(.progressSession(SessionProgress(sessionID: Self.session(1), progressID: Self.progress(1), step: .inbox, stepStatus: .finished)))
        )
        await phone.sync()
        var session = harness.server.reviewSnapshot(email: SyncHarness.email).sessions[Self.session(1).rawValue]
        #expect(session?.qualifyingActivity == false, "the Inbox still had an item")
        try await phone.review(
            .review(.progressSession(SessionProgress(sessionID: Self.session(1), progressID: Self.progress(2), step: .wins, stepStatus: .finished)))
        )
        await phone.sync()
        session = harness.server.reviewSnapshot(email: SyncHarness.email).sessions[Self.session(1).rawValue]
        #expect(session?.qualifyingActivity == true)
        #expect(try await phone.document().issues.isEmpty)
    }

    @Test("020-FR-035 the fake server range-checks the review day and time")
    func fakeServerChecksWeekdayAndTime() async throws {
        let (_, phone) = try await activated()
        for body in [
            #"{"review_weekday":8,"expected_revision":1}"#, #"{"review_weekday":0,"expected_revision":1}"#,
            #"{"review_time":"25:00","expected_revision":1}"#, #"{"review_time":"9:5","expected_revision":1}"#,
        ] {
            #expect(try await raw(phone, .put, ["review", "settings"], Data(body.utf8)) == 422, "\(body)")
        }
    }

    @Test("020-FR-012 the fake sweep floors parks after a gap of 24 h or more and repairs a missing clock")
    func fakeSweepGapAndRepair() async throws {
        let (harness, phone) = try await activated()
        try await nextTask("Renovate the bathroom", id: "t1", form: 1, on: phone)
        harness.clock.advance(by: Self.day)
        #expect(harness.server.runAutoParkSweep() == 0)
        // The sweep then does not run for 21 days: the gap floors every park
        // for 7 days, so nothing parks at once.
        harness.clock.advance(by: 21 * Self.day)
        let gapAt = harness.clock.now()
        #expect(harness.server.runAutoParkSweep() == 0, "a sweep gap of 24 h or more floors parks for 7 days")
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).settings.ownerParkFloorAt == gapAt.addingTimeInterval(7 * Self.day))
        var parked = 0
        while harness.clock.now() < gapAt.addingTimeInterval(7 * Self.day + 3_600) {
            harness.clock.advance(by: 12 * 3_600)
            parked += harness.server.runAutoParkSweep()
            if harness.clock.now() < gapAt.addingTimeInterval(7 * Self.day) {
                #expect(parked == 0, "nothing parks before the floor")
            }
        }
        #expect(parked == 1, "regular sweeps park once the floor passed")

        // A Next task without a clock is repaired by the sweep, with 14 days of grace.
        try await nextTask("Clean the gutter", id: "t2", form: 2, on: phone)
        harness.server.dropClock(email: SyncHarness.email, title: "Clean the gutter")
        harness.clock.advance(by: 3_600)
        _ = harness.server.runAutoParkSweep()
        let repaired = try #require(harness.snapshot.task(titled: "Clean the gutter")?.formulation)
        #expect(repaired.parkFloorAt == harness.clock.now().addingTimeInterval(14 * Self.day))
    }

    // MARK: - Settings and consent (T151, T108)

    @Test("020-FR-035 a settings change racing another device: 409, refetch, only the changed fields resent")
    func settingsConflict() async throws {
        let (harness, phone) = try await activated()
        let tablet = await harness.device()
        try await tablet.signIn()
        try await tablet.review(.review(.updateSettings(ReviewSettingsChange(reviewWeekday: 2))))
        await tablet.sync()
        try await phone.review(.review(.updateSettings(ReviewSettingsChange(thresholdDays: 21))))
        await phone.sync()

        #expect(try await phone.document().issues.isEmpty)
        let settings = harness.server.reviewSnapshot(email: SyncHarness.email).settings
        #expect(settings.reviewWeekday == 2, "the other device's change is kept")
        #expect(settings.thresholdDays == 21)
        let puts = phone.transport.exchanges.filter { $0.request.method == .put }
        #expect(puts.compactMap(\.statusCode) == [409, 200])
    }

    /// The M-01 "threshold just changed" note's inputs on the device: the
    /// change instant (which also keys its dismissal) and the floor date.
    private func thresholdNote(on device: Device) async throws -> (changedAt: Date?, floor: Date?, days: Int) {
        let settings = try await device.current().review.settings
        return (settings.thresholdChangedAt, settings.ownerParkFloorAt, settings.thresholdDays)
    }

    @Test("020-FR-039 the threshold-changed note outlives the settings acknowledgement and later pulls")
    func thresholdNoteSurvivesSync() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.updateSettings(ReviewSettingsChange(thresholdDays: 7))))
        let changedAt = try #require(try await thresholdNote(on: phone).changedAt, "the optimistic change sets it")

        await phone.sync()
        #expect(try await phone.document().outbox.isEmpty, "the PUT was acknowledged")
        var note = try await thresholdNote(on: phone)
        #expect(note.days == 7)
        #expect(note.changedAt == changedAt, "the server settings do not carry it; the device keeps its own")
        #expect(note.floor == changedAt.addingTimeInterval(7 * Self.day))

        harness.clock.advance(by: 3_600)
        await phone.sync()
        note = try await thresholdNote(on: phone)
        #expect(note.changedAt == changedAt, "a later pull keeps it too, so a dismissal stays keyed to it")
        let settings = try await phone.current().review.settings
        let now = harness.clock.now()
        #expect(ThresholdChangeNote.change(settings: settings, dismissedChange: nil, now: now) == changedAt, "it shows")
        let dismissed = changedAt.timeIntervalSince1970
        #expect(ThresholdChangeNote.change(settings: settings, dismissedChange: dismissed, now: now) == nil, "until dismissed")
    }

    @Test("020-FR-039 the note survives a settings answer lost before a pull, and the resend")
    func thresholdNoteSurvivesLostAnswer() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.updateSettings(ReviewSettingsChange(thresholdDays: 21))))
        let changedAt = try #require(try await thresholdNote(on: phone).changedAt)
        try await loseResponse(on: phone, matching: FakeServerTransport.path("review/settings", method: .put))

        harness.clock.advance(by: 3_600)
        await phone.sync()
        #expect(try await phone.document().outbox.isEmpty)
        let note = try await thresholdNote(on: phone)
        #expect(note.days == 21)
        #expect(note.changedAt == changedAt, "the pull found the threshold this device set")
    }

    @Test("020-FR-039 a threshold another device set replaces this device's note")
    func thresholdNoteReplacedByOtherDevice() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.updateSettings(ReviewSettingsChange(thresholdDays: 7))))
        await phone.sync()
        #expect(try await thresholdNote(on: phone).changedAt != nil)

        let tablet = await harness.device()
        try await tablet.signIn()
        harness.clock.advance(by: 3_600)
        try await tablet.review(.review(.updateSettings(ReviewSettingsChange(thresholdDays: 28))))
        await tablet.sync()
        harness.clock.advance(by: 3_600)
        await phone.sync()
        let note = try await thresholdNote(on: phone)
        #expect(note.days == 28)
        #expect(note.changedAt == nil, "this device did not set 28 days")
    }

    @Test("020-FR-024 consent grant and revoke are idempotent; a revoke blocks cloud use at once, offline")
    func consent() async throws {
        let (harness, phone) = try await activated()
        try await phone.review(.review(.grantNavigatorConsent(provider: "openai", consentTextVersion: 1)))
        try await phone.review(.review(.grantNavigatorConsent(provider: "openai", consentTextVersion: 1)))
        await phone.sync()
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).consents["openai"]?.allowsCloud == true)
        phone.transport.inject(.offline, times: 100)
        try await phone.review(.review(.revokeNavigatorConsent(provider: "openai")))
        #expect(try await phone.current().review.navigatorConsents["openai"]?.allowsCloud == false, "blocked at once, offline")
        await phone.sync()
        phone.transport.clearFaults()
        harness.clock.advance(by: 3_600)
        try await phone.review(.review(.revokeNavigatorConsent(provider: "openai")))
        await phone.sync()
        #expect(try await phone.document().issues.isEmpty)
        #expect(harness.server.reviewSnapshot(email: SyncHarness.email).consents["openai"]?.allowsCloud == false)
    }
}

extension Device {
    /// Applies `command` the way a workspace with the review exposed does:
    /// replayed with the device's activation, appended clock-aware.
    @discardableResult
    func review(_ command: GTDCommand) async throws -> StoreDocument {
        let date = clock.now()
        return try await store.update { doc in
            var state = OutboxReplayer.replay(doc.outbox, onto: doc.base, activatedAt: doc.local.activatedAt).state
            // This helper stands for a workspace showing the review (tests turn
            // the flag off on the server, which the next pull brings).
            if !state.review.isExposed { state.review.accountlessReleaseSwitch = true }
            try GTDReducer.apply(command, at: date, to: &state)
            doc.outbox = OutboxCompactor.appending(
                PendingOperation(command: command, issuedAt: date), to: doc.outbox, clockAware: true
            )
        }
    }
}
