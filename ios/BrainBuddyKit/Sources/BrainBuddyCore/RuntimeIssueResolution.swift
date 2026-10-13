import Foundation

// What a person decided for one shared-runtime sync issue, and what the workspace reports back
// (spec 026 design M-02/D-02, runtime-ffi.md `resolve_issue`). Pure values shared by the iPhone and
// the Mac so both apps submit the same decision; the draft/legality models stay in each app's
// presentation layer and only produce one of these once the person has applied their choice.

/// A decision for one issue and every action held behind it. Executed atomically against
/// `shownRevision`: if the record changed after the person was shown it, nothing is saved.
public struct RuntimeIssueResolution: Equatable, Sendable {
    public enum Outcome: Equatable, Sendable {
        /// Queue the person's saved edit again as a new command, against `shownRevision`.
        case keepMine
        /// Use the account's version; the saved edit stays in the issue for recovery and export.
        case useAccountVersion
        /// The item was deleted elsewhere and stays deleted; it is never recreated.
        case keepDeleted
    }

    public let issueID: String
    public let outcome: Outcome
    /// The edit revision of the account's record the person was looking at; the precondition of a
    /// kept edit. `nil` where the record had none.
    public let shownRevision: String?
    /// Held actions that stay held (and stay issues).
    public let keepForLater: [String]
    /// Held actions the person reviewed and approved to be queued again under new IDs, each with
    /// the revision of its own record that the person was shown when approving it.
    public let retry: [RetryDependent]
    /// Held actions dropped. Include an ID only after the person confirmed the named list.
    public let discard: [String]

    public init(
        issueID: String, outcome: Outcome, shownRevision: String?, keepForLater: [String] = [],
        retry: [RetryDependent] = [], discard: [String] = []
    ) {
        self.issueID = issueID
        self.outcome = outcome
        self.shownRevision = shownRevision
        self.keepForLater = keepForLater
        self.retry = retry
        self.discard = discard
    }
}

/// A held action approved for retry. `shownRevision` is the revision of the record that action
/// edits, as displayed in the retry preview; it is the precondition of the new command when that
/// record is not the issue's own (an action on another entity), so a reviewed retry does not fail
/// against a revision it was never shown. `nil` keeps the action's own precondition.
public struct RetryDependent: Equatable, Sendable {
    public let id: String
    public let shownRevision: String?

    public init(id: String, shownRevision: String? = nil) {
        self.id = id
        self.shownRevision = shownRevision
    }
}

/// A command queued again in place of a rejected or held one.
public struct RuntimeReplacedCommand: Equatable, Sendable {
    public let oldCommandID: String
    public let newCommandID: String
}

/// What a stored resolution did.
public struct RuntimeIssueResolutionResult: Equatable, Sendable {
    public let replaced: [RuntimeReplacedCommand]
    public let discarded: [String]
    public let kept: [String]
    /// This answered a repeat of an already stored resolution; nothing new was written.
    public let repeated: Bool

    public init(replaced: [RuntimeReplacedCommand], discarded: [String], kept: [String], repeated: Bool) {
        self.replaced = replaced
        self.discarded = discarded
        self.kept = kept
        self.repeated = repeated
    }
}

/// Why a resolution was refused. Whatever the case, nothing was saved.
public enum RuntimeIssueResolutionError: Error, Equatable, Sendable {
    /// The account's record changed after it was shown: show both versions again.
    case changedAgain
    /// Another window or device already resolved the issue.
    case alreadyResolved
    /// The issue is gone.
    case unknownIssue
    /// The send may have reached the account; it is reconciled first, never re-sent.
    case notResolvable
    /// A deleted item is never recreated by keeping an edit.
    case itemDeleted
    /// The decision lacks a choice for a held action, or names one that is not held.
    case incompleteDecision
    /// The shared runtime is not running this workspace.
    case notReady
    /// Any other safe code from the runtime.
    case failed(code: String)

