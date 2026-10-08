import BrainBuddyCore
import Foundation
import Testing

/// Review queries (contracts/ios-commands.md §6; tasks.md T053, T133) and the
/// shared review-flow vectors they answer (`review_flow_vectors.json`).
@Suite("GTDQueries: weekly review (spec 020)")
struct QueriesReviewTests {
    static let flow = ReviewVectors.flow

    /// A task from a flow vector's task row.
    static func task(_ raw: VectorValue) -> TaskRecord {
        let id = TaskID(raw["id"]?.string ?? "")
        let state = raw["state"]?.string.flatMap(TaskState.init(rawValue:)) ?? .next
        let updated = ReviewVectors.instant(raw["updated_at"]) ?? Review.instant("2026-01-01T00:00:00Z")
        var task = TaskRecord(
            id: id, serverID: id.rawValue, serverRevision: raw["revision"]?.int ?? 1, title: id.rawValue, state: state,
            waitingSince: ReviewVectors.instant(raw["waiting_since"]), completedAt: ReviewVectors.instant(raw["completed_at"]),
            orderKey: 0, createdAt: updated, updatedAt: updated
        )
        if let parkedAt = ReviewVectors.instant(raw["parked_at"]) {
            task.parked = ParkMarker(at: parkedAt, formulationID: "form_parked")
        }
        return task
    }

    static func receipt(_ raw: VectorValue) -> ReviewReceipt {
        ReviewReceipt(
            taskID: TaskID(raw["task_id"]?.string ?? ""), kind: raw["kind"]?.string.flatMap(ReceiptKind.init(rawValue:)) ?? .waiting,
            reviewedAt: ReviewVectors.instant(raw["reviewed_at"]) ?? .distantPast,
            hiddenUntil: ReviewVectors.instant(raw["hidden_until"]) ?? .distantPast,
            source: raw["source"]?.string.flatMap(ReceiptSource.init(rawValue:)) ?? .keep, taskRevision: raw["task_revision"]?.int
        )
    }

    static func ids(_ value: VectorValue?) -> [TaskID] { value?.array.compactMap(\.string).map { TaskID($0) } ?? [] }

    // MARK: - Flow vectors

    @Test("020-FR-028 quick and full reviews have their fixed step order", arguments: ReviewVectors.section(flow, "steps"))
    func steps(_ vector: Vector) throws {
        let mode = try #require(vector["mode"]?.string.flatMap(ReviewMode.init(rawValue:)))
        #expect(mode.steps.map(\.rawValue) == vector["expect"]?.array.compactMap(\.string))
    }

    @Test("020-FR-028 wins are the tasks completed in the last 7 days", arguments: ReviewVectors.section(flow, "wins"))
    func wins(_ vector: Vector) throws {
        let now = try #require(ReviewVectors.instant(vector["now"]))
        let tasks = (vector["tasks"]?.array ?? []).map(Self.task)
        #expect(ReviewRules.wins(tasks, now: now).map(\.id) == Self.ids(vector["expect"]))
    }

    @Test("020-FR-031 the capacity mirror, with nothing but the Next count before 4 weeks", arguments: ReviewVectors.section(flow, "capacity"))
    func capacity(_ vector: Vector) throws {
        let mirror = CapacityMirror.compute(
            nextCount: vector["next_count"]?.int ?? 0,
            completedAt: (vector["completed_at"]?.array ?? []).compactMap { ReviewVectors.instant($0) },
            now: try #require(ReviewVectors.instant(vector["now"]))
        )
        let expect = try #require(vector["expect"])
        #expect(mirror.nextCount == expect["next_count"]?.int)
        #expect(mirror.weeksOfHistory == expect["weeks_of_history"]?.int)
        #expect(mirror.weeklyAverage4w == expect["weekly_average_4w"]?.double)
        #expect(mirror.impliedWeeks == expect["implied_weeks"]?.double)
    }

