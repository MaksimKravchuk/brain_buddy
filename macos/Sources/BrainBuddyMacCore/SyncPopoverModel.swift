import BrainBuddyCore
import Foundation

/// Every focusable control of X-02, in the words of the design.
package enum SyncPopoverControl: Hashable, Sendable {
    /// The attention action: "Sign in again" (session ended).
    case signInAgain
    /// "Sign in…" (account-less).
    case signIn
    /// The failing notice's "Copy" (its reference id).
    case failingCopy
    case issueCopy(SyncIssue.ID)
    case copyOutcome(SyncIssue.ID)
    case dismiss(SyncIssue.ID)
    case discardOutcome(SyncIssue.ID)
    /// "Outcome discarded · Undo", for 5 s after a discard.
    case undoDiscard(SyncIssue.ID)
    case syncNow
    /// The offline notice's last-failure "Copy".
    case offlineCopy
    case signOut
    case backupShowInFinder, reportShowInFinder, laterFileShowInFinder
}

/// The pre-upgrade files X-02 has a line for (data-model E8, FR-021, FR-033).
package struct MacUpgradeFiles: Equatable, Sendable {
    /// The pre-upgrade backup: its file and the date the rule may delete it.
    package var backup: URL?
    package var backupKeptUntil: Date?
    /// Some records could not be carried over, so the backup is kept past its date.
    package var notCarried: Bool
    /// The import report (`popoverImportAdjusted`).
    package var report: URL?
    /// A previous-version file kept as found (`popoverLaterFile`).
    package var laterFile: URL?

    package init(
        backup: URL? = nil, backupKeptUntil: Date? = nil, notCarried: Bool = false, report: URL? = nil, laterFile: URL? = nil
    ) {
        self.backup = backup
        self.backupKeptUntil = backupKeptUntil
        self.notCarried = notCarried
        self.report = report
        self.laterFile = laterFile
    }

    package static let none = MacUpgradeFiles()
}

/// One sync issue as X-02 lists it.
package struct SyncPopoverIssue: Equatable, Sendable, Identifiable {
    package var id: SyncIssue.ID
    /// What was attempted, on one line, shortened past 60 characters.
    package var attempted: String
    package var why: String
    package var referenceID: String?
    /// A merge kept the account's outcome: the Mac's own outcome, in full, never shortened.
    package var keptOutcome: String?
    /// "Discard your outcome for “Garden”" (kept outcome) or "Dismiss: <issue>".
    package var actionAccessibilityLabel: String
    /// Discarded less than 5 s ago: the row reads "Outcome discarded · Undo".
    package var discarded: Bool

    package var isKeptOutcome: Bool { keptOutcome != nil }
}

