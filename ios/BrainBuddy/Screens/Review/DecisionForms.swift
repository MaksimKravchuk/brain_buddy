import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The four two-step decisions of the card (M-04), pushed inside its sheet.
enum DecisionForm: Hashable {
    case reformulate
    case firstStep
    case waiting
    case extend

    /// The form a card decision opens; nil for one-tap decisions.
    init?(_ decision: DecisionType) {
        switch decision {
        case .reformulate: self = .reformulate
        case .firstStep: self = .firstStep
        case .waiting: self = .waiting
        case .extend: self = .extend
        case .complete, .someday, .cancel, .keepWaiting, .followUp, .returnToNext, .keepSomeday: return nil
        }
    }

    var decision: DecisionType {
        switch self {
        case .reformulate: .reformulate
        case .firstStep: .firstStep
        case .waiting: .waiting
        case .extend: .extend
        }
    }

    /// The device-local draft this form keeps its unsaved text in (FR-052).
    var draftKind: DraftKey.FormKind {
        switch self {
        case .reformulate: .reformulate
        case .firstStep: .firstStep
        case .waiting: .waitingFor
        case .extend: .extensionReason
        }
    }
}

/// M-04 (spec 020): one field and one confirming button per two-step
/// decision. Unsaved text never goes without a choice (FR-052): it is kept as
/// a device-local draft (keyed by form, task and wording, never sent) while
/// typing and when the app leaves the foreground, Back and Close ask first
/// with "Keep editing" as the default, and the sheet cannot be swiped away
/// while the field is dirty. Reopening the same form for the same wording
/// brings the text back. No Suggest yet (navigator: slice PR-08).
struct DecisionFormView: View {
    let form: DecisionForm
    let taskID: TaskID
    /// The wording the card was opened on; drafts and the decision name it.
    let formulationID: FormulationID?
    let stallReason: StallReason?
    @Binding var isDirty: Bool
    let onSaved: (DecisionID, DecisionType, String) -> Void
    let onStale: () -> Void
    let onCloseCard: () -> Void
    /// The task as the card showed it: any change since makes the save stale.
    let expectedTask: TaskStamp?
    /// Previews only: starts the field with this text instead of a draft.
    private let seedText: String?

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var text = ""
    @State private var hasLoaded = false
    @State private var restoredDraft = false
    @State private var problem: String?
    @State private var confirmsDiscard = false
    @State private var leaveTarget = LeaveTarget.back
    /// The decision was saved (and its drafts removed): a debounced or
    /// background draft write must not bring the text back.
    @State private var didSave = false
    @FocusState private var isFieldFocused: Bool

    private enum LeaveTarget {
        case back
        case closeCard
    }

    init(
        form: DecisionForm, taskID: TaskID, formulationID: FormulationID?, stallReason: StallReason?,
        isDirty: Binding<Bool>, onSaved: @escaping (DecisionID, DecisionType, String) -> Void,
        onStale: @escaping () -> Void, onCloseCard: @escaping () -> Void, expectedTask: TaskStamp? = nil,
        seedText: String? = nil
    ) {
        self.expectedTask = expectedTask
        self.form = form
        self.taskID = taskID
        self.formulationID = formulationID
        self.stallReason = stallReason
        _isDirty = isDirty
        self.onSaved = onSaved
        self.onStale = onStale
        self.onCloseCard = onCloseCard
        self.seedText = seedText
    }

