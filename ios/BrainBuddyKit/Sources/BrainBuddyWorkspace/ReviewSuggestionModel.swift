import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Observation

// The shared state machine of the first Weekly Review suggestion request (design M-04 / D-04,
// states .01-.20; spec 026 T049). The iPhone and Mac sheets (PR-59/60) render `phase` and call
// the actions below; they hold no copy of this machine. Policy (which executor may see the
// input, consent) is the shared Rust core's, through `LocalAIAdapter`; GTD rules stay in the
// reducer, reached through the `ReviewSuggestionPort` (the workspace).

/// Failures of the task port, content-free.
public enum SuggestionPortError: Error, Equatable, Sendable {
    /// The task changed since it was shown (the shown-version check refused).
    case conflict
    /// The save was refused; nothing was written.
    case rejected(code: String)
    /// The outcome of a save is not known (a lost acknowledgement); retrying the same identity is safe.
    case unknown(code: String)
}

/// What the model needs from the workspace; `Workspace` conforms (`Workspace+ReviewAI`). The two
/// save calls throw `SuggestionPortError`; any other error counts as an unknown outcome.
@MainActor
public protocol ReviewSuggestionPort: AnyObject {
    /// The signed-in account, or a stable local label when account-less.
    var suggestionOwner: String { get }
    /// The approved FR-019 payload from the current projection, nil when the task is gone.
    func suggestionInput(for taskID: TaskID, kind: SuggestionKind, stallReason: StallReason?) -> SuggestionInput?
    /// The task as the sheet shows it now; the shown-version check of the apply step.
    func suggestionShownTask(_ taskID: TaskID) -> ShownTask?
    func suggestionNotes(_ taskID: TaskID) -> String?
    func suggestionConsents() -> [OwnerConsentFact]
    func grantSuggestionConsent(provider: String, textVersion: Int) async throws
    func revokeSuggestionConsent(provider: String) async throws
    /// One ordinary notes edit with a stable identity: the same `editorID` and `notes` after an
    /// unknown outcome return the original save and never append twice.
    func saveSuggestionNotes(_ taskID: TaskID, notes: String, editorID: String) async throws
    /// An accepted suggestion. Inside a review run (`sessionID`) it is the same session-bound decision the
    /// manual card records, returning its ID for Undo; outside a run it is a plain wording update (nil).
    /// Both are checked against `expected`.
    func applySuggestion(kind: SuggestionKind, taskID: TaskID, title: String, aiUse: AIUse,
                         navigatorRequestID: String?, expected: ShownTask, sessionID: ReviewSessionID?,
                         editorID: String) async throws -> DecisionID?
}

/// What survives a closed sheet or a lost process. Never proposals or model output; the answer
/// the person typed and the stable identity of its notes edit are theirs, kept locally.
public struct ReviewSuggestionRecord: Codable, Equatable, Sendable {
    public enum Stage: String, Codable, Sendable {
        case requestSent, cancelled, answerSaving, answerSaved
    }
    public struct PendingAnswer: Codable, Equatable, Sendable {
        public var editorID: String
        public var answer: String
        public var newNotes: String
        public var outcomeUnknown: Bool
    }
    public var stage: Stage
    public var transmitted: Bool
    public var answerDraft: String
    public var pending: PendingAnswer?
}

public protocol ReviewSuggestionJournal: Sendable {
    func load(_ key: String) async throws -> ReviewSuggestionRecord?
    func save(_ record: ReviewSuggestionRecord, for key: String) async throws
    func clear(_ key: String) async throws
}

public actor InMemoryReviewSuggestionJournal: ReviewSuggestionJournal {
    private var records: [String: ReviewSuggestionRecord] = [:]
    public init() {}
    public func load(_ key: String) -> ReviewSuggestionRecord? { records[key] }
    public func save(_ record: ReviewSuggestionRecord, for key: String) { records[key] = record }
    public func clear(_ key: String) { records[key] = nil }
}

