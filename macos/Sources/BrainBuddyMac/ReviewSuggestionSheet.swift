import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyMacCore
import BrainBuddyWorkspace
import SwiftUI

#if canImport(FoundationModels)
    import FoundationModels
#endif

/// Design D-04, the Weekly Review suggestion sheet opened from a task's detail (spec 026 T060).
/// It renders the kit's `ReviewSuggestionModel` (the shared PR-49 state machine, the one the iPhone
/// uses) and holds no state machine of its own: `ReviewSuggestionScreen` maps a phase to words,
/// buttons and the first focus, and the view draws that. A suggestion is a proposal; nothing changes
/// until "Apply suggestion". `VoiceCapture` stays transcription and is not a way in.

/// What the sheet shows for one phase, as plain values (the state mapping the tests read).
struct ReviewSuggestionScreen: Equatable {
    enum Action: Hashable {
        case request, requestAgain, cancel, continueWithoutAI, allowCloud, tryCloudInstead
        case submitAnswer, retrySuggestions, apply, keepCurrentWording, reviewAfterChange
        case keepEditing, discardAnswer, done
    }

    enum Focus: Equatable {
        /// The outcome heading, so VoiceOver starts on what happened.
        case heading
        case answerField
        /// The safe choice of the leave-with-unsaved-answer prompt.
        case keepEditing
    }

    struct Control: Equatable {
        var action: Action
        var title: String
        var prominent = false
        var enabled = true
    }

    /// Everything the mapping reads from the model, so it is testable without one.
    struct Input: Equatable {
        var phase: ReviewSuggestionModel.Phase
        var kind: SuggestionKind
        var cloudPossible: Bool
        var canTryCloud = false
        var answerSaved = false
        var referenceID: String?
        var applyFailure: String?
        var notesTruncated = false
        var question: String?
        var leaving = false
        /// Revoking the cloud consent did not complete; the grant stays current.
        var revokeFailed = false
    }

    var heading: String
    var lines: [String] = []
    var reference: String?
    var buttons: [Control] = []
    var firstFocus = Focus.heading
    /// Said once through a polite announcement when the screen appears (.13-.15, .12).
    var announcement: String?
    var showsProposals = false
    var showsAnswerField = false
    var consentFields: [String] = []

    /// The phase, as a key that changes exactly when the screen does.
    var key: String { heading + "|" + buttons.map(\.title).joined(separator: ",") }

    /// The person's "Your answer" is typed and not yet in the notes: leaving asks first (.20).
    static func leavePrompt() -> ReviewSuggestionScreen {
        ReviewSuggestionScreen(
            heading: "Discard your answer?", lines: ["It hasn't been added to the notes."],
            buttons: [
                Control(action: .keepEditing, title: "Keep editing", prominent: true),
                Control(action: .discardAnswer, title: "Discard"),
            ],
            firstFocus: .keepEditing, showsAnswerField: false)
    }

    /// What the consent lists and the request body field each line stands for (020-FR-019); a test
    /// compares the paths with the encoded `NavigatorSuggestionBody`, so the list cannot drift from it.
    static let sentFieldPaths: [(label: String, path: String)] = [
        ("Task title", "task.title"), ("Task notes", "task.notes"),
        ("Why it stalled, if you chose a reason", "task.stall_reason"), ("Project name", "project.name"),
        ("Up to 20 other open task titles in that project", "project.open_task_titles"),
        ("The kind of suggestion you asked for", "kind"),
    ]

    static var sentFields: [String] { sentFieldPaths.map(\.label) }

    static func make(_ input: Input) -> ReviewSuggestionScreen {
        var screen = base(input)
        if input.revokeFailed, !screen.lines.contains(revokeFailedLine) { screen.lines.append(revokeFailedLine) }
        return screen
    }

    static let revokeFailedLine = "Cloud suggestions could not be turned off. Your consent is still on."

