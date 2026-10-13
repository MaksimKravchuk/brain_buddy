import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMac
@testable import BrainBuddyMacCore
@testable import BrainBuddyWorkspace

/// The Mac's Weekly Review suggestion surface (spec 026 T060, design D-04): the shared PR-49 model
/// reached through `BrainBuddyModel`, and the sheet's phase-to-screen mapping. The state machine
/// itself is the kit's (`ReviewSuggestionModelTests`); these cases pin what the Mac adds: where the
/// entry is offered, that one model is shared and released, the copy and focus of each state, and
/// that no sync state or foreign focus move reaches the sheet. No provider or on-device model runs.
@Suite("Review suggestions")
@MainActor
struct ReviewSuggestionTests {
    typealias Screen = ReviewSuggestionScreen

    private func input(
        _ phase: ReviewSuggestionModel.Phase, kind: SuggestionKind = .reformulate, cloud: Bool = false, saved: Bool = false,
        reference: String? = nil, question: String? = nil, tryCloud: Bool = false, leaving: Bool = false
    ) -> Screen.Input {
        Screen.Input(
            phase: phase, kind: kind, cloudPossible: cloud, canTryCloud: tryCloud, answerSaved: saved, referenceID: reference,
            question: question, leaving: leaving)
    }

    private func screen(_ phase: ReviewSuggestionModel.Phase, cloud: Bool = false, saved: Bool = false,
                        reference: String? = nil, question: String? = nil, tryCloud: Bool = false) -> Screen {
        Screen.make(input(phase, cloud: cloud, saved: saved, reference: reference, question: question, tryCloud: tryCloud))
    }

    private func titles(_ screen: Screen) -> [String] { screen.buttons.map(\.title) }

    // MARK: State mapping (D-04 .01-.20)

    @Test("026-FR-018 026-FR-020 an unrequested sheet asks nothing of a model and says task content stays on this device")
    func idleOffersOnlyAnExplicitRequest() {
        let local = screen(.idle)
        #expect(local.lines.contains("Task content stays on this device."))
        #expect(titles(local) == ["Request suggestions", "Continue without AI"])
        let cloud = screen(.idle, cloud: true)
        #expect(cloud.lines.first?.contains("Cloud suggestions need your consent first.") == true)
    }

