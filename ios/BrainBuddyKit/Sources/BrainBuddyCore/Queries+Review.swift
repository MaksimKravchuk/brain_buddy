import Foundation

/// FR-031: the Next count, and the 4-week pace and implied weeks once there
/// are 4 full weeks of history and a completion in them (else nil).
public struct CapacityMirror: Hashable, Sendable {
    public var nextCount: Int
    public var weeksOfHistory: Int
    public var weeklyAverage4w: Double?
    public var impliedWeeks: Double?

    public static let weeks = 4
    static let week: TimeInterval = 7 * FormulationRule.day

    public init(nextCount: Int, weeksOfHistory: Int, weeklyAverage4w: Double?, impliedWeeks: Double?) {
        self.nextCount = nextCount
        self.weeksOfHistory = weeksOfHistory
        self.weeklyAverage4w = weeklyAverage4w
        self.impliedWeeks = impliedWeeks
    }

    public static func compute(nextCount: Int, completedAt: [Date], now: Date) -> CapacityMirror {
        var weeksOfHistory = 0
        if let first = completedAt.min() { weeksOfHistory = Int((now.timeIntervalSince(first) / week).rounded(.down)) }
        let windowStart = now.addingTimeInterval(-Double(weeks) * week)
        let recent = completedAt.filter { $0 >= windowStart && $0 <= now }.count
        guard weeksOfHistory >= weeks, recent > 0 else {
            return CapacityMirror(nextCount: nextCount, weeksOfHistory: weeksOfHistory, weeklyAverage4w: nil, impliedWeeks: nil)
        }
        let average = Double(recent) / Double(weeks)
        return CapacityMirror(
            nextCount: nextCount, weeksOfHistory: weeksOfHistory, weeklyAverage4w: average,
            impliedWeeks: Double(nextCount) / average
        )
    }
}

/// FR-032: at most `limit` Someday tasks a look is due for.
public struct SomedayQueue: Hashable, Sendable {
    public var eligibleTotal: Int
    public var shown: [TaskRecord]
}

/// One local day of the review's "Dates in the next 14 days" step.
public struct DueDay: Hashable, Sendable {
    public var day: CalendarDay
    public var tasks: [TaskRecord]
}

/// Why a parked task cannot return to Next (M-09).
public enum ParkReturnProblem: Hashable, Sendable {
    /// No longer parked in Someday: it was moved or returned elsewhere.
    case changedElsewhere
    /// Its project is archived; restore the project first.
    case projectArchived(name: String)
}

/// M-16 (FR-034, FR-050, SC-002): where the decision step stands.
public enum DecisionStepOutcome: Hashable, Sendable {
    /// The card to show: `position` of `total` in the run's queue.
    case card(TaskID, position: Int, total: Int)
    /// Nothing asked for a decision.
    case nothingAsks
    /// Every card is decided; `keptWording` of them ("Save anyway") still ask.
    case allDecided(Int, keptWording: Int)
    /// "Not now" was used: `stillAsking` of the queue wait for a decision.
    case someLeft(decided: Int, total: Int, stillAsking: Int)
}

/// M-11: a neutral line about an earlier review above Quick and Full.
public enum ReviewEntryNotice: Hashable, Sendable {
    /// A review of `origin` was closed when a newer one synced (FR-029).
    case replacedElsewhere(origin: ReviewOrigin, decisions: Int)
    /// The 7-day idle rule closed the review started at `startedAt`.
    case closedAfterAWeek(startedAt: Date, decisions: Int)
}

/// The pure review-flow rules, run against `review_flow_vectors.json` like
/// `backend/app/modules/tasks/review_rules.py`.
public enum ReviewRules {
    public static let winsWindow: TimeInterval = 7 * FormulationRule.day
    public static let waitingAge: TimeInterval = 7 * FormulationRule.day
    public static let recentPark: TimeInterval = 30 * FormulationRule.day
    public static let somedayShown = 7
    public static let restartAfter: TimeInterval = 21 * FormulationRule.day

    /// Completed in the last 7 days (both ends included), most recent first, then id.
    public static func wins(_ tasks: some Sequence<TaskRecord>, now: Date) -> [TaskRecord] {
        let since = now.addingTimeInterval(-winsWindow)
        return tasks.filter { task in
            guard task.state == .completed, let done = task.completedAt else { return false }
            return done >= since && done <= now
        }
        .sorted { lhs, rhs in
            lhs.completedAt != rhs.completedAt ? lhs.completedAt! > rhs.completedAt! : lhs.id < rhs.id
        }
    }

