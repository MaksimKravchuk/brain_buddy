import BrainBuddyMacCore
import SwiftUI

/// View › "Close task details" ⌘\: closes the task open beside the list, as ⌘\ does on the web.
/// Pending edits save first, the same as choosing another task. Disabled with no task open.
struct TaskDetailsCommands: Commands {
    @FocusedValue(\.closeTaskDetails) private var closeTaskDetails

    @FocusedValue(\.handOffSelectedStep) private var handOffSelectedStep

    var body: some Commands {
        CommandGroup(after: .sidebar) {
            Button("Close task details") { closeTaskDetails?.close() }
                .keyboardShortcut("\\", modifiers: [.command])
                .disabled(closeTaskDetails == nil)
            // The keyboard entry to the hand-off sheet (030-FR-040): no shortcut, the menu is the way in.
            Button(AgentsCopy.handOff) { handOffSelectedStep?.open() }
                .disabled(handOffSelectedStep == nil)
        }
    }
}

/// Opens the hand-off sheet for the selected step; present only where the inspector's button is enabled.
struct HandOffSelectedStepAction {
    let open: () -> Void
}

private struct HandOffSelectedStepKey: FocusedValueKey {
    typealias Value = HandOffSelectedStepAction
}

extension FocusedValues {
    var handOffSelectedStep: HandOffSelectedStepAction? {
        get { self[HandOffSelectedStepKey.self] }
        set { self[HandOffSelectedStepKey.self] = newValue }
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
