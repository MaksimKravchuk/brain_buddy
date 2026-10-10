import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-18 (spec 020, FR-032, FR-034): Waiting for tasks older than 7 days, one at
/// a time: keep waiting (looks again in 7 days), create a follow-up (a Next
/// action in the same project), return to Next, or cancel. Each is a review
/// decision with the Undo status line; a typed title is a device draft until
/// it is saved (FR-052).
struct WaitingStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace

    var body: some View {
        ReviewItemStep(
            context: context, step: .waiting, list: .waiting, emptyTitle: ReviewCopy.nothingToChase,
            queue: { workspace.waitingDue(session: context.sessionID) },
            meta: { task in
                let days = task.waitingSince.map { Int(workspace.reviewNow.timeIntervalSince($0) / FormulationRule.day) } ?? 0
                return ReviewCopy.waitingMeta(waitingFor: task.waitingFor ?? "", days: max(0, days))
            },
            choices: [
                ReviewItemChoice(
                    decision: .keepWaiting, title: ReviewCopy.name(of: .keepWaiting),
                    subtitle: ReviewCopy.keepWaitingSubtitle
                ),
                ReviewItemChoice(
                    decision: .followUp, title: ReviewCopy.name(of: .followUp), prompt: ReviewCopy.followUpPrompt
                ),
                ReviewItemChoice(
                    decision: .returnToNext, title: ReviewCopy.name(of: .returnToNext), prompt: ReviewCopy.returnPrompt,
                    prefillsTitle: true
                ),
                ReviewItemChoice(decision: .cancel, title: ReviewCopy.name(of: .cancel)),
            ]
        )
    }
}

/// One decision of an item step. With a `prompt` it first asks for a title.
struct ReviewItemChoice: Identifiable {
    let decision: DecisionType
    let title: String
    var subtitle: String? = nil
    var prompt: String? = nil
    /// The task's own title is the starting text (return to Next).
    var prefillsTitle = false

    var id: DecisionType { decision }
}

/// The item steps of the review (Waiting for, Someday): the tasks due a look,
/// snapshotted when the step opens, one at a time. What is due and what each
/// decision does are Core's; a task decided in this run, or no longer in
/// `list`, is passed over, and Undo brings it back.
struct ReviewItemStep: View {
    let context: ReviewStepContext
    let step: ReviewStep
    let list: TaskState
    let emptyTitle: String
    let queue: () -> [TaskRecord]
    let meta: (TaskRecord) -> String
    let choices: [ReviewItemChoice]

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @State private var snapshot: [TaskRecord]?
    /// The task as the item showed it: a change since makes the decision stale (FR-011).
    @State private var shown: ShownTask?
    @State private var asking: ReviewItemChoice?
    @State private var text = ""
    @State private var problem: String?
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false

    init(
        context: ReviewStepContext, step: ReviewStep, list: TaskState, emptyTitle: String,
        queue: @escaping () -> [TaskRecord], meta: @escaping (TaskRecord) -> String, choices: [ReviewItemChoice]
    ) {
        self.context = context
        self.step = step
        self.list = list
        self.emptyTitle = emptyTitle
        self.queue = queue
        self.meta = meta
        self.choices = choices
    }

