import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

// Shared fakes for the suggestion tests. None of them talks to a provider or a model: the policy is
// the real Rust core through the bridge, everything else is scripted.

/// A gate that holds a call until the test opens it.
actor SuggestionGate {
    private var continuation: CheckedContinuation<Void, Never>?
    private var opened = false
    func wait() async {
        if opened { return }
        await withCheckedContinuation { continuation = $0 }
    }
    func open() {
        opened = true
        continuation?.resume()
        continuation = nil
    }
}

actor SuggestionCounter {
    private(set) var value = 0
    func bump() { value += 1 }
}

final class FakeExecutor: LocalAIExecutor, @unchecked Sendable {  // @unchecked: every field is guarded by `lock`
    let source = LocalAISource.appleOnDevice
    private let lock = NSLock()
    private var _facts: LocalAIFacts
    private var _result: Result<ModelAnswer, any Error>
    private var _gate: SuggestionGate?
    private var _calls = 0
    private var _inputs: [SuggestionInput] = []

    init(runtime: LocalAIRuntime = .ready, languages: [String] = ["en"], free: UInt64 = 4_000, required: UInt64 = 1_000,
         result: Result<ModelAnswer, any Error> = .success(ModelAnswer(proposals: ["Draft the outline"]))) {
        _facts = LocalAIFacts(source: .appleOnDevice, runtime: runtime, supportedLanguages: languages,
                              freeMemoryMB: free, requiredMemoryMB: required)
        _result = result
    }
    var calls: Int { lock.withLock { _calls } }
    var inputs: [SuggestionInput] { lock.withLock { _inputs } }
    func setResult(_ result: Result<ModelAnswer, any Error>) { lock.withLock { _result = result } }
    func setGate(_ gate: SuggestionGate?) { lock.withLock { _gate = gate } }
    func facts() async -> LocalAIFacts { lock.withLock { _facts } }
    func suggest(_ input: SuggestionInput, terms: AITerms) async throws -> ModelAnswer {
        let (gate, result) = lock.withLock { () -> (SuggestionGate?, Result<ModelAnswer, any Error>) in
            _calls += 1
            _inputs.append(input)
            return (_gate, _result)
        }
        await gate?.wait()
        return try result.get()
    }
}

final class FakeRemote: NavigatorRemote, @unchecked Sendable {  // @unchecked: every field is guarded by `lock`
    private let lock = NSLock()
    private var _status: NavigatorStatusDTO
    private var _result: Result<NavigatorSuggestionResponseDTO, any Error>
    private var _gate: SuggestionGate?
    private var _statusCalls = 0
    private var _bodies: [NavigatorSuggestionBody] = []

    init(status: NavigatorStatusDTO = FakeRemote.configured,
         result: Result<NavigatorSuggestionResponseDTO, any Error> = .success(
             NavigatorSuggestionResponseDTO(requestID: "nav_req_1", provider: "openai", proposals: ["Draft the outline"]))) {
        _status = status
        _result = result
    }
    static let configured = NavigatorStatusDTO(provider: "openai", consent: nil, consentCurrent: false,
                                               consentTextVersion: 1, available: true)
    var suggestCalls: Int { lock.withLock { _bodies.count } }
    var statusCalls: Int { lock.withLock { _statusCalls } }
    var bodies: [NavigatorSuggestionBody] { lock.withLock { _bodies } }
    func setResult(_ result: Result<NavigatorSuggestionResponseDTO, any Error>) { lock.withLock { _result = result } }
    func setGate(_ gate: SuggestionGate?) { lock.withLock { _gate = gate } }
    func status() async throws -> NavigatorStatusDTO { lock.withLock { _statusCalls += 1; return _status } }
    func suggest(_ body: NavigatorSuggestionBody) async throws -> NavigatorSuggestionResponseDTO {
        let (gate, result) = lock.withLock { () -> (SuggestionGate?, Result<NavigatorSuggestionResponseDTO, any Error>) in
            _bodies.append(body)
            return (_gate, _result)
        }
        await gate?.wait()
        return try result.get()
    }
}

