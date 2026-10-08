import Foundation

/// A three-way field edit: leave alone, clear (JSON `null`), or set.
public enum FieldChange<Value: Hashable & Sendable & Codable>: Hashable, Sendable, Codable {
    case unchanged
    case clear
    case set(Value)

    public var isChanged: Bool { self != .unchanged }

    /// `later` wins unless it is `.unchanged`.
    public func merged(with later: FieldChange) -> FieldChange { later.isChanged ? later : self }
}

/// Field edits for PATCH /tasks/{id}. List/state changes are transitions, not edits.
/// `waitingFor` may only be set while the task is Waiting (server rule).
public struct TaskChanges: Hashable, Sendable, Codable {
    public var title: FieldChange<String>
    public var details: FieldChange<String>
    public var projectID: FieldChange<ProjectID>
    public var tagIDs: FieldChange<[TagID]>
    public var dueDate: FieldChange<CalendarDay>
    public var priority: FieldChange<TaskPriority>
    public var waitingFor: FieldChange<String>

    public init(
        title: FieldChange<String> = .unchanged, details: FieldChange<String> = .unchanged,
        projectID: FieldChange<ProjectID> = .unchanged, tagIDs: FieldChange<[TagID]> = .unchanged,
        dueDate: FieldChange<CalendarDay> = .unchanged, priority: FieldChange<TaskPriority> = .unchanged,
        waitingFor: FieldChange<String> = .unchanged
    ) {
        self.title = title
        self.details = details
        self.projectID = projectID
        self.tagIDs = tagIDs
        self.dueDate = dueDate
        self.priority = priority
        self.waitingFor = waitingFor
    }

    public var hasChanges: Bool {
        title.isChanged || details.isChanged || projectID.isChanged || tagIDs.isChanged
            || dueDate.isChanged || priority.isChanged || waitingFor.isChanged
    }

    /// Field-by-field merge where `later` wins.
    public func merged(with later: TaskChanges) -> TaskChanges {
        TaskChanges(
            title: title.merged(with: later.title), details: details.merged(with: later.details),
            projectID: projectID.merged(with: later.projectID), tagIDs: tagIDs.merged(with: later.tagIDs),
            dueDate: dueDate.merged(with: later.dueDate), priority: priority.merged(with: later.priority),
            waitingFor: waitingFor.merged(with: later.waitingFor)
        )
    }
}

/// One user intent. Each case maps to exactly one API request, so each queued
/// command carries exactly one `Idempotency-Key`. Commands carry every id they
/// create, which keeps `GTDReducer` deterministic and replayable.
public enum GTDCommand: Hashable, Sendable, Codable {
    case createProject(CreateProject)
    case updateProject(UpdateProject)
    case archiveProject(ProjectID)
    /// `PATCH /projects/{id}` with `desired_outcome` (spec 021); nil clears it.
    case setProjectOutcome(project: ProjectID, outcome: String?)
    /// `POST /projects/{id}/unarchive` (ADR-0020).
    case unarchiveProject(project: ProjectID)
    case createTag(CreateTag)
    case renameTag(RenameTag)
    case deleteTag(TagID)
    case createTask(CreateTask)
    case updateTask(UpdateTask)
    case transitionTask(TransitionTask)
    case createSubtask(CreateSubtask)
    case updateSubtask(UpdateSubtask)
    case transitionSubtask(TransitionSubtask)
    case createComment(CreateComment)
    case updateComment(UpdateComment)
    /// `POST /tasks/{id}/decisions` (spec 020, contracts/ios-commands.md §2).
    case decideTask(DecideTask)
    /// `POST /review/decisions/{id}/undo`.
    case undoDecision(DecisionID)
    /// `POST /tasks/{id}/auto-park`.
    case autoParkTask(AutoParkTask)
    /// `POST /review/bulk-releases`.
    case bulkRelease(BulkRelease)
    /// `POST /review/bulk-releases/{id}/undo`.
    case undoBulkRelease(BulkID)
    /// One request per case; mutates `GTDState.review` only.
    case review(ReviewCommand)

