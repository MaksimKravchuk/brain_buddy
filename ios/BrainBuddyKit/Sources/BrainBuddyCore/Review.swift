import Foundation

// The weekly review's records on the device (spec 020, data-model E2 – E8 and
// E10). `ReviewState` lives in `GTDState.review`: pulled from
// `GET /review/state` when signed in (plus what acknowledged commands
// returned), the only copy without an account. `LocalReviewState` is device
// state that never syncs (`StoreDocument.local`).

// MARK: - Codes

/// Review steps (data-model E3), in the full review's order.
public enum ReviewStep: String, Hashable, Sendable, Codable, CaseIterable, CodingKeyRepresentable {
    case wins
    case mindSweep = "mind_sweep"
    case inbox, decisions
    case restOfNext = "rest_of_next"
    case waiting, projects, someday, dates, summary
}

/// FR-028: quick = wins, Inbox, decisions, summary; full = all ten steps.
public enum ReviewMode: String, Hashable, Sendable, Codable, CaseIterable {
    case quick, full

    public var steps: [ReviewStep] {
        switch self {
        case .quick: [.wins, .inbox, .decisions, .summary]
        case .full: ReviewStep.allCases
        }
    }
}

public enum ReviewEntry: String, Hashable, Sendable, Codable, CaseIterable {
    case list, notification
    case widgetDecisions = "widget_decisions"
    case sidebar, restart
}

public enum ReviewOrigin: String, Hashable, Sendable, Codable, CaseIterable {
    case ios, web, macos
}

public enum ReviewSessionStatus: String, Hashable, Sendable, Codable, CaseIterable {
    case open, completed
    case completedEmpty = "completed_empty"
    case partial, abandoned

    /// Counted reviews: completed, partial, and an open one once it qualifies (FR-029).
    public func isCounted(qualifyingActivity: Bool) -> Bool {
        switch self {
        case .completed, .partial: true
        case .open: qualifyingActivity
        case .completedEmpty, .abandoned: false
        }
    }

    /// How a session ends (FR-029): Done on the summary → completed or
    /// completed_empty; replaced or idle-closed → partial or abandoned.
    public static func ended(by end: SessionEnd, qualifyingActivity: Bool) -> ReviewSessionStatus {
        switch end {
        case .finish: qualifyingActivity ? .completed : .completedEmpty
        case .replace, .idleClose: qualifyingActivity ? .partial : .abandoned
        }
    }
}

public enum SessionEnd: String, Hashable, Sendable, CaseIterable {
    case finish, replace
    case idleClose = "idle_close"
}

/// Step statuses merge monotonically: finished > skipped > pending.
public enum StepStatus: String, Hashable, Sendable, Codable, CaseIterable {
    case pending, finished, skipped

    var rank: Int {
        switch self {
        case .pending: 0
        case .skipped: 1
        case .finished: 2
        }
    }

    public func merged(with other: StepStatus) -> StepStatus { other.rank > rank ? other : self }
}

public enum ClearStart: String, Hashable, Sendable, Codable, CaseIterable {
    case yes
    case notReally = "not_really"
}

/// FR-007: a code, never free text.
public enum StallReason: String, Hashable, Sendable, Codable, CaseIterable {
    case unclear
    case tooBig = "too_big"
    case missingInfo = "missing_info"
    case waitingOnSomeone = "waiting_on_someone"
    case noEnergy = "no_energy"
    case noLongerMatters = "no_longer_matters"
}

/// FR-026; `notUsed` = proposals shown, own text saved.
public enum AIUse: String, Hashable, Sendable, Codable, CaseIterable {
    case none
    case asIs = "as_is"
    case edited
    case notUsed = "not_used"
}

/// The ten FR-033 summary counters, in the summary's fixed order.
public enum SessionCounter: String, Hashable, Sendable, Codable, CaseIterable, CodingKeyRepresentable {
    case done, reformulated
    case firstStep = "first_step"
    case waiting, someday, cancelled, extended
    case inboxProcessed = "inbox_processed"
    case kept
    case movedToNext = "moved_to_next"
}

extension DecisionType {
    /// The counter a decision increments (`review_counts_as`, data-model E4).
    public var countsAs: SessionCounter {
        switch self {
        case .complete: .done
        case .reformulate: .reformulated
        case .firstStep: .firstStep
        case .waiting: .waiting
        case .someday: .someday
        case .cancel: .cancelled
        case .extend: .extended
        case .keepWaiting, .keepSomeday: .kept
        case .followUp, .returnToNext: .movedToNext
        }
    }
}

/// The ten counters of a session.
public struct SessionCounts: Hashable, Sendable, Codable {
    public var values: [SessionCounter: Int]

    public init(_ values: [SessionCounter: Int] = [:]) { self.values = values.filter { $0.value != 0 } }

    public subscript(counter: SessionCounter) -> Int {
        get { values[counter] ?? 0 }
        set { values[counter] = newValue == 0 ? nil : newValue }
    }

    public var total: Int { values.values.reduce(0, +) }

    /// A counter this build does not know is dropped, not fatal.
    public init(from decoder: Decoder) throws {
        let raw = try decoder.singleValueContainer().decode([String: Int].self)
        var values: [SessionCounter: Int] = [:]
        for (name, count) in raw { if let counter = SessionCounter(rawValue: name) { values[counter] = count } }
        self.init(values)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(values)
    }
}

// MARK: - Settings (E2)

public struct ReviewSettings: Hashable, Sendable, Codable {
    public static let defaultThreshold = 14

    public var thresholdDays: Int
    /// ISO weekday, Monday = 1.
    public var reviewWeekday: Int
    /// `HH:MM` local wall time.
    public var reviewTime: String
    /// The IANA zone classification uses (signed in: the stored one).
    public var timeZone: String
    public var onboardedAt: Date?
    /// FR-016 / FR-051: nil until the explainer was acknowledged.
    public var activatedAt: Date?
    public var ownerParkFloorAt: Date?
    public var thresholdChangedAt: Date?
    /// The server's settings revision; nil until pulled.
    public var revision: Int?

    public init(
        thresholdDays: Int = ReviewSettings.defaultThreshold, reviewWeekday: Int = 5, reviewTime: String = "16:00",
        timeZone: String = "UTC", onboardedAt: Date? = nil, activatedAt: Date? = nil, ownerParkFloorAt: Date? = nil,
        thresholdChangedAt: Date? = nil, revision: Int? = nil
    ) {
        self.thresholdDays = thresholdDays
        self.reviewWeekday = reviewWeekday
        self.reviewTime = reviewTime
        self.timeZone = timeZone
        self.onboardedAt = onboardedAt
        self.activatedAt = activatedAt
        self.ownerParkFloorAt = ownerParkFloorAt
        self.thresholdChangedAt = thresholdChangedAt
        self.revision = revision
    }