    private static func base(_ input: Input) -> ReviewSuggestionScreen {
        if input.leaving { return leavePrompt() }
        let continueButton = Control(action: .continueWithoutAI, title: "Continue without AI")
        switch input.phase {
        case .idle:
            let intro = input.kind == .firstStep ? "Suggest a first step" : "Suggest clearer wording"
            return ReviewSuggestionScreen(
                heading: intro,
                lines: [
                    input.cloudPossible
                        ? "Suggestions run on this Mac when they can. Cloud suggestions need your consent first."
                        : "Task content stays on this device.",
                    "Nothing changes until you apply a suggestion.",
                ],
                buttons: [Control(action: .request, title: "Request suggestions", prominent: true), continueButton])
        case .requesting:
            return ReviewSuggestionScreen(
                heading: "Preparing suggestions…",
                lines: ["You can close this window. The request keeps running until you cancel it."],
                buttons: [Control(action: .cancel, title: "Cancel"), continueButton])
        case .cancelling:
            return ReviewSuggestionScreen(
                heading: "Stopping suggestions…", lines: ["You can still decide this task yourself."],
                buttons: [Control(action: .cancel, title: "Cancel", enabled: false), continueButton],
                announcement: "Stopping suggestions")
        case .cancelled(let afterTransmission):
            let text =
                afterTransmission
                ? "Suggestions stopped here. The provider may still finish processing data already sent. No result will be applied."
                : "Suggestions cancelled. Nothing was sent."
            return ReviewSuggestionScreen(
                heading: afterTransmission ? "Suggestions stopped" : "Suggestions cancelled", lines: [text],
                buttons: [continueButton, Control(action: .requestAgain, title: "Request again")], announcement: text)
        case .interrupted(let mayHaveBeenSent):
            let text =
                "Suggestions were interrupted. Nothing was applied."
                + (mayHaveBeenSent ? " The provider may have received the request." : "")
            return ReviewSuggestionScreen(
                heading: "Suggestions were interrupted", lines: [text], reference: input.referenceID,
                buttons: [continueButton, Control(action: .requestAgain, title: "Request again")], announcement: text)
        case .needsConsent(let provider, _, let state):
            var lines = [
                "Brain Buddy would send these to \(provider):",
                "Notes are sent as written, including any names in them.",
            ]
            if state == .textOutdated { lines.insert("The consent text changed since you last allowed it.", at: 0) }
            return ReviewSuggestionScreen(
                heading: "Use cloud suggestions?", lines: lines,
                buttons: [Control(action: .allowCloud, title: "Allow cloud suggestions", prominent: true), continueButton],
                consentFields: sentFields)
        case .consentOff:
            return ReviewSuggestionScreen(
                heading: "Cloud suggestions are off", lines: ["New requests are not made. Nothing was sent."],
                buttons: [continueButton, Control(action: .requestAgain, title: "Request again")])
        case .unavailable(let reason):
            return unavailable(reason, input, saved: false)
        case .answerSavedSuggestionFailed(let reason):
            var screen = unavailable(reason, input, saved: true)
            screen.heading = "Your answer was saved. Suggestions aren't available."
            screen.buttons = [
                Control(action: .retrySuggestions, title: "Try suggestions again", prominent: true),
                Control(action: .continueWithoutAI, title: "I'll write my own step"),
            ]
            return screen
        case .noSuggestion:
            return ReviewSuggestionScreen(
                heading: "No suggestion this time", lines: ["You can still decide this task yourself."],
                buttons: [continueButton, Control(action: .requestAgain, title: "Request again")])
        case .proposals:
            var lines = ["Nothing changes until you apply."]
            if input.notesTruncated { lines.append("Part of the notes was not considered.") }
            if let code = input.applyFailure { lines.append("Couldn't apply the suggestion (\(code)). It is unchanged.") }
            return ReviewSuggestionScreen(
                heading: "Review suggestion", lines: lines,
                buttons: [
                    Control(action: .apply, title: "Apply suggestion", prominent: true),
                    Control(action: .keepCurrentWording, title: "Keep current wording"),
                ], showsProposals: true)
        case .question:
            return ReviewSuggestionScreen(
                heading: input.question ?? "One question first",
                buttons: [
                    Control(action: .submitAnswer, title: "Add to notes and suggest again", prominent: true),
                    Control(action: .continueWithoutAI, title: "I'll write my own step"),
                ], firstFocus: .answerField, showsAnswerField: true)
        case .savingAnswer:
            return ReviewSuggestionScreen(heading: "Saving…", lines: ["Adding your answer to the notes."])
        case .answerNotSaved(let failure):
            var lines = ["Couldn't add your answer to the notes. Your answer is saved here."]
            switch failure {
            case .conflict: lines.append("This task changed since you opened it. Adding again uses the current notes.")
            case .unknownOutcome: lines.append("It isn't clear whether the first try went through. Retrying never adds it twice.")
            case .rejected: break
            }
            var reference = input.referenceID
            if case .rejected(let code) = failure { reference = code }
            return ReviewSuggestionScreen(
                heading: "Your answer isn't in the notes yet", lines: lines, reference: reference,
                buttons: [
                    Control(action: .submitAnswer, title: "Retry", prominent: true),
                    Control(action: .continueWithoutAI, title: "I'll write my own step"),
                ], firstFocus: .answerField, showsAnswerField: true)
        case .stale:
            return ReviewSuggestionScreen(
                heading: "This task changed",
                lines: ["This task changed. Review it before applying a suggestion."],
                buttons: [
                    Control(action: .reviewAfterChange, title: "Review the task", prominent: true),
                    Control(action: .keepCurrentWording, title: "Keep current wording"),
                ], showsProposals: true)
        case .applying:
            return ReviewSuggestionScreen(heading: "Applying…")
        case .applied:
            return ReviewSuggestionScreen(
                heading: "Suggestion applied", lines: ["The task now reads as you chose. You can still edit it."],
                buttons: [Control(action: .done, title: "Done", prominent: true)], announcement: "Suggestion applied")
        case .manual:
            return ReviewSuggestionScreen(
                heading: "Continue without AI", lines: ["Nothing was sent and nothing changed. You can decide this yourself."],
                buttons: [Control(action: .done, title: "Done", prominent: true)])
        }
    }