    public struct CreateProject: Hashable, Sendable, Codable {
        public var projectID: ProjectID
        public var name: String
        public var color: String?
        public var desiredOutcome: String?
        public init(projectID: ProjectID, name: String, color: String? = nil, desiredOutcome: String? = nil) {
            self.projectID = projectID
            self.name = name
            self.color = color
            self.desiredOutcome = desiredOutcome
        }
    }

    public struct UpdateProject: Hashable, Sendable, Codable {
        public var projectID: ProjectID
        public var name: String?
        public var color: FieldChange<String>
        public init(projectID: ProjectID, name: String? = nil, color: FieldChange<String> = .unchanged) {
            self.projectID = projectID
            self.name = name
            self.color = color
        }
    }

    public struct CreateTag: Hashable, Sendable, Codable {
        public var tagID: TagID
        public var name: String
        public init(tagID: TagID, name: String) {
            self.tagID = tagID
            self.name = name
        }
    }

    public struct RenameTag: Hashable, Sendable, Codable {
        public var tagID: TagID
        public var name: String
        public init(tagID: TagID, name: String) {
            self.tagID = tagID
            self.name = name
        }
    }

    /// Creates an open task. Terminal tasks are created open and then transitioned.
    public struct CreateTask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var title: String
        public var details: String?
        public var list: OpenList
        public var waitingFor: String?
        public var dueDate: CalendarDay?
        public var priority: TaskPriority
        public var projectID: ProjectID?
        public var tagIDs: [TagID]
        /// The formulation a creation in Next starts (`new_formulation_id`).
        public var newFormulationID: FormulationID?
        public init(
            taskID: TaskID, title: String, details: String? = nil, list: OpenList,
            waitingFor: String? = nil, dueDate: CalendarDay? = nil, priority: TaskPriority = .none,
            projectID: ProjectID? = nil, tagIDs: [TagID] = [], newFormulationID: FormulationID? = nil
        ) {
            self.taskID = taskID
            self.title = title
            self.details = details
            self.list = list
            self.waitingFor = waitingFor
            self.dueDate = dueDate
            self.priority = priority
            self.projectID = projectID
            self.tagIDs = tagIDs
            self.newFormulationID = newFormulationID
        }
    }

    public struct UpdateTask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var changes: TaskChanges
        /// The formulation a substantive title change in Next starts.
        public var newFormulationID: FormulationID?
        public init(taskID: TaskID, changes: TaskChanges, newFormulationID: FormulationID? = nil) {
            self.taskID = taskID
            self.changes = changes
            self.newFormulationID = newFormulationID
        }
    }

    /// `toList` is required for `move` and `reopen` and ignored otherwise;
    /// `waitingFor` is required when the destination is Waiting.
    public struct TransitionTask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var action: TaskTransitionAction
        public var toList: OpenList?
        public var waitingFor: String?
        /// The formulation a move or reopen into Next starts.
        public var newFormulationID: FormulationID?
        public init(
            taskID: TaskID, action: TaskTransitionAction, toList: OpenList? = nil, waitingFor: String? = nil,
            newFormulationID: FormulationID? = nil
        ) {
            self.taskID = taskID
            self.action = action
            self.toList = toList
            self.waitingFor = waitingFor
            self.newFormulationID = newFormulationID
        }
    }

    /// A decision on one task (contracts/http.md §3). Carries every client id
    /// it creates: the decision, a new formulation, a follow-up task.
    public struct DecideTask: Hashable, Sendable, Codable {
        public var decisionID: DecisionID
        public var taskID: TaskID
        public var type: DecisionType
        /// The formulation decided on (required for the Next-only types).
        public var formulationID: FormulationID?
        public var newFormulationID: FormulationID?
        public var stallReason: StallReason?
        public var title: String?
        public var waitingFor: String?
        /// `extend` only: why the wording still fits.
        public var reason: String?
        public var sessionID: ReviewSessionID?
        public var aiUse: AIUse
        public var navigatorRequestID: String?
        /// `follow_up`: the client id of the task it creates (`task_<uuid>`).
        public var followUpTaskID: TaskID?
        /// False once the undo snapshot was dropped by local retention (7 days).
        public var undoRetained: Bool
        /// FR-011: the task as the card or form showed it (`ShownTask`: its
        /// revision, `updatedAt` and children). A decision on a task that changed since is
        /// stale. Checked only when the person decides (not on replay, where
        /// the server's `expected_revision` and yield rule decide) and never
        /// stored or sent, so it is not part of the encoded command.
        public var expectedTask: ShownTask? = nil

        enum CodingKeys: String, CodingKey {
            case decisionID, taskID, type, formulationID, newFormulationID, stallReason, title, waitingFor, reason
            case sessionID, aiUse, navigatorRequestID, followUpTaskID, undoRetained
        }

        public init(
            decisionID: DecisionID, taskID: TaskID, type: DecisionType, formulationID: FormulationID? = nil,
            newFormulationID: FormulationID? = nil, stallReason: StallReason? = nil, title: String? = nil,
            waitingFor: String? = nil, reason: String? = nil, sessionID: ReviewSessionID? = nil, aiUse: AIUse = .none,
            navigatorRequestID: String? = nil, followUpTaskID: TaskID? = nil, undoRetained: Bool = true,
            expectedTask: ShownTask? = nil
        ) {
            self.expectedTask = expectedTask
            self.decisionID = decisionID
            self.taskID = taskID
            self.type = type
            self.formulationID = formulationID
            self.newFormulationID = newFormulationID
            self.stallReason = stallReason
            self.title = title
            self.waitingFor = waitingFor
            self.reason = reason
            self.sessionID = sessionID
            self.aiUse = aiUse
            self.navigatorRequestID = navigatorRequestID
            self.followUpTaskID = followUpTaskID
            self.undoRetained = undoRetained
        }
    }

    /// A park the device observed. `observedAt` is the instant it evaluated
    /// the task as `park_due` (signed in: its clock plus the last observed
    /// server offset). `optimistic` is false when the device was online: the
    /// task then parks on the device only once the server answers
    /// `applied: true` (contracts/ios-commands.md §5).
    public struct AutoParkTask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var formulationID: FormulationID
        public var observedAt: Date?
        public var optimistic: Bool

        public init(taskID: TaskID, formulationID: FormulationID, observedAt: Date? = nil, optimistic: Bool = true) {
            self.taskID = taskID
            self.formulationID = formulationID
            self.observedAt = observedAt
            self.optimistic = optimistic
        }
    }

    /// A person's release of several tasks to Someday (FR-017 restart,
    /// FR-030 Inbox remainder); the server decides eligibility per task.
    public struct BulkRelease: Hashable, Sendable, Codable {
        public var bulkID: BulkID
        public var kind: BulkReleaseKindCode
        public var sessionID: ReviewSessionID?
        public var taskIDs: [TaskID]
        public var undoRetained: Bool

        public init(
            bulkID: BulkID, kind: BulkReleaseKindCode, sessionID: ReviewSessionID? = nil, taskIDs: [TaskID],
            undoRetained: Bool = true
        ) {
            self.bulkID = bulkID
            self.kind = kind
            self.sessionID = sessionID
            self.taskIDs = taskIDs
            self.undoRetained = undoRetained
        }
    }

    public struct CreateSubtask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var subtaskID: SubtaskID
        public var title: String
        public init(taskID: TaskID, subtaskID: SubtaskID, title: String) {
            self.taskID = taskID
            self.subtaskID = subtaskID
            self.title = title
        }
    }

    public struct UpdateSubtask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var subtaskID: SubtaskID
        public var title: String
        public init(taskID: TaskID, subtaskID: SubtaskID, title: String) {
            self.taskID = taskID
            self.subtaskID = subtaskID
            self.title = title
        }
    }

    public struct TransitionSubtask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var subtaskID: SubtaskID
        public var action: SubtaskTransitionAction
        public init(taskID: TaskID, subtaskID: SubtaskID, action: SubtaskTransitionAction) {
            self.taskID = taskID
            self.subtaskID = subtaskID
            self.action = action
        }
    }

    public struct CreateComment: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var commentID: CommentID
        public var body: String
        public init(taskID: TaskID, commentID: CommentID, body: String) {
            self.taskID = taskID
            self.commentID = commentID
            self.body = body
        }
    }

    public struct UpdateComment: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var commentID: CommentID
        public var body: String
        public init(taskID: TaskID, commentID: CommentID, body: String) {
            self.taskID = taskID
            self.commentID = commentID
            self.body = body
        }
    }
}