    /// The rule's owner inputs; `timeZone` overrides the stored zone.
    public func clockSettings(timeZone override: String? = nil) -> OwnerClockSettings {
        OwnerClockSettings(
            thresholdDays: thresholdDays, timeZoneIdentifier: override ?? timeZone, ownerParkFloorAt: ownerParkFloorAt,
            activatedAt: activatedAt
        )
    }

    /// The grace date of FR-016: `activated_at + 14 d`.
    public var graceUntil: Date? { activatedAt?.addingTimeInterval(FormulationRule.activationGrace) }

    /// Server settings as the device keeps them (FR-039, M-01): the wire
    /// carries no `threshold_changed_at`, so the instant of this device's own
    /// threshold change, which keys the dismissible "threshold just changed"
    /// note and its dismissal, is kept while the server's threshold is the one
    /// `held` (what the device shows, queued changes included) has. A
    /// threshold this device did not set takes the server's value.
    public func keepingThresholdChange(of held: ReviewSettings) -> ReviewSettings {
        var merged = self
        if merged.thresholdChangedAt == nil, held.thresholdDays == thresholdDays {
            merged.thresholdChangedAt = held.thresholdChangedAt
        }
        return merged
    }

    enum CodingKeys: String, CodingKey {
        case thresholdDays, reviewWeekday, reviewTime, timeZone, onboardedAt, activatedAt, ownerParkFloorAt
        case thresholdChangedAt, revision
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let defaults = ReviewSettings()
        thresholdDays = try values.decodeIfPresent(Int.self, forKey: .thresholdDays) ?? defaults.thresholdDays
        reviewWeekday = try values.decodeIfPresent(Int.self, forKey: .reviewWeekday) ?? defaults.reviewWeekday
        reviewTime = try values.decodeIfPresent(String.self, forKey: .reviewTime) ?? defaults.reviewTime
        timeZone = try values.decodeIfPresent(String.self, forKey: .timeZone) ?? defaults.timeZone
        onboardedAt = try values.decodeIfPresent(Date.self, forKey: .onboardedAt)
        activatedAt = try values.decodeIfPresent(Date.self, forKey: .activatedAt)
        ownerParkFloorAt = try values.decodeIfPresent(Date.self, forKey: .ownerParkFloorAt)
        thresholdChangedAt = try values.decodeIfPresent(Date.self, forKey: .thresholdChangedAt)
        revision = try values.decodeIfPresent(Int.self, forKey: .revision)
    }
}

// MARK: - Sessions (E3)

public struct ReviewSession: Identifiable, Hashable, Sendable, Codable {
    public var id: ReviewSessionID
    public var mode: ReviewMode
    public var entry: ReviewEntry
    public var origin: ReviewOrigin
    public var status: ReviewSessionStatus
    public var startedAt: Date
    public var lastActivityAt: Date
    public var endedAt: Date?
    public var currentStep: ReviewStep?
    public var steps: [ReviewStep: StepStatus]
    public var activeSecondsByStep: [ReviewStep: Int]
    public var counts: SessionCounts
    public var setAsideTaskIDs: [TaskID]
    public var setAsideCount: Int
    public var qualifyingActivity: Bool
    public var clearStart: ClearStart?
    /// The `asks_for_decision` snapshot taken when the decision step first opened.
    public var decisionQueue: [TaskID]?
    /// Progress ids already merged (replay protection, http §6).
    public var appliedProgress: Set<ProgressID>
    /// The server's revision; informative only.
    public var revision: Int?
    /// Another device finished or replaced this review ("review ended elsewhere").
    public var endedElsewhere: Bool
    /// The merged current step moved past this device's ("review moved on elsewhere").
    public var movedOnElsewhere: Bool

    public init(
        id: ReviewSessionID, mode: ReviewMode, entry: ReviewEntry, origin: ReviewOrigin, status: ReviewSessionStatus = .open,
        startedAt: Date, lastActivityAt: Date? = nil, endedAt: Date? = nil, currentStep: ReviewStep? = nil,
        steps: [ReviewStep: StepStatus] = [:], activeSecondsByStep: [ReviewStep: Int] = [:],
        counts: SessionCounts = SessionCounts(), setAsideTaskIDs: [TaskID] = [], setAsideCount: Int = 0,
        qualifyingActivity: Bool = false, clearStart: ClearStart? = nil, decisionQueue: [TaskID]? = nil,
        appliedProgress: Set<ProgressID> = [], revision: Int? = nil, endedElsewhere: Bool = false,
        movedOnElsewhere: Bool = false
    ) {
        self.id = id
        self.mode = mode
        self.entry = entry
        self.origin = origin
        self.status = status
        self.startedAt = startedAt
        self.lastActivityAt = lastActivityAt ?? startedAt
        self.endedAt = endedAt
        self.currentStep = currentStep
        self.steps = steps
        self.activeSecondsByStep = activeSecondsByStep
        self.counts = counts
        self.setAsideTaskIDs = setAsideTaskIDs
        self.setAsideCount = setAsideCount
        self.qualifyingActivity = qualifyingActivity
        self.clearStart = clearStart
        self.decisionQueue = decisionQueue
        self.appliedProgress = appliedProgress
        self.revision = revision
        self.endedElsewhere = endedElsewhere
        self.movedOnElsewhere = movedOnElsewhere
    }

    public var isCounted: Bool { status.isCounted(qualifyingActivity: qualifyingActivity) }

    /// Decisions made in the run: the summary's counts without Inbox processed.
    public var decisionCount: Int { counts.total - counts[.inboxProcessed] }

    /// Closed by the 7-day idle rule (FR-029), as `ReviewSessionUpkeep.closeIdle` ends it.
    public var closedForIdleness: Bool {
        (status == .partial || status == .abandoned) && endedAt == lastActivityAt.addingTimeInterval(Self.idleCloseAfter)
    }

    /// The regularity instant this session contributes, if counted (data-model E3).
    public var countedAt: Date? {
        guard isCounted else { return nil }
        if status == .completed, let endedAt { return endedAt }
        return lastActivityAt
    }

    /// FR-029: an open session idle for 7 days is closed by the sweep.
    public static let idleCloseAfter: TimeInterval = 7 * FormulationRule.day