    public init(code: String) {
        switch code {
        case "REVISION_CONFLICT": self = .changedAgain
        case "ISSUE_ALREADY_RESOLVED": self = .alreadyResolved
        case "UNKNOWN_ISSUE": self = .unknownIssue
        case "ISSUE_NOT_RESOLVABLE": self = .notResolvable
        case "ENTITY_DELETED": self = .itemDeleted
        case "DEPENDENT_CHOICE_REQUIRED", "UNKNOWN_DEPENDENT", "DISCARD_NOT_CONFIRMED", "INVALID_CHOICE":
            self = .incompleteDecision
        case "WORKSPACE_NOT_READY", "WORKSPACE_CLOSED": self = .notReady
        default: self = .failed(code: code)
        }
    }
}

/// The account's copy of an issue's record, read-only: what the "account version" side of a
/// conflict shows.
public struct RuntimeIssueAccountVersion: Equatable, Sendable {
    /// The revision to quote back as `RuntimeIssueResolution.shownRevision`.
    public let revision: String?
    /// The account deleted the record.
    public let isDeleted: Bool
    /// The account's text for the members the person's saved edit also holds, by member name
    /// (`title`, `details`, …). Empty for a deleted record.
    public let fields: [String: String]

    public init(revision: String?, isDeleted: Bool, fields: [String: String]) {
        self.revision = revision
        self.isDeleted = isDeleted
        self.fields = fields
    }
}

/// Where the device's recovery stands, for the status line and the recovery card (design M-03/D-03).
/// Read-only facts; the wording and legal actions are the presentation layer's.
public struct RuntimeSyncRecovery: Equatable, Sendable {
    public enum Rebuild: Equatable, Sendable {
        case idle
        case rebuilding
        /// The rebuild did not finish; the reference is safe to quote.
        case failed(referenceID: String?)
    }

    /// The device's intake epoch as the store holds it.
    public enum Epoch: String, Equatable, Sendable {
        case none, pendingRegistration = "pending_registration", active, closed
        /// A value this build does not know.
        case unknown
    }

    public enum AccountLink: String, Equatable, Sendable {
        case unchosen, accountLess = "account_less", linking, linked
        case unknown
    }

    public var epoch: Epoch
    public var accountLink: AccountLink
    /// The device's store was written by a newer app: nothing is saved or synced until it updates.
    public var storeNeedsUpdate: Bool
    /// The shared runtime is not running this workspace (it failed to open, or is read-only).
    public var storeUnavailable: Bool
    public var rebuild: Rebuild

    public init(
        epoch: Epoch = .none, accountLink: AccountLink = .unchosen, storeNeedsUpdate: Bool = false,
        storeUnavailable: Bool = false, rebuild: Rebuild = .idle
    ) {
        self.epoch = epoch
        self.accountLink = accountLink
        self.storeNeedsUpdate = storeNeedsUpdate
        self.storeUnavailable = storeUnavailable
        self.rebuild = rebuild
    }

    public init(epochState: String, accountLinkState: String) {
        self.init(
            epoch: Epoch(rawValue: epochState) ?? .unknown,
            accountLink: AccountLink(rawValue: accountLinkState) ?? .unknown)
    }

    /// The server closed the device's epoch: held and uncertain work is reconciled before more is sent.
    public var epochClosed: Bool { epoch == .closed }

    /// Whether any recovery state needs showing.
    public var needsAttention: Bool {
        storeNeedsUpdate || storeUnavailable || rebuild != .idle || epochClosed
    }
}

// MARK: - Planning

/// One new command that takes the place of a rejected or held one.
public struct RustIssueReplacement: Equatable, Sendable {
    public let commandID: String
    /// A JSON `Precondition` array.
    public let preconditions: Data
    public let dependsOn: [String]

    public init(commandID: String, preconditions: Data, dependsOn: [String]) {
        self.commandID = commandID
        self.preconditions = preconditions
        self.dependsOn = dependsOn
    }
}

