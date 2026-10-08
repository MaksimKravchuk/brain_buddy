import Foundation

/// One sync issue in words: what was attempted, why it did not happen, the
/// reference id to quote, and (for a merge that kept the account's desired
/// outcome) the local outcome in full.
public struct SyncIssueDescription: Hashable, Sendable {
    public var attempted: String
    public var why: String
    public var referenceID: String?
    /// Never clipped: the person may need to copy it.
    public var keptOutcome: String?

    public init(attempted: String, why: String, referenceID: String? = nil, keptOutcome: String? = nil) {
        self.attempted = attempted
        self.why = why
        self.referenceID = referenceID
        self.keptOutcome = keptOutcome
    }
}

/// The words for a sync issue, shared by the iPhone's Sync issues screen and the
/// Mac's status popover (contracts/kit-commands.md §5). The reason is the issue's
/// `message`, which the engine writes with the copy below; names come from
/// `state` when the record still exists, else a generic noun.
public enum SyncIssueDescriber {
    public static func describe(_ issue: SyncIssue, in state: GTDState) -> SyncIssueDescription {
        if case .setProjectOutcome(let id, let outcome) = issue.command, issue.message == GTDValidationError.outcomeKept.message {
            return SyncIssueDescription(
                attempted: "Desired outcome for \(quote(state.projects[id]?.name ?? "this project"))", why: issue.message,
                referenceID: issue.referenceID, keptOutcome: outcome
            )
        }
        return SyncIssueDescription(
            attempted: describe(issue.command, in: state), why: issue.message, referenceID: issue.referenceID
        )
    }

    // MARK: Reasons the engine writes

    public static let keptRejecting = "The server kept rejecting this change."

    /// Archive and unarchive say what state the project is left in; any other command keeps `keptRejecting`.
    public static func keptRejecting(_ command: GTDCommand) -> String {
        switch command {
        case .unarchiveProject: "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later."
        case .archiveProject: "Brain Buddy couldn't archive it, so it's still active. Try again later."
        default: keptRejecting
        }
    }

    /// An unarchive the server refused because an active project has the name; `count` queued
    /// captures were kept without the project.
    public static func unarchiveNameInUse(_ name: String, keptWithoutProject count: Int) -> String {
        let reason = "Another active project is already called “\(name)”."
        guard count > 0 else { return reason }
        let tasks = count == 1 ? "1 task you added to it was" : "\(count) tasks you added to it were"
        return "\(reason) \(tasks) kept without a project."
    }

    /// An archive answered as a server older than ADR-0020 answers it.
    public static func serverStillClears(project name: String) -> String {
        "Your account's server is out of date, so archiving \(quote(name)) removed its tasks from the project."
    }

    /// A task that was added without its project because the project was archived elsewhere.
    public static func archivedElsewhere(project name: String) -> String {
        "Project \(quote(name)) was archived on another device, so the task was added without a project."
    }

    /// Defensive: no client deletes a task, so this is reachable only through a foreign or purged record.
    public static func deletedElsewhere(task title: String) -> String {
        "Couldn't save your change to \(quote(title)): it was deleted on another device."
    }

    // MARK: What was attempted

    /// A short, human description of a queued command, for example
    /// "Complete “Buy milk”" or "Rename project “Work” to “Home”".
    public static func describe(_ command: GTDCommand, in state: GTDState) -> String {
        switch command {
        case .createProject(let create):
            return "Create project \(quote(create.name))"
        case .updateProject(let update):
            return describeProjectUpdate(update, in: state)
        case .archiveProject(let id):
            return "Archive \(projectPhrase(id, in: state))"
        case .unarchiveProject(let id):
            return "Unarchive \(projectPhrase(id, in: state))"
        case .setProjectOutcome(let id, _):
            return "Change the desired outcome of \(quote(state.projects[id]?.name ?? "this project"))"
        case .createTag(let create):
            return "Create tag #\(create.name)"
        case .renameTag(let rename):
            if let old = state.tags[rename.tagID]?.name, old != rename.name {
                return "Rename #\(old) to #\(rename.name)"
            }
            return "Rename tag to #\(rename.name)"
        case .deleteTag(let id):
            return "Delete \(tagPhrase(id, in: state))"
        case .createTask(let create):
            return "Add \(quote(create.title)) to \(create.list.title)"
        case .updateTask(let update):
            return describeTaskUpdate(update, in: state)
        case .transitionTask(let transition):
            return describeTransition(transition, in: state)
        case .createSubtask(let create):
            return "Add subtask \(quote(create.title)) to \(taskPhrase(create.taskID, in: state))"
        case .updateSubtask(let update):
            return "Rename \(subtaskPhrase(update.subtaskID, of: update.taskID, in: state)) to \(quote(update.title))"
        case .transitionSubtask(let transition):
            let subtask = subtaskPhrase(transition.subtaskID, of: transition.taskID, in: state)
            switch transition.action {
            case .complete: return "Complete \(subtask)"
            case .reopen: return "Reopen \(subtask)"
            case .cancel: return "Cancel \(subtask)"
            }
        case .createComment(let create):
            return "Comment on \(taskPhrase(create.taskID, in: state))"
        case .updateComment(let update):
            return "Edit a comment on \(taskPhrase(update.taskID, in: state))"
        case .decideTask(let decide):
            return "Decide on \(taskPhrase(decide.taskID, in: state))"
        case .undoDecision:
            return "Undo a decision"
        case .autoParkTask(let park):
            return "Move \(taskPhrase(park.taskID, in: state)) to Someday / maybe"
        case .bulkRelease(let release):
            return release.taskIDs.count == 1
                ? "Move 1 task to Someday / maybe" : "Move \(release.taskIDs.count) tasks to Someday / maybe"
        case .undoBulkRelease:
            return "Undo moving tasks to Someday / maybe"
        case .review:
            return "Save weekly review progress"
        }
    }

