import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// Active projects with management actions, or the read-only archive.
struct ProjectsScreen: View {
    private let showsArchived: Bool

    init(showsArchived: Bool = false) {
        self.showsArchived = showsArchived
    }

    var body: some View {
        if showsArchived {
            ArchivedProjectsList()
                .bbScreenTitle("Archived projects")
        } else {
            ActiveProjectsList()
                .bbScreenTitle("Projects")
        }
    }
}

// MARK: - Active projects

private struct ActiveProjectsList: View {
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts

    @State private var editorMode: ProjectEditorSheet.Mode?
    @State private var archiveCandidate: ProjectRecord?
    @State private var isConfirmingArchive = false

    var body: some View {
        let summaries = workspace.projects()
        let hasArchived = !workspace.projects(archived: true).isEmpty
        List {
            if summaries.isEmpty {
                EmptyStateView(
                    title: "No projects yet",
                    message: "Group tasks that share an outcome. Add a project here, or type @name when you capture a task.",
                    systemImage: "folder"
                )
                .frame(maxWidth: .infinity)
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            } else {
                Section {
                    ForEach(summaries) { summary in
                        row(summary)
                    }
                } footer: {
                    Text("A project needs a next action when none of its tasks is in Next actions.")
                }
            }
            if hasArchived {
                Section {
                    NavigationLink(value: AppRoute.archivedProjects) {
                        Label("Archived projects", systemImage: "folder.badge.minus")
                            .labelStyle(.bbRow)
                    }
                }
            }
        }
        .bbDenseList()
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    editorMode = .create
                } label: {
                    Label("New project", systemImage: "plus")
                }
            }
        }
        .sheet(item: $editorMode) { mode in
            ProjectEditorSheet(mode: mode)
        }
        .confirmationDialog(
            archiveTitle,
            isPresented: $isConfirmingArchive,
            titleVisibility: .visible,
            presenting: archiveCandidate
        ) { project in
            Button("Archive project", role: .destructive) { archive(project) }
            Button("Cancel", role: .cancel) {}
        } message: { _ in
            Text("Its tasks stay in their lists but lose the project. You can't undo this.")
        }
    }

    private func row(_ summary: ProjectSummary) -> some View {
        let project = summary.project
        return NavigationLink(value: AppRoute.destination(.project(project.id))) {
            ProjectSummaryRow(summary: summary)
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button {
                confirmArchive(project)
            } label: {
                Label("Archive", systemImage: "archivebox")
            }
            .tint(BBColor.danger)
            Button {
                editorMode = .edit(project)
            } label: {
                Label("Rename", systemImage: "pencil")
            }
            .tint(BBColor.secondary)
        }
        .contextMenu {
            Button {
                editorMode = .edit(project)
            } label: {
                Label("Rename", systemImage: "pencil")
            }
            ProjectColorMenu(current: project.color) { newColor in
                setColor(newColor, of: project)
            }
            Divider()
            Button(role: .destructive) {
                confirmArchive(project)
            } label: {
                Label("Archive", systemImage: "archivebox")
            }
        }
    }

    private var archiveTitle: String {
        guard let archiveCandidate else { return "Archive project?" }
        return "Archive “\(archiveCandidate.name)”?"
    }

    private func confirmArchive(_ project: ProjectRecord) {
        archiveCandidate = project
        isConfirmingArchive = true
    }

    private func archive(_ project: ProjectRecord) {
        let name = project.name
        let archived = TaskCommandRunner.run(toasts) {
            try workspace.archiveProject(project.id)
        }
        archiveCandidate = nil
        if archived {
            toasts.show("Archived “\(name)”", actionTitle: nil, action: nil)
        }
    }

    private func setColor(_ color: String?, of project: ProjectRecord) {
        let current = workspace.project(project.id)?.color
        guard !ProjectColorNames.same(color, current) else { return }
        _ = TaskCommandRunner.run(toasts) {
            try workspace.setProjectColor(project.id, color: color)
        }
    }
}

/// "Colour" submenu for a project's context menu; the current colour is checked.
private struct ProjectColorMenu: View {
    let current: String?
    let choose: (String?) -> Void