    /// Waiting more than 7 days, not hidden by a current receipt, oldest first.
    public static func waitingQueue(
        _ tasks: some Sequence<TaskRecord>, receipts: [ReviewReceipt], now: Date
    ) -> [TaskRecord] {
        tasks.filter { task in
            guard task.state == .waiting, let since = task.waitingSince, now.timeIntervalSince(since) > waitingAge else {
                return false
            }
            let receipt = receipts.first { $0.taskID == task.id && $0.kind == .waiting }
            return !(receipt?.hides(task, now: now) ?? false)
        }
        .sorted { ($0.waitingSince!, $0.id) < ($1.waitingSince!, $1.id) }
    }

    /// Someday tasks no current receipt hides, without parks of the last 30
    /// days; never reviewed first (oldest `updatedAt`, then id), then the
    /// oldest receipt.
    public static func somedayQueue(
        _ tasks: some Sequence<TaskRecord>, receipts: [ReviewReceipt], now: Date, limit: Int = somedayShown
    ) -> SomedayQueue {
        var never: [TaskRecord] = []
        var reviewed: [(reviewedAt: Date, task: TaskRecord)] = []
        for task in tasks where task.state == .someday {
            if let parked = task.parked, now.timeIntervalSince(parked.at) < recentPark { continue }
            guard let receipt = receipts.first(where: { $0.taskID == task.id && $0.kind == .someday }) else {
                never.append(task)
                continue
            }
            if !receipt.hides(task, now: now) { reviewed.append((receipt.reviewedAt, task)) }
        }
        never.sort { ($0.updatedAt, $0.id) < ($1.updatedAt, $1.id) }
        reviewed.sort { ($0.reviewedAt, $0.task.updatedAt, $0.task.id) < ($1.reviewedAt, $1.task.updatedAt, $1.task.id) }
        let order = never + reviewed.map(\.task)
        return SomedayQueue(eligibleTotal: order.count, shown: Array(order.prefix(limit)))
    }

    /// FR-017: onboarded, and 21 days since the last counted review or onboarding.
    public static func restartMode(onboardedAt: Date?, lastCountedReviewAt: Date?, now: Date) -> Bool {
        guard let onboardedAt else { return false }
        return now.timeIntervalSince(lastCountedReviewAt ?? onboardedAt) >= restartAfter
    }

    /// E3 / FR-029: whether finishing `step` now is qualifying activity. A
    /// step with items to decide qualifies only when its queue is empty; Wins,
    /// the mind sweep, the rest of Next and Dates have nothing to decide; the
    /// summary never qualifies.
    public static func hasNothingToDecide(_ step: ReviewStep, in state: GTDState, now: Date) -> Bool {
        switch step {
        case .summary: false
        case .wins, .mindSweep, .restOfNext, .dates: true
        case .inbox: !state.tasks.values.contains { $0.state == .inbox }
        case .decisions: GTDQueries.decisionQueue(in: state, now: now).isEmpty
        case .waiting: GTDQueries.waitingDue(in: state, now: now).isEmpty
        case .someday: GTDQueries.somedayDue(in: state, now: now).eligibleTotal == 0
        case .projects: GTDQueries.projectsNeedingNextAction(in: state).isEmpty
        }
    }
}

/// Spec 020 queries (contracts/ios-commands.md §6). Classification uses the
/// owner's stored zone when signed in and the device's zone without an
/// account: pass `timeZone` to override the stored one ("Which zone, for what").
extension GTDQueries {
    static func clockSettings(_ state: GTDState, timeZone: String?) -> OwnerClockSettings {
        state.review.settings.clockSettings(timeZone: timeZone)
    }

    /// §5 class of `task` at `now`.
    public static func formulationClass(
        of task: TaskRecord, now: Date, settings: ReviewSettings, timeZone: String? = nil
    ) -> FormulationClass {
        let clock = settings.clockSettings(timeZone: timeZone)
        return FormulationRule.classify(GTDReducer.evaluationView(task, settings: clock), settings: clock, now: now)
    }