    private static func unavailable(
        _ reason: ReviewSuggestionModel.Unavailable, _ input: Input, saved: Bool
    ) -> ReviewSuggestionScreen {
        var screen = ReviewSuggestionScreen(
            heading: "Suggestions aren't available. You can continue without AI.", reference: input.referenceID)
        var buttons = [Control(action: .continueWithoutAI, title: "Continue without AI")]
        switch reason {
        case .localUnavailable(let reasons):
            screen.heading = "On-device suggestions aren't available for this task"
            screen.lines = reasons.map { localReason($0.reason) }
        case .localFailed:
            screen.lines = ["The on-device model couldn't answer. Nothing was sent."]
            if input.canTryCloud { buttons.append(Control(action: .tryCloudInstead, title: "Try cloud suggestions instead")) }
        case .remoteOff: screen.lines = ["Cloud suggestions aren't available."]
        case .signedOut: screen.lines = ["Sign in to use cloud suggestions."]
        case .rateLimited: screen.lines = ["Too many requests. Try again in a few minutes."]
        case .providerError: screen.lines = ["The suggestion service didn't answer."]
        case .invalidProposal: screen.lines = ["The answer couldn't be used. Nothing changed."]
        case .inputTooLarge: screen.lines = ["This task has too much text for a suggestion."]
        case .taskGone: screen.lines = ["This task is no longer available."]
        case .journalFailed:
            screen.lines = ["This Mac couldn't save its local record of the request, so nothing was sent."]
        case .consentChangeFailed:
            screen.lines = ["Cloud suggestions could not be turned off. Your consent is still on."]
        }
        if !saved { buttons.append(Control(action: .requestAgain, title: "Request again")) }
        screen.buttons = buttons
        return screen
    }

    static func localReason(_ reason: LocalAIUnavailableReason) -> String {
        switch reason {
        case .deviceNotEligible: "This Mac can't run on-device suggestions."
        case .systemFeatureOff: "Apple Intelligence is turned off."
        case .modelNotReady: "The on-device model isn't ready yet."
        case .notDownloaded: "The on-device model isn't downloaded."
        case .disabled: "On-device suggestions are turned off."
        case .unsupportedLanguage: "This task's language isn't supported on this Mac."
        case .insufficientMemory: "There isn't enough free memory for on-device suggestions."
        case .failedThisRequest: "On-device suggestions failed for this request."
        }
    }
}

