import BrainBuddyCore
import Foundation

// The weekly review's wire shapes (spec 020, contracts/http.md §3 – §7), field
// for field with `backend/app/schemas/review.py` and pinned by the golden
// `review_wire_fixtures.json`. Request bodies omit a nil optional field, as
// every other body here does, so each has one canonical encoding.

// MARK: - Requests

/// `POST /tasks/{id}/decisions` (`DecisionRequest`).
public struct DecisionRequestBody: Codable, Hashable, Sendable {
    public var decisionID: String?
    public var type: DecisionType
    public var expectedRevision: Int
    public var formulationID: String?
    public var stallReason: StallReason?
    public var title: String?
    public var waitingFor: String?
    public var reason: String?
    public var sessionID: String?
    public var aiUse: AIUse
    public var navigatorRequestID: String?
    public var clientDecidedAt: Date?
    public var newFormulationID: String?
    public var followUpTaskID: String?

    public init(
        decisionID: String? = nil, type: DecisionType, expectedRevision: Int, formulationID: String? = nil,
        stallReason: StallReason? = nil, title: String? = nil, waitingFor: String? = nil, reason: String? = nil,
        sessionID: String? = nil, aiUse: AIUse = .none, navigatorRequestID: String? = nil, clientDecidedAt: Date? = nil,
        newFormulationID: String? = nil, followUpTaskID: String? = nil
    ) {
        self.decisionID = decisionID
        self.type = type
        self.expectedRevision = expectedRevision
        self.formulationID = formulationID
        self.stallReason = stallReason
        self.title = title
        self.waitingFor = waitingFor
        self.reason = reason
        self.sessionID = sessionID
        self.aiUse = aiUse
        self.navigatorRequestID = navigatorRequestID
        self.clientDecidedAt = clientDecidedAt
        self.newFormulationID = newFormulationID
        self.followUpTaskID = followUpTaskID
    }

    enum CodingKeys: String, CodingKey {
        case type, title, reason
        case decisionID = "decision_id"
        case expectedRevision = "expected_revision"
        case formulationID = "formulation_id"
        case stallReason = "stall_reason"
        case waitingFor = "waiting_for"
        case sessionID = "session_id"
        case aiUse = "ai_use"
        case navigatorRequestID = "navigator_request_id"
        case clientDecidedAt = "client_decided_at"
        case newFormulationID = "new_formulation_id"
        case followUpTaskID = "follow_up_task_id"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        decisionID = try values.decodeIfPresent(String.self, forKey: .decisionID)
        type = try values.decode(DecisionType.self, forKey: .type)
        expectedRevision = try values.decode(Int.self, forKey: .expectedRevision)
        formulationID = try values.decodeIfPresent(String.self, forKey: .formulationID)
        stallReason = try values.decodeIfPresent(StallReason.self, forKey: .stallReason)
        title = try values.decodeIfPresent(String.self, forKey: .title)
        waitingFor = try values.decodeIfPresent(String.self, forKey: .waitingFor)
        reason = try values.decodeIfPresent(String.self, forKey: .reason)
        sessionID = try values.decodeIfPresent(String.self, forKey: .sessionID)
        aiUse = try values.decodeIfPresent(AIUse.self, forKey: .aiUse) ?? .none
        navigatorRequestID = try values.decodeIfPresent(String.self, forKey: .navigatorRequestID)
        clientDecidedAt = try values.decodeIfPresent(Date.self, forKey: .clientDecidedAt)
        newFormulationID = try values.decodeIfPresent(String.self, forKey: .newFormulationID)
        followUpTaskID = try values.decodeIfPresent(String.self, forKey: .followUpTaskID)
    }
}

/// `POST /review/decisions/{id}/undo`.
public struct UndoDecisionBody: Codable, Hashable, Sendable {
    public var expectedTaskRevision: Int
    public init(expectedTaskRevision: Int) { self.expectedTaskRevision = expectedTaskRevision }
    enum CodingKeys: String, CodingKey { case expectedTaskRevision = "expected_task_revision" }
}

