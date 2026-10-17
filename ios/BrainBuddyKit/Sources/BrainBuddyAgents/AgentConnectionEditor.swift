import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Observation

public enum AgentEditorMode: Equatable, Sendable {
    case add
    case replaceCredential(AgentConnectionDTO)
    case edit(AgentConnectionDTO)
    case delete(AgentConnectionDTO)
}

public enum AgentEditorPhase: Equatable, Sendable {
    case idle, adding, testing, working, done
    case failed(AgentNotice)
}

/// One sheet of Settings › Agents: Add, Replace credential, Edit, Delete (030-FR-031 – 030-FR-035).
/// One Idempotency-Key per action, reused while Try again repeats it. The password is sent only
/// where the server needs it. Secrets live here only for the request: they are emptied when it ends
/// and on `dismiss()`, and never printed or logged.
@MainActor
@Observable
public final class AgentConnectionEditor: CustomStringConvertible {
    public let mode: AgentEditorMode
    public var name: String
    public var address: String
    public var scheme: AgentAuthScheme
    public var secret = ""
    public var password = ""
    public private(set) var phase = AgentEditorPhase.idle
    /// The last-read copy whose `revision` is sent; replaced when a stale revision is re-read.
    public private(set) var current: AgentConnectionDTO?
    @ObservationIgnored private var key: UUID?
    @ObservationIgnored private let model: AgentSettingsModel
    @ObservationIgnored private let log: any AgentLogSink

    public nonisolated var description: String { "AgentConnectionEditor (redacted)" }

    public init(mode: AgentEditorMode, model: AgentSettingsModel, log: any AgentLogSink = SystemAgentLog()) {
        self.mode = mode
        self.model = model
        self.log = log
        let saved: AgentConnectionDTO?
        switch mode {
        case .add: saved = nil
        case .replaceCredential(let c), .edit(let c), .delete(let c): saved = c
        }
        name = saved?.name ?? ""
        address = saved?.agentAddress ?? ""
        scheme = saved?.authScheme ?? .bearer
        current = saved
    }

    // MARK: derived state