    public static func isIdleCloseDue(lastActivityAt: Date, now: Date) -> Bool {
        now.timeIntervalSince(lastActivityAt) >= idleCloseAfter
    }

    /// FR-029: at least one item decision, or a non-summary step finished
    /// (not skipped) with nothing to decide.
    public static func qualifies(itemDecisions: Int, finishedEmptySteps: Set<ReviewStep>) -> Bool {
        itemDecisions > 0 || finishedEmptySteps.contains { $0 != .summary }
    }

    /// The latest counted-review instant of `sessions` (data-model E3).
    public static func lastCountedReviewAt(_ sessions: some Sequence<ReviewSession>) -> Date? {
        sessions.compactMap(\.countedAt).max()
    }
}

// MARK: - Decisions (E4) and receipts (E5)

/// What the task looked like right after a change, to tell later whether it
/// changed since: the device's last write instant and the server's revision.
public struct TaskStamp: Hashable, Sendable, Codable {
    /// Nil when only the server's revision is known (an acknowledged release).
    public var updatedAt: Date?
    public var serverRevision: Int?

    public init(updatedAt: Date?, serverRevision: Int?) {
        self.updatedAt = updatedAt
        self.serverRevision = serverRevision
    }

    public init(_ task: TaskRecord) { self.init(updatedAt: task.updatedAt, serverRevision: task.serverRevision) }

    public func matches(_ task: TaskRecord?) -> Bool {
        guard let task else { return false }
        return (updatedAt == nil || task.updatedAt == updatedAt) && task.serverRevision == serverRevision
    }
}

/// FR-011: the task as a decision card or form showed it. A person's
/// decision on a task that changed since is stale: the task itself or its
/// children. The task is compared by what a person sees (`visible`): its
/// revision, write instants and other server-set fields are left out, so an
/// acknowledgement of an edit that was queued before the card opened is not a
/// change. Child edits leave the parent untouched, on the device
/// (`Reducer+Children`) and on the server (a
/// subtask or comment has its own revision), so the children are compared
/// by what a person sees: ids, subtask title, state and order, comment body.
/// Server ids, revisions, authors and server-set times are left out, so an
/// acknowledgement that changes nothing visible is not a change. Before the
/// task's detail was read (a pulled task, `childrenSyncedAt == nil`) the
/// device may hold only some children: then the children the card showed
/// must be unchanged (present, same title, state and relative order, same
/// comment body), and children it did not show (the ones hydration fills in)
/// are not a change. Every child edit made on this device since the card
/// opened is a change whatever its acknowledgement state: the device's
/// child-edit count (`GTDState.localChildEdits`) must be what the card saw.
/// A child another device created before this one hydrated the task cannot
/// be told from one that already existed. Never encoded or stored.
public struct ShownTask: Hashable, Sendable {
    /// The task as a person sees it (`visible`).
    public var content: TaskRecord
    /// The device held every child when the card opened: the task's detail
    /// was read (`childrenSyncedAt`), or the server has not seen the task
    /// yet, so all of its children are on the device.
    public var childrenKnown: Bool
    public var subtasks: [SubtaskRecord]
    public var comments: [CommentRecord]
    /// This device's child edits on the task when the card opened
    /// (`GTDState.localChildEdits`).
    public var localChildEdits: Int
    /// Content-free proof from the original canonical read; local prepared gesture only.
    public var runtimeAdmissionToken: Data?

    public init(_ task: TaskRecord, localChildEdits: Int = 0) {
        self.localChildEdits = localChildEdits
        runtimeAdmissionToken = nil
        content = Self.visible(task)
        childrenKnown = task.serverID == nil || task.childrenSyncedAt != nil
        subtasks = Self.visible(task.subtasks)
        comments = Self.visible(task.comments)
    }

    /// `localChildEdits`: this device's child edits on the task now, nil when
    /// not tracked.
    public func matches(_ task: TaskRecord?, localChildEdits current: Int?) -> Bool {
        if let current, current != localChildEdits { return false }
        return matches(task)
    }

    public func matches(_ task: TaskRecord?) -> Bool {
        guard let task, content == Self.visible(task) else { return false }
        let currentSubtasks = Self.visible(task.subtasks)
        let currentComments = Self.visible(task.comments)
        if childrenKnown { return currentSubtasks == subtasks && currentComments == comments }
        // Before full hydration: every child the card did show must still be
        // there as shown (a missing one was deleted elsewhere: hydration
        // drops a cached child only when the server no longer lists it).
        // Children it did not show are what hydration or a sync brought in;
        // this device's own child edits are caught by the child-edit count.
        let byID = Dictionary(currentSubtasks.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        for shown in subtasks {
            guard let current = byID[shown.id], current.title == shown.title, current.state == shown.state else {
                return false
            }
        }
        let shownOrder = subtasks.sorted { ($0.orderKey, $0.id.rawValue) < ($1.orderKey, $1.id.rawValue) }.map(\.id)
        let currentOrder = subtasks.compactMap { byID[$0.id] }
            .sorted { ($0.orderKey, $0.id.rawValue) < ($1.orderKey, $1.id.rawValue) }.map(\.id)
        guard shownOrder == currentOrder else { return false }
        let commentsByID = Dictionary(currentComments.map { ($0.id, $0.body) }, uniquingKeysWith: { first, _ in first })
        return comments.allSatisfy { commentsByID[$0.id] == $0.body }
    }

    /// The task without its ids, revision, server-set instants and order key,
    /// and without the children (compared on their own).
    static func visible(_ task: TaskRecord) -> TaskRecord {
        var visible = task
        visible.serverID = nil
        visible.serverRevision = nil
        visible.waitingSince = nil
        visible.completedAt = nil
        visible.cancelledAt = nil
        visible.orderKey = 0
        visible.createdAt = .distantPast
        visible.updatedAt = .distantPast
        visible.subtasks = []
        visible.comments = []
        visible.childrenSyncedAt = nil
        return visible
    }

    static func visible(_ subtasks: [SubtaskRecord]) -> [SubtaskRecord] {
        subtasks.map { subtask in
            var visible = subtask
            visible.serverID = nil
            visible.serverRevision = nil
            return visible
        }
        .sorted { $0.id.rawValue < $1.id.rawValue }
    }

    static func visible(_ comments: [CommentRecord]) -> [CommentRecord] {
        comments.map { comment in
            var visible = comment
            visible.serverID = nil
            visible.serverRevision = nil
            visible.authorID = nil
            // The server sets these on acknowledgement; an edit changes the body.
            visible.createdAt = .distantPast
            visible.editedAt = nil
            return visible
        }
        .sorted { $0.id.rawValue < $1.id.rawValue }
    }
}

/// Content-bearing: nulled 7 days after the decision (R15).
public struct DecisionUndo: Hashable, Sendable, Codable {
    public var taskBefore: TaskRecord
    public var createdTaskID: TaskID?
    public var createdTaskAfter: TaskStamp?
    /// The receipt the decision wrote, and the one it replaced.
    public var receiptWritten: ReceiptKind?
    public var receiptReplaced: ReviewReceipt?
    /// The run as the decision found it, so an Undo right after it takes the
    /// decision's qualifying activity back too (as compaction's cancel does).
    public var sessionBefore: SessionBefore?