public enum RustIssueChoice: Equatable, Sendable {
    case useCurrent
    case keepMine(RustIssueReplacement)
}

public enum RustDependentChoice: Equatable, Sendable {
    case keepForLater
    case retry(RustIssueReplacement)
    case discard(confirmed: Bool)
}

/// The runtime's form of a `RuntimeIssueResolution`: new command IDs minted, shown revisions
/// written into the replacements' preconditions.
public struct RustIssueResolveRequest: Equatable, Sendable {
    public let issueID: String
    public let choice: RustIssueChoice
    /// For every action held behind the issue, in queue order.
    public let dependents: [(commandID: String, choice: RustDependentChoice)]

    public init(issueID: String, choice: RustIssueChoice, dependents: [(commandID: String, choice: RustDependentChoice)]) {
        self.issueID = issueID
        self.choice = choice
        self.dependents = dependents
    }

    public static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.issueID == rhs.issueID && lhs.choice == rhs.choice && lhs.dependents.count == rhs.dependents.count
            && zip(lhs.dependents, rhs.dependents).allSatisfy { $0.commandID == $1.commandID && $0.choice == $1.choice }
    }
}

public enum RuntimeIssueResolutionPlanner {
    /// Turns a decision into the runtime request. Every action held behind the issue must have an
    /// explicit choice; nothing is decided by omission.
    ///
    /// A kept edit is queued against `shownRevision`. A retried action keeps its own preconditions,
    /// except where it built on the issue's record: it then follows the kept edit's replacement, or,
    /// when the account's version was chosen, is approved against `shownRevision`. A wait on a
    /// replaced command moves to its replacement, and a wait on the dismissed edit is dropped.
    public static func plan(
        _ resolution: RuntimeIssueResolution, among issues: [RustWorkspaceIssue], makeCommandID: () -> String
    ) throws -> RustIssueResolveRequest {
        guard let issue = issues.first(where: { $0.id == resolution.issueID }) else {
            throw RuntimeIssueResolutionError.unknownIssue
        }
        let held = issue.dependentIDs
        let listed = resolution.keepForLater + resolution.retry.map(\.id) + resolution.discard
        guard Set(listed) == Set(held), listed.count == held.count else {
            throw RuntimeIssueResolutionError.incompleteDecision
        }
        var scope = Scope(
            target: (try intent(of: issue))["entity_id"] as? String, revision: resolution.shownRevision,
            primaryID: issue.commandID)
        let choice: RustIssueChoice
        switch resolution.outcome {
        case .useAccountVersion, .keepDeleted:
            choice = .useCurrent
        case .keepMine:
            let replacement = try replacement(for: issue, primary: true, shownRevision: nil, scope: scope, makeCommandID: makeCommandID)
            scope.replaced[issue.commandID] = replacement.commandID
            choice = .keepMine(replacement)
        }
        var dependents: [(commandID: String, choice: RustDependentChoice)] = []
        for id in held {
            if let retried = resolution.retry.first(where: { $0.id == id }) {
                guard let dependent = issues.first(where: { $0.commandID == id || $0.id == id }) else {
                    throw RuntimeIssueResolutionError.incompleteDecision
                }
                let replacement = try replacement(
                    for: dependent, primary: false, shownRevision: retried.shownRevision, scope: scope,
                    makeCommandID: makeCommandID)
                scope.replaced[dependent.commandID] = replacement.commandID
                dependents.append((id, .retry(replacement)))
            } else if resolution.discard.contains(id) {
                dependents.append((id, .discard(confirmed: true)))
            } else {
                dependents.append((id, .keepForLater))
            }
        }
        return RustIssueResolveRequest(issueID: issue.id, choice: choice, dependents: dependents)
    }

    private struct Scope {
        /// The entity the issue's own command edits.
        let target: String?
        /// The account's revision of it that the person was shown.
        let revision: String?
        let primaryID: String
        var replaced: [String: String] = [:]
    }

