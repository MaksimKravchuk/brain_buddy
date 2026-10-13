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
public enum ConflictVersion: String, Codable, Equatable, Sendable { case saved, account }

/// What to do with one later action.
public enum DependentChoice: String, Codable, Equatable, Sendable { case keepForLater, reviewAndRetry, discard }

/// The user's unsent decision for one conflict (M-02.01, .08, .11, .12; Mac D-02). Holding a draft
/// never submits anything: relaunch restores it, and only `apply` (after `canApply`) produces a
/// decision. The iPhone detail and the Mac popover both run on this one value.
///
/// Only the choices are persisted (`Codable`): never the phase, a discard confirmation or any of the
/// user's text, so a restored draft cannot submit and cannot arrive with a discard already confirmed.
public struct ConflictDecisionDraft: Equatable, Sendable, Codable {
    public enum Phase: Equatable, Sendable {
        case choosing, confirmingDiscard, saving, saveFailed, changedAgain
    }

    public private(set) var phase: Phase = .choosing
    /// The version of the record the user is looking at; a change returns to `.changedAgain`.
    public private(set) var shownRevision: String?
    public private(set) var version: ConflictVersion?
    public private(set) var choices: [String: DependentChoice]
    public private(set) var approvedRetries: Set<String> = []
    public private(set) var discardConfirmed = false
    public let dependentIDs: [String]
    /// The issue the draft belongs to, where the caller keeps drafts for several.
    public let issueID: String?
    /// False where there is no version to pick (the item was deleted elsewhere): the only way to
    /// resolve it is to keep it deleted.
    public private(set) var requiresVersion = true
    /// For each later action the runtime could queue again, the other held actions it waits on.
    /// An action absent from the map cannot be retried. `nil` leaves retry unrestricted. The runtime
    /// refuses a replacement that waits on a held action which is not itself queued again, so such a
    /// retry is never offered.
    public private(set) var retryDependencies: [String: [String]]?
    /// For a later action on another record than the issue's own, the revision of that record the
    /// retry preview shows: the precondition its new command is approved against. Not persisted.
    public private(set) var dependentRevisions: [String: String] = [:]

    private enum CodingKeys: String, CodingKey {
        case shownRevision, version, choices, approvedRetries, dependentIDs, issueID
    }

