import Foundation

// How the shared runtime's typed issues (`RustWorkspaceIssue`) are worded and what the user may do
// about them (spec 026 design M-01/M-02/M-03, D-02.11-12). Pure values, so every state is tested on
// Linux; the screens only render. Nothing here sends or resolves anything: it says which choices are
// legal and whether the draft of a decision may be applied.

/// What kind of problem a runtime issue reports, from its reason code.
public enum RuntimeIssueKind: Equatable, Sendable {
    /// The record changed after the user was shown it.
    case versionConflict
    /// The record was deleted elsewhere; it is never recreated.
    case deletedElsewhere
    /// Held behind a rejected earlier action (kept, not dropped).
    case blockedDependent
    /// A command this one builds on was rejected.
    case dependencyRejected
    /// The send may or may not have reached the account; never re-sent under a new ID.
    case unknownOutcome
    /// Any other canonical refusal; the code is kept for the reference line only.
    case rejected(code: String)

    public init(reason: String) {
        let code = reason.uppercased()
        switch code {
        case "REVISION_CONFLICT": self = .versionConflict
        case "ENTITY_DELETED": self = .deletedElsewhere
        case "BLOCKED_DEPENDENCY": self = .blockedDependent
        case "DEPENDENCY_REJECTED": self = .dependencyRejected
        default:
            if code.contains("UNKNOWN") || code.contains("UNCERTAIN") {
                self = .unknownOutcome
            } else {
                self = .rejected(code: reason)
            }
        }
    }
}

/// A choice offered for an issue.
public enum RuntimeIssueAction: Equatable, Sendable {
    case chooseVersion, copySavedEdit, keepItemDeleted, reviewDependents
    case keepForLater, reviewAndRetry, discardAction, copyReference
}

/// One saved field of the user's edit, in a stable order.
public struct RuntimeSavedField: Equatable, Sendable {
    public let name: String
    public let value: String
}

/// One issue as the list row and the detail render it.
public struct RuntimeIssueCard: Identifiable, Equatable, Sendable {
    public let id: String
    public let kind: RuntimeIssueKind
    public let title: String
    public let message: String
    /// The user's own text, exactly as saved. Never trimmed or truncated.
    public let savedFields: [RuntimeSavedField]
    /// The version the user was shown when they made the edit.
    public let shownVersion: String?
    /// Opaque, payload-free reference to quote when reporting.
    public let referenceID: String
    public let blockedDependentCount: Int
    public let actions: [RuntimeIssueAction]
    public let accessibilityLabel: String
}

public enum RuntimeIssuePresenter {
    /// Cards for `issues`, oldest unresolved first so dependants follow their predecessor.
    public static func cards(_ issues: [RustWorkspaceIssue]) -> [RuntimeIssueCard] {
        issues.sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }.map(card)
    }

    public static func card(_ issue: RustWorkspaceIssue) -> RuntimeIssueCard {
        let kind = RuntimeIssueKind(reason: issue.reason)
        let fields = issue.localText.sorted { $0.key < $1.key }.map { RuntimeSavedField(name: $0.key, value: $0.value) }
        let dependents = issue.dependentIDs.count
        var title = "", message = "", actions: [RuntimeIssueAction] = []
        switch kind {
        case .versionConflict:
            title = "Choose a version"
            message = "This item changed on your account after you edited it. Both versions are saved."
            actions = [.chooseVersion, .copySavedEdit]
        case .deletedElsewhere:
            title = "Deleted on another device"
            message = "This item was deleted on another device. Your edit is saved in this issue."
            actions = [.copySavedEdit, .keepItemDeleted]
        case .blockedDependent:
            title = "Waiting for an earlier action"
            message = "This saved action is kept. It needs your decision once the earlier action is resolved."
            actions = [.keepForLater, .reviewAndRetry, .discardAction]
        case .dependencyRejected:
            title = "An earlier action was rejected"
            message = "This saved action builds on one that couldn't sync. It is kept until you decide."
            actions = [.keepForLater, .reviewAndRetry, .discardAction]
        case .unknownOutcome:
            title = "Earlier changes need verification"
            message = "We can't tell whether this change reached your account. It is kept and won't be sent again as a new change."
            actions = [.copySavedEdit]
        case .rejected:
            title = "This change couldn't sync"
            message = "The change is saved on this device but your account couldn't apply it."
        }
        if dependents > 0 {
            message += " " + laterActions(dependents) + " need your decision."
            if !actions.contains(.reviewDependents) { actions.append(.reviewDependents) }
        }
        if fields.isEmpty { actions.removeAll { $0 == .copySavedEdit } }
        actions.append(.copyReference)
        let label = ([title, message] + fields.map { "\($0.name): \($0.value)" } + ["Reference ID: \(issue.id)"])
            .joined(separator: ". ")
        return RuntimeIssueCard(
            id: issue.id, kind: kind, title: title, message: message, savedFields: fields,
            shownVersion: issue.shownBaseRevision, referenceID: issue.id,
            blockedDependentCount: dependents, actions: actions, accessibilityLabel: label)
    }

    /// "1 later action" / "2 later actions".
    public static func laterActions(_ count: Int) -> String {
        count == 1 ? "1 later action" : "\(SyncCopy.grouped(count)) later actions"
    }

    /// The saved action summaries of `issue`'s dependants, in dependency order (creation order).
    /// A dependant that is not (or no longer) an open issue reads "Saved action".
    public static func dependentSummaries(of issue: RustWorkspaceIssue, among all: [RustWorkspaceIssue])
        -> [DependentSummary]
    {
        let byID = Dictionary(all.flatMap { [($0.id, $0), ($0.commandID, $0)] }, uniquingKeysWith: { first, _ in first })
        return issue.dependentIDs.map { id in
            let known = byID[id]
            let text = known?.localText.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value)" }.joined(separator: " · ")
            return DependentSummary(id: id, summary: (text?.isEmpty == false ? text : nil) ?? "Saved action",
                                    shownVersion: known?.shownBaseRevision)
        }
    }
}