    public struct SessionBefore: Hashable, Sendable, Codable {
        public var qualifyingActivity: Bool
        public var lastActivityAt: Date
        /// The run's `lastActivityAt` right after the decision.
        public var lastActivityAfter: Date

        public init(qualifyingActivity: Bool, lastActivityAt: Date, lastActivityAfter: Date) {
            self.qualifyingActivity = qualifyingActivity
            self.lastActivityAt = lastActivityAt
            self.lastActivityAfter = lastActivityAfter
        }
    }

    public init(
        taskBefore: TaskRecord, createdTaskID: TaskID? = nil, createdTaskAfter: TaskStamp? = nil,
        receiptWritten: ReceiptKind? = nil, receiptReplaced: ReviewReceipt? = nil, sessionBefore: SessionBefore? = nil
    ) {
        self.taskBefore = taskBefore
        self.createdTaskID = createdTaskID
        self.createdTaskAfter = createdTaskAfter
        self.receiptWritten = receiptWritten
        self.receiptReplaced = receiptReplaced
        self.sessionBefore = sessionBefore
    }
}

public struct ReviewDecision: Identifiable, Hashable, Sendable, Codable {
    public var id: DecisionID
    public var taskID: TaskID
    public var type: DecisionType
    public var sessionID: ReviewSessionID?
    public var decidedAt: Date
    public var formulationID: FormulationID?
    public var stallReason: StallReason?
    /// For `reformulate`: false when only a cosmetic edit was saved.
    public var substantive: Bool?
    public var aiUse: AIUse
    /// Only for `extend`: the reason, kept as decision history (FR-043).
    public var reasonText: String?
    public var undo: DecisionUndo?
    /// The decided task right after the decision; Undo needs it unchanged.
    public var taskAfter: TaskStamp
    public var yieldedAutoPark: Bool
    /// The Undo snapshot is the server's, not this device's: the decision is
    /// known only from the server's answer (the replay could not record it),
    /// or retention dropped the local snapshot while an Undo still names it.
    /// A queued Undo is then left for the server to answer instead of being
    /// refused here.
    public var snapshotOnServer: Bool

    public init(
        id: DecisionID, taskID: TaskID, type: DecisionType, sessionID: ReviewSessionID? = nil, decidedAt: Date,
        formulationID: FormulationID? = nil, stallReason: StallReason? = nil, substantive: Bool? = nil,
        aiUse: AIUse = .none, reasonText: String? = nil, undo: DecisionUndo? = nil, taskAfter: TaskStamp,
        yieldedAutoPark: Bool = false, snapshotOnServer: Bool = false
    ) {
        self.snapshotOnServer = snapshotOnServer
        self.id = id
        self.taskID = taskID
        self.type = type
        self.sessionID = sessionID
        self.decidedAt = decidedAt
        self.formulationID = formulationID
        self.stallReason = stallReason
        self.substantive = substantive
        self.aiUse = aiUse
        self.reasonText = reasonText
        self.undo = undo
        self.taskAfter = taskAfter
        self.yieldedAutoPark = yieldedAutoPark
    }

    enum CodingKeys: String, CodingKey {
        case id, taskID, type, sessionID, decidedAt, formulationID, stallReason, substantive, aiUse, reasonText, undo
        case taskAfter, yieldedAutoPark, snapshotOnServer
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(DecisionID.self, forKey: .id)
        taskID = try values.decode(TaskID.self, forKey: .taskID)
        type = try values.decode(DecisionType.self, forKey: .type)
        sessionID = try values.decodeIfPresent(ReviewSessionID.self, forKey: .sessionID)
        decidedAt = try values.decode(Date.self, forKey: .decidedAt)
        formulationID = try values.decodeIfPresent(FormulationID.self, forKey: .formulationID)
        stallReason = try values.decodeIfPresent(StallReason.self, forKey: .stallReason)
        substantive = try values.decodeIfPresent(Bool.self, forKey: .substantive)
        aiUse = try values.decodeIfPresent(AIUse.self, forKey: .aiUse) ?? AIUse.none
        reasonText = try values.decodeIfPresent(String.self, forKey: .reasonText)
        undo = try values.decodeIfPresent(DecisionUndo.self, forKey: .undo)
        taskAfter = try values.decode(TaskStamp.self, forKey: .taskAfter)
        yieldedAutoPark = try values.decodeIfPresent(Bool.self, forKey: .yieldedAutoPark) ?? false
        snapshotOnServer = try values.decodeIfPresent(Bool.self, forKey: .snapshotOnServer) ?? false
    }
}

public enum ReceiptKind: String, Hashable, Sendable, Codable, CaseIterable {
    case waiting, someday

    /// FR-032: Waiting checks in again after 7 days, Someday after 30.
    public var hiddenFor: TimeInterval {
        switch self {
        case .waiting: 7 * FormulationRule.day
        case .someday: 30 * FormulationRule.day
        }
    }
}

public enum ReceiptSource: String, Hashable, Sendable, Codable, CaseIterable {
    /// Keep waiting / keep in Someday.
    case keep
    /// A person's own release to Someday (decision, restart, Inbox remainder).
    case release
}

/// One current receipt per task and kind (data-model E5).
public struct ReviewReceipt: Hashable, Sendable, Codable {
    public var taskID: TaskID
    public var kind: ReceiptKind
    public var reviewedAt: Date
    public var hiddenUntil: Date
    public var source: ReceiptSource
    /// The task as the receipt saw it: hidden only while it is unchanged.
    public var taskRevision: Int?
    public var taskUpdatedAt: Date?
    public var decisionID: DecisionID?
    public var bulkID: BulkID?

