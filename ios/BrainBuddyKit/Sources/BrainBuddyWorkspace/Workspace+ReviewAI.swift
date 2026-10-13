import BrainBuddyAPI
import BrainBuddyCore
import Foundation

// The workspace side of the first Weekly Review suggestion path (spec 026 T049). The state machine
// is `ReviewSuggestionModel`; this file only lends it the workspace's projection, its consent
// ledger and its ordinary command path, and keeps one model per task for the workspace's life.

extension Workspace: ReviewSuggestionPort {
    /// The model for `taskID`/`kind`, created once. Closing a sheet leaves it, and a live request in
    /// it, in place; `releaseReviewSuggestionModel` ends it after apply, manual continuation or discard.
    public func reviewSuggestionModel(
        for taskID: TaskID, kind: SuggestionKind, stallReason: StallReason? = nil, adapter: LocalAIAdapter,
        remote: (any NavigatorRemote)?, privacy: AIPrivacyMode, shown: ShownTask? = nil
    ) -> ReviewSuggestionModel {
        let model = reviewSuggestions.model(for: taskID, kind: kind) {
            ReviewSuggestionModel(
                taskID: taskID, kind: kind, stallReason: stallReason, port: self, remote: remote, adapter: adapter,
                journal: suggestionJournal(), privacy: privacy)
        }
        if let shown { model.adoptShownTask(shown) }
        return model
    }

    public func releaseReviewSuggestionModel(for taskID: TaskID, kind: SuggestionKind) {
        reviewSuggestions.release(taskID, kind: kind)
    }

    private func suggestionJournal() -> any ReviewSuggestionJournal {
        guard let runtime = rustRuntime else { return InMemoryReviewSuggestionJournal() }
        return RuntimeDraftSuggestionJournal(runtime: runtime)
    }

    // MARK: Port

    public var suggestionOwner: String { account?.id ?? "local" }

    /// The approved FR-019 payload: title, notes, optional stall reason, project name, up to 20 other
    /// open task titles of that project, and the kind. Nothing else is read.
    public func suggestionInput(for taskID: TaskID, kind: SuggestionKind, stallReason: StallReason?) -> SuggestionInput? {
        guard let task = state.tasks[taskID] else { return nil }
        let project = task.projectID.flatMap { state.projects[$0] }
        let others = task.projectID.map { id in
            state.tasks.values.filter { $0.projectID == id && $0.id != taskID && $0.isOpen }
                .sorted { ($0.orderKey, $0.createdAt) < ($1.orderKey, $1.createdAt) }.map(\.title)
        } ?? []
        return SuggestionInput(
            kind: kind, taskTitle: task.title, taskNotes: task.details.flatMap { $0.isEmpty ? nil : $0 },
            stallReason: stallReason?.rawValue, projectName: project?.name, openTaskTitles: others)
    }

    public func suggestionShownTask(_ taskID: TaskID) -> ShownTask? {
        if isRustSelected, let shown = taskDetailShownTask(taskID) { return shown }
        return state.tasks[taskID].map(shownTask(of:))
    }

    public func suggestionNotes(_ taskID: TaskID) -> String? { state.tasks[taskID].map { $0.details ?? "" } }

    public func suggestionConsents() -> [OwnerConsentFact] {
        let owner = suggestionOwner
        return state.review.navigatorConsents.values.compactMap { consent in
            guard let granted = consent.grantedAt, let version = consent.consentTextVersion else { return nil }
            return OwnerConsentFact(owner: owner, provider: consent.provider, grantedAt: granted,
                                    revokedAt: consent.revokedAt, consentTextVersion: version)
        }
    }

    public func grantSuggestionConsent(provider: String, textVersion: Int) async throws {
        try await grantNavigatorConsent(provider: provider, consentTextVersion: textVersion,
                                        editorID: "suggestion-consent-" + UUID().uuidString.lowercased())
    }

    public func revokeSuggestionConsent(provider: String) async throws {
        try await revokeNavigatorConsent(provider: provider,
                                         editorID: "suggestion-revoke-" + UUID().uuidString.lowercased())
    }

    /// An ordinary task-notes command. The editor identity makes a retry after a lost acknowledgement
    /// return the original save instead of writing again.
    public func saveSuggestionNotes(_ taskID: TaskID, notes: String, editorID: String) async throws {
        do { try await updateTask(taskID, TaskChanges(details: .set(notes)), editorID: editorID) }
        catch { throw Self.suggestionPortError(error) }
    }

    /// The ordinary decision command, checked against the version the sheet showed.
    public func applySuggestion(kind: SuggestionKind, taskID: TaskID, title: String, aiUse: AIUse,
                                navigatorRequestID: String?, expected: ShownTask, editorID: String) async throws {
        do {
            _ = try await decide(kind == .firstStep ? .firstStep : .reformulate, on: taskID, title: title,
                                 aiUse: aiUse, navigatorRequestID: navigatorRequestID, expectedTask: expected,
                                 editorID: editorID)
        } catch { throw Self.suggestionPortError(error) }
    }

    /// Known refusals are values; a bridge failure whose outcome is not known stays retryable with the
    /// same identity.
    nonisolated static func suggestionPortError(_ error: any Error) -> SuggestionPortError {
        switch error {
        case let known as SuggestionPortError: return known
        case GTDValidationError.formulationChanged: return .conflict
        case is GTDValidationError: return .rejected(code: "VALIDATION")
        case RustDomainError.refused(let reason, _):
            return ["revision_conflict", "formulation_changed"].contains(reason) ? .conflict : .rejected(code: reason)
        case let bridge as RustBridgeError:
            switch bridge.code {
            case "REVISION_CONFLICT", "SHOWN_FRAME_RELOAD_REQUIRED": return .conflict
            case "INVALID_REQUEST", "INVALID_DRAFT_ID", "DRAFT_INTENT_MISMATCH": return .rejected(code: bridge.code)
            default: return .unknown(code: bridge.code)
            }
        default: return .unknown(code: "SAVE_FAILED")
        }
    }
}

/// The suggestion record in the runtime's own draft store: durable, local, never synced, and not
/// the Task. It holds the cancellation, the typed answer and the stable notes-command identity.
struct RuntimeDraftSuggestionJournal: ReviewSuggestionJournal {
    let runtime: RustWorkspaceRuntime

    private func draftID(_ key: String) -> String { "runtime:ai-suggestion:" + key }

    func load(_ key: String) async throws -> ReviewSuggestionRecord? {
        guard let draft = try await runtime.loadDraft(draftID(key)) else { return nil }
        return try JSONDecoder().decode(ReviewSuggestionRecord.self, from: draft.fields)
    }

    func save(_ record: ReviewSuggestionRecord, for key: String) async throws {
        try await runtime.saveDraft(RustWorkspaceDraft(
            draftID: draftID(key), editorKind: "runtime_ai_suggestion", fields: try JSONEncoder().encode(record),
            updatedAt: ISO8601DateFormatter().string(from: Date())))
    }

    func clear(_ key: String) async throws { try await runtime.deleteDraft(draftID(key)) }
}
