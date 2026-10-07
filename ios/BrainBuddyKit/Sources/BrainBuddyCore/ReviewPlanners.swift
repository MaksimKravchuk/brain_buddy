import Foundation

// Pure Core functions for review behaviour that otherwise lives only in the
// app or the widget, so it is Linux-testable (contracts/ios-commands.md §6).

// MARK: - Markers (FR-004, FR-038)

/// The colour role of a marker. `destructive` (rose) is reserved for real due
/// dates and destructive controls; no age class may use it.
public enum MarkerRole: String, Hashable, Sendable, CaseIterable {
    case none
    /// Slate: ageing, paused.
    case neutral
    /// Indigo: asks for a decision.
    case decision
    /// Amber, the warning semantic: moves to Someday tomorrow.
    case caution
    /// Rose: never an age marker.
    case destructive
}

public struct MarkerStyle: Hashable, Sendable {
    public var text: String?
    /// SF Symbol name.
    public var symbol: String?
    public var role: MarkerRole
    /// List surfaces show only "asks" and "moves tomorrow" (owner decision 2).
    public var showsInLists: Bool
    /// Tapping the marker opens the decision card.
    public var opensCard: Bool

    public static func `for`(_ formulationClass: FormulationClass) -> MarkerStyle {
        switch formulationClass {
        case .none, .fresh:
            MarkerStyle(text: nil, symbol: nil, role: .none, showsInLists: false, opensCard: false)
        case .ageing:
            MarkerStyle(text: ReviewCopy.markerAgeing, symbol: "hourglass", role: .neutral, showsInLists: false, opensCard: false)
        case .paused:
            MarkerStyle(text: ReviewCopy.markerPaused, symbol: "pause.circle", role: .neutral, showsInLists: false, opensCard: false)
        case .asks:
            MarkerStyle(
                text: ReviewCopy.markerAsks, symbol: "questionmark.circle", role: .decision, showsInLists: true,
                opensCard: true
            )
        case .movesTomorrow, .parkDue:
            MarkerStyle(
                text: ReviewCopy.markerMovesTomorrow, symbol: "archivebox", role: .caution, showsInLists: true, opensCard: true
            )
        }
    }
}

// MARK: - Decision card

/// FR-007: the reason → recommended decision table of design M-03. The
/// recommendation never limits the choice: every decision stays enabled.
public enum StallReasonRecommendation {
    public static func decision(for reason: StallReason?) -> DecisionType? {
        switch reason {
        case nil: nil
        case .unclear: .reformulate
        case .tooBig, .missingInfo, .noEnergy: .firstStep
        case .waitingOnSomeone: .waiting
        case .noLongerMatters: .cancel
        }
    }

    /// The card's seven decisions for a task in Next, in the fixed order of
    /// design M-03 (the web numbers them 1 – 7 in this order): Done first,
    /// "Keep 7 more days" last and only while the formulation was not
    /// extended yet.
    public static func cardDecisions(extensionUsed: Bool) -> [DecisionType] {
        let all: [DecisionType] = [.complete, .reformulate, .firstStep, .waiting, .someday, .cancel, .extend]
        return extensionUsed ? all.filter { $0 != .extend } : all
    }
}

/// FR-048 / design "Undo (iOS)": about 5 s, at least 10 s while VoiceOver or
/// Switch Control runs.
public enum UndoWindowPolicy {
    public static func duration(voiceOver: Bool, switchControl: Bool) -> TimeInterval {
        voiceOver || switchControl ? 10 : 5
    }
}

/// FR-047: the decision card is a large sheet outside a review and full
/// screen inside one.
public enum ReviewPresentation: Hashable, Sendable {
    case largeSheet
    case fullScreen

    public static func decisionCard(inReview: Bool) -> ReviewPresentation { inReview ? .fullScreen : .largeSheet }
}