    public init(
        taskID: TaskID, kind: ReceiptKind, reviewedAt: Date, hiddenUntil: Date, source: ReceiptSource,
        taskRevision: Int? = nil, taskUpdatedAt: Date? = nil, decisionID: DecisionID? = nil, bulkID: BulkID? = nil
    ) {
        self.taskID = taskID
        self.kind = kind
        self.reviewedAt = reviewedAt
        self.hiddenUntil = hiddenUntil
        self.source = source
        self.taskRevision = taskRevision
        self.taskUpdatedAt = taskUpdatedAt
        self.decisionID = decisionID
        self.bulkID = bulkID
    }

    /// Hidden while not expired and the task is unchanged since.
    public func hides(_ task: TaskRecord, now: Date) -> Bool {
        guard now < hiddenUntil else { return false }
        if let taskRevision, taskRevision != task.serverRevision { return false }
        if let taskUpdatedAt, taskUpdatedAt != task.updatedAt { return false }
        return true
    }
}

/// A park the person has seen on "While you were away" (data-model E6). It
/// names the park instant too: a repeat park of the same formulation (after
/// an Undo, T-046) is a new park, unseen again.
public struct ParkAck: Hashable, Sendable, Codable {
    public var taskID: TaskID
    public var formulationID: FormulationID
    public var parkedAt: Date?

    public init(taskID: TaskID, formulationID: FormulationID, parkedAt: Date? = nil) {
        self.taskID = taskID
        self.formulationID = formulationID
        self.parkedAt = parkedAt
    }

    /// Whether this acknowledgement covers `marker` on `task`.
    public func covers(_ task: TaskID, _ marker: ParkMarker) -> Bool {
        taskID == task && formulationID == marker.formulationID && (parkedAt == nil || parkedAt == marker.at)
    }
}

// MARK: - Bulk releases (E7)

public enum BulkReleaseKindCode: String, Hashable, Sendable, Codable, CaseIterable {
    case restart
    case inboxRemainder = "inbox_remainder"
}

public struct BulkReleasedTask: Hashable, Sendable, Codable {
    public var taskID: TaskID
    public var previousState: OpenList
    /// Next tasks only; nulled 7 days after the release (R15).
    public var clockBefore: ReleasedClock?
    public var taskAfter: TaskStamp
    /// False when the release is known only from the server's answer (the
    /// device's replay found the task already released): the server keeps
    /// the clock, and an Undo is left to it.
    public var clockKnown: Bool
    /// The Someday receipt the release replaced; its Undo puts it back.
    public var receiptReplaced: ReviewReceipt?

    public init(
        taskID: TaskID, previousState: OpenList, clockBefore: ReleasedClock?, taskAfter: TaskStamp, clockKnown: Bool = true,
        receiptReplaced: ReviewReceipt? = nil
    ) {
        self.taskID = taskID
        self.previousState = previousState
        self.clockBefore = clockBefore
        self.taskAfter = taskAfter
        self.clockKnown = clockKnown
        self.receiptReplaced = receiptReplaced
    }

    enum CodingKeys: String, CodingKey {
        case taskID, previousState, clockBefore, taskAfter, clockKnown, receiptReplaced
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        taskID = try values.decode(TaskID.self, forKey: .taskID)
        previousState = try values.decode(OpenList.self, forKey: .previousState)
        clockBefore = try values.decodeIfPresent(ReleasedClock.self, forKey: .clockBefore)
        taskAfter = try values.decode(TaskStamp.self, forKey: .taskAfter)
        clockKnown = try values.decodeIfPresent(Bool.self, forKey: .clockKnown) ?? true
        receiptReplaced = try values.decodeIfPresent(ReviewReceipt.self, forKey: .receiptReplaced)
    }
}

/// The most items one request takes (http §5, §6).
public enum ReviewLimits {
    public static let bulkReleaseItems = 500
    public static let parkAcknowledgements = 200
}

public struct BulkSkippedTask: Hashable, Sendable, Codable {
    public var taskID: TaskID
    /// `stale` or `not_eligible`.
    public var reason: String

    public init(taskID: TaskID, reason: String) {
        self.taskID = taskID
        self.reason = reason
    }
}

public struct BulkUndoResult: Hashable, Sendable, Codable {
    public var restored: [TaskID]
    public var skipped: [TaskID]

    public init(restored: [TaskID], skipped: [TaskID]) {
        self.restored = restored
        self.skipped = skipped
    }
}

public struct BulkReleaseRecord: Identifiable, Hashable, Sendable, Codable {
    public var id: BulkID
    public var kind: BulkReleaseKindCode
    public var sessionID: ReviewSessionID?
    public var createdAt: Date
    public var released: [BulkReleasedTask]
    public var skipped: [BulkSkippedTask]
    public var undoneAt: Date?
    public var undoResult: BulkUndoResult?

    public init(
        id: BulkID, kind: BulkReleaseKindCode, sessionID: ReviewSessionID?, createdAt: Date,
        released: [BulkReleasedTask], skipped: [BulkSkippedTask], undoneAt: Date? = nil, undoResult: BulkUndoResult? = nil
    ) {
        self.id = id
        self.kind = kind
        self.sessionID = sessionID
        self.createdAt = createdAt
        self.released = released
        self.skipped = skipped
        self.undoneAt = undoneAt
        self.undoResult = undoResult
    }
}

// MARK: - Navigator consent (E8)

public struct NavigatorConsent: Hashable, Sendable, Codable {
    public var provider: String
    public var grantedAt: Date?
    public var revokedAt: Date?
    public var consentTextVersion: Int?

    public init(provider: String, grantedAt: Date? = nil, revokedAt: Date? = nil, consentTextVersion: Int? = nil) {
        self.provider = provider
        self.grantedAt = grantedAt
        self.revokedAt = revokedAt
        self.consentTextVersion = consentTextVersion
    }

    /// A grant that was not revoked. A revoke on this device counts at once,
    /// offline (FR-024).
    public var allowsCloud: Bool { grantedAt != nil && revokedAt == nil }
}

// MARK: - What the server said (GET /review/state)

/// The last counted review's summary (http §5 `last_counted_review`).
public struct LastCountedReview: Hashable, Sendable, Codable {
    public var sessionID: ReviewSessionID
    public var status: ReviewSessionStatus
    public var origin: ReviewOrigin
    public var endedAt: Date?
    public var counts: SessionCounts
    public var clearStart: ClearStart?