@MainActor
@Observable
public final class ReviewSuggestionModel {
    public enum Unavailable: Equatable, Sendable {
        /// No local executor is suitable and no remote request is permitted or made.
        case localUnavailable([LocalAIUnavailability])
        /// The local executor failed on this request; a cloud run needs an explicit choice.
        case localFailed
        case remoteOff
        case signedOut
        case rateLimited
        case providerError
        /// The answer failed the shared validation; nothing is shown and nothing changes.
        case invalidProposal
        case inputTooLarge
        case taskGone
    }

    public enum AnswerSaveFailure: Equatable, Sendable {
        /// The task changed; the existing conflict resolution decides, the answer stays.
        case conflict
        case rejected(code: String)
        /// A lost acknowledgement; retrying reconciles with the same identity.
        case unknownOutcome
    }

    public enum Phase: Equatable, Sendable {
        case idle
        case requesting
        case cancelling
        case cancelled(afterTransmission: Bool)
        case interrupted(mayHaveBeenSent: Bool)
        case needsConsent(provider: String, textVersion: Int, state: AIConsentState)
        case consentOff
        case unavailable(Unavailable)
        case noSuggestion
        case proposals
        case question
        case savingAnswer
        case answerNotSaved(AnswerSaveFailure)
        case answerSavedSuggestionFailed(Unavailable)
        case stale
        case applying
        case applied
        case manual
    }

    public let taskID: TaskID
    public let kind: SuggestionKind
    public private(set) var phase = Phase.idle
    public private(set) var proposals: [String] = []
    public private(set) var question: String?
    public private(set) var notesTruncated = false
    /// A safe reference to quote for a provider failure; never content.
    public private(set) var referenceID: String?
    /// The notes edit for the person's answer is committed; only inference may be retried.
    public private(set) var answerSaved = false
    /// Why the last apply did not land; the proposals stay.
    public private(set) var applyFailure: String?
    public private(set) var proposalsWereShown = false
    /// A local executor failed and the person may explicitly choose the cloud.
    public private(set) var canTryCloud = false
    public var answerDraft = "" {
        didSet { if answerDraft != oldValue { persistDraft() } }
    }

    @ObservationIgnored private let stallReason: StallReason?
    // Weak: the workspace owns the center that owns this model. A gone workspace reads as a gone task.
    @ObservationIgnored private weak var weakPort: (any ReviewSuggestionPort)?
    private var port: PortHandle { PortHandle(base: weakPort) }
    @ObservationIgnored private let remote: (any NavigatorRemote)?
    @ObservationIgnored private let adapter: LocalAIAdapter
    @ObservationIgnored private let journal: any ReviewSuggestionJournal
    @ObservationIgnored private let privacy: AIPrivacyMode
    @ObservationIgnored private let makeID: @MainActor () -> String
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var task: Task<Void, Never>?
    @ObservationIgnored private var transmitted = false
    @ObservationIgnored private var failedLocal: [LocalAISource] = []
    @ObservationIgnored private var shown: ShownTask?
    public private(set) var navigatorRequestID: String?
    /// The review decision an in-run apply recorded, for Undo; nil outside a run.
    public private(set) var appliedDecisionID: DecisionID?
    @ObservationIgnored private var pending: ReviewSuggestionRecord.PendingAnswer?
    @ObservationIgnored private var applyEditorID: String?
    @ObservationIgnored private var persisting: Task<Void, Never>?
    @ObservationIgnored private var restoring = false

    public init(taskID: TaskID, kind: SuggestionKind, stallReason: StallReason? = nil,
                port: any ReviewSuggestionPort, remote: (any NavigatorRemote)?, adapter: LocalAIAdapter,
                journal: any ReviewSuggestionJournal = InMemoryReviewSuggestionJournal(),
                privacy: AIPrivacyMode, makeID: @escaping @MainActor () -> String = { UUID().uuidString.lowercased() }) {
        self.taskID = taskID
        self.kind = kind
        self.stallReason = stallReason
        self.weakPort = port
        self.remote = remote
        self.adapter = adapter
        self.journal = journal
        self.privacy = privacy
        self.makeID = makeID
    }