    /// §4 instants of `task` (nil while not activated, outside Next or without a clock).
    public static func derivedInstants(of task: TaskRecord, settings: ReviewSettings, timeZone: String? = nil)
        -> DerivedInstants?
    {
        let clock = settings.clockSettings(timeZone: timeZone)
        return FormulationRule.derivedInstants(of: GTDReducer.evaluationView(task, settings: clock), settings: clock)
    }

    /// The `asks_for_decision` aggregate in queue order: earliest-asking first.
    public static func decisionQueue(in state: GTDState, now: Date, timeZone: String? = nil) -> [TaskRecord] {
        let settings = clockSettings(state, timeZone: timeZone)
        let tasks = state.tasks.values.filter { $0.state == .next }
            .map { (id: $0.id, task: GTDReducer.evaluationView($0, settings: settings)) }
        return FormulationRule.decisionQueue(tasks, settings: settings, now: now).compactMap { state.tasks[$0] }
    }

    /// The widget's "N ask" (the same aggregate as `decisionQueue`).
    public static func askCount(in state: GTDState, now: Date, timeZone: String? = nil) -> Int {
        decisionQueue(in: state, now: now, timeZone: timeZone).count
    }

    /// Next tasks whose park is due at `now`; empty before activation (FR-051).
    public static func dueAutoParks(in state: GTDState, now: Date, timeZone: String? = nil) -> [TaskRecord] {
        let settings = clockSettings(state, timeZone: timeZone)
        guard settings.activatedAt != nil else { return [] }
        return state.tasks.values.filter { task in
            task.state == .next
                && FormulationRule.classify(GTDReducer.evaluationView(task, settings: settings), settings: settings, now: now)
                    == .parkDue
        }
        .sorted { ($0.formulation?.startedAt ?? .distantPast, $0.id) < ($1.formulation?.startedAt ?? .distantPast, $1.id) }
    }

    /// Auto-parked tasks not yet seen on "While you were away", oldest park first.
    public static func unseenParks(in state: GTDState) -> [TaskRecord] {
        state.tasks.values.filter { task in
            guard task.state == .someday, let marker = task.parked else { return false }
            return !state.review.hasSeen(task.id, marker)
        }
        .sorted { ($0.parked!.at, $0.id) < ($1.parked!.at, $1.id) }
    }

    /// The acknowledgement of each unseen park, in `unseenParks` order: what
    /// "While you were away" lists and may later acknowledge.
    public static func unseenParkAcks(in state: GTDState) -> [ParkAck] {
        unseenParks(in: state).compactMap { task in
            task.parked.map { ParkAck(taskID: task.id, formulationID: $0.formulationID, parkedAt: $0.at) }
        }
    }

    /// FR-015: what Continue on "While you were away" acknowledges: of the
    /// parks the sheet `shown`, those still unseen as the same park.
    public static func whileAwayAcknowledgements(shown: [ParkAck], in state: GTDState) -> [ParkAck] {
        let unseen = Set(unseenParkAcks(in: state))
        return shown.filter { unseen.contains($0) }
    }

    /// FR-017: Next tasks at least 28 days into their formulation, not paused.
    public static func restartCandidates(in state: GTDState, now: Date, timeZone: String? = nil) -> [TaskRecord] {
        let settings = clockSettings(state, timeZone: timeZone)
        return state.tasks.values.filter { task in
            task.state == .next
                && FormulationRule.isRestartEligible(GTDReducer.evaluationView(task, settings: settings), settings: settings, now: now)
        }
        .sorted { ($0.formulation?.startedAt ?? .distantPast, $0.id) < ($1.formulation?.startedAt ?? .distantPast, $1.id) }
    }

    /// Restart mode (FR-017) from the counted reviews this state knows.
    public static func restartMode(in state: GTDState, now: Date) -> Bool {
        ReviewRules.restartMode(
            onboardedAt: state.review.settings.onboardedAt, lastCountedReviewAt: lastCountedReview(in: state), now: now
        )
    }

    /// Tasks completed in the last 7 days, most recent first (FR-028).
    public static func wins(in state: GTDState, now: Date) -> [TaskRecord] {
        ReviewRules.wins(state.tasks.values, now: now)
    }

    /// FR-031.
    public static func capacityMirror(in state: GTDState, now: Date) -> CapacityMirror {
        CapacityMirror.compute(
            nextCount: state.tasks.values.filter { $0.state == .next }.count,
            completedAt: state.tasks.values.compactMap { $0.state == .completed ? $0.completedAt : nil }, now: now
        )
    }