/// Review commands (contracts/ios-commands.md §2): each maps to one request
/// and mutates `GTDState.review` only.
public enum ReviewCommand: Hashable, Sendable, Codable {
    /// `POST /review/explainer/acknowledge` with the device zone (FR-051).
    /// It writes only the activation instant; task clocks change in the
    /// post-replay activation step (`ReviewActivation`).
    case acknowledgeExplainer(timeZone: String?)
    /// `PUT /review/settings`: only the fields this change sets.
    case updateSettings(ReviewSettingsChange)
    /// `POST /review/parks/acknowledge`.
    case acknowledgeParks([ParkAck])
    /// `POST /review/sessions` with `id` and `replace_open: true`.
    case startSession(StartSession)
    /// `PATCH /review/sessions/{id}` with `progress_id`.
    case progressSession(SessionProgress)
    /// `POST /review/sessions/{id}/finish` (only Done on the summary).
    case finishSession(FinishSession)
    /// `POST /review/navigator/consent`.
    case grantNavigatorConsent(provider: String, consentTextVersion: Int)
    /// `DELETE /review/navigator/consent`.
    case revokeNavigatorConsent(provider: String)
}

/// The fields of `PUT /review/settings` a change sets; nil leaves a field alone.
public struct ReviewSettingsChange: Hashable, Sendable, Codable {
    public var thresholdDays: Int?
    public var reviewWeekday: Int?
    public var reviewTime: String?
    public var timeZone: String?
    public var onboarded: Bool