/// `POST /tasks/{id}/auto-park`: no `expected_revision` by design.
public struct AutoParkBody: Codable, Hashable, Sendable {
    public var formulationID: String
    public init(formulationID: String) { self.formulationID = formulationID }
    enum CodingKeys: String, CodingKey { case formulationID = "formulation_id" }
}

/// `POST /review/explainer/acknowledge`.
public struct ExplainerAcknowledgeBody: Codable, Hashable, Sendable {
    public var timeZone: String?
    public init(timeZone: String?) { self.timeZone = timeZone }
    enum CodingKeys: String, CodingKey { case timeZone = "time_zone" }
}

/// `PUT /review/settings`: only the fields a change sets.
public struct ReviewSettingsUpdateBody: Codable, Hashable, Sendable {
    public var thresholdDays: Int?
    public var reviewWeekday: Int?
    public var reviewTime: String?
    public var timeZone: String?
    /// Only `true` is ever sent.
    public var onboarded: Bool?
    public var expectedRevision: Int

    public init(_ change: ReviewSettingsChange, expectedRevision: Int) {
        thresholdDays = change.thresholdDays
        reviewWeekday = change.reviewWeekday
        reviewTime = change.reviewTime
        timeZone = change.timeZone
        onboarded = change.onboarded ? true : nil
        self.expectedRevision = expectedRevision
    }

    enum CodingKeys: String, CodingKey {
        case onboarded
        case thresholdDays = "threshold_days"
        case reviewWeekday = "review_weekday"
        case reviewTime = "review_time"
        case timeZone = "time_zone"
        case expectedRevision = "expected_revision"
    }
}

public struct ParkAcknowledgementItem: Codable, Hashable, Sendable {
    public var taskID: String
    public var formulationID: String
    public init(taskID: String, formulationID: String) {
        self.taskID = taskID
        self.formulationID = formulationID
    }
    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case formulationID = "formulation_id"
    }
}

/// `POST /review/parks/acknowledge` (204).
public struct ParkAcknowledgeBody: Codable, Hashable, Sendable {
    public var items: [ParkAcknowledgementItem]
    public init(items: [ParkAcknowledgementItem]) { self.items = items }
}

/// `POST /review/sessions`.
public struct SessionStartBody: Codable, Hashable, Sendable {
    public var id: String?
    public var mode: ReviewMode
    public var entry: ReviewEntry
    public var origin: ReviewOrigin
    public var skipSteps: [ReviewStep]
    public var replaceOpen: Bool

    public init(id: String?, mode: ReviewMode, entry: ReviewEntry, origin: ReviewOrigin, skipSteps: [ReviewStep], replaceOpen: Bool) {
        self.id = id
        self.mode = mode
        self.entry = entry
        self.origin = origin
        self.skipSteps = skipSteps
        self.replaceOpen = replaceOpen
    }

    enum CodingKeys: String, CodingKey {
        case id, mode, entry, origin
        case skipSteps = "skip_steps"
        case replaceOpen = "replace_open"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decodeIfPresent(String.self, forKey: .id)
        mode = try values.decode(ReviewMode.self, forKey: .mode)
        entry = try values.decode(ReviewEntry.self, forKey: .entry)
        origin = try values.decode(ReviewOrigin.self, forKey: .origin)
        skipSteps = try values.decodeIfPresent([ReviewStep].self, forKey: .skipSteps) ?? []
        replaceOpen = try values.decode(Bool.self, forKey: .replaceOpen)
    }
}

public struct StepUpdateBody: Codable, Hashable, Sendable {
    public var code: ReviewStep
    public var status: StepStatus

    public init(code: ReviewStep, status: StepStatus) {
        self.code = code
        self.status = status
    }
}

public struct ActiveSecondsBody: Codable, Hashable, Sendable {
    public var code: ReviewStep
    public var seconds: Int

    public init(code: ReviewStep, seconds: Int) {
        self.code = code
        self.seconds = seconds
    }
}

/// `PATCH /review/sessions/{id}`: merged, replay-safe by `progress_id`.
public struct SessionProgressBody: Codable, Hashable, Sendable {
    public var progressID: String
    public var currentStep: ReviewStep?
    public var step: StepUpdateBody?
    public var activeSeconds: ActiveSecondsBody?
    public var setAsideTaskID: String?
    public var inboxProcessedDelta: Int?
    /// Only `true` is ever sent.
    public var snapshotDecisionQueue: Bool?