extension ReviewSuggestionScreen.Input {
    @MainActor
    init(_ model: ReviewSuggestionModel, cloudPossible: Bool, leaving: Bool) {
        self.init(
            phase: model.phase, kind: model.kind, cloudPossible: cloudPossible, canTryCloud: model.canTryCloud,
            answerSaved: model.answerSaved, referenceID: model.referenceID, applyFailure: model.applyFailure,
            notesTruncated: model.notesTruncated, question: model.question, leaving: leaving,
            revokeFailed: model.revokeFailed)
    }
}

/// Opens (or finds) the shared model for one task and kind, then shows the sheet. The model outlives
/// the sheet in the workspace, so closing is not Cancel and a live request is found on reopening.
struct ReviewSuggestionSheetLoader: View {
    let model: BrainBuddyModel
    let taskID: TaskID
    let kind: SuggestionKind
    let onClose: () -> Void
    @State private var suggestion: ReviewSuggestionModel?

    init(model: BrainBuddyModel, task: TaskRecord, kind: SuggestionKind, onClose: @escaping () -> Void) {
        self.model = model
        taskID = task.id
        self.kind = kind
        self.onClose = onClose
        let adapter = model.reviewSuggestionAdapter(executors: MacLocalAI.executors)
        _suggestion = State(initialValue: adapter.flatMap { model.reviewSuggestionModel(for: task, kind: kind, adapter: $0) })
    }

    var body: some View {
        if let suggestion {
            ReviewSuggestionSheet(
                suggestion: suggestion, taskTitle: model.workspace.task(taskID)?.title ?? "",
                cloudPossible: model.workspace.account != nil || model.navigatorRemote != nil, onClose: onClose,
                onFinish: {
                    model.releaseReviewSuggestion(for: taskID, kind: kind)
                    onClose()
                })
        } else {
            VStack(alignment: .leading, spacing: 12) {
                Text("Suggestions aren't available for this task").font(.title3.bold())
                    .accessibilityAddTraits(.isHeader)
                Text("You can still decide it yourself.")
                HStack {
                    Spacer()
                    Button("Close", action: onClose).keyboardShortcut(.cancelAction)
                }
            }
            .padding(24)
            .frame(width: 440)
        }
    }
}

struct ReviewSuggestionSheet: View {
    @Bindable var suggestion: ReviewSuggestionModel
    let taskTitle: String
    let cloudPossible: Bool
    let onClose: () -> Void
    let onFinish: () -> Void

    @State private var leaving = false
    @State private var selected = 0
    @State private var proposalText = ""
    @State private var savingShown = false
    @FocusState private var focus: ReviewSuggestionScreen.Focus?

    private var screen: ReviewSuggestionScreen {
        .make(.init(suggestion, cloudPossible: cloudPossible, leaving: leaving && suggestion.hasUnsavedAnswer))
    }

    var body: some View {
        let screen = screen
        // A fresh identity per screen: each starts with its own default focus (the outcome heading,
        // the answer field, or the safe choice), and nothing outside the view moves focus.
        VStack(alignment: .leading, spacing: 14) {
            content(screen)
        }
        .id(screen.key)
        .defaultFocus($focus, screen.firstFocus)
        .padding(24)
        .frame(width: 480)
        .task { await suggestion.recover() }
        .task(id: screen.key) {
            if let text = screen.announcement { AccessibilityNotification.Announcement(text).post() }
        }
        .task(id: suggestion.phase == .savingAnswer) {
            guard suggestion.phase == .savingAnswer else { savingShown = false; return }
            try? await Task.sleep(for: .milliseconds(300))
            savingShown = suggestion.phase == .savingAnswer
        }
        .onChange(of: suggestion.proposals, initial: true) { _, proposals in
            selected = 0
            if let first = proposals.first { proposalText = first }
        }
        .interactiveDismissDisabled(suggestion.hasUnsavedAnswer)
    }

    @ViewBuilder
    private func content(_ screen: ReviewSuggestionScreen) -> some View {
        // Until 300 ms have passed, a save keeps showing the question (no flicker for a fast save).
        if suggestion.phase == .savingAnswer && !savingShown {
            let question = ReviewSuggestionScreen.make(
                .init(phase: .question, kind: suggestion.kind, cloudPossible: cloudPossible, question: suggestion.question))
            render(question, enabled: false)
        } else {
            render(screen, enabled: true)
        }
    }

