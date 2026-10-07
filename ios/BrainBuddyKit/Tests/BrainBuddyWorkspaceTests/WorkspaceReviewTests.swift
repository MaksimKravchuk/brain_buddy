import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// The weekly review on the workspace (spec 020; tasks.md T058, T089, T091,
/// T135, T151): decisions and Undo, form drafts, device auto-park, local
/// retention, the device zone and account linking.
@MainActor
@Suite struct WorkspaceReviewTests {
    nonisolated static let day: TimeInterval = 86_400
    nonisolated static let berlin = TimeZone(identifier: "Europe/Berlin")!
    nonisolated static let newYork = TimeZone(identifier: "America/New_York")!

    /// An account-less workspace with the review exposed and activated at
    /// `Fixture.epoch`, in Berlin.
    private func activatedWorkspace(
        store: InMemoryDocumentStore = InMemoryDocumentStore(), clock: TestClock = TestClock()
    ) async throws -> Workspace {
        let workspace = await loadedWorkspace(store: store, clock: clock)
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { Self.berlin }
        try workspace.acknowledgeExplainer()
        return workspace
    }

    private func nextTask(_ title: String, in workspace: Workspace) throws -> TaskID {
        try workspace.capture(CaptureDraft(text: title, list: .next))
    }

    // MARK: - Explainer (T087)

    @Test("020-FR-051 dismissing the explainer activates account-less at once and records the zone")
    func explainerActivates() async throws {
        let clock = TestClock()
        let workspace = await loadedWorkspace(clock: clock)
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { Self.berlin }
        let task = try nextTask("Renovate the bathroom", in: workspace)
        let before = try #require(workspace.task(task))
        #expect(workspace.explainerNeeded)
        clock.advance(by: 60)
        try workspace.acknowledgeExplainer()
        #expect(!workspace.explainerNeeded)
        #expect(workspace.localReview.activatedAt == Fixture.epoch.addingTimeInterval(60))
        #expect(workspace.localReview.lastObservedTimeZone == "Europe/Berlin")
        #expect(workspace.state.review.settings.timeZone == "Europe/Berlin")
        let after = try #require(workspace.task(task))
        #expect(after.title == before.title && after.state == before.state && after.details == before.details)
        #expect(after.formulation?.parkFloorAt == Fixture.epoch.addingTimeInterval(60 + 14 * Self.day), "only the clock changed")
        await workspace.flush()
        #expect(workspace.state == workspace.replayedState)
    }

    // MARK: - Decisions and Undo (T058)

    @Test("020-FR-010 020-FR-048 decide and undo through the workspace; an unsent pair cancels in the outbox")
    func decideAndUndo() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        clock.advance(by: 15 * Self.day)
        #expect(workspace.formulationClass(of: task) == .asks)
        #expect(workspace.decisionQueue().map(\.id) == [task])
        #expect(workspace.askCount() == 1)
        let before = try #require(workspace.task(task))