@MainActor
final class FakePort: ReviewSuggestionPort {
    var suggestionOwner = "owner-1"
    var title = "Renovate the bathroom"
    var notes = "Tiles chosen"
    var consents: [OwnerConsentFact] = []
    var shown: ShownTask?
    var gone = false
    var saveOutcomes: [(any Error)?] = []
    var applyOutcome: (any Error)?
    var grantCalls = 0
    var revokeCalls = 0
    private(set) var saves: [(notes: String, editorID: String)] = []
    private(set) var applies: [(title: String, aiUse: AIUse, requestID: String?, editorID: String)] = []
    /// Notes written by distinct edit identities; a repeated identity is the same edit.
    private var committed: [String: String] = [:]
    private(set) var appendedAnswers = 0

    func suggestionInput(for taskID: TaskID, kind: SuggestionKind, stallReason: StallReason?) -> SuggestionInput? {
        gone ? nil : SuggestionInput(kind: kind, taskTitle: title, taskNotes: notes, stallReason: stallReason?.rawValue,
                                     projectName: nil, openTaskTitles: [])
    }
    func suggestionShownTask(_ taskID: TaskID) -> ShownTask? { shown }
    func suggestionNotes(_ taskID: TaskID) -> String? { gone ? nil : notes }
    func suggestionConsents() -> [OwnerConsentFact] { consents }
    func grantSuggestionConsent(provider: String, textVersion: Int) async throws {
        grantCalls += 1
        consents = [OwnerConsentFact(owner: suggestionOwner, provider: provider, grantedAt: Date(timeIntervalSince1970: 1_800_000_000),
                                     consentTextVersion: textVersion)]
    }
    func revokeSuggestionConsent(provider: String) async throws {
        revokeCalls += 1
        consents = consents.map {
            var consent = $0
            consent.revokedAt = Date(timeIntervalSince1970: 1_800_000_100)
            return consent
        }
    }
    func saveSuggestionNotes(_ taskID: TaskID, notes newNotes: String, editorID: String) async throws {
        saves.append((newNotes, editorID))
        let outcome = saveOutcomes.isEmpty ? nil : saveOutcomes.removeFirst()
        if let error = outcome as? SuggestionPortError, error == .unknown(code: "LOST_ACK") {
            commit(newNotes, editorID)  // the write happened; the acknowledgement was lost
            throw error
        }
        if let outcome { throw outcome }
        commit(newNotes, editorID)
    }
    private func commit(_ newNotes: String, _ editorID: String) {
        if committed[editorID] == nil {
            committed[editorID] = newNotes
            appendedAnswers += 1
            notes = newNotes
        }
    }
    func applySuggestion(kind: SuggestionKind, taskID: TaskID, title: String, aiUse: AIUse, navigatorRequestID: String?,
                         expected: ShownTask, editorID: String) async throws {
        applies.append((title, aiUse, navigatorRequestID, editorID))
        if let applyOutcome { throw applyOutcome }
    }
}

@MainActor
final class PortKeeper {
    var ports: [FakePort] = []
}

@MainActor
@Suite struct ReviewSuggestionModelTests {
    let runtime: RustBridgeRuntime
    let taskID = TaskID("task-1")
    /// The model holds its port weakly, as in the app; the test keeps the ports alive.
    private let keeper = PortKeeper()

    init() throws { runtime = try RustBridgeRuntime() }

    private func adapter(_ executors: [FakeExecutor]) -> LocalAIAdapter {
        LocalAIAdapter(policy: runtime, executors: executors, detectLanguage: { _ in "en" })
    }

