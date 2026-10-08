import Foundation

// How sync is worded and timed, for the Mac status line and the iPhone's
// (contracts/sync-status.md). Pure values with an injected `now`, so every
// state is tested on Linux; the apps only render the description.

/// The cadences and thresholds of sync, in one place.
public enum SyncTiming {
    /// The indicator appears only for a sync running at least this long.
    public static let indicatorDelay: TimeInterval = 1
    /// Once shown, it stays at least this long.
    public static let indicatorMinimum: TimeInterval = 0.5
    /// " · N changes waiting" shows (online) once the oldest change waited longer than this.
    public static let waitingSuffixAfter: TimeInterval = 10
    /// "Couldn't sync" shows once an attempt started at least this long after `failingSince` has failed.
    public static let failureSurfacesAfter: TimeInterval = 60
    /// The apps describe again at least this often.
    public static let relativeRefresh: TimeInterval = 30
    /// The `.periodic` trigger, on the Mac always and on the iPhone while the scene is active.
    public static let periodicTick: TimeInterval = 15
    /// `SyncConfiguration.pullInterval` for both apps: with the tick, pulls stay under 45 s apart.
    public static let pullAge: TimeInterval = 30
    /// The web's visible-tab refetch; not used by the kit, recorded so the three cadences sit together.
    public static let webRefetch: TimeInterval = 45
}

public enum DeviceKind: Sendable {
    case mac, iPhone

    public var noun: String { self == .mac ? "Mac" : "iPhone" }
}

/// What the line is told, from the workspace (data-model E6).
public struct SyncSnapshot: Equatable, Sendable {
    public enum Account: Equatable, Sendable {
        case none
        case linked(email: String)
    }

    public var account: Account
    /// The session ended (engine status `needsSignIn`).
    public var sessionEnded: Bool
    public var isOnline: Bool
    /// A cycle is running; feeds `SyncActivityIndicator` only.
    public var isSyncing: Bool
    public var lastSyncedAt: Date?
    public private(set) var pendingCount: Int
    /// When the oldest waiting change became sendable: nil iff nothing waits.
    public private(set) var oldestPendingAt: Date?
    /// Operations issued before the account was linked that are still unsent.
    public private(set) var initialUploadRemaining: Int
    public var issueCount: Int
    public var failingSince: Date?
    public var lastFailedAttemptAt: Date?
    public var lastFailureReferenceID: String?

    /// Out-of-range input is clamped to what data-model E6 allows: no negative count, no age without
    /// a change, a first upload no larger than the queue, and, with no account, nothing waiting.
    public init(
        account: Account, sessionEnded: Bool = false, isOnline: Bool = true, isSyncing: Bool = false,
        lastSyncedAt: Date? = nil, pendingCount: Int = 0, oldestPendingAt: Date? = nil,
        initialUploadRemaining: Int = 0, issueCount: Int = 0, failingSince: Date? = nil,
        lastFailedAttemptAt: Date? = nil, lastFailureReferenceID: String? = nil
    ) {
        let linked = account != .none
        self.account = account
        self.sessionEnded = sessionEnded
        self.isOnline = isOnline
        self.isSyncing = isSyncing
        self.lastSyncedAt = lastSyncedAt
        self.pendingCount = linked ? max(0, pendingCount) : 0
        self.oldestPendingAt = self.pendingCount == 0 ? nil : oldestPendingAt
        self.initialUploadRemaining = min(max(0, initialUploadRemaining), self.pendingCount)
        self.issueCount = max(0, issueCount)
        self.failingSince = failingSince
        self.lastFailedAttemptAt = lastFailedAttemptAt
        self.lastFailureReferenceID = lastFailureReferenceID
    }
}

/// The row of contracts/sync-status.md §3 that holds, first match from the top.
public enum SyncLineState: Equatable, Sendable {
    case accountLess, sessionEnded, rejected, failing, offline, notSyncedYet, synced
}

public struct SyncStatusDescription: Equatable, Sendable {
    public enum Tone: Equatable, Sendable { case calm, attention }
    public enum Glyph: Equatable, Sendable { case none, sessionEnded, warning }
    public enum Action: Equatable, Sendable { case none, signIn, signInAgain, retry, showIssues }