    public init(
        sessionID: ReviewSessionID, status: ReviewSessionStatus, origin: ReviewOrigin, endedAt: Date?,
        counts: SessionCounts, clearStart: ClearStart?
    ) {
        self.sessionID = sessionID
        self.status = status
        self.origin = origin
        self.endedAt = endedAt
        self.counts = counts
        self.clearStart = clearStart
    }
}

public struct ReviewServerFacts: Hashable, Sendable, Codable {
    /// The `weekly_review` flag is effective for the account (a gated read
    /// answered); false after `404 weekly_review_disabled`.
    public var exposed: Bool
    public var lastCountedReviewAt: Date?
    public var lastCountedReview: LastCountedReview?
    public var nextReviewAt: Date?
    public var restartMode: Bool
    public var openSessionID: ReviewSessionID?
    public var pulledAt: Date?

    public init(
        exposed: Bool, lastCountedReviewAt: Date? = nil, lastCountedReview: LastCountedReview? = nil,
        nextReviewAt: Date? = nil, restartMode: Bool = false, openSessionID: ReviewSessionID? = nil, pulledAt: Date? = nil
    ) {
        self.exposed = exposed
        self.lastCountedReviewAt = lastCountedReviewAt
        self.lastCountedReview = lastCountedReview
        self.nextReviewAt = nextReviewAt
        self.restartMode = restartMode
        self.openSessionID = openSessionID
        self.pulledAt = pulledAt
    }
}

// MARK: - ReviewState

/// `GTDState.review` (contracts/ios-commands.md §1).
public struct ReviewState: Hashable, Sendable, Codable {
    public var settings: ReviewSettings
    public var sessions: [ReviewSessionID: ReviewSession]
    public var decisions: [DecisionID: ReviewDecision]
    public var receipts: [ReviewReceipt]
    /// Parks seen on "While you were away".
    public var parkAcks: [ParkAck]
    public var bulkReleases: [BulkID: BulkReleaseRecord]
    /// Per provider.
    public var navigatorConsents: [String: NavigatorConsent]
    /// Set once `GET /review/state` was read: the server keeps the clocks, so
    /// a Next task it holds without one stays unclassified until it repairs it.
    public var server: ReviewServerFacts?
    /// Account-less only: the build's weekly-review release switch
    /// (`BBWeeklyReviewLocal`, ADR-0027), set by the workspace on every state
    /// it builds; nil when signed in, where `server.exposed` (pulled,
    /// persisted in the base, merged by every pull) decides. A device input,
    /// never encoded: the build, not the store, decides it.
    public var accountlessReleaseSwitch: Bool? = nil

    /// Whether the weekly review is exposed on this device: signed in, the
    /// account's `weekly_review` flag as the last gated read answered;
    /// account-less, the release switch. While it is not, the reducer refuses
    /// a person's review actions (`GTDReducer`, `.reviewUnavailable`).
    public var isExposed: Bool { accountlessReleaseSwitch ?? (server?.exposed == true) }

    public init(
        settings: ReviewSettings = ReviewSettings(), sessions: [ReviewSessionID: ReviewSession] = [:],
        decisions: [DecisionID: ReviewDecision] = [:], receipts: [ReviewReceipt] = [], parkAcks: [ParkAck] = [],
        bulkReleases: [BulkID: BulkReleaseRecord] = [:], navigatorConsents: [String: NavigatorConsent] = [:],
        server: ReviewServerFacts? = nil
    ) {
        self.settings = settings
        self.sessions = sessions
        self.decisions = decisions
        self.receipts = receipts
        self.parkAcks = parkAcks
        self.bulkReleases = bulkReleases
        self.navigatorConsents = navigatorConsents
        self.server = server
    }

    public static let empty = ReviewState()

    public func receipt(for task: TaskID, kind: ReceiptKind) -> ReviewReceipt? {
        receipts.first { $0.taskID == task && $0.kind == kind }
    }

    public mutating func setReceipt(_ receipt: ReviewReceipt) {
        receipts.removeAll { $0.taskID == receipt.taskID && $0.kind == receipt.kind }
        receipts.append(receipt)
    }

    public mutating func removeReceipt(for task: TaskID, kind: ReceiptKind) {
        receipts.removeAll { $0.taskID == task && $0.kind == kind }
    }

    /// Whether the park `marker` on `task` was seen.
    public func hasSeen(_ task: TaskID, _ marker: ParkMarker) -> Bool {
        parkAcks.contains { $0.covers(task, marker) }
    }

    /// The open session, if any (at most one is open per owner).
    public var openSession: ReviewSession? {
        sessions.values.filter { $0.status == .open }.max { ($0.startedAt, $0.id) < ($1.startedAt, $1.id) }
    }

    enum CodingKeys: String, CodingKey {
        case settings, sessions, decisions, receipts, parkAcks, bulkReleases, navigatorConsents, server
    }

    /// Every member is optional on disk, so `{}` (the v1 → v2 migration) decodes.
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        settings = try values.decodeIfPresent(ReviewSettings.self, forKey: .settings) ?? ReviewSettings()
        sessions = try values.decodeIfPresent([ReviewSessionID: ReviewSession].self, forKey: .sessions) ?? [:]
        decisions = try values.decodeIfPresent([DecisionID: ReviewDecision].self, forKey: .decisions) ?? [:]
        receipts = try values.decodeIfPresent([ReviewReceipt].self, forKey: .receipts) ?? []
        parkAcks = try values.decodeIfPresent([ParkAck].self, forKey: .parkAcks) ?? []
        bulkReleases = try values.decodeIfPresent([BulkID: BulkReleaseRecord].self, forKey: .bulkReleases) ?? [:]
        navigatorConsents = try values.decodeIfPresent([String: NavigatorConsent].self, forKey: .navigatorConsents) ?? [:]
        server = try values.decodeIfPresent(ReviewServerFacts.self, forKey: .server)
    }
}

// MARK: - Device-local state (E10)

/// Unsaved form text (FR-052): form kind + task id + formulation id, or
/// session id + step item, or project id. Never sent, never in an outbox
/// operation, never logged.
public struct DraftKey: Hashable, Sendable, Codable, CodingKeyRepresentable, CustomStringConvertible {
    public let rawValue: String

    public init(rawValue: String) { self.rawValue = rawValue }

    public enum FormKind: String, Hashable, Sendable, CaseIterable {
        case reformulate
        case firstStep = "first_step"
        case waitingFor = "waiting_for"
        case extensionReason = "extension_reason"
        case followUp = "follow_up"
        case returnToNext = "return_to_next"
    }

    /// A decision form on one formulation of one task.
    public static func decisionForm(_ kind: FormKind, task: TaskID, formulation: FormulationID?) -> DraftKey {
        DraftKey(rawValue: "form:\(kind.rawValue):\(task.rawValue):\(formulation?.rawValue ?? "-")")
    }