    public init(
        progressID: String, currentStep: ReviewStep? = nil, step: StepUpdateBody? = nil,
        activeSeconds: ActiveSecondsBody? = nil, setAsideTaskID: String? = nil, inboxProcessedDelta: Int? = nil,
        snapshotDecisionQueue: Bool? = nil
    ) {
        self.progressID = progressID
        self.currentStep = currentStep
        self.step = step
        self.activeSeconds = activeSeconds
        self.setAsideTaskID = setAsideTaskID
        self.inboxProcessedDelta = inboxProcessedDelta
        self.snapshotDecisionQueue = snapshotDecisionQueue
    }

    enum CodingKeys: String, CodingKey {
        case step
        case progressID = "progress_id"
        case currentStep = "current_step"
        case activeSeconds = "active_seconds"
        case setAsideTaskID = "set_aside_task_id"
        case inboxProcessedDelta = "inbox_processed_delta"
        case snapshotDecisionQueue = "snapshot_decision_queue"
    }
}

/// `POST /review/sessions/{id}/finish`.
public struct SessionFinishBody: Codable, Hashable, Sendable {
    public var clearStart: ClearStart?
    public init(clearStart: ClearStart?) { self.clearStart = clearStart }
    enum CodingKeys: String, CodingKey { case clearStart = "clear_start" }
}

public struct BulkReleaseItemBody: Codable, Hashable, Sendable {
    public var taskID: String
    public var expectedRevision: Int
    public init(taskID: String, expectedRevision: Int) {
        self.taskID = taskID
        self.expectedRevision = expectedRevision
    }
    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case expectedRevision = "expected_revision"
    }
}

/// `POST /review/bulk-releases`; eligibility is the server's.
public struct BulkReleaseBody: Codable, Hashable, Sendable {
    public var id: String?
    public var kind: BulkReleaseKindCode
    public var sessionID: String?
    public var items: [BulkReleaseItemBody]

    public init(id: String?, kind: BulkReleaseKindCode, sessionID: String?, items: [BulkReleaseItemBody]) {
        self.id = id
        self.kind = kind
        self.sessionID = sessionID
        self.items = items
    }

    enum CodingKeys: String, CodingKey {
        case id, kind, items
        case sessionID = "session_id"
    }
}

/// `POST /review/navigator/consent`.
public struct NavigatorConsentGrantBody: Codable, Hashable, Sendable {
    public var provider: String
    public var consentTextVersion: Int
    public init(provider: String, consentTextVersion: Int) {
        self.provider = provider
        self.consentTextVersion = consentTextVersion
    }
    enum CodingKeys: String, CodingKey {
        case provider
        case consentTextVersion = "consent_text_version"
    }
}

// MARK: - Responses

public struct DecisionRecordDTO: Codable, Hashable, Sendable {
    public var id: String
    public var type: DecisionType
    public var taskID: String
    public var sessionID: String?
    public var decidedAt: Date
    public var substantive: Bool?
    public var stallReason: StallReason?
    public var aiUse: AIUse
    public var yieldedAutoPark: Bool

    public init(
        id: String, type: DecisionType, taskID: String, sessionID: String?, decidedAt: Date, substantive: Bool?,
        stallReason: StallReason?, aiUse: AIUse, yieldedAutoPark: Bool = false
    ) {
        self.id = id
        self.type = type
        self.taskID = taskID
        self.sessionID = sessionID
        self.decidedAt = decidedAt
        self.substantive = substantive
        self.stallReason = stallReason
        self.aiUse = aiUse
        self.yieldedAutoPark = yieldedAutoPark
    }