    public var journalKey: String { taskID.rawValue + ":" + kind.rawValue }

    /// The answer was typed but not yet added to the notes (.20: leaving asks first).
    public var hasUnsavedAnswer: Bool {
        !answerSaved && !answerDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    public var isRequestLive: Bool { phase == .requesting || phase == .savingAnswer || phase == .cancelling }

    /// The AI-use code a manual decision records after the proposals were shown and not used (FR-026);
    /// the manual decision passes it with `navigatorRequestID`.
    public var aiUseForManualDecision: AIUse { proposalsWereShown ? .notUsed : .none }

    /// The task version the card showed; the apply step is checked against it. After an answer is
    /// saved the model adopts the saved projection instead.
    public func adoptShownTask(_ task: ShownTask) { shown = task }

    /// Waits for the running request or answer step; deterministic tests await it, a view does not.
    public func settled() async {
        await task?.value
        await persisting?.value
    }

    // MARK: Recovery (.15, .17-.19)

    /// Reads what an earlier model instance left. A request no live task backs is interrupted, never
    /// resent; a cancellation stays cancelled; an unsaved answer and its identity survive.
    public func recover() async {
        guard phase == .idle, let record = try? await journal.load(journalKey) else { return }
        guard phase == .idle else { return }
        restoring = true
        transmitted = record.transmitted
        pending = record.pending
        answerDraft = record.answerDraft
        switch record.stage {
        case .requestSent: phase = .interrupted(mayHaveBeenSent: record.transmitted)
        case .cancelled: phase = .cancelled(afterTransmission: record.transmitted)
        case .answerSaving:
            // The process ended during the save: whether it committed is unknown, so the stored identity is reused.
            if pending != nil { pending?.outcomeUnknown = true }
            phase = .answerNotSaved(.unknownOutcome)
        case .answerSaved:
            // The notes edit is committed; only inference may run again, never the edit.
            answerSaved = true
            phase = .interrupted(mayHaveBeenSent: record.transmitted)
        }
        restoring = false
    }

    // MARK: Request (.01-.09, .13-.15)

    /// The explicit request action; also "Request again" and "Try suggestions again".
    public func request() {
        guard canStart else { return }
        failedLocal = []
        start()
    }

    /// After a local failure: an explicit choice to run the shared policy again with the failed
    /// executor excluded, which may route to the cloud only through current consent.
    public func tryCloudInstead() {
        guard canTryCloud, canStart else { return }
        start()
    }

    /// "Allow cloud suggestions": records the consent through the existing path, then requests.
    public func allowCloud() async {
        guard case .needsConsent(let provider, let version, _) = phase else { return }
        do { try await port.grantSuggestionConsent(provider: provider, textVersion: version) } catch {
            phase = .unavailable(.providerError)
            return
        }
        failedLocal = []
        start()
    }

    /// "Continue without AI" at the consent prompt: nothing was or will be sent.
    public func declineCloud() { phase = .manual }

    public func revokeCloud(provider: String) async {
        generation += 1
        task?.cancel()
        try? await port.revokeSuggestionConsent(provider: provider)
        proposals = []
        question = nil
        phase = .consentOff
    }

    /// Explicit cancellation (.13). The local record is durable before the request is released, and
    /// a result that still arrives is ignored.
    public func cancel() async {
        guard phase == .requesting else { return }
        phase = .cancelling
        generation += 1
        let sent = transmitted
        await persist(stage: .cancelled, transmitted: sent)
        task?.cancel()
        task = nil
        phase = .cancelled(afterTransmission: sent)
    }

    /// "Continue without AI": manual work was never blocked; any live request is cancelled first.
    public func continueWithoutAI() async {
        if isRequestLive { await cancel() }
        generation += 1
        task?.cancel()
        proposals = []
        question = nil
        phase = .manual
    }

    private var canStart: Bool {
        switch phase {
        case .requesting, .cancelling, .savingAnswer, .applying, .applied: false
        default: true
        }
    }

    private func start() {
        generation += 1
        let current = generation
        phase = .requesting
        transmitted = false
        canTryCloud = false
        referenceID = nil
        task = Task { await self.run(current) }
    }

    private func live(_ current: Int) -> Bool { current == generation && !Task.isCancelled }

    private func consentStamp(_ owner: String) -> [OwnerConsentFact] {
        port.suggestionConsents().filter { $0.owner == owner }
    }

    private func run(_ current: Int) async {
        guard let input = port.suggestionInput(for: taskID, kind: kind, stallReason: stallReason) else {
            return fail(.unavailable(.taskGone), current)
        }
        if shown == nil || answerSaved { shown = port.suggestionShownTask(taskID) ?? shown }
        let owner = port.suggestionOwner
        let stamp = consentStamp(owner)
        var remoteFacts: RemoteFacts?
        if privacy == .remoteAllowed, let remote {
            // A status read carries no task data; a failure just means no cloud route.
            if let status = try? await remote.status() {
                guard live(current) else { return }
                remoteFacts = RemoteFacts(
                    provider: status.provider, credentialsConfigured: status.available,
                    consentTextVersion: status.consentTextVersion,
                    echoedConsent: status.provider.map { (allowed: true, provider: $0) }, consents: stamp)
            }
        }
        let route: AIRoute
        do {
            route = try await adapter.route(input: input, owner: owner, privacy: privacy,
                                            failedLocal: failedLocal, remote: remoteFacts)
        } catch { return fail(.unavailable(.providerError), current) }
        guard live(current) else { return }
        switch route {
        case .deterministic: finish(.noSuggestion, current)
        case .denied(let denial): deny(denial, remoteFacts, current)
        case .local(let source, let terms): await runLocal(source, terms, input, current)
        case .remote(let provider, _, _): await runRemote(provider, input, owner, stamp, current)
        }
    }

    private func runLocal(_ source: LocalAISource, _ terms: AITerms, _ input: SuggestionInput, _ current: Int) async {
        await persist(stage: .requestSent, transmitted: false)
        guard live(current) else { return }
        let adapter = self.adapter
        do {
            let answer = try await withTimeout(milliseconds: terms.timeoutMS) {
                try await adapter.runLocal(source, input: input, terms: terms)
            }
            guard live(current) else { return }
            await deliver(answer, input, current)
        } catch is CancellationError {
            return
        } catch {
            guard live(current) else { return }
            failedLocal.append(source)
            canTryCloud = privacy == .remoteAllowed
            fail(.unavailable(.localFailed), current)
        }
    }

    private func runRemote(_ provider: String, _ input: SuggestionInput, _ owner: String,
                           _ stamp: [OwnerConsentFact], _ current: Int) async {
        guard let remote else { return fail(.unavailable(.remoteOff), current) }
        // The send is recorded first: from here a lost request may have reached the provider.
        transmitted = true
        await persist(stage: .requestSent, transmitted: true)
        guard live(current) else { return }
        let body = NavigatorSuggestionBody(
            kind: input.kind.rawValue, consent: .init(externalProcessingAllowed: true, provider: provider),
            task: input.kind == .projectNextAction ? nil
                : .init(title: input.taskTitle ?? "", notes: input.taskNotes, stallReason: input.stallReason),
            project: input.kind == .projectNextAction
                ? .init(name: input.projectName ?? "", openTaskTitles: input.openTaskTitles) : nil)
        do {
            let response = try await remote.suggest(body)
            // Late, cancelled, another account, or consent changed meanwhile: nothing is inserted.
            guard live(current) else { return }
            guard port.suggestionOwner == owner else { phase = .idle; return }
            if consentStamp(owner) != stamp, !hasCurrentConsent(owner, provider) {
                proposals = []
                phase = .consentOff
                return
            }
            navigatorRequestID = response.requestID
            notesTruncated = response.notesTruncated
            await deliver(ModelAnswer(proposals: response.proposals ?? [], clarifyingQuestion: response.clarifyingQuestion),
                          input, current)
        } catch let error as APIError {
            guard live(current) else { return }
            map(error, current)
        } catch {
            guard live(current) else { return }
            fail(.interrupted(mayHaveBeenSent: true), current)
        }
    }

    private func hasCurrentConsent(_ owner: String, _ provider: String) -> Bool {
        consentStamp(owner).contains { $0.provider == provider && $0.revokedAt == nil }
    }

    private func map(_ error: APIError, _ current: Int) {
        referenceID = error.referenceID
        switch error.kind {
        case .unauthorized: fail(.unavailable(.signedOut), current)
        case .rateLimited: fail(.unavailable(.rateLimited), current)
        case .featureDisabled: fail(.unavailable(.remoteOff), current)
        default:
            if error.isUncertainOutcome || error.requestMayHaveBeenSent {
                fail(.interrupted(mayHaveBeenSent: true), current)
            } else {
                fail(.unavailable(.providerError), current)
            }
        }
    }

    private func deny(_ denial: AIDenial, _ remoteFacts: RemoteFacts?, _ current: Int) {
        switch denial {
        case .cancelled: return
        case .localUnavailable(let reasons): fail(.unavailable(.localUnavailable(reasons)), current)
        case .remoteDisabled, .credentialsMissing, .providerMismatch: fail(.unavailable(.remoteOff), current)
        case .inputTooLarge: fail(.unavailable(.inputTooLarge), current)
        case .consentRequired(let state):
            // Nothing was sent. The provider and consent text come from the configured server facts.
            guard state != .revoked else { return finish(.consentOff, current) }
            guard let provider = remoteFacts?.provider, let version = remoteFacts?.consentTextVersion else {
                return fail(.unavailable(.remoteOff), current)
            }
            finish(.needsConsent(provider: provider, textVersion: version, state: state), current)
        }
    }

    private func deliver(_ answer: ModelAnswer, _ input: SuggestionInput, _ current: Int) async {
        let verdict: ValidatedAnswer
        do { verdict = try await adapter.validate(answer, for: input) } catch {
            return fail(.unavailable(.invalidProposal), current)
        }
        guard live(current) else { return }
        switch verdict {
        case .proposals(let values):
            proposals = values
            question = nil
            proposalsWereShown = true
            finish(.proposals, current)
        case .question(let text):
            question = text
            proposals = []
            finish(.question, current)
        case .malformed: fail(.unavailable(.invalidProposal), current)
        case .noUsefulSuggestion: finish(.noSuggestion, current)
        }
    }

    private func finish(_ next: Phase, _ current: Int) {
        guard current == generation else { return }
        phase = next
        if next == .proposals || next == .noSuggestion {
            answerSaved = false
            pending = nil
            answerDraft = ""
        }
        if next != .question { clearJournal() }
        task = nil
    }

    /// A failed run. Once the answer is committed it is the "saved, suggestion failed" state (.19).
    private func fail(_ next: Phase, _ current: Int) {
        guard current == generation else { return }
        if answerSaved, case .unavailable(let reason) = next {
            phase = .answerSavedSuggestionFailed(reason)
        } else {
            phase = next
        }
        task = nil
    }

    // MARK: Clarifying question (.16-.20)

    /// "Add to notes and suggest again": one ordinary notes edit with the answer appended once,
    /// the saved projection adopted, then inference again. The answer is never appended twice.
    public func submitAnswer() {
        switch phase {
        case .question, .answerNotSaved: break
        default: return
        }
        let text = answerDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        generation += 1
        let current = generation
        phase = .savingAnswer
        task = Task { await self.saveAnswer(text, current) }
    }

    private func saveAnswer(_ text: String, _ current: Int) async {
        let identity: ReviewSuggestionRecord.PendingAnswer
        if let existing = pending, existing.outcomeUnknown, existing.answer == text {
            identity = existing
        } else {
            guard let notes = port.suggestionNotes(taskID) else { return fail(.unavailable(.taskGone), current) }
            identity = .init(editorID: "suggestion-answer-" + makeID(), answer: text,
                             newNotes: notes.isEmpty ? text : notes + "\n\n" + text, outcomeUnknown: false)
        }
        pending = identity
        // The identity is durable before the first save attempt, so a lost acknowledgement reconciles.
        await persist(stage: .answerSaving, transmitted: transmitted)
        do {
            try await port.saveSuggestionNotes(taskID, notes: identity.newNotes, editorID: identity.editorID)
        } catch {
            guard current == generation else { return }
            switch error as? SuggestionPortError ?? .unknown(code: "SAVE_FAILED") {
            case .unknown:
                pending?.outcomeUnknown = true
                phase = .answerNotSaved(.unknownOutcome)
            case .conflict:
                pending = nil
                phase = .answerNotSaved(.conflict)
            case .rejected(let code):
                pending = nil
                phase = .answerNotSaved(.rejected(code: code))
            }
            await persist(stage: .answerSaving, transmitted: transmitted)
            task = nil
            return
        }
        guard current == generation else { return }
        answerSaved = true
        answerDraft = ""
        pending = nil
        await persist(stage: .answerSaved, transmitted: transmitted)
        guard current == generation else { return }
        phase = .requesting
        await run(current)
    }

    /// "Try suggestions again" after the answer was saved: inference only.
    public func retrySuggestions() {
        guard answerSaved, canStart else { return }
        failedLocal = []
        start()
    }

    /// An explicit Discard (.20). A saved answer is already in the notes and is not removed.
    public func discardAnswer() {
        guard !answerSaved else { return }
        pending = nil
        answerDraft = ""
        if phase == .answerNotSaved(.conflict) || phase == .answerNotSaved(.unknownOutcome) { phase = .question }
        clearJournal()
    }

    // MARK: Apply (.10-.12)

    /// "Apply suggestion": the ordinary decision command against the version the sheet showed.
    /// `text` may be an edited proposal. Nothing changes until this is called.
    public func apply(_ text: String, sessionID: ReviewSessionID? = nil) async {
        guard phase == .proposals, kind != .projectNextAction else { return }
        let title = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return }
        guard let expected = shown else { phase = .stale; return }
        let editorID = applyEditorID ?? "suggestion-apply-" + makeID()
        applyEditorID = editorID
        phase = .applying
        applyFailure = nil
        do {
            appliedDecisionID = try await port.applySuggestion(
                kind: kind, taskID: taskID, title: title, aiUse: proposals.contains(title) ? .asIs : .edited,
                navigatorRequestID: navigatorRequestID, expected: expected, sessionID: sessionID, editorID: editorID)
            phase = .applied
            proposals = []
            applyEditorID = nil
            clearJournal()
        } catch {
            switch error as? SuggestionPortError ?? .unknown(code: "APPLY_FAILED") {
            case .conflict:
                // The task changed; the proposals stay, the person rereads and confirms again.
                phase = .stale
                applyEditorID = nil
            case .rejected(let code):
                phase = .proposals
                applyFailure = code
                applyEditorID = nil
            case .unknown(let code):
                phase = .proposals
                applyFailure = code
            }
        }
    }

