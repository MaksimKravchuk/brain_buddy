import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// A task's comments inside task detail, oldest first: who wrote it, when,
/// whether it was edited, and whether it has synced. Your own comments can be
/// edited in place; new ones are added at the bottom.
struct CommentsSection: View {
    private let task: TaskRecord
    private let isReadOnly: Bool

    @Environment(Workspace.self) private var workspace
    @State private var newBody = ""
    @State private var errorMessage: String?
    @FocusState private var isComposing: Bool

    init(task: TaskRecord, isReadOnly: Bool = false) {
        self.task = task
        self.isReadOnly = isReadOnly
    }

    private var comments: [CommentRecord] {
        task.comments.sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
    }

    private var trimmedBody: String {
        newBody.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        if !(isReadOnly && comments.isEmpty) {
            Section {
                ForEach(comments) { comment in
                    DetailCommentRow(
                        taskID: task.id,
                        comment: comment,
                        canEdit: !isReadOnly && workspace.isOwnComment(comment)
                    ) { message in
                        errorMessage = message
                    }
                }
                if !isReadOnly {
                    composer
                }
            } header: {
                BBSectionHeader("Comments", count: comments.isEmpty ? nil : comments.count)
            } footer: {
                if let errorMessage {
                    InlineProblemText(message: errorMessage)
                }
            }
        }
    }

    private var composer: some View {
        VStack(alignment: .trailing, spacing: 8) {
            Label {
                TextField("Add a comment", text: $newBody, axis: .vertical)
                    .lineLimit(1...8)
                    .focused($isComposing)
                    .accessibilityLabel("New comment")
            } icon: {
                Image(systemName: "plus")
                    .accessibilityHidden(true)
            }
            .labelStyle(.bbRow)
            .frame(maxWidth: .infinity, minHeight: BBMetrics.rowMinHeight, alignment: .leading)
            if !trimmedBody.isEmpty {
                Button("Add comment") { Task { await add() } }
                    .buttonStyle(.borderless)
                    .frame(minHeight: 44)
            }
        }
    }

    @MainActor private func add() async {
        let text = trimmedBody
        guard !text.isEmpty else { return }
        do {
            try await workspace.addComment(to: task.id, body: text, editorID: UUID().uuidString)
            newBody = ""
            errorMessage = nil
            isComposing = false
        } catch {
            errorMessage = error.message
        }
    }
}

private struct DetailCommentRow: View {
    let taskID: TaskID
    let comment: CommentRecord
    let canEdit: Bool
    let onProblem: (String?) -> Void

    @Environment(Workspace.self) private var workspace
    @State private var isEditing = false
    @State private var draft = ""
    @FocusState private var isFocused: Bool

    init(taskID: TaskID, comment: CommentRecord, canEdit: Bool, onProblem: @escaping (String?) -> Void) {
        self.taskID = taskID
        self.comment = comment
        self.canEdit = canEdit
        self.onProblem = onProblem
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(metadata)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if canEdit && !isEditing {
                    Button("Edit", action: beginEditing)
                        .buttonStyle(.borderless)
                        .font(.caption)
                        .frame(minWidth: 44, minHeight: 44)
                        .accessibilityLabel("Edit comment")
                }
            }
            if isEditing {
                editor
            } else {
                Text(comment.body)
                    .textSelection(.enabled)
            }
        }
        .accessibilityElement(children: isEditing ? .contain : .combine)
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Comment", text: $draft, axis: .vertical)
                .lineLimit(1...12)
                .focused($isFocused)
                .accessibilityLabel("Comment")
            HStack {
                Button("Cancel") {
                    isEditing = false
                }
                .frame(minHeight: 44)
                Spacer()
                Button("Save") { Task { await save() } }
                    .fontWeight(.semibold)
                    .frame(minHeight: 44)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            .buttonStyle(.borderless)
        }
    }

    private var metadata: String {
        var parts = [workspace.isOwnComment(comment) ? "You" : "Another account"]
        parts.append(comment.createdAt.formatted(.relative(presentation: .named)))
        if comment.editedAt != nil { parts.append("edited") }
        if comment.serverID == nil && workspace.account != nil { parts.append("not synced yet") }
        return parts.joined(separator: " · ")
    }

    private func beginEditing() {
        draft = comment.body
        isEditing = true
        isFocused = true
    }

    @MainActor private func save() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        guard text != comment.body else {
            isEditing = false
            return
        }
        do {
            try await workspace.editComment(comment.id, in: taskID, body: text, editorID: UUID().uuidString)
            isEditing = false
            onProblem(nil)
        } catch {
            onProblem(error.message)
        }
    }
}