    @Test("020-FR-032 Waiting older than 7 days, unhidden, oldest first", arguments: ReviewVectors.section(flow, "waiting_queue"))
    func waitingQueue(_ vector: Vector) throws {
        let queue = ReviewRules.waitingQueue(
            (vector["tasks"]?.array ?? []).map(Self.task), receipts: (vector["receipts"]?.array ?? []).map(Self.receipt),
            now: try #require(ReviewVectors.instant(vector["now"]))
        )
        #expect(queue.map(\.id) == Self.ids(vector["expect"]))
    }

    @Test("020-FR-032 at most 7 Someday tasks, never reviewed first", arguments: ReviewVectors.section(flow, "someday_queue"))
    func somedayQueue(_ vector: Vector) throws {
        let queue = ReviewRules.somedayQueue(
            (vector["tasks"]?.array ?? []).map(Self.task), receipts: (vector["receipts"]?.array ?? []).map(Self.receipt),
            now: try #require(ReviewVectors.instant(vector["now"])), limit: vector["limit"]?.int ?? 7
        )
        #expect(queue.eligibleTotal == vector["expect"]?["eligible_total"]?.int)
        #expect(queue.shown.map(\.id) == Self.ids(vector["expect"]?["shown"]))
    }

    @Test("020-FR-017 restart mode: 21 days from the last counted review, or from onboarding", arguments: ReviewVectors.section(flow, "restart"))
    func restart(_ vector: Vector) throws {
        let restart = ReviewRules.restartMode(
            onboardedAt: ReviewVectors.instant(vector["onboarded_at"]),
            lastCountedReviewAt: ReviewVectors.instant(vector["last_counted_review_at"]),
            now: try #require(ReviewVectors.instant(vector["now"]))
        )
        #expect(restart == vector["expect"]?.bool)
    }

    @Test("020-FR-029 Done → completed or completed_empty; replaced or idle → partial or abandoned", arguments: ReviewVectors.section(flow, "session_status"))
    func sessionStatus(_ vector: Vector) throws {
        let end = try #require(vector["end"]?.string.flatMap(SessionEnd.init(rawValue:)))
        let status = ReviewSessionStatus.ended(by: end, qualifyingActivity: vector["qualifying_activity"]?.bool ?? false)
        #expect(status.rawValue == vector["expect"]?.string)
    }

    @Test("020-FR-029 a review idle for 7 days is closed", arguments: ReviewVectors.section(flow, "idle_close"))
    func idleClose(_ vector: Vector) throws {
        let due = ReviewSession.isIdleCloseDue(
            lastActivityAt: try #require(ReviewVectors.instant(vector["last_activity_at"])),
            now: try #require(ReviewVectors.instant(vector["now"]))
        )
        #expect(due == vector["expect"]?.bool)
    }

    @Test("020-FR-029 qualifying activity: a decision, or a non-summary step finished with nothing to decide", arguments: ReviewVectors.section(flow, "qualifying_activity"))
    func qualifyingActivity(_ vector: Vector) {
        let empty = Set(
            (vector["steps"]?.object ?? [:]).compactMap { code, step -> ReviewStep? in
                guard step["status"]?.string == "finished", step["finished_empty"]?.bool == true else { return nil }
                return ReviewStep(rawValue: code)
            }
        )
        #expect(ReviewSession.qualifies(itemDecisions: vector["item_decisions"]?.int ?? 0, finishedEmptySteps: empty) == vector["expect"]?.bool)
    }

    @Test("020-FR-029 counted reviews: completed, partial, and open once it qualifies", arguments: ReviewVectors.section(flow, "counted_review"))
    func countedReview(_ vector: Vector) throws {
        let status = try #require(vector["status"]?.string.flatMap(ReviewSessionStatus.init(rawValue:)))
        #expect(status.isCounted(qualifyingActivity: vector["qualifying_activity"]?.bool ?? false) == vector["expect"]?.bool)
    }

