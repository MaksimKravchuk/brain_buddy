import BrainBuddyCore
import BrainBuddyWorkspace
import Observation
import SwiftUI

// MARK: - Launch and context

/// What the review cover starts from (M-11).
enum ReviewLaunch: Identifiable, Hashable {
    case new(ReviewMode)
    case resume(ReviewSessionID)

    var id: String {
        switch self {
        case .new(let mode): "new-\(mode.rawValue)"
        case .resume(let id): "resume-\(id.rawValue)"
        }
    }
}

/// What a step needs from the cover around it.
struct ReviewStepContext {
    let sessionID: ReviewSessionID
    let fields: ReviewFields
    /// Next: finishes the step and moves on (asking first about unsaved text).
    let advance: () -> Void
    /// Done on the summary, with the optional answer.
    let finish: (ClearStart?) -> Void
}

/// The fields of the step on screen that hold text not saved yet (FR-052).
/// Leave, Skip and Next ask before it is lost.
@MainActor
@Observable
final class ReviewFields {
    private(set) var dirty: Set<DraftKey> = []
    private var messages: [DraftKey: String] = [:]
    private var editorID = UUID().uuidString

    init() {}

    var hasUnsavedText: Bool { !dirty.isEmpty }

    /// What the question names: the field's own words, else the general ones.
    var unsavedMessage: String { messages.values.first ?? ReviewCopy.discardTypedTitle }

    func set(_ key: DraftKey, dirty isDirty: Bool, message: String? = nil) {
        if isDirty { dirty.insert(key) } else { dirty.remove(key) }
        messages[key] = isDirty ? message : nil
    }

    /// Discard: the drafts go with the text.
    func discard(in workspace: Workspace) async throws {
        for key in dirty { try await workspace.discardDraft(for: key, editorID: editorID) }
        dirty = []
        messages = [:]
    }
}

extension ReviewStepContext {
    /// A context for previews of the steps.
    @MainActor static let preview = ReviewStepContext(
        sessionID: ReviewSessionID("review_preview"), fields: ReviewFields(), advance: {}, finish: { _ in }
    )
}

// MARK: - The cover

/// The weekly review, full screen (M-10 – M-22, spec 020). First the screens
/// the entry order puts ahead of the steps that are due (onboarding, "While
/// you were away", restart: `Workspace.reviewEntryScreens`), then the run's
/// steps one at a time. The cover only chooses what is on screen and records
/// progress (`Workspace.recordReviewProgress`, merged and replay-safe); every
/// rule, count and queue is Core's. Leave and Skip are at the top, the
/// primary action at the bottom of each step, and "N of M" with the step
/// segments scrolls sideways at accessibility text sizes (`ReviewLayout`).
/// Leaving keeps everything: the run stays open on this and every device.
struct ReviewCover: View {
    let launch: ReviewLaunch

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var prelude: [ReviewScreen] = []
    @State private var sessionID: ReviewSessionID?
    @State private var step: ReviewStep = .wins
    @State private var hasLoaded = false
    @State private var editorID = UUID().uuidString
    @State private var problem: String?
    @State private var isSaving = false
    @State private var fields = ReviewFields()
    @State private var activity = ActiveTimeAccumulator()
    @State private var sentSeconds: [ReviewStep: Int] = [:]
    @State private var pendingExit: Exit?
    @State private var asksToDiscard = false
    @State private var asksToLeave = false
    @State private var movedOnNote: String?
    private enum Exit {
        case leave
        case skip
        case next
    }

    init(launch: ReviewLaunch) {
        self.launch = launch
    }

    private var session: ReviewSession? { sessionID.flatMap { workspace.state.review.sessions[$0] } }

