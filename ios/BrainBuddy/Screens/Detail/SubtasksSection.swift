import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// A task's subtasks inside task detail: tap the circle to complete or
/// reopen, rename inline (saved on Return or when the field loses focus),
/// cancel or reopen from the row menu, and add new ones at the bottom.
/// State is shown by symbol and strikethrough as well as colour, and spoken.
struct SubtasksSection: View {
    private let task: TaskRecord
    private let isReadOnly: Bool

    @Environment(Workspace.self) private var workspace
    @State private var newTitle = ""
    @State private var errorMessage: String?
    @FocusState private var isAdding: Bool

    init(task: TaskRecord, isReadOnly: Bool = false) {
        self.task = task
        self.isReadOnly = isReadOnly
    }

    private var subtasks: [SubtaskRecord] {
        task.subtasks.sorted { ($0.orderKey, $0.id) < ($1.orderKey, $1.id) }
    }

    var body: some View {
        if !(isReadOnly && subtasks.isEmpty) {
            Section {
                ForEach(subtasks) { subtask in
                    DetailSubtaskRow(taskID: task.id, subtask: subtask, isReadOnly: isReadOnly) { message in
                        errorMessage = message
                    }
                }
                if !isReadOnly {
                    addRow
                }
            } header: {
                BBSectionHeader(header)
            } footer: {
                if let errorMessage {
                    InlineProblemText(message: errorMessage)
                }
            }
        }
    }

    private var header: String {
        let done = subtasks.filter { $0.state == .completed }.count
        let counted = subtasks.filter { $0.state != .cancelled }.count
        return counted == 0 ? "Subtasks" : "Subtasks · \(done) of \(counted) done"
    }

    private var addRow: some View {
        Label {
            TextField("Add a subtask", text: $newTitle)
                .focused($isAdding)
                .submitLabel(.done)
                .onSubmit { Task { await add() } }
                .accessibilityLabel("New subtask")
        } icon: {
            Image(systemName: "plus")
                .accessibilityHidden(true)
        }
        .labelStyle(.bbRow)
        .frame(minHeight: BBMetrics.rowMinHeight)
    }

    @MainActor private func add() async {
        let title = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return }
        do {
            try await workspace.addSubtask(to: task.id, title: title, editorID: UUID().uuidString)
            newTitle = ""
            errorMessage = nil
            // Keep the keyboard up for the next one.
            isAdding = true
        } catch {
            errorMessage = error.message
        }
    }
}

private struct DetailSubtaskRow: View {
    let taskID: TaskID
    let subtask: SubtaskRecord
    let isReadOnly: Bool
    let onProblem: (String?) -> Void

    @Environment(Workspace.self) private var workspace
    @State private var title: String
    @FocusState private var isEditing: Bool
    /// The state symbol sits in the same icon column as the rows above.
    @ScaledMetric(relativeTo: .body) private var iconColumn: CGFloat = BBMetrics.iconColumn

    init(taskID: TaskID, subtask: SubtaskRecord, isReadOnly: Bool, onProblem: @escaping (String?) -> Void) {
        self.taskID = taskID
        self.subtask = subtask
        self.isReadOnly = isReadOnly
        self.onProblem = onProblem
        _title = State(initialValue: subtask.title)
    }

    private var isOpen: Bool { subtask.state == .open }

    var body: some View {
        HStack(spacing: BBSpacing.s3) {
            Button(action: toggle) {
                // The symbol takes the 24 pt icon column; the padding grows the
                // hit target to 44 pt and the negative padding below gives that
                // width back to the layout, so the title lines up with the
                // property rows above.
                Image(systemName: symbol)
                    .font(.title3)
                    .foregroundStyle(isOpen ? BBColor.textTertiary : BBColor.brandText)
                    .frame(width: iconColumn, height: BBMetrics.rowMinHeight)
                    .padding(.horizontal, (BBMetrics.rowMinHeight - iconColumn) / 2)
                    .contentShape(Rectangle())
            }
            .padding(.horizontal, -(BBMetrics.rowMinHeight - iconColumn) / 2)
            .buttonStyle(.borderless)
            .disabled(isReadOnly)
            .accessibilityLabel(subtask.title)
            .accessibilityValue(stateName)
            .accessibilityHint(isOpen ? "Completes the subtask." : "Reopens the subtask.")

            if isOpen && !isReadOnly {
                TextField("Subtask", text: $title, axis: .vertical)
                    .focused($isEditing)
                    .submitLabel(.done)
                    .onSubmit { isEditing = false }
                    .onChange(of: title) { _, newValue in
                        if newValue.contains(where: \.isNewline) {
                            title = newValue.split(whereSeparator: \.isNewline).joined(separator: " ")
                            isEditing = false
                        }
                    }
                    .accessibilityLabel("Subtask title")
            } else {
                VStack(alignment: .leading, spacing: 2) {
                    Text(subtask.title)
                        .strikethrough(!isOpen)
                        .foregroundStyle(isOpen ? Color.primary : Color.secondary)
                    if subtask.state == .cancelled {
                        Text("Cancelled")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .accessibilityElement(children: .combine)
            }

            Spacer(minLength: 0)

            if !isReadOnly {
                Menu {
                    ForEach(availableActions, id: \.self) { action in
                        Button {
                            Task { await transition(action) }
                        } label: {
                            Label(Self.title(for: action), systemImage: Self.symbol(for: action))
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis")
                        .frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .menuStyle(.button)
                .buttonStyle(.borderless)
                .accessibilityLabel("More for \(subtask.title)")
            }
        }
        .onChange(of: isEditing) { _, editing in
            if !editing { commitRename() }
        }
        .onChange(of: subtask.title) { _, newValue in
            if !isEditing { title = newValue }
        }
        .onDisappear { commitRename() }
    }

    private var symbol: String {
        switch subtask.state {
        case .open: "circle"
        case .completed: "checkmark.circle.fill"
        case .cancelled: "xmark.circle"
        }
    }

    private var stateName: String {
        switch subtask.state {
        case .open: "Open"
        case .completed: "Completed"
        case .cancelled: "Cancelled"
        }
    }

    /// Every transition to a different state (the reducer rejects same-state ones).
    private var availableActions: [SubtaskTransitionAction] {
        let all: [SubtaskTransitionAction] = [.complete, .reopen, .cancel]
        return all.filter { $0.targetState != subtask.state }
    }

    private static func title(for action: SubtaskTransitionAction) -> String {
        switch action {
        case .complete: "Complete"
        case .reopen: "Reopen"
        case .cancel: "Cancel subtask"
        }
    }

    private static func symbol(for action: SubtaskTransitionAction) -> String {
        switch action {
        case .complete: "checkmark.circle"
        case .reopen: "arrow.uturn.backward.circle"
        case .cancel: "xmark.circle"
        }
    }

    private func toggle() {
        Task { await transition(isOpen ? .complete : .reopen) }
    }

    @MainActor private func transition(_ action: SubtaskTransitionAction) async {
        await commitRename()
        do {
            try await workspace.transitionSubtask(subtask.id, in: taskID, action, editorID: UUID().uuidString)
            onProblem(nil)
        } catch {
            onProblem(error.message)
        }
    }

    @MainActor private func commitRename() async {
        guard isOpen, !isReadOnly else { return }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed != subtask.title else { return }
        guard !trimmed.isEmpty else {
            title = subtask.title
            return
        }
        do {
            try await workspace.renameSubtask(subtask.id, in: taskID, to: trimmed, editorID: UUID().uuidString)
            title = trimmed
            onProblem(nil)
        } catch {
            title = subtask.title
            onProblem(error.message)
        }
    }
}