    /// Waiting more than 7 days that no receipt hides, oldest first (FR-032).
    public static func waitingDue(in state: GTDState, now: Date) -> [TaskRecord] {
        ReviewRules.waitingQueue(state.tasks.values, receipts: state.review.receipts, now: now)
    }

    /// At most `limit` Someday tasks a look is due for (FR-032).
    public static func somedayDue(in state: GTDState, now: Date, limit: Int = ReviewRules.somedayShown) -> SomedayQueue {
        ReviewRules.somedayQueue(state.tasks.values, receipts: state.review.receipts, now: now, limit: limit)
    }

    /// Active projects without an open next action (`ProjectSummary.needsNextAction`).
    public static func projectsNeedingNextAction(in state: GTDState) -> [ProjectSummary] {
        projects(in: state).filter(\.needsNextAction)
    }

    /// Open tasks due from `today` to `today + days - 1`, one entry per day
    /// with a task, ascending; within a day in the Next list's manual order
    /// (`orderKey`, then id; http §6 `dates`).
    public static func datesAhead(in state: GTDState, today: CalendarDay, days: Int = 14) -> [DueDay] {
        let last = today.adding(days: days - 1)
        var byDay: [CalendarDay: [TaskRecord]] = [:]
        for task in state.tasks.values where task.isOpen {
            guard let due = task.dueDate, due >= today, due <= last else { continue }
            byDay[due, default: []].append(task)
        }
        return byDay.keys.sorted().map { day in
            DueDay(day: day, tasks: byDay[day]!.sorted { ($0.orderKey, $0.id) < ($1.orderKey, $1.id) })
        }
    }

    /// The regularity instant: completed and partial reviews, and an open one
    /// once it qualifies (FR-029, FR-038); the server's when it knows a later one.
    public static func lastCountedReview(in state: GTDState) -> Date? {
        [ReviewSession.lastCountedReviewAt(state.review.sessions.values), state.review.server?.lastCountedReviewAt]
            .compactMap { $0 }.max()
    }

    /// FR-005: the card's third-stall offer, evaluated as the classification is.
    public static func isThirdStall(_ task: TaskRecord, now: Date, settings: ReviewSettings, timeZone: String? = nil) -> Bool {
        let clock = settings.clockSettings(timeZone: timeZone)
        return FormulationRule.isThirdStall(GTDReducer.evaluationView(task, settings: clock), settings: clock, now: now)
    }

    /// FR-009: the instants "Keep 7 more days" would give if chosen at `now`
    /// (M-04 "Asks again on …", "Keep until …"); nil when it is not allowed.
    public static func extensionInstants(
        of task: TaskRecord, now: Date, settings: ReviewSettings, timeZone: String? = nil
    ) -> DerivedInstants? {
        let clock = settings.clockSettings(timeZone: timeZone)
        let view = GTDReducer.evaluationView(task, settings: clock)
        guard let extended = try? FormulationRule.extend(view, reason: "", settings: clock, now: now) else { return nil }
        return FormulationRule.derivedInstants(of: extended, settings: clock)
    }

    /// FR-012 (M-02 "after N days in Next"): whole days from the parked
    /// wording's start to the park, from the clock the park stored. A park
    /// pulled from the server carries no clock (http §3 `parked`): nil, so
    /// the copy says no number rather than a guessed one.
    public static func parkedAfterDays(_ task: TaskRecord) -> Int? {
        guard let marker = task.parked, let started = marker.clockBefore?.startedAt else { return nil }
        return max(0, Int((marker.at.timeIntervalSince(started) / FormulationRule.day).rounded(.down)))
    }

    /// FR-015 (M-09 "Return to Next"): why a park cannot go back to Next
    /// now, or nil. A task no longer parked in Someday changed elsewhere; a
    /// park in an archived project needs the project restored first (spec
    /// edge case "Task in an archived project"; http.md `project_archived`).
    /// With `shown` (the park M-09 listed), a later park of the same task (a
    /// repeat park after an Undo, a park synced in) is not the one shown: it
    /// changed elsewhere, so the row never acts on a park it did not show.
    public static func parkReturnProblem(of id: TaskID, shown: ParkAck? = nil, in state: GTDState) -> ParkReturnProblem? {
        guard let task = state.tasks[id], task.state == .someday, let marker = task.parked else { return .changedElsewhere }
        if let shown, shown.taskID != id || shown.formulationID != marker.formulationID || shown.parkedAt != marker.at {
            return .changedElsewhere
        }
        if let projectID = task.projectID, let project = state.projects[projectID], project.state != .active {
            return .projectArchived(name: project.name)
        }
        return nil
    }