    var body: some View {
        let task = workspace.task(taskID)
        Form {
            Section {
                Text(subheader(task))
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
            }
            Section {
                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...8)
                    .focused($isFieldFocused)
                    .submitLabel(.done)
                    .accessibilityLabel(prompt)
            } header: {
                Text(prompt)
            } footer: {
                footer(task)
            }
            if restoredDraft {
                Section {
                    HStack(alignment: .firstTextBaseline) {
                        Text(ReviewCopy.draftRestored)
                            .font(BBFont.meta)
                            .foregroundStyle(BBColor.textTertiary)
                        Spacer(minLength: BBSpacing.s2)
                        Button(ReviewCopy.clearDraft, action: clearDraft)
                            .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                    }
                }
            }
            if let problem {
                Section {
                    InlineProblemText(message: problem)
                }
            }
            Section {
                Button(action: save) {
                    Text(saveTitle(task))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canSave(task))
            }
            .listRowBackground(Color.clear)
        }
        .navigationTitle(navigationTitle)
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    requestLeave(.back)
                } label: {
                    Label("Back", systemImage: "chevron.backward")
                        .labelStyle(.titleAndIcon)
                }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button("Close") { requestLeave(.closeCard) }
            }
        }
        .alert(ReviewCopy.unsavedTitle, isPresented: $confirmsDiscard) {
            // The cancel role makes "Keep editing" the default (FR-052).
            Button(ReviewCopy.keepEditing, role: .cancel) {}
            Button(ReviewCopy.discard, role: .destructive, action: discardAndLeave)
        }
        .onAppear(perform: load)
        .onChange(of: text) { _, newValue in
            // Every field is one line: Return (or a pasted line break) ends the edit.
            if newValue.contains(where: \.isNewline) {
                text = newValue.split(whereSeparator: \.isNewline).joined(separator: " ")
                isFieldFocused = false
                return
            }
            isDirty = Self.hasUnsavedText(newValue, form: form, title: task?.title ?? "")
        }
        .task(id: text) {
            // Kept on the device a moment after typing stops (and on leaving
            // the foreground, below), so an app kill loses nothing.
            try? await Task.sleep(for: .milliseconds(500))
            guard !Task.isCancelled else { return }
            persistDraft()
        }
        .onChange(of: scenePhase) { _, phase in
            if phase != .active { persistDraft() }
        }
        // The review switched off: the card closes; the typed text is kept.
        .onChange(of: workspace.reviewExposed) { _, exposed in
            if !exposed { persistDraft() }
        }
    }

    // MARK: Copy (design M-04)

    private var navigationTitle: String { ReviewCopy.formTitle(form.decision) }

    private var prompt: String {
        switch form {
        case .reformulate: ReviewCopy.reformulatePrompt
        case .firstStep: ReviewCopy.firstStepPrompt
        case .waiting: ReviewCopy.waitingPrompt
        case .extend: ReviewCopy.extendPrompt
        }
    }

    private var placeholder: String { ReviewCopy.formPlaceholder(form.decision) }

    private func subheader(_ task: TaskRecord?) -> String {
        guard let task else { return "" }
        var parts = [task.title]
        if form == .firstStep, let stallReason {
            parts.append(ReviewCopy.reasonMeta(stallReason))
        } else if form != .waiting, let started = task.formulation?.startedAt {
            parts.append(ReviewCopy.daysInNext(since: started, now: workspace.reviewNow))
        }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private func footer(_ task: TaskRecord?) -> some View {
        if let line = footerText(task) {
            // A plain String: task titles are shown as typed, never as Markdown.
            Text(line)
        }
    }

    private func footerText(_ task: TaskRecord?) -> String? {
        switch form {
        case .reformulate:
            return isCosmetic(task) ? ReviewCopy.cosmeticEdit : ReviewCopy.reformulateFooter
        case .firstStep:
            return ReviewCopy.firstStepFooter(oldTitle: task?.title ?? "")
        case .waiting:
            return ReviewCopy.waitingFooter
        case .extend:
            // Dates are shown in the device's current zone (ios-commands §6).
            guard let dates = extensionDates(task) else { return nil }
            return ReviewCopy.extendFooter(
                asksAgain: ReviewCopy.day(dates.askAt, in: .current), moves: ReviewCopy.day(dates.parkDueAt, in: .current)
            )
        }
    }

    private func saveTitle(_ task: TaskRecord?) -> String {
        switch form {
        case .reformulate:
            return isCosmetic(task) ? ReviewCopy.saveAnyway : ReviewCopy.saveNewWording
        case .firstStep:
            return ReviewCopy.saveFirstStep
        case .waiting:
            return ReviewCopy.moveToWaitingFor
        case .extend:
            guard canSave(task), let dates = extensionDates(task) else { return ReviewCopy.extendNeedsReason }
            return ReviewCopy.keepUntil(ReviewCopy.day(dates.askAt, in: .current))
        }
    }

    // MARK: Rules (Core's, asked, not re-decided)

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    /// FR-002: a changed wording whose formulation key is unchanged.
    private func isCosmetic(_ task: TaskRecord?) -> Bool {
        guard let task, form == .reformulate, Self.hasUnsavedText(text, form: form, title: task.title), !trimmed.isEmpty
        else {
            return false
        }
        return !FormulationKey.isSubstantive(from: task.title, to: trimmed)
    }

    private func canSave(_ task: TaskRecord?) -> Bool {
        guard task != nil else { return false }
        switch form {
        case .reformulate: return isDirty && !trimmed.isEmpty
        case .firstStep, .extend: return !trimmed.isEmpty
        case .waiting: return WaitingForInput.problem(text) == nil
        }
    }

    /// The instants "Keep 7 more days" would give (FR-009), asked of Core in
    /// the workspace's classification zone: asks again 7 days from now,
    /// moves to Someday after that, floors kept.
    private func extensionDates(_ task: TaskRecord?) -> DerivedInstants? {
        guard let task else { return nil }
        return workspace.extensionInstants(of: task.id)
    }

    /// Unsaved text: a changed wording, or anything typed in the other forms.
    static func hasUnsavedText(_ text: String, form: DecisionForm, title: String) -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        switch form {
        case .reformulate: return trimmed != title.trimmingCharacters(in: .whitespacesAndNewlines)
        case .firstStep, .waiting, .extend: return !trimmed.isEmpty
        }
    }

    // MARK: Drafts (FR-052)

    private var draftKey: DraftKey { DraftKey.decisionForm(form.draftKind, task: taskID, formulation: formulationID) }

    private func load() {
        guard !hasLoaded else { return }
        hasLoaded = true
        let title = workspace.task(taskID)?.title ?? ""
        if let seedText {
            text = seedText
        } else if let draft = workspace.draft(for: draftKey) {
            text = draft
            restoredDraft = true
        } else {
            text = form == .reformulate ? title : ""
        }
        isDirty = Self.hasUnsavedText(text, form: form, title: title)
        isFieldFocused = true
    }

    private func persistDraft() {
        guard hasLoaded, seedText == nil, !didSave else { return }
        let title = workspace.task(taskID)?.title ?? ""
        if Self.hasUnsavedText(text, form: form, title: title) {
            workspace.saveDraft(text, for: draftKey)
        } else if workspace.draft(for: draftKey) != nil {
            workspace.discardDraft(for: draftKey)
        }
    }

    private func clearDraft() {
        workspace.discardDraft(for: draftKey)
        restoredDraft = false
        text = form == .reformulate ? (workspace.task(taskID)?.title ?? "") : ""
    }

    // MARK: Leaving

    private func requestLeave(_ target: LeaveTarget) {
        leaveTarget = target
        if isDirty {
            confirmsDiscard = true
        } else {
            leave()
        }
    }

    private func discardAndLeave() {
        workspace.discardDraft(for: draftKey)
        isDirty = false
        leave()
    }

    private func leave() {
        switch leaveTarget {
        case .back: dismiss()
        case .closeCard: onCloseCard()
        }
    }

    // MARK: Saving

    /// Saves on the wording the card was opened on (`formulationID`): when a
    /// sync or another window reformulated the task meanwhile, the reducer
    /// refuses it (`.formulationChanged`), nothing is applied and the card
    /// shows the stale state (FR-011).
    private func save() {
        guard !didSave, let task = workspace.task(taskID), canSave(task) else { return }
        let value = trimmed
        problem = nil
        do {
            let decisionID: DecisionID
            switch form {
            case .reformulate:
                decisionID = try workspace.decide(
                    .reformulate, on: taskID, title: value, stallReason: stallReason, formulationID: formulationID,
                    expectedTask: expectedTask
                )
            case .firstStep:
                decisionID = try workspace.decide(
                    .firstStep, on: taskID, title: value, stallReason: stallReason, formulationID: formulationID,
                    expectedTask: expectedTask
                )
            case .waiting:
                decisionID = try workspace.decide(
                    .waiting, on: taskID, waitingFor: value, stallReason: stallReason, formulationID: formulationID,
                    expectedTask: expectedTask
                )
            case .extend:
                decisionID = try workspace.decide(
                    .extend, on: taskID, reason: value, stallReason: stallReason, formulationID: formulationID,
                    expectedTask: expectedTask
                )
            }
            // `decide` removed the drafts; nothing may write them back.
            didSave = true
            isDirty = false
            // The toast names the new wording when there is one.
            let shown = form == .reformulate || form == .firstStep ? value : task.title
            onSaved(decisionID, form.decision, shown)
        } catch {
            switch error {
            case .formulationChanged, .taskNotFound:
                // The draft stays: it is keyed by the wording, which may be unchanged.
                persistDraft()
                onStale()
            case .decisionNotAllowed:
                problem = ReviewCopy.decisionNotAllowed
            case .reviewUnavailable:
                persistDraft()
                problem = error.message
            default:
                problem = error.message
            }
        }
    }
}

