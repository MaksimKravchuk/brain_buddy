import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

extension View {
    /// Row actions for a task in any list: a leading swipe to complete (or to
    /// reopen a completed or cancelled task), a trailing swipe to move or
    /// cancel, and a context menu with every transition the task allows.
    ///
    /// Mirrors ADR-0006: an open task moves only to a *different* open list and
    /// can be completed or cancelled; only a terminal task can be reopened, and
    /// always into an explicitly chosen list. Invalid transitions are never
    /// offered. Moving to Waiting for and reopening present a sheet, because
    /// both need more input (who or what, and where to).
    func taskActions(_ task: TaskRecord) -> some View {
        modifier(TaskActionsModifier(task: task))
    }
}

private struct TaskActionsModifier: ViewModifier {
    let task: TaskRecord

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @State private var isMoving = false
    @State private var moveInitialList: OpenList?
    @State private var isReopening = false

    func body(content: Content) -> some View {
        content
            .swipeActions(edge: .leading, allowsFullSwipe: true) { leadingActions }
            .swipeActions(edge: .trailing, allowsFullSwipe: false) { trailingActions }
            .contextMenu { TaskTransitionMenuItems(task: task, onMove: requestMove, onComplete: complete, onCancel: cancel, onReopen: requestReopen) }
            .sheet(isPresented: $isMoving) {
                MoveSheet(task: task, initialList: moveInitialList)
            }
            .sheet(isPresented: $isReopening) {
                ReopenSheet(task: task)
            }
    }

    @ViewBuilder private var leadingActions: some View {
        if task.isOpen {
            Button(action: complete) {
                Label("Complete", systemImage: "checkmark.circle")
            }
            .tint(.green)
        } else {
            Button(action: requestReopen) {
                Label("Reopen", systemImage: "arrow.uturn.backward.circle")
            }
            .tint(.accentColor)
        }
    }

    @ViewBuilder private var trailingActions: some View {
        if task.isOpen {
            Button {
                requestMove(nil)
            } label: {
                Label("Move", systemImage: "arrow.right.circle")
            }
            .tint(.indigo)
            Button(action: cancel) {
                Label("Cancel task", systemImage: "xmark.circle")
            }
            .tint(.gray)
        }
    }

    /// A direct move for Inbox, Next actions and Someday / maybe; Waiting for
    /// (or no list yet, from the swipe) opens the sheet.
    private func requestMove(_ list: OpenList?) {
        if let list, list != .waiting {
            _ = TaskCommandRunner.run(toasts) { () throws(GTDValidationError) in
                try TaskListMover.move(task, to: list, waitingFor: nil, workspace: workspace, toasts: toasts)
            }
        } else {
            moveInitialList = list
            isMoving = true
        }
    }

    private func requestReopen() {
        isReopening = true
    }

    private func complete() {
        TaskCommandRunner.complete(task, workspace: workspace, toasts: toasts)
    }

    private func cancel() {
        TaskCommandRunner.cancel(task, workspace: workspace, toasts: toasts)
    }
}

/// The transitions a task allows, as menu items. Used by the row context menu
/// and the task detail screen so both always offer the same set.
struct TaskTransitionMenuItems: View {
    let task: TaskRecord
    /// Called with the chosen list; `.waiting` must ask who or what first.
    let onMove: (OpenList?) -> Void
    let onComplete: () -> Void
    let onCancel: () -> Void
    let onReopen: () -> Void

    var body: some View {
        if let current = task.openList {
            Menu {
                ForEach(OpenList.allCases.filter { $0 != current }) { list in
                    Button {
                        onMove(list)
                    } label: {
                        Label(list == .waiting ? "\(list.title)…" : list.title, systemImage: list.symbolName)
                    }
                }
            } label: {
                Label("Move to", systemImage: "arrow.right.circle")
            }
            Button(action: onComplete) {
                Label("Complete", systemImage: "checkmark.circle")
            }
            Button(action: onCancel) {
                Label("Cancel task", systemImage: "xmark.circle")
            }
        } else {
            Button(action: onReopen) {
                Label("Reopen into…", systemImage: "arrow.uturn.backward.circle")
            }
        }
    }
}

/// Moves and reopens with an Undo toast. The throwing forms let sheets show a
/// rejected change inline; list rows wrap them in `TaskCommandRunner.run`.
@MainActor
enum TaskListMover {
    /// Moves an open task to another open list and offers Undo back to the
    /// list it came from (restoring its waiting note when that was Waiting for).
    static func move(
        _ task: TaskRecord, to list: OpenList, waitingFor: String?, workspace: Workspace, toasts: ToastCenter
    ) throws(GTDValidationError) {
        guard let origin = task.openList else { throw .taskNotOpen }
        let originWaitingFor = task.waitingFor
        try workspace.moveTask(task.id, to: list, waitingFor: list == .waiting ? waitingFor : nil)
        toasts.show("Moved to \(list.title)", actionTitle: "Undo") {
            _ = TaskCommandRunner.run(toasts) { () throws(GTDValidationError) in
                try workspace.moveTask(task.id, to: origin, waitingFor: origin == .waiting ? originWaitingFor : nil)
            }
        }
    }

    /// Reopens a completed or cancelled task into `list` and offers Undo,
    /// which completes or cancels it again.
    static func reopen(
        _ task: TaskRecord, to list: OpenList, waitingFor: String?, workspace: Workspace, toasts: ToastCenter
    ) throws(GTDValidationError) {
        guard task.state.isTerminal else { throw .taskNotClosed }
        let wasCancelled = task.state == .cancelled
        try workspace.reopenTask(task.id, to: list, waitingFor: list == .waiting ? waitingFor : nil)
        toasts.show("Reopened in \(list.title)", actionTitle: "Undo") {
            _ = TaskCommandRunner.run(toasts) { () throws(GTDValidationError) in
                if wasCancelled {
                    try workspace.cancelTask(task.id)
                } else {
                    try workspace.completeTask(task.id)
                }
            }
        }
    }
}
