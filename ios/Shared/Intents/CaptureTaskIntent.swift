import AppIntents
import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation

/// "Add to Brain Buddy": captures one task into the shared store, fully
/// offline, from Siri, Shortcuts, Spotlight and the Action button. The text
/// takes Smart Add tokens (`#tag`, `@project`, `@"Two words"`), resolved on
/// the device; projects and tags that don't exist yet are created.
///
/// It runs without opening the app (`openAppWhenRun` keeps its default, false).
struct CaptureTaskIntent: AppIntent {
    static let title: LocalizedStringResource = "Add to Brain Buddy"

    static let description = IntentDescription(
        "Captures a task, even offline. Add #tag or @project to the text to file it as you type."
    )

    @Parameter(
        title: "Task",
        description: "What to capture. #tag and @project are applied, and new ones are created.",
        requestValueDialog: "What do you want to capture?"
    )
    var text: String

    @Parameter(title: "List", default: .inbox)
    var list: OpenListAppEnum

    @Parameter(title: "Waiting for", description: "Who or what you're waiting on. Needed for Waiting for.")
    var waitingFor: String?

    @Parameter(title: "Notes")
    var notes: String?

    @Parameter(title: "Due date")
    var dueDate: Date?

    static var parameterSummary: some ParameterSummary {
        Summary("Add \(\.$text) to \(\.$list)")
    }

    init() {}

    init(text: String, list: OpenListAppEnum = .inbox, waitingFor: String? = nil) {
        self.text = text
        self.list = list
        self.waitingFor = waitingFor
    }

    @MainActor
    func perform() async throws -> some IntentResult & ReturnsValue<TaskEntity> & ProvidesDialog {
        let destination = list.openList
        let waiting = waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        // Waiting for needs a person or thing; ask for it rather than fail.
        if destination == .waiting, waiting.isEmpty {
            throw $waitingFor.needsValueError("Who or what are you waiting on?")
        }

        let workspace = await SharedWorkspace.make()
        try SharedWorkspace.requireLoaded(workspace)

        let draft = CaptureDraft(
            text: text,
            list: destination,
            waitingFor: destination == .waiting ? waiting : "",
            details: notes ?? "",
            dueDate: dueDate.map { CalendarDay(date: $0) }
        )
        let taskID: TaskID
        do throws(GTDValidationError) {
            taskID = try workspace.capture(draft)
        } catch {
            throw BrainBuddyIntentError(error)
        }
        try await SharedWorkspace.didWrite(workspace)

        guard let record = workspace.task(taskID) else {
            throw BrainBuddyIntentError(.taskNotFound)
        }
        return .result(value: TaskEntity(record: record), dialog: "Added to \(destination.title).")
    }
}