    private static func describeProjectUpdate(_ update: GTDCommand.UpdateProject, in state: GTDState) -> String {
        let project = projectPhrase(update.projectID, in: state)
        let colorChanged = update.color.isChanged
        if let newName = update.name {
            let rename: String
            if let old = state.projects[update.projectID]?.name, old != newName {
                rename = "Rename project \(quote(old)) to \(quote(newName))"
            } else {
                rename = "Rename project to \(quote(newName))"
            }
            return colorChanged ? "\(rename) and change its colour" : rename
        }
        if update.color == .clear { return "Remove the colour of \(project)" }
        if colorChanged { return "Change the colour of \(project)" }
        return "Edit \(project)"
    }

    private static func describeTaskUpdate(_ update: GTDCommand.UpdateTask, in state: GTDState) -> String {
        let task = taskPhrase(update.taskID, in: state)
        let changes = update.changes
        let changedCount = [
            changes.title.isChanged, changes.details.isChanged, changes.projectID.isChanged,
            changes.tagIDs.isChanged, changes.dueDate.isChanged, changes.priority.isChanged,
            changes.waitingFor.isChanged,
        ].filter { $0 }.count
        guard changedCount == 1 else { return "Edit \(task)" }

        if case .set(let title) = changes.title { return "Rename \(task) to \(quote(title))" }
        if changes.details.isChanged {
            return changes.details == .clear ? "Clear the notes of \(task)" : "Edit the notes of \(task)"
        }
        switch changes.projectID {
        case .set(let projectID): return "Move \(task) to \(projectPhrase(projectID, in: state))"
        case .clear: return "Remove \(task) from its project"
        case .unchanged: break
        }
        if changes.tagIDs.isChanged { return "Change the tags on \(task)" }
        switch changes.dueDate {
        case .set(let day):
            let date = day.startDate().formatted(date: .abbreviated, time: .omitted)
            return "Set the due date of \(task) to \(date)"
        case .clear: return "Remove the due date from \(task)"
        case .unchanged: break
        }
        switch changes.priority {
        case .set(let priority) where priority != TaskPriority.none:
            return "Set the priority of \(task) to \(priority.title.lowercased())"
        case .set, .clear: return "Remove the priority from \(task)"
        case .unchanged: break
        }
        if changes.waitingFor.isChanged { return "Change what \(task) is waiting for" }
        return "Edit \(task)"
    }

    private static func describeTransition(_ transition: GTDCommand.TransitionTask, in state: GTDState) -> String {
        let task = taskPhrase(transition.taskID, in: state)
        switch transition.action {
        case .move:
            guard let list = transition.toList else { return "Move \(task)" }
            return "Move \(task) to \(list.title)"
        case .complete:
            return "Complete \(task)"
        case .cancel:
            return "Cancel \(task)"
        case .reopen:
            guard let list = transition.toList else { return "Reopen \(task)" }
            return "Reopen \(task) in \(list.title)"
        }
    }

    // MARK: Phrases

    private static func taskPhrase(_ id: TaskID, in state: GTDState) -> String {
        guard let task = state.tasks[id] else { return "a task" }
        return quote(task.title)
    }

    private static func projectPhrase(_ id: ProjectID, in state: GTDState) -> String {
        guard let project = state.projects[id] else { return "a project" }
        return "project \(quote(project.name))"
    }

    private static func tagPhrase(_ id: TagID, in state: GTDState) -> String {
        guard let tag = state.tags[id] else { return "a tag" }
        return "#\(tag.name)"
    }

    private static func subtaskPhrase(_ id: SubtaskID, of taskID: TaskID, in state: GTDState) -> String {
        guard let subtask = state.tasks[taskID]?.subtasks.first(where: { $0.id == id }) else { return "a subtask" }
        return "subtask \(quote(subtask.title))"
    }

    /// Curly-quoted, on one line, shortened past 60 characters.
    public static func quote(_ text: String) -> String {
        let singleLine = text.replacingOccurrences(of: "\n", with: " ")
        let limit = 60
        let clipped = singleLine.count > limit ? String(singleLine.prefix(limit - 1)) + "…" : singleLine
        return "“\(clipped)”"
    }
}