        let decision = try workspace.decide(.someday, on: task)
        #expect(decision.rawValue.hasPrefix("decision_"))
        #expect(workspace.task(task)?.state == .someday)
        #expect(workspace.decisionQueue().isEmpty)
        clock.advance(by: 4)
        try workspace.undoDecision(decision)
        let restored = try #require(workspace.task(task))
        #expect(restored.state == .next)
        #expect(restored.formulation == before.formulation, "the clock comes back exactly")
        await workspace.flush()
        let commands = workspace.document.outbox.map(\.command)
        #expect(!commands.contains { if case .decideTask = $0 { true } else { false } }, "decision and Undo cancelled")
        #expect(workspace.state == workspace.replayedState)
    }

    @Test("020-FR-011 020-FR-052 a form decision is bound to the wording it was opened on: a reformulation elsewhere refuses it")
    func decisionBoundToOpenedFormulation() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        clock.advance(by: 15 * Self.day)
        let opened = try #require(workspace.task(task)?.formulation?.id)
        // Another window (or a sync) reformulates while the form is open.
        try workspace.updateTask(task, TaskChanges(title: .set("Get 3 quotes for the bathroom")))
        let current = try #require(workspace.task(task))
        #expect(current.formulation?.id != opened)
        clock.advance(by: 15 * Self.day)

        #expect(throws: GTDValidationError.formulationChanged) {
            try workspace.decide(.reformulate, on: task, title: "Measure the bathroom wall", formulationID: opened)
        }
        #expect(throws: GTDValidationError.formulationChanged) {
            try workspace.decide(.extend, on: task, reason: "Waiting for the plumber", formulationID: opened)
        }
        #expect(workspace.task(task) == current, "nothing was applied")
        await workspace.flush()
        #expect(!workspace.document.outbox.contains { if case .decideTask = $0.command { true } else { false } })

        // The same decision on the current wording goes through.
        try workspace.decide(.extend, on: task, reason: "Waiting for the plumber", formulationID: current.formulation?.id)
        #expect(workspace.task(task)?.formulation?.extendedAt != nil)
    }

    @Test("020-FR-005 020-FR-009 the card's third-stall offer and the extension preview use the classification zone")
    func cardQueries() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        #expect(workspace.extensionInstants(of: task) == nil, "fresh: nothing to extend")
        #expect(workspace.isThirdStall(task) == false)
        clock.advance(by: 15 * Self.day)
        let record = try #require(workspace.task(task))
        let expected = GTDQueries.extensionInstants(
            of: record, now: workspace.reviewNow, settings: workspace.state.review.settings, timeZone: "Europe/Berlin"
        )
        #expect(workspace.extensionInstants(of: task) == expected)
        #expect(workspace.extensionInstants(of: task)?.askAt == workspace.reviewNow.addingTimeInterval(7 * Self.day))
        #expect(workspace.isThirdStall(task) == false, "the first wording")
        #expect(workspace.extensionInstants(of: "missing") == nil)
    }

    @Test("020-FR-015 closing While you were away without Continue keeps the parks unseen and shows the linking notices once")
    func closeWhileAwayClearsNotices() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let parked = try nextTask("Clean out the garage", in: workspace)
        clock.advance(by: 21 * Self.day)
        #expect(workspace.applyDueAutoParks() == 0)
        clock.advance(by: Self.day)
        #expect(workspace.applyDueAutoParks() == 1)
        let extended = try nextTask("Call the landlord", in: workspace)
        workspace.edit { $0.local.linkedExtensionNotices = [extended] }
        #expect(workspace.parkReturnProblem(of: parked) == nil)
        #expect(workspace.linkedExtensionNotices == [extended])

        workspace.closeWhileAway()
        #expect(workspace.linkedExtensionNotices.isEmpty, "notices are shown once")
        #expect(workspace.unseenParks().map(\.id).contains(parked), "a swipe-down is not seen")
        #expect(!workspace.whileAwayShouldShowAtAppOpen(), "not again today")
        clock.advance(by: Self.day)
        #expect(workspace.whileAwayShouldShowAtAppOpen(), "the parks come back another day")
        await workspace.flush()
        #expect(try await workspace.store.load()?.local.linkedExtensionNotices == [])
    }

    @Test("020-FR-015 Continue marks seen only the parks the sheet showed; one that arrived meanwhile stays unseen")
    func continueAcknowledgesShownParks() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let shownTask = try nextTask("Clean out the garage", in: workspace)
        let arrivedTask = try nextTask("Sort the photo albums", in: workspace)
        clock.advance(by: 21 * Self.day)
        #expect(workspace.applyDueAutoParks() == 0)
        clock.advance(by: Self.day)
        #expect(workspace.applyDueAutoParks() == 2)
        // The sheet appeared listing only the first (the second arrived while it was open).
        let shown = workspace.unseenParkAcks().filter { $0.taskID == shownTask }
        #expect(shown.count == 1)

        try workspace.dismissWhileAway(shown: shown)
        #expect(workspace.unseenParks().map(\.id) == [arrivedTask], "never displayed, so not seen")
        await workspace.flush()
        let acknowledged = workspace.document.outbox.flatMap { operation -> [ParkAck] in
            if case .review(.acknowledgeParks(let items)) = operation.command { return items }
            return []
        }
        #expect(acknowledged.map(\.taskID) == [shownTask])
    }

    @Test("020-FR-042 020-FR-015 While you were away taken away by the review switching off records nothing")
    func whileAwayTakenAwayWhenHidden() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let parked = try nextTask("Clean out the garage", in: workspace)
        clock.advance(by: 21 * Self.day)
        #expect(workspace.applyDueAutoParks() == 0)
        clock.advance(by: Self.day)
        #expect(workspace.applyDueAutoParks() == 1)
        let extended = try nextTask("Call the landlord", in: workspace)
        workspace.edit { $0.local.linkedExtensionNotices = [extended] }
        #expect(workspace.whileAwayShouldShowAtAppOpen())

        // The release switch (signed in: the flag) goes off while M-09 is
        // presented: the sheet is taken away, and its appear and close
        // callbacks must not record it.
        workspace.accountlessReviewEnabled = false
        #expect(!workspace.reviewExposed)
        workspace.markWhileAwayShown()
        workspace.closeWhileAway()
        #expect(workspace.localReview.wywaLastShownDay == nil, "not shown")
        #expect(workspace.linkedExtensionNotices == [extended], "the once-only notices are kept")
        #expect(workspace.unseenParks().map(\.id) == [parked], "not seen")

        workspace.accountlessReviewEnabled = true
        #expect(workspace.whileAwayShouldShowAtAppOpen(), "back on: it shows, the same day")
    }

    @Test("020-FR-011 a follow-up decision mints task_ and form_ client ids")
    func followUpIDs() async throws {
        let workspace = try await activatedWorkspace()
        let waiting = try workspace.capture(CaptureDraft(text: "Quote from Ann", list: .waiting, waitingFor: "Ann"))
        try workspace.decide(.followUp, on: waiting, title: "Ask Ann about the quote")
        await workspace.flush()
        guard case .decideTask(let decide)? = workspace.document.outbox.last?.command else {
            Issue.record("expected a queued decision")
            return
        }
        let followUp = try #require(decide.followUpTaskID)
        #expect(ClientID.isValid(followUp.rawValue, prefix: "task"))
        #expect(ClientID.isValid(try #require(decide.newFormulationID).rawValue, prefix: "form"))
        #expect(workspace.task(followUp)?.state == .next)
    }

    // MARK: - Drafts (T058, FR-052)

    @Test("020-FR-052 drafts are stored, restored and removed on save, discard and formulation change, never in the outbox")
    func draftsLifecycle() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        let formulation = try #require(workspace.task(task)?.formulation?.id)
        let key = DraftKey.decisionForm(.reformulate, task: task, formulation: formulation)
        workspace.saveDraft("Measure the bathroom wall", for: key)
        #expect(workspace.draft(for: key) == "Measure the bathroom wall")
        await workspace.flush()
        #expect(try await workspace.store.load()?.local.formDrafts[key]?.text == "Measure the bathroom wall")
        let outbox = String(decoding: try JSONEncoder().encode(workspace.document.outbox), as: UTF8.self)
        #expect(!outbox.contains("Measure the bathroom wall"), "a draft never enters an operation")

        // Discard.
        workspace.discardDraft(for: key)
        #expect(workspace.draft(for: key) == nil)

        // Save (the decision) removes the task's drafts.
        clock.advance(by: 15 * Self.day)
        workspace.saveDraft("Measure the wall", for: key)
        let stepKey = DraftKey.reviewStep(session: ReviewSessionID.make(UUID()), step: .mindSweep, item: "0")
        workspace.saveDraft("Call the bank", for: stepKey)
        try workspace.decide(.reformulate, on: task, title: "Measure the wall")
        #expect(workspace.draft(for: key) == nil)
        #expect(workspace.localReview.formDrafts[key] == nil)
        #expect(workspace.draft(for: stepKey) == "Call the bank", "drafts of other forms stay")

        // A formulation change invalidates a draft typed for the old one.
        let other = try nextTask("Clean the gutter", in: workspace)
        let otherKey = DraftKey.decisionForm(
            .firstStep, task: other, formulation: try #require(workspace.task(other)?.formulation?.id)
        )
        workspace.saveDraft("Buy a ladder", for: otherKey)
        try workspace.updateTask(other, TaskChanges(title: .set("Repair the gutter")))
        #expect(workspace.draft(for: otherKey) == nil)
        workspace.runLocalReviewMaintenance()
        #expect(workspace.localReview.formDrafts[otherKey] == nil)
    }

    @Test("020-FR-052 drafts expire after 7 days and are removed at sign-out")
    func draftsExpire() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let project = try workspace.createProject(name: "Renovation")
        let key = DraftKey.projectNextAction(project)
        workspace.saveDraft("Call the plumber", for: key)
        clock.advance(by: 6 * Self.day)
        #expect(workspace.draft(for: key) == "Call the plumber")
        clock.advance(by: 1 * Self.day + 1)
        #expect(workspace.draft(for: key) == nil)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        #expect(try await workspace.store.load()?.local.formDrafts.isEmpty == true)

        workspace.saveDraft("Order tiles", for: key)
        await workspace.flush()
        try await workspace.signOut(discardUnsyncedChanges: true)
        #expect(workspace.localReview.formDrafts.isEmpty)
        #expect(try await workspace.store.load() == nil)
    }

    // MARK: - Device auto-park (T089)

    @Test("020-FR-012 020-SC-006 no park without 24 hours of moves tomorrow; at most 10 per call; account-less parks are final")
    func applyDueAutoParks() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let tasks = try (0..<12).map { try nextTask("Task \($0)", in: workspace) }
        // Never seen "moves tomorrow" (the app was not opened): the first
        // look only starts the warning.
        clock.advance(by: 30 * Self.day)
        #expect(workspace.applyDueAutoParks() == 0)
        #expect(tasks.allSatisfy { workspace.task($0)?.state == .next })
        clock.advance(by: Self.day - 60)
        #expect(workspace.applyDueAutoParks() == 0, "23 h 59 min of warning are not enough")
        clock.advance(by: 60)
        #expect(workspace.applyDueAutoParks() == 10)
        #expect(workspace.unseenParks().count == 10)
        #expect(workspace.localReview.parkBatchWaiting)
        #expect(workspace.applyDueAutoParks() == 0, "the rest wait for While you were away")
        try workspace.dismissWhileAway(shown: workspace.unseenParkAcks())
        #expect(workspace.unseenParks().isEmpty)
        #expect(workspace.applyDueAutoParks() == 2)
        #expect(tasks.allSatisfy { workspace.task($0)?.state == .someday && workspace.task($0)?.parked != nil })
        await workspace.flush()
        #expect(workspace.state == workspace.replayedState, "account-less parks are final, replay included")
    }

    @Test("020-FR-012 a task seen moving tomorrow parks the day after; nothing parks before activation")
    func parkAfterWarning() async throws {
        let clock = TestClock()
        let workspace = await loadedWorkspace(clock: clock)
        workspace.accountlessReviewEnabled = true
        let task = try nextTask("Renovate the bathroom", in: workspace)
        clock.advance(by: 40 * Self.day)
        #expect(workspace.applyDueAutoParks() == 0, "not activated")
        try workspace.acknowledgeExplainer()
        // Activation clamps the clock: park due 21 days later.
        clock.advance(by: 20 * Self.day + 3_600)
        #expect(workspace.formulationClass(of: task) == .movesTomorrow)
        #expect(workspace.applyDueAutoParks() == 0)
        clock.advance(by: Self.day)
        #expect(workspace.applyDueAutoParks() == 1)
        #expect(workspace.task(task)?.state == .someday)
        #expect(workspace.whileAwayShouldShowAtAppOpen())
        workspace.markWhileAwayShown()
        #expect(!workspace.whileAwayShouldShowAtAppOpen(), "once per day")
    }

    // MARK: - Local retention (T089)

    @Test("020-FR-043 maintenance nulls undo and bulk snapshots, closes idle runs and deletes drafts after 7 days")
    func localMaintenance() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        let old = try nextTask("Sell the bike", in: workspace)
        let inbox = try workspace.capture(CaptureDraft(text: "Idea", list: .inbox))
        clock.advance(by: 29 * Self.day)
        _ = try nextTask("Fresh", in: workspace)
        let session = try workspace.startReview(mode: .full, entry: .list)
        let decision = try workspace.decide(.someday, on: task, sessionID: session)
        let bulk = try #require(try workspace.bulkRelease(.inboxRemainder, taskIDs: [inbox], sessionID: session).first)
        _ = old
        #expect(workspace.state.review.decisions[decision]?.undo != nil)
        #expect(workspace.state.review.bulkReleases[bulk]?.released.first?.previousState == .inbox)
        workspace.saveDraft("x", for: .projectNextAction("p1"))

        clock.advance(by: 7 * Self.day + 1)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        #expect(workspace.state.review.decisions[decision]?.undo == nil)
        #expect(workspace.state.review.decisions[decision] != nil, "the decision itself is history")
        #expect(throws: GTDValidationError.undoUnavailable) { try workspace.undoDecision(decision) }
        #expect(workspace.state.review.sessions[session]?.status == .partial, "idle 7 days with a decision: partial")
        #expect(workspace.localReview.formDrafts.isEmpty)
        #expect(workspace.state == workspace.replayedState.closingIdle(workspace.localReview))
    }

    @Test("020-FR-043 020-FR-048 signed in, an Undo queued offline past the 7-day window is answered by the server, not dropped as done")
    func expiredQueuedUndoReachesTheServer() async throws {
        let world = World()
        world.server.setWeeklyReview(email: World.email, enabled: true)
        let phone = await world.device()
        let workspace = phone.workspace
        workspace.deviceTimeZone = { Self.berlin }
        try await phone.signIn()
        await workspace.syncNow()
        try workspace.acknowledgeExplainer()
        let task = try nextTask("Renovate the bathroom", in: workspace)
        await workspace.syncNow()
        world.clock.advance(by: 15 * Self.day)
        let decision = try workspace.decide(.someday, on: task)
        await workspace.syncNow()
        #expect(world.snapshot.tasks.values.first?.state == .someday)
        #expect(workspace.document.outbox.isEmpty)

        // Offline: Undo inside the window, then 8 days pass before the device syncs.
        phone.transport.inject(.offline, times: 1_000)
        try workspace.undoDecision(decision)
        #expect(workspace.task(task)?.state == .next)
        world.clock.advance(by: 8 * Self.day)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        let kept = try #require(workspace.document.base.review.decisions[decision], "kept for the queued Undo")
        #expect(kept.undo == nil, "its snapshot expired on the device")
        #expect(kept.snapshotOnServer)
        #expect(workspace.document.outbox.map(\.command) == [.undoDecision(decision)])

        phone.transport.clearFaults()
        phone.transport.clearLog()
        await workspace.syncNow()
        #expect(
            phone.transport.requests.contains { $0.method == .post && $0.url.path.hasSuffix("/undo") },
            "the Undo was sent, not replayed as already done"
        )
        // The fake server keeps the snapshot; the real one may answer 409
        // undo_unavailable, which is set aside with its Ref (ReviewSyncTests).
        #expect(workspace.issues.isEmpty, "\(workspace.issues.map(\.message))")
        #expect(workspace.document.outbox.isEmpty)
        #expect(world.snapshot.tasks.values.first?.state == .next)
        #expect(workspace.task(task)?.state == .next)
        #expect(workspace.state.review.decisions[decision] == nil)
    }

    // MARK: - Retention and an unsent pair compaction kept (round 4)

    /// Whether the queued `decideTask` / `bulkRelease` still asks for its snapshot.
    private func retainsUndo(_ workspace: Workspace, decision: DecisionID? = nil, bulk: BulkID? = nil) -> Bool? {
        for operation in workspace.document.outbox {
            switch operation.command {
            case .decideTask(let decide) where decide.decisionID == decision: return decide.undoRetained
            case .bulkRelease(let release) where release.bulkID == bulk: return release.undoRetained
            default: continue
            }
        }
        return nil
    }

    @Test("020-FR-043 020-FR-048 account-less, an Undo after the run moved on still holds once 7-day retention runs")
    func accountlessUndoneDecisionSurvivesRetention() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        let other = try nextTask("Sell the bike", in: workspace)
        clock.advance(by: 15 * Self.day)
        let run = try workspace.startReview(mode: .quick, entry: .list)
        let decision = try workspace.decide(.someday, on: task, sessionID: run)
        try workspace.recordReviewProgress(run, currentStep: .summary)
        clock.advance(by: 3)
        try workspace.undoDecision(decision)
        let kept = try workspace.decide(.someday, on: other)
        await workspace.flush()
        #expect(workspace.task(task)?.state == .next)
        #expect(retainsUndo(workspace, decision: decision) == true, "the run moved on: compaction kept the pair")
        let counts = workspace.state.review.sessions[run]?.counts

        clock.advance(by: 8 * Self.day)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        #expect(workspace.task(task)?.state == .next, "the Undo still holds")
        #expect(workspace.issues.isEmpty)
        #expect(workspace.state.review.sessions[run]?.counts == counts)
        #expect(retainsUndo(workspace, decision: decision) == true, "its Undo needs the snapshot")
        #expect(retainsUndo(workspace, decision: kept) == false, "R15: a snapshot no Undo needs still expires")
        #expect(workspace.state.review.decisions[kept]?.undo == nil)
        #expect(workspace.state == workspace.replayedState.closingIdle(workspace.localReview))
    }

    @Test("020-FR-017 020-FR-043 account-less, a bulk-release Undo compaction kept still holds once 7-day retention runs")
    func accountlessUndoneReleaseSurvivesRetention() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        let edited = try nextTask("Clean the gutter", in: workspace)
        clock.advance(by: 29 * Self.day)
        let bulk = try #require(try workspace.bulkRelease(.restart, taskIDs: [task, edited]).first)
        // An edit of a released task keeps compaction from cancelling the pair.
        try workspace.updateTask(edited, TaskChanges(details: .set("Ladder first")))
        clock.advance(by: 3)
        try workspace.undoBulkRelease([bulk])
        await workspace.flush()
        #expect(workspace.task(task)?.state == .next)
        #expect(retainsUndo(workspace, bulk: bulk) == true)
        let before = workspace.state.tasks

        clock.advance(by: 8 * Self.day)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        #expect(workspace.task(task)?.state == .next, "the Undo still holds, clock included")
        #expect(workspace.state.tasks == before)
        #expect(workspace.issues.isEmpty)
        #expect(retainsUndo(workspace, bulk: bulk) == true)
    }

    /// A signed-in device with the review exposed and activated, online.
    private func signedInDevice(_ world: World) async throws -> (phone: AppDevice, workspace: Workspace) {
        world.server.setWeeklyReview(email: World.email, enabled: true)
        let phone = await world.device()
        let workspace = phone.workspace
        workspace.deviceTimeZone = { Self.berlin }
        try await phone.signIn()
        await workspace.syncNow()
        try workspace.acknowledgeExplainer()
        return (phone, workspace)
    }

    @Test("020-FR-043 020-FR-048 signed in, an unsent decision and its Undo kept past 7 days offline sync with no issue")
    func signedInUnsentPairSurvivesRetention() async throws {
        let world = World()
        let (phone, workspace) = try await signedInDevice(world)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        await workspace.syncNow()
        world.clock.advance(by: 15 * Self.day)

        phone.transport.inject(.offline, times: 1_000)
        let run = try workspace.startReview(mode: .quick, entry: .list)
        let decision = try workspace.decide(.someday, on: task, sessionID: run)
        try workspace.recordReviewProgress(run, currentStep: .summary)
        world.clock.advance(by: 3)
        try workspace.undoDecision(decision)
        await workspace.flush()
        #expect(retainsUndo(workspace, decision: decision) == true)
        world.clock.advance(by: 8 * Self.day)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        #expect(workspace.task(task)?.state == .next)
        #expect(retainsUndo(workspace, decision: decision) == true)

        phone.transport.clearFaults()
        await workspace.syncNow()
        await workspace.syncNow()
        #expect(workspace.issues.isEmpty, "\(workspace.issues.map(\.message))")
        #expect(workspace.document.outbox.isEmpty)
        #expect(world.snapshot.tasks.values.first?.state == .next)
        #expect(workspace.task(task)?.state == .next)
    }

    @Test("020-FR-017 020-FR-043 signed in, an unsent bulk release and its Undo kept past 7 days offline sync with no issue")
    func signedInUnsentReleaseSurvivesRetention() async throws {
        let world = World()
        let (phone, workspace) = try await signedInDevice(world)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        let edited = try nextTask("Clean the gutter", in: workspace)
        await workspace.syncNow()
        world.clock.advance(by: 29 * Self.day)

        phone.transport.inject(.offline, times: 1_000)
        let bulk = try #require(try workspace.bulkRelease(.restart, taskIDs: [task, edited]).first)
        try workspace.updateTask(edited, TaskChanges(details: .set("Ladder first")))
        world.clock.advance(by: 3)
        try workspace.undoBulkRelease([bulk])
        await workspace.flush()
        #expect(retainsUndo(workspace, bulk: bulk) == true)
        world.clock.advance(by: 8 * Self.day)
        workspace.runLocalReviewMaintenance()
        await workspace.flush()
        #expect(workspace.task(task)?.state == .next)

        phone.transport.clearFaults()
        await workspace.syncNow()
        await workspace.syncNow()
        #expect(workspace.issues.isEmpty, "\(workspace.issues.map(\.message))")
        #expect(workspace.document.outbox.isEmpty)
        #expect(world.snapshot.task(titled: "Renovate the bathroom")?.state == .next)
        #expect(workspace.task(task)?.state == .next)
    }

    // MARK: - Runs (T135)

    @Test("020-SC-007 an offline quick review with 3 decisions keeps its counts")
    func quickReviewOffline() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        let tasks = try ["A", "B", "C"].map { try nextTask($0, in: workspace) }
        clock.advance(by: 15 * Self.day)
        let screens = workspace.reviewEntryScreens(for: .widgetDecisions)
        #expect(screens.last == .quickReview(start: .decisions, skipping: [.wins, .inbox]))
        let session = try workspace.startReview(mode: .quick, entry: .widgetDecisions, skipping: [.wins, .inbox])
        try workspace.recordReviewProgress(session, activeStep: .decisions, activeSeconds: 30, snapshotDecisionQueue: true)
        try workspace.decide(.complete, on: tasks[0], sessionID: session)
        try workspace.decide(.someday, on: tasks[1], sessionID: session)
        try workspace.decide(.cancel, on: tasks[2], sessionID: session)
        try workspace.finishReview(session, clearStart: .yes)
        let run = try #require(workspace.state.review.sessions[session])
        #expect(run.status == .completed)
        #expect(run.counts[.done] == 1 && run.counts[.someday] == 1 && run.counts[.cancelled] == 1)
        #expect(run.decisionQueue == tasks.sorted())
        #expect(workspace.lastCountedReview() != nil)
        await workspace.flush()
        #expect(workspace.state == workspace.replayedState)
    }

    // MARK: - Device zone (T151)

    @Test("020-FR-035 020-FR-046 the zone is sent only after the device's own zone changed")
    func deviceZone() async throws {
        let workspace = await loadedWorkspace()
        workspace.accountlessReviewEnabled = true
        var zone = Self.berlin
        workspace.deviceTimeZone = { [zone] in zone }
        #expect(!workspace.sendDeviceTimeZoneIfChanged(), "first sight: recorded, not sent")
        #expect(workspace.localReview.lastObservedTimeZone == "Europe/Berlin")
        #expect(!workspace.sendDeviceTimeZoneIfChanged())
        zone = Self.newYork
        workspace.deviceTimeZone = { [zone] in zone }
        #expect(workspace.sendDeviceTimeZoneIfChanged())
        #expect(!workspace.sendDeviceTimeZoneIfChanged(), "sent once")
        await workspace.flush()
        let changes = workspace.document.outbox.compactMap { operation -> String? in
            if case .review(.updateSettings(let change)) = operation.command { change.timeZone } else { nil }
        }
        #expect(changes == ["America/New_York"])
        #expect(workspace.state.review.settings.timeZone == "America/New_York")
    }

    @Test("020-FR-036 signed in, the reminder and shown next review use the device zone, classification the stored one")
    func zonesForWhat() async throws {
        let clock = TestClock(Date(timeIntervalSince1970: 1_791_100_800))  // 2026-10-04, a Sunday
        let workspace = await loadedWorkspace(clock: clock)
        workspace.deviceTimeZone = { Self.newYork }
        let fire = try #require(workspace.nextReviewReminder())
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = Self.newYork
        let parts = calendar.dateComponents([.weekday, .hour, .minute], from: fire)
        #expect(parts.weekday == 6 && parts.hour == 16 && parts.minute == 0, "Friday 16:00 New York time")
        #expect(workspace.classificationZone == "America/New_York", "account-less: the device zone")
    }

    // MARK: - Against the fake server (T089, T091, T151)

    @Test("020-FR-012 020-FR-013 a device clock 2 days ahead, online: no local park, no M-09 entry, never re-issued")
    func clockAheadOnline() async throws {
        let world = World()
        world.server.setWeeklyReview(email: World.email, enabled: true)
        let skewed = ManualClock()
        skewed.set(world.clock.now().addingTimeInterval(2 * Self.day))
        let store = InMemoryDocumentStore()
        let transport = world.server.makeTransport()
        let scheduler = ManualSyncScheduler()
        let engine = SyncEngine(
            store: store, tokenStore: InMemorySessionTokenStore(), transport: transport, now: skewed.provider,
            configuration: SyncConfiguration(scheduler: scheduler, jitter: { 0.5 }, clientVersion: "test")
        )
        let ids = IDSequence(namespace: 7)
        let workspace = Workspace(store: store, sync: engine, now: skewed.provider, makeID: { ids.next() })
        await workspace.load()
        try await workspace.signIn(serverURL: FakeBrainBuddyServer.baseURL, email: World.email, password: World.password)
        await workspace.syncNow()
        #expect(workspace.reviewExposed)
        try workspace.acknowledgeExplainer()
        let task = try workspace.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        await workspace.syncNow()
        #expect(abs((workspace.localReview.serverClockOffset ?? 0) + 2 * Self.day) < 5)

        // 20 days on the server, 22 on the device clock: the device sees the
        // server's instant through the offset, so nothing is due yet.
        world.clock.advance(by: 20 * Self.day)
        skewed.advance(by: 20 * Self.day)
        #expect(workspace.formulationClass(of: task) == .movesTomorrow)
        #expect(workspace.applyDueAutoParks() == 0)
        // Even a park the device issues online is shown only once applied.
        let formulation = try #require(workspace.task(task)?.formulation?.id)
        try workspace.perform(.autoParkTask(.init(taskID: task, formulationID: formulation, observedAt: skewed.now(), optimistic: false)))
        #expect(workspace.task(task)?.state == .next)
        await workspace.syncNow()
        #expect(workspace.task(task)?.state == .next, "applied: false, the server's Next task wins")
        #expect(workspace.unseenParks().isEmpty)
        #expect(workspace.issues.isEmpty)
        #expect(world.snapshot.tasks.values.first?.state == .next)
    }

    @Test("020-FR-035 two devices in different zones syncing repeatedly: the stored zone changes once")
    func twoZones() async throws {
        let world = World()
        world.server.setWeeklyReview(email: World.email, enabled: true)
        let phone = await world.device()
        phone.workspace.deviceTimeZone = { Self.berlin }
        try await phone.signIn()
        try phone.workspace.acknowledgeExplainer()
        _ = try phone.workspace.capture(CaptureDraft(text: "Pay rent", list: .next, dueDate: CalendarDay(year: 2026, month: 10, day: 30)))
        await phone.workspace.syncNow()
        let tablet = await world.device()
        tablet.workspace.deviceTimeZone = { Self.newYork }
        try await tablet.signIn()
        for _ in 0..<3 {
            tablet.workspace.runReviewUpkeep()
            await tablet.workspace.syncNow()
            phone.workspace.runReviewUpkeep()
            await phone.workspace.syncNow()
            world.clock.advance(by: 3_600)
        }
        var settings = world.server.reviewSnapshot(email: World.email).settings
        #expect(settings.timeZone == "Europe/Berlin", "the tablet only recorded its zone")
        #expect(tablet.workspace.localReview.lastObservedTimeZone == "America/New_York")
        let floorBefore = world.snapshot.tasks.values.first?.formulation?.parkFloorAt

        phone.workspace.deviceTimeZone = { Self.newYork }
        for _ in 0..<3 {
            phone.workspace.runReviewUpkeep()
            await phone.workspace.syncNow()
            tablet.workspace.runReviewUpkeep()
            await tablet.workspace.syncNow()
            world.clock.advance(by: 3_600)
        }
        settings = world.server.reviewSnapshot(email: World.email).settings
        #expect(settings.timeZone == "America/New_York")
        let zoneWrites = (phone.transport.exchanges + tablet.transport.exchanges).filter {
            $0.request.method == .put && ($0.request.body.map { String(decoding: $0, as: UTF8.self) } ?? "").contains("time_zone")
        }
        #expect(zoneWrites.count == 1, "the stored zone changed once")
        let floorAfter = world.snapshot.tasks.values.first?.formulation?.parkFloorAt
        #expect(floorAfter != nil && floorAfter != floorBefore, "the due-dated task's floor was raised")
        #expect(phone.workspace.issues.isEmpty && tablet.workspace.issues.isEmpty)
    }

    @Test("020-FR-014 020-FR-040 linking an account-less install: local parks stay in Someday, extensions dropped and listed", arguments: [false, true])
    func accountLinking(modern: Bool) async throws {
        let world = World()
        world.server.setWeeklyReview(email: World.email, enabled: true)
        let phone = await world.device()
        let workspace = phone.workspace
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { Self.berlin }
        try workspace.acknowledgeExplainer()
        let parked = try (0..<3).map { try workspace.capture(CaptureDraft(text: "Old \($0)", list: .next)) }
        world.clock.advance(by: 10 * Self.day)
        let reformulate = try workspace.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        let waiting = try workspace.capture(CaptureDraft(text: "Get the quote", list: .next))
        let extended = try workspace.capture(CaptureDraft(text: "Call the landlord", list: .next))
        // The old tasks park (one batch seen on M-09).
        world.clock.advance(by: 11 * Self.day)
        #expect(workspace.applyDueAutoParks() == 0)
        world.clock.advance(by: Self.day + 60)
        #expect(workspace.applyDueAutoParks() == 3)
        try workspace.dismissWhileAway(shown: workspace.unseenParkAcks())
        // The newer ones ask (15 days in): two decisions and an extension.
        world.clock.advance(by: 3 * Self.day)
        let attempt = modern ? try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL) : nil
        try workspace.decide(.reformulate, on: reformulate, title: "Measure the bathroom wall")
        try workspace.decide(.waiting, on: waiting, waitingFor: "Ann")
        try workspace.decide(.extend, on: extended, reason: "The landlord is away")
        await workspace.flush()

        if let attempt {
            let outcome = try await workspace.completeSignIn(attempt, credential: .password(email: World.email, password: World.password))
            guard case .signedIn = outcome else { Issue.record("Expected signed in"); return }
        } else {
            try await phone.signIn()
        }
        await phone.workspace.syncNow()

        let server = world.snapshot.tasks.values
        for title in ["Old 0", "Old 1", "Old 2"] {
            let task = try #require(server.first { $0.title == title })
            #expect(task.state == .someday && task.parked == nil)
        }
        #expect(server.first { $0.title == "Measure the bathroom wall" }?.state == .next)
        #expect(server.first { $0.title == "Get the quote" }?.state == .waiting)
        #expect(server.first { $0.title == "Call the landlord" }?.state == .next)
        #expect(world.server.reviewSnapshot(email: World.email).decisionIDs.count == 2, "the extension was never sent")
        #expect(!phone.transport.exchanges.contains { exchange in
            (exchange.response?.body).map { String(decoding: $0, as: UTF8.self).contains("extension_not_due") } ?? false
        })
        #expect(workspace.unseenParks().isEmpty)
        #expect(workspace.linkedExtensionNotices == [extended])
        #expect(workspace.issues.isEmpty)
        #expect(parked.allSatisfy { workspace.task($0)?.state == .someday })
        try workspace.dismissWhileAway(shown: workspace.unseenParkAcks())
        #expect(workspace.linkedExtensionNotices.isEmpty)
    }

    // MARK: - Review round on 3e0f799

    @Test("020-FR-043 020-FR-052 local retention and idle close run while the review is hidden")
    func retentionWithReviewHidden() async throws {
        let store = InMemoryDocumentStore()
        let clock = TestClock()
        let workspace = try await activatedWorkspace(store: store, clock: clock)
        let task = try nextTask("Renovate the bathroom", in: workspace)
        clock.advance(by: 15 * Self.day)
        let session = try workspace.startReview(mode: .quick, entry: .list)
        let decision = try workspace.decide(.someday, on: task, sessionID: session)
        workspace.saveDraft("Order tiles", for: .projectNextAction("p1"))
        await workspace.flush()

        // The release switch is turned off; a week later the app starts.
        clock.advance(by: 7 * Self.day + 60)
        let hidden = await loadedWorkspace(store: store, clock: clock, ids: IDSequence(namespace: 2))
        #expect(!hidden.reviewExposed)
        await hidden.flush()
        #expect(hidden.localReview.formDrafts.isEmpty, "drafts expire with the review hidden")
        #expect(hidden.state.review.decisions[decision]?.undo == nil, "undo snapshots are nulled with the review hidden")
        #expect(hidden.state.review.sessions[session]?.status == .partial, "idle runs close with the review hidden")
        #expect(hidden.document.outbox.allSatisfy { if case .autoParkTask = $0.command { false } else { true } })
    }

    @Test("020-FR-029 020-FR-043 review upkeep replays nothing, with or without a recorded idle close")
    func upkeepDoesNotReplay() async throws {
        let clock = TestClock()
        let workspace = try await activatedWorkspace(clock: clock)
        for n in 0..<20 { _ = try nextTask("Task \(n)", in: workspace) }
        await workspace.flush()
        let replays = workspace.fullReplayCount
        workspace.runReviewUpkeep()
        workspace.runReviewUpkeep()
        #expect(workspace.fullReplayCount == replays, "nothing to close: no replay")

        let session = try workspace.startReview(mode: .quick, entry: .list)
        clock.advance(by: 7 * Self.day + 60)
        workspace.runReviewUpkeep()
        await workspace.flush()
        #expect(workspace.localReview.idleClosedSessions == [session])
        #expect(workspace.state.review.sessions[session]?.status == .abandoned)
        let afterClose = workspace.fullReplayCount
        workspace.runReviewUpkeep()
        workspace.runReviewUpkeep()
        #expect(workspace.fullReplayCount == afterClose, "a recorded close is read from the state: no replay")
        #expect(workspace.localReview.idleClosedSessions == [session], "still open underneath: kept")
        #expect(workspace.state == workspace.replayedState.closingIdle(workspace.localReview))
    }

    @Test("020-FR-015 020-FR-030 lists go out within the server limits: 200 park acknowledgements, 500 tasks per release")
    func requestLimits() async throws {
        var base = GTDState()
        for n in 0..<201 {
            var task = Fixture.serverTask(TaskID("p\(n)"), "Parked \(n)", state: .someday)
            task.parked = ParkMarker(at: Fixture.epoch, formulationID: FormulationID.make(UUID()))
            base.tasks[task.id] = task
        }
        for n in 0..<501 { base.tasks[TaskID("i\(n)")] = Fixture.serverTask(TaskID("i\(n)"), "Idea \(n)", state: .inbox) }
        var document = StoreDocument(base: base)
        document.generation = 1
        let store = InMemoryDocumentStore(document: document)
        let workspace = await loadedWorkspace(store: store)
        workspace.accountlessReviewEnabled = true
        #expect(workspace.unseenParks().count == 201)
        try workspace.dismissWhileAway(shown: workspace.unseenParkAcks())
        #expect(workspace.unseenParks().isEmpty)
        let ids = try workspace.bulkRelease(.inboxRemainder, taskIDs: (0..<501).map { TaskID("i\($0)") })
        #expect(ids.count == 2)
        await workspace.flush()
        let sizes = workspace.document.outbox.compactMap { operation -> Int? in
            switch operation.command {
            case .review(.acknowledgeParks(let items)): items.count
            case .bulkRelease(let release): release.taskIDs.count
            default: nil
            }
        }
        #expect(sizes == [200, 1, 500, 1])
        #expect((0..<501).allSatisfy { workspace.task(TaskID("i\($0)"))?.state == .someday })
        try workspace.undoBulkRelease(ids)
        #expect((0..<501).allSatisfy { workspace.task(TaskID("i\($0)"))?.state == .inbox })
    }

    @Test("020-FR-014 a failed linking step stops sign-in and leaves the device account-less and consistent", arguments: [false, true])
    func linkingFailureStopsSignIn(modern: Bool) async throws {
        let store = ControlledStore()
        let legacy = FakeSyncService(store: store)
        let server = FakeBrainBuddyServer()
        _ = server.addAccount(email: "ana@example.com", password: "pw")
        let transport = server.makeTransport()
        let engine = SyncEngine(store: store, tokenStore: InMemorySessionTokenStore(), transport: transport)
        let sync: any SyncService = modern ? engine : legacy
        let clock = TestClock()
        let workspace = makeWorkspace(store: store, sync: sync, clock: clock)
        await workspace.load()
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { Self.berlin }
        try workspace.acknowledgeExplainer()
        let task = try nextTask("Renovate the bathroom", in: workspace)
        clock.advance(by: 20 * Self.day + 3_600)
        #expect(workspace.applyDueAutoParks() == 0)
        clock.advance(by: Self.day)
        #expect(workspace.applyDueAutoParks() == 1)
        await workspace.flush()
        let attempt = modern ? try await workspace.beginSignIn(serverURL: FakeBrainBuddyServer.baseURL) : nil
        let before = try #require(try await store.load())

        await store.failWrites(with: .io("disk full"))
        await #expect(throws: WorkspaceError.self) {
            if let attempt {
                _ = try await workspace.completeSignIn(attempt, credential: .password(email: "ana@example.com", password: "pw"))
            } else {
                try await workspace.signIn(serverURL: Fixture.serverURL, email: "ana@example.com", password: "pw")
            }
        }
        #expect(await legacy.calls.allSatisfy { if case .signIn = $0 { false } else { true } }, "nothing is uploaded")
        #expect(!transport.requests.contains { $0.url.path == "/api/auth/login" }, "conversion fails before authentication or upload")
        #expect(workspace.account == nil)
        await store.failWrites(with: nil)
        let after = try #require(try await store.load())
        #expect(after.outbox == before.outbox, "the outbox is unchanged")
        #expect(workspace.task(task)?.state == .someday)
        #expect(workspace.state == workspace.replayedState)
    }

    @Test("020-FR-014 020-FR-040 linking a store migrated from v1: decisions on formulations the device derived are applied")
    func linkingV1Store() async throws {
        let world = World()
        world.server.setWeeklyReview(email: World.email, enabled: true)
        // A version 1 store: tasks created before spec 020 (no client formulation ids).
        let old = await loadedWorkspace(clock: TestClock(world.clock.now()))
        let waiting = try old.capture(CaptureDraft(text: "Get the quote", list: .next))
        let reformulate = try old.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        await old.flush()
        var object = try #require(
            try JSONSerialization.jsonObject(with: StoreDocumentCoding.encode(old.document)) as? [String: Any]
        )
        object["version"] = 1
        object["local"] = nil
        var base = try #require(object["base"] as? [String: Any])
        base["review"] = nil
        object["base"] = base
        let directory = try makeTemporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("store.json")
        try JSONSerialization.data(withJSONObject: object).write(to: url)

        let phone = await world.device(store: FileDocumentStore(fileURL: url))
        let workspace = phone.workspace
        #expect(workspace.loadError == nil)
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { Self.berlin }
        try workspace.acknowledgeExplainer()
        world.clock.advance(by: 15 * Self.day)
        try workspace.decide(.waiting, on: waiting, waitingFor: "Ann")
        try workspace.decide(.reformulate, on: reformulate, title: "Measure the bathroom wall")
        await workspace.flush()

        try await phone.signIn()
        await workspace.syncNow()
        #expect(workspace.issues.isEmpty, "\(workspace.issues.map(\.message))")
        let server = world.snapshot.tasks.values
        #expect(server.first { $0.title == "Get the quote" }?.state == .waiting)
        #expect(server.first { $0.title == "Measure the bathroom wall" }?.state == .next)
        #expect(world.server.reviewSnapshot(email: World.email).decisionIDs.count == 2)
    }
}

extension GTDState {
    /// `state` as the workspace shows it: the replay with the device's idle closes.
    func closingIdle(_ local: LocalReviewState) -> GTDState {
        var copy = self
        ReviewSessionUpkeep.closeIdle(local.idleClosedSessions, in: &copy)
        return copy
    }
}