    private func render(_ screen: ReviewSuggestionScreen, enabled: Bool) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            if !taskTitle.isEmpty {
                Text(taskTitle).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                    .accessibilityLabel("Task: \(taskTitle)")
            }
            Text(screen.heading)
                .font(.title3.bold())
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
                .focusable()
                .focused($focus, equals: .heading)
            ForEach(screen.lines, id: \.self) { line in
                Text(line).font(.callout).fixedSize(horizontal: false, vertical: true)
            }
            if !screen.consentFields.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(screen.consentFields, id: \.self) { Label($0, systemImage: "circle.fill").labelStyle(.titleOnly) }
                }
                .font(.callout)
                .padding(.leading, 12)
                .accessibilityElement(children: .combine)
            }
            if let reference = screen.reference {
                HStack(spacing: 6) {
                    Text("Reference \(reference)").font(.caption.monospaced()).textSelection(.enabled)
                    SwiftUI.Button("Copy") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(reference, forType: .string)
                        AccessibilityNotification.Announcement("Copied").post()
                    }
                    .buttonStyle(.link)
                    .font(.caption)
                }
            }
            if screen.showsProposals { proposals }
            if screen.showsAnswerField { answerField }
            actions(screen)
        }
        .disabled(!enabled)
    }

    // MARK: Proposals (.10, .11)

    private var proposals: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(suggestion.proposals.enumerated()), id: \.offset) { index, text in
                SwiftUI.Button {
                    selected = index
                    proposalText = text
                } label: {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: selected == index ? "largecircle.fill.circle" : "circle")
                        Text(text).multilineTextAlignment(.leading)
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Suggestion \(index + 1) of \(suggestion.proposals.count): \(text)")
                .accessibilityValue(selected == index ? "Selected" : "Not selected")
                .accessibilityAddTraits(.isButton)
            }
            Text("Edit before applying").font(.caption).foregroundStyle(.secondary)
            TextField("Suggestion, editable", text: $proposalText, axis: .vertical)
                .lineLimit(1...3)
                .textFieldStyle(.roundedBorder)
        }
    }

    // MARK: Clarifying question (.16-.20)

    private var answerField: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Your answer").font(.callout.weight(.medium))
            TextEditor(text: $suggestion.answerDraft)
                .font(.body)
                .frame(minHeight: 72, maxHeight: 140)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(.secondary.opacity(0.4)))
                .focused($focus, equals: .answerField)
                .accessibilityLabel("Your answer")
            Text("It is added to this task's notes only when you choose Add to notes and suggest again.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    // MARK: Buttons

    private func actions(_ screen: ReviewSuggestionScreen) -> some View {
        HStack {
            if !screen.buttons.contains(where: { $0.action == .keepEditing }) && !isFinal(screen) {
                SwiftUI.Button("Close") { close() }
                    .keyboardShortcut(.cancelAction)
                    .help("Closing keeps a running request. It does not cancel it.")
            }
            Spacer()
            ForEach(screen.buttons, id: \.action) { button in
                let view = SwiftUI.Button(button.title) { perform(button.action) }
                    .disabled(!button.enabled || !isEnabled(button.action))
                if button.action == .keepEditing {
                    view.focused($focus, equals: .keepEditing).keyboardShortcut(.cancelAction)
                        .buttonStyle(.borderedProminent)
                } else if button.prominent {
                    view.keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent)
                } else {
                    view
                }
            }
        }
    }

    private func isFinal(_ screen: ReviewSuggestionScreen) -> Bool { screen.buttons.contains { $0.action == .done } }

    private func isEnabled(_ action: ReviewSuggestionScreen.Action) -> Bool {
        switch action {
        case .submitAnswer: !suggestion.answerDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .apply: !proposalText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        default: true
        }
    }

    private func close() {
        if suggestion.hasUnsavedAnswer {
            leaving = true
        } else {
            onClose()
        }
    }

    private func perform(_ action: ReviewSuggestionScreen.Action) {
        switch action {
        case .request, .requestAgain: suggestion.request()
        case .cancel: Task { await suggestion.cancel() }
        case .continueWithoutAI: Task { await suggestion.continueWithoutAI() }
        case .allowCloud: Task { await suggestion.allowCloud() }
        case .tryCloudInstead: suggestion.tryCloudInstead()
        case .submitAnswer: suggestion.submitAnswer()
        case .retrySuggestions: suggestion.retrySuggestions()
        case .apply: Task { await suggestion.apply(proposalText) }
        case .keepCurrentWording: suggestion.keepCurrentWording()
        case .reviewAfterChange: suggestion.reviewAfterChange()
        case .keepEditing: leaving = false
        case .discardAnswer:
            suggestion.discardAnswer()
            leaving = false
            onFinish()
        case .done: onFinish()
        }
    }
}