    /// After a stale task: reread the shown version and keep the proposals for a fresh confirmation.
    public func reviewAfterChange() {
        guard phase == .stale, let current = port.suggestionShownTask(taskID) else { return }
        shown = current
        phase = .proposals
    }

    /// "Keep current wording".
    public func keepCurrentWording() { phase = .manual }

    // MARK: Journal

    private func persist(stage: ReviewSuggestionRecord.Stage, transmitted sent: Bool) async {
        let record = ReviewSuggestionRecord(stage: stage, transmitted: sent, answerDraft: answerDraft, pending: pending)
        try? await journal.save(record, for: journalKey)
    }

    private func persistDraft() {
        guard !restoring, question != nil, !answerSaved else { return }
        let stage: ReviewSuggestionRecord.Stage = pending == nil ? .requestSent : .answerSaving
        let record = ReviewSuggestionRecord(stage: stage, transmitted: transmitted, answerDraft: answerDraft, pending: pending)
        let journal = self.journal, key = journalKey, previous = persisting
        persisting = Task {
            await previous?.value
            try? await journal.save(record, for: key)
        }
    }

    private func clearJournal() {
        let journal = self.journal, key = journalKey, previous = persisting
        persisting = Task {
            await previous?.value
            try? await journal.clear(key)
        }
    }
}