    public init(
        thresholdDays: Int? = nil, reviewWeekday: Int? = nil, reviewTime: String? = nil, timeZone: String? = nil,
        onboarded: Bool = false
    ) {
        self.thresholdDays = thresholdDays
        self.reviewWeekday = reviewWeekday
        self.reviewTime = reviewTime
        self.timeZone = timeZone
        self.onboarded = onboarded
    }

    public var isEmpty: Bool {
        thresholdDays == nil && reviewWeekday == nil && reviewTime == nil && timeZone == nil && !onboarded
    }
}

public struct StartSession: Hashable, Sendable, Codable {
    public var sessionID: ReviewSessionID
    public var mode: ReviewMode
    public var entry: ReviewEntry
    public var origin: ReviewOrigin
    public var skipSteps: [ReviewStep]

    public init(
        sessionID: ReviewSessionID, mode: ReviewMode, entry: ReviewEntry, origin: ReviewOrigin = .ios,
        skipSteps: [ReviewStep] = []
    ) {
        self.sessionID = sessionID
        self.mode = mode
        self.entry = entry
        self.origin = origin
        self.skipSteps = skipSteps
    }
}

/// One progress change, replay-safe by `progressID` at any age (http §6).
public struct SessionProgress: Hashable, Sendable, Codable {
    public var sessionID: ReviewSessionID
    public var progressID: ProgressID
    public var currentStep: ReviewStep?
    public var step: ReviewStep?
    public var stepStatus: StepStatus?
    public var activeStep: ReviewStep?
    public var activeSeconds: Int?
    public var setAsideTaskID: TaskID?
    public var inboxProcessedDelta: Int?
    public var snapshotDecisionQueue: Bool