    enum CodingKeys: String, CodingKey {
        case id, type, substantive
        case taskID = "task_id"
        case sessionID = "session_id"
        case decidedAt = "decided_at"
        case stallReason = "stall_reason"
        case aiUse = "ai_use"
        case yieldedAutoPark = "yielded_auto_park"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        type = try values.decode(DecisionType.self, forKey: .type)
        taskID = try values.decode(String.self, forKey: .taskID)
        sessionID = try values.decodeIfPresent(String.self, forKey: .sessionID)
        decidedAt = try values.decode(Date.self, forKey: .decidedAt)
        substantive = try values.decodeIfPresent(Bool.self, forKey: .substantive)
        stallReason = try values.decodeIfPresent(StallReason.self, forKey: .stallReason)
        aiUse = try values.decode(AIUse.self, forKey: .aiUse)
        yieldedAutoPark = try values.decodeIfPresent(Bool.self, forKey: .yieldedAutoPark) ?? false
    }
}

public struct ReceiptDTO: Codable, Hashable, Sendable {
    public var taskID: String
    public var kind: ReceiptKind
    public var hiddenUntil: Date
    public var taskRevision: Int

    public init(taskID: String, kind: ReceiptKind, hiddenUntil: Date, taskRevision: Int) {
        self.taskID = taskID
        self.kind = kind
        self.hiddenUntil = hiddenUntil
        self.taskRevision = taskRevision
    }

    enum CodingKeys: String, CodingKey {
        case kind
        case taskID = "task_id"
        case hiddenUntil = "hidden_until"
        case taskRevision = "task_revision"
    }
}

public struct DecisionResponseDTO: Codable, Hashable, Sendable {
    public var decision: DecisionRecordDTO
    public var task: TaskDTO
    public var createdTask: TaskDTO?
    public var receipt: ReceiptDTO?
    public var sessionCounts: SessionCounts?

    public init(
        decision: DecisionRecordDTO, task: TaskDTO, createdTask: TaskDTO? = nil, receipt: ReceiptDTO? = nil,
        sessionCounts: SessionCounts? = nil
    ) {
        self.decision = decision
        self.task = task
        self.createdTask = createdTask
        self.receipt = receipt
        self.sessionCounts = sessionCounts
    }

    enum CodingKeys: String, CodingKey {
        case decision, task, receipt
        case createdTask = "created_task"
        case sessionCounts = "session_counts"
    }
}

public struct UndoDecisionResponseDTO: Codable, Hashable, Sendable {
    public var task: TaskDTO
    public var undoneDecisionID: String
    public var deletedTaskID: String?
    public var sessionCounts: SessionCounts?

    public init(task: TaskDTO, undoneDecisionID: String, deletedTaskID: String?, sessionCounts: SessionCounts?) {
        self.task = task
        self.undoneDecisionID = undoneDecisionID
        self.deletedTaskID = deletedTaskID
        self.sessionCounts = sessionCounts
    }

    enum CodingKeys: String, CodingKey {
        case task
        case undoneDecisionID = "undone_decision_id"
        case deletedTaskID = "deleted_task_id"
        case sessionCounts = "session_counts"
    }
}

public struct AutoParkResponseDTO: Codable, Hashable, Sendable {
    public var applied: Bool
    public var task: TaskDTO
    public init(applied: Bool, task: TaskDTO) {
        self.applied = applied
        self.task = task
    }
}

public struct ReviewSettingsDTO: Codable, Hashable, Sendable {
    public var thresholdDays: Int
    public var reviewWeekday: Int
    public var reviewTime: String
    public var timeZone: String
    public var onboardedAt: Date?
    public var activatedAt: Date?
    public var ownerParkFloorAt: Date?
    public var revision: Int

    public init(
        thresholdDays: Int, reviewWeekday: Int, reviewTime: String, timeZone: String, onboardedAt: Date?,
        activatedAt: Date?, ownerParkFloorAt: Date?, revision: Int
    ) {
        self.thresholdDays = thresholdDays
        self.reviewWeekday = reviewWeekday
        self.reviewTime = reviewTime
        self.timeZone = timeZone
        self.onboardedAt = onboardedAt
        self.activatedAt = activatedAt
        self.ownerParkFloorAt = ownerParkFloorAt
        self.revision = revision
    }

    enum CodingKeys: String, CodingKey {
        case revision
        case thresholdDays = "threshold_days"
        case reviewWeekday = "review_weekday"
        case reviewTime = "review_time"
        case timeZone = "time_zone"
        case onboardedAt = "onboarded_at"
        case activatedAt = "activated_at"
        case ownerParkFloorAt = "owner_park_floor_at"
    }