/// FR-015: "While you were away" is always the first screen of a review and
/// at app open at most once a calendar day.
public enum WhileAwayPresentation {
    public enum Context: String, Hashable, Sendable {
        case appOpen = "app_open"
        case reviewStart = "review_start"
    }

    public static func shouldShow(context: Context, hasUnseen: Bool, lastShownDay: CalendarDay?, today: CalendarDay)
        -> Bool
    {
        guard hasUnseen else { return false }
        if context == .reviewStart { return true }
        return lastShownDay.map { today > $0 } ?? true
    }

    public static func shouldShowAtAppOpen(lastShownDay: CalendarDay?, today: CalendarDay, hasUnseen: Bool) -> Bool {
        shouldShow(context: .appOpen, hasUnseen: hasUnseen, lastShownDay: lastShownDay, today: today)
    }
}

/// A sheet the weekly review shows at app open (T092, T093), in this order.
public enum ReviewStartupSheet: String, Hashable, Sendable, Identifiable {
    /// M-26.
    case explainer
    /// M-09.
    case whileAway

    public var id: String { rawValue }
}

/// What the app shows at open, and when a capture asked for meanwhile (a
/// `brainbuddy://capture` deep link, ⌘N, the capture bar) may show (design
/// "Entry order", T092): the explainer (M-26) before anything else, a capture
/// deep link that is not on screen yet included; then "While you were away"
/// (M-09), which yields to a requested capture and follows it. Neither is
/// presented over another sheet (one modal at a time), and a capture already
/// on screen is never taken away.
public enum ReviewStartupPlanner {
    public struct Context: Hashable, Sendable {
        public var reviewExposed: Bool
        public var explainerNeeded: Bool
        /// `WhileAwayPresentation.shouldShowAtAppOpen` for today.
        public var whileAwayDue: Bool
        /// A capture was asked for (shown or waiting).
        public var captureRequested: Bool
        /// Something is already presented (a sheet, a cover, a dialog).
        public var screenBusy: Bool

        public init(reviewExposed: Bool, explainerNeeded: Bool, whileAwayDue: Bool, captureRequested: Bool, screenBusy: Bool) {
            self.reviewExposed = reviewExposed
            self.explainerNeeded = explainerNeeded
            self.whileAwayDue = whileAwayDue
            self.captureRequested = captureRequested
            self.screenBusy = screenBusy
        }
    }

    /// The startup sheet to present now, or nil.
    public static func sheetToPresent(_ context: Context) -> ReviewStartupSheet? {
        guard context.reviewExposed, !context.screenBusy else { return nil }
        if context.explainerNeeded { return .explainer }
        if context.whileAwayDue, !context.captureRequested { return .whileAway }
        return nil
    }

    /// Whether a requested capture may be presented: one on screen stays;
    /// otherwise not while a startup sheet is up or the explainer is due.
    public static func captureMayPresent(
        startupSheet: ReviewStartupSheet?, captureOnScreen: Bool, reviewExposed: Bool, explainerNeeded: Bool
    ) -> Bool {
        if captureOnScreen { return true }
        return startupSheet == nil && !(reviewExposed && explainerNeeded)
    }
}

/// FR-033 / design "Mobile viability": one summary column and a sideways
/// scrolling step bar exactly at accessibility text sizes.
public enum ReviewLayout {
    public static func summaryColumns(isAccessibilitySize: Bool) -> Int { isAccessibilitySize ? 1 : 2 }
    public static func stepBarScrolls(isAccessibilitySize: Bool) -> Bool { isAccessibilitySize }
}

// MARK: - Active time (SC-004)

/// The SC-004 active-time rule (data-model E3) with an injected clock: the
/// time since the last counted event goes to the step on screen when it is at
/// most 2 minutes; a longer gap adds 0; background and leave pause counting
/// until foreground or resume.
public struct ActiveTimeAccumulator: Hashable, Sendable {
    public enum Event: Hashable, Sendable {
        case enterStep(ReviewStep)
        case interaction
        case background
        case foreground
        case leave
        case resume(ReviewStep)
    }