    var body: some View {
        content
            .bbScreenBackground()
            .toastMagicTap()
            .overlay {
                let stateReadiness = workspace.reviewReadiness(.state)
                let summaryReadiness = workspace.reviewReadiness(.summary(nil))
                let readiness = stateReadiness == .ready ? summaryReadiness : stateReadiness
                if readiness != .ready {
                    WorkspaceQueryContent(readiness: readiness, retry: {
                        Task { try? await workspace.prepareReviewRead(.state); try? await workspace.prepareReviewRead(.summary(nil)); load() }
                    }) { EmptyView() }
                }
            }
            .sheet(
                isPresented: Binding(
                    get: { prelude.first == .whileAway },
                    set: { if !$0, prelude.first == .whileAway { advancePrelude() } }
                )
            ) {
                WhileYouWereAwaySheet()
            }
            .confirmationDialog(ReviewCopy.leaveTitle, isPresented: $asksToLeave, titleVisibility: .visible) {
                Button(ReviewCopy.leave, action: leaveNow)
                Button(ReviewCopy.keepGoing, role: .cancel) {}
            } message: {
                Text(ReviewCopy.leaveMessage(step: stepNumber))
            }
            .alert(fields.unsavedMessage, isPresented: $asksToDiscard) {
                // The cancel role makes "Keep editing" the default (FR-052).
                Button(ReviewCopy.keepEditing, role: .cancel) { pendingExit = nil }
                Button(ReviewCopy.discard, role: .destructive) {
                    Task {
                        do {
                            try await fields.discard(in: workspace)
                            if let exit = pendingExit { perform(exit) }
                        } catch { problem = TaskCommandRunner.message(for: error) }
                    }
                }
            }
            .task { try? await workspace.prepareReviewRead(.state); try? await workspace.prepareReviewRead(.summary(nil)); load() }
            .onChange(of: workspace.reviewExposed) { _, exposed in
                if !exposed { dismiss() }
            }
            .onChange(of: scenePhase) { _, phase in
                activity.record(phase == .active ? .foreground : .background, at: Date())
            }
            .onChange(of: session?.currentStep) { _, merged in
                // Another device continued this review: jump to its step.
                guard let session, session.movedOnElsewhere, let merged, merged != step else { return }
                movedOnNote = ReviewCopy.reviewMovedOn(toStep: (session.mode.steps.firstIndex(of: merged) ?? 0) + 1)
                step = merged
            }
    }

    @ViewBuilder private var content: some View {
        if let screen = prelude.first {
            preludeView(screen)
        } else if let session {
            if session.status == .open { run(session) } else { ended(session) }
        } else if let problem {
            InlineProblemText(message: problem)
                .padding(BBSpacing.s4)
        } else {
            Color.clear
        }
    }

    // MARK: Before the steps

    private func load() {
        guard !hasLoaded else { return }
        hasLoaded = true
        // The explainer is shown at app open, and the mode picker is the entry screen.
        prelude = workspace.reviewEntryScreens(for: .list).filter { screen in
            switch screen {
            case .onboarding, .whileAway, .restart: true
            case .explainer, .modePicker, .resume, .quickReview: false
            }
        }
        if prelude.isEmpty { Task { await beginDurably() } }
    }

    @ViewBuilder private func preludeView(_ screen: ReviewScreen) -> some View {
        switch screen {
        case .onboarding, .restart:
            VStack(spacing: 0) {
                HStack {
                    Button("Close") { dismiss() }
                        .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                    Spacer()
                }
                .padding(.horizontal, BBSpacing.s4)
                if screen == .onboarding {
                    OnboardingScreen(onDone: advancePrelude)
                } else {
                    RestartScreen(onStart: advancePrelude)
                }
            }
        case .explainer, .whileAway, .modePicker, .resume, .quickReview:
            // "While you were away" is a sheet over this.
            Color.clear
        }
    }

    private func advancePrelude() {
        guard !prelude.isEmpty else { return }
        prelude.removeFirst()
        if prelude.isEmpty { Task { await beginDurably() } }
    }

    /// Starts the chosen review (replacing an open one, FR-029) or picks up
    /// the one being resumed.
    private func begin() {
        Task { await beginDurably() }
    }

    @MainActor private func beginDurably() async {
        guard sessionID == nil, !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        let id: ReviewSessionID
        switch launch {
        case .new(let mode):
            do {
                id = try await workspace.startReview(mode: mode, entry: .list, editorID: editorID)
            } catch {
                problem = TaskCommandRunner.message(for: error)
                return
            }
        case .resume(let resumed):
            id = resumed
        }
        sessionID = id
        if let started = workspace.state.review.sessions[id] {
            step = started.currentStep ?? started.mode.steps[0]
        }
        activity.record(.enterStep(step), at: Date())
    }

