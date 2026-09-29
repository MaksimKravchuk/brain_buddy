import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Moves an open task to another open list. The task's current list is not
/// offered (ADR-0006: a move needs a different list). Waiting for asks who or
/// what the task is waiting on before the move is allowed.
struct MoveSheet: View {
    private let task: TaskRecord

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    @State private var destination: OpenList?
    @State private var waitingFor = ""
    @State private var errorMessage: String?

    /// `initialList` preselects a destination, for example Waiting for chosen
    /// from a context menu.
    init(task: TaskRecord, initialList: OpenList? = nil) {
        self.task = task
        _destination = State(initialValue: initialList == task.openList ? nil : initialList)
    }

    private var choices: [OpenList] {
        OpenList.allCases.filter { $0 != task.openList }
    }

    private var canMove: Bool {
        guard let destination else { return false }
        return destination != .waiting || WaitingForInput.problem(waitingFor) == nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(task.title)
                        .font(.headline)
                        .lineLimit(3)
                } footer: {
                    if let current = task.openList {
                        Text("Now in \(current.title)")
                    }
                }
                Picker("Move to", selection: $destination) {
                    ForEach(choices) { list in
                        Label(list.title, systemImage: list.symbolName)
                            .tag(Optional(list))
                    }
                }
                .pickerStyle(.inline)
                if destination == .waiting {
                    WaitingForSection(text: $waitingFor)
                }
                if let errorMessage {
                    Section {
                        InlineProblemText(message: errorMessage)
                    }
                }
            }
            .navigationTitle("Move task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Move", action: move)
                        .disabled(!canMove)
                }
            }
            .onChange(of: destination) { _, _ in errorMessage = nil }
        }
        .presentationDetents([.medium, .large])
    }

    private func move() {
        guard let destination else { return }
        let current = workspace.task(self.task.id) ?? self.task
        do {
            try TaskListMover.move(current, to: destination, waitingFor: waitingFor, workspace: workspace, toasts: toasts)
            dismiss()
        } catch {
            errorMessage = error.message
        }
    }
}

/// The "Waiting for" field used wherever a task enters Waiting for: moving,
/// reopening, capturing and processing the inbox. It takes focus when it
/// appears, because the move can't happen until it is filled in.
struct WaitingForSection: View {
    @Binding var text: String
    @FocusState private var isFocused: Bool

    init(text: Binding<String>) {
        _text = text
    }

    var body: some View {
        Section {
            TextField("Who or what are you waiting on?", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .textInputAutocapitalization(.sentences)
                .focused($isFocused)
                .accessibilityLabel("Waiting for")
                .onAppear { isFocused = true }
        } header: {
            Text("Waiting for")
        } footer: {
            WaitingForFooter(text: text)
        }
    }
}

/// Explains the rule, then the problem once the person has typed something.
struct WaitingForFooter: View {
    let text: String

    var body: some View {
        let count = text.trimmingCharacters(in: .whitespacesAndNewlines).count
        if count > GTDLimits.waitingFor {
            InlineProblemText(message: GTDValidationError.waitingForTooLong.message)
        } else {
            Text("Name the person, event or condition you are waiting on.")
        }
    }
}

/// Client-side checks for a waiting note, matching the reducer's messages so
/// buttons can be disabled before the command is even tried.
enum WaitingForInput {
    static func problem(_ text: String) -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return GTDValidationError.waitingForRequired.message }
        if trimmed.count > GTDLimits.waitingFor { return GTDValidationError.waitingForTooLong.message }
        return nil
    }
}

/// A rejected change, stated in words with an icon so it never relies on colour.
struct InlineProblemText: View {
    let message: String

    var body: some View {
        Label {
            Text(message)
        } icon: {
            Image(systemName: "exclamationmark.circle")
                .accessibilityHidden(true)
        }
        .font(.footnote)
        .foregroundStyle(BBColor.dangerText)
        .accessibilityElement(children: .combine)
    }
}