    private func model(
        _ port: FakePort, executor: FakeExecutor? = FakeExecutor(), remote: FakeRemote? = nil,
        privacy: AIPrivacyMode = .onDeviceOnly, kind: SuggestionKind = .reformulate,
        journal: any ReviewSuggestionJournal = InMemoryReviewSuggestionJournal()
    ) -> ReviewSuggestionModel {
        var counter = 0
        keeper.ports.append(port)
        return ReviewSuggestionModel(
            taskID: taskID, kind: kind, port: port, remote: remote, adapter: adapter(executor.map { [$0] } ?? []),
            journal: journal, privacy: privacy, makeID: { counter += 1; return "id\(counter)" })
    }

    private func granted(_ port: FakePort) {
        port.consents = [OwnerConsentFact(owner: port.suggestionOwner, provider: "openai",
                                          grantedAt: Date(timeIntervalSince1970: 1_800_000_000), consentTextVersion: 1)]
    }

    private func started(_ model: ReviewSuggestionModel) async -> ReviewSuggestionModel {
        model.request()
        await model.settled()
        return model
    }

    // MARK: Local journeys (026-FR-018)

    @Test("026-FR-018 an available local adapter returns validated proposals and sends nothing remote")
    func localAvailableJourney() async {
        let remote = FakeRemote()
        let sut = await started(model(FakePort(), remote: remote, privacy: .remoteAllowed))
        #expect(sut.phase == .proposals)
        #expect(sut.proposals == ["Draft the outline"])
        #expect(remote.suggestCalls == 0)
    }

    @Test("026-FR-018 026-SC-006 on-device only with no suitable local executor continues manually, no remote request")
    func localUnavailableOnDeviceOnly() async {
        let remote = FakeRemote()
        for executor in [FakeExecutor(runtime: .modelNotReady), FakeExecutor(languages: ["de"]), FakeExecutor(free: 10)] {
            let sut = await started(model(FakePort(), executor: executor, remote: remote))
            guard case .unavailable(.localUnavailable(let reasons)) = sut.phase else {
                Issue.record("expected unavailable, got \(sut.phase)")
                continue
            }
            #expect(reasons.count == 1)
            await sut.continueWithoutAI()
            #expect(sut.phase == .manual)
        }
        #expect(remote.suggestCalls == 0 && remote.statusCalls == 0)
    }

    @Test("026-FR-018 a local executor error in on-device-only mode never falls through to the cloud")
    func localErrorStaysLocal() async {
        let remote = FakeRemote()
        let port = FakePort()
        granted(port)
        let executor = FakeExecutor(result: .failure(LocalAIError.executorFailed))
        let sut = await started(model(port, executor: executor, remote: remote))
        #expect(sut.phase == .unavailable(.localFailed))
        #expect(!sut.canTryCloud)
        sut.tryCloudInstead()
        await sut.settled()
        #expect(sut.phase == .unavailable(.localFailed))
        #expect(remote.suggestCalls == 0)
    }

    @Test("026-FR-018 after a local failure the cloud runs only on an explicit choice and current consent")
    func localErrorThenExplicitCloud() async {
        let remote = FakeRemote()
        let port = FakePort()
        granted(port)
        let executor = FakeExecutor(result: .failure(LocalAIError.executorFailed))
        let sut = model(port, executor: executor, remote: remote, privacy: .remoteAllowed)
        sut.request()
        await sut.settled()
        #expect(sut.phase == .unavailable(.localFailed) && sut.canTryCloud)
        #expect(remote.suggestCalls == 0, "no silent fallback")
        sut.tryCloudInstead()
        await sut.settled()
        #expect(sut.phase == .proposals)
        #expect(remote.suggestCalls == 1)
    }

    // MARK: Consent (026-FR-019)

    @Test("026-FR-019 without consent nothing is sent; declining never contacts the provider")
    func declinedConsentNeverContactsProvider() async {
        let remote = FakeRemote()
        let sut = model(FakePort(), executor: nil, remote: remote, privacy: .remoteAllowed)
        sut.request()
        await sut.settled()
        #expect(sut.phase == .needsConsent(provider: "openai", textVersion: 1, state: .missing))
        sut.declineCloud()
        #expect(sut.phase == .manual)
        #expect(remote.suggestCalls == 0)
    }