    /// A field of a review step (session id + step item).
    public static func reviewStep(session: ReviewSessionID, step: ReviewStep, item: String) -> DraftKey {
        DraftKey(rawValue: "step:\(session.rawValue):\(step.rawValue):\(item)")
    }

    /// The first next action typed for a project without one (M-08, M-19).
    public static func projectNextAction(_ project: ProjectID) -> DraftKey {
        DraftKey(rawValue: "project:\(project.rawValue)")
    }

    /// The task a decision-form draft belongs to, if it is one.
    public var taskID: TaskID? {
        let parts = rawValue.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 4, parts[0] == "form" else { return nil }
        return TaskID(String(parts[2]))
    }

    /// The formulation a decision-form draft was typed for.
    public var formulationID: FormulationID? {
        let parts = rawValue.split(separator: ":", omittingEmptySubsequences: false)
        guard parts.count == 4, parts[0] == "form", parts[3] != "-" else { return nil }
        return FormulationID(String(parts[3]))
    }

    public var description: String { rawValue }

    public init(from decoder: Decoder) throws { rawValue = try decoder.singleValueContainer().decode(String.self) }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }

    public var codingKey: CodingKey { AnyCodingKey(rawValue) }
    public init?<T: CodingKey>(codingKey: T) { rawValue = codingKey.stringValue }
}

public struct FormDraft: Hashable, Sendable, Codable {
    public var text: String
    public var savedAt: Date

    public init(text: String, savedAt: Date) {
        self.text = text
        self.savedAt = savedAt
    }
}

/// When this device first saw a task one day from its park, so a park
/// always follows at least 24 hours of "Moves to Someday tomorrow" (SC-006).
public struct ParkWarning: Hashable, Sendable, Codable {
    public var formulationID: FormulationID
    public var since: Date

    public init(formulationID: FormulationID, since: Date) {
        self.formulationID = formulationID
        self.since = since
    }
}

/// `StoreDocument.local` (data-model E10): never synced, removed with the
/// store on sign-out.
public struct LocalReviewState: Hashable, Sendable, Codable {
    /// Account-less FR-016 / FR-051 anchor: when the explainer was first
    /// dismissed on this device.
    public var activatedAt: Date?
    /// Signed in: suppresses the explainer until the pulled `activated_at` arrives.
    public var explainerSeenLocally: Bool
    /// The R9 loop guard: a park issued for a formulation is never issued again.
    public var issuedAutoParks: [TaskID: FormulationID]
    public var formDrafts: [DraftKey: FormDraft]
    /// The local day "While you were away" was last shown at app open (FR-015).
    public var wywaLastShownDay: CalendarDay?
    /// The last observed `server_now − device time` (signed in only).
    public var serverClockOffset: TimeInterval?
    /// The IANA zone this device last observed (a zone change is sent only
    /// when the device's own zone changed).
    public var lastObservedTimeZone: String?
    /// Tasks whose unsent "Keep 7 more days" was dropped at account linking.
    public var linkedExtensionNotices: [TaskID]
    public var lastNotificationScheduledAt: Date?
    public var parkWarnings: [TaskID: ParkWarning]
    /// More due parks wait until "While you were away" for the applied ones
    /// was continued or closed (the device safety valve).
    public var parkBatchWaiting: Bool
    /// Account-less: sessions this device closed after 7 idle days (FR-029),
    /// applied after every replay by `ReviewSessionUpkeep.closeIdle`.
    public var idleClosedSessions: [ReviewSessionID]

    public init(
        activatedAt: Date? = nil, explainerSeenLocally: Bool = false, issuedAutoParks: [TaskID: FormulationID] = [:],
        formDrafts: [DraftKey: FormDraft] = [:], wywaLastShownDay: CalendarDay? = nil, serverClockOffset: TimeInterval? = nil,
        lastObservedTimeZone: String? = nil, linkedExtensionNotices: [TaskID] = [], lastNotificationScheduledAt: Date? = nil,
        parkWarnings: [TaskID: ParkWarning] = [:], parkBatchWaiting: Bool = false, idleClosedSessions: [ReviewSessionID] = []
    ) {
        self.idleClosedSessions = idleClosedSessions
        self.activatedAt = activatedAt
        self.explainerSeenLocally = explainerSeenLocally
        self.issuedAutoParks = issuedAutoParks
        self.formDrafts = formDrafts
        self.wywaLastShownDay = wywaLastShownDay
        self.serverClockOffset = serverClockOffset
        self.lastObservedTimeZone = lastObservedTimeZone
        self.linkedExtensionNotices = linkedExtensionNotices
        self.lastNotificationScheduledAt = lastNotificationScheduledAt
        self.parkWarnings = parkWarnings
        self.parkBatchWaiting = parkBatchWaiting
    }

    public static let empty = LocalReviewState()

    enum CodingKeys: String, CodingKey {
        case activatedAt, explainerSeenLocally, issuedAutoParks, formDrafts, wywaLastShownDay, serverClockOffset
        case lastObservedTimeZone, linkedExtensionNotices, lastNotificationScheduledAt, parkWarnings, parkBatchWaiting
        case idleClosedSessions
    }

    /// Every member is decoded with `decodeIfPresent`, so `{}` decodes.
    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        activatedAt = try values.decodeIfPresent(Date.self, forKey: .activatedAt)
        explainerSeenLocally = try values.decodeIfPresent(Bool.self, forKey: .explainerSeenLocally) ?? false
        issuedAutoParks = try values.decodeIfPresent([TaskID: FormulationID].self, forKey: .issuedAutoParks) ?? [:]
        formDrafts = try values.decodeIfPresent([DraftKey: FormDraft].self, forKey: .formDrafts) ?? [:]
        wywaLastShownDay = try values.decodeIfPresent(CalendarDay.self, forKey: .wywaLastShownDay)
        serverClockOffset = try values.decodeIfPresent(TimeInterval.self, forKey: .serverClockOffset)
        lastObservedTimeZone = try values.decodeIfPresent(String.self, forKey: .lastObservedTimeZone)
        linkedExtensionNotices = try values.decodeIfPresent([TaskID].self, forKey: .linkedExtensionNotices) ?? []
        lastNotificationScheduledAt = try values.decodeIfPresent(Date.self, forKey: .lastNotificationScheduledAt)
        parkWarnings = try values.decodeIfPresent([TaskID: ParkWarning].self, forKey: .parkWarnings) ?? [:]
        parkBatchWaiting = try values.decodeIfPresent(Bool.self, forKey: .parkBatchWaiting) ?? false
        idleClosedSessions = try values.decodeIfPresent([ReviewSessionID].self, forKey: .idleClosedSessions) ?? []
    }
}