    private static func intent(of issue: RustWorkspaceIssue) throws -> [String: Any] {
        guard let intent = try? JSONSerialization.jsonObject(with: issue.localIntent) as? [String: Any] else {
            throw RuntimeIssueResolutionError.failed(code: "MALFORMED_ISSUE")
        }
        return intent
    }

    private static func replacement(
        for issue: RustWorkspaceIssue, primary: Bool, shownRevision: String?, scope: Scope,
        makeCommandID: () -> String
    ) throws -> RustIssueReplacement {
        let intent = try intent(of: issue)
        let newPrimary = scope.replaced[scope.primaryID]
        let preconditions = (intent["preconditions"] as? [[String: Any]] ?? []).map { precondition -> [String: Any] in
            var precondition = precondition
            if var after = precondition["after_command"] as? [String: Any] {
                if let old = after["command_id"] as? String, let new = scope.replaced[old] {
                    after["command_id"] = new
                    precondition["after_command"] = after
                }
            } else if precondition["entity_id"] as? String != scope.target, !primary, let shownRevision,
                precondition["entity_id"] as? String == intent["entity_id"] as? String
            {
                // Another entity: approved against the revision its preview displayed.
                precondition["edit_revision"] = shownRevision
            } else if precondition["entity_id"] as? String == scope.target, let target = scope.target {
                if primary {
                    if let revision = scope.revision { precondition["edit_revision"] = revision }
                } else if let newPrimary {
                    // It built on the edit that is being queued again: it follows the new command.
                    precondition = [
                        "after_command": [
                            "command_id": newPrimary, "entity_type": precondition["entity_type"] ?? "task",
                            "entity_id": target,
                        ]
                    ]
                } else if let revision = scope.revision {
                    precondition["edit_revision"] = revision
                }
            }
            return precondition
        }
        let dependsOn = (intent["depends_on"] as? [String] ?? []).compactMap { id -> String? in
            if let new = scope.replaced[id] { return new }
            return id == scope.primaryID && newPrimary == nil ? nil : id
        }
        guard let data = try? JSONSerialization.data(withJSONObject: preconditions, options: [.sortedKeys]) else {
            throw RuntimeIssueResolutionError.failed(code: "MALFORMED_ISSUE")
        }
        return RustIssueReplacement(commandID: makeCommandID(), preconditions: data, dependsOn: dependsOn)
    }
}

/// The exact requests submitted for issues, kept until the workspace binding ends, so an Apply
/// repeated after a lost or uncertain completion (or a double tap) sends the same new command IDs
/// and the runtime answers it as a repeat instead of a new decision.
public struct RuntimeIssueResolutionLedger: Sendable {
    private var submitted: [String: (resolution: RuntimeIssueResolution, request: RustIssueResolveRequest)] = [:]

    public init() {}

    /// The request for `resolution`: the stored one when the same decision was submitted before,
    /// otherwise a freshly planned one, which is stored before it is sent.
    public mutating func request(
        for resolution: RuntimeIssueResolution, among issues: [RustWorkspaceIssue], makeCommandID: () -> String
    ) throws -> RustIssueResolveRequest {
        if let known = submitted[resolution.issueID], known.resolution == resolution { return known.request }
        let request = try RuntimeIssueResolutionPlanner.plan(resolution, among: issues, makeCommandID: makeCommandID)
        submitted[resolution.issueID] = (resolution, request)
        return request
    }

    /// A refusal that proves nothing was stored drops the request, so the next decision plans anew;
    /// an uncertain failure keeps it for the repeat. Success keeps it too: a repeat answers `repeated`.
    public mutating func settle(issueID: String, error: RuntimeIssueResolutionError?) {
        switch error {
        case .changedAgain, .alreadyResolved, .unknownIssue, .notResolvable, .itemDeleted, .incompleteDecision:
            submitted[issueID] = nil
        case .notReady, .failed, nil: break
        }
    }

    public mutating func removeAll() { submitted = [:] }
}
