import BrainBuddyCore
import SwiftUI

/// The task card (boards 13 to 20): task detail as a half sheet over the list,
/// with the grabber, at the medium detent first and pulled up to large for
/// the rest of the detail (properties, comments). `AppRouter` presents it for
/// every place that opens a task.
///
/// It has its own navigation stack for the toolbar (Close, the task's menu,
/// the keyboard's Done); nothing is pushed onto it. Its toasts show inside the
/// sheet (`TaskDetailScreen` hosts them above its bar), where the tab's toast
/// host is covered.
struct TaskSheet: View {
    private let taskID: TaskID

    @State private var detent: PresentationDetent = .medium
    /// A regular-width sheet (iPad) has no detents: it is always full.
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    init(taskID: TaskID) {
        self.taskID = taskID
    }

    var body: some View {
        NavigationStack {
            TaskDetailScreen(taskID: taskID, isExpanded: detent == .large || horizontalSizeClass == .regular)
        }
        .toastMagicTap()
        .presentationDetents([.medium, .large], selection: $detent)
        .presentationDragIndicator(.visible)
    }
}

/// Closes the task sheet; the toolbar's leading item, also for VoiceOver and
/// keyboard users, who cannot drag the grabber.
struct TaskSheetCloseButton: View {
    @Environment(AppRouter.self) private var router

    var body: some View {
        Button {
            router.closeTask()
        } label: {
            Label("Close", systemImage: "xmark")
        }
    }
}