public struct DependentSummary: Identifiable, Equatable, Sendable {
    public let id: String
    public let summary: String
    public let shownVersion: String?
}

// MARK: - M-02 decision draft

/// Which version of the conflicting field the user chose.
public enum ConflictVersion: Equatable, Sendable { case saved, account }

/// What to do with one later action.
public enum DependentChoice: Equatable, Sendable { case keepForLater, reviewAndRetry, discard }

/// The user's unsent decision for one conflict (M-02.01, .08, .11, .12). Holding a draft never
/// submits anything: relaunch restores it, and only `apply` (after `canApply`) produces a decision.
public struct ConflictDecisionDraft: Equatable, Sendable {
    public enum Phase: Equatable, Sendable {
        case choosing, confirmingDiscard, saving, changedAgain
    }

    public private(set) var phase: Phase = .choosing
    /// The version of the record the user is looking at; a change returns to `.changedAgain`.
    public private(set) var shownRevision: String?
    public private(set) var version: ConflictVersion?
    public private(set) var choices: [String: DependentChoice]
    public private(set) var approvedRetries: Set<String> = []
    public private(set) var discardConfirmed = false
    public let dependentIDs: [String]

    /// Every later action starts as Keep for later, the safe choice.
    public init(dependentIDs: [String], shownRevision: String?) {
        self.dependentIDs = dependentIDs
        self.shownRevision = shownRevision
        self.choices = Dictionary(uniqueKeysWithValues: dependentIDs.map { ($0, .keepForLater) })
    }

    public var discardedIDs: [String] { dependentIDs.filter { choices[$0] == .discard } }
    public var retryIDs: [String] { dependentIDs.filter { choices[$0] == .reviewAndRetry } }

    /// The text of the named discard confirmation, or nil when nothing is selected to discard.
    public var discardPrompt: String? {
        let count = discardedIDs.count
        guard count > 0 else { return nil }
        return "Discard these \(count == 1 ? "1 saved action" : "\(count) saved actions")?"
    }

    public static let discardExplanation = "They will not be sent. Other saved actions will be kept."
    public var discardConfirmTitle: String {
        let count = discardedIDs.count
        return "Discard \(count == 1 ? "1 action" : "\(count) actions")"
    }

    public func choice(for id: String) -> DependentChoice { choices[id] ?? .keepForLater }

    /// Apply is possible only once a version is chosen, every retry is approved against the shown
    /// version, and any discard was confirmed by name.
    public var canApply: Bool {
        guard phase == .choosing || phase == .confirmingDiscard, version != nil else { return false }
        guard Set(retryIDs).isSubset(of: approvedRetries) else { return false }
        return discardedIDs.isEmpty || discardConfirmed
    }

    /// Choosing the account's version drops the user's edit, so later actions that build on it need
    /// an explicit decision; this says whether the dependent section must be answered.
    public var needsDependentDecision: Bool { !dependentIDs.isEmpty }

    public mutating func choose(_ version: ConflictVersion) {
        guard phase != .saving else { return }
        self.version = version
        if phase == .changedAgain { phase = .choosing }
    }

    public mutating func setChoice(_ choice: DependentChoice, for id: String) {
        guard phase != .saving, choices[id] != nil else { return }
        choices[id] = choice
        if choice != .reviewAndRetry { approvedRetries.remove(id) }
        discardConfirmed = false
        if phase == .confirmingDiscard { phase = .choosing }
    }

    public mutating func approveRetry(for id: String) {
        guard phase != .saving, choices[id] == .reviewAndRetry else { return }
        approvedRetries.insert(id)
    }

    /// Opens the named confirmation (M-02.12). No effect without something selected to discard.
    public mutating func requestDiscard() {
        guard phase == .choosing, !discardedIDs.isEmpty else { return }
        phase = .confirmingDiscard
    }

    public mutating func confirmDiscard() {
        guard phase == .confirmingDiscard else { return }
        discardConfirmed = true
        phase = .choosing
    }

