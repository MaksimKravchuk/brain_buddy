import BrainBuddyCore
import Foundation

/// A Done, Cancel or move made in the main window, which Edit › Undo (⌘Z) takes back: the task
/// returns to the open list it left, with the Waiting reason it had there. Text fields keep their
/// own typing undo; this covers the list changes, as the web's ⌘Z does for its Undo toast.
package struct TaskListChange: Equatable, Sendable {
    package let taskID: TaskID
    package let previousList: TaskList
    package let previousWaitingFor: String?
    package let resultingState: TaskState

    /// `nil` when nothing moved: the task was not in an open list before, or is still where it was.
    package init?(before: TaskRecord, after: TaskRecord?) {
        guard let previousList = before.openList, let after, after.id == before.id, after.state != before.state else {
            return nil
        }
        taskID = before.id
        self.previousList = previousList
        previousWaitingFor = previousList == .waiting ? before.waitingFor : nil
        resultingState = after.state
    }

    /// The Edit menu reads "Undo <actionName>" (sentence case, like the menu items we own).
    package var actionName: String {
        switch resultingState {
        case .completed: "Done"
        case .cancelled: "Cancel task"
        default: "Move to \(resultingState.openList?.title ?? "list")"
        }
    }
}

extension BrainBuddyModel {
    /// Takes `change` back when the task is still where the change left it; otherwise says so and
    /// changes nothing.
    @discardableResult
    package func undo(_ change: TaskListChange) async -> Bool {
        guard let task = task(change.taskID), task.state == change.resultingState else {
            error = "This task has changed since, so there is nothing to undo."
            return false
        }
        if task.state.isTerminal {
            return await reopenTask(change.taskID, to: change.previousList, waitingFor: change.previousWaitingFor)
        }
        return await moveTask(change.taskID, to: change.previousList, waitingFor: change.previousWaitingFor)
    }
}