    var body: some View {
        Menu {
            Picker("Colour", selection: selection) {
                Text("No colour").tag(String?.none)
                if let custom = customColor {
                    Text("Current colour").tag(String?.some(custom))
                }
                ForEach(BBColor.projectColorPalette, id: \.self) { hex in
                    Text(ProjectColorNames.name(for: hex)).tag(String?.some(hex))
                }
            }
        } label: {
            Label("Colour", systemImage: "paintpalette")
        }
    }

    private var matchedCurrent: String? {
        ProjectColorNames.paletteEntry(matching: current, in: BBColor.projectColorPalette) ?? current
    }

    private var customColor: String? {
        guard let current,
            ProjectColorNames.paletteEntry(matching: current, in: BBColor.projectColorPalette) == nil
        else { return nil }
        return current
    }

    private var selection: Binding<String?> {
        Binding(get: { matchedCurrent }, set: { choose($0) })
    }
}

// MARK: - Archived projects

/// Archived projects are read-only: there is no unarchive on the server, and
/// archiving removed the project from its tasks, so there is nothing to open.
private struct ArchivedProjectsList: View {
    @Environment(Workspace.self) private var workspace

    var body: some View {
        let summaries = workspace.projects(archived: true)
        if summaries.isEmpty {
            EmptyStateView(
                title: "No archived projects",
                message: "Projects you archive are listed here, read-only.",
                systemImage: "archivebox"
            )
        } else {
            List {
                Section {
                    ForEach(summaries) { summary in
                        ArchivedProjectRow(project: summary.project)
                    }
                } footer: {
                    Text("Archived projects are read-only and can't be restored. Their tasks stayed in their lists.")
                }
            }
            .bbDenseList()
        }
    }
}

private struct ArchivedProjectRow: View {
    let project: ProjectRecord
    @ScaledMetric(relativeTo: .body) private var dotSize: CGFloat = 10

    var body: some View {
        Label {
            Text(project.name)
                .foregroundStyle(BBColor.textTertiary)
        } icon: {
            ProjectColorIndicator(hex: project.color, diameter: dotSize)
        }
        .labelStyle(.bbRow)
        .accessibilityElement(children: .combine)
    }
}

// MARK: - Shared row

/// A project with its colour, open count and the GTD "needs a next action"
/// signal as words. Used here and in the Lists hub. The colour dot sits in the
/// icon column, so names line up with the symbol rows around them; the signal
/// shares the name's line when it fits and drops under it otherwise.
struct ProjectSummaryRow: View {
    let summary: ProjectSummary
    @ScaledMetric(relativeTo: .body) private var dotSize: CGFloat = 10

    var body: some View {
        HStack(spacing: BBSpacing.s2) {
            Label {
                title
            } icon: {
                ProjectColorIndicator(hex: summary.project.color, diameter: dotSize)
            }
            .labelStyle(.bbRow)
            // Plain slate count, the same as the Lists hub rows; nothing for zero.
            CountBadge(count: summary.openTaskCount)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    @ViewBuilder private var title: some View {
        if summary.needsNextAction {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: BBSpacing.s2) {
                    name
                    Spacer(minLength: BBSpacing.s2)
                    NeedsNextActionMarker()
                }
                VStack(alignment: .leading, spacing: 2) {
                    name
                    NeedsNextActionMarker()
                }
            }
        } else {
            name
        }
    }

    private var name: some View {
        Text(summary.project.name)
            .foregroundStyle(BBColor.textPrimary)
    }

    private var accessibilityText: String {
        let count = summary.openTaskCount
        let tasks = count == 0 ? "no open tasks" : count == 1 ? "1 open task" : "\(count) open tasks"
        let marker = summary.needsNextAction ? ", needs a next action" : ""
        return "\(summary.project.name), \(tasks)\(marker)"
    }
}

private struct NeedsNextActionMarker: View {
    var body: some View {
        Label {
            Text("Needs a next action")
        } icon: {
            Image(systemName: "exclamationmark.circle")
                .foregroundStyle(BBColor.warning)
        }
        .labelStyle(.titleAndIcon)
        .font(BBFont.meta)
        .foregroundStyle(BBColor.textTertiary)
        .fixedSize(horizontal: true, vertical: false)
    }
}