/// X-02's content (contracts/mac-app-host.md §6, design X-02): which lines, which controls, the Tab
/// order and the focus rules. Built from the snapshot and the issues for the popover's view, which
/// only lays it out; focus moves go through `MacPresentationRouter`.
package struct SyncPopoverContent: Equatable, Sendable {
    package enum Notice: Equatable, Sendable {
        case accountLess(SyncCopyText)
        case sessionEnded(SyncCopyText)
        case failing(SyncCopyText, referenceID: String?)
        case offline(SyncCopyText, referenceID: String?)
    }

    package var notice: Notice?
    /// "Last synced · Today at 14:31"; nil account-less or before the first sync.
    package var lastSynced: String?
    /// The waiting line, or the first-upload line instead of it; nil account-less.
    package var queue: String?
    /// "2 changes couldn't sync"; nil when there is none.
    package var issuesHeading: String?
    package var issues: [SyncPopoverIssue]
    /// "Sync now" is shown whenever an account is linked, disabled (never hidden) where no sync can run.
    package var syncNowShown: Bool
    package var syncNowEnabled: Bool
    package var email: String?
    package var backupLine: String?
    package var reportLine: String?
    package var laterFileLine: String?

    /// The design's Tab order (planning review c2, G27), with only the controls that are shown and
    /// enabled.
    package var tabOrder: [SyncPopoverControl] {
        var order: [SyncPopoverControl] = []
        switch notice {
        case .sessionEnded?: order.append(.signInAgain)
        case .accountLess?: order.append(.signIn)
        case .failing(_, let reference)? where reference != nil: order.append(.failingCopy)
        default: break
        }
        for issue in issues {
            if issue.discarded {
                order.append(.undoDiscard(issue.id))
                continue
            }
            if issue.referenceID != nil { order.append(.issueCopy(issue.id)) }
            if issue.isKeptOutcome {
                order.append(.copyOutcome(issue.id))
                order.append(.discardOutcome(issue.id))
            } else {
                order.append(.dismiss(issue.id))
            }
        }
        if syncNowShown, syncNowEnabled { order.append(.syncNow) }
        if case .offline(_, let reference)? = notice, reference != nil { order.append(.offlineCopy) }
        if email != nil { order.append(.signOut) }
        if backupLine != nil { order.append(.backupShowInFinder) }
        if reportLine != nil { order.append(.reportShowInFinder) }
        if laterFileLine != nil { order.append(.laterFileShowInFinder) }
        return order
    }

    /// Focus on open: the attention action; otherwise "Sync now" when enabled; otherwise "Sign in…"
    /// when account-less; otherwise the first enabled control.
    package var initialFocus: SyncPopoverControl? {
        switch notice {
        case .sessionEnded?: return .signInAgain
        case .failing(_, let reference)? where reference != nil: return .failingCopy
        default: break
        }
        if syncNowShown, syncNowEnabled { return .syncNow }
        if case .accountLess? = notice { return .signIn }
        return tabOrder.first
    }

    /// Focus after "Dismiss" (or a discard that went for good) on `id`, computed with the issues as
    /// they were: the next issue's Copy, or the previous issue's when the last row went; after the
    /// last issue, "Sync now", or "Sign out…" when Sync now is disabled.
    package func focusAfterRemoving(_ id: SyncIssue.ID) -> SyncPopoverControl? {
        guard let index = issues.firstIndex(where: { $0.id == id }) else { return nil }
        let remaining = issues.enumerated().filter { $0.element.id != id }.map(\.element)
        if !remaining.isEmpty {
            let neighbour = index < remaining.count ? remaining[index] : remaining[remaining.count - 1]
            return Self.firstControl(of: neighbour)
        }
        if syncNowShown, syncNowEnabled { return .syncNow }
        if email != nil { return .signOut }
        return nil
    }

    /// The issue's first control: its Copy, or the next control it has when it has no reference.
    private static func firstControl(of issue: SyncPopoverIssue) -> SyncPopoverControl {
        if issue.discarded { return .undoDiscard(issue.id) }
        if issue.referenceID != nil { return .issueCopy(issue.id) }
        return issue.isKeptOutcome ? .copyOutcome(issue.id) : .dismiss(issue.id)
    }
}

package enum SyncPopoverModel {
    /// Titles past this length are shortened on one line (design X-02 "long text, many issues").
    package static let titleLimit = 60

    package static func content(
        snapshot: SyncSnapshot, issues: [SyncIssue], state: GTDState, files: MacUpgradeFiles,
        discarded: Set<SyncIssue.ID> = [], now: Date, device: DeviceKind = .mac, calendar: Calendar = .current
    ) -> SyncPopoverContent {
        let line = SyncStatusDescriber.describe(snapshot, now: now, device: device, calendar: calendar)
        var content = SyncPopoverContent(
            notice: nil, lastSynced: nil, queue: nil, issuesHeading: nil, issues: [], syncNowShown: false,
            syncNowEnabled: false, email: nil, backupLine: nil, reportLine: nil, laterFileLine: nil
        )
        switch snapshot.account {
        case .none:
            content.notice = .accountLess(SyncCopy.popoverAccountLess(device: device))
        case .linked(let email):
            content.email = email
            content.syncNowShown = true
            content.syncNowEnabled = syncNowAvailable(snapshot, line)
            content.lastSynced = snapshot.lastSyncedAt.map { SyncCopy.popoverLastSynced($0, now: now, calendar: calendar) }
            content.queue = SyncCopy.popoverQueue(snapshot, now: now)
            if snapshot.sessionEnded {
                content.notice = .sessionEnded(SyncCopy.popoverSessionEnded(device: device))
            } else if !snapshot.isOnline {
                content.notice = .offline(
                    SyncCopy.popoverOffline(snapshot, now: now, device: device, calendar: calendar),
                    referenceID: snapshot.lastFailedAttemptAt == nil ? nil : nonEmpty(snapshot.lastFailureReferenceID)
                )
            } else if failureSurfaced(snapshot),
                let failing = SyncCopy.popoverFailing(snapshot, now: now, device: device, calendar: calendar)
            {
                // Shown whenever the 60 s have passed, also when rejected changes win the line: the
                // popover shows every state that holds.
                content.notice = .failing(failing, referenceID: nonEmpty(snapshot.lastFailureReferenceID))
            }
            content.issues = issues.map { row($0, state: state, discarded: discarded.contains($0.id)) }
            let open = content.issues.filter { !$0.discarded }.count
            if open > 0 { content.issuesHeading = "\(SyncCopy.changes(open)) couldn't sync" }
        }
        if files.backup != nil, let until = files.backupKeptUntil {
            content.backupLine = SyncCopy.popoverBackup(until: until, notCarried: files.notCarried, now: now, calendar: calendar)
        }
        if files.report != nil { content.reportLine = SyncCopy.popoverImportAdjusted }
        if files.laterFile != nil { content.laterFileLine = SyncCopy.popoverLaterFile }
        return content
    }

    /// "Sync now" (X-02, X-07 and X-01's Retry): the line's `syncNowEnabled` (false account-less,
    /// offline or with the session ended; never false because a sync runs), and also false offline or
    /// with the session ended when another state wins the line, such as rejected changes, because no
    /// sync can run then either (the popover shows every state that holds).
    package static func syncNowAvailable(_ snapshot: SyncSnapshot, _ line: SyncStatusDescription) -> Bool {
        line.syncNowEnabled && snapshot.account != .none && snapshot.isOnline && !snapshot.sessionEnded
    }

    /// The failure run has lasted 60 s with an attempt at or after the mark (sync-status §3), the
    /// rule `SyncStatusDescriber` uses for "Couldn't sync".
    static func failureSurfaced(_ snapshot: SyncSnapshot) -> Bool {
        guard let since = snapshot.failingSince, let last = snapshot.lastFailedAttemptAt else { return false }
        return (last.timeIntervalSince(since) * 1000).rounded() >= SyncTiming.failureSurfacesAfter * 1000
    }

    static func row(_ issue: SyncIssue, state: GTDState, discarded: Bool) -> SyncPopoverIssue {
        let description = SyncIssueDescriber.describe(issue, in: state)
        let label: String
        if description.keptOutcome != nil, case .setProjectOutcome(let project, _) = issue.command {
            label = "Discard your outcome for “\(state.projects[project]?.name ?? "this project")”"
        } else {
            label = "Dismiss: \(description.attempted)"
        }
        return SyncPopoverIssue(
            id: issue.id, attempted: shortened(description.attempted), why: description.why,
            referenceID: nonEmpty(description.referenceID), keptOutcome: description.keptOutcome,
            actionAccessibilityLabel: label, discarded: discarded
        )
    }

    /// One line: past `titleLimit` characters the text ends in "…".
    package static func shortened(_ text: String) -> String {
        guard text.count > titleLimit else { return text }
        return String(text.prefix(titleLimit - 1)) + "…"
    }

    private static func nonEmpty(_ text: String?) -> String? {
        guard let text, !text.isEmpty else { return nil }
        return text
    }
}