    // MARK: The run

    private var stepNumber: Int { ((session?.mode.steps.firstIndex(of: step)) ?? 0) + 1 }

    private func run(_ session: ReviewSession) -> some View {
        VStack(spacing: 0) {
            topBar(session)
            if let note = movedOnNote ?? problem {
                Text(note)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, BBSpacing.s4)
            }
            stepView(session)
                .id(step)
                .transition(.opacity)
        }
        .simultaneousGesture(TapGesture().onEnded { activity.record(.interaction, at: Date()) })
    }

    @ViewBuilder private func stepView(_ session: ReviewSession) -> some View {
        let context = ReviewStepContext(
            sessionID: session.id, fields: fields, advance: { attempt(.next) }, finish: finish
        )
        switch step {
        case .wins: WinsStep(context: context)
        case .mindSweep: MindSweepStep(context: context)
        case .inbox: InboxStep(context: context)
        case .decisions: DecisionsStep(context: context)
        case .restOfNext: RestOfNextStep(context: context)
        case .waiting: WaitingStep(context: context)
        case .projects: ProjectsStep(context: context)
        case .someday: SomedayStep(context: context)
        case .dates: DatesStep(context: context)
        case .summary: SummaryStep(context: context)
        }
    }

    private func topBar(_ session: ReviewSession) -> some View {
        let steps = session.mode.steps
        return VStack(spacing: BBSpacing.s1) {
            HStack {
                Button(ReviewCopy.leave) { attempt(.leave) }
                    .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                Spacer()
                if step != .summary {
                    Button(ReviewCopy.skip) { attempt(.skip) }
                        .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                }
            }
            stepBar(session, steps: steps)
        }
        .padding(.horizontal, BBSpacing.s4)
    }

    /// "N of M" and one segment per step; a skipped step is dashed. It scrolls
    /// sideways exactly at accessibility sizes instead of shrinking its text.
    @ViewBuilder private func stepBar(_ session: ReviewSession, steps: [ReviewStep]) -> some View {
        let bar = HStack(spacing: BBSpacing.s2) {
            Text(ReviewCopy.stepPosition(stepNumber, of: steps.count))
                .font(BBFont.subtitle.monospacedDigit())
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize()
            ForEach(steps, id: \.self) { item in
                segment(for: item, status: session.steps[item] ?? .pending)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(ReviewCopy.stepPosition(stepNumber, of: steps.count)): \(ReviewCopy.stepTitle(step))")
        if ReviewLayout.stepBarScrolls(isAccessibilitySize: dynamicTypeSize.isAccessibilitySize) {
            ScrollView(.horizontal, showsIndicators: false) { bar }
        } else {
            bar
        }
    }

    @ViewBuilder private func segment(for item: ReviewStep, status: StepStatus) -> some View {
        if status == .skipped {
            Capsule()
                .strokeBorder(BBColor.controlStroke, style: StrokeStyle(lineWidth: 1.5, dash: [3, 2]))
                .frame(width: 24, height: 6)
        } else {
            Capsule()
                .fill(status == .finished || item == step ? BBColor.brandText : BBColor.hairlineStrong)
                .frame(width: 24, height: 6)
        }
    }

    // MARK: Moving on

    private func attempt(_ exit: Exit) {
        if fields.hasUnsavedText {
            pendingExit = exit
            asksToDiscard = true
        } else {
            perform(exit)
        }
    }

    private func perform(_ exit: Exit) {
        pendingExit = nil
        switch exit {
        case .leave: asksToLeave = true
        case .skip: move(.skipped)
        case .next: move(.finished)
        }
    }

    /// Records the step as `status` with its active time and moves to the next.
    private func move(_ status: StepStatus) {
        guard !isSaving else { return }
        isSaving = true
        Task { await moveDurably(status) }
    }

    @MainActor private func moveDurably(_ status: StepStatus) async {
        defer { isSaving = false }
        guard let session, let index = session.mode.steps.firstIndex(of: step) else { return }
        let upcoming = index + 1 < session.mode.steps.count ? session.mode.steps[index + 1] : nil
        let seconds = unsentSeconds(for: step)
        do {
            try await workspace.recordReviewProgress(
                session.id, currentStep: upcoming, step: step, stepStatus: status,
                activeStep: seconds == nil ? nil : step, activeSeconds: seconds, editorID: editorID
            )
        } catch {
            problem = TaskCommandRunner.message(for: error)
            return
        }
        problem = nil
        movedOnNote = nil
        sentSeconds[step, default: 0] += seconds ?? 0
        guard let upcoming else { return }
        activity.record(.enterStep(upcoming), at: Date())
        withAnimation(BBMotion.animation(.base, reduceMotion: reduceMotion)) { step = upcoming }
    }

    private func unsentSeconds(for step: ReviewStep) -> Int? {
        let delta = (activity.secondsByStep[step] ?? 0) - (sentSeconds[step] ?? 0)
        return delta > 0 ? delta : nil
    }

    /// The step's active time is sent before the review is left or finished.
    @MainActor private func sendActiveTime() async -> Bool {
        guard let id = sessionID, let seconds = unsentSeconds(for: step) else { return true }
        do {
            try await workspace.recordReviewProgress(id, activeStep: step, activeSeconds: seconds, editorID: editorID)
            sentSeconds[step, default: 0] += seconds
            return true
        } catch {
            problem = TaskCommandRunner.message(for: error)
            return false
        }
    }

    private func leaveNow() {
        Task { guard await sendActiveTime() else { return }; activity.record(.leave, at: Date()); dismiss() }
    }

    private func finish(_ clearStart: ClearStart?) {
        guard !isSaving else { return }
        isSaving = true
        Task { await finishDurably(clearStart) }
    }

    @MainActor private func finishDurably(_ clearStart: ClearStart?) async {
        defer { isSaving = false }
        guard let id = sessionID else { return }
        guard await sendActiveTime() else { return }
        do {
            try await workspace.finishReview(id, clearStart: clearStart, editorID: editorID)
        } catch {
            problem = TaskCommandRunner.message(for: error)
            return
        }
        dismiss()
    }

    /// M-13: another device finished or replaced this review, or the 7-day
    /// idle rule closed it. Nothing made here is lost.
    private func ended(_ session: ReviewSession) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s4) {
            Text(session.closedForIdleness ? ReviewCopy.reviewClosedIdle : ReviewCopy.reviewEndedElsewhere)
                .font(BBFont.body)
                .foregroundStyle(BBColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Button {
                dismiss()
            } label: {
                Text(ReviewCopy.openTheReview).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            }
            .buttonStyle(.borderedProminent)
            .tint(BBColor.brandFill)
        }
        .padding(BBSpacing.s4)
        .frame(maxHeight: .infinity, alignment: .center)
    }
}