    /// As the device keeps it.
    public var settings: ReviewSettings {
        ReviewSettings(
            thresholdDays: thresholdDays, reviewWeekday: reviewWeekday, reviewTime: reviewTime, timeZone: timeZone,
            onboardedAt: onboardedAt, activatedAt: activatedAt, ownerParkFloorAt: ownerParkFloorAt, revision: revision
        )
    }
}

public struct LastCountedReviewDTO: Codable, Hashable, Sendable {
    public var sessionID: String
    public var status: ReviewSessionStatus
    public var origin: ReviewOrigin
    public var endedAt: Date?
    public var counts: SessionCounts
    public var clearStart: ClearStart?

    public init(
        sessionID: String, status: ReviewSessionStatus, origin: ReviewOrigin, endedAt: Date?, counts: SessionCounts,
        clearStart: ClearStart?
    ) {
        self.sessionID = sessionID
        self.status = status
        self.origin = origin
        self.endedAt = endedAt
        self.counts = counts
        self.clearStart = clearStart
    }

    enum CodingKeys: String, CodingKey {
        case status, origin, counts
        case sessionID = "session_id"
        case endedAt = "ended_at"
        case clearStart = "clear_start"
    }
}

public struct UnseenParkDTO: Codable, Hashable, Sendable {
    public var taskID: String
    public var formulationID: String
    public var parkedAt: Date

    public init(taskID: String, formulationID: String, parkedAt: Date) {
        self.taskID = taskID
        self.formulationID = formulationID
        self.parkedAt = parkedAt
    }

    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case formulationID = "formulation_id"
        case parkedAt = "parked_at"
    }
}

public struct ReviewStateCountsDTO: Codable, Hashable, Sendable {
    public var asksForDecision: Int
    public var movesTomorrow: Int

    public init(asksForDecision: Int, movesTomorrow: Int) {
        self.asksForDecision = asksForDecision
        self.movesTomorrow = movesTomorrow
    }

    enum CodingKeys: String, CodingKey {
        case asksForDecision = "asks_for_decision"
        case movesTomorrow = "moves_tomorrow"
    }
}

/// `SessionResponse`: exactly the http §6 field list.
public struct SessionDTO: Codable, Hashable, Sendable {
    public var id: String
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
    public var setAsideCount: Int
    public var qualifyingActivity: Bool
    public var clearStart: ClearStart?
    public var revision: Int

    public init(
        id: String, mode: ReviewMode, entry: ReviewEntry, origin: ReviewOrigin, status: ReviewSessionStatus,
        startedAt: Date, lastActivityAt: Date, endedAt: Date?, currentStep: ReviewStep?, steps: [ReviewStep: StepStatus],
        activeSecondsByStep: [ReviewStep: Int], counts: SessionCounts, setAsideCount: Int, qualifyingActivity: Bool,
        clearStart: ClearStart?, revision: Int
    ) {
        self.id = id
        self.mode = mode
        self.entry = entry
        self.origin = origin
        self.status = status
        self.startedAt = startedAt
        self.lastActivityAt = lastActivityAt
        self.endedAt = endedAt
        self.currentStep = currentStep
        self.steps = steps
        self.activeSecondsByStep = activeSecondsByStep
        self.counts = counts
        self.setAsideCount = setAsideCount
        self.qualifyingActivity = qualifyingActivity
        self.clearStart = clearStart
        self.revision = revision
    }

    enum CodingKeys: String, CodingKey {
        case id, mode, entry, origin, status, steps, counts, revision
        case startedAt = "started_at"
        case lastActivityAt = "last_activity_at"
        case endedAt = "ended_at"
        case currentStep = "current_step"
        case activeSecondsByStep = "active_seconds_by_step"
        case setAsideCount = "set_aside_count"
        case qualifyingActivity = "qualifying_activity"
        case clearStart = "clear_start"
    }

