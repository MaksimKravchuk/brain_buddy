import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import FoundationModels
import SwiftUI
import os

// MARK: - Entry

/// Which suggestion the decision card asked for (`.sheet(item:)`).
struct ReviewSuggestionTarget: Identifiable {
    let kind: SuggestionKind
    var id: String { kind.rawValue }
}

// MARK: - The sheet

/// M-04 (spec 026, T059): the first Weekly Review suggestion request, rendered from PR-49's shared
/// `ReviewSuggestionModel`. The model owns every state, consent and policy decision; this view maps
/// `phase` to copy and calls its actions. Nothing changes in the task until "Apply suggestion".
/// Closing the sheet is not Cancel: the workspace keeps the model, so reopening finds a live request.
struct ReviewSuggestionSheet: View {
    let taskID: TaskID
    let kind: SuggestionKind
    let stallReason: StallReason?
    /// The task as the card showed it; the apply step is checked against it.
    let shown: ShownTask?
    let onApplied: () -> Void

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss
    @State private var model: ReviewSuggestionModel?
    @State private var noAdapter = false
    @State private var edited = ""
    @State private var confirmsDiscard = false
    @AccessibilityFocusState private var outcomeFocused: Bool
    @FocusState private var answerFocused: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: BBSpacing.s4) {
                    if let model { content(model) } else if noAdapter { manualOnly } else { ProgressView() }
                }
                .padding(BBSpacing.s4)
            }
            .bbScreenBackground()
            .navigationTitle(kind == .firstStep ? "Suggest a first step" : "Suggest wording")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close", action: close) } }
        }
        .presentationDetents([.large])
        .interactiveDismissDisabled(isEditingAnswer)
        .alert("Discard your answer?", isPresented: $confirmsDiscard) {
            Button("Keep editing", role: .cancel) { answerFocused = true }
            Button("Discard", role: .destructive) { discardAndLeave() }
        } message: {
            Text("It hasn't been added to the notes.")
        }
        .task { await open() }
        .onChange(of: model?.phase) { _, phase in if let phase { phaseChanged(phase) } }
    }

    // MARK: Lifecycle

    private func open() async {
        guard model == nil else { return }
        guard let adapter = SuggestionEngines.adapter else { noAdapter = true; return }
        let opened = workspace.reviewSuggestionModel(
            for: taskID, kind: kind, stallReason: stallReason, adapter: adapter,
            remote: SuggestionEngines.remote(for: workspace.account),
            privacy: workspace.account == nil ? .onDeviceOnly : .remoteAllowed, shown: shown)
        model = opened
        await opened.recover()
        phaseChanged(opened.phase)
    }

    private func phaseChanged(_ phase: ReviewSuggestionModel.Phase) {
        guard let model else { return }
        switch phase {
        case .applied: leave(applied: true)
        case .manual: leave(applied: false)
        case .question: answerFocused = true
        case .proposals:
            if edited.isEmpty { edited = model.proposals.first ?? "" }
            outcomeFocused = true
        case .requesting: edited = ""
        case .cancelling: announce("Stopping suggestions")
        case .cancelled: announce("Suggestions cancelled")
        case .interrupted: announce("Suggestions were interrupted")
        default: outcomeFocused = true
        }
    }

    /// Stopping, cancelled and interrupted are said once, politely, and focus moves to the outcome.
    private func announce(_ text: String) {
        AccessibilityNotification.Announcement(text).post()
        outcomeFocused = true
    }

    /// Applied, continued manually or discarded: the model is finished and released.
    private func leave(applied: Bool) {
        workspace.releaseReviewSuggestionModel(for: taskID, kind: kind)
        if applied { onApplied() }
        dismiss()
    }

    private var isEditingAnswer: Bool {
        guard let model, model.hasUnsavedAnswer else { return false }
        switch model.phase {
        case .question, .answerNotSaved: return true
        default: return false
        }
    }

    /// Back or Close with a typed, unsubmitted answer asks first (.20); otherwise the request stays live.
    private func close() {
        if isEditingAnswer { confirmsDiscard = true } else { dismiss() }
    }

    private func discardAndLeave() {
        model?.discardAnswer()
        leave(applied: false)
    }

    private func run(_ action: @escaping @MainActor (ReviewSuggestionModel) async -> Void) {
        guard let model else { return }
        Task { await action(model) }
    }

    // MARK: States

    @ViewBuilder private func content(_ m: ReviewSuggestionModel) -> some View {
        switch m.phase {
        case .idle:
            outcome("Suggestions", workspace.account == nil
                ? "Task content stays on this device." : "Brain Buddy tries a model on this device first. Task content stays here unless you allow cloud suggestions.")
            action("Request suggestions", prominent: true) { m.request() }
            action("Continue without AI") { run { await $0.continueWithoutAI() } }
        case .requesting:
            outcome("Preparing suggestions…", "Your task is unchanged. You can keep working without AI.", busy: true)
            action("Cancel") { run { await $0.cancel() } }
            action("Continue without AI") { run { await $0.continueWithoutAI() } }
        case .cancelling:
            outcome("Stopping suggestions…", "Your task is unchanged.", busy: true)
            action("Cancel", disabled: true) {}
            action("Continue without AI") { run { await $0.continueWithoutAI() } }
        case .cancelled(let afterTransmission):
            outcome("Suggestions cancelled", afterTransmission
                ? "Suggestions stopped here. The provider may still finish processing data already sent. No result will be applied."
                : "Nothing was sent.")
            retryActions(m, again: "Request again")
        case .interrupted(let mayHaveBeenSent):
            outcome("Suggestions were interrupted", "Nothing was applied." + (mayHaveBeenSent ? " The provider may have received the request." : "")
                + (m.answerSaved ? " Your answer was saved to the notes." : ""))
            retryActions(m, again: "Request again")
        case .needsConsent(let provider, _, let state):
            consent(m, provider: provider, outdated: state == .textOutdated)
        case .consentOff:
            outcome("Cloud suggestions are off", "New requests won't be sent, and no earlier result will be used.")
            action("Continue without AI") { run { await $0.continueWithoutAI() } }
        case .unavailable(let reason):
            unavailable(m, reason, saved: false)
        case .answerSavedSuggestionFailed(let reason):
            unavailable(m, reason, saved: true)
        case .noSuggestion:
            outcome("No suggestion this time", "You can still write it yourself.")
            retryActions(m, again: "Request again")
        case .proposals:
            proposals(m)
        case .question:
            question(m, saving: false)
        case .savingAnswer:
            question(m, saving: true)
        case .answerNotSaved(let failure):
            question(m, saving: false, failure: failure)
        case .stale:
            outcome("This task changed", "Review it before applying a suggestion. Your edited wording is kept.")
            action("Review the task", prominent: true) { m.reviewAfterChange() }
            action("Keep current wording") { m.keepCurrentWording() }
        case .applying:
            outcome("Applying…", nil, busy: true)
        case .applied, .manual:
            ProgressView()
        }
    }

    private var manualOnly: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s4) {
            outcome("Suggestions aren't available", "You can continue without AI.")
            action("Continue without AI", prominent: true) { dismiss() }
        }
    }

    private func retryActions(_ m: ReviewSuggestionModel, again: String) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            action(again, prominent: true) { if m.answerSaved { m.retrySuggestions() } else { m.request() } }
            action("Continue without AI") { run { await $0.continueWithoutAI() } }
        }
    }

    /// .03: the configured provider and the exact fields, before anything is sent.
    private func consent(_ m: ReviewSuggestionModel, provider: String, outdated: Bool) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s4) {
            outcome("Use cloud suggestions?", (outdated ? "What is sent changed since you last agreed. " : "")
                + "To suggest wording, Brain Buddy sends this to \(provider):")
            VStack(alignment: .leading, spacing: BBSpacing.s1) {
                ForEach(Self.sentFields, id: \.self) { Label($0, systemImage: "arrow.up.right").font(BBFont.secondary) }
            }
            .padding(BBSpacing.s4)
            .bbCard()
            Text("Notes are sent as written, including any names in them.")
                .font(BBFont.meta).foregroundStyle(BBColor.textTertiary)
            action("Allow cloud suggestions", prominent: true) { run { await $0.allowCloud() } }
            action("Continue without AI") { m.declineCloud() }
        }
    }

    private static let sentFields = [
        "The task title", "The task notes", "The stall reason, if you chose one", "The project name",
        "Titles of up to 20 other open tasks in that project", "Whether you asked for a first step or new wording",
    ]

    /// .05 / .08 / .19: why there is no suggestion, with a safe reference and the ways forward.
    private func unavailable(_ m: ReviewSuggestionModel, _ reason: ReviewSuggestionModel.Unavailable, saved: Bool) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s4) {
            outcome(saved ? "Your answer was saved" : "Suggestions aren't available",
                    (saved ? "Suggestions aren't available. " : "") + Self.detail(reason) + " You can continue without AI.")
            if case .offline = workspace.syncStatus, workspace.account != nil {
                Label("Offline — connect to request cloud suggestions.", systemImage: "icloud.slash")
                    .font(BBFont.meta).foregroundStyle(BBColor.textTertiary)
            }
            if let reference = m.referenceID {
                Button("Copy reference ID: \(reference)") { UIPasteboard.general.string = reference }
                    .font(BBFont.meta).frame(minHeight: BBMetrics.hitTarget)
            }
            if m.canTryCloud { action("Try cloud suggestions instead", prominent: true) { m.tryCloudInstead() } }
            switch reason {
            case .taskGone, .signedOut, .inputTooLarge: EmptyView()
            default: action(saved ? "Try suggestions again" : "Try again", prominent: !m.canTryCloud) { saved ? m.retrySuggestions() : m.request() }
            }
            action("Continue without AI") { run { await $0.continueWithoutAI() } }
        }
    }

    private static func detail(_ reason: ReviewSuggestionModel.Unavailable) -> String {
        switch reason {
        case .localUnavailable(let reasons):
            "On-device suggestions aren't available for this task. "
                + Set(reasons.map(\.reason.rawValue)).sorted().compactMap { LocalAIUnavailableReason(rawValue: $0) }.map(Self.words).joined(separator: " ")
        case .localFailed: "The on-device model couldn't answer this time."
        case .remoteOff: "Cloud suggestions are off."
        case .signedOut: "Sign in again to request cloud suggestions."
        case .rateLimited: "Too many requests. Try again in a few minutes."
        case .providerError: "The suggestion service didn't answer."
        case .invalidProposal: "The answer didn't pass Brain Buddy's checks, so nothing is shown."
        case .inputTooLarge: "This task has too much text to suggest from."
        case .taskGone: "This task is no longer here."
        }
    }

    private static func words(_ reason: LocalAIUnavailableReason) -> String {
        switch reason {
        case .deviceNotEligible: "This device can't run them."
        case .systemFeatureOff: "Apple Intelligence is off in Settings."
        case .modelNotReady: "The on-device model isn't ready yet."
        case .notDownloaded: "The on-device model isn't downloaded."
        case .disabled: "They are turned off."
        case .unsupportedLanguage: "This task's language isn't supported."
        case .insufficientMemory: "There isn't enough free memory right now."
        case .failedThisRequest: "The model failed on this request."
        }
    }

    /// .10 / .06: pick or edit one proposal; nothing changes until Apply.
    private func proposals(_ m: ReviewSuggestionModel) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s4) {
            outcome("Review suggestion", "Nothing changes until you apply.")
            if m.notesTruncated {
                Label("Part of the notes was not considered.", systemImage: "scissors").font(BBFont.meta)
            }
            ForEach(m.proposals, id: \.self) { proposal in
                Button { edited = proposal } label: {
                    Text(proposal).font(BBFont.body).multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget, alignment: .leading)
                        .padding(.horizontal, BBSpacing.s3)
                        .background(BBColor.surfaceRaised, in: RoundedRectangle(cornerRadius: BBRadius.row, style: .continuous))
                        .overlay {
                            RoundedRectangle(cornerRadius: BBRadius.row, style: .continuous)
                                .strokeBorder(edited == proposal ? BBColor.brandText : BBColor.hairline, lineWidth: edited == proposal ? 2 : 1)
                        }
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(edited == proposal ? .isSelected : [])
            }
            Text("Edit before applying").font(BBFont.subtitle).foregroundStyle(BBColor.textSecondary)
            TextField("Suggestion", text: $edited, axis: .vertical).lineLimit(2...6).textFieldStyle(.roundedBorder)
            if m.applyFailure != nil { InlineProblemText(message: "Couldn't apply the suggestion. Nothing changed. Try again.") }
            action("Apply suggestion", prominent: true, disabled: edited.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty) {
                run { [edited] in await $0.apply(edited) }
            }
            action("Keep current wording") { m.keepCurrentWording() }
        }
    }

    /// .16-.18: the clarifying question is not an error; the typed answer survives every failure.
    private func question(_ m: ReviewSuggestionModel, saving: Bool, failure: ReviewSuggestionModel.AnswerSaveFailure? = nil) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s4) {
            outcome(failure == nil ? "One question first" : "Couldn't add your answer to the notes",
                    failure.map { Self.detail($0) } ?? m.question)
            if failure != nil, let question = m.question { Text(question).font(BBFont.body) }
            Text("Your answer").font(BBFont.subtitle).foregroundStyle(BBColor.textSecondary)
            TextField("Your answer", text: Binding(get: { m.answerDraft }, set: { m.answerDraft = $0 }), axis: .vertical)
                .lineLimit(3...8).textFieldStyle(.roundedBorder).focused($answerFocused).disabled(saving)
            if saving {
                SavingLabel()
            } else {
                let empty = m.answerDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                action(failure == nil ? "Add to notes and suggest again" : "Retry", prominent: true, disabled: empty) { m.submitAnswer() }
                action("I'll write my own step") { if isEditingAnswer { confirmsDiscard = true } else { run { await $0.continueWithoutAI() } } }
            }
        }
    }

    private static func detail(_ failure: ReviewSuggestionModel.AnswerSaveFailure) -> String {
        switch failure {
        case .conflict: "The task changed since you opened it. Your answer is saved here."
        case .rejected: "Your answer is saved here."
        case .unknownOutcome: "We couldn't confirm the save, and retrying won't add it twice. Your answer is saved here."
        }
    }

    // MARK: Pieces

    private func outcome(_ title: String, _ text: String?, busy: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            Text(title).font(BBFont.title).foregroundStyle(BBColor.textPrimary)
                .accessibilityAddTraits(.isHeader).accessibilityFocused($outcomeFocused)
            if busy { ProgressView() }
            if let text {
                Text(text).font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private func action(_ title: String, prominent: Bool = false, disabled: Bool = false, _ run: @escaping () -> Void) -> some View {
        let label = Text(title).frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
        return Group {
            if prominent { Button(action: run) { label }.buttonStyle(.borderedProminent) }
            else { Button(action: run) { label }.buttonStyle(.bordered) }
        }
        .disabled(disabled)
    }
}

/// "Saving…" appears only after 300 ms (.17), so a quick save does not flash.
private struct SavingLabel: View {
    @State private var visible = false
    var body: some View {
        Group { if visible { Label("Saving…", systemImage: "arrow.triangle.2.circlepath").font(BBFont.meta) } }
            .frame(minHeight: BBMetrics.hitTarget)
            .task { try? await Task.sleep(for: .milliseconds(300)); visible = true }
    }
}

// MARK: - Engines

/// What the sheet hands the shared model: the policy bridge, the app's on-device executor and the
/// signed-in account's navigator endpoint. The policy itself is the Rust core's.
@MainActor
enum SuggestionEngines {
    static let adapter: LocalAIAdapter? = (try? RustBridgeRuntime()).map {
        LocalAIAdapter(policy: $0, executors: [AppleOnDeviceExecutor()])
    }

    static func remote(for account: LinkedAccount?) -> (any NavigatorRemote)? {
        account.map { BrainBuddyAPIClient(baseURL: $0.serverURL, tokenStore: KeychainSessionTokenStore()) }
    }
}

@Generable
private struct NavigatorDraft {
    @Guide(description: "Up to three suggestions, each one short sentence starting with a verb. Empty when a question is needed.")
    var proposals: [String]
    @Guide(description: "One short clarifying question, only when no useful suggestion is possible without more information.")
    var clarifyingQuestion: String?
}

/// Apple's on-device model through Foundation Models. It reports what the system says; the shared
/// policy decides whether it may run, and a failure is the model's to route, never hidden here.
private struct AppleOnDeviceExecutor: LocalAIExecutor {
    let source = LocalAISource.appleOnDevice

    func facts() async -> LocalAIFacts {
        let model = SystemLanguageModel.default
        let runtime: LocalAIRuntime
        switch model.availability {
        case .available: runtime = .ready
        case .unavailable(.deviceNotEligible): runtime = .deviceNotEligible
        case .unavailable(.appleIntelligenceNotEnabled): runtime = .systemFeatureOff
        case .unavailable(.modelNotReady): runtime = .modelNotReady
        case .unavailable: runtime = .disabled
        }
        // The system owns the model's memory; the app's own headroom is the only figure it can state.
        return LocalAIFacts(
            source: source, runtime: runtime,
            supportedLanguages: model.supportedLanguages.compactMap { $0.languageCode?.identifier },
            freeMemoryMB: UInt64(os_proc_available_memory()) / 1_048_576, requiredMemoryMB: 0)
    }

    func suggest(_ input: SuggestionInput, terms: AITerms) async throws -> ModelAnswer {
        let ask = input.kind == .firstStep
            ? "Suggest a tiny, concrete first step that takes about five minutes."
            : "Suggest a clearer wording of this task as one concrete next action."
        let session = LanguageModelSession(instructions: ask
            + " Reply in the language of the task. If you cannot do this without more information, give no suggestions and ask one short question.")
        let facts = [("Task", input.taskTitle), ("Notes", input.taskNotes), ("Why it stalled", input.stallReason),
                     ("Project", input.projectName),
                     ("Other open tasks", input.openTaskTitles.isEmpty ? nil : input.openTaskTitles.joined(separator: "; "))]
        let prompt = facts.compactMap { label, value in value.map { "\(label): \($0)" } }.joined(separator: "\n")
        let result = try await session.respond(
            to: prompt, generating: NavigatorDraft.self,
            options: GenerationOptions(maximumResponseTokens: Int(terms.maxOutputTokens)))
        return ModelAnswer(proposals: result.content.proposals, clarifyingQuestion: result.content.clarifyingQuestion)
    }
}