// MARK: - Shared step pieces

/// One step: its heading (where VoiceOver lands on every step change), a
/// scrolling body, and the primary action in the bottom bar, above the
/// Undo status line. At every text size the body scrolls above the bar.
struct ReviewStepFrame<Content: View>: View {
    let title: String
    let primaryTitle: String?
    let primaryEnabled: Bool
    let onPrimary: () -> Void
    let content: Content

    @AccessibilityFocusState private var isTitleFocused: Bool

    init(
        title: String, primaryTitle: String? = nil, primaryEnabled: Bool = true, onPrimary: @escaping () -> Void = {},
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.primaryTitle = primaryTitle
        self.primaryEnabled = primaryEnabled
        self.onPrimary = onPrimary
        self.content = content()
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: BBSpacing.s5) {
                Text(title)
                    .font(BBFont.display)
                    .foregroundStyle(BBColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityFocused($isTitleFocused)
                content
            }
            .padding(BBSpacing.s4)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scrollDismissesKeyboard(.interactively)
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 0) {
                ToastHost()
                if let primaryTitle {
                    Button(action: onPrimary) {
                        Text(primaryTitle).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(BBColor.brandFill)
                    .disabled(!primaryEnabled)
                    .padding(.horizontal, BBSpacing.s4)
                    .padding(.bottom, BBSpacing.s2)
                }
            }
        }
        .onAppear { isTitleFocused = true }
    }
}

/// A full-width choice with a line under it: the mode picker, the Inbox
/// choices and the Waiting and Someday decisions.
struct ReviewChoiceRow: View {
    let title: String
    let subtitle: String?
    let isProminent: Bool
    let action: () -> Void

