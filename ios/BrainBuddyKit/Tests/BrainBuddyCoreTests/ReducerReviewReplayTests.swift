import BrainBuddyCore
import Foundation
import Testing

/// Review commands replayed onto pulled state, decision field rules against
/// http §3, list caps and E3 qualifying activity (review round on 3e0f799).
@Suite("GTDReducer: review replay and decision rules (spec 020)")
struct ReducerReviewReplayTests {
    let t0 = Review.instant("2026-09-10T09:00:00Z")

    // MARK: - B1: a decision is never rejected locally during replay

    @Test(
        "020-FR-011 020-SC-007 a queued decision the pulled task already reflects stays queued for the server, not rejected",
        arguments: [DecisionType.someday, .complete, .reformulate]
    )
    func decisionOnDecidedTaskStaysQueued(_ type: DecisionType) throws {
        var decided = Review.nextTask("t1", title: "Renovate the bathroom", started: t0, serverRevision: 2)
        switch type {
        case .someday:
            decided.state = .someday
            decided.formulation = nil
        case .complete:
            decided.state = .completed
            decided.formulation = nil
        default:
            decided.title = "Call the tiler"
            decided.formulation = FormulationClock(id: Review.form(2), startedAt: Review.now)
        }
        let base = Review.state([decided])
        var operation = Review.op(
            Review.decide(
                type, "t1", formulation: Review.form(1), title: type == .reformulate ? "Call the tiler" : nil,
                newFormulation: type == .reformulate ? Review.form(2) : nil
            ),
            at: Review.now
        )
        for sent in [false, true] {
            operation.attempts = sent ? 1 : 0
            let result = OutboxReplayer.replay([operation], onto: base)
            #expect(result.rejected.isEmpty, "the server answers this decision, not the replay (sent: \(sent))")
            #expect(result.outbox.map(\.id) == [operation.id])
            #expect(result.state.tasks["t1"] == decided, "the pulled task is shown as it is")
        }
    }

    // MARK: - N1: an Undo of a decision whose snapshot only the server has

    @Test("020-FR-048 a queued Undo of a decision known only from the server's answer waits for the server, not refused")
    func undoOfServerOnlyDecisionStaysQueued() throws {
        var task = Review.nextTask("t1", started: t0, serverRevision: 2)
        task.state = .someday
        task.formulation = nil
        var base = Review.state([task])
        base.review.decisions[Review.decision(1)] = ReviewDecision(
            id: Review.decision(1), taskID: "t1", type: .someday, decidedAt: Review.now, undo: nil, taskAfter: TaskStamp(task),
            snapshotOnServer: true
        )
        let undo = Review.op(.undoDecision(Review.decision(1)), at: Review.now.addingTimeInterval(5))
        let result = OutboxReplayer.replay([undo], onto: base)
        #expect(result.rejected.isEmpty)
        #expect(result.outbox.map(\.id) == [undo.id])
        #expect(result.state == base, "nothing to restore on the device; the server answers")

        // A snapshot this device dropped (retention) is still refused.
        var purged = base
        purged.review.decisions[Review.decision(1)]?.snapshotOnServer = false
        #expect(OutboxReplayer.replay([undo], onto: purged).rejected.map(\.error) == [.undoUnavailable])
    }

    // MARK: - N5: operations on a follow-up whose decision waits for the server