extension LegacyImportCoordinator {
    /// The files X-02 has a quiet line for, as they are on disk now.
    package func upgradeFiles() -> MacUpgradeFiles {
        var files = MacUpgradeFiles()
        let record = localState.load()?.legacyImport
        if let backup = backup() {
            files.backup = backup.file
            files.backupKeptUntil = backup.keptUntil
            files.notCarried = (record?.report?.notCarriedCount ?? 0) > 0
        }
        if let record, record.backupDeletedAt == nil, let name = record.report?.fileName, MacFiles.exists(folder.file(name)) {
            files.report = folder.file(name)
        }
        if record?.laterFile != nil, MacFiles.exists(folder.legacy) { files.laterFile = folder.legacy }
        return files
    }
}

/// "Discard outcome", then "Outcome discarded · Undo" for 5 s (design X-02 "outcome kept on
/// account"; review c2, G32): the issue is dismissed in the workspace only when the 5 s have passed
/// (or the popover closes), so Undo needs nothing from the kit.
package struct OutcomeDiscards: Equatable, Sendable {
    package static let undoWindow: TimeInterval = 5

    private var discardedAt: [SyncIssue.ID: Date] = [:]

    package init() {}

    package var ids: Set<SyncIssue.ID> { Set(discardedAt.keys) }

    package mutating func discard(_ id: SyncIssue.ID, at now: Date) { discardedAt[id] = now }

    /// Undo restores the issue.
    package mutating func undo(_ id: SyncIssue.ID) { discardedAt[id] = nil }

    /// The discards whose 5 s are over, to dismiss for good; they leave this list.
    package mutating func expired(at now: Date) -> [SyncIssue.ID] {
        let due = discardedAt.filter { now.timeIntervalSince($0.value) >= Self.undoWindow }.map(\.key)
        for id in due { discardedAt[id] = nil }
        return due.sorted { $0.uuidString < $1.uuidString }
    }

    /// Every discard, when the popover closes and Undo is no longer on screen.
    package mutating func all() -> [SyncIssue.ID] {
        defer { discardedAt = [:] }
        return discardedAt.keys.sorted { $0.uuidString < $1.uuidString }
    }

    /// When the next discard goes for good.
    package var nextExpiry: Date? { discardedAt.values.min().map { $0.addingTimeInterval(Self.undoWindow) } }
}
