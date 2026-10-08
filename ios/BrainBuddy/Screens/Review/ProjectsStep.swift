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

    var body: some View {
        let projects = workspace.projectsNeedingNextAction()
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
                    )
                    Button {
                        add(to: summary.id, key: key)
                    } label: {
                        Text(ReviewCopy.addNextAction).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                    }
                    .buttonStyle(.bordered)
                    .disabled((texts[summary.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            if let problem {
                InlineProblemText(message: problem)
            }
        }
    }

    private func binding(for id: ProjectID) -> Binding<String> {
        Binding(get: { texts[id] ?? "" }, set: { texts[id] = $0 })
    }

    private func add(to id: ProjectID, key: DraftKey) {
        problem = nil
        do {
            try workspace.capture(CaptureDraft(text: texts[id] ?? "", list: .next, contextProjectID: id))
        } catch {
            problem = error.message
            return
        }
        texts[id] = nil
        ReviewDraftField.submitted(key, in: workspace, fields: context.fields)
    }
}