    public var state: SyncLineState
    /// The whole line, for example "Synced 3 min ago · 2 changes waiting".
    public var text: String
    /// The part before " · ".
    public var leading: String
    /// "Sign in to sync" or "Retry".
    public var trailingActionTitle: String?
    public var tone: Tone
    public var glyph: Glyph
    public var action: Action
    public var accessibilityLabel: String
    public var tooltip: String
    /// Attention states are announced when they appear.
    public var announceOnEntry: Bool
    /// False only where no sync can run; never because one is running (single-flight).
    public var syncNowEnabled: Bool
    /// "Last tried 14:35", while failing.
    public var lastTriedText: String?
}

public enum SyncStatusDescriber {
    public static func describe(
        _ snapshot: SyncSnapshot, now: Date, device: DeviceKind, calendar: Calendar
    ) -> SyncStatusDescription {
        let state = lineState(snapshot)
        var text = "", trailing: String?, tone = SyncStatusDescription.Tone.calm
        var glyph = SyncStatusDescription.Glyph.none, action = SyncStatusDescription.Action.none
        switch state {
        case .accountLess:
            text = "On this \(device.noun) · Sign in to sync"
            trailing = "Sign in to sync"
            action = .signIn
        case .sessionEnded:
            text = "Sign in again to sync"
            (tone, glyph, action) = (.attention, .sessionEnded, .signInAgain)
        case .rejected:
            text = "\(SyncCopy.changes(snapshot.issueCount)) couldn't sync"
            (tone, glyph, action) = (.attention, .warning, .showIssues)
        case .failing:
            text = "Couldn't sync · Retry"
            trailing = "Retry"
            (tone, glyph, action) = (.attention, .warning, .retry)
        case .offline:
            text = snapshot.pendingCount == 0 ? "Offline" : "Offline · \(SyncCopy.changes(snapshot.pendingCount)) waiting"
        case .notSyncedYet:
            text = "Not synced yet"
        case .synced:
            text = syncedText(snapshot, now: now, calendar: calendar)
        }
        let lastTried = snapshot.lastFailedAttemptAt.map { "Last tried \(SyncCopy.clock($0, now: now, calendar: calendar))" }
        return SyncStatusDescription(
            state: state, text: text, leading: text.components(separatedBy: " · ")[0],
            trailingActionTitle: trailing, tone: tone, glyph: glyph, action: action,
            accessibilityLabel: "Sync status: \(text). Show details",
            tooltip: tooltip(for: state, snapshot, now: now, device: device, calendar: calendar),
            announceOnEntry: tone == .attention,
            syncNowEnabled: ![.accountLess, .sessionEnded, .offline].contains(state),
            lastTriedText: state == .failing ? lastTried : nil
        )
    }

    static func lineState(_ s: SyncSnapshot) -> SyncLineState {
        if s.account == .none { return .accountLess }
        if s.sessionEnded { return .sessionEnded }
        if s.issueCount >= 1 { return .rejected }
        if s.isOnline, let since = s.failingSince, let last = s.lastFailedAttemptAt,
            milliseconds(last.timeIntervalSince(since)) >= milliseconds(SyncTiming.failureSurfacesAfter)
        {
            return .failing
        }
        if !s.isOnline { return .offline }
        if s.lastSyncedAt == nil || s.initialUploadRemaining > 0 { return .notSyncedYet }
        return .synced
    }

    /// Intervals are compared in whole milliseconds, so a stored date's rounding never tips a boundary.
    static func milliseconds(_ interval: TimeInterval) -> Int { Int((interval * 1000).rounded()) }

    private static func syncedText(_ s: SyncSnapshot, now: Date, calendar: Calendar) -> String {
        var text = relative(since: s.lastSyncedAt ?? now, now: now, calendar: calendar)
        if s.pendingCount >= 1, let oldest = s.oldestPendingAt,
            milliseconds(now.timeIntervalSince(oldest)) > milliseconds(SyncTiming.waitingSuffixAfter)
        {
            text += " · \(SyncCopy.changes(s.pendingCount)) waiting"
        }
        return text
    }

