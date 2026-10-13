import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// The shared AI capability policy as the Apple adapter reaches it (spec 026 T049; FR-018, FR-019,
/// FR-020, FR-023): the decision is the Rust core's, so these run the real bridge and fake only
/// the executor and the provider.
@MainActor
@Suite struct LocalAIPolicyTests {
    let runtime: RustBridgeRuntime

    init() throws { runtime = try RustBridgeRuntime() }

    private func adapter(_ executors: [FakeExecutor], language: String? = "en") -> LocalAIAdapter {
        LocalAIAdapter(policy: runtime, executors: executors, detectLanguage: { _ in language })
    }

    private let input = SuggestionInput(kind: .reformulate, taskTitle: "Renovate the bathroom", taskNotes: "Tiles chosen")

    private func remote(consents: [OwnerConsentFact], version: Int = 1, provider: String? = "openai",
                        credentials: Bool = true, echo: Bool = true) -> RemoteFacts {
        RemoteFacts(provider: provider, credentialsConfigured: credentials, consentTextVersion: version,
                    echoedConsent: provider.map { (allowed: echo, provider: $0) }, consents: consents)
    }

    private func consent(revoked: Bool = false, version: Int = 1, owner: String = "owner-1") -> OwnerConsentFact {
        OwnerConsentFact(owner: owner, provider: "openai", grantedAt: Date(timeIntervalSince1970: 1_800_000_000),
                         revokedAt: revoked ? Date(timeIntervalSince1970: 1_800_000_050) : nil, consentTextVersion: version)
    }

    private func route(_ executors: [FakeExecutor] = [FakeExecutor()], privacy: AIPrivacyMode = .onDeviceOnly,
                       language: String? = "en", cancelled: Bool = false, failed: [LocalAISource] = [],
                       remote: RemoteFacts? = nil, input override: SuggestionInput? = nil) async throws -> AIRoute {
        try await adapter(executors, language: language).route(
            input: override ?? input, owner: "owner-1", privacy: privacy, cancelled: cancelled, failedLocal: failed, remote: remote)
    }

    @Test("026-FR-018 a ready, language-matching local executor is chosen over any remote route")
    func localPreferred() async throws {
        let granted = remote(consents: [consent()])
        #expect(try await route(privacy: .remoteAllowed, remote: granted) == .local(.appleOnDevice, .navigator))
    }

