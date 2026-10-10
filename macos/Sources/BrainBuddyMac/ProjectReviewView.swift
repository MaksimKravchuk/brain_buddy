import BrainBuddyCore
import BrainBuddyMacCore
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
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Review projects").font(.title2.bold())
                    Text(loaded ? "\(items.count) project\(items.count == 1 ? "" : "s") left · revisit after seven days" : "One project at a time")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close review") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }

            if items.isEmpty {
                ContentUnavailableView(
                    "Projects reviewed", systemImage: "checkmark.circle",
                    description: Text("Your decisions are saved on this Mac. Projects return after seven days.")
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let item = items[index]
                HStack {
                    Button("Previous") {
                        index -= 1
                        decision = nil
                    }
                    .disabled(index == 0)
                    Text("\(index + 1) of \(items.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Next") {
                        index += 1
                        decision = nil
                    }
                    .disabled(index >= items.count - 1)
                    Spacer()
                    Button("Open project to edit actions") { openProject(item.id) }
                }
                ScrollView {
                    details(item)
                }
                Divider()
                decisionControls(item)
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
        .padding(24)
        .frame(width: 700, height: 640)
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
        VStack(alignment: .leading, spacing: 16) {
            Text(item.project.name).font(.title3.bold())
            if let last = item.lastReview?.reviewedAt {
                Text("Last reviewed \(last.formatted(date: .abbreviated, time: .omitted))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            VStack(alignment: .leading, spacing: 8) {
                Text("WHY REVIEW NOW").font(.caption.bold()).foregroundStyle(.secondary)
                ForEach(reasons(for: item), id: \.self) { reason in
                    Label(reason, systemImage: "exclamationmark.circle")
                        .font(.subheadline)
                }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))

            VStack(alignment: .leading, spacing: 5) {
                Text("DESIRED OUTCOME").font(.caption.bold()).foregroundStyle(.secondary)
                Text(item.project.desiredOutcome ?? "No outcome defined yet.")
                    .foregroundStyle(item.project.desiredOutcome == nil ? .secondary : .primary)
            }
            ForEach(TaskList.allCases) { list in
                let rows = item.openTasks.filter { $0.state == list.taskState }
                if !rows.isEmpty {
                    VStack(alignment: .leading, spacing: 7) {
                        Text("\(list.title.uppercased()) · \(rows.count)")
                            .font(.caption.bold())
                            .foregroundStyle(.secondary)
                        ForEach(rows) { task in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(task.title)
                                if let waiting = task.waitingFor {
                                    Text("Waiting for \(waiting)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
            let closures = item.tasks.filter(\.state.isTerminal)
                .sorted { ($0.completedAt ?? $0.cancelledAt ?? .distantPast) > ($1.completedAt ?? $1.cancelledAt ?? .distantPast) }
            if !closures.isEmpty {
                VStack(alignment: .leading, spacing: 7) {
                    Text("RECENT CLOSURES").font(.caption.bold()).foregroundStyle(.secondary)
                    ForEach(Array(closures.prefix(3))) { task in
                        Text("\(task.state == .completed ? "Completed" : "Cancelled") · \(task.title)")
                            .font(.subheadline)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    @ViewBuilder
    private func decisionControls(_ item: ProjectReviewItem) -> some View {
        if item.openTasks.isEmpty {
            Text("No open actions. If the outcome is complete, archive this project; otherwise add a Next action.")
                .font(.subheadline)
            Button("Archive completed project…") { confirmingArchive = true }
                .disabled(!model.canArchiveProject)
                .help("Add or clear the current task draft before archiving")
        } else {
            Picker("Your decision", selection: $decision) {
                Text("Choose after checking the project").tag(ProjectReviewDecision?.none)
                ForEach(ProjectReviewDecision.allCases) { option in
                    Text(option.title).tag(Optional(option))
                }
            }
            .pickerStyle(.menu)
            .disabled(item.nextCount == 0 && item.waitingCount == 0 && item.somedayCount == 0)
            Text(decisionHint(for: item))
                .font(.caption)
                .foregroundStyle(.secondary)
            Button("Mark reviewed") {
                guard let decision else { return }
                if model.markProjectReviewed(item, decision: decision) { removeCurrent() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(!canMark(item))
        }
    }

    private func load() {
        items = model.loadProjectReview()
        index = 0
        decision = nil
        loaded = true
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
        let weekAgo = Date().addingTimeInterval(-7 * 24 * 60 * 60)
        let oldWaiting = item.openTasks.filter { $0.state == .waiting && ($0.waitingSince.map { $0 < weekAgo } ?? false) }.count
        if oldWaiting > 0 { result.append("\(oldWaiting) Waiting item\(oldWaiting == 1 ? "" : "s") older than a week") }
        if item.somedayCount > 0 {
            result.append("\(item.somedayCount) Someday item\(item.somedayCount == 1 ? "" : "s") to reconsider")
        }
        if result.isEmpty { result.append("Check that the Next action is still executable") }
        return result
    }
}