    @Test("020-FR-010 edits queued on a follow-up whose decision the replay keeps unapplied wait with it")
    func followUpEditsWait() throws {
        var done = Review.task("w1", title: "Quote from Ann", state: .completed)
        done.serverID = "task_w1"
        done.serverRevision = 3
        let base = Review.state([done])
        let followUp: TaskID = "task_00000000-0000-4000-8000-000000000009"
        let decide = Review.op(
            Review.decide(.followUp, "w1", title: "Ask Ann", newFormulation: Review.form(2), followUp: followUp), at: Review.now
        )
        let note = Review.op(
            .createSubtask(.init(taskID: followUp, subtaskID: "s1", title: "Find her number")), at: Review.now.addingTimeInterval(1)
        )
        let result = OutboxReplayer.replay([decide, note], onto: base)
        #expect(result.rejected.isEmpty, "the edit waits with its decision, not refused as taskNotFound")
        #expect(result.outbox.map(\.id) == [decide.id, note.id])
        #expect(result.state.tasks[followUp] == nil)

        // The server's answer brings the follow-up: the edit then applies.
        var answered = base
        answered.tasks[followUp] = Review.task(followUp, title: "Ask Ann", state: .next)
        let after = OutboxReplayer.replay([note], onto: answered)
        #expect(after.rejected.isEmpty)
        #expect(after.state.tasks[followUp]?.subtasks.map(\.title) == ["Find her number"])

        // A follow-up nobody waits for is still refused.
        let orphan = OutboxReplayer.replay([note], onto: base)
        #expect(orphan.rejected.map(\.error) == [.taskNotFound])
    }

    // MARK: - B2 / Codex 1: a yield with an unknown clock_before

    @Test("020-FR-009 020-FR-012 an extension made before a server park whose clock the device lacks is replayed, not refused")
    func extensionYieldWithoutClockBefore() throws {
        var parked = Review.nextTask("t1", started: t0, serverRevision: 3)
        parked.state = .someday
        parked.formulation = nil
        let parkedAt = t0.addingTimeInterval(21 * Review.day + 3_600)
        parked.parked = ParkMarker(at: parkedAt, formulationID: Review.form(1), fromRevision: nil, clockBefore: nil, stalledBefore: 0)
        var state = Review.state([parked])
        let decidedAt = t0.addingTimeInterval(20 * Review.day)
        let outcome = try Review.apply(
            Review.decide(.extend, "t1", formulation: Review.form(1), reason: "The landlord is away"), at: decidedAt,
            to: &state, mode: .replay
        )
        #expect(outcome == .applied)
        let task = try #require(state.tasks["t1"])
        #expect(task.state == .next && task.parked == nil)
        #expect(task.formulation?.extendedAt == decidedAt)
        #expect(state.review.decisions[Review.decision(1)]?.yieldedAutoPark == true)
    }