    /// The ladder of §3; a time in the future counts as now.
    static func relative(since last: Date, now: Date, calendar: Calendar) -> String {
        let seconds = max(0, milliseconds(now.timeIntervalSince(last))) / 1000
        if seconds < 60 { return "Synced just now" }
        if seconds < 3600 { return "Synced \(seconds / 60) min ago" }
        let days = CalendarDay(date: last, calendar: calendar).days(to: CalendarDay(date: now, calendar: calendar))
        switch days {
        case 0: return "Synced \(seconds / 3600) h ago"
        case 1: return "Synced yesterday"
        case 2...6: return "Synced \(days) days ago"
        default: return "Synced on \(SyncCopy.dayMonth(last, now: now, calendar: calendar))"
        }
    }

    private static func tooltip(
        for state: SyncLineState, _ s: SyncSnapshot, now: Date, device: DeviceKind, calendar: Calendar
    ) -> String {
        switch state {
        case .synced, .notSyncedYet, .offline:
            guard let last = s.lastSyncedAt else { return "Not synced yet. Click for details." }
            return "Last synced \(SyncCopy.when(last, now: now, calendar: calendar, capitalized: false)). Click for details."
        case .failing:
            var text = "Couldn't reach Brain Buddy since \(SyncCopy.clock(s.failingSince ?? now, now: now, calendar: calendar))."
            text += " Last tried \(SyncCopy.clock(s.lastFailedAttemptAt ?? now, now: now, calendar: calendar)). It keeps trying."
            if let reference = s.lastFailureReferenceID, !reference.isEmpty { text += " Reference ID \(reference)" }
            return text
        case .sessionEnded:
            return "Your session ended. Sign in again to keep syncing."
        case .rejected:
            return "\(SyncCopy.changes(s.issueCount)) couldn't sync. Click for details."
        case .accountLess:
            return "Your tasks are stored on this \(device.noun). Click for details."
        }
    }
}

/// A sentence or two of the copy catalogue (contracts/sync-status.md §3), for the apps to lay out.
public struct SyncCopyText: Equatable, Sendable {
    public var title: String
    public var detail: String?
    public var footnote: String?

    /// The parts on one line, for a place that has no layout.
    public var sentence: String { [title, detail, footnote].compactMap { $0 }.joined(separator: " ") }
}

/// What a sign-out says about the pre-upgrade backup (Mac only, data-model E8).
public enum SignOutBackupNote: Equatable, Sendable {
    /// The backup stays: until `until` (`importedAt + 30 days`), or with no date once that has passed.
    case kept(until: Date)
    /// This sign-out deletes it.
    case removed
}

/// Every sentence the Mac popover, its sign-in and sign-out sheets, and the iPhone's sign-out
/// confirmation use, so the two devices word them the same way.
public enum SyncCopy {
    // MARK: Pieces

    /// "1 change" / "1,284 changes".
    public static func changes(_ count: Int) -> String { count == 1 ? "1 change" : "\(grouped(count)) changes" }

    static func grouped(_ number: Int) -> String {
        var digits = String(abs(number))
        var out = ""
        while digits.count > 3 {
            out = "," + digits.suffix(3) + out
            digits.removeLast(3)
        }
        return (number < 0 ? "-" : "") + digits + out
    }

    /// "59 s", "1 min", "1 h", "1 day", "2 days".
    public static func age(_ interval: TimeInterval) -> String {
        let seconds = max(0, SyncStatusDescriber.milliseconds(interval) / 1000)
        switch seconds {
        case ..<60: return "\(seconds) s"
        case ..<3600: return "\(seconds / 60) min"
        case ..<86_400: return "\(seconds / 3600) h"
        default: return seconds / 86_400 == 1 ? "1 day" : "\(seconds / 86_400) days"
        }
    }

    /// "14:35" today, else "Sat 3 Oct".
    static func clock(_ date: Date, now: Date, calendar: Calendar) -> String {
        let day = CalendarDay(date: date, calendar: calendar)
        guard day != CalendarDay(date: now, calendar: calendar) else { return hourMinute(date, calendar) }
        return "\(weekdays[(day.dayNumber % 7 + 11) % 7]) \(dayMonth(date, now: now, calendar: calendar))"
    }