    @Test("020-FR-038 the regularity instant comes from counted reviews only", arguments: ReviewVectors.section(flow, "regularity"))
    func regularity(_ vector: Vector) throws {
        let sessions = (vector["sessions"]?.array ?? []).enumerated().map { index, raw in
            ReviewSession(
                id: Review.session(index + 1), mode: .quick, entry: .list, origin: .ios,
                status: raw["status"]?.string.flatMap(ReviewSessionStatus.init(rawValue:)) ?? .open,
                startedAt: ReviewVectors.instant(raw["last_activity_at"]) ?? .distantPast,
                lastActivityAt: ReviewVectors.instant(raw["last_activity_at"]), endedAt: ReviewVectors.instant(raw["ended_at"]),
                qualifyingActivity: raw["qualifying_activity"]?.bool ?? false
            )
        }
        #expect(ReviewVectors.iso(ReviewSession.lastCountedReviewAt(sessions)) == vector["expect"])
    }

    @Test("020-FR-004 020-FR-047 the decision queue: the aggregate, earliest-asking first", arguments: ReviewVectors.section(flow, "decision_queue"))
    func decisionQueueVector(_ vector: Vector) throws {
        let raw = try #require(vector["settings"])
        let settings = ReviewSettings(
            thresholdDays: raw["threshold_days"]?.int ?? 14, timeZone: raw["time_zone"]?.string ?? "UTC",
            activatedAt: ReviewVectors.instant(raw["activated_at"]), ownerParkFloorAt: ReviewVectors.instant(raw["owner_park_floor_at"])
        )
        var state = Review.state([], settings: settings)
        for row in vector["tasks"]?.array ?? [] {
            let id = TaskID(row["id"]?.string ?? "")
            let clocked = try FormulationTests.clock(row, taskID: id.rawValue)
            var task = Review.task(id, title: id.rawValue, state: clocked.state ?? .next)
            task.clocked = clocked
            state.tasks[id] = task
        }
        let now = try #require(ReviewVectors.instant(vector["now"]))
        #expect(GTDQueries.decisionQueue(in: state, now: now).map(\.id) == Self.ids(vector["expect"]))
        #expect(GTDQueries.askCount(in: state, now: now) == Self.ids(vector["expect"]).count)
    }

    // MARK: - Queries over GTDState

    @Test("020-FR-004 formulationClass and askCount use the owner's stored zone unless told otherwise")
    func formulationClassUsesTheStoredZone() {
        // Due 16 Oct: the clock starts at local midnight in the zone that classifies.
        let due = CalendarDay(year: 2026, month: 10, day: 16)!
        let task = Review.nextTask("t1", started: Review.instant("2026-09-01T09:00:00Z"), due: due)
        let settings = Review.settings(zone: "Pacific/Honolulu")
        let justAfterBerlinMidnight = Review.instant("2026-10-15T22:30:00Z")
        #expect(GTDQueries.formulationClass(of: task, now: justAfterBerlinMidnight, settings: settings) == .paused)
        #expect(GTDQueries.formulationClass(of: task, now: justAfterBerlinMidnight, settings: settings, timeZone: "Europe/Berlin") == .fresh)
    }

    @Test("020-FR-005 the third stalled wording: asking, with two stalled wordings before it")
    func thirdStall() {
        let settings = Review.settings()
        let asking = Review.now.addingTimeInterval(-15 * Review.day)
        let twice = Review.nextTask("t1", started: asking, stalled: 2)
        #expect(GTDQueries.isThirdStall(twice, now: Review.now, settings: settings))
        #expect(!GTDQueries.isThirdStall(Review.nextTask("t2", started: asking, stalled: 1), now: Review.now, settings: settings))
        let fresh = Review.nextTask("t3", started: Review.now.addingTimeInterval(-2 * Review.day), stalled: 2)
        #expect(!GTDQueries.isThirdStall(fresh, now: Review.now, settings: settings), "not asking yet")
        // A clock that started before activation is clamped to it (FR-016):
        // 40 days in Next but only 10 since activation does not ask yet.
        let clamped = Review.nextTask("t4", started: Review.now.addingTimeInterval(-40 * Review.day), stalled: 2)
        let late = Review.settings(activatedAt: Review.now.addingTimeInterval(-10 * Review.day))
        #expect(!GTDQueries.isThirdStall(clamped, now: Review.now, settings: late))
    }

