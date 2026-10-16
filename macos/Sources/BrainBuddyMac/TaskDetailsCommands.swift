import SwiftUI

/// View › "Close task details" ⌘\: closes the task open beside the list, as ⌘\ does on the web.
/// Pending edits save first, the same as choosing another task. Disabled with no task open.
struct TaskDetailsCommands: Commands {
    @FocusedValue(\.closeTaskDetails) private var closeTaskDetails

    var body: some Commands {
        CommandGroup(after: .sidebar) {
            Button("Close task details") { closeTaskDetails?.close() }
                .keyboardShortcut("\\", modifiers: [.command])
                .disabled(closeTaskDetails == nil)
        }
    }
}

/// The window's way to close its open task; absent while none is open.
struct CloseTaskDetailsAction {
    let close: () -> Void
}

private struct CloseTaskDetailsKey: FocusedValueKey {
    typealias Value = CloseTaskDetailsAction
}

extension FocusedValues {
    var closeTaskDetails: CloseTaskDetailsAction? {
        get { self[CloseTaskDetailsKey.self] }
        set { self[CloseTaskDetailsKey.self] = newValue }
    }
}