    /// Cancel returns to the opener with the draft and every selection intact.
    public mutating func cancelDiscard() {
        if phase == .confirmingDiscard { phase = .choosing }
        discardConfirmed = false
    }

    /// The account side changed after the card opened (M-02.08): the draft is kept, but the version
    /// choice, retry approvals and discard confirmation are cleared so the user applies again.
    public mutating func refresh(currentRevision: String?) {
        guard currentRevision != shownRevision else { return }
        shownRevision = currentRevision
        version = nil
        approvedRetries = []
        discardConfirmed = false
        phase = .changedAgain
    }

    /// The decision to store, or nil unless `canApply`. Moves to `.saving`; a second call is a no-op,
    /// so a resubmission cannot create a second resolution.
    public mutating func apply() -> ConflictDecision? {
        guard canApply, let version else { return nil }
        phase = .saving
        return ConflictDecision(
            version: version, againstRevision: shownRevision, keepForLater: dependentIDs.filter { choices[$0] == .keepForLater },
            retry: retryIDs, discard: discardedIDs)
    }

    /// The write failed locally: keep everything and let the user try again (M-02.05).
    public mutating func saveFailed() {
        if phase == .saving { phase = .choosing }
    }

    public var title: String {
        switch phase {
        case .saving: "Saving your choice…"
        case .changedAgain: "This task changed again. Review both versions."
        case .choosing, .confirmingDiscard: dependentIDs.isEmpty ? "Choose a version" : "\(RuntimeIssuePresenter.laterActions(dependentIDs.count)) need your decision"
        }
    }
}

/// What the user decided; durable once stored, and always against `againstRevision`.
public struct ConflictDecision: Equatable, Sendable {
    public let version: ConflictVersion
    public let againstRevision: String?
    public let keepForLater: [String]
    public let retry: [String]
    public let discard: [String]
}

// MARK: - M-01 / M-03 status

/// Where the user is sent from the status.
public enum RuntimeSyncAction: Equatable, Sendable {
    case none, signInAgain, retry, openIssues, openRecovery, updateApp
}

public struct RuntimeSyncStatus: Equatable, Sendable {
    public enum Distinction: Equatable, Sendable {
        case localOnly, savedLocally, pending, synced, signInNeeded, updateNeeded, hasIssues, failing
    }

    public let distinction: Distinction
    public let headline: String
    /// "Your changes are saved on this device." where that is the truthful reading.
    public let detail: String?
    public let action: RuntimeSyncAction
    public let needsAttention: Bool
    /// Why Sync now is off, when it is.
    public let syncNowDisabledReason: String?
    /// The reference ID, only for a failure that has one.
    public let referenceID: String?
    public let accessibilityLabel: String
}

public enum RuntimeSyncStatusPresenter {
    /// Priority (design M-01): update needed, session ended, issues, persistent failure, offline,
    /// waiting, synced. Reuses `SyncStatusDescriber` for the quiet texts and timings of spec 021.
    public static func describe(
        _ snapshot: SyncSnapshot, updateNeeded: Bool = false, now: Date, device: DeviceKind,
        calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> RuntimeSyncStatus {
        let base = SyncStatusDescriber.describe(snapshot, now: now, device: device, calendar: calendar)
        let saved = "Your changes are saved on this device."
        var distinction = RuntimeSyncStatus.Distinction.synced
        var headline = base.text, detail: String?, action = RuntimeSyncAction.none, attention = base.tone == .attention
        var disabled: String?
        if updateNeeded {
            (distinction, headline, attention, action) = (.updateNeeded, "Update needed to sync", true, .updateApp)
            detail = "Your saved tasks and waiting changes stay on this device."
            disabled = "Update the app to sync again."
        } else {
            switch base.state {
            case .accountLess:
                distinction = .localOnly
                action = .none
            case .sessionEnded:
                distinction = .signInNeeded
                action = .signInAgain
                detail = "Your waiting changes stay with this account. \(saved)"
                disabled = "Sign in again to sync."
            case .rejected:
                distinction = .hasIssues
                action = .openIssues
                detail = "Other changes synced. This change is saved here."
            case .failing:
                distinction = .failing
                action = .retry
                detail = saved
            case .offline:
                distinction = .savedLocally
                detail = saved
                disabled = "Connect to sync."
            case .notSyncedYet:
                distinction = snapshot.pendingCount > 0 ? .pending : .synced
            case .synced:
                distinction = snapshot.pendingCount > 0 ? .pending : .synced
            }
        }
        let reference = distinction == .failing ? snapshot.lastFailureReferenceID : nil
        let label = [headline, detail, reference.map { "Reference ID: \($0)" }].compactMap { $0 }.joined(separator: ". ")
        return RuntimeSyncStatus(
            distinction: distinction, headline: headline, detail: detail, action: action, needsAttention: attention,
            syncNowDisabledReason: disabled, referenceID: reference, accessibilityLabel: "Sync status: \(label)")
    }
}
