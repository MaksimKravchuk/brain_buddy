import AppIntents
import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation

/// Completes a task, fully offline. Siri and Shortcuts pick the task through
/// `TaskEntityQuery`; widget rows run it from their completion button, in the
/// widget extension's process.
///
/// It needs an unlocked device: choosing a task lists and reads back task
/// titles, which must not happen on the Lock Screen (or from a widget in
/// StandBy) for whoever is holding the phone.
struct CompleteTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Complete task"

    static let description = IntentDescription("Marks a Brain Buddy task as complete, even offline.")

    static let authenticationPolicy: IntentAuthenticationPolicy = .requiresAuthentication

    @Parameter(title: "Task", requestValueDialog: "Which task did you finish?")
    var task: TaskEntity

    static var parameterSummary: some ParameterSummary {
        Summary("Complete \(\.$task)")
    }

    init() {}

    init(task: TaskEntity) {
        self.task = task
    }

    /// For widget buttons. Only the id is read when the intent runs; the task
    /// itself is looked up in the store then.
    init(taskID: String) {
        self.task = TaskEntity(id: taskID, title: "", listName: "", dueDate: nil)
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        let workspace = await SharedWorkspace.make()
        try SharedWorkspace.requireLoaded(workspace)

        let id = TaskID(task.id)
        guard let record = workspace.task(id) else {
            throw BrainBuddyIntentError(.taskNotFound)
        }
        // A second tap on a widget that hasn't refreshed yet is not an error.
        if record.state == .completed {
            return .result(dialog: "That task is already complete.")
        }
        do {
            try await workspace.completeTask(id, editorID: UUID().uuidString)
        } catch {
            if let validation = error as? GTDValidationError { throw BrainBuddyIntentError(validation) }
            throw BrainBuddyIntentError(message: "Brain Buddy couldn't save this change. Try again.")
        }
        try await SharedWorkspace.didWrite(workspace)
        return .result(dialog: "Completed “\(record.title)”.")
    }
}
