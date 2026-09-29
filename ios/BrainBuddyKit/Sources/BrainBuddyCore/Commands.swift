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

    public struct CreateProject: Hashable, Sendable, Codable {
        public var projectID: ProjectID
        public var name: String
        public var color: String?
        public init(projectID: ProjectID, name: String, color: String? = nil) {
            self.projectID = projectID
            self.name = name
            self.color = color
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
        public init(
            taskID: TaskID, title: String, details: String? = nil, list: OpenList,
            waitingFor: String? = nil, dueDate: CalendarDay? = nil, priority: TaskPriority = .none,
            projectID: ProjectID? = nil, tagIDs: [TagID] = []
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
        }
    }

    public struct UpdateTask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var changes: TaskChanges
        public init(taskID: TaskID, changes: TaskChanges) {
            self.taskID = taskID
            self.changes = changes
        }
    }

    /// `toList` is required for `move` and `reopen` and ignored otherwise;
    /// `waitingFor` is required when the destination is Waiting.
    public struct TransitionTask: Hashable, Sendable, Codable {
        public var taskID: TaskID
        public var action: TaskTransitionAction
        public var toList: OpenList?
        public var waitingFor: String?
        public init(taskID: TaskID, action: TaskTransitionAction, toList: OpenList? = nil, waitingFor: String? = nil) {
            self.taskID = taskID
            self.action = action
            self.toList = toList
            self.waitingFor = waitingFor
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