    /// As the device keeps it; `local` keeps what only the device knows.
    public func session(keeping local: ReviewSession?) -> ReviewSession {
        ReviewSession(
            id: ReviewSessionID(id), mode: mode, entry: entry, origin: origin, status: status, startedAt: startedAt,
            lastActivityAt: lastActivityAt, endedAt: endedAt, currentStep: currentStep, steps: steps,
            activeSecondsByStep: activeSecondsByStep, counts: counts, setAsideTaskIDs: local?.setAsideTaskIDs ?? [],
            setAsideCount: setAsideCount, qualifyingActivity: qualifyingActivity, clearStart: clearStart,
            decisionQueue: local?.decisionQueue, appliedProgress: local?.appliedProgress ?? [], revision: revision
        )
    }
}

/// `GET /review/state` (http §5).
public struct ReviewStateDTO: Codable, Hashable, Sendable {
    public var settings: ReviewSettingsDTO
    public var explainerSeen: Bool
    public var graceUntil: Date?
    public var lastCountedReviewAt: Date?
    public var lastCountedReview: LastCountedReviewDTO?
    public var nextReviewAt: Date
    public var restartMode: Bool
    public var openSession: SessionDTO?
    public var unseenParks: [UnseenParkDTO]
    public var counts: ReviewStateCountsDTO
    public var receipts: [ReceiptDTO]
    public var serverNow: Date

    public init(
        settings: ReviewSettingsDTO, explainerSeen: Bool, graceUntil: Date?, lastCountedReviewAt: Date?,
        lastCountedReview: LastCountedReviewDTO?, nextReviewAt: Date, restartMode: Bool, openSession: SessionDTO?,
        unseenParks: [UnseenParkDTO], counts: ReviewStateCountsDTO, receipts: [ReceiptDTO], serverNow: Date
    ) {
        self.settings = settings
        self.explainerSeen = explainerSeen
        self.graceUntil = graceUntil
        self.lastCountedReviewAt = lastCountedReviewAt
        self.lastCountedReview = lastCountedReview
        self.nextReviewAt = nextReviewAt
        self.restartMode = restartMode
        self.openSession = openSession
        self.unseenParks = unseenParks
        self.counts = counts
        self.receipts = receipts
        self.serverNow = serverNow
    }

    enum CodingKeys: String, CodingKey {
        case settings, counts, receipts
        case explainerSeen = "explainer_seen"
        case graceUntil = "grace_until"
        case lastCountedReviewAt = "last_counted_review_at"
        case lastCountedReview = "last_counted_review"
        case nextReviewAt = "next_review_at"
        case restartMode = "restart_mode"
        case openSession = "open_session"
        case unseenParks = "unseen_parks"
        case serverNow = "server_now"
    }
}

public struct QueueDayDTO: Codable, Hashable, Sendable {
    public var day: CalendarDay
    public var taskIDs: [String]
    enum CodingKeys: String, CodingKey {
        case day
        case taskIDs = "task_ids"
    }
}

/// A queue's `meta`, whichever step it belongs to (every member optional).
public struct QueueMetaDTO: Codable, Hashable, Sendable {
    public var count: Int?
    public var nextCount: Int?
    public var weeklyAverage4w: Double?
    public var weeksOfHistory: Int?
    public var impliedWeeks: Double?
    public var eligibleTotal: Int?
    public var shown: Int?
    public var days: [QueueDayDTO]?

    enum CodingKeys: String, CodingKey {
        case count, shown, days
        case nextCount = "next_count"
        case weeklyAverage4w = "weekly_average_4w"
        case weeksOfHistory = "weeks_of_history"
        case impliedWeeks = "implied_weeks"
        case eligibleTotal = "eligible_total"
    }
}

/// `GET /review/queues/{step}`.
public struct QueueResponseDTO: Codable, Hashable, Sendable {
    public var items: [TaskDTO]
    public var meta: QueueMetaDTO
}

public struct BulkReleasedItemDTO: Codable, Hashable, Sendable {
    public var taskID: String
    public var revisionAfter: Int
    public init(taskID: String, revisionAfter: Int) {
        self.taskID = taskID
        self.revisionAfter = revisionAfter
    }
    enum CodingKeys: String, CodingKey {
        case taskID = "task_id"
        case revisionAfter = "revision_after"
    }
}

public struct BulkSkippedItemDTO: Codable, Hashable, Sendable {
    public var taskID: String
    public var reason: String
    public init(taskID: String, reason: String) {
        self.taskID = taskID
        self.reason = reason
    }
    enum CodingKeys: String, CodingKey {
        case reason
        case taskID = "task_id"
    }
}