    public init(
        sessionID: ReviewSessionID, progressID: ProgressID, currentStep: ReviewStep? = nil, step: ReviewStep? = nil,
        stepStatus: StepStatus? = nil, activeStep: ReviewStep? = nil, activeSeconds: Int? = nil,
        setAsideTaskID: TaskID? = nil, inboxProcessedDelta: Int? = nil, snapshotDecisionQueue: Bool = false
    ) {
        self.sessionID = sessionID
        self.progressID = progressID
        self.currentStep = currentStep
        self.step = step
        self.stepStatus = stepStatus
        self.activeStep = activeStep
        self.activeSeconds = activeSeconds
        self.setAsideTaskID = setAsideTaskID
        self.inboxProcessedDelta = inboxProcessedDelta
        self.snapshotDecisionQueue = snapshotDecisionQueue
    }
}

public struct FinishSession: Hashable, Sendable, Codable {
    public var sessionID: ReviewSessionID
    public var clearStart: ClearStart?

    public init(sessionID: ReviewSessionID, clearStart: ClearStart? = nil) {
        self.sessionID = sessionID
        self.clearStart = clearStart
    }
}

/// Every rule the reducer enforces. `message` is user-facing copy: calm,
/// sentence case, English, and specific about the reason.
public enum GTDValidationError: Error, Hashable, Sendable, Codable {
    case taskNotFound
    case subtaskNotFound
    case commentNotFound
    case projectNotFound
    case tagNotFound
    case idAlreadyExists
    case emptyTitle
    case titleTooLong
    case detailsTooLong
    case waitingForRequired
    case waitingForTooLong
    case waitingForOnlyOnWaitingTasks
    case emptyName
    case nameTooLong
    case colorTooLong
    case duplicateProjectName(String)
    case duplicateTagName(String)
    case projectNotActive
    case tagNotActive
    case duplicateTag
    case taskNotOpen
    case taskNotClosed
    case moveRequiresDestination
    case moveRequiresDifferentList
    case reopenRequiresDestination
    case subtaskAlreadyInState
    case emptyComment
    case commentTooLong
    case nothingToChange
    /// `priority` cannot be cleared; "no priority" is `.set(.none)` (server: "Task priority cannot be null").
    case priorityRequired
    case projectAlreadyArchived
    case tagAlreadyDeleted
    // Spec 021 (contracts/kit-commands.md §2).
    case outcomeTooLong
    case unarchiveNameInUse(String)
    /// A merge by name did not apply the local archive to the account's active project.
    case archiveNotMerged(String)
    /// A merge by name kept the account's desired outcome; the local one is in the issue's command.
    case outcomeKept
    // Spec 020 (contracts/ios-commands.md §2).
    case decisionNotAllowed
    case extensionAlreadyUsed
    case extensionNotDue
    case formulationChanged
    case undoUnavailable
    case projectArchived
    case extensionReasonRequired
    case extensionReasonTooLong
    case reviewNotFound
    /// More items than one request takes (bulk release 500, park acknowledgements 200).
    case tooManyItems
    /// The weekly review is not exposed (the flag or release switch is off).
    case reviewUnavailable
    /// A progress change names a step the review's mode does not have (the server answers 422).
    case stepNotInReview
    /// Spec 021 (FR-018, X-04): the device is signing out and its data is about to be removed, so
    /// the workspace takes no change until that is done; the change is refused, never dropped.
    case signingOut