    @Test("020-FR-009 an extension the device can check is still refused when it is not due")
    func extensionStillCheckedWhenClockKnown() {
        var state = Review.state([Review.nextTask("t1", started: Review.now.addingTimeInterval(-3 * Review.day))])
        #expect(
            Review.error {
                try Review.apply(Review.decide(.extend, "t1", formulation: Review.form(1), reason: "x"), to: &state)
            } == .extensionNotDue
        )
    }

    // MARK: - Codex 3: fields http requires are required here too

    @Test("020-FR-010 return to Next needs a title, as http requires; nothing changes when it is missing")
    func returnToNextNeedsTitle() {
        var waiting = Review.task("w1", title: "Quote from Ann", state: .waiting)
        waiting.waitingFor = "Ann"
        let state = Review.state([waiting])
        var working = state
        #expect(Review.error { try Review.apply(Review.decide(.returnToNext, "w1", newFormulation: Review.form(3)), to: &working) } == .emptyTitle)
        #expect(working == state)
    }

    @Test(
        "020-FR-010 every decision type rejects a missing field http requires",
        arguments: [
            (DecisionType.reformulate, GTDValidationError.emptyTitle), (.firstStep, .emptyTitle),
            (.waiting, .waitingForRequired), (.extend, .extensionReasonRequired), (.followUp, .emptyTitle),
            (.returnToNext, .emptyTitle),
        ]
    )
    func requiredFields(_ type: DecisionType, _ expected: GTDValidationError) {
        var next = Review.nextTask("t1", started: t0)
        if type == .followUp || type == .returnToNext {
            next.state = .waiting
            next.waitingFor = "Ann"
            next.formulation = nil
        }
        var state = Review.state([next])
        let before = state
        let error = Review.error {
            try Review.apply(
                Review.decide(
                    type, "t1", formulation: type.decidesOnFormulation ? Review.form(1) : nil, newFormulation: Review.form(2),
                    followUp: type == .followUp ? "task_00000000-0000-4000-8000-000000000009" : nil
                ),
                to: &state
            )
        }
        #expect(error == expected)
        #expect(state == before)
    }

    // MARK: - Codex 4: archived project

    @Test("020-FR-010 return to Next into an archived project is refused, as follow-up is", arguments: [TaskState.waiting, .someday])
    func returnToNextArchivedProject(_ list: TaskState) {
        var task = Review.task("w1", title: "Quote from Ann", state: list)
        task.waitingFor = list == .waiting ? "Ann" : nil
        task.projectID = "old"
        var state = Review.state([task])
        state.projects["old"] = ProjectRecord(id: "old", name: "Old flat", state: .archived, createdAt: t0)
        let before = state
        #expect(
            Review.error {
                try Review.apply(
                    Review.decide(.returnToNext, "w1", title: "Ask Ann", newFormulation: Review.form(3)), to: &state
                )
            } == .projectArchived
        )
        #expect(state == before)
    }

    // MARK: - Server list limits

    @Test("020-FR-017 020-FR-015 a bulk release is at most 500 tasks and a park acknowledgement at most 200 items")
    func listCaps() {
        var state = Review.state([])
        let tooMany = (0...500).map { TaskID("t\($0)") }
        #expect(
            Review.error { try Review.apply(.bulkRelease(.init(bulkID: Review.bulk(1), kind: .inboxRemainder, taskIDs: tooMany)), to: &state) }
                == .tooManyItems
        )
        let acks = (0...200).map { ParkAck(taskID: TaskID("t\($0)"), formulationID: Review.form($0 + 1)) }
        #expect(Review.error { try Review.apply(.review(.acknowledgeParks(acks)), to: &state) } == .tooManyItems)
        #expect(!GTDValidationError.tooManyItems.message.isEmpty)
    }

    // MARK: - Bounded device copy

    @Test("020-FR-043 020-FR-017 once a bulk release is undone no released item keeps its pre-release clock")
    func undoneBulkReleaseKeepsNoClock() throws {
        let extended = Review.nextTask(
            "t1", started: Review.now.addingTimeInterval(-30 * Review.day), extendedAt: Review.now.addingTimeInterval(-15 * Review.day)
        )
        var state = Review.state([extended])
        try Review.apply(.bulkRelease(.init(bulkID: Review.bulk(1), kind: .restart, taskIDs: ["t1"])), to: &state)
        #expect(state.review.bulkReleases[Review.bulk(1)]?.released.first?.clockBefore?.clock.extensionReason != nil)
        try Review.apply(.undoBulkRelease(Review.bulk(1)), at: Review.now.addingTimeInterval(30), to: &state)
        let record = try #require(state.review.bulkReleases[Review.bulk(1)])
        #expect(record.undoneAt != nil && record.released.allSatisfy { $0.clockBefore == nil }, "the reason text does not outlive the Undo")
        #expect(state.tasks["t1"]?.formulation == extended.formulation, "the clock itself came back")
    }

    @Test("020-FR-017 a restart item whose clock only the server holds is never put back into Next without one")
    func undoWithoutAKnownClockLeavesTheTaskForTheServer() throws {
        var released = Review.nextTask("t1", started: Review.now.addingTimeInterval(-30 * Review.day), serverRevision: 5)
        released.state = .someday
        released.formulation = nil
        var state = Review.state([released])
        let item = BulkReleasedTask(
            taskID: "t1", previousState: .next, clockBefore: nil, taskAfter: TaskStamp(released), clockKnown: false
        )
        state.review.bulkReleases[Review.bulk(1)] = BulkReleaseRecord(
            id: Review.bulk(1), kind: .restart, sessionID: nil, createdAt: Review.now, released: [item], skipped: []
        )
        try Review.apply(.undoBulkRelease(Review.bulk(1)), at: Review.now.addingTimeInterval(30), to: &state)
        #expect(state.tasks["t1"]?.state == .someday, "the server's answer brings it back with its clock")
        #expect(state.review.bulkReleases[Review.bulk(1)]?.undoneAt != nil)
    }

    @Test("020-FR-043 retention bounds the device copy: snapshots always, history only when the server keeps it")
    func retentionBounds() throws {
        let now = Review.now
        let old = now.addingTimeInterval(-8 * Review.day)
        let task = Review.nextTask("t1", started: t0)
        func decision(_ n: Int, at date: Date) -> ReviewDecision {
            ReviewDecision(
                id: Review.decision(n), taskID: "t1", type: .extend, decidedAt: date, reasonText: "Quote first",
                undo: DecisionUndo(taskBefore: task), taskAfter: TaskStamp(task)
            )
        }
        let released = BulkReleasedTask(
            taskID: "t1", previousState: .next, clockBefore: ReleasedClock(clock: task.formulation!, stalledBefore: 0),
            taskAfter: TaskStamp(task)
        )
        func bulk(_ n: Int, at date: Date) -> BulkReleaseRecord {
            BulkReleaseRecord(id: Review.bulk(n), kind: .restart, sessionID: nil, createdAt: date, released: [released], skipped: [])
        }
        var ended = ReviewSession(id: Review.session(1), mode: .quick, entry: .list, origin: .ios, status: .completed, startedAt: old, endedAt: old)
        ended.appliedProgress = [Review.progress(1)]
        var ancient = ended
        ancient.id = Review.session(2)
        ancient.endedAt = now.addingTimeInterval(-40 * Review.day)
        var open = ReviewSession(id: Review.session(3), mode: .quick, entry: .list, origin: .ios, startedAt: now)
        open.appliedProgress = [Review.progress(2)]
        let review = ReviewState(
            sessions: [ended.id: ended, ancient.id: ancient, open.id: open],
            decisions: [Review.decision(1): decision(1, at: old), Review.decision(2): decision(2, at: now)],
            bulkReleases: [Review.bulk(1): bulk(1, at: old), Review.bulk(2): bulk(2, at: now)]
        )

        var accountless = review
        ReviewRetention.apply(to: &accountless, now: now, signedIn: false)
        #expect(accountless.decisions[Review.decision(1)]?.undo == nil)
        #expect(accountless.decisions[Review.decision(1)]?.reasonText == "Quote first", "account-less, the reason is the only copy")
        #expect(accountless.decisions[Review.decision(2)]?.undo != nil)
        #expect(accountless.bulkReleases[Review.bulk(1)]?.released.first?.clockBefore == nil)
        #expect(accountless.bulkReleases[Review.bulk(2)]?.released.first?.clockBefore != nil)
        #expect(accountless.sessions.count == 3)
        #expect(accountless.sessions[ended.id]?.appliedProgress.isEmpty == true)
        #expect(accountless.sessions[open.id]?.appliedProgress == [Review.progress(2)])

        var signedIn = review
        ReviewRetention.apply(to: &signedIn, now: now, signedIn: true)
        #expect(Set(signedIn.decisions.keys) == [Review.decision(2)])
        #expect(Set(signedIn.bulkReleases.keys) == [Review.bulk(2)])
        #expect(Set(signedIn.sessions.keys) == [ended.id, open.id])
        #expect(!ReviewRetention.isDue(signedIn, now: now, signedIn: true))
    }

    // MARK: - N2: retention keeps a decision a queued Undo names

    @Test("020-FR-043 020-FR-048 signed in, retention keeps a decision a queued Undo names, without its snapshot")
    func retentionKeepsDecisionAQueuedUndoNames() throws {
        let now = Review.now
        let old = now.addingTimeInterval(-8 * Review.day)
        let task = Review.nextTask("t1", started: t0)
        let decided = ReviewDecision(
            id: Review.decision(1), taskID: "t1", type: .someday, decidedAt: old, undo: DecisionUndo(taskBefore: task),
            taskAfter: TaskStamp(task)
        )
        var review = ReviewState(decisions: [decided.id: decided])
        #expect(ReviewRetention.isDue(review, now: now, signedIn: true, keeping: [decided.id]), "the snapshot still expires")
        ReviewRetention.apply(to: &review, now: now, signedIn: true, keeping: [decided.id])
        #expect(review.decisions[decided.id] != nil, "kept, so the queued Undo is not replayed as already done")
        #expect(review.decisions[decided.id]?.undo == nil, "the 7-day snapshot bound still holds")
        #expect(review.decisions[decided.id]?.snapshotOnServer == true, "an acknowledged decision: the server answers")
        #expect(!ReviewRetention.isDue(review, now: now, signedIn: true, keeping: [decided.id]))

        // Its Undo stays queued for the server instead of vanishing as satisfied.
        var base = Review.state([task])
        base.review = review
        let undo = Review.op(.undoDecision(decided.id), at: now)
        let result = OutboxReplayer.replay([undo], onto: base)
        #expect(result.rejected.isEmpty)
        #expect(result.outbox.map(\.id) == [undo.id])

        // Once no Undo names it, the record goes as before.
        ReviewRetention.apply(to: &review, now: now, signedIn: true)
        #expect(review.decisions.isEmpty)

        // Account-less there is no server copy: the record stays unmarked.
        var accountless = ReviewState(decisions: [decided.id: decided])
        ReviewRetention.apply(to: &accountless, now: now, signedIn: false, keeping: [decided.id])
        #expect(accountless.decisions[decided.id]?.undo == nil)
        #expect(accountless.decisions[decided.id]?.snapshotOnServer == false)
    }

    // MARK: - Round 4: an unsent pair compaction kept keeps its snapshot

    @Test("020-FR-017 020-FR-043 020-FR-048 an unsent decision or release a queued Undo names keeps asking for its snapshot")
    func outboxSnapshotsAQueuedUndoNeeds() throws {
        let now = Review.now
        let old = now.addingTimeInterval(-8 * Review.day)
        let decide = Review.op(Review.decide(.someday, "t1", decision: 1), at: old)
        let otherDecide = Review.op(Review.decide(.someday, "t2", decision: 2), at: old)
        let release = Review.op(.bulkRelease(.init(bulkID: Review.bulk(1), kind: .restart, taskIDs: ["t3"])), at: old)
        let otherRelease = Review.op(.bulkRelease(.init(bulkID: Review.bulk(2), kind: .restart, taskIDs: ["t4"])), at: old)
        let undos = ReviewRetention.QueuedUndos([
            Review.op(.undoDecision(Review.decision(1)), at: old), Review.op(.undoBulkRelease(Review.bulk(1)), at: old),
        ])
        #expect(undos.decisions == [Review.decision(1)] && undos.bulkReleases == [Review.bulk(1)])

        #expect(ReviewRetention.expiringSnapshot(of: decide, now: now, undos: undos) == nil, "its Undo needs it")
        #expect(ReviewRetention.expiringSnapshot(of: release, now: now, undos: undos) == nil, "its Undo needs it")
        // R15 still holds for the rest.
        guard case .decideTask(let expired)? = ReviewRetention.expiringSnapshot(of: otherDecide, now: now, undos: undos)?.command,
            case .bulkRelease(let expiredRelease)? = ReviewRetention.expiringSnapshot(of: otherRelease, now: now, undos: undos)?.command
        else {
            Issue.record("a snapshot no Undo needs should expire")
            return
        }
        #expect(!expired.undoRetained && !expiredRelease.undoRetained)
        // Inside the window, or already sent: untouched.
        let fresh = Review.op(Review.decide(.someday, "t2", decision: 2), at: now.addingTimeInterval(-6 * Review.day))
        #expect(ReviewRetention.expiringSnapshot(of: fresh, now: now, undos: undos) == nil)
        var sent = otherDecide
        sent.attempts = 1
        #expect(ReviewRetention.expiringSnapshot(of: sent, now: now, undos: undos) == nil)
    }

    @Test("020-FR-043 020-FR-048 replaying a decision and its Undo works with the kept snapshot and fails without it")
    func undoNeedsTheKeptSnapshot() throws {
        let task = Review.nextTask("t1", started: t0)
        let base = Review.state([task])
        let decide = Review.op(Review.decide(.someday, "t1", decision: 1, formulation: Review.form(1)), at: Review.now)
        let undo = Review.op(.undoDecision(Review.decision(1)), at: Review.now.addingTimeInterval(3))
        let kept = OutboxReplayer.replay([decide, undo], onto: base)
        #expect(kept.rejected.isEmpty)
        #expect(kept.state.tasks["t1"]?.state == .next)

        // What retention used to do to the decision: the Undo is then refused.
        var stripped = decide
        if case .decideTask(var command) = stripped.command {
            command.undoRetained = false
            stripped.command = .decideTask(command)
        }
        let lost = OutboxReplayer.replay([stripped, undo], onto: base)
        #expect(lost.rejected.map(\.error) == [.undoUnavailable])
        #expect(lost.state.tasks["t1"]?.state == .someday)
    }

    // MARK: - N3: recorded idle closes are read from the state

    @Test("020-FR-029 a recorded idle close stays while the run underneath is open and goes once it ended otherwise")
    func recordedIdleClosesFromState() throws {
        let started = Review.now.addingTimeInterval(-10 * Review.day)
        var open = ReviewSession(id: Review.session(1), mode: .quick, entry: .list, origin: .ios, startedAt: started)
        open.lastActivityAt = started
        var qualified = open
        qualified.id = Review.session(2)
        qualified.qualifyingActivity = true
        var finished = open
        finished.id = Review.session(3)
        finished.status = .completed
        finished.endedAt = Review.now
        var replaced = open
        replaced.id = Review.session(4)
        replaced.status = .abandoned
        replaced.endedAt = Review.now
        var elsewhere = open
        elsewhere.id = Review.session(5)
        elsewhere.status = .abandoned
        elsewhere.endedElsewhere = true
        let recorded = [open.id, qualified.id, finished.id, replaced.id, elsewhere.id, Review.session(6)]
        var replayed = GTDState()
        for session in [open, qualified, finished, replaced, elsewhere] { replayed.review.sessions[session.id] = session }

        // What a replay-based check keeps: the runs the replay still has open.
        let byReplay = recorded.filter { replayed.review.sessions[$0]?.status == .open }
        var shown = replayed
        ReviewSessionUpkeep.closeIdle(recorded, in: &shown)
        #expect(ReviewSessionUpkeep.recordedIdleCloses(recorded, in: shown) == byReplay)
        #expect(byReplay == [open.id, qualified.id])
    }

    // MARK: - E3 qualifying activity

    @Test("020-FR-029 finishing a step qualifies only when it had nothing to decide")
    func qualifyingActivity() throws {
        var state = Review.state([Review.task("i1", title: "Idea", state: .inbox)])
        try Review.apply(.review(.startSession(StartSession(sessionID: Review.session(1), mode: .full, entry: .list))), to: &state)
        try Review.apply(
            .review(.progressSession(SessionProgress(sessionID: Review.session(1), progressID: Review.progress(1), step: .inbox, stepStatus: .finished))),
            to: &state
        )
        #expect(state.review.sessions[Review.session(1)]?.qualifyingActivity == false, "the Inbox still had an item")
        try Review.apply(
            .review(.progressSession(SessionProgress(sessionID: Review.session(1), progressID: Review.progress(2), step: .wins, stepStatus: .finished))),
            to: &state
        )
        #expect(state.review.sessions[Review.session(1)]?.qualifyingActivity == true, "Wins has nothing to decide")
        #expect(ReviewRules.hasNothingToDecide(.inbox, in: Review.state([]), now: Review.now))
        #expect(!ReviewRules.hasNothingToDecide(.inbox, in: state, now: Review.now))
        #expect(!ReviewRules.hasNothingToDecide(.summary, in: state, now: Review.now), "the summary never qualifies")
    }
}