public struct BulkReleaseResponseDTO: Codable, Hashable, Sendable {
    public var id: String
    public var released: [BulkReleasedItemDTO]
    public var skipped: [BulkSkippedItemDTO]
    public init(id: String, released: [BulkReleasedItemDTO], skipped: [BulkSkippedItemDTO]) {
        self.id = id
        self.released = released
        self.skipped = skipped
    }
}

public struct BulkReleaseUndoResponseDTO: Codable, Hashable, Sendable {
    public var restored: [String]
    public var skipped: [BulkSkippedItemDTO]
    public init(restored: [String], skipped: [BulkSkippedItemDTO]) {
        self.restored = restored
        self.skipped = skipped
    }
}

public struct NavigatorConsentDTO: Codable, Hashable, Sendable {
    public var grantedAt: Date
    public var revokedAt: Date?
    public var consentTextVersion: Int

    public init(grantedAt: Date, revokedAt: Date?, consentTextVersion: Int) {
        self.grantedAt = grantedAt
        self.revokedAt = revokedAt
        self.consentTextVersion = consentTextVersion
    }

    enum CodingKeys: String, CodingKey {
        case grantedAt = "granted_at"
        case revokedAt = "revoked_at"
        case consentTextVersion = "consent_text_version"
    }
}

/// `GET /review/navigator` (never gated).
public struct NavigatorStatusDTO: Codable, Hashable, Sendable {
    public var provider: String?
    public var consent: NavigatorConsentDTO?
    public var consentCurrent: Bool
    public var consentTextVersion: Int
    public var available: Bool

    public init(
        provider: String?, consent: NavigatorConsentDTO?, consentCurrent: Bool, consentTextVersion: Int, available: Bool
    ) {
        self.provider = provider
        self.consent = consent
        self.consentCurrent = consentCurrent
        self.consentTextVersion = consentTextVersion
        self.available = available
    }

    enum CodingKeys: String, CodingKey {
        case provider, consent, available
        case consentCurrent = "consent_current"
        case consentTextVersion = "consent_text_version"
    }
}

/// `POST /review/navigator/suggestions` (the navigator client is PR-08's).
public struct NavigatorSuggestionResponseDTO: Codable, Hashable, Sendable {
    public var requestID: String
    public var provider: String
    public var notesTruncated: Bool
    public var proposals: [String]?
    public var clarifyingQuestion: String?
    enum CodingKeys: String, CodingKey {
        case provider, proposals
        case requestID = "request_id"
        case notesTruncated = "notes_truncated"
        case clarifyingQuestion = "clarifying_question"
    }
}

// MARK: - Client

extension BrainBuddyAPIClient {
    /// `POST /tasks/{id}/decisions` → 200.
    public func decide(taskID: String, _ body: DecisionRequestBody, idempotencyKey: UUID) async throws(APIError)
        -> DecisionResponseDTO
    {
        try await mutate(.post, ["tasks", taskID, "decisions"], body, key: idempotencyKey)
    }

    /// `POST /review/decisions/{id}/undo` → 200; 404 once already undone.
    public func undoDecision(id: String, expectedTaskRevision: Int, idempotencyKey: UUID) async throws(APIError)
        -> UndoDecisionResponseDTO
    {
        try await mutate(
            .post, ["review", "decisions", id, "undo"], UndoDecisionBody(expectedTaskRevision: expectedTaskRevision),
            key: idempotencyKey
        )
    }

    /// `POST /tasks/{id}/auto-park` → 200 `{applied, task}`.
    public func autoPark(taskID: String, formulationID: String, idempotencyKey: UUID) async throws(APIError)
        -> AutoParkResponseDTO
    {
        try await mutate(.post, ["tasks", taskID, "auto-park"], AutoParkBody(formulationID: formulationID), key: idempotencyKey)
    }

    /// `GET /review/state`; 404 `weekly_review_disabled` is `.featureDisabled`.
    public func reviewState() async throws(APIError) -> ReviewStateDTO {
        try await get(["review", "state"])
    }