    public static let gapLimit: TimeInterval = 120

    public private(set) var secondsByStep: [ReviewStep: Int] = [:]
    private var step: ReviewStep?
    private var last: Date?

    public init() {}

    public mutating func record(_ event: Event, at instant: Date) {
        if let step, let last {
            let gap = instant.timeIntervalSince(last)
            if gap <= Self.gapLimit { secondsByStep[step, default: 0] += Int(gap.rounded(.down)) }
        }
        switch event {
        case .enterStep(let entered), .resume(let entered):
            step = entered
            secondsByStep[entered, default: 0] += 0
            last = instant
        case .background, .leave:
            last = nil
        case .interaction, .foreground:
            last = step == nil ? nil : instant
        }
    }
}

// MARK: - Schedule (FR-036)

/// Local wall-clock arithmetic for the review slot.
public enum ReviewClock {
    /// `HH:MM` (00:00 – 23:59) as hour and minute.
    public static func wallTime(_ text: String) -> (hour: Int, minute: Int)? {
        let parts = text.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 2, parts[0].count == 2, parts[1].count == 2, let hour = Int(parts[0]),
            let minute = Int(parts[1]), (0...23).contains(hour), (0...59).contains(minute)
        else { return nil }
        return (hour, minute)
    }

    /// The instant `day` at `hour:minute` in `zone`. A local time inside a
    /// daylight-saving gap moves forward by the gap length (02:30 → 03:30); in
    /// a repeated hour the first occurrence is used (Python's `fold=0`, http §5).
    public static func instant(day: CalendarDay, hour: Int, minute: Int, in zone: TimeZone) -> Date {
        let wall = day.dayNumber * CalendarDay.secondsPerDay + hour * 3_600 + minute * 60
        func offset(atSecond second: Int) -> Int {
            zone.secondsFromGMT(for: Date(timeIntervalSince1970: TimeInterval(second)))
        }
        let candidates = Set([offset(atSecond: wall - 86_400), offset(atSecond: wall), offset(atSecond: wall + 86_400)])
        let valid = candidates.filter { offset(atSecond: wall - $0) == $0 }
        if let first = valid.max() { return Date(timeIntervalSince1970: TimeInterval(wall - first)) }
        return Date(timeIntervalSince1970: TimeInterval(wall - offset(atSecond: wall - 86_400)))
    }
}

/// FR-036: one notification a week at the review day and time in the
/// device's current zone, skipped after a counted review in the 6 days
/// before the slot. It reads only `reviewWeekday` and `reviewTime` from
/// `settings` (never `settings.timeZone`): call it with `TimeZone.current`.
public enum ReviewReminderPlanner {
    public static let skipWindow: TimeInterval = 6 * FormulationRule.day

    public static func nextFireDate(
        settings: ReviewSettings, lastCountedReview: Date?, now: Date, timeZone: TimeZone
    ) -> Date? {
        guard let time = ReviewClock.wallTime(settings.reviewTime), (1...7).contains(settings.reviewWeekday) else {
            return nil
        }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let today = CalendarDay(date: now, calendar: calendar)
        // ISO weekday of `today`: 1970-01-01 was a Thursday (4).
        let isoWeekday = ((today.dayNumber % 7 + 7) % 7 + 3) % 7 + 1
        var day = today.adding(days: (settings.reviewWeekday - isoWeekday + 7) % 7)
        var slot = ReviewClock.instant(day: day, hour: time.hour, minute: time.minute, in: timeZone)
        if slot <= now {
            day = day.adding(days: 7)
            slot = ReviewClock.instant(day: day, hour: time.hour, minute: time.minute, in: timeZone)
        }
        if let lastCountedReview, lastCountedReview >= slot.addingTimeInterval(-skipWindow) {
            slot = ReviewClock.instant(day: day.adding(days: 7), hour: time.hour, minute: time.minute, in: timeZone)
        }
        return slot
    }
}