    /// "28 Sep", with the year when it is not this one.
    static func dayMonth(_ date: Date, now: Date, calendar: Calendar) -> String {
        let day = CalendarDay(date: date, calendar: calendar)
        let text = "\(day.day) \(months[day.month - 1])"
        return day.year == CalendarDay(date: now, calendar: calendar).year ? text : "\(text) \(day.year)"
    }

    /// "today at 14:31", "yesterday at 14:31", "on 28 Sep at 14:31" ("Today at …" when `capitalized`).
    static func when(_ date: Date, now: Date, calendar: Calendar, capitalized: Bool) -> String {
        let days = CalendarDay(date: date, calendar: calendar).days(to: CalendarDay(date: now, calendar: calendar))
        let time = hourMinute(date, calendar)
        let phrase: String
        switch days {
        case 0: phrase = "today at \(time)"
        case 1: phrase = "yesterday at \(time)"
        default: phrase = "on \(dayMonth(date, now: now, calendar: calendar)) at \(time)"
        }
        return capitalized ? phrase.prefix(1).uppercased() + phrase.dropFirst() : phrase
    }

    private static let months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    private static let weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    private static func hourMinute(_ date: Date, _ calendar: Calendar) -> String {
        let offset = calendar.timeZone.secondsFromGMT(for: date)
        let local = Int(date.timeIntervalSince1970.rounded(.down)) + offset
        let minuteOfDay = ((local % 86_400 + 86_400) % 86_400) / 60
        func pad(_ value: Int) -> String { value < 10 ? "0\(value)" : "\(value)" }
        return "\(pad(minuteOfDay / 60)):\(pad(minuteOfDay % 60))"
    }

    // MARK: Account

    public static func accountSwitchRefused(device: DeviceKind) -> SyncCopyText {
        SyncCopyText(
            title: "Sign out first to use another account.",
            detail: "Changes from the other account are still waiting on this \(device.noun).")
    }

    // MARK: Popover

    public static func popoverLastSynced(_ date: Date, now: Date, calendar: Calendar) -> String {
        "Last synced · \(when(date, now: now, calendar: calendar, capitalized: true))"
    }

    public static let popoverWaitingNothing = "Waiting to sync · Nothing"

    public static func popoverWaiting(count: Int, oldest: TimeInterval) -> String {
        "Waiting to sync · \(changes(count)) · oldest \(age(oldest))"
    }

    public static func popoverFirstUpload(remaining: Int) -> String {
        "Adding your tasks to your account · \(grouped(remaining)) left"
    }

    /// The queue line: the first upload while it drains (instead of the waiting count), else what waits.
    public static func popoverQueue(_ s: SyncSnapshot, now: Date) -> String {
        if s.initialUploadRemaining > 0 { return popoverFirstUpload(remaining: s.initialUploadRemaining) }
        guard s.pendingCount > 0, let oldest = s.oldestPendingAt else { return popoverWaitingNothing }
        return popoverWaiting(count: s.pendingCount, oldest: now.timeIntervalSince(oldest))
    }

    /// "You're offline…", and, after an earlier failure, when it was and its reference id.
    public static func popoverOffline(_ s: SyncSnapshot, now: Date, device: DeviceKind, calendar: Calendar) -> SyncCopyText {
        var footnote: String?
        if let last = s.lastFailedAttemptAt {
            footnote = "Last failed \(clock(last, now: now, calendar: calendar))" + referenceSuffix(s.lastFailureReferenceID)
        }
        return SyncCopyText(
            title: "You're offline. Changes are saved on this \(device.noun) and sync when you're back online.",
            footnote: footnote)
    }

    /// Nil unless a failure run has started.
    public static func popoverFailing(
        _ s: SyncSnapshot, now: Date, device: DeviceKind, calendar: Calendar
    ) -> SyncCopyText? {
        guard let since = s.failingSince else { return nil }
        let tried = clock(s.lastFailedAttemptAt ?? since, now: now, calendar: calendar)
        return SyncCopyText(
            title: "Couldn't sync since \(clock(since, now: now, calendar: calendar))",
            detail: "Brain Buddy didn't answer. Your changes are safe on this \(device.noun), and it keeps trying.",
            footnote: "Last tried \(tried)" + referenceSuffix(s.lastFailureReferenceID))
    }

