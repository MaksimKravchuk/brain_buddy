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
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false

    var body: some View {
        let key = DraftKey.reviewStep(session: context.sessionID, step: .mindSweep, item: "line")
        let submission = context.fields.submittedDrafts[key]
        let addedIDs = added + (submission.map { added.contains($0.taskID) ? [] : [$0.taskID] } ?? [])
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
            ).disabled(isSaving)
            Button {
                add(key)
            } label: {
                Text(ReviewCopy.addToInbox).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            }
            .buttonStyle(.bordered)
            .disabled(isSaving || submission != nil || line.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            if submission != nil {
                Text("Added to Inbox. The saved draft still needs to be cleared.")
                    .font(BBFont.meta)
                Button("Retry draft cleanup") { retryCleanup(key) }
                    .frame(minHeight: BBMetrics.hitTarget)
                    .disabled(isSaving || context.fields.cleaningDrafts.contains(key))
            }
            if let problem {
                InlineProblemText(message: problem)
            }
            if !addedIDs.isEmpty {
                Text(ReviewCopy.addedThisStep)
                    .font(BBFont.subtitle)
                    .foregroundStyle(BBColor.textSecondary)
                ForEach(addedIDs, id: \.self) { id in
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
        guard !isSaving, context.fields.submittedDrafts[key] == nil else { return }
        isSaving = true
        let text = line
        let submittedEditorID = editorID
        Task { await addDurably(key, text: text, editorID: submittedEditorID) }
    }

    @MainActor private func addDurably(_ key: DraftKey, text: String, editorID submittedEditorID: String) async {
        defer { isSaving = false }
        problem = nil
        let id: TaskID
        do {
            id = try await workspace.capture(CaptureDraft(text: text, list: .inbox), editorID: submittedEditorID)
        } catch {
            problem = TaskCommandRunner.message(for: error)
            return
        }
        // Capture returned a known durable result. Any later retry is cleanup only.
        context.fields.recordSubmission(key, taskID: id, editorID: submittedEditorID)
        added.append(id)
        line = ""
        await cleanDraft(key)
    }

    private func retryCleanup(_ key: DraftKey) {
        guard !isSaving, !context.fields.cleaningDrafts.contains(key) else { return }
        isSaving = true
        Task {
            await cleanDraft(key)
            isSaving = false
        }
    }

    @MainActor private func cleanDraft(_ key: DraftKey) async {
        problem = nil
        do {
            try await context.fields.cleanSubmittedDraft(key, in: workspace)
            if context.fields.submittedDrafts[key] == nil { editorID = UUID().uuidString }
        } catch {
            problem = "Added to Inbox. " + TaskCommandRunner.message(for: error)
        }
    }
}

#Preview("M-14 default") {
    MindSweepStep(context: .preview)
        .environment(Workspace.preview())
        .environment(ToastCenter())
}