    /// Every later action starts as Keep for later, the safe choice.
    public init(
        dependentIDs: [String], shownRevision: String?, issueID: String? = nil, requiresVersion: Bool = true,
        retryDependencies: [String: [String]]? = nil, dependentRevisions: [String: String] = [:]
    ) {
        self.dependentRevisions = dependentRevisions
        self.dependentIDs = dependentIDs
        self.shownRevision = shownRevision
        self.issueID = issueID
        self.requiresVersion = requiresVersion
        self.retryDependencies = retryDependencies
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

    /// Nothing chosen yet: there is nothing to keep across a relaunch.
    public var isUntouched: Bool { version == nil && choices.values.allSatisfy { $0 == .keepForLater } }

    /// Whether "Review and retry" may be offered for `id` now: it is a known saved action, and every
    /// earlier held action it waits on is itself being retried.
    public func canRetry(_ id: String) -> Bool {
        guard let rules = retryDependencies else { return true }
        guard let waitsOn = rules[id] else { return false }
        let held = Set(dependentIDs)
        return waitsOn.allSatisfy { $0 == id || !held.contains($0) || choices[$0] == .reviewAndRetry }
    }

    /// Why "Review and retry" is not available for `id`, or nil when it is.
    public func retryUnavailableReason(for id: String) -> String? {
        guard !canRetry(id) else { return nil }
        return retryDependencies?[id] == nil
            ? "This action can't be retried from here. Keep it for later."
            : "It waits on an earlier saved action. Retry that one first, or keep this for later."
    }

    /// Apply is possible only once a version is chosen, every retry is approved against the shown
    /// version, and any discard was confirmed by name.
    public var canApply: Bool { readyToApply && (discardedIDs.isEmpty || discardConfirmed) }

    /// Everything `canApply` needs except the named discard confirmation, which the Mac asks for as
    /// its Apply step.
    public var readyToApply: Bool {
        guard phase != .saving else { return false }
        if requiresVersion, version == nil { return false }
        return Set(retryIDs).isSubset(of: approvedRetries) && retryIDs.allSatisfy(canRetry)
    }

    /// Choosing the account's version drops the user's edit, so later actions that build on it need
    /// an explicit decision; this says whether the dependent section must be answered.
    public var needsDependentDecision: Bool { !dependentIDs.isEmpty }

    public mutating func choose(_ version: ConflictVersion) {
        guard phase != .saving else { return }
        self.version = version
        if phase == .changedAgain || phase == .saveFailed { phase = .choosing }
    }

    public mutating func setChoice(_ choice: DependentChoice, for id: String) {
        guard phase != .saving, choices[id] != nil else { return }
        if choice == .reviewAndRetry, !canRetry(id) { return }
        choices[id] = choice
        if choice != .reviewAndRetry { approvedRetries.remove(id) }
        normalizeRetries()
        discardConfirmed = false
        if phase == .confirmingDiscard { phase = .choosing }
    }

    /// A retry whose predecessor is no longer retried would be refused by the runtime: it goes back
    /// to Keep for later, and its approval with it.
    private mutating func normalizeRetries() {
        var changed = true
        while changed {
            changed = false
            for id in retryIDs where !canRetry(id) {
                choices[id] = .keepForLater
                approvedRetries.remove(id)
                changed = true
            }
        }
    }

    public mutating func approveRetry(for id: String) {
        guard phase != .saving, choices[id] == .reviewAndRetry else { return }
        approvedRetries.insert(id)
    }

    /// Switching the approval off withdraws it, and `canApply` follows.
    public mutating func withdrawRetryApproval(for id: String) {
        guard phase != .saving else { return }
        approvedRetries.remove(id)
    }

    /// Opens the named confirmation (M-02.12). No effect without something selected to discard.
    public mutating func requestDiscard() {
        guard phase != .saving, phase != .confirmingDiscard, !discardedIDs.isEmpty else { return }
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
    /// choice (unless `keepingVersion`), retry approvals and discard confirmation are cleared so the
    /// user applies again.
    public mutating func refresh(currentRevision: String?, keepingVersion: Bool = false) {
        guard currentRevision != shownRevision else { return }
        markChangedAgain(revision: currentRevision, keepingVersion: keepingVersion)
    }

    /// The same, where the account's record is known to have moved even if its revision reads alike.
    public mutating func markChangedAgain(revision: String?, keepingVersion: Bool = false) {
        shownRevision = revision
        if !keepingVersion { version = nil }
        approvedRetries = []
        discardConfirmed = false
        phase = .changedAgain
    }

    /// The decision to store, or nil unless `canApply`. Moves to `.saving`; a second call is a no-op,
    /// so a resubmission cannot create a second resolution.
    public mutating func apply() -> ConflictDecision? {
        guard canApply else { return nil }
        phase = .saving
        return ConflictDecision(
            version: version, againstRevision: shownRevision,
            keepForLater: dependentIDs.filter { choices[$0] == .keepForLater }, retry: retryIDs,
            retryRevisions: dependentRevisions.filter { retryIDs.contains($0.key) }, discard: discardedIDs)
    }

    /// The write failed locally: keep everything and let the user try again (M-02.05).
    public mutating func saveFailed() {
        if phase == .saving { phase = .saveFailed }
    }

    /// Takes in what became of the decision `apply` produced. A stored (or already gone) resolution
    /// leaves nothing to keep: the caller drops the draft. A record that changed again keeps the draft
    /// and asks for a new decision; any other refusal keeps it and offers a retry.
    public mutating func finish(_ outcome: RuntimeIssueApplyOutcome, keepingVersion: Bool = false) {
        guard phase == .saving else { return }
        switch outcome {
        case .resolved, .gone: break
        case .changedAgain(let current): markChangedAgain(revision: current?.revision, keepingVersion: keepingVersion)
        case .failed: phase = .saveFailed
        }
    }

    /// Relaunch: puts back what `saved` held, for the actions this issue still has. Nothing is
    /// submitted and no discard arrives confirmed. A draft saved against another revision of the
    /// record returns as "changed again", with its choices but no version or approval.
    public mutating func restore(from saved: ConflictDecisionDraft) {
        guard saved.issueID == issueID else { return }
        version = saved.version
        approvedRetries = []
        for id in dependentIDs { choices[id] = saved.choices[id] ?? .keepForLater }
        normalizeRetries()
        approvedRetries = Set(retryIDs.filter { saved.approvedRetries.contains($0) })
        discardConfirmed = false
        phase = .choosing
        if saved.shownRevision != shownRevision { markChangedAgain(revision: shownRevision) }
    }

    public var title: String {
        switch phase {
        case .saving: "Saving your choice…"
        case .saveFailed: "Your choice wasn't saved. Try again."
        case .changedAgain: "This task changed again. Review both versions."
        case .choosing, .confirmingDiscard:
            dependentIDs.isEmpty
                ? "Choose a version" : "\(RuntimeIssuePresenter.laterActions(dependentIDs.count)) need your decision"
        }
    }
}

/// What the user decided; durable once stored, and always against `againstRevision`.
public struct ConflictDecision: Equatable, Sendable {
    /// Nil where the item was deleted elsewhere and the only choice is to keep it deleted.
    public let version: ConflictVersion?
    public let againstRevision: String?
    public let keepForLater: [String]
    public let retry: [String]
    /// The displayed revision of each retried action on another record (see `dependentRevisions`).
    public let retryRevisions: [String: String]
    public let discard: [String]

    public init(
        version: ConflictVersion?, againstRevision: String?, keepForLater: [String], retry: [String],
        retryRevisions: [String: String] = [:], discard: [String]
    ) {
        self.version = version
        self.againstRevision = againstRevision
        self.keepForLater = keepForLater
        self.retry = retry
        self.retryRevisions = retryRevisions
        self.discard = discard
    }
}

extension RetryDependent {
    /// The retry list of a resolution: the one place the draft's retried ids and the revisions their
    /// previews showed become `RetryDependent`s.
    public static func list(ids: [String], revisions: [String: String]) -> [RetryDependent] {
        ids.map { RetryDependent(id: $0, shownRevision: revisions[$0]) }
    }
}

extension RuntimeIssueResolution {
    /// The draft's decision as the runtime takes it: the saved version is `.keepMine`, the account's
    /// is `.useAccountVersion`, and no version (deleted elsewhere) is `.keepDeleted`. Every held
    /// action is in exactly one of keepForLater, retry and discard.
    public init(issueID: String, decision: ConflictDecision) {
        let outcome: Outcome
        switch decision.version {
        case .saved?: outcome = .keepMine
        case .account?: outcome = .useAccountVersion
        case nil: outcome = .keepDeleted
        }
        self.init(
            issueID: issueID, outcome: outcome, shownRevision: decision.againstRevision,
            keepForLater: decision.keepForLater,
            retry: RetryDependent.list(ids: decision.retry, revisions: decision.retryRevisions), discard: decision.discard)
    }
}

extension RuntimeIssuePresenter {
    /// A fresh draft for `issue`: Keep for later for every held action, retry offered only for an
    /// action that is itself a known saved issue and whose held predecessors can be retried too.
    ///
    /// The draft is decided against the revision of the account's record the person is shown
    /// (`account.revision`), so a record that moves afterwards is caught as "changed again". Without
    /// the account's record it falls back to the revision the user edited.
    public static func draft(
        for issue: RustWorkspaceIssue, among all: [RustWorkspaceIssue], account: RuntimeIssueAccountVersion? = nil
    ) -> ConflictDecisionDraft {
        var rules: [String: [String]] = [:]
        var revisions: [String: String] = [:]
        let target = issue.targetEntity
        for id in issue.dependentIDs {
            guard let known = all.first(where: { $0.commandID == id || $0.id == id }) else { continue }
            rules[id] = known.waitsOn
            if let shown = known.shownBaseRevision, known.targetEntity != target { revisions[id] = shown }
        }
        return ConflictDecisionDraft(
            dependentIDs: issue.dependentIDs, shownRevision: account.map(\.revision) ?? issue.shownBaseRevision,
            issueID: issue.id, requiresVersion: RuntimeIssueKind(reason: issue.reason) != .deletedElsewhere, retryDependencies: rules,
            dependentRevisions: revisions)
    }
}

extension RustWorkspaceIssue {
    /// The record this issue's own command edits.
    public var targetEntity: String? {
        (try? JSONSerialization.jsonObject(with: localIntent) as? [String: Any])?["entity_id"] as? String
    }

    /// The commands this issue's own command waits on (`depends_on` of its saved intent).
    public var waitsOn: [String] {
        guard let intent = try? JSONSerialization.jsonObject(with: localIntent) as? [String: Any] else { return [] }
        return intent["depends_on"] as? [String] ?? []
    }
}

// MARK: - M-01 / M-03 status

/// Where the user is sent from the status.
public enum RuntimeSyncAction: Equatable, Sendable {
    case none, signInAgain, retry, openIssues, openRecovery, updateApp
}

public struct RuntimeSyncStatus: Equatable, Sendable {
    public enum Distinction: Equatable, Sendable {
        case localOnly, savedLocally, pending, notSyncedYet, synced, signInNeeded, updateNeeded, hasIssues, failing
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

/// The runtime's transport is failing (not offline, not signed out). The reference ID is opaque.
public struct TransportFailure: Equatable, Sendable {
    public let referenceID: String?
    public init(referenceID: String?) { self.referenceID = referenceID }
}

public enum RuntimeSyncStatusPresenter {
    /// Priority (design M-01): update needed, session ended, issues, persistent failure, offline,
    /// waiting, synced. Reuses `SyncStatusDescriber` for the quiet texts and timings of spec 021.
    public static func describe(
        _ input: SyncSnapshot, updateNeeded: Bool = false, transportFailure: TransportFailure? = nil,
        now: Date, device: DeviceKind, calendar: Calendar = Calendar(identifier: .gregorian)
    ) -> RuntimeSyncStatus {
        var snapshot = input
        // A transport failure the runtime reports now is persistent by the time it is reported: it
        // is given the timing of the legacy engine's failure, so it surfaces as "Couldn't sync".
        if let transportFailure, snapshot.failingSince == nil {
            snapshot.failingSince = now.addingTimeInterval(-SyncTiming.failureSurfacesAfter - 1)
            snapshot.lastFailedAttemptAt = now
            snapshot.lastFailureReferenceID = transportFailure.referenceID
        }
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
                distinction = snapshot.pendingCount > 0 ? .pending : .notSyncedYet
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

// MARK: - M-03 recovery card

/// What the recovery card says and offers for the runtime's recovery state (design M-03; the Mac's
/// D-03 reads the same facts). Waiting changes and saved issues are always named as kept.
public struct RuntimeRecoveryCard: Equatable, Sendable {
    public enum Action: Equatable, Sendable {
        case updateApp, tryAgain
        case copyReference(String)
    }

    public enum Condition: Equatable, Sendable {
        case updateNeededStore, rebuilding, rebuildFailed(referenceID: String?)
    }

    public let condition: Condition
    public let title: String
    public let detail: String
    public let actions: [Action]
    /// Sync is stopped until the person acts.
    public let isBlocking: Bool
    public let accessibilityLabel: String

    public init?(_ recovery: RuntimeSyncRecovery, pendingCount: Int) {
        let condition: Condition, title: String, detail: String, actions: [Action]
        var reference: String?
        if recovery.storeNeedsUpdate {
            condition = .updateNeededStore
            title = "Update needed to open tasks"
            detail = "Nothing is written and nothing syncs until you update."
            actions = [.updateApp, .tryAgain]
        } else if recovery.rebuild == .rebuilding {
            condition = .rebuilding
            title = "Rebuilding synced copy…"
            detail = "\(SyncCopy.changes(pendingCount)) waiting. Your waiting changes and saved conflicts will be kept."
            actions = []
        } else if case .failed(let failedReference) = recovery.rebuild {
            condition = .rebuildFailed(referenceID: failedReference)
            title = "Couldn't rebuild the synced copy."
            detail = "Your waiting changes are saved."
            actions = [.tryAgain] + (failedReference.map { [.copyReference($0)] } ?? [])
            reference = failedReference
        } else {
            return nil
        }
        self.condition = condition
        self.title = title
        self.detail = detail
        self.actions = actions
        isBlocking = condition == .updateNeededStore
        accessibilityLabel = [title, detail, reference.map { "Reference ID: \($0)" }].compactMap { $0 }
            .joined(separator: ". ")
    }
}