    @Test("026-FR-019 allowing cloud grants once, then sends exactly the approved payload")
    func allowCloudSendsApprovedPayloadOnly() async throws {
        let remote = FakeRemote()
        let port = FakePort()
        let sut = model(port, executor: nil, remote: remote, privacy: .remoteAllowed)
        sut.request()
        await sut.settled()
        await sut.allowCloud()
        await sut.settled()
        #expect(port.grantCalls == 1 && sut.phase == .proposals)
        let body = try #require(remote.bodies.first)
        let json = try #require(JSONSerialization.jsonObject(with: JSONEncoder().encode(body)) as? [String: Any])
        #expect(Set(json.keys) == ["kind", "consent", "task"])
        let task = try #require(json["task"] as? [String: Any])
        #expect(Set(task.keys) == ["title", "notes"])
        #expect(task["notes"] as? String == "Tiles chosen")
    }

    @Test("026-FR-019 revoked or outdated consent is refused before any provider call")
    func revokedConsentRefused() async {
        let remote = FakeRemote()
        let port = FakePort()
        port.consents = [OwnerConsentFact(owner: "owner-1", provider: "openai", grantedAt: Date(timeIntervalSince1970: 1_800_000_000),
                                          revokedAt: Date(timeIntervalSince1970: 1_800_000_050), consentTextVersion: 1)]
        let revoked = await started(model(port, executor: nil, remote: remote, privacy: .remoteAllowed))
        #expect(revoked.phase == .consentOff)
        port.consents = [OwnerConsentFact(owner: "owner-1", provider: "openai", grantedAt: Date(timeIntervalSince1970: 1_800_000_000),
                                          consentTextVersion: 0 + 1)]
        let old = FakeRemote(status: NavigatorStatusDTO(provider: "openai", consent: nil, consentCurrent: false,
                                                        consentTextVersion: 2, available: true))
        let outdated = await started(model(port, executor: nil, remote: old, privacy: .remoteAllowed))
        #expect(outdated.phase == .needsConsent(provider: "openai", textVersion: 2, state: .textOutdated))
        #expect(remote.suggestCalls == 0 && old.suggestCalls == 0)
    }

    @Test("026-FR-019 revoking while a cloud request is in flight discards the late result")
    func revocationDuringRequest() async {
        let remote = FakeRemote()
        let gate = SuggestionGate()
        remote.setGate(gate)
        let port = FakePort()
        granted(port)
        let sut = model(port, executor: nil, remote: remote, privacy: .remoteAllowed)
        sut.request()
        while remote.suggestCalls == 0 { await Task.yield() }
        await sut.revokeCloud(provider: "openai")
        await gate.open()
        await sut.settled()
        #expect(sut.phase == .consentOff && sut.proposals.isEmpty)
    }

    @Test("026-FR-019 a result for another account is not inserted")
    func accountSwitchDiscardsResult() async {
        let remote = FakeRemote()
        let gate = SuggestionGate()
        remote.setGate(gate)
        let port = FakePort()
        granted(port)
        let sut = model(port, executor: nil, remote: remote, privacy: .remoteAllowed)
        sut.request()
        while remote.suggestCalls == 0 { await Task.yield() }
        port.suggestionOwner = "owner-2"
        await gate.open()
        await sut.settled()
        #expect(sut.proposals.isEmpty && sut.phase == .idle)
    }

    // MARK: Cancellation, interruption, UI closure (026-FR-020)