    var body: some View {
        let read = WorkspaceReviewRead.queue(step, context.sessionID)
        let page = workspace.reviewPageState(read)
        let task = current
        ReviewItemContent(
            title: task?.title ?? ((snapshot ?? []).isEmpty ? emptyTitle : ReviewCopy.stepTitle(step)),
            meta: task.map(meta), choices: task == nil ? [] : choices, asking: asking,
            draft: task.map { DraftKey.reviewStep(session: context.sessionID, step: step, item: $0.id.rawValue) },
            text: $text, fields: context.fields, problem: problem,
            onChoose: { choice in
                if let task { choose(choice, for: task) }
            },
            onSave: {
                if let task, let asking { decide(asking.decision, task, title: text) }
            },
            onBack: { asking = nil },
            onNext: context.advance
        )
        .disabled(isSaving)
        .id(task?.id)
        .onAppear { if snapshot == nil { snapshot = queue() } }
        .task { try? await workspace.prepareReviewRead(read); snapshot = queue() }
        .overlay {
            if page.readiness != .ready {
                WorkspaceQueryContent(readiness: page.readiness, retry: { Task { try? await workspace.prepareReviewRead(read); snapshot = queue() } }) { EmptyView() }
            }
        }
        .safeAreaInset(edge: .bottom) {
            WorkspaceQueryPageControls(page: page,
                previous: { try? await workspace.previousReviewPage(read); snapshot = queue() },
                next: { try? await workspace.nextReviewPage(read); snapshot = queue() })
                .disabled(isSaving)
        }
        .onChange(of: task?.id, initial: true) { _, _ in
            asking = nil
            text = ""
            shown = task.flatMap { workspace.reviewShownTask($0.id, read: .queue(step, context.sessionID)) }
        }
    }

    private var current: TaskRecord? {
        guard let snapshot else { return nil }
        return snapshot.first { $0.state == list }
    }

    private func choose(_ choice: ReviewItemChoice, for task: TaskRecord) {
        problem = nil
        if choice.prompt != nil {
            asking = choice
            text = choice.prefillsTitle ? task.title : ""
        } else {
            decide(choice.decision, task, title: nil)
        }
    }

    private func decide(_ type: DecisionType, _ task: TaskRecord, title: String?) {
        guard !isSaving else { return }
        isSaving = true
        let expectedTask = shown
        let submittedEditorID = editorID
        Task { await decideDurably(type, task, title: title, expectedTask: expectedTask, editorID: submittedEditorID) }
    }

    @MainActor private func decideDurably(_ type: DecisionType, _ task: TaskRecord, title: String?, expectedTask: ShownTask?, editorID submittedEditorID: String) async {
        defer { isSaving = false }
        let typed = title?.trimmingCharacters(in: .whitespacesAndNewlines)
        let decisionID: DecisionID
        do {
            decisionID = try await workspace.decide(
                type, on: task.id, title: typed, sessionID: context.sessionID, expectedTask: expectedTask,
                editorID: submittedEditorID
            )
        } catch {
            guard let validation = error as? GTDValidationError else {
                problem = TaskCommandRunner.message(for: error)
                return
            }
            switch validation {
            case .formulationChanged, .taskNotFound:
                problem = ReviewCopy.stale
            case .projectArchived where type == .followUp:
                problem = ReviewCopy.archivedFollowUp
            default:
                problem = TaskCommandRunner.message(for: error)
            }
            return
        }
        problem = nil
        asking = nil
        text = ""
        context.fields.set(.reviewStep(session: context.sessionID, step: step, item: task.id.rawValue), dirty: false)
        snapshot = queue()
        editorID = UUID().uuidString
        DecisionUndoToast.show(
            decisionID, decision: type, title: typed ?? task.title, taskID: task.id, workspace: workspace, toasts: toasts
        )
    }
}

/// The item step for given values (every state has a preview).
struct ReviewItemContent: View {
    let title: String
    let meta: String?
    let choices: [ReviewItemChoice]
    let asking: ReviewItemChoice?
    let draft: DraftKey?
    @Binding var text: String
    let fields: ReviewFields
    let problem: String?
    let onChoose: (ReviewItemChoice) -> Void
    let onSave: () -> Void
    let onBack: () -> Void
    let onNext: () -> Void

    init(
        title: String, meta: String?, choices: [ReviewItemChoice], asking: ReviewItemChoice?, draft: DraftKey?,
        text: Binding<String>, fields: ReviewFields, problem: String?, onChoose: @escaping (ReviewItemChoice) -> Void,
        onSave: @escaping () -> Void, onBack: @escaping () -> Void, onNext: @escaping () -> Void
    ) {
        self.title = title
        self.meta = meta
        self.choices = choices
        self.asking = asking
        self.draft = draft
        _text = text
        self.fields = fields
        self.problem = problem
        self.onChoose = onChoose
        self.onSave = onSave
        self.onBack = onBack
        self.onNext = onNext
    }