    public var message: String {
        switch self {
        case .taskNotFound: "This task no longer exists."
        case .subtaskNotFound: "This subtask no longer exists."
        case .commentNotFound: "This comment no longer exists."
        case .projectNotFound: "This project no longer exists."
        case .tagNotFound: "This tag no longer exists."
        case .idAlreadyExists: "This item was already added."
        case .emptyTitle: "Add a title for the task."
        case .titleTooLong: "Keep the title under \(GTDLimits.title) characters."
        case .detailsTooLong: "Keep the notes under \(GTDLimits.details) characters."
        case .waitingForRequired: "Say who or what you are waiting on."
        case .waitingForTooLong: "Keep the waiting note under \(GTDLimits.waitingFor) characters."
        case .waitingForOnlyOnWaitingTasks: "Only tasks in Waiting for have a waiting note."
        case .emptyName: "Add a name."
        case .nameTooLong: "Keep the name under \(GTDLimits.name) characters."
        case .colorTooLong: "This colour value is too long."
        case .duplicateProjectName(let name): "A project named \(name) already exists."
        case .duplicateTagName(let name): "A tag named \(name) already exists."
        case .projectNotActive: "Archived projects can't take new tasks."
        case .tagNotActive: "Deleted tags can't be added to tasks."
        case .duplicateTag: "This tag is already on the task."
        case .taskNotOpen: "Reopen this task first."
        case .taskNotClosed: "This task is already open."
        case .moveRequiresDestination: "Choose a list to move the task to."
        case .moveRequiresDifferentList: "The task is already in this list."
        case .reopenRequiresDestination: "Choose the list to reopen the task into."
        case .subtaskAlreadyInState: "The subtask is already in that state."
        case .emptyComment: "Write something before saving the comment."
        case .commentTooLong: "Keep the comment under \(GTDLimits.comment) characters."
        case .nothingToChange: "There is nothing to save."
        case .priorityRequired: "Choose a priority, or No priority."
        case .projectAlreadyArchived: "This project is already archived."
        case .tagAlreadyDeleted: "This tag was already deleted."
        case .outcomeTooLong: "Keep the desired outcome under 1,000 characters."
        case .unarchiveNameInUse(let name): "Another active project is already called “\(name)”. Rename one first."
        case .outcomeKept: "Kept the desired outcome already on your account. Yours is below, so you can copy it."
        case .archiveNotMerged(let name):
            "Your account already has an active project called “\(name)”. This Mac's tasks were added to it, and it stays active."
        case .decisionNotAllowed: "This decision isn't available for this task's current list. Nothing was changed."
        case .extensionAlreadyUsed: "You've already kept this wording 7 more days once."
        case .extensionNotDue: "This wording can be kept 7 more days once it asks for a decision."
        case .formulationChanged: "This task changed on another device, so nothing was applied."
        case .undoUnavailable: "Couldn't undo: the task changed since."
        case .projectArchived: "Restore this archived project first."
        case .extensionReasonRequired: "Add a reason to continue."
        case .extensionReasonTooLong: "Keep the reason under \(GTDLimits.title) characters."
        case .reviewNotFound: "This review is no longer on this device."
        case .tooManyItems: "That's more than can be saved at once. Try fewer tasks."
        case .reviewUnavailable: "The weekly review is turned off for now. Nothing was changed."
        case .stepNotInReview: "That step isn't part of this review. Nothing was changed."
        case .signingOut: "Brain Buddy is signing out. This wasn't saved; try again in a moment."
        }
    }
}

/// How `GTDReducer.apply` treats commands whose goal already holds.
public enum ApplyMode: Sendable, Hashable {
    /// A user action on the device: every rule is an error.
    case interactive
    /// Re-running queued commands on top of newer server state: commands whose
    /// goal already holds report `.alreadySatisfied`, creating a project or
    /// tag whose normalized name is taken merges into the existing one, and a
    /// task creation or edit drops what the task can no longer take (an
    /// archived project, a deleted tag, a waiting note outside Waiting) and
    /// keeps the rest (`GTDReducer.replayable(_:in:)`).
    case replay
}

public enum ApplyOutcome: Hashable, Sendable {
    case applied
    case alreadySatisfied
    case mergedProject(into: ProjectID)
    case mergedTag(into: TagID)
}