    @Test("026-FR-020 explicit cancel before transmission is durable and a late local result is ignored")
    func cancelIgnoresLateResult() async throws {
        let executor = FakeExecutor()
        let gate = SuggestionGate()
        executor.setGate(gate)
        let journal = InMemoryReviewSuggestionJournal()
        let sut = model(FakePort(), executor: executor, journal: journal)
        sut.request()
        while executor.calls == 0 { await Task.yield() }
        await sut.cancel()
        #expect(sut.phase == .cancelled(afterTransmission: false))
        #expect(try await journal.load(sut.journalKey)?.stage == .cancelled)
        await gate.open()
        await sut.settled()
        #expect(sut.phase == .cancelled(afterTransmission: false) && sut.proposals.isEmpty)
    }

    @Test("026-FR-020 cancel after transmission says so, records it, and ignores the result")
    func cancelAfterTransmission() async throws {
        let remote = FakeRemote()
        let gate = SuggestionGate()
        remote.setGate(gate)
        let port = FakePort()
        granted(port)
        let journal = InMemoryReviewSuggestionJournal()
        let sut = model(port, executor: nil, remote: remote, privacy: .remoteAllowed, journal: journal)
        sut.request()
        while remote.suggestCalls == 0 { await Task.yield() }
        await sut.cancel()
        #expect(sut.phase == .cancelled(afterTransmission: true))
        #expect(try await journal.load(sut.journalKey)?.transmitted == true)
        await gate.open()
        await sut.settled()
        #expect(sut.proposals.isEmpty && sut.phase == .cancelled(afterTransmission: true))
        // "Request again" is a new explicit request.
        sut.request()
        await sut.settled()
        #expect(remote.suggestCalls == 2)
    }

    @Test("026-FR-020 closing the UI alone keeps the live request; reopening finds it and its result")
    func closingUIKeepsRequestLive() async {
        let executor = FakeExecutor()
        let gate = SuggestionGate()
        executor.setGate(gate)
        let center = ReviewSuggestionCenter()
        let port = FakePort()
        let make = { self.model(port, executor: executor) }
        var first: ReviewSuggestionModel? = center.model(for: taskID, kind: .reformulate, make: make)
        first?.request()
        while executor.calls == 0 { await Task.yield() }
        first = nil  // the sheet is gone; nothing cancelled
        let reopened = center.model(for: taskID, kind: .reformulate, make: make)
        #expect(reopened.phase == .requesting)
        await gate.open()
        await reopened.settled()
        #expect(reopened.phase == .proposals)
        #expect(executor.calls == 1)
    }

    @Test("026-FR-020 a request lost with the process becomes interrupted and is never resent")
    func lostRequestIsInterrupted() async {
        let remote = FakeRemote()
        let port = FakePort()
        granted(port)
        let journal = InMemoryReviewSuggestionJournal()
        try? await journal.save(ReviewSuggestionRecord(stage: .requestSent, transmitted: true, answerDraft: "", pending: nil),
                                for: "task-1:reformulate")
        let sut = model(port, executor: nil, remote: remote, privacy: .remoteAllowed, journal: journal)
        await sut.recover()
        #expect(sut.phase == .interrupted(mayHaveBeenSent: true))
        await sut.settled()
        #expect(remote.suggestCalls == 0)
        sut.request()
        await sut.settled()
        #expect(remote.suggestCalls == 1, "only the explicit request transmits")
    }

    @Test("026-FR-020 a lost synchronous response is interrupted without automatic resend")
    func lostResponseNoResend() async {
        let remote = FakeRemote(result: .failure(APIError(kind: .network("offline"), message: "offline", requestMayHaveBeenSent: true)))
        let port = FakePort()
        granted(port)
        let sut = await started(model(port, executor: nil, remote: remote, privacy: .remoteAllowed))
        #expect(sut.phase == .interrupted(mayHaveBeenSent: true))
        #expect(remote.suggestCalls == 1)
    }