    var body: some View {
        ReviewStepFrame(title: title, primaryTitle: ReviewCopy.next, onPrimary: onNext) {
            if let meta {
                Text(meta)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let asking, let prompt = asking.prompt, let draft {
                Text(prompt)
                    .font(BBFont.subtitle)
                    .foregroundStyle(BBColor.textSecondary)
                ReviewDraftField(prompt: prompt, key: draft, text: $text, fields: fields)
                ReviewChoiceRow(title: asking.title, isProminent: true, action: onSave)
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button(action: onBack) {
                    Text("Back").frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                }
            } else {
                ForEach(choices) { choice in
                    ReviewChoiceRow(title: choice.title, subtitle: choice.subtitle) { onChoose(choice) }
                }
            }
            if let problem {
                InlineProblemText(message: problem)
            }
        }
    }
}

// MARK: - Previews (M-18 states)

private extension ReviewItemChoice {
    static let waitingChoices = [
        ReviewItemChoice(decision: .keepWaiting, title: "Keep waiting", subtitle: ReviewCopy.keepWaitingSubtitle),
        ReviewItemChoice(decision: .followUp, title: "Create a follow-up", prompt: ReviewCopy.followUpPrompt),
        ReviewItemChoice(decision: .returnToNext, title: "Return to Next", prompt: ReviewCopy.returnPrompt),
        ReviewItemChoice(decision: .cancel, title: "Cancel"),
    ]
}

#Preview("M-18 default") {
    @Previewable @State var text = ""
    ReviewItemContent(
        title: "Pick up the drill", meta: ReviewCopy.waitingMeta(waitingFor: "Sam", days: 9),
        choices: ReviewItemChoice.waitingChoices, asking: nil, draft: nil, text: $text, fields: ReviewFields(),
        problem: nil, onChoose: { _ in }, onSave: {}, onBack: {}, onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-18 follow-up") {
    @Previewable @State var text = "Text Sam about the drill"
    ReviewItemContent(
        title: "Pick up the drill", meta: ReviewCopy.waitingMeta(waitingFor: "Sam", days: 9),
        choices: ReviewItemChoice.waitingChoices, asking: ReviewItemChoice.waitingChoices[1],
        draft: DraftKey.reviewStep(session: ReviewSessionID("review_preview"), step: .waiting, item: "t1"), text: $text,
        fields: ReviewFields(), problem: nil, onChoose: { _ in }, onSave: {}, onBack: {}, onNext: {}
    )
    .environment(ToastCenter())
    .environment(Workspace.preview())
}

#Preview("M-18 archived project") {
    @Previewable @State var text = ""
    ReviewItemContent(
        title: "Pick up the drill", meta: ReviewCopy.waitingMeta(waitingFor: "Sam", days: 9),
        choices: ReviewItemChoice.waitingChoices, asking: nil, draft: nil, text: $text, fields: ReviewFields(),
        problem: ReviewCopy.archivedFollowUp, onChoose: { _ in }, onSave: {}, onBack: {}, onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-18 nothing to chase") {
    @Previewable @State var text = ""
    ReviewItemContent(
        title: ReviewCopy.nothingToChase, meta: nil, choices: [], asking: nil, draft: nil, text: $text,
        fields: ReviewFields(), problem: nil, onChoose: { _ in }, onSave: {}, onBack: {}, onNext: {}
    )
    .environment(ToastCenter())
}

#Preview("M-18 accessibility size") {
    @Previewable @State var text = ""
    ReviewItemContent(
        title: "Pick up the drill", meta: ReviewCopy.waitingMeta(waitingFor: "Sam", days: 9),
        choices: ReviewItemChoice.waitingChoices, asking: nil, draft: nil, text: $text, fields: ReviewFields(),
        problem: nil, onChoose: { _ in }, onSave: {}, onBack: {}, onNext: {}
    )
    .environment(ToastCenter())
    .environment(\.dynamicTypeSize, .accessibility5)
}