// MARK: - Previews (every M-04 state)

/// A task from the preview workspace's Next list.
@MainActor
private func previewNextTask(_ workspace: Workspace) -> TaskRecord? {
    workspace.list(.list(.next)).sections.first?.tasks.first
}

#Preview("M-04 reformulate") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .reformulate, taskID: task.id, formulationID: task.formulation?.id, stallReason: nil,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {}
            )
        }
    }
    .environment(workspace)
}

#Preview("M-04 reformulate, cosmetic edit only") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .reformulate, taskID: task.id, formulationID: task.formulation?.id, stallReason: nil,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {},
                seedText: task.title.uppercased() + "."
            )
        }
    }
    .environment(workspace)
}

#Preview("M-04 find a first step") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .firstStep, taskID: task.id, formulationID: task.formulation?.id, stallReason: .tooBig,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {}
            )
        }
    }
    .environment(workspace)
}

#Preview("M-04 Waiting for") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .waiting, taskID: task.id, formulationID: task.formulation?.id, stallReason: nil,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {},
                seedText: "Landlord's OK on the budget"
            )
        }
    }
    .environment(workspace)
}

#Preview("M-04 keep 7 more days, empty") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .extend, taskID: task.id, formulationID: task.formulation?.id, stallReason: nil,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {}
            )
        }
    }
    .environment(workspace)
}

#Preview("M-04 keep 7 more days, ready") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .extend, taskID: task.id, formulationID: task.formulation?.id, stallReason: nil,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {},
                seedText: "Starting after the landlord replies on Monday"
            )
        }
    }
    .environment(workspace)
}

#Preview("M-04 accessibility size") {
    @Previewable @State var dirty = false
    let workspace = Workspace.preview()
    NavigationStack {
        if let task = previewNextTask(workspace) {
            DecisionFormView(
                form: .firstStep, taskID: task.id, formulationID: task.formulation?.id, stallReason: .tooBig,
                isDirty: $dirty, onSaved: { _, _, _ in }, onStale: {}, onCloseCard: {}, seedText: "Measure the wall"
            )
        }
    }
    .environment(workspace)
    .environment(\.dynamicTypeSize, .accessibility5)
}