// MARK: On-device executor

/// The Mac's on-device executors. Apple's Foundation Models are offered only through the shared
/// policy, which reads `facts()`: a Mac that is not eligible, has Apple Intelligence off or has no
/// ready model reports why and is never asked. No weights are bundled and nothing is downloaded here.
enum MacLocalAI {
    static var executors: [any LocalAIExecutor] {
        #if canImport(FoundationModels)
            [FoundationModelsExecutor()]
        #else
            []
        #endif
    }
}

#if canImport(FoundationModels)
    @Generable
    private struct GeneratedNavigatorAnswer {
        @Guide(description: "Up to three distinct wordings of the task. Empty only when a question is needed first.")
        var proposals: [String]
        @Guide(description: "One short question, only when no wording can be suggested without more information.")
        var clarifyingQuestion: String?
    }

    struct FoundationModelsExecutor: LocalAIExecutor {
        let source = LocalAISource.appleOnDevice

        func facts() async -> LocalAIFacts {
            let model = SystemLanguageModel.default
            let runtime: LocalAIRuntime
            switch model.availability {
            case .available: runtime = .ready
            case .unavailable(.deviceNotEligible): runtime = .deviceNotEligible
            case .unavailable(.appleIntelligenceNotEnabled): runtime = .systemFeatureOff
            case .unavailable(.modelNotReady): runtime = .modelNotReady
            case .unavailable: runtime = .modelNotReady
            }
            let languages = model.supportedLanguages.compactMap { $0.languageCode?.identifier }
            // The system keeps the model resident and manages its memory, so the app has no figure
            // to compare: the requirement is stated as zero rather than inventing a free amount.
            return LocalAIFacts(
                source: .appleOnDevice, runtime: runtime, supportedLanguages: languages,
                freeMemoryMB: ProcessInfo.processInfo.physicalMemory / 1_048_576, requiredMemoryMB: 0)
        }

        func suggest(_ input: SuggestionInput, terms: AITerms) async throws -> ModelAnswer {
            let session = LanguageModelSession(instructions: Self.instructions(for: input.kind))
            let options = GenerationOptions(maximumResponseTokens: Int(terms.maxOutputTokens))
            let answer = try await session.respond(
                to: Self.prompt(for: input), generating: GeneratedNavigatorAnswer.self, options: options)
            return ModelAnswer(proposals: answer.content.proposals, clarifyingQuestion: answer.content.clarifyingQuestion)
        }

        private static func instructions(for kind: SuggestionKind) -> String {
            let goal =
                switch kind {
                case .firstStep: "Suggest the smallest concrete first step that gets this task moving."
                case .reformulate: "Suggest clearer wordings of this task as one concrete next action that starts with a verb."
                case .projectNextAction: "Suggest the next concrete action for this project."
                }
            return """
                \(goal) Answer in the language of the task. Each suggestion is one short line, under 100 \
                characters, with no numbering. Never invent facts about the person. If you cannot suggest \
                anything without more information, give no suggestions and ask one short question.
                """
        }

        private static func prompt(for input: SuggestionInput) -> String {
            var parts = ["Task: \(input.taskTitle ?? "")"]
            if let notes = input.taskNotes { parts.append("Notes: \(notes)") }
            if let reason = input.stallReason { parts.append("Why it stalled: \(reason)") }
            if let project = input.projectName { parts.append("Project: \(project)") }
            if !input.openTaskTitles.isEmpty {
                parts.append("Other open tasks in the project: " + input.openTaskTitles.joined(separator: "; "))
            }
            return parts.joined(separator: "\n")
        }
    }
#endif
