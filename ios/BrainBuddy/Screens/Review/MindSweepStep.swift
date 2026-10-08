import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-14 (spec 020, FR-028): a one-line capture into the Inbox, with the list
/// of what this step added. A line typed but not added is kept as a device
/// draft; Next, Skip and Leave ask about it first (FR-052).
struct MindSweepStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace
    @State private var line = ""
    @State private var added: [TaskID] = []
    @State private var problem: String?

    var body: some View {
        let key = DraftKey.reviewStep(session: context.sessionID, step: .mindSweep, item: "line")
        ReviewStepFrame(
            title: ReviewCopy.stepTitle(.mindSweep), primaryTitle: ReviewCopy.next, onPrimary: context.advance
        ) {
            Text(ReviewCopy.mindSweepPrompt)
                .font(BBFont.body)
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            ReviewDraftField(
                prompt: ReviewCopy.addToInbox, key: key, text: $line, fields: context.fields,
                unsavedMessage: ReviewCopy.notInInboxYet
            )
            Button {
                add(key)
            } label: {
                Text(ReviewCopy.addToInbox).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            }
            .buttonStyle(.bordered)
            .disabled(line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            if let problem {
                InlineProblemText(message: problem)
            }
            if !added.isEmpty {
                Text(ReviewCopy.addedThisStep)
                    .font(BBFont.subtitle)
                    .foregroundStyle(BBColor.textSecondary)
                ForEach(added, id: \.self) { id in
                    if let task = workspace.task(id) {
                        Text(task.title)
                            .font(BBFont.body)
                            .foregroundStyle(BBColor.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private func add(_ key: DraftKey) {
        problem = nil
        let id: TaskID
        do {
            id = try workspace.capture(CaptureDraft(text: line, list: .inbox))
        } catch {
            problem = error.message
            return
        }
        added.append(id)
        line = ""
        ReviewDraftField.submitted(key, in: workspace, fields: context.fields)
    }
}

#Preview("M-14 default") {
    MindSweepStep(context: .preview)
        .environment(Workspace.preview())
        .environment(ToastCenter())
}
