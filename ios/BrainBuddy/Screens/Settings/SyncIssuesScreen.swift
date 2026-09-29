import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import SwiftUI
import UIKit

/// Local changes the server rejected. Each one says what was attempted, why
/// it failed, and a reference ID to quote when reporting it.
struct SyncIssuesScreen: View {
    @Environment(Workspace.self) private var workspace

    init() {}

    var body: some View {
        let issues = workspace.issues.sorted { $0.occurredAt > $1.occurredAt }
        Group {
            if issues.isEmpty {
                EmptyStateView(
                    title: "No sync issues",
                    message: "Changes the server can't apply show up here.",
                    systemImage: "checkmark.circle"
                )
            } else {
                List {
                    Section {
                        ForEach(issues) { issue in
                            row(issue)
                        }
                    } header: {
                        Text(explanation)
                            .textCase(nil)
                    }
                }
            }
        }
        .navigationTitle("Sync issues")
    }

    private func row(_ issue: SyncIssue) -> some View {
        SyncIssueRow(issue: issue, summary: Self.describe(issue.command, in: workspace.state))
            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                Button {
                    workspace.dismissIssue(issue.id)
                } label: {
                    Label("Dismiss", systemImage: "xmark")
                }
            }
            .contextMenu {
                if let referenceID = issue.referenceID {
                    Button {
                        UIPasteboard.general.string = referenceID
                    } label: {
                        Label("Copy reference ID", systemImage: "doc.on.doc")
                    }
                }
                Button {
                    workspace.dismissIssue(issue.id)
                } label: {
                    Label("Dismiss", systemImage: "xmark")
                }
            }
    }

    private var explanation: String {
        if workspace.pendingChangeCount > 0 {
            return "These changes couldn't be applied on the server. Your other changes still sync as usual."
        }
        return "These changes couldn't be applied on the server. Your other changes are synced."
    }
}

private struct SyncIssueRow: View {
    let issue: SyncIssue
    let summary: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(summary)
                .font(.body.weight(.medium))
            Text(issue.message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
            if let referenceID = issue.referenceID {
                Text("Reference ID: \(referenceID)")
                    .font(.footnote.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
            Text(issue.occurredAt.formatted(date: .abbreviated, time: .shortened))
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Pure helpers (no SwiftUI)

extension SyncIssuesScreen {
    /// A short, human description of a queued command, for example
    /// "Complete “Buy milk”" or "Rename project “Work” to “Home”". Names come
    /// from `state` when the record still exists, else a generic noun.
    static func describe(_ command: GTDCommand, in state: GTDState) -> String {
        switch command {
        case .createProject(let create):
            return "Create project \(quote(create.name))"
        case .updateProject(let update):
            return describeProjectUpdate(update, in: state)
        case .archiveProject(let id):
            return "Archive \(projectPhrase(id, in: state))"
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
    static func quote(_ text: String) -> String {
        let singleLine = text.replacingOccurrences(of: "\n", with: " ")
        let limit = 60
        let clipped = singleLine.count > limit ? String(singleLine.prefix(limit - 1)) + "…" : singleLine
        return "“\(clipped)”"
    }
}
