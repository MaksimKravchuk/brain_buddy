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
        #expect(dropped.first?.droppedResponse?.statusCode == 200)
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
            try GTDReducer.apply(command, at: date, to: &state)
            doc.outbox = OutboxCompactor.appending(
                PendingOperation(command: command, issuedAt: date), to: doc.outbox, clockAware: true
            )
        }
    }
}