    private static func referenceSuffix(_ id: String?) -> String {
        guard let id, !id.isEmpty else { return "" }
        return " · Reference ID \(id)"
    }

    public static func popoverSessionEnded(device: DeviceKind) -> SyncCopyText {
        SyncCopyText(
            title: "Your session ended",
            detail: "Sign in again to keep syncing. Your changes stay on this \(device.noun) until then.")
    }

    public static func popoverAccountLess(device: DeviceKind) -> SyncCopyText {
        let other = device == .mac ? "iPhone" : "Mac"
        return SyncCopyText(
            title: "Your tasks are stored on this \(device.noun)",
            detail: "Nothing is sent anywhere until you sign in. Sign in to use the same tasks on your \(other) and the web.")
    }

    /// Mac only. `until` is `importedAt + 30 days`; once it has passed, the backup is still kept
    /// until sign-out, or for good while some records could not be carried over (data-model E8).
    public static func popoverBackup(until: Date, notCarried: Bool, now: Date, calendar: Calendar) -> String {
        let lead = "Backup from before the update"
        if until > now { return "\(lead) · kept until \(dayMonth(until, now: now, calendar: calendar))" }
        return notCarried
            ? "\(lead) · kept because some records couldn't be carried over" : "\(lead) · removed when you sign out"
    }

    public static let popoverLaterFile = "A file from the previous version is on this Mac. It was not added."
    public static let popoverImportAdjusted = "Some details changed during the update."
    public static let popoverFirstLoadEmpty = "Your tasks are still arriving."

    // MARK: Sign out

    /// The unsent-changes variants of the sign-out alert; a session that ended says how to send them first.
    public static func signOutUnsent(count: Int, offline: Bool, sessionEnded: Bool, device: DeviceKind) -> SyncCopyText {
        let one = count == 1
        var detail = "Sign out and remove \(one ? "it" : "them") from this \(device.noun)?"
        if sessionEnded {
            detail += " To send \(one ? "it" : "them") first, choose Cancel and sign in again."
        } else {
            detail += " \(one ? "It hasn't" : "They haven't") reached your account."
            if offline { detail += " You're offline, so \(one ? "it" : "they") can't be sent now." }
        }
        return SyncCopyText(title: "\(changes(count)) \(one ? "hasn't" : "haven't") synced yet.", detail: detail)
    }

    public static func signOutNothingUnsent(device: DeviceKind) -> SyncCopyText {
        SyncCopyText(
            title: "Sign out?", detail: "Your tasks are removed from this \(device.noun). They stay in your account.")
    }

    public static func signOutIssues(count: Int, device: DeviceKind) -> String {
        "\(changes(count)) that couldn't sync will also be removed from this \(device.noun)."
    }

    /// Mac only. Undated once the date has passed while the backup is still kept.
    public static func signOutBackup(until: Date, now: Date, calendar: Calendar) -> String {
        let base = "A copy of your tasks from before the update stays on this Mac"
        guard until > now else { return base + "." }
        return base + " until \(dayMonth(until, now: now, calendar: calendar))."
    }

    public static let signOutBackupRemoved = "The copy of your tasks from before the update will also be removed from this Mac."

    /// The whole confirmation, its sentences in order: the base text, the open issues, then the backup note.
    public static func signOutConfirmation(
        unsent: Int, offline: Bool, sessionEnded: Bool, issues: Int, backup: SignOutBackupNote?,
        device: DeviceKind, now: Date, calendar: Calendar
    ) -> SyncCopyText {
        var text =
            unsent > 0
            ? signOutUnsent(count: unsent, offline: offline, sessionEnded: sessionEnded, device: device)
            : signOutNothingUnsent(device: device)
        var sentences = [text.detail].compactMap { $0 }
        if issues > 0 { sentences.append(signOutIssues(count: issues, device: device)) }
        switch backup {
        case .kept(let until)?: sentences.append(signOutBackup(until: until, now: now, calendar: calendar))
        case .removed?: sentences.append(signOutBackupRemoved)
        case nil: break
        }
        text.detail = sentences.joined(separator: " ")
        return text
    }
}