    init(title: String, subtitle: String? = nil, isProminent: Bool = false, action: @escaping () -> Void) {
        self.title = title
        self.subtitle = subtitle
        self.isProminent = isProminent
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(BBFont.bodyMedium)
                    .foregroundStyle(isProminent ? BBColor.onBrand : BBColor.textPrimary)
                if let subtitle {
                    Text(subtitle)
                        .font(BBFont.meta)
                        .foregroundStyle(isProminent ? BBColor.onBrand : BBColor.textTertiary)
                }
            }
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.horizontal, BBSpacing.s4)
            .padding(.vertical, BBSpacing.s3)
            .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
            .background(
                isProminent ? BBColor.brandFill : BBColor.surfaceRaised,
                in: RoundedRectangle(cornerRadius: BBRadius.row, style: .continuous)
            )
            .overlay {
                RoundedRectangle(cornerRadius: BBRadius.row, style: .continuous)
                    .strokeBorder(BBColor.hairline, lineWidth: 1)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
    }
}

/// A one-line text field whose unsaved text is kept as a device-local draft
/// (never sent), reported to the cover so leaving asks first, and brought
/// back after an app kill (FR-052). `submit` clears the draft.
struct ReviewDraftField: View {
    let prompt: String
    let key: DraftKey
    @Binding var text: String
    let fields: ReviewFields
    /// The question asked about unsaved text, given the text; the general one by default.
    let unsavedMessage: ((String) -> String)?

    @Environment(Workspace.self) private var workspace
    @Environment(\.scenePhase) private var scenePhase
    @State private var hasLoaded = false
    @State private var problem: String?
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false

    init(
        prompt: String, key: DraftKey, text: Binding<String>, fields: ReviewFields,
        unsavedMessage: ((String) -> String)? = nil
    ) {
        self.prompt = prompt
        self.key = key
        _text = text
        self.fields = fields
        self.unsavedMessage = unsavedMessage
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            TextField(prompt, text: $text, axis: .vertical)
                .lineLimit(1...4)
                .submitLabel(.done)
                .padding(BBSpacing.s3)
                .frame(minHeight: BBMetrics.hitTarget)
                .bbCard()
                .accessibilityLabel(prompt)
            if let problem {
                InlineProblemText(message: problem)
                Button("Retry draft save") { Task { await loadDraft(); await persistDraft() } }
                    .frame(minHeight: BBMetrics.hitTarget)
            }
        }
            .task { await loadDraft() }
            .onChange(of: text) { _, _ in report() }
            .task(id: text) {
                // Kept a moment after typing stops, and when the app leaves the foreground.
                try? await Task.sleep(for: .milliseconds(500))
                guard !Task.isCancelled, hasLoaded else { return }
                await persistDraft()
            }
            .onChange(of: scenePhase) { _, phase in
                if phase != .active, hasLoaded { Task { await persistDraft() } }
            }
    }

    @MainActor private func loadDraft() async {
        guard !hasLoaded else { return }
        do {
            if text.isEmpty, let draft = try await workspace.draft(for: key, editorID: editorID) { text = draft }
            hasLoaded = true
            report()
        } catch { problem = TaskCommandRunner.message(for: error) }
    }

    @MainActor private func persistDraft() async {
        guard hasLoaded, !isSaving else { return }
        isSaving = true
        defer { isSaving = false }
        do {
            if isBlank {
                if try await workspace.draft(for: key, editorID: editorID) != nil {
                    try await workspace.discardDraft(for: key, editorID: editorID)
                }
            } else {
                try await workspace.saveDraft(text, for: key, editorID: editorID)
            }
            problem = nil
        } catch { problem = TaskCommandRunner.message(for: error) }
    }

    private var isBlank: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func report() {
        let line = text.trimmingCharacters(in: .whitespacesAndNewlines)
        fields.set(key, dirty: !isBlank, message: unsavedMessage?(line))
    }

    /// The text was saved elsewhere: the draft and the unsaved flag go.
    static func submitted(_ key: DraftKey, in workspace: Workspace, fields: ReviewFields, editorID: String) async throws {
        try await workspace.discardDraft(for: key, editorID: editorID)
        fields.set(key, dirty: false)
    }
}