    /// `POST /review/explainer/acknowledge` → the review state.
    public func acknowledgeExplainer(timeZone: String?, idempotencyKey: UUID) async throws(APIError) -> ReviewStateDTO {
        try await mutate(.post, ["review", "explainer", "acknowledge"], ExplainerAcknowledgeBody(timeZone: timeZone), key: idempotencyKey)
    }

    /// `PUT /review/settings` → the settings; 409 on a stale `expected_revision`.
    public func updateReviewSettings(_ body: ReviewSettingsUpdateBody, idempotencyKey: UUID) async throws(APIError)
        -> ReviewSettingsDTO
    {
        try await mutate(.put, ["review", "settings"], body, key: idempotencyKey)
    }

    /// `POST /review/parks/acknowledge` → 204.
    public func acknowledgeParks(_ items: [ParkAcknowledgementItem], idempotencyKey: UUID) async throws(APIError) {
        let body = try encode(ParkAcknowledgeBody(items: items))
        _ = try await exchange(Endpoint(.post, ["review", "parks", "acknowledge"], body: body, idempotencyKey: idempotencyKey))
    }

    /// `POST /review/sessions` → 201 session.
    public func startSession(_ body: SessionStartBody, idempotencyKey: UUID) async throws(APIError) -> SessionDTO {
        try await mutate(.post, ["review", "sessions"], body, key: idempotencyKey)
    }

    /// `PATCH /review/sessions/{id}` → the merged session.
    public func progressSession(id: String, _ body: SessionProgressBody, idempotencyKey: UUID) async throws(APIError)
        -> SessionDTO
    {
        try await mutate(.patch, ["review", "sessions", id], body, key: idempotencyKey)
    }

    /// `POST /review/sessions/{id}/finish` → the session (idempotent).
    public func finishSession(id: String, clearStart: ClearStart?, idempotencyKey: UUID) async throws(APIError) -> SessionDTO {
        try await mutate(.post, ["review", "sessions", id, "finish"], SessionFinishBody(clearStart: clearStart), key: idempotencyKey)
    }

    /// `GET /review/sessions/{id}`.
    public func session(id: String) async throws(APIError) -> SessionDTO {
        try await get(["review", "sessions", id])
    }

    /// `GET /review/queues/{step}?session_id=…`.
    public func reviewQueue(_ step: ReviewStep, sessionID: String?) async throws(APIError) -> QueueResponseDTO {
        try await get(["review", "queues", step.rawValue], query: sessionID.map { [(name: "session_id", value: $0)] } ?? [])
    }

    /// `POST /review/bulk-releases` → 200 with released and skipped.
    public func bulkRelease(_ body: BulkReleaseBody, idempotencyKey: UUID) async throws(APIError) -> BulkReleaseResponseDTO {
        try await mutate(.post, ["review", "bulk-releases"], body, key: idempotencyKey)
    }

    /// `POST /review/bulk-releases/{id}/undo` → 200 (the stored result when already undone).
    public func undoBulkRelease(id: String, idempotencyKey: UUID) async throws(APIError) -> BulkReleaseUndoResponseDTO {
        let exchange = try await exchange(Endpoint(.post, ["review", "bulk-releases", id, "undo"], body: Data("{}".utf8), idempotencyKey: idempotencyKey))
        return try decode(exchange)
    }

    /// `GET /review/navigator`.
    public func navigatorStatus() async throws(APIError) -> NavigatorStatusDTO {
        try await get(["review", "navigator"])
    }

    /// `POST /review/navigator/consent`.
    public func grantNavigatorConsent(provider: String, consentTextVersion: Int, idempotencyKey: UUID) async throws(APIError) {
        let body = try encode(NavigatorConsentGrantBody(provider: provider, consentTextVersion: consentTextVersion))
        _ = try await exchange(Endpoint(.post, ["review", "navigator", "consent"], body: body, idempotencyKey: idempotencyKey))
    }

    /// `DELETE /review/navigator/consent` → 204 (never gated).
    public func revokeNavigatorConsent(idempotencyKey: UUID) async throws(APIError) {
        _ = try await exchange(Endpoint(.delete, ["review", "navigator", "consent"], idempotencyKey: idempotencyKey))
    }
}
