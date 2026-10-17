import SwiftUI

/// Commands remain available with M01's toolbar hidden and M07's board-sized action set.
struct WorkspaceMenuCommands: Commands {
    @FocusedValue(\.workspaceCommands) private var actions

    var body: some Commands {
        CommandGroup(replacing: .newItem) {
            Group {
                Button("New step") { actions?.newStep() }
                    .keyboardShortcut("n", modifiers: .command)
                Button("Quick Open…") { actions?.quickOpen() }
                    .keyboardShortcut("o", modifiers: .command)
                Button("Quick Capture") { actions?.quickCapture() }
                    .keyboardShortcut("b", modifiers: [.control, .option, .shift])
                Button("Voice to task draft…") { actions?.voice() }
                Divider()
                Button("New tag") { actions?.newTag() }
                Button("New project…") { actions?.newProject() }
                Button("Review projects…") { actions?.reviewProjects() }
            }
            .disabled(actions == nil)
        }
        CommandGroup(after: .textEditing) {
            Menu("Find") {
                Button("Search tasks…") { actions?.search() }
                    .keyboardShortcut("f", modifiers: .command)
            }
            .disabled(actions == nil)
        }

    }
}

struct WorkspaceCommandsAction {
    let newStep: () -> Void
    let quickOpen: () -> Void
    let quickCapture: () -> Void
    let voice: () -> Void
    let search: () -> Void
    let newTag: () -> Void
    let newProject: () -> Void
    let reviewProjects: () -> Void

    /// A previously captured menu callback must not replace a live collection draft.
    static func beginCollection<Kind>(_ kind: Kind, presented: inout Kind?, name: inout String, isBusy: Bool) {
        guard !isBusy, presented == nil else { return }
        name = ""
        presented = kind
    }
}

private struct WorkspaceCommandsKey: FocusedValueKey {
    typealias Value = WorkspaceCommandsAction
}

extension FocusedValues {
    var workspaceCommands: WorkspaceCommandsAction? {
        get { self[WorkspaceCommandsKey.self] }
        set { self[WorkspaceCommandsKey.self] = newValue }
    }
}