    @Test("026-FR-020 an invalid proposal shows nothing and changes no Task")
    func invalidProposalChangesNothing() async {
        let port = FakePort()
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: ["Call Marta about 500 dollars", "#urgent do it"])))
        let sut = await started(model(port, executor: executor))
        #expect(sut.phase == .unavailable(.invalidProposal) && sut.proposals.isEmpty)
        await sut.apply("Call Marta about 500 dollars")
        #expect(port.applies.isEmpty && port.saves.isEmpty)
    }

    // MARK: Apply (026-FR-020)

    @Test("026-FR-020 nothing changes until Apply; apply runs the shown-version decision with the edit recorded")
    func applyIsExplicitAndShownVersionChecked() async throws {
        let port = FakePort()
        port.shown = ShownTask(Self.record())
        let remote = FakeRemote()
        granted(port)
        let sut = model(port, executor: nil, remote: remote, privacy: .remoteAllowed)
        sut.request()
        await sut.settled()
        #expect(sut.phase == .proposals && port.applies.isEmpty, "a proposal alone is not a Task change")
        await sut.apply("Draft the outline for the bathroom")
        #expect(sut.phase == .applied)
        #expect(port.applies.count == 1)
        #expect(port.applies.first?.aiUse == .edited && port.applies.first?.requestID == "nav_req_1")
    }

    @Test("026-FR-020 a changed task is stale, keeps the proposals and asks for a fresh confirmation")
    func staleProposal() async {
        let port = FakePort()
        port.shown = ShownTask(Self.record())
        port.applyOutcome = SuggestionPortError.conflict
        let sut = await started(model(port))
        await sut.apply("Draft the outline")
        #expect(sut.phase == .stale && sut.proposals == ["Draft the outline"])
        port.applyOutcome = nil
        sut.reviewAfterChange()
        #expect(sut.phase == .proposals)
        await sut.apply("Draft the outline")
        #expect(sut.phase == .applied && port.applies.count == 2)
    }

    static func record() -> TaskRecord {
        TaskRecord(id: TaskID("task-1"), title: "Renovate the bathroom", state: .next,
                   orderKey: 0, createdAt: Date(timeIntervalSince1970: 0), updatedAt: Date(timeIntervalSince1970: 0))
    }

    // MARK: Clarifying question (026-FR-016)

    private func questioner(_ port: FakePort, executor: FakeExecutor) async -> ReviewSuggestionModel {
        executor.setResult(.success(ModelAnswer(proposals: [], clarifyingQuestion: "Which tiles did you choose")))
        let sut = await started(model(port, executor: executor))
        return sut
    }

    @Test("026-FR-020 a valid clarifying question is its own state, not an empty result or error")
    func clarifyingQuestionState() async {
        let sut = await questioner(FakePort(), executor: FakeExecutor())
        #expect(sut.phase == .question && sut.question == "Which tiles did you choose" && sut.proposals.isEmpty)
    }

    @Test("026-FR-020 the answer is appended to the notes once, the saved projection adopted, then inference reruns")
    func answerSavedThenRerun() async {
        let port = FakePort()
        let executor = FakeExecutor()
        let sut = await questioner(port, executor: executor)
        sut.answerDraft = "Grey ones"
        sut.submitAnswer()
        executor.setResult(.success(ModelAnswer(proposals: ["Order the grey tiles"])))
        await sut.settled()
        #expect(port.saves.count == 1 && port.notes == "Tiles chosen\n\nGrey ones" && port.appendedAnswers == 1)
        #expect(port.saves.first?.editorID == "suggestion-answer-id1")
        #expect(executor.inputs.last?.taskNotes == "Tiles chosen\n\nGrey ones", "the rerun uses the saved notes")
        #expect(sut.phase == .proposals && sut.answerDraft.isEmpty && !sut.answerSaved)
    }

    @Test("026-FR-020 an unknown save outcome reconciles with the same identity and never appends twice")
    func unknownOutcomeKeepsIdentity() async {
        let port = FakePort()
        port.saveOutcomes = [SuggestionPortError.unknown(code: "LOST_ACK")]
        let executor = FakeExecutor()
        let sut = await questioner(port, executor: executor)
        sut.answerDraft = "Grey ones"
        sut.submitAnswer()
        await sut.settled()
        #expect(sut.phase == .answerNotSaved(.unknownOutcome) && sut.answerDraft == "Grey ones")
        executor.setResult(.success(ModelAnswer(proposals: ["Order the grey tiles"])))
        sut.submitAnswer()
        await sut.settled()
        #expect(port.saves.count == 2 && port.saves[0].editorID == port.saves[1].editorID)
        #expect(port.saves[0].notes == port.saves[1].notes)
        #expect(port.appendedAnswers == 1, "the second attempt is the same edit")
        #expect(sut.phase == .proposals)
    }

    @Test("026-FR-020 a save conflict keeps the answer and never submits inference as if the edit succeeded")
    func saveConflictKeepsAnswer() async {
        let port = FakePort()
        port.saveOutcomes = [SuggestionPortError.conflict]
        let executor = FakeExecutor()
        let sut = await questioner(port, executor: executor)
        let before = executor.calls
        sut.answerDraft = "Grey ones"
        sut.submitAnswer()
        await sut.settled()
        #expect(sut.phase == .answerNotSaved(.conflict) && sut.answerDraft == "Grey ones" && !sut.answerSaved)
        #expect(executor.calls == before)
    }

    @Test("026-FR-020 after the answer is saved, a failed suggestion retries inference only")
    func inferenceOnlyRetry() async {
        let port = FakePort()
        let executor = FakeExecutor()
        let sut = await questioner(port, executor: executor)
        sut.answerDraft = "Grey ones"
        executor.setResult(.failure(LocalAIError.executorFailed))
        sut.submitAnswer()
        await sut.settled()
        #expect(sut.answerSaved && sut.phase == .answerSavedSuggestionFailed(.localFailed))
        executor.setResult(.success(ModelAnswer(proposals: ["Order the grey tiles"])))
        sut.retrySuggestions()
        await sut.settled()
        #expect(sut.phase == .proposals)
        #expect(port.saves.count == 1 && port.appendedAnswers == 1, "the edit is never repeated")
    }

    @Test("026-FR-020 an unsubmitted answer survives interruption; only an explicit discard removes it")
    func unsavedAnswerSurvives() async {
        let port = FakePort()
        let journal = InMemoryReviewSuggestionJournal()
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: [], clarifyingQuestion: "Which tiles did you choose")))
        let first = model(port, executor: executor, journal: journal)
        first.request()
        await first.settled()
        first.answerDraft = "Grey ones"
        #expect(first.hasUnsavedAnswer)
        await first.settled()
        let relaunched = model(port, executor: executor, journal: journal)
        await relaunched.recover()
        #expect(relaunched.answerDraft == "Grey ones")
        relaunched.discardAnswer()
        #expect(relaunched.answerDraft.isEmpty && !relaunched.hasUnsavedAnswer)
    }

    @Test("026-FR-020 a process lost during the save recovers with the stored identity, not a new edit")
    func recoveryMidSave() async {
        let port = FakePort()
        let journal = InMemoryReviewSuggestionJournal()
        let pending = ReviewSuggestionRecord.PendingAnswer(editorID: "suggestion-answer-old", answer: "Grey ones",
                                                           newNotes: "Tiles chosen\n\nGrey ones", outcomeUnknown: false)
        try? await journal.save(ReviewSuggestionRecord(stage: .answerSaving, transmitted: false, answerDraft: "Grey ones",
                                                       pending: pending), for: "task-1:reformulate")
        let executor = FakeExecutor(result: .success(ModelAnswer(proposals: ["Order the grey tiles"])))
        let sut = model(port, executor: executor, journal: journal)
        await sut.recover()
        #expect(sut.phase == .answerNotSaved(.unknownOutcome) && sut.answerDraft == "Grey ones")
        sut.submitAnswer()
        await sut.settled()
        #expect(port.saves.first?.editorID == "suggestion-answer-old")
        #expect(sut.phase == .proposals)
    }
}