/// The device time-zone rule (FR-035, owner decision 2026-10-06): a zone
/// change is sent only when this device's own zone changed since it last
/// observed one, never because the pulled zone differs.
public enum DeviceZoneTracker {
    public static func change(lastObserved: String?, current: TimeZone) -> TimeZone? {
        guard let lastObserved, lastObserved != current.identifier else { return nil }
        return current
    }
}

// MARK: - Entry (FR-037, design "Entry order of the review")

/// `brainbuddy://review` and `brainbuddy://review/decisions` (the widget chip).
public enum ReviewRoute: Hashable, Sendable {
    case review
    case decisions

    public static func parse(_ url: URL) -> ReviewRoute? {
        guard url.scheme?.lowercased() == "brainbuddy", url.host?.lowercased() == "review" else { return nil }
        let path = url.path.split(separator: "/").map { $0.lowercased() }
        switch path {
        case []: return .review
        case ["decisions"]: return .decisions
        default: return nil
        }
    }
}

/// The screens a review entry opens, in order.
public enum ReviewScreen: Hashable, Sendable {
    /// M-26.
    case explainer
    /// M-12.
    case onboarding
    /// M-09.
    case whileAway
    /// M-10.
    case restart
    /// M-11 mode picker.
    case modePicker
    /// Continue an open review at `step`.
    case resume(ReviewSessionID, step: ReviewStep)
    /// A new quick review starting at `step` with `skipping` marked skipped.
    case quickReview(start: ReviewStep, skipping: [ReviewStep])
}

/// What the entry order depends on.
public struct ReviewEntryState: Hashable, Sendable {
    public var explainerNeeded: Bool
    public var onboarded: Bool
    public var hasUnseenParks: Bool
    public var restartMode: Bool
    public var openSession: ReviewSession?

    public init(
        explainerNeeded: Bool, onboarded: Bool, hasUnseenParks: Bool, restartMode: Bool, openSession: ReviewSession?
    ) {
        self.explainerNeeded = explainerNeeded
        self.onboarded = onboarded
        self.hasUnseenParks = hasUnseenParks
        self.restartMode = restartMode
        self.openSession = openSession
    }
}

/// Explainer, onboarding, While you were away, restart, then resume or the
/// mode picker; the widget chip lands on the decision step instead (an open
/// review resumes there, otherwise a quick review with Wins and Inbox skipped).
public enum ReviewEntryPlanner {
    public static func start(for entry: ReviewEntry, state: ReviewEntryState) -> [ReviewScreen] {
        var screens: [ReviewScreen] = []
        if state.explainerNeeded { screens.append(.explainer) }
        if !state.onboarded { screens.append(.onboarding) }
        if state.hasUnseenParks { screens.append(.whileAway) }
        if state.restartMode { screens.append(.restart) }
        switch entry {
        case .widgetDecisions:
            if let open = state.openSession {
                screens.append(.resume(open.id, step: .decisions))
            } else {
                screens.append(.quickReview(start: .decisions, skipping: [.wins, .inbox]))
            }
        case .list, .notification, .sidebar, .restart:
            if let open = state.openSession {
                screens.append(.resume(open.id, step: open.currentStep ?? open.mode.steps[0]))
            } else {
                screens.append(.modePicker)
            }
        }
        return screens
    }
}

// MARK: - Navigator proposals (FR-019)

/// Drops a proposal whose formulation key equals the current title, any open
/// task of the project the device holds (not only the 20 titles sent), or an
/// earlier proposal (contracts/navigator.md §2 rule 5).
public enum NavigatorProposalFilter {
    public static func dropDuplicates(_ proposals: [String], currentTitle: String, projectOpenTitles: [String]) -> [String] {
        var seen = Set([FormulationKey.key(currentTitle)] + projectOpenTitles.map(FormulationKey.key))
        return proposals.filter { seen.insert(FormulationKey.key($0)).inserted }
    }
}