    public var isBusy: Bool {
        switch phase {
        case .adding, .testing, .working: true
        default: false
        }
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var trimmedAddress: String { address.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var nameChanged: Bool { trimmedName != current?.name }
    private var addressChanged: Bool { trimmedAddress != current?.agentAddress }
    private var schemeChanged: Bool { scheme != current?.authScheme }

    /// Edit shows Current password only when the address or type differs from the saved one (030-FR-032).
    public var destinationChanged: Bool {
        if case .edit = mode { return addressChanged || schemeChanged }
        return false
    }

    public var needsPassword: Bool {
        if case .edit = mode { return destinationChanged }
        return true
    }

    public var canSubmit: Bool {
        guard !isBusy, model.controlsEnabled, current != nil || mode == .add else { return false }
        if needsPassword && password.isEmpty { return false }
        // 030-FR-036: without a password on the account only a name-only Edit is possible.
        if model.isPasswordless && needsPassword { return false }
        switch mode {
        case .add: return !trimmedName.isEmpty && !trimmedAddress.isEmpty && !secret.isEmpty
        case .replaceCredential: return !secret.isEmpty
        case .edit: return !trimmedName.isEmpty && !trimmedAddress.isEmpty && (nameChanged || addressChanged || schemeChanged)
        case .delete: return true
        }
    }

    // MARK: actions

    public func submit() async {
        guard canSubmit, let remote = model.remote(), let owner = model.account?.id else { return }
        let actionKey = key ?? UUID(), started = ContinuousClock.now
        key = actionKey
        phase = mode == .add ? .adding : .working
        let sent = (name: trimmedName, address: trimmedAddress, scheme: scheme, secret: secret, password: password)
        let target = current
        let stage: String
        let result: Result<AgentConnectionDTO, APIError>
        switch mode {
        case .add:
            stage = "add"
            result = await model.call { () async throws(APIError) -> AgentConnectionDTO in
                try await remote.createAgentConnection(
                    name: sent.name, address: sent.address, scheme: sent.scheme, credential: sent.secret,
                    currentPassword: sent.password, idempotencyKey: actionKey)
            }
        case .replaceCredential:
            stage = "replace"
            result = await model.call { () async throws(APIError) -> AgentConnectionDTO in
                try await remote.replaceAgentCredential(
                    id: target?.id ?? "", credential: sent.secret, currentPassword: sent.password,
                    expectedRevision: target?.revision ?? 0, idempotencyKey: actionKey)
            }
        case .edit:
            stage = "edit"
            let (renamed, moved, retyped) = (nameChanged, addressChanged, schemeChanged)
            result = await model.call { () async throws(APIError) -> AgentConnectionDTO in
                try await remote.updateAgentConnection(
                    id: target?.id ?? "", name: renamed ? sent.name : nil, address: moved ? sent.address : nil,
                    scheme: retyped ? sent.scheme : nil, currentPassword: moved || retyped ? sent.password : nil,
                    expectedRevision: target?.revision ?? 0, idempotencyKey: actionKey)
            }
        case .delete:
            stage = "delete"
            result = await model.call { () async throws(APIError) -> AgentConnectionDTO in
                try await remote.disconnectAgentConnection(
                    id: target?.id ?? "", currentPassword: sent.password, expectedRevision: target?.revision ?? 0,
                    idempotencyKey: actionKey)
            }
        }
        clearSecrets()
        guard model.account?.id == owner else {
            phase = .idle
            return record(stage, "discarded", started)
        }
        switch result {
        case .success(let saved):
            key = nil
            var outcome = "done"
            if mode == .add { outcome = await testAdded(saved, remote: remote, owner: owner) }
            else if case .delete = mode { model.remove(saved.id) }
            else { model.apply(saved, select: false) }
            phase = .done
            record(stage, outcome, started)
        case .failure(let error):
            await fail(error, remote: remote, stage: stage, started: started)
        }
    }

    /// Closing the sheet: nothing typed survives, and the next action gets its own key.
    public func dismiss() {
        clearSecrets()
        key = nil
        phase = .idle
    }

    // MARK: private

    /// Add and test: the new agent is selected whether or not its test succeeds (G-07.03).
    private func testAdded(_ created: AgentConnectionDTO, remote: any AgentSettingsRemote, owner: String) async -> String {
        phase = .testing
        model.apply(created)
        let testKey = UUID()
        let tested = await model.call { () async throws(APIError) -> AgentConnectionDTO in
            try await remote.testAgentConnection(id: created.id, idempotencyKey: testKey)
        }
        guard model.account?.id == owner else { return "discarded" }
        if case .success(let fresh) = tested {
            model.apply(fresh)
            return "done"
        }
        return "addedTestFailed"
    }

    private func fail(
        _ error: APIError, remote: any AgentSettingsRemote, stage: String, started: ContinuousClock.Instant
    ) async {
        // A definite refusal is a different request next time; only an unknown outcome keeps its key.
        if !(error.isRetryable && error.requestMayHaveBeenSent) { key = nil }
        phase = .failed(await model.report(error, passwordBearing: true))
        if error.agentFailure == .staleRevision, let id = current?.id {
            let fresh = await model.call { () async throws(APIError) -> AgentConnectionDTO in
                try await remote.agentConnection(id: id)
            }
            if case .success(let latest) = fresh {
                current = latest
                model.apply(latest, select: false)
            }
        }
        record(stage, "failed", started, reference: error.referenceID)
    }

    private func clearSecrets() {
        secret = ""
        password = ""
    }

    /// Stage, outcome, duration and reference only (030-FR-039): never a name, address or secret.
    private func record(_ stage: String, _ outcome: String, _ started: ContinuousClock.Instant, reference: String? = nil) {
        let parts = started.duration(to: .now).components
        let millis = parts.seconds * 1000 + parts.attoseconds / 1_000_000_000_000_000
        log.log("agent-editor stage=\(stage) outcome=\(outcome) ms=\(millis)" + (reference.map { " ref=\($0)" } ?? ""))
    }
}
