import BrainBuddyCore
import SwiftUI

/// A row that opens its task in the task sheet (`AppRouter.presentTask`),
/// where a `NavigationLink` used to push task detail. Plain, so the row keeps
/// its own look and the completion mark inside it stays its own button; apply
/// `bbCardRow()`, `taskActions(_:)` and the like to this view, as to the link.
struct TaskOpenButton<Label: View>: View {
    private let taskID: TaskID
    private let label: Label

    @Environment(AppRouter.self) private var router

    init(_ taskID: TaskID, @ViewBuilder label: () -> Label) {
        self.taskID = taskID
        self.label = label()
    }

    var body: some View {
        Button {
            router.presentTask(taskID)
        } label: {
            label
        }
        .buttonStyle(.plain)
        .accessibilityHint("Opens the task.")
    }
}