    @Test("026-FR-018 every local unavailability reason is named, and on-device only is denied")
    func localUnavailableReasons() async throws {
        let cases: [(FakeExecutor, String?, LocalAIUnavailableReason)] = [
            (FakeExecutor(runtime: .deviceNotEligible), "en", .deviceNotEligible),
            (FakeExecutor(runtime: .systemFeatureOff), "en", .systemFeatureOff),
            (FakeExecutor(runtime: .modelNotReady), "en", .modelNotReady),
            (FakeExecutor(runtime: .notDownloaded), "en", .notDownloaded),
            (FakeExecutor(runtime: .disabled), "en", .disabled),
            (FakeExecutor(languages: ["de"]), "en", .unsupportedLanguage),
            (FakeExecutor(), nil, .unsupportedLanguage),
            (FakeExecutor(free: 100, required: 1_000), "en", .insufficientMemory),
        ]
        for (executor, language, reason) in cases {
            let outcome = try await route([executor], language: language)
            #expect(outcome == .denied(.localUnavailable([LocalAIUnavailability(source: .appleOnDevice, reason: reason)])),
                    "\(reason)")
        }
    }

    @Test("026-FR-018 on-device only never leads to a remote route, also after the local executor failed")
    func onDeviceOnlyNeverRemote() async throws {
        let granted = remote(consents: [consent()])
        let afterFailure = try await route(privacy: .onDeviceOnly, failed: [.appleOnDevice], remote: granted)
        #expect(afterFailure == .denied(.localUnavailable([LocalAIUnavailability(source: .appleOnDevice, reason: .failedThisRequest)])))
        let none = try await route([], privacy: .onDeviceOnly, remote: granted)
        #expect(none == .denied(.localUnavailable([])))
    }

    @Test("026-FR-019 a remote route needs configuration, credentials, echoed and current stored consent")
    func remoteNeedsEveryCondition() async throws {
        let no: [FakeExecutor] = []
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent()]))
                == .remote(provider: "openai", consentTextVersion: 1, terms: .navigator))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent()], provider: nil))
                == .denied(.remoteDisabled))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent()], credentials: false))
                == .denied(.credentialsMissing))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent()], echo: false))
                == .denied(.consentRequired(.missing)))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: []))
                == .denied(.consentRequired(.missing)))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent(revoked: true)]))
                == .denied(.consentRequired(.revoked)))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent()], version: 2))
                == .denied(.consentRequired(.textOutdated)))
        #expect(try await route(no, privacy: .remoteAllowed, remote: remote(consents: [consent(owner: "owner-2")]))
                == .denied(.consentRequired(.missing)), "another owner's consent is not this owner's")
        #expect(try await route(no, privacy: .remoteAllowed, remote: nil) == .denied(.localUnavailable([])))
    }

    @Test("026-FR-020 cancellation wins over everything and an oversized input is not sent")
    func cancelledAndOversized() async throws {
        let granted = remote(consents: [consent()])
        #expect(try await route(privacy: .remoteAllowed, cancelled: true, remote: granted) == .denied(.cancelled))
        let huge = SuggestionInput(kind: .reformulate, taskTitle: "Renovate", taskNotes: String(repeating: "a", count: 40_000))
        #expect(try await route([], privacy: .remoteAllowed, remote: granted, input: huge) == .denied(.inputTooLarge))
        #expect(try await route(input: huge) == .denied(.inputTooLarge))
    }

    @Test("026-FR-019 a malformed policy request fails closed with a content-free error")
    func malformedRequestFailsClosed() async {
        do {
            _ = try await runtime.aiRoute(Data("{\"owner\": 1}".utf8))
            Issue.record("expected a failure")
        } catch let error as RustBridgeError {
            #expect(error.code == "INVALID_REQUEST" && error.field == "request")
        } catch { Issue.record("unexpected \(error)") }
    }

    @Test("026-FR-020 model answers go through the shared validation rules 1-5")
    func sharedAnswerValidation() async throws {
        let sut = adapter([])
        let known = ["Draft the outline"]
        #expect(try await sut.validate(ModelAnswer(proposals: ["Draft the outline", "Draft the outline"]), for: input)
                == .proposals(["Draft the outline"]))
        #expect(try await sut.validate(ModelAnswer(proposals: ["Call Marta about 500 dollars"]), for: input) == .malformed)
        #expect(try await sut.validate(ModelAnswer(proposals: ["Renovate the bathroom"]), for: input) == .malformed,
                "rule 2: equal to the current title")
        #expect(try await sut.validate(ModelAnswer(proposals: ["Draft the outline"]), for: input, projectOpenTitles: known)
                == .noUsefulSuggestion, "rule 5: an open task of the project the client holds")
        #expect(try await sut.validate(ModelAnswer(proposals: [], clarifyingQuestion: "Which tiles did you choose"), for: input)
                == .question("Which tiles did you choose"))
        #expect(try await sut.validate(ModelAnswer(proposals: []), for: input) == .malformed)
    }

    @Test("026-FR-018 the executor receives no more than the approved payload")
    func executorGetsApprovedPayload() async throws {
        let executor = FakeExecutor()
        let answer = try await adapter([executor]).runLocal(.appleOnDevice, input: input, terms: .navigator)
        #expect(answer.proposals == ["Draft the outline"])
        #expect(executor.inputs == [input])
    }

    // MARK: The workspace as port (026-FR-020, 026-FR-023)

    private func activated() async throws -> Workspace {
        let workspace = await loadedWorkspace()
        workspace.accountlessReviewEnabled = true
        workspace.deviceTimeZone = { TimeZone(identifier: "Europe/Berlin")! }
        try workspace.acknowledgeExplainer()
        return workspace
    }

    @Test("026-FR-019 the workspace builds the approved payload from its projection and nothing else")
    func workspaceInputIsApprovedPayload() async throws {
        let workspace = try await activated()
        let project = try workspace.capture(CaptureDraft(text: "Fix the sink @Home", list: .next))
        let other = try workspace.capture(CaptureDraft(text: "Paint the hall @Home", list: .next))
        let done = try workspace.capture(CaptureDraft(text: "Old chore @Home", list: .next))
        try workspace.completeTask(done)
        try workspace.updateTask(project, TaskChanges(details: .set("Needs a new seal")))
        let input = try #require(workspace.suggestionInput(for: project, kind: .firstStep, stallReason: .tooBig))
        #expect(input.taskTitle == "Fix the sink" && input.taskNotes == "Needs a new seal")
        #expect(input.stallReason == "too_big" && input.projectName == "Home")
        #expect(input.openTaskTitles == [workspace.task(other)?.title].compactMap { $0 }, "other open titles only")
        #expect(workspace.suggestionInput(for: TaskID("missing"), kind: .firstStep, stallReason: nil) == nil)
    }

    @Test("026-FR-020 apply runs the ordinary decision, records the AI use, and nothing changes before it")
    func workspaceApplyIsOrdinaryDecision() async throws {
        let workspace = try await activated()
        let task = try workspace.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        let shown = workspace.shownTask(of: try #require(workspace.task(task)))
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: ["Draft the outline"])))
        let model = workspace.reviewSuggestionModel(
            for: task, kind: .reformulate, adapter: adapter([executor]), remote: nil, privacy: .onDeviceOnly, shown: shown)
        model.request()
        await model.settled()
        #expect(model.phase == .proposals)
        #expect(workspace.task(task)?.title == "Renovate the bathroom", "a proposal is not a Task change")
        let session = try workspace.startReview(mode: .full, entry: .list)
        await model.apply("Draft the outline", sessionID: session)
        #expect(model.phase == .applied)
        #expect(workspace.task(task)?.title == "Draft the outline")
        let id = try #require(model.appliedDecisionID)
        let decision = try #require(workspace.state.review.decisions[id])
        #expect(decision.aiUse == .asIs && decision.type == .reformulate && decision.sessionID == session)
        try workspace.undoDecision(id)
        #expect(workspace.task(task)?.title == "Renovate the bathroom", "Undo within the existing window")
        workspace.releaseReviewSuggestionModel(for: task, kind: .reformulate)
    }

    @Test("026-FR-020 outside a review run, apply is a plain wording update with no decision")
    func workspaceApplyOutsideSession() async throws {
        let workspace = try await activated()
        let task = try workspace.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        let shown = workspace.shownTask(of: try #require(workspace.task(task)))
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: ["Draft the outline"])))
        let model = workspace.reviewSuggestionModel(
            for: task, kind: .reformulate, adapter: adapter([executor]), remote: nil, privacy: .onDeviceOnly, shown: shown)
        model.request()
        await model.settled()
        await model.apply("Draft the outline")
        #expect(model.phase == .applied && model.appliedDecisionID == nil)
        #expect(workspace.task(task)?.title == "Draft the outline" && workspace.state.review.decisions.isEmpty)
    }

    @Test("026-FR-020 a task edited since it was shown is refused as stale and keeps its new wording")
    func workspaceApplyStale() async throws {
        let workspace = try await activated()
        let task = try workspace.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        let shown = workspace.shownTask(of: try #require(workspace.task(task)))
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: ["Draft the outline"])))
        let model = workspace.reviewSuggestionModel(
            for: task, kind: .reformulate, adapter: adapter([executor]), remote: nil, privacy: .onDeviceOnly, shown: shown)
        model.request()
        await model.settled()
        try workspace.updateTask(task, TaskChanges(title: .set("Renovate the guest bathroom")))
        await model.apply("Draft the outline")
        #expect(model.phase == .stale)
        #expect(workspace.task(task)?.title == "Renovate the guest bathroom")
        #expect(workspace.state.review.decisions.isEmpty)
    }

    @Test("026-FR-020 the answer is an ordinary notes edit with a stable identity, adopted before the rerun")
    func workspaceAnswerNotesEdit() async throws {
        let workspace = try await activated()
        let task = try workspace.capture(CaptureDraft(text: "Renovate the bathroom", list: .next))
        try workspace.updateTask(task, TaskChanges(details: .set("Tiles chosen")))
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: [], clarifyingQuestion: "Which tiles did you choose")))
        let model = workspace.reviewSuggestionModel(
            for: task, kind: .reformulate, adapter: adapter([executor]), remote: nil, privacy: .onDeviceOnly)
        model.request()
        await model.settled()
        #expect(model.phase == .question)
        executor.setResult(.success(ModelAnswer(proposals: ["Order the grey tiles"])))
        model.answerDraft = "Grey ones"
        model.submitAnswer()
        await model.settled()
        #expect(workspace.task(task)?.details == "Tiles chosen\n\nGrey ones")
        #expect(executor.inputs.last?.taskNotes == "Tiles chosen\n\nGrey ones")
        #expect(model.phase == .proposals)
    }

    @Test("026-FR-023 workspace errors map to content-free conflict, rejection or unknown outcomes")
    func errorMapping() {
        #expect(Workspace.suggestionPortError(GTDValidationError.formulationChanged) == .conflict)
        #expect(Workspace.suggestionPortError(GTDValidationError.taskNotFound) == .rejected(code: "VALIDATION"))
        #expect(Workspace.suggestionPortError(RustDomainError.refused(reason: "revision_conflict", field: nil)) == .conflict)
        #expect(Workspace.suggestionPortError(RustBridgeError(code: "SHOWN_FRAME_RELOAD_REQUIRED")) == .conflict)
        #expect(Workspace.suggestionPortError(RustBridgeError(code: "CANCELLED")) == .unknown(code: "CANCELLED"))
        #expect(Workspace.suggestionPortError(CancellationError()) == .unknown(code: "SAVE_FAILED"))
    }
}
