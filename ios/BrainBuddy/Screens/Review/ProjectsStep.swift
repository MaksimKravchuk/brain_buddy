import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-19 (spec 020, FR-028): the active projects with nothing to do next, each
/// with a field for its next action (filed in Next, in that project). The
/// navigator's "Suggest" is not built yet. An action typed but not added is
/// a device draft (FR-052).
struct ProjectsStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace
    @State private var texts: [ProjectID: String] = [:]
    @State private var problem: String?
    @State private var editorIDs: [ProjectID: String] = [:]
    @State private var savingProjects: Set<ProjectID> = []

    var body: some View {
        let read = WorkspaceReviewRead.projects
        let page = workspace.reviewPageState(read)
        let projects = workspace.projectsNeedingNextAction()
        let cleanupKeys = context.fields.submittedDrafts.keys.filter {
            context.fields.submittedDrafts[$0]?.projectID != nil
        }.sorted { $0.rawValue < $1.rawValue }
        ReviewStepFrame(
            title: projects.isEmpty ? ReviewCopy.projectsEmpty : ReviewCopy.stepTitle(.projects),
            primaryTitle: ReviewCopy.next, onPrimary: context.advance
        ) {
            if !projects.isEmpty {
                Text(ReviewCopy.projectsIntro)
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            ForEach(projects) { summary in
                let key = DraftKey.projectNextAction(summary.id)
                VStack(alignment: .leading, spacing: BBSpacing.s2) {
                    Text(summary.project.name)
                        .font(BBFont.bodyMedium)
                        .foregroundStyle(BBColor.textPrimary)
                        .accessibilityAddTraits(.isHeader)
                    ReviewDraftField(
                        prompt: ReviewCopy.nextActionPlaceholder, key: key, text: binding(for: summary.id),
                        fields: context.fields
                    ).disabled(savingProjects.contains(summary.id))
                    Button {
                        add(to: summary.id, key: key)
                    } label: {
                        Text(ReviewCopy.addNextAction).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                    }
                    .buttonStyle(.bordered)
                    .disabled(savingProjects.contains(summary.id) || context.fields.submittedDrafts[key] != nil
                        || (texts[summary.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            // A committed next action can remove its project from the query.
            // Keep its cleanup retry outside those rows, including after remount.
            ForEach(cleanupKeys, id: \.self) { key in
                Text("Next action added. The saved draft still needs to be cleared.")
                    .font(BBFont.meta)
                Button("Retry draft cleanup") { retryCleanup(key) }
                    .frame(minHeight: BBMetrics.hitTarget)
                    .disabled(context.fields.cleaningDrafts.contains(key))
            }
            if let problem {
                InlineProblemText(message: problem)
            }
        }
        .overlay {
            if page.readiness != .ready {
                WorkspaceQueryContent(readiness: page.readiness, retry: { Task { try? await workspace.prepareReviewRead(read) } }) { EmptyView() }
            }
        }
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: page,
                previous: { try? await workspace.previousReviewPage(read) },
                next: { try? await workspace.nextReviewPage(read) })
        }
        .task { try? await workspace.prepareReviewRead(read) }
    }

    private func binding(for id: ProjectID) -> Binding<String> {
        Binding(get: { texts[id] ?? "" }, set: { texts[id] = $0 })
    }

    private func add(to id: ProjectID, key: DraftKey) {
        guard !savingProjects.contains(id), context.fields.submittedDrafts[key] == nil else { return }
        savingProjects.insert(id)
        let text = texts[id] ?? ""
        let submittedEditorID = editorIDs[id] ?? UUID().uuidString
        editorIDs[id] = submittedEditorID
        Task { await addDurably(to: id, key: key, text: text, editorID: submittedEditorID) }
    }

    @MainActor private func addDurably(to id: ProjectID, key: DraftKey, text: String, editorID: String) async {
        problem = nil
        defer { savingProjects.remove(id) }
        let taskID: TaskID
        do {
            taskID = try await workspace.capture(CaptureDraft(text: text, list: .next, contextProjectID: id), editorID: editorID)
        } catch {
            problem = TaskCommandRunner.message(for: error)
            return
        }
        context.fields.recordSubmission(key, taskID: taskID, editorID: editorID, projectID: id)
        texts[id] = nil
        await cleanDraft(key, projectID: id)
    }

    private func retryCleanup(_ key: DraftKey) {
        guard !context.fields.cleaningDrafts.contains(key),
              let id = context.fields.submittedDrafts[key]?.projectID else { return }
        Task { await cleanDraft(key, projectID: id) }
    }

    @MainActor private func cleanDraft(_ key: DraftKey, projectID: ProjectID) async {
        problem = nil
        do {
            try await context.fields.cleanSubmittedDraft(key, in: workspace)
            if context.fields.submittedDrafts[key] == nil { editorIDs[projectID] = UUID().uuidString }
        } catch {
            problem = "Next action added. " + TaskCommandRunner.message(for: error)
        }
    }
}
