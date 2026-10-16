import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import BrainBuddyWorkspace
import SwiftUI

/// The Project review on this Mac: one active project at a time. A decision is a mark in
/// `mac-local.json` keyed to the project's tasks as they were when the review opened, so it is
/// refused once they changed and the project returns after seven days (FR-023).
struct ProjectReviewView: View {
    let model: BrainBuddyModel
    let openProject: (ProjectID) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var items: [ProjectReviewItem] = []
    @State private var index = 0
    @State private var loaded = false
    @State private var decision: ProjectReviewDecision?
    @State private var confirmingArchive = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            MacReviewHeader(
                title: "Review projects",
                caption: loaded ? "\(items.count) project\(items.count == 1 ? "" : "s") on this page · revisit after seven days" : "One project at a time",
                onClose: { dismiss() })

            if !loaded {
                ProgressView("Loading projects…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.projectReviewReadiness != .ready {
                if case .failed = model.projectReviewReadiness, model.workspace.isRustSelected {
                    MacSheetEmptyState(
                        title: "Project review couldn’t load", systemImage: "exclamationmark.triangle",
                        description: "The complete project signature is unavailable. Retry to check the current canonical review query."
                    ) {
                        Button("Retry", action: load)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if case .failed = model.projectReviewReadiness {
                    MacSheetEmptyState(title: "Projects couldn’t load", systemImage: "exclamationmark.triangle") {
                        Button("Retry", action: load)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ProgressView("Loading projects…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else if items.isEmpty {
                MacSheetEmptyState(
                    title: "Projects reviewed", systemImage: "checkmark.circle",
                    description: "Your decisions are saved on this Mac. Projects return after seven days."
                ) {
                    if model.projectsPageState.hasNext {
                        Button("Next projects") {
                            Task {
                                await model.workspace.nextProjectsPage()
                                load()
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let item = items[index]
                let taskPageState = model.projectReviewTaskPageState(item)
                HStack(spacing: 8) {
                    Button("Previous") {
                        index -= 1
                        decision = nil
                    }
                    .buttonStyle(.carryOnQuiet)
                    .disabled(index == 0)
                    Text("\(index + 1) of \(items.count)")
                        .font(MacSheetFont.meta)
                        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    Button(index >= items.count - 1 && model.projectsPageState.hasNext ? "Next projects" : "Next") {
                        if index < items.count - 1 {
                            index += 1
                            decision = nil
                        } else {
                            Task {
                                await model.workspace.nextProjectsPage()
                                load()
                            }
                        }
                    }
                    .buttonStyle(.carryOnQuiet)
                    .disabled(index >= items.count - 1 && !model.projectsPageState.hasNext)
                    Spacer()
                    Button("Open project to edit actions") { openProject(item.id) }
                        .buttonStyle(.carryOnSecondary)
                }
                ScrollView {
                    if taskPageState.readiness == .ready {
                        details(item)
                        HStack(spacing: 12) {
                            Button("Previous actions") { changeTaskPage(previous: true, item: item) }
                                .buttonStyle(.macText)
                                .disabled(!taskPageState.hasPrevious)
                            Text(taskPageState.hasPrevious || taskPageState.hasNext ? "More actions" : "All actions shown")
                                .font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                            Button("Next actions") { changeTaskPage(previous: false, item: item) }
                                .buttonStyle(.macText)
                                .disabled(!taskPageState.hasNext)
                        }
                        .padding(.top, 12)
                    } else if case .failed = taskPageState.readiness {
                        MacSheetEmptyState(title: "Project actions couldn’t load", systemImage: "exclamationmark.triangle") {
                            if taskPageState.readiness == .failed("REVIEW_PAGE_CHANGED") {
                                Button("Reload review", action: load)
                            } else {
                                Button("Retry actions") { Task { await loadProjectTasks(item) } }
                            }
                        }
                    } else {
                        ProgressView("Loading project actions…")
                    }
                }
                .task(id: item.id) { await loadProjectTasks(item) }
                MacSheetDivider()
                decisionControls(item)
                    .disabled(taskPageState.readiness != .ready)
                if let error = model.error {
                    Text(error).font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coStatusDanger)
                }
            }
        }
        .padding(24)
        .frame(width: 700, height: 640)
        .macSheetSurface()
        .onAppear(perform: load)
        .confirmationDialog("Archive this completed project?", isPresented: $confirmingArchive) {
            Button("Archive project") {
                guard index < items.count else { return }
                let id = items[index].id
                Task { if await model.archiveProject(id) { removeCurrent() } }
            }
            Button("Keep project", role: .cancel) {}
        } message: {
            Text("The project and its tasks remain available in Archived projects.")
        }
    }

    private func details(_ item: ProjectReviewItem) -> some View {
        let closures = item.tasks.filter(\.state.isTerminal)
        let displayedClosures = model.workspace.isRustSelected
            ? Array(closures.prefix(3))
            : Array(closures.sorted { ($0.completedAt ?? $0.cancelledAt ?? .distantPast) > ($1.completedAt ?? $1.cancelledAt ?? .distantPast) }.prefix(3))
        return MacProjectReviewDetails(
            name: item.project.name,
            lastReviewed: (item.lastReview?.reviewedAt).map { "Last reviewed \($0.formatted(date: .abbreviated, time: .omitted))" },
            reasons: reasons(for: item),
            desiredOutcome: item.project.desiredOutcome,
            sections: TaskList.allCases.compactMap { list -> MacProjectReviewSection? in
                let wholeCount = item.count(list.taskState)
                guard wholeCount > 0 else { return nil }
                let rows = item.openTasks.filter { $0.state == list.taskState }
                return MacProjectReviewSection(
                    title: "\(list.title.uppercased()) · \(wholeCount)",
                    rows: rows.map { MacProjectReviewRow(title: $0.title, waitingFor: $0.waitingFor) })
            },
            closuresTitle: model.workspace.isRustSelected ? "CLOSURES ON THIS PAGE" : "RECENT CLOSURES",
            closures: displayedClosures.map { "\($0.state == .completed ? "Completed" : "Cancelled") · \($0.title)" }
        )
    }

    @ViewBuilder
    private func decisionControls(_ item: ProjectReviewItem) -> some View {
        if item.openTaskCount == 0 {
            MacReviewLine(
                text: "No open actions. If the outcome is complete, archive this project; otherwise add a Next action.",
                tone: .primary)
            Button("Archive completed project…") { confirmingArchive = true }
                .buttonStyle(.carryOnSecondary)
                .disabled(!model.canArchiveProject)
                .help("Add or clear the current task draft before archiving")
        } else if item.openTasks.isEmpty {
            MacReviewLine(text: "No open actions are on this page. Load another actions page to review the project.")
        } else {
            Picker("Your decision", selection: $decision) {
                Text("Choose after checking the project").tag(ProjectReviewDecision?.none)
                ForEach(ProjectReviewDecision.allCases) { option in
                    Text(option.title).tag(Optional(option))
                }
            }
            .pickerStyle(.menu)
            .font(MacSheetFont.body)
            .disabled(item.nextCount == 0 && item.waitingCount == 0 && item.somedayCount == 0)
            MacReviewLine(text: decisionHint(for: item), small: true)
            Button("Mark reviewed") {
                guard let decision else { return }
                if model.workspace.isRustSelected {
                    Task { if await model.markNativeProjectReviewed(item, decision: decision) { removeCurrent() } }
                } else if model.markProjectReviewed(item, decision: decision) {
                    removeCurrent()
                }
            }
            .buttonStyle(.carryOnStrong)
            .disabled(!canMark(item) || model.projectReviewTaskPageState(item).readiness != .ready)
        }
    }

    private func changeTaskPage(previous: Bool, item: ProjectReviewItem) {
        Task {
            let updated = previous
                ? await model.previousProjectReviewTaskPage(item)
                : await model.nextProjectReviewTaskPage(item)
            guard index < items.count, items[index].id == item.id,
                  items[index].projectionGeneration == item.projectionGeneration else { return }
            items[index] = updated
        }
    }

    private func loadProjectTasks(_ item: ProjectReviewItem) async {
        let updated = await model.reloadProjectReviewTaskPage(item)
        guard !Task.isCancelled, index < items.count, items[index].id == item.id,
              items[index].projectionGeneration == item.projectionGeneration else { return }
        items[index] = updated
    }

    private func load() {
        loaded = false
        Task {
            items = await model.loadProjectReview()
            index = 0
            decision = nil
            loaded = true
        }
    }

    private func removeCurrent() {
        items.remove(at: index)
        index = min(index, max(items.count - 1, 0))
        decision = nil
    }

    private func canMark(_ item: ProjectReviewItem) -> Bool {
        guard let decision else { return false }
        switch decision {
        case .keep, .actionUpdated: return item.nextCount > 0 || item.waitingCount > 0 || item.somedayCount > 0
        case .deferred: return item.nextCount == 0 && (item.waitingCount > 0 || item.somedayCount > 0)
        }
    }

    private func decisionHint(for item: ProjectReviewItem) -> String {
        if item.nextCount == 0 && item.waitingCount == 0 && item.somedayCount == 0 {
            return "Add a Next action in the project before marking it reviewed."
        }
        if decision == .actionUpdated { return "Use this after changing an action in the project." }
        if decision == .deferred { return "Available when the project has no Next action and remains in Waiting or Someday." }
        return "A review does not change task dates or GTD states."
    }

    private func reasons(for item: ProjectReviewItem) -> [String] {
        var result: [String] = []
        if item.hasChanges { result.append("Actions changed since the last review") }
        if item.project.desiredOutcome?.isEmpty ?? true { result.append("Desired outcome is missing") }
        if item.nextCount == 0 { result.append("No Next action") }
        if !model.workspace.isRustSelected {
            let weekAgo = Date().addingTimeInterval(-7 * 24 * 60 * 60)
            let oldWaiting = item.openTasks.filter { $0.state == .waiting && ($0.waitingSince.map { $0 < weekAgo } ?? false) }.count
            if oldWaiting > 0 { result.append("\(oldWaiting) Waiting item\(oldWaiting == 1 ? "" : "s") older than a week") }
        }
        if item.somedayCount > 0 {
            result.append("\(item.somedayCount) Someday item\(item.somedayCount == 1 ? "" : "s") to reconsider")
        }
        if result.isEmpty { result.append("Check that the Next action is still executable") }
        return result
    }
}

/// One list's section of the project under review: "NEXT ACTIONS · 3" and its open tasks.
struct MacProjectReviewSection: Hashable {
    let title: String
    let rows: [MacProjectReviewRow]
}

/// An open task under review, with who it waits for.
struct MacProjectReviewRow: Hashable {
    let title: String
    var waitingFor: String?
}

/// What the Project review shows about one project: its name in 20 semibold, when it was last
/// reviewed, why to review it now on a `bg-ground` plate, the desired outcome, the open tasks by
/// list and the recent closures. Presentation only.
struct MacProjectReviewDetails: View {
    let name: String
    let lastReviewed: String?
    let reasons: [String]
    let desiredOutcome: String?
    let sections: [MacProjectReviewSection]
    let closuresTitle: String
    let closures: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(name)
                    .font(MacSheetFont.cardTitle)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                if let lastReviewed {
                    MacReviewLine(text: lastReviewed, small: true)
                }
            }
            MacSheetPlate(padding: 14) {
                MacReviewSectionLabel(text: "WHY REVIEW NOW")
                ForEach(reasons, id: \.self) { reason in
                    MacSheetStatus(
                        text: reason, systemImage: "exclamationmark.circle", tone: .primary, font: MacSheetFont.body)
                }
            }
            VStack(alignment: .leading, spacing: 5) {
                MacReviewSectionLabel(text: "DESIRED OUTCOME")
                MacReviewLine(text: desiredOutcome ?? "No outcome defined yet.", tone: desiredOutcome == nil ? .secondary : .primary)
            }
            ForEach(sections, id: \.self) { section in
                VStack(alignment: .leading, spacing: 7) {
                    MacReviewSectionLabel(text: section.title)
                    ForEach(Array(section.rows.enumerated()), id: \.offset) { _, row in
                        VStack(alignment: .leading, spacing: 2) {
                            MacReviewLine(text: row.title, tone: .primary)
                            if let waiting = row.waitingFor {
                                MacReviewLine(text: "Waiting for \(waiting)", small: true)
                            }
                        }
                    }
                }
            }
            if !closures.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    MacReviewSectionLabel(text: closuresTitle)
                    ForEach(Array(closures.enumerated()), id: \.offset) { _, closure in
                        MacReviewLine(text: closure, tone: .primary)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
