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
    /// A runtime issue's "Review" (opens the conflict detail) and its reference "Copy" (spec 026, D-01/D-02).
    case openConflict(String)
    case runtimeCopy(String)
    /// D-03's recovery actions.
    case recovery(SyncRecoveryAction)
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
    /// Typed Rust-runtime issues (D-01 "Open sync issues"), listed after the legacy ones.
    package var runtimeIssues: [SyncPopoverRuntimeIssue] = []
    /// D-03: update needed, rebuilding, interrupted or uncertain migration; nil when nothing to recover.
    package var recovery: SyncRecoveryContent?

    /// The design's Tab order (planning review c2, G27), with only the controls that are shown and
    /// enabled.
    package var tabOrder: [SyncPopoverControl] {
        var order: [SyncPopoverControl] = []
        // Update-needed outranks every other state (design D-01 priority); its actions come first.
        if let recovery { order.append(contentsOf: recovery.actions.map { .recovery($0) }) }
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
        for issue in runtimeIssues {
            if issue.referenceID != nil { order.append(.runtimeCopy(issue.id)) }
            order.append(.openConflict(issue.id))
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
        if let recovery, recovery.condition.isBlocking, let first = recovery.actions.first { return .recovery(first) }
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
        discarded: Set<SyncIssue.ID> = [], runtimeIssues: [SyncRuntimeIssue] = [],
        recovery: SyncRecoveryCondition? = nil, now: Date, device: DeviceKind = .mac, calendar: Calendar = .current
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
            content.runtimeIssues = runtimeRows(runtimeIssues)
            let open = content.issues.filter { !$0.discarded }.count + content.runtimeIssues.count
            if open > 0 { content.issuesHeading = "\(SyncCopy.changes(open)) couldn't sync" }
        }
        content.recovery = recovery.map { SyncRecoveryContent($0, pendingCount: snapshot.pendingCount) }
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

    /// The typed runtime issues as rows: actions blocked behind another issue are counted under it,
    /// not rows of their own, so "2 later actions" never inflate the heading count.
    /// Adds the typed runtime issues and a recovery condition to content built without them (the
    /// controller's `popoverContent()`), keeping the heading count honest.
    package static func adding(
        runtimeIssues: [SyncRuntimeIssue], recovery: SyncRecoveryCondition? = nil, pendingCount: Int = 0,
        to content: SyncPopoverContent
    ) -> SyncPopoverContent {
        var content = content
        guard content.email != nil else { return content }
        content.runtimeIssues = runtimeRows(runtimeIssues)
        let open = content.issues.filter { !$0.discarded }.count + content.runtimeIssues.count
        content.issuesHeading = open > 0 ? "\(SyncCopy.changes(open)) couldn't sync" : nil
        content.recovery = recovery.map { SyncRecoveryContent($0, pendingCount: pendingCount) }
        return content
    }

    static func runtimeRows(_ issues: [SyncRuntimeIssue]) -> [SyncPopoverRuntimeIssue] {
        let blocked = Set(issues.flatMap(\.dependentIDs))
        return issues.filter { !blocked.contains($0.id) && !blocked.contains($0.commandID) }.map { issue in
            SyncPopoverRuntimeIssue(
                id: issue.id, attempted: shortened(issue.summary), why: issue.kind.why,
                referenceID: issue.referenceID, kind: issue.kind, laterActions: issue.dependentIDs.count
            )
        }
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

// MARK: - Typed runtime issues (spec 026, D-01/D-02)

/// What a runtime issue is, from the reason code the Rust core kept (contracts/sync-v1.md error table).
package enum SyncRuntimeIssueKind: Equatable, Sendable {
    /// Concurrent edit of one field: choose a version (D-02.01).
    case versionConflict
    /// Deleted elsewhere while edited here (D-02.09).
    case deletedElsewhere
    /// An earlier action was rejected, so this one waits (D-02.11).
    case dependencyRejected
    /// Any other rejection: kept and shown, never dropped.
    case rejected
    /// The send may or may not have reached the account. Never resolvable here: the runtime reconciles
    /// it first, and nothing here may suggest a retry is safe.
    case unknownOutcome

    package init(reason: String) {
        switch reason.lowercased().filter({ $0 != "_" && $0 != "-" }) {
        case "revisionconflict": self = .versionConflict
        case "entitydeleted": self = .deletedElsewhere
        case "dependencyrejected": self = .dependencyRejected
        default: self = RuntimeIssueKind(reason: reason) == .unknownOutcome ? .unknownOutcome : .rejected
        }
    }

    var why: String {
        switch self {
        case .versionConflict: return "This task changed on another device. Both versions are saved."
        case .deletedElsewhere: return "This item was deleted on another device. Your edit is saved in this issue."
        case .dependencyRejected: return "An earlier change wasn't accepted. This change is saved here."
        case .rejected: return "This change isn't accepted. It is saved here."
        case .unknownOutcome:
            return "We can't tell whether this change reached your account. It is kept and won't be sent again as a new change."
        }
    }
}

/// One typed runtime issue as the Mac sees it. It keeps the core's string ids and the shown base
/// revision; it is never coerced into a legacy `SyncIssue`.
package struct SyncRuntimeIssue: Equatable, Sendable, Identifiable {
    package var id: String
    package var commandID: String
    package var kind: SyncRuntimeIssueKind
    /// What the user attempted, on one line (from the issue's saved text; never a payload).
    package var summary: String
    /// The user's own saved edit, in full.
    package var savedEdit: String?
    package var shownBaseRevision: String?
    package var dependentIDs: [String]
    /// The commands this one's own command waits on (for what a retry would be refused for).
    package var waitsOn: [String]
    /// The record the issue's own command edits.
    package var targetEntity: String?
    /// Safe, opaque id to copy: it carries no task, AI or auth content.
    package var referenceID: String? { id.isEmpty ? nil : id }

    package init(
        id: String, commandID: String, reason: String, summary: String, savedEdit: String? = nil,
        shownBaseRevision: String? = nil, dependentIDs: [String] = [], waitsOn: [String] = [], targetEntity: String? = nil
    ) {
        self.id = id
        self.commandID = commandID
        kind = SyncRuntimeIssueKind(reason: reason)
        self.summary = summary
        self.savedEdit = savedEdit
        self.shownBaseRevision = shownBaseRevision
        self.dependentIDs = dependentIDs
        self.waitsOn = waitsOn
        self.targetEntity = targetEntity
    }

    /// From the kit's issue: every saved text member is kept (`RustWorkspaceIssue.savedFields`).
    package init(_ issue: RustWorkspaceIssue) {
        self.init(
            id: issue.id, commandID: issue.commandID, reason: issue.reason,
            summary: issue.savedSummary, savedEdit: issue.savedEditText,
            shownBaseRevision: issue.shownBaseRevision, dependentIDs: issue.dependentIDs, waitsOn: issue.waitsOn,
            targetEntity: issue.targetEntity
        )
    }
}

package struct SyncPopoverRuntimeIssue: Equatable, Sendable, Identifiable {
    package var id: String
    package var attempted: String
    package var why: String
    package var referenceID: String?
    package var kind: SyncRuntimeIssueKind
    package var laterActions: Int

    package var actionAccessibilityLabel: String { "Review: \(attempted)" }
}

// MARK: - D-02 conflict detail

package enum SyncConflictVersion: String, Equatable, Sendable, Codable { case yours, account }

/// The Mac's name for the shared choice (`DependentChoice`, BrainBuddyCore).
package typealias SyncDependentChoice = DependentChoice

/// A later action blocked behind the conflicted one (D-02.11).
package struct SyncBlockedAction: Equatable, Sendable, Identifiable {
    package var id: String
    package var summary: String
    /// "Keep for later" is the safe initial selection.
    package var choice: SyncDependentChoice = .keepForLater
    /// "Review and retry" needs an explicit approval of the shown preview; never a default.
    package var retryApproved = false
    /// Whether "Review and retry" can be chosen now (the runtime would not refuse it).
    package var retryAvailable = true
    /// The other held actions this one waits on; nil when it is not a saved issue and so can't be
    /// retried from here.
    package var retryWaitsOn: [String]? = []
    /// For an action on another record than the issue's own, the revision its retry preview shows.
    package var shownRevision: String?

    package init(id: String, summary: String, retryWaitsOn: [String]? = [], shownRevision: String? = nil) {
        self.id = id
        self.summary = summary
        self.retryWaitsOn = retryWaitsOn
        self.shownRevision = shownRevision
    }
}

/// What the user decided, to hand to the workspace when it can store it atomically.
package struct SyncConflictResolution: Equatable, Sendable {
    package enum Outcome: Equatable, Sendable {
        case version(SyncConflictVersion)
        case keepDeleted
    }

    package var issueID: String
    package var outcome: Outcome
    /// The revision the user was shown: the resolution applies against it, or not at all.
    package var shownRevision: String?
    package var keep: [String]
    package var retry: [String]
    package var retryRevisions: [String: String] = [:]
    package var discard: [String]

    /// The decision as the workspace takes it: Yours keeps the user's edit, Account uses the
    /// account's version, and a deleted item stays deleted. Every held action is in exactly one list.
    package var runtime: RuntimeIssueResolution {
        let mapped: RuntimeIssueResolution.Outcome
        switch outcome {
        case .version(.yours): mapped = .keepMine
        case .version(.account): mapped = .useAccountVersion
        case .keepDeleted: mapped = .keepDeleted
        }
        return RuntimeIssueResolution(
            issueID: issueID, outcome: mapped, shownRevision: shownRevision, keepForLater: keep,
            retry: RetryDependent.list(ids: retry, revisions: retryRevisions), discard: discard)
    }
}

/// The draft that survives closing, Back, Cancel and relaunch: restoring it never submits. It is the
/// same value the iPhone keeps (`ConflictDecisionDraft`).
package typealias SyncConflictDraft = ConflictDecisionDraft

/// D-02's state machine as a value: a radio choice with no default, Apply gated on every needed
/// decision, discard behind the named confirmation, a changed account side clearing approvals. The
/// decision itself (choices, approvals, discard confirmation, what the runtime would refuse) is the
/// shared `ConflictDecisionDraft`; this adds the Mac's wording, phases and focus.
package struct SyncConflictModel: Equatable, Sendable {
    package enum Phase: Equatable, Sendable {
        case choosing
        case confirmingDiscard
        /// "Saving your choice…": a second submit creates no second resolution.
        case saving
        case saveFailed
        /// Stored durably and waiting to sync; both originals remain.
        case waiting
        case changedAgain
    }

    package let issueID: String
    package let kind: SyncRuntimeIssueKind
    package private(set) var accountVersion: String?
    package let yourEdit: String
    private var core: ConflictDecisionDraft
    private let held: [SyncBlockedAction]
    private var storedWaiting = false

    /// The account's record could not be read, so there is no revision to decide against yet.
    private var accountUnreadable: Bool

    package init(issue: SyncRuntimeIssue, accountVersion: String?, blocked: [SyncBlockedAction] = []) {
        self.init(
            issue: issue, accountVersion: accountVersion, shownRevision: issue.shownBaseRevision, unreadable: false,
            blocked: blocked)
    }

    /// With the account's record as the workspace read it: its text is the account side, and its
    /// edit revision is the one a kept edit is decided against. `nil` means it could not be read; then
    /// nothing can be applied until it is (a deleted-elsewhere item needs no account version).
    package init(issue: SyncRuntimeIssue, account: RuntimeIssueAccountVersion?, blocked: [SyncBlockedAction] = []) {
        self.init(
            issue: issue, accountVersion: account.flatMap(Self.text(of:)), shownRevision: account?.revision,
            unreadable: account == nil && issue.kind != .deletedElsewhere, blocked: blocked)
    }

    private init(
        issue: SyncRuntimeIssue, accountVersion: String?, shownRevision: String?, unreadable: Bool,
        blocked: [SyncBlockedAction]
    ) {
        issueID = issue.id
        kind = issue.kind
        self.accountVersion = accountVersion
        accountUnreadable = unreadable
        yourEdit = issue.savedEdit ?? issue.summary
        held = blocked
        var rules: [String: [String]] = [:]
        var revisions: [String: String] = [:]
        for action in blocked {
            if let waitsOn = action.retryWaitsOn { rules[action.id] = waitsOn }
            if let shown = action.shownRevision { revisions[action.id] = shown }
        }
        core = ConflictDecisionDraft(
            dependentIDs: blocked.map(\.id), shownRevision: shownRevision, issueID: issue.id,
            requiresVersion: issue.kind != .deletedElsewhere, retryDependencies: rules,
            dependentRevisions: revisions)
    }

    package var shownRevision: String? { core.shownRevision }

    package var selected: SyncConflictVersion? {
        core.version.map { $0 == .saved ? SyncConflictVersion.yours : .account }
    }

    package var actions: [SyncBlockedAction] {
        held.map { action in
            var action = action
            action.choice = core.choice(for: action.id)
            action.retryApproved = core.approvedRetries.contains(action.id)
            action.retryAvailable = core.canRetry(action.id)
            return action
        }
    }

    package var phase: Phase {
        if storedWaiting { return .waiting }
        switch core.phase {
        case .choosing: return .choosing
        case .confirmingDiscard: return .confirmingDiscard
        case .saving: return .saving
        case .saveFailed: return .saveFailed
        case .changedAgain: return .changedAgain
        }
    }

    package var title: String {
        switch kind {
        case .deletedElsewhere: "Deleted on another device"
        case .unknownOutcome: "Earlier changes need verification"
        default: "Choose a title"
        }
    }
    package var versionLabels: [(SyncConflictVersion, String)] {
        [(.yours, "Your saved edit"), (.account, "Current account version")]
    }
    package var blockedHeading: String? {
        held.isEmpty ? nil : "\(held.count) later action\(held.count == 1 ? "" : "s") need your decision"
    }
    package var statusLine: String? {
        switch phase {
        case .saving: return "Saving your choice…"
        case .saveFailed: return "Your choice wasn't saved. Try again."
        case .waiting: return "Your choice is saved and waiting to sync."
        case .changedAgain: return "This task changed again. Review both versions."
        case .choosing, .confirmingDiscard: return accountUnreadable ? "Couldn't read the account's version. Try again." : nil
        }
    }

    private var discardCount: Int { core.discardedIDs.count }
    package var confirmDiscardTitle: String { "Discard these \(discardCount) saved action\(discardCount == 1 ? "" : "s")?" }
    package var confirmDiscardButton: String { "Discard \(discardCount) action\(discardCount == 1 ? "" : "s")" }
    package let confirmDiscardDetail = ConflictDecisionDraft.discardExplanation
    /// The exact summaries the confirmation names. Cancel is its initially focused control.
    package var discardSummaries: [String] { actions.filter { $0.choice == .discard }.map(\.summary) }

    package enum InitialFocus: Equatable, Sendable { case title, blockedHeading, cancelDiscard }

    /// Where focus starts: Cancel in the discard confirmation, the dependent-actions heading when
    /// later actions need a decision, otherwise the title. Each is a rendered, focusable view.
    package var initialFocus: InitialFocus {
        if phase == .confirmingDiscard { return .cancelDiscard }
        return held.isEmpty ? .title : .blockedHeading
    }

    package var isEditable: Bool { phase == .choosing || phase == .changedAgain || phase == .saveFailed }

    /// Apply stays disabled until a version is picked (no default) and every retry is approved.
    package var isResolvable: Bool { kind != .unknownOutcome }
    package var applyEnabled: Bool { isResolvable && isEditable && !accountUnreadable && core.readyToApply }

    /// Why "Review and retry" can't be chosen for `id` yet, or nil when it can.
    package func retryUnavailableReason(for id: String) -> String? { core.retryUnavailableReason(for: id) }

    package mutating func select(_ version: SyncConflictVersion) {
        guard isEditable else { return }
        core.choose(version == .yours ? .saved : .account)
    }

    package mutating func setChoice(_ choice: SyncDependentChoice, for id: String) {
        guard isEditable else { return }
        core.setChoice(choice, for: id)
    }

    package mutating func approveRetry(_ id: String) {
        guard isEditable else { return }
        core.approveRetry(for: id)
    }

    package mutating func withdrawRetryApproval(_ id: String) {
        guard isEditable else { return }
        core.withdrawRetryApproval(for: id)
    }

    /// "Apply choice": asks for the named discard confirmation, or submits.
    package mutating func apply() -> SyncConflictResolution? {
        guard applyEnabled else { return nil }
        if discardCount > 0 {
            core.requestDiscard()
            return nil
        }
        return begin()
    }

    package mutating func confirmDiscard() -> SyncConflictResolution? {
        guard core.phase == .confirmingDiscard else { return nil }
        core.confirmDiscard()
        return begin()
    }

    /// Cancel returns to the sheet with every choice kept.
    package mutating func cancelDiscard() { core.cancelDiscard() }

    private mutating func begin() -> SyncConflictResolution? {
        guard let decision = core.apply() else { return nil }
        return SyncConflictResolution(
            issueID: issueID, outcome: kind == .deletedElsewhere ? .keepDeleted : .version(selected ?? .yours),
            shownRevision: decision.againstRevision, keep: decision.keepForLater, retry: decision.retry,
            retryRevisions: decision.retryRevisions, discard: decision.discard)
    }

    package mutating func saveFailed() { core.saveFailed() }
    package mutating func savedWhileOffline() { if core.phase == .saving { storedWaiting = true } }

    /// What became of the applied decision (the workspace's answer). A record that changed again
    /// shows the account's new text and keeps the draft; any other refusal keeps it and offers a retry.
    package mutating func finish(_ outcome: RuntimeIssueApplyOutcome) {
        if case .changedAgain(let current) = outcome {
            accountVersion = current.flatMap(Self.text(of:))
            if current != nil { accountUnreadable = false }
        }
        core.finish(outcome, keepingVersion: true)
    }

    /// The account's text for the field the user edited, in the keys `SyncRuntimeIssue` reads.
    package static func text(of version: RuntimeIssueAccountVersion) -> String? {
        guard !version.isDeleted else { return nil }
        return version.fields["after"] ?? version.fields["title"] ?? version.fields["text"]
            ?? version.fields.sorted { $0.key < $1.key }.first?.value
    }

    /// The account side moved after the card opened: show it, keep the user's draft and original
    /// edit, clear every approval and require an explicit apply again (D-02.08).
    package mutating func accountChanged(revision: String?, accountVersion: String?) {
        if accountUnreadable {
            // The first successful read: nothing changed, there was just nothing to compare with.
            accountUnreadable = false
            self.accountVersion = accountVersion
            core.adoptRevision(revision)
            return
        }
        guard revision != shownRevision || accountVersion != self.accountVersion else { return }
        self.accountVersion = accountVersion
        storedWaiting = false
        core.markChangedAgain(revision: revision, keepingVersion: true)
    }

    package var draft: SyncConflictDraft { core }

    /// Relaunch: the draft returns as it was; nothing is submitted and no discard is pre-confirmed.
    package mutating func restore(_ draft: SyncConflictDraft) { core.restore(from: draft) }
}

// MARK: - D-03 recovery

package enum SyncRecoveryAction: Hashable, Sendable {
    case updateApp, tryAgain, rebuildSyncedCopy, exportSavedData, openImportReport
    case copyReference(String)
}

package enum SyncRecoveryCondition: Equatable, Sendable {
    case updateNeededSync
    case updateNeededStore
    case rebuilding
    case rebuildFailed(referenceID: String?)
    case importFailed
    case migrationUncertain
    case interrupted

    /// States where sync is stopped.
    package var isBlocking: Bool { self == .updateNeededSync || self == .updateNeededStore }
}

/// D-03's words and actions; waiting changes and saved conflicts are always named as kept.
package struct SyncRecoveryContent: Equatable, Sendable {
    package var condition: SyncRecoveryCondition
    package var title: String
    package var detail: String
    package var actions: [SyncRecoveryAction]
    package var referenceID: String?

    package init(_ condition: SyncRecoveryCondition, pendingCount: Int) {
        self.condition = condition
        referenceID = nil
        switch condition {
        case .updateNeededSync:
            title = "Update needed to sync"
            detail = "Your saved tasks and waiting changes stay on this device."
            actions = [.updateApp]
        case .updateNeededStore:
            title = "Update needed to open tasks"
            detail = "Nothing is written and nothing syncs until you update."
            actions = [.updateApp, .tryAgain, .exportSavedData]
        case .rebuilding:
            title = "Rebuilding synced copy…"
            detail = "\(SyncCopy.changes(pendingCount)) waiting. Your waiting changes and saved conflicts will be kept."
            actions = []
        case .rebuildFailed(let reference):
            title = "Couldn't rebuild the synced copy."
            detail = "Your waiting changes are saved."
            actions = [.tryAgain] + (reference.map { [.copyReference($0)] } ?? [])
            referenceID = reference
        case .importFailed:
            title = "Couldn't import earlier data"
            detail = "Your earlier data file is unchanged. The new store hasn't been activated."
            actions = [.openImportReport, .tryAgain]
        case .migrationUncertain:
            title = "Earlier changes need verification"
            detail = "Your earlier store and waiting changes are kept while sync checks what reached your account."
            actions = [.tryAgain]
        case .interrupted:
            title = "Connect to finish recovery"
            detail = "Your waiting changes are saved. Recovery resumes from where it stopped."
            actions = []
        }
    }
}

extension SyncRecoveryCondition {
    /// The recovery state the workspace reports. `updateNeededSync` is the sync transport's
    /// `UPGRADE_REQUIRED`; the store being newer than this build outranks it.
    package init?(_ recovery: RuntimeSyncRecovery) {
        if recovery.storeNeedsUpdate {
            self = .updateNeededStore
        } else if recovery.syncNeedsUpdate {
            self = .updateNeededSync
        } else if recovery.rebuild == .rebuilding {
            self = .rebuilding
        } else if case .failed(let reference) = recovery.rebuild {
            self = .rebuildFailed(referenceID: reference)
        } else if recovery.epochClosed {
            self = .migrationUncertain
        } else {
            return nil
        }
    }
}