    @Test("020-FR-009 keep 7 more days previews its dates: asks again 7 days from now, moves 7 days after that")
    func extensionPreview() throws {
        let settings = Review.settings()
        let task = Review.nextTask("t1", started: Review.now.addingTimeInterval(-15 * Review.day))
        let instants = try #require(GTDQueries.extensionInstants(of: task, now: Review.now, settings: settings))
        #expect(instants.askAt == Review.now.addingTimeInterval(7 * Review.day))
        #expect(instants.parkDueAt == Review.now.addingTimeInterval(14 * Review.day))
        let fresh = Review.nextTask("t2", started: Review.now.addingTimeInterval(-2 * Review.day))
        #expect(GTDQueries.extensionInstants(of: fresh, now: Review.now, settings: settings) == nil, "not due yet")
        let used = Review.nextTask("t3", started: Review.now.addingTimeInterval(-30 * Review.day), extendedAt: Review.now)
        #expect(GTDQueries.extensionInstants(of: used, now: Review.now, settings: settings) == nil, "used once")
        // The classification zone moves a due date's clock start (§6): the
        // preview follows the zone it is asked with.
        let due = CalendarDay(year: 2026, month: 9, day: 20)!
        let dueTask = Review.nextTask("t4", started: Review.instant("2026-09-02T09:00:00Z"), due: due)
        let berlin = try #require(GTDQueries.extensionInstants(of: dueTask, now: Review.now, settings: settings))
        let honolulu = try #require(
            GTDQueries.extensionInstants(of: dueTask, now: Review.now, settings: settings, timeZone: "Pacific/Honolulu")
        )
        #expect(berlin.start != honolulu.start)
    }

    @Test("020-FR-012 a park's age comes from its own clock: after the activation grace or an extension too; unknown without it")
    func parkedAge() {
        let started = Review.instant("2026-09-01T08:00:00Z")
        var parked = Review.task("t1", title: "Call Bob", state: .someday)
        // Kept 7 more days, then parked 28 days and 6 hours after the start.
        let at = started.addingTimeInterval(28 * Review.day + 6 * 3_600)
        parked.parked = ParkMarker(
            at: at, formulationID: Review.form(1),
            clockBefore: FormulationClock(id: Review.form(1), startedAt: started, extendedAt: started.addingTimeInterval(14 * Review.day))
        )
        #expect(GTDQueries.parkedAfterDays(parked) == 28)
        // A park pulled from the server carries no clock (http §3): no guess.
        parked.parked = ParkMarker(at: at, formulationID: Review.form(1))
        #expect(GTDQueries.parkedAfterDays(parked) == nil)
        #expect(GTDQueries.parkedAfterDays(Review.task("t2", title: "Plan", state: .someday)) == nil, "not parked")
    }

    @Test("020-FR-015 returning a park to Next: open unless its project is archived or it changed elsewhere")
    func parkReturn() {
        let now = Review.now
        var parked = Review.task("t1", title: "Return the old router", state: .someday)
        parked.parked = ParkMarker(at: now, formulationID: Review.form(1))
        var state = Review.state([parked, Review.task("t2", title: "Update the CV", state: .next)])
        #expect(GTDQueries.parkReturnProblem(of: "t1", in: state) == nil)
        state.projects["p1"] = ProjectRecord(id: "p1", name: "Old flat", state: .archived, createdAt: now)
        state.tasks["t1"]?.projectID = "p1"
        #expect(GTDQueries.parkReturnProblem(of: "t1", in: state) == .projectArchived(name: "Old flat"))
        state.projects["p1"]?.state = .active
        #expect(GTDQueries.parkReturnProblem(of: "t1", in: state) == nil)
        #expect(GTDQueries.parkReturnProblem(of: "t2", in: state) == .changedElsewhere, "back in Next already")
        #expect(GTDQueries.parkReturnProblem(of: "gone", in: state) == .changedElsewhere)
        state.tasks["t1"]?.parked = nil
        #expect(GTDQueries.parkReturnProblem(of: "t1", in: state) == .changedElsewhere, "no longer parked")
    }

    @Test("020-FR-015 Continue acknowledges only the parks While you were away showed, as the parks it showed")
    func whileAwayAcknowledgesShownOnly() {
        let now = Review.now
        var first = Review.task("t1", title: "Return the old router", state: .someday)
        first.parked = ParkMarker(at: now, formulationID: Review.form(1))
        var state = Review.state([first])
        let shown = GTDQueries.unseenParkAcks(in: state)
        #expect(shown == [ParkAck(taskID: "t1", formulationID: Review.form(1), parkedAt: now)])

        // While the sheet is open, a sync brings another park.
        var arrived = Review.task("t2", title: "Update the CV", state: .someday)
        arrived.parked = ParkMarker(at: now.addingTimeInterval(60), formulationID: Review.form(2))
        state.tasks["t2"] = arrived
        #expect(GTDQueries.unseenParkAcks(in: state).count == 2)
        #expect(GTDQueries.whileAwayAcknowledgements(shown: shown, in: state) == shown, "the arrived park stays unseen")

        // A shown park returned (in the sheet or elsewhere) or seen elsewhere needs no acknowledgement.
        state.tasks["t1"]?.state = .next
        state.tasks["t1"]?.parked = nil
        #expect(GTDQueries.whileAwayAcknowledgements(shown: shown, in: state).isEmpty)
        // Parked again as a new park meanwhile: not the park that was shown.
        state.tasks["t1"]?.state = .someday
        state.tasks["t1"]?.parked = ParkMarker(at: now.addingTimeInterval(120), formulationID: Review.form(1))
        #expect(GTDQueries.whileAwayAcknowledgements(shown: shown, in: state).isEmpty)
    }

    @Test("020-FR-015 a shown park replaced by a later park of the same task is changed elsewhere: no Return, not in Return all")
    func shownParkReplacedByLaterPark() throws {
        let now = Review.now
        var parked = Review.task("t1", title: "Return the old router", state: .someday)
        parked.parked = ParkMarker(at: now, formulationID: Review.form(1))
        var state = Review.state([parked])
        let shown = try #require(GTDQueries.unseenParkAcks(in: state).first)
        #expect(GTDQueries.parkReturnProblem(of: "t1", shown: shown, in: state) == nil, "the park the sheet showed")
        #expect(WhileAwayOutcome.initial(for: nil).offersReturn)

        // Returned to Next (Undo), then the same formulation parked again later.
        state.tasks["t1"]?.state = .next
        state.tasks["t1"]?.parked = nil
        state.tasks["t1"]?.state = .someday
        state.tasks["t1"]?.parked = ParkMarker(at: now.addingTimeInterval(8 * Review.day), formulationID: Review.form(1))
        #expect(GTDQueries.parkReturnProblem(of: "t1", in: state) == nil, "on its own the new park can return")
        let problem = GTDQueries.parkReturnProblem(of: "t1", shown: shown, in: state)
        #expect(problem == .changedElsewhere, "not the park that was shown")
        let outcome = WhileAwayOutcome.initial(for: problem)
        #expect(outcome == .changedElsewhere && !outcome.offersReturn, "no Return to Next, and Return all skips it")

        // A different formulation at the shown instant is not the shown park either.
        state.tasks["t1"]?.parked = ParkMarker(at: now, formulationID: Review.form(2))
        #expect(GTDQueries.parkReturnProblem(of: "t1", shown: shown, in: state) == .changedElsewhere)

        // The archived-project problem still applies to the shown park.
        state.tasks["t1"]?.parked = ParkMarker(at: now, formulationID: Review.form(1))
        state.projects["p1"] = ProjectRecord(id: "p1", name: "Old flat", state: .archived, createdAt: now)
        state.tasks["t1"]?.projectID = "p1"
        #expect(GTDQueries.parkReturnProblem(of: "t1", shown: shown, in: state) == .projectArchived(name: "Old flat"))
        #expect(!WhileAwayOutcome.archived(project: "Old flat").offersReturn)
        #expect(!WhileAwayOutcome.returned.offersReturn && !WhileAwayOutcome.notice.offersReturn)
    }

    @Test("020-FR-028 wins, capacity, Waiting and Someday due, projects without a next action and restart candidates over a state")
    func stateQueries() {
        let now = Review.now
        var state = Review.state([
            Review.nextTask("n1", started: now.addingTimeInterval(-40 * Review.day), project: "p1"),
            Review.task("c1", title: "Done", state: .completed), Review.task("w1", title: "Drill", state: .waiting),
            Review.task("s1", title: "Bed", state: .someday), Review.task("p2task", title: "Plan", state: .waiting),
        ])
        state.tasks["c1"]?.completedAt = now.addingTimeInterval(-Review.day)
        state.tasks["w1"]?.waitingSince = now.addingTimeInterval(-8 * Review.day)
        state.tasks["p2task"]?.projectID = "p2"
        state.projects["p1"] = ProjectRecord(id: "p1", name: "Flat", createdAt: now)
        state.projects["p2"] = ProjectRecord(id: "p2", name: "Garden", createdAt: now)
        state.review.settings.activatedAt = Review.instant("2026-08-01T00:00:00Z")
        #expect(GTDQueries.wins(in: state, now: now).map(\.id) == ["c1"])
        #expect(GTDQueries.capacityMirror(in: state, now: now).nextCount == 1)
        #expect(GTDQueries.capacityMirror(in: state, now: now).weeklyAverage4w == nil, "fewer than 4 weeks of history")
        #expect(GTDQueries.waitingDue(in: state, now: now).map(\.id) == ["w1"], "no waiting_since: not due")
        #expect(GTDQueries.somedayDue(in: state, now: now).shown.map(\.id) == ["s1"])
        #expect(GTDQueries.projectsNeedingNextAction(in: state).map(\.project.id) == ["p2"])
        #expect(GTDQueries.restartCandidates(in: state, now: now).map(\.id) == ["n1"])
    }

    @Test("020-FR-028 dates ahead: 14 local days from today, within a day in manual order (orderKey, then id)")
    func datesAhead() {
        let today = CalendarDay(year: 2026, month: 10, day: 9)!
        var b = Review.task("b", title: "B", state: .next, orderKey: 1)
        b.dueDate = today.adding(days: 2)
        var a = Review.task("a", title: "A", state: .waiting, orderKey: 1)
        a.dueDate = today.adding(days: 2)
        var first = Review.task("z", title: "Z", state: .next, orderKey: 0)
        first.dueDate = today.adding(days: 2)
        var edge = Review.task("edge", title: "Edge", state: .next)
        edge.dueDate = today.adding(days: 13)
        var outside = Review.task("out", title: "Out", state: .next)
        outside.dueDate = today.adding(days: 14)
        var past = Review.task("past", title: "Past", state: .next)
        past.dueDate = today.adding(days: -1)
        let days = GTDQueries.datesAhead(in: Review.state([a, b, first, edge, outside, past]), today: today)
        #expect(days.map(\.day) == [today.adding(days: 2), today.adding(days: 13)])
        #expect(days.first?.tasks.map(\.id) == ["z", "a", "b"])
    }

    @Test("020-FR-038 the last counted review is the latest counted session, or the server's later one")
    func lastCountedReview() {
        var state = Review.state([])
        let ended = Review.instant("2026-09-30T15:40:00Z")
        state.review.sessions[Review.session(1)] = ReviewSession(
            id: Review.session(1), mode: .quick, entry: .list, origin: .ios, status: .completed, startedAt: ended,
            endedAt: ended, qualifyingActivity: true
        )
        state.review.sessions[Review.session(2)] = ReviewSession(
            id: Review.session(2), mode: .quick, entry: .list, origin: .ios, status: .completedEmpty,
            startedAt: Review.now, endedAt: Review.now
        )
        #expect(GTDQueries.lastCountedReview(in: state) == ended, "completed_empty never counts")
        state.review.server = ReviewServerFacts(exposed: true, lastCountedReviewAt: Review.instant("2026-10-02T10:00:00Z"))
        #expect(GTDQueries.lastCountedReview(in: state) == Review.instant("2026-10-02T10:00:00Z"))
    }

    // MARK: - The decision step, releases and entry notices (T137 – T143)

    private func queueState(_ ids: [TaskID]) -> (GTDState, ReviewSession) {
        let starts = ["2026-09-22T09:00:00Z", "2026-09-23T09:00:00Z", "2026-09-24T09:00:00Z"]
        let tasks = zip(ids.indices, ids).map { index, id in
            Review.nextTask(id, started: Review.instant(starts[index]), formulation: Review.form(index + 1))
        }
        var state = Review.state(tasks)
        let session = ReviewSession(
            id: Review.session(1), mode: .quick, entry: .list, origin: .ios, startedAt: Review.now, decisionQueue: ids
        )
        state.review.sessions[session.id] = session
        return (state, session)
    }

    @Test("020-FR-034 020-FR-050 020-SC-002 the decision step walks the run's queue: card, Not now, kept wording, all decided")
    func decisionStepOutcomes() throws {
        var (state, session) = queueState(["a", "b", "c"])
        func outcome() -> DecisionStepOutcome {
            GTDQueries.decisionStep(in: state, session: state.review.sessions[session.id] ?? session, now: Review.now)
        }
        #expect(outcome() == .card("a", position: 1, total: 3))
        try Review.apply(Review.decide(.someday, "a", decision: 1, formulation: Review.form(1), session: session.id), to: &state)
        #expect(outcome() == .card("b", position: 2, total: 3))
        state.review.sessions[session.id]?.setAsideTaskIDs = ["b"]
        #expect(outcome() == .card("c", position: 3, total: 3), "Not now passes the card over")
        // "Save anyway": a decision, yet the task still asks.
        try Review.apply(
            Review.decide(.reformulate, "c", decision: 3, formulation: Review.form(3), title: "call bob.", session: session.id),
            to: &state
        )
        #expect(outcome() == .someLeft(decided: 2, total: 3, stillAsking: 2))
        try Review.apply(Review.decide(.someday, "b", decision: 2, formulation: Review.form(2), session: session.id), to: &state)
        #expect(outcome() == .allDecided(3, keptWording: 1))
        // Undo brings the card back as current.
        try Review.apply(.undoDecision(Review.decision(1)), at: Review.now.addingTimeInterval(1), to: &state)
        #expect(outcome() == .card("a", position: 1, total: 3))
        let (empty, quiet) = queueState([])
        #expect(GTDQueries.decisionStep(in: empty, session: quiet, now: Review.now) == .nothingAsks)
    }

    @Test("020-FR-017 020-FR-030 a release can be undone until the person moves on: a review started, or the Inbox step left")
    func openReleases() {
        var state = Review.state([])
        let released = BulkReleasedTask(taskID: "t1", previousState: .next, clockBefore: nil, taskAfter: TaskStamp(updatedAt: nil, serverRevision: 2))
        func record(_ n: Int, _ kind: BulkReleaseKindCode, session: ReviewSessionID? = nil, at date: Date = Review.now) -> BulkReleaseRecord {
            BulkReleaseRecord(id: Review.bulk(n), kind: kind, sessionID: session, createdAt: date, released: [released], skipped: [])
        }
        state.review.bulkReleases[Review.bulk(1)] = record(1, .restart)
        #expect(GTDQueries.openRestartReleases(in: state).map(\.id) == [Review.bulk(1)])
        state.review.bulkReleases[Review.bulk(1)]?.undoneAt = Review.now
        #expect(GTDQueries.openRestartReleases(in: state).isEmpty, "undone")
        state.review.bulkReleases[Review.bulk(1)]?.undoneAt = nil
        state.review.sessions[Review.session(1)] = ReviewSession(
            id: Review.session(1), mode: .quick, entry: .list, origin: .ios, startedAt: Review.now.addingTimeInterval(60)
        )
        #expect(GTDQueries.openRestartReleases(in: state).isEmpty, "Start the review is moving on")

        let session = ReviewSession(id: Review.session(2), mode: .quick, entry: .list, origin: .ios, startedAt: Review.now)
        state.review.bulkReleases[Review.bulk(2)] = record(2, .inboxRemainder, session: session.id)
        state.review.bulkReleases[Review.bulk(3)] = record(3, .inboxRemainder, session: Review.session(9))
        #expect(GTDQueries.openInboxReleases(in: state, session: session).map(\.id) == [Review.bulk(2)])
        var left = session
        left.steps[.inbox] = .finished
        #expect(GTDQueries.openInboxReleases(in: state, session: left).isEmpty, "the step was left")
    }

    @Test("020-FR-038 days since the last counted review are whole local days; none before the first")
    func daysSinceLastReview() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let today = CalendarDay(year: 2026, month: 10, day: 9)!
        var state = Review.state([])
        #expect(GTDQueries.daysSinceLastReview(in: state, today: today, calendar: calendar) == nil)
        let ended = Review.instant("2026-09-30T15:40:00Z")
        state.review.sessions[Review.session(1)] = ReviewSession(
            id: Review.session(1), mode: .quick, entry: .list, origin: .ios, status: .completed, startedAt: ended,
            endedAt: ended, qualifyingActivity: true
        )
        #expect(GTDQueries.daysSinceLastReview(in: state, today: today, calendar: calendar) == 9)
    }

    @Test("020-FR-029 020-SC-007 the entry names a review another device ended or the idle rule closed, with its decisions kept")
    func entryNotice() {
        var state = Review.state([])
        let started = Review.instant("2026-10-02T12:40:00Z")
        var idle = ReviewSession(
            id: Review.session(1), mode: .full, entry: .list, origin: .web, status: .partial, startedAt: started,
            lastActivityAt: started, qualifyingActivity: true
        )
        idle.counts[.done] = 4
        idle.counts[.inboxProcessed] = 3
        idle.endedAt = started.addingTimeInterval(ReviewSession.idleCloseAfter)
        state.review.sessions[idle.id] = idle
        #expect(GTDQueries.entryNotice(in: state) == .closedAfterAWeek(startedAt: started, decisions: 4), "Inbox processed is not a decision")
        var replaced = idle
        replaced.id = Review.session(2)
        replaced.endedAt = started.addingTimeInterval(ReviewSession.idleCloseAfter + 60)
        replaced.endedElsewhere = true
        state.review.sessions[replaced.id] = replaced
        #expect(GTDQueries.entryNotice(in: state) == .replacedElsewhere(origin: .web, decisions: 4))
        let done = ReviewSession(
            id: Review.session(3), mode: .quick, entry: .list, origin: .ios, status: .completed,
            startedAt: started.addingTimeInterval(9 * Review.day), endedAt: started.addingTimeInterval(9 * Review.day),
            qualifyingActivity: true
        )
        state.review.sessions[done.id] = done
        #expect(GTDQueries.entryNotice(in: state) == nil, "a later finished review leaves nothing to say")
    }
}