/// The port, or safe answers once the workspace is gone: no task, no consent, and saves that refuse.
@MainActor
private struct PortHandle {
    let base: (any ReviewSuggestionPort)?
    var suggestionOwner: String { base?.suggestionOwner ?? "" }
    func suggestionInput(for id: TaskID, kind: SuggestionKind, stallReason: StallReason?) -> SuggestionInput? {
        base?.suggestionInput(for: id, kind: kind, stallReason: stallReason)
    }
    func suggestionShownTask(_ id: TaskID) -> ShownTask? { base?.suggestionShownTask(id) }
    func suggestionNotes(_ id: TaskID) -> String? { base?.suggestionNotes(id) }
    func suggestionConsents() -> [OwnerConsentFact] { base?.suggestionConsents() ?? [] }
    func grantSuggestionConsent(provider: String, textVersion: Int) async throws {
        try await base?.grantSuggestionConsent(provider: provider, textVersion: textVersion)
    }
    func revokeSuggestionConsent(provider: String) async throws { try await base?.revokeSuggestionConsent(provider: provider) }
    func saveSuggestionNotes(_ id: TaskID, notes: String, editorID: String) async throws {
        guard let base else { throw SuggestionPortError.rejected(code: "WORKSPACE_GONE") }
        try await base.saveSuggestionNotes(id, notes: notes, editorID: editorID)
    }
    func applySuggestion(kind: SuggestionKind, taskID: TaskID, title: String, aiUse: AIUse, navigatorRequestID: String?,
                         expected: ShownTask, sessionID: ReviewSessionID?, editorID: String) async throws -> DecisionID? {
        guard let base else { throw SuggestionPortError.rejected(code: "WORKSPACE_GONE") }
        return try await base.applySuggestion(kind: kind, taskID: taskID, title: title, aiUse: aiUse,
                                              navigatorRequestID: navigatorRequestID, expected: expected,
                                              sessionID: sessionID, editorID: editorID)
    }
}

