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

    /// FR-051: the explainer is shown until an activation instant is known or
    /// this device already showed it.
    public static func explainerNeeded(in state: GTDState, local: LocalReviewState) -> Bool {
        state.review.settings.activatedAt == nil && local.activatedAt == nil && !local.explainerSeenLocally
    }
}