    /// The decision step (M-16) for `session`: its queue is the snapshot taken
    /// when the step opened. The card is the first task not decided, not set
    /// aside with "Not now" and still asking; a decision of this run counts
    /// even when the task still asks afterwards (a cosmetic save, FR-002).
    public static func decisionStep(
        in state: GTDState, session: ReviewSession, now: Date, timeZone: String? = nil
    ) -> DecisionStepOutcome {
        let queue = session.decisionQueue ?? decisionQueue(in: state, now: now, timeZone: timeZone).map(\.id)
        let decided = Set(state.review.decisions.values.filter { $0.sessionID == session.id }.map(\.taskID))
        let aside = Set(session.setAsideTaskIDs)
        func asks(_ id: TaskID) -> Bool {
            guard let task = state.tasks[id] else { return false }
            return formulationClass(of: task, now: now, settings: state.review.settings, timeZone: timeZone).asksForDecision
        }
        if let current = queue.first(where: { !decided.contains($0) && !aside.contains($0) && asks($0) }) {
            return .card(current, position: (queue.firstIndex(of: current) ?? 0) + 1, total: queue.count)
        }
        let decidedCount = queue.filter(decided.contains).count
        let kept = queue.filter { decided.contains($0) && asks($0) }.count
        let left = queue.filter { aside.contains($0) && !decided.contains($0) && asks($0) }.count
        if left > 0 { return .someLeft(decided: decidedCount, total: queue.count, stillAsking: left + kept) }
        return decidedCount == 0 ? .nothingAsks : .allDecided(decidedCount, keptWording: kept)
    }

    /// FR-017: restart releases the person can still undo: not undone, and no
    /// review started since ("Start the review" is moving on).
    public static func openRestartReleases(in state: GTDState) -> [BulkReleaseRecord] {
        let lastStart = state.review.sessions.values.map(\.startedAt).max()
        return state.review.bulkReleases.values.filter { record in
            record.kind == .restart && record.undoneAt == nil && !record.released.isEmpty
                && (lastStart.map { $0 < record.createdAt } ?? true)
        }
        .sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
    }

    /// FR-030: the Inbox-remainder releases of `session` the person can still
    /// undo: not undone, and the Inbox step is not left yet.
    public static func openInboxReleases(in state: GTDState, session: ReviewSession) -> [BulkReleaseRecord] {
        guard (session.steps[.inbox] ?? .pending) == .pending else { return [] }
        return state.review.bulkReleases.values.filter { record in
            record.kind == .inboxRemainder && record.sessionID == session.id && record.undoneAt == nil
                && !record.released.isEmpty
        }
        .sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
    }

    /// Whole local days since the last counted review (FR-038), nil when there is none.
    public static func daysSinceLastReview(in state: GTDState, today: CalendarDay, calendar: Calendar = .current) -> Int? {
        lastCountedReview(in: state).map { max(0, CalendarDay(date: $0, calendar: calendar).days(to: today)) }
    }

    /// M-11: the latest ended review, when another device ended it or the
    /// idle rule closed it.
    public static func entryNotice(in state: GTDState) -> ReviewEntryNotice? {
        let ended = state.review.sessions.values.filter { $0.status != .open }
        guard let latest = ended.max(by: { ($0.endedAt ?? $0.startedAt, $0.id) < ($1.endedAt ?? $1.startedAt, $1.id) })
        else { return nil }
        if latest.endedElsewhere { return .replacedElsewhere(origin: latest.origin, decisions: latest.decisionCount) }
        if latest.closedForIdleness { return .closedAfterAWeek(startedAt: latest.startedAt, decisions: latest.decisionCount) }
        return nil
    }

    /// FR-051: the explainer is shown until an activation instant is known or
    /// this device already showed it.
    public static func explainerNeeded(in state: GTDState, local: LocalReviewState) -> Bool {
        state.review.settings.activatedAt == nil && local.activatedAt == nil && !local.explainerSeenLocally
    }
}