/// Runs `work` and fails with `LocalAIError.executorFailed` if it outlives `milliseconds`.
private func withTimeout<T: Sendable>(
    milliseconds: UInt32, _ work: @escaping @Sendable () async throws -> T
) async throws -> T {
    try await withThrowingTaskGroup(of: T.self) { group in
        group.addTask { try await work() }
        group.addTask {
            try await Task.sleep(nanoseconds: UInt64(milliseconds) * 1_000_000)
            throw LocalAIError.executorFailed
        }
        defer { group.cancelAll() }
        guard let first = try await group.next() else { throw LocalAIError.executorFailed }
        return first
    }
}

/// Keeps one model per task and kind for the life of the workspace, so closing a sheet leaves a
/// live request running and reopening finds it. Only an explicit end releases a model.
@MainActor
public final class ReviewSuggestionCenter {
    private var models: [String: ReviewSuggestionModel] = [:]
    public init() {}

    public func model(for taskID: TaskID, kind: SuggestionKind,
                      make: () -> ReviewSuggestionModel) -> ReviewSuggestionModel {
        let key = taskID.rawValue + ":" + kind.rawValue
        if let existing = models[key] { return existing }
        let created = make()
        models[key] = created
        return created
    }

    /// Releases a finished model (applied, continued manually or discarded).
    public func release(_ taskID: TaskID, kind: SuggestionKind) {
        models[taskID.rawValue + ":" + kind.rawValue] = nil
    }

    public func releaseAll() { models = [:] }
}
