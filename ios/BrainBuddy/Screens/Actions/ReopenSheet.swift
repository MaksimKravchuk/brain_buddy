import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Reopens a completed or cancelled task into an explicitly chosen open list
/// (ADR-0006). The list it was in before is preselected when this device
/// knows it, otherwise Next actions. Waiting for asks who or what first.
struct ReopenSheet: View {
    private let task: TaskRecord

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    @State private var destination: OpenList
    @State private var waitingFor: String
    @State private var errorMessage: String?
    @State private var isSaving = false
    @State private var editorID = UUID().uuidString

    init(task: TaskRecord, initialList: OpenList? = nil) {
        self.task = task
        _destination = State(initialValue: initialList ?? task.lastOpenList ?? .next)
        _waitingFor = State(initialValue: task.waitingFor ?? "")
    }

    private var canReopen: Bool {
        destination != .waiting || WaitingForInput.problem(waitingFor) == nil
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(task.title)
                        .font(.headline)
                        .lineLimit(3)
                } footer: {
                    Text(statusLine)
                }
                Picker("Reopen into", selection: $destination) {
                    ForEach(OpenList.allCases) { list in
                        Label(list.title, systemImage: list.symbolName)
                            .tag(list)
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
            .navigationTitle("Reopen task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Reopen") { Task { await reopen() } }
                        .disabled(!canReopen || isSaving)
                }
            }
            .onChange(of: destination) { _, _ in errorMessage = nil }
        }
        .presentationDetents([.medium, .large])
    }

    private var statusLine: String {
        let state = task.state == .cancelled ? "Cancelled" : "Completed"
        guard let previous = task.lastOpenList else { return state }
        return "\(state) · previously in \(previous.title)"
    }

    @MainActor private func reopen() async {
        let current = self.task
        isSaving = true
        defer { isSaving = false }
        do {
            try await TaskListMover.reopen(current, to: destination, waitingFor: waitingFor, workspace: workspace, toasts: toasts, editorID: editorID)
            dismiss()
        } catch {
            errorMessage = error.message
        }
    }
}