/// The device copy's retention (data-model "Device-local retention", R15,
/// contracts/ios-commands.md §5), signed in or not: content-bearing Undo and
/// bulk-release clock snapshots are nulled 7 days after they were taken, and
/// an ended run keeps no progress ids. Signed in, the server holds the
/// history, so the device also drops decisions and bulk releases once their
/// Undo is gone and ended runs after 35 days (`lastCountedReview` comes from
/// the server then). A decision a queued Undo names is kept instead, without
/// its snapshot and marked `snapshotOnServer` (a signed-in base holds only
/// acknowledged decisions), so the server answers that Undo (200, or 409
/// `undo_unavailable` with its Ref) rather than the replay taking it as done.
/// In the outbox, an unsent decision or release keeps asking for its snapshot
/// while a queued Undo names it (`expiringSnapshot(of:now:undos:)`).
/// Account-less, the store is the only copy: nothing but the snapshots is dropped.
public enum ReviewRetention {
    public static let snapshotWindow: TimeInterval = 7 * FormulationRule.day
    public static let endedRunWindow: TimeInterval = 35 * FormulationRule.day

    /// Whether `apply` would change `review`.
    public static func isDue(
        _ review: ReviewState, now: Date, signedIn: Bool, keeping referenced: Set<DecisionID> = []
    ) -> Bool {
        var copy = review
        apply(to: &copy, now: now, signedIn: signedIn, keeping: referenced)
        return copy != review
    }

    public static func apply(
        to review: inout ReviewState, now: Date, signedIn: Bool, keeping referenced: Set<DecisionID> = []
    ) {
        let cutoff = now.addingTimeInterval(-snapshotWindow)
        for (id, decision) in review.decisions where decision.decidedAt <= cutoff {
            if signedIn, !referenced.contains(id) {
                review.decisions[id] = nil
                continue
            }
            if decision.undo != nil { review.decisions[id]?.undo = nil }
            if signedIn { review.decisions[id]?.snapshotOnServer = true }
        }
        for (id, record) in review.bulkReleases where record.createdAt <= cutoff {
            if signedIn {
                review.bulkReleases[id] = nil
            } else if record.released.contains(where: { $0.clockBefore != nil }) {
                review.bulkReleases[id]?.released = record.released.map { item in
                    var item = item
                    item.clockBefore = nil
                    return item
                }
            }
        }
        let runCutoff = now.addingTimeInterval(-endedRunWindow)
        for (id, session) in review.sessions where session.status != .open {
            if signedIn, (session.endedAt ?? session.lastActivityAt) <= runCutoff {
                review.sessions[id] = nil
            } else if !session.appliedProgress.isEmpty {
                review.sessions[id]?.appliedProgress = []
            }
        }
    }

    /// The decisions and bulk releases a queued Undo names.
    public struct QueuedUndos: Hashable, Sendable {
        public var decisions: Set<DecisionID> = []
        public var bulkReleases: Set<BulkID> = []

        public init(_ operations: [PendingOperation]) {
            for operation in operations {
                switch operation.command {
                case .undoDecision(let id): decisions.insert(id)
                case .undoBulkRelease(let id): bulkReleases.insert(id)
                default: break
                }
            }
        }
    }

    /// `operation` once its 7-day snapshot window has passed at `now`: an
    /// unsent decision or bulk release stops asking the reducer for its Undo
    /// snapshot. Not while a queued Undo names it: that Undo was taken inside
    /// the window and needs the snapshot to replay, and dropping the pair
    /// instead would change the run and the operations compaction kept
    /// because they depend on the decision. The undone replay holds no
    /// decision snapshot, and signed in the pair leaves the outbox together.
    /// Nil when nothing changes; sent operations are never modified.
    public static func expiringSnapshot(
        of operation: PendingOperation, now: Date, undos: QueuedUndos
    ) -> PendingOperation? {
        guard !operation.hasBeenSent, operation.issuedAt <= now.addingTimeInterval(-snapshotWindow) else { return nil }
        var expired = operation
        switch operation.command {
        case .decideTask(var decide) where decide.undoRetained && !undos.decisions.contains(decide.decisionID):
            decide.undoRetained = false
            expired.command = .decideTask(decide)
        case .bulkRelease(var release) where release.undoRetained && !undos.bulkReleases.contains(release.bulkID):
            release.undoRetained = false
            expired.command = .bulkRelease(release)
        default:
            return nil
        }
        return expired
    }
}

/// Account-less session upkeep (FR-029); signed in, the server's sweep closes
/// idle sessions and the device reads the result.
public enum ReviewSessionUpkeep {
    /// The open sessions idle for 7 days at `now`.
    public static func idleSessions(in state: GTDState, now: Date) -> [ReviewSessionID] {
        state.review.sessions.values
            .filter { $0.status == .open && ReviewSession.isIdleCloseDue(lastActivityAt: $0.lastActivityAt, now: now) }
            .map(\.id).sorted()
    }

    /// Closes the listed sessions that are still open: partial when they
    /// qualified, abandoned otherwise, ended 7 days after their last activity.
    public static func closeIdle(_ ids: [ReviewSessionID], in state: inout GTDState) {
        for id in ids {
            guard var session = state.review.sessions[id], session.status == .open else { continue }
            session.status = .ended(by: .idleClose, qualifyingActivity: session.qualifyingActivity)
            session.endedAt = session.lastActivityAt.addingTimeInterval(ReviewSession.idleCloseAfter)
            state.review.sessions[id] = session
        }
    }

    /// The recorded idle closes a state built with `closeIdle` still needs,
    /// read from that state alone (no replay): a run showing exactly the end
    /// `closeIdle` writes is still open underneath (or was ended the same way,
    /// where keeping the record changes nothing). A run finished, replaced,
    /// ended elsewhere or no longer held drops out.
    public static func recordedIdleCloses(_ ids: [ReviewSessionID], in state: GTDState) -> [ReviewSessionID] {
        ids.filter { id in
            guard let session = state.review.sessions[id], !session.endedElsewhere else { return false }
            return session.status == .ended(by: .idleClose, qualifyingActivity: session.qualifyingActivity)
                && session.endedAt == session.lastActivityAt.addingTimeInterval(ReviewSession.idleCloseAfter)
        }
    }
}