    @Test("026-FR-019 026-SC-006 the consent names the configured provider and the exact fields, with Allow and Continue without AI")
    func consentNamesProviderAndFields() {
        let consent = screen(.needsConsent(provider: "openai", textVersion: 1, state: .missing))
        #expect(consent.heading == "Use cloud suggestions?")
        #expect(consent.lines.first == "Brain Buddy would send these to openai:")
        #expect(consent.consentFields == [
            "Task title", "Task notes", "Why it stalled, if you chose a reason", "Project name",
            "Up to 20 other open task titles in that project", "The kind of suggestion you asked for",
        ])
        #expect(consent.lines.contains("Notes are sent as written, including any names in them."))
        #expect(titles(consent) == ["Allow cloud suggestions", "Continue without AI"])
        let outdated = screen(.needsConsent(provider: "openai", textVersion: 2, state: .textOutdated))
        #expect(outdated.lines.first == "The consent text changed since you last allowed it.")
    }

    @Test("026-FR-019 revoked consent reads as off and offers no send, only manual work or an explicit new request")
    func consentOff() {
        let off = screen(.consentOff)
        #expect(off.heading == "Cloud suggestions are off")
        #expect(titles(off) == ["Continue without AI", "Request again"])
        #expect(!titles(off).contains("Allow cloud suggestions"))
    }

    @Test("026-FR-020 loading offers Cancel and Continue without AI; stopping disables repeated Cancel and is announced")
    func loadingAndStopping() {
        let loading = screen(.requesting)
        #expect(loading.heading == "Preparing suggestions…")
        #expect(titles(loading) == ["Cancel", "Continue without AI"])
        let stopping = screen(.cancelling)
        #expect(stopping.heading == "Stopping suggestions…")
        #expect(stopping.buttons.first { $0.action == .cancel }?.enabled == false)
        #expect(stopping.announcement != nil && stopping.firstFocus == .heading)
    }

    @Test("026-FR-020 cancellation tells the truth about what was sent, and interruption never resends on its own")
    func cancelledAndInterrupted() {
        #expect(screen(.cancelled(afterTransmission: false)).lines == ["Suggestions cancelled. Nothing was sent."])
        #expect(screen(.cancelled(afterTransmission: true)).lines == [
            "Suggestions stopped here. The provider may still finish processing data already sent. No result will be applied.",
        ])
        let lost = screen(.interrupted(mayHaveBeenSent: true), reference: "ref-1")
        #expect(lost.lines == ["Suggestions were interrupted. Nothing was applied. The provider may have received the request."])
        #expect(lost.reference == "ref-1")
        #expect(titles(lost) == ["Continue without AI", "Request again"], "a new request is the person's choice")
        #expect(screen(.interrupted(mayHaveBeenSent: false)).lines == ["Suggestions were interrupted. Nothing was applied."])
        for phase in [ReviewSuggestionModel.Phase.cancelled(afterTransmission: true), .interrupted(mayHaveBeenSent: true)] {
            let outcome = screen(phase)
            #expect(outcome.announcement != nil && outcome.firstFocus == .heading, "announced once, focus on the outcome heading")
        }
    }

    @Test("026-FR-018 on-device unavailability is a calm manual continuation, a failed local run may offer the cloud explicitly")
    func unavailable() {
        let unsupported = screen(.unavailable(.localUnavailable([.init(source: .appleOnDevice, reason: .systemFeatureOff)])))
        #expect(unsupported.heading == "On-device suggestions aren't available for this task")
        #expect(unsupported.lines == ["Apple Intelligence is turned off."])
        #expect(!titles(unsupported).contains("Try cloud suggestions instead"))
        let failed = screen(.unavailable(.localFailed), tryCloud: true)
        #expect(failed.heading == "Suggestions aren't available. You can continue without AI.")
        #expect(titles(failed) == ["Continue without AI", "Try cloud suggestions instead", "Request again"])
        #expect(!titles(screen(.unavailable(.localFailed), tryCloud: false)).contains("Try cloud suggestions instead"))
        let provider = screen(.unavailable(.providerError), reference: "abc")
        #expect(provider.reference == "abc")
    }

    @Test("026-FR-020 a ready proposal is editable and explicit, notes cut short are disclosed, and a stale task asks for a reread")
    func proposalAndStale() {
        let ready = Screen.make(
            Screen.Input(phase: .proposals, kind: .reformulate, cloudPossible: false, notesTruncated: true))
        #expect(ready.heading == "Review suggestion" && ready.showsProposals)
        #expect(ready.lines.contains("Nothing changes until you apply."))
        #expect(ready.lines.contains("Part of the notes was not considered."))
        #expect(titles(ready) == ["Apply suggestion", "Keep current wording"])
        let stale = screen(.stale)
        #expect(stale.lines == ["This task changed. Review it before applying a suggestion."])
        #expect(stale.showsProposals, "the draft stays while the person rereads")
        #expect(titles(stale) == ["Review the task", "Keep current wording"])
        #expect(!titles(stale).contains("Apply suggestion"), "a stale proposal is never applied without a fresh confirmation")
    }

    @Test("026-FR-016 026-FR-020 a clarifying question shows the answer field focused, offers manual, and is not a proposal")
    func clarifyingQuestion() {
        let question = screen(.question, question: "What does done look like?")
        #expect(question.heading == "What does done look like?")
        #expect(question.showsAnswerField && !question.showsProposals && question.firstFocus == .answerField)
        #expect(titles(question) == ["Add to notes and suggest again", "I'll write my own step"])
    }

    @Test("026-FR-016 a failed answer save keeps the answer and Retry; a saved answer with failed inference retries inference only")
    func answerSaveStates() {
        let conflict = screen(.answerNotSaved(.conflict))
        #expect(conflict.lines.first == "Couldn't add your answer to the notes. Your answer is saved here.")
        #expect(conflict.showsAnswerField && conflict.firstFocus == .answerField && titles(conflict).first == "Retry")
        let rejected = screen(.answerNotSaved(.rejected(code: "VALIDATION")))
        #expect(rejected.reference == "VALIDATION")
        let saved = screen(.answerSavedSuggestionFailed(.providerError), saved: true, reference: "r1")
        #expect(saved.heading == "Your answer was saved. Suggestions aren't available.")
        #expect(titles(saved) == ["Try suggestions again", "I'll write my own step"])
        #expect(!saved.showsAnswerField, "the answer is already in the notes and is not offered again")
        #expect(saved.reference == "r1")
        #expect(screen(.savingAnswer).heading == "Saving…")
    }

    @Test("026-FR-020 leaving with an unsaved answer focuses Keep editing first, and only Discard removes the draft")
    func leavingWithUnsavedAnswer() {
        let prompt = Screen.make(input(.question, leaving: true))
        #expect(prompt.heading == "Discard your answer?")
        #expect(prompt.lines == ["It hasn't been added to the notes."])
        #expect(prompt.firstFocus == .keepEditing)
        #expect(titles(prompt) == ["Keep editing", "Discard"])
    }

    @Test("026-FR-020 applied and manual end on Done; applied is announced")
    func endStates() {
        #expect(screen(.applied).announcement == "Suggestion applied")
        #expect(titles(screen(.applied)) == ["Done"] && titles(screen(.manual)) == ["Done"])
    }

    @Test("026-FR-019 every phase has a screen, and no screen asks for focus anywhere but its heading, answer field or safe choice")
    func everyPhaseHasAScreen() {
        let phases: [ReviewSuggestionModel.Phase] = [
            .idle, .requesting, .cancelling, .cancelled(afterTransmission: false), .interrupted(mayHaveBeenSent: false),
            .needsConsent(provider: "p", textVersion: 1, state: .missing), .consentOff, .unavailable(.taskGone),
            .noSuggestion, .proposals, .question, .savingAnswer, .answerNotSaved(.unknownOutcome),
            .answerSavedSuggestionFailed(.remoteOff), .stale, .applying, .applied, .manual,
        ]
        for phase in phases {
            let screen = screen(phase)
            #expect(!screen.heading.isEmpty)
            #expect(Set(screen.buttons.map(\.action)).count == screen.buttons.count, "no duplicated action in \(phase)")
        }
    }

    // MARK: The sheet's source and the presentation guard

    @Test("026-FR-020 the sheet sets its first focus with defaultFocus, never assigns a FocusState, and passes the presentation guard")
    func sheetRespectsThePresentationGuard() throws {
        let sources = try MacPresentationGuardTests.sources()
        let sheet = try #require(sources.first { $0.name == "BrainBuddyMac/ReviewSuggestionSheet.swift" })
        #expect(sheet.text.contains(".defaultFocus($focus"))
        #expect(MacPresentationGuardTests.violations(file: sheet.name, text: sheet.text).isEmpty)
        let content = try #require(sources.first { $0.name == "BrainBuddyMac/ContentView.swift" })
        #expect(MacPresentationGuardTests.violations(file: content.name, text: content.text).isEmpty)
        // VoiceCapture is transcription and stays out of it.
        let voice = try #require(sources.first { $0.name == "BrainBuddyMac/VoiceCapture.swift" })
        #expect(!voice.text.contains("ReviewSuggestion"))
    }

    // MARK: The shared model (026-FR-018, -019, -020)

    /// An on-device executor that answers with a fixed wording; no model runs.
    private final class ScriptedExecutor: LocalAIExecutor, @unchecked Sendable {  // @unchecked: `inputs` is lock-guarded
        let source = LocalAISource.appleOnDevice
        private let lock = NSLock()
        private var seen: [SuggestionInput] = []
        var inputs: [SuggestionInput] { lock.withLock { seen } }
        func facts() async -> LocalAIFacts {
            LocalAIFacts(source: .appleOnDevice, runtime: .ready, supportedLanguages: ["en"], freeMemoryMB: 4_000, requiredMemoryMB: 1_000)
        }
        func suggest(_ input: SuggestionInput, terms: AITerms) async throws -> ModelAnswer {
            lock.withLock { seen.append(input) }
            return ModelAnswer(proposals: ["Call the workshop for a quote"])
        }
    }

    private func adapter(_ executors: [ScriptedExecutor]) throws -> LocalAIAdapter {
        LocalAIAdapter(policy: try RustBridgeRuntime(), executors: executors, detectLanguage: { _ in "en" })
    }

    @Test("026-FR-018 026-SC-006 the entry is offered only on a Next action while the review is exposed")
    func entryEligibility() async throws {
        let app = await OfflineWorkspaceTests.App()
        let next = try app.add("Sort out the bike", .next)
        let waiting = try app.add("Wait for the quote", .waiting, waitingFor: "Sam")
        let nextTask = try #require(app.workspace.task(next))
        #expect(app.model.reviewSuggestionKinds(for: nextTask).isEmpty, "review not exposed: no entry")

        app.workspace.accountlessReviewEnabled = true
        #expect(app.model.reviewSuggestionKinds(for: nextTask) == [.reformulate, .firstStep])
        let waitingTask = try #require(app.workspace.task(waiting))
        #expect(app.model.reviewSuggestionKinds(for: waitingTask).isEmpty, "the decision it would apply is not allowed there")
        #expect(app.model.reviewSuggestionModel(for: waitingTask, kind: .reformulate, adapter: try adapter([])) == nil)
    }

    @Test("026-FR-020 an editor with unsaved fields blocks the entry with a message, so a later editor save cannot overwrite an applied wording")
    func dirtyEditorBlocksTheEntry() async throws {
        let app = await OfflineWorkspaceTests.App()
        app.workspace.accountlessReviewEnabled = true
        let id = try app.add("Sort out the bike", .next)
        let task = try #require(app.workspace.task(id))
        #expect(app.model.reviewSuggestionEntry(for: task, editorDirty: false) == .available([.reformulate, .firstStep]))
        #expect(app.model.reviewSuggestionEntry(for: task, editorDirty: true) == .blocked(BrainBuddyModel.suggestionBlockedByEditor))
        let waiting = try #require(app.workspace.task(try app.add("Wait", .waiting, waitingFor: "Sam")))
        #expect(app.model.reviewSuggestionEntry(for: waiting, editorDirty: true) == .hidden)
    }

    @Test("026-FR-018 026-FR-019 account-less, nothing leaves the Mac: no executor means manual continuation and no remote request")
    func accountLessNeverGoesRemote() async throws {
        let app = await OfflineWorkspaceTests.App()
        app.workspace.accountlessReviewEnabled = true
        let id = try app.add("Sort out the bike", .next)
        let task = try #require(app.workspace.task(id))
        let suggestion = try #require(app.model.reviewSuggestionModel(for: task, kind: .reformulate, adapter: try adapter([])))
        suggestion.request()
        await suggestion.settled()
        guard case .unavailable(.localUnavailable) = suggestion.phase else {
            Issue.record("expected the on-device-unavailable state, got \(suggestion.phase)")
            return
        }
        #expect(app.transport.requests.isEmpty, "no request of any kind was made")
        let screen = Screen.make(Screen.Input(suggestion, cloudPossible: false, leaving: false))
        #expect(screen.heading == "On-device suggestions aren't available for this task")
        await suggestion.continueWithoutAI()
        #expect(suggestion.phase == .manual)
    }

    @Test("026-FR-020 one model is shared per task and kind, a proposal changes nothing until applied, and release ends it")
    func sharedModelProposalApplyRelease() async throws {
        let app = await OfflineWorkspaceTests.App()
        app.workspace.accountlessReviewEnabled = true
        let id = try app.add("Sort out the bike", .next)
        let task = try #require(app.workspace.task(id))
        let executor = ScriptedExecutor()
        let adapter = try adapter([executor])
        let first = try #require(app.model.reviewSuggestionModel(for: task, kind: .reformulate, adapter: adapter))
        let again = try #require(app.model.reviewSuggestionModel(for: task, kind: .reformulate, adapter: adapter))
        #expect(first === again, "closing and reopening the sheet finds the same model")
        let other = try #require(app.model.reviewSuggestionModel(for: task, kind: .firstStep, adapter: adapter))
        #expect(first !== other)

        first.request()
        await first.settled()
        #expect(first.phase == .proposals && first.proposals == ["Call the workshop for a quote"])
        #expect(executor.inputs.first?.taskTitle == "Sort out the bike")
        #expect(app.workspace.task(id)?.title == "Sort out the bike", "a proposal is not a change")

        await first.apply("Call the workshop for a quote")
        #expect(first.phase == .applied)
        #expect(app.workspace.task(id)?.title == "Call the workshop for a quote", "applied through the ordinary decision")

        app.model.releaseReviewSuggestion(for: id, kind: .reformulate)
        let reread = try #require(app.workspace.task(id))
        let fresh = try #require(app.model.reviewSuggestionModel(for: reread, kind: .reformulate, adapter: adapter))
        #expect(fresh !== first, "after release a reopened sheet starts clean")
        #expect(fresh.phase == .idle)
    }

    @Test("026-FR-020 a task edited elsewhere is stale: the proposal is kept and nothing is applied until the person rereads")
    func staleProposal() async throws {
        let app = await OfflineWorkspaceTests.App()
        app.workspace.accountlessReviewEnabled = true
        let id = try app.add("Sort out the bike", .next)
        let task = try #require(app.workspace.task(id))
        let suggestion = try #require(app.model.reviewSuggestionModel(for: task, kind: .reformulate, adapter: try adapter([ScriptedExecutor()])))
        suggestion.request()
        await suggestion.settled()
        try app.workspace.updateTask(id, TaskChanges(details: .set("Changed on another window")))

        await suggestion.apply("Call the workshop for a quote")
        #expect(suggestion.phase == .stale)
        #expect(app.workspace.task(id)?.title == "Sort out the bike")
        suggestion.reviewAfterChange()
        #expect(suggestion.phase == .proposals && suggestion.proposals == ["Call the workshop for a quote"])
        await suggestion.apply("Call the workshop for a quote")
        #expect(suggestion.phase == .applied)
    }
}
