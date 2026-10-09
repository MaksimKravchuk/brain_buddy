import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Active tags with their open-task counts: create, rename, delete.
struct TagsScreen: View {
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts

    @State private var editorMode: TagEditorSheet.Mode?
    @State private var deleteCandidate: TagRecord?
    @State private var isConfirmingDelete = false

    init() {}

    var body: some View {
        content
            .bbScreenTitle("Tags")
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        editorMode = .create
                    } label: {
                        Label("New tag", systemImage: "plus")
                    }
                }
            }
            .sheet(item: $editorMode) { mode in
                TagEditorSheet(mode: mode)
            }
            .confirmationDialog(
                deleteTitle,
                isPresented: $isConfirmingDelete,
                titleVisibility: .visible,
                presenting: deleteCandidate
            ) { tag in
                Button("Delete tag", role: .destructive) { delete(tag) }
                Button("Cancel", role: .cancel) {}
            } message: { _ in
                Text("It's removed from every task. The tasks stay.")
            }
    }

    @ViewBuilder private var content: some View {
        let tags = workspace.tags()
        if tags.isEmpty {
            EmptyStateView(
                title: "No tags yet",
                message: "Tags group tasks by where or how you do them. Add one here, or type #name when you capture a task.",
                systemImage: "tag"
            )
        } else {
            List {
                ForEach(tags) { summary in
                    row(summary)
                }
            }
            .bbDenseList()
        }
    }

    private func row(_ summary: TagSummary) -> some View {
        let tag = summary.tag
        return NavigationLink(value: AppRoute.destination(.tag(tag.id))) {
            TagSummaryRow(summary: summary)
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button {
                confirmDelete(tag)
            } label: {
                Label("Delete", systemImage: "trash")
            }
            .tint(BBColor.danger)
            Button {
                editorMode = .rename(tag)
            } label: {
                Label("Rename", systemImage: "pencil")
            }
            .tint(BBColor.secondary)
        }
        .contextMenu {
            Button {
                editorMode = .rename(tag)
            } label: {
                Label("Rename", systemImage: "pencil")
            }
            Divider()
            Button(role: .destructive) {
                confirmDelete(tag)
            } label: {
                Label("Delete", systemImage: "trash")
            }
        }
    }

    private var deleteTitle: String {
        guard let deleteCandidate else { return "Delete tag?" }
        return "Delete #\(deleteCandidate.name)?"
    }

    private func confirmDelete(_ tag: TagRecord) {
        deleteCandidate = tag
        isConfirmingDelete = true
    }

    private func delete(_ tag: TagRecord) {
        let name = tag.name
        let deleted = TaskCommandRunner.run(toasts) {
            try workspace.deleteTag(tag.id)
        }
        deleteCandidate = nil
        if deleted {
            toasts.show("Deleted #\(name)", actionTitle: nil, action: nil)
        }
    }
}

/// A tag as a one-line row (`#` in the icon column, name, open-task count).
struct TagSummaryRow: View {
    let summary: TagSummary

    var body: some View {
        HStack(spacing: BBSpacing.s2) {
            Label {
                Text(summary.tag.name)
                    .foregroundStyle(BBColor.textPrimary)
            } icon: {
                Image(systemName: "number")
            }
            .labelStyle(.bbRow)
            Spacer(minLength: BBSpacing.s2)
            // Plain slate count, the same as the Lists hub rows; nothing for zero.
            CountBadge(count: summary.openTaskCount)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    private var accessibilityText: String {
        let count = summary.openTaskCount
        let tasks = count == 0 ? "no open tasks" : count == 1 ? "1 open task" : "\(count) open tasks"
        return "Tag \(summary.tag.name), \(tasks)"
    }
}
