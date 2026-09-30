import SwiftUI

struct ProjectReviewView: View {
    @ObservedObject var model: BrainBuddyModel
    let openProject: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var items: [ProjectReviewItem] = []
    @State private var index = 0
    @State private var loading = true
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
                    .disabled(model.busy)
            }

            if loading {
                ProgressView("Loading projects…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if !loaded {
                ContentUnavailableView("Could not load review", systemImage: "arrow.clockwise",
                                       description: Text(model.error ?? "Try again."))
                Button("Retry") { Task { await load() } }
            } else if items.isEmpty {
                ContentUnavailableView("Projects reviewed", systemImage: "checkmark.circle",
                                       description: Text("Your decisions are saved on this Mac. Projects return after seven days."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                let item = items[index]
                HStack {
                    Button("Previous") { index -= 1; decision = nil }
                        .disabled(index == 0 || model.busy)
                    Text("\(index + 1) of \(items.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Button("Next") { index += 1; decision = nil }
                        .disabled(index >= items.count - 1 || model.busy)
                    Spacer()
                    Button("Open project to edit actions") { openProject(item.id) }
                        .disabled(model.busy)
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text(item.project.name).font(.title3.bold())
                        if let last = item.project.last_reviewed_at.flatMap(Self.date) {
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
                            Text(item.project.desired_outcome ?? "No outcome defined yet.")
                                .foregroundStyle(item.project.desired_outcome == nil ? .secondary : .primary)
                        }
                        ForEach(TaskList.allCases) { list in
                            let rows = item.openTasks.filter { $0.state == list.rawValue }
                            if !rows.isEmpty {
                                VStack(alignment: .leading, spacing: 7) {
                                    Text("\(list.title.uppercased()) · \(rows.count)")
                                        .font(.caption.bold())
                                        .foregroundStyle(.secondary)
                                    ForEach(rows) { task in
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(task.title)
                                            if let waiting = task.waiting_for {
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
                        let closures = item.tasks
                            .filter { $0.state == "completed" || $0.state == "cancelled" }
                            .sorted { ($0.completed_at ?? $0.cancelled_at ?? "") > ($1.completed_at ?? $1.cancelled_at ?? "") }
                        if !closures.isEmpty {
                            VStack(alignment: .leading, spacing: 7) {
                                Text("RECENT CLOSURES").font(.caption.bold()).foregroundStyle(.secondary)
                                ForEach(Array(closures.prefix(3))) { task in
                                    Text("\(task.state == "completed" ? "Completed" : "Cancelled") · \(task.title)")
                                        .font(.subheadline)
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }

                Divider()
                if item.openTasks.isEmpty {
                    Text("No open actions. If the outcome is complete, archive this project; otherwise add a Next action.")
                        .font(.subheadline)
                    Button("Archive completed project…") { confirmingArchive = true }
                        .disabled(model.busy)
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
                        Task {
                            if await model.markProjectReviewed(item.project, decision: decision) {
                                items.remove(at: index)
                                index = min(index, max(items.count - 1, 0))
                                self.decision = nil
                            }
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.busy || !canMark(item))
                }
                if let error = model.error {
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
        .padding(24)
        .frame(width: 700, height: 640)
        .task { await load() }
        .confirmationDialog("Archive this completed project?", isPresented: $confirmingArchive) {
            Button("Archive project") {
                guard index < items.count else { return }
                let item = items[index]
                Task {
                    if await model.archiveProject(item.id) {
                        items.remove(at: index)
                        index = min(index, max(items.count - 1, 0))
                        decision = nil
                    }
                }
            }
            Button("Keep project", role: .cancel) {}
        } message: {
            Text("The project and its tasks remain available in Archived projects.")
        }
    }

    private func load() async {
        loading = true
        if let fetched = await model.loadProjectReview() {
            items = fetched
            index = 0
            decision = nil
            loaded = true
        } else {
            loaded = false
        }
        loading = false
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
        if item.project.review_has_changes == true { result.append("Actions changed since the last review") }
        if item.project.desired_outcome?.isEmpty ?? true { result.append("Desired outcome is missing") }
        if item.nextCount == 0 { result.append("No Next action") }
        let oldWaiting = item.openTasks.filter { task in
            task.state == TaskList.waiting.rawValue &&
                (task.waiting_since.flatMap(Self.date).map { $0 < Date().addingTimeInterval(-7 * 24 * 60 * 60) } ?? false)
        }.count
        if oldWaiting > 0 { result.append("\(oldWaiting) Waiting item\(oldWaiting == 1 ? "" : "s") older than a week") }
        if item.somedayCount > 0 { result.append("\(item.somedayCount) Someday item\(item.somedayCount == 1 ? "" : "s") to reconsider") }
        if result.isEmpty { result.append("Check that the Next action is still executable") }
        return result
    }

    private static func date(_ value: String) -> Date? {
        ISO8601DateFormatter().date(from: value)
    }
}
