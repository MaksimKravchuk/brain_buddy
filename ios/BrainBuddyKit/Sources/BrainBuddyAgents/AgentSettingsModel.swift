import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Observation

/// The seven connection calls Settings › Agents makes (030-FR-029 – 030-FR-034).
/// `BrainBuddyAPIClient` is the production remote; tests supply a fake.
public protocol AgentSettingsRemote: Sendable {
    func agentConnections() async throws(APIError) -> [AgentConnectionDTO]
    func agentConnection(id: String) async throws(APIError) -> AgentConnectionDTO
    func createAgentConnection(
        name: String, address: String, scheme: AgentAuthScheme, credential: String, currentPassword: String,
        idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO
    func updateAgentConnection(
        id: String, name: String?, address: String?, scheme: AgentAuthScheme?, currentPassword: String?,
        expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO
    func testAgentConnection(id: String, idempotencyKey: UUID) async throws(APIError) -> AgentConnectionDTO
    func replaceAgentCredential(
        id: String, credential: String, currentPassword: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO
    func disconnectAgentConnection(
        id: String, currentPassword: String, expectedRevision: Int, idempotencyKey: UUID
    ) async throws(APIError) -> AgentConnectionDTO
}

extension BrainBuddyAPIClient: AgentSettingsRemote {}

/// A failure in words (030-FR-034, 030-FR-038): a short message, whether Try again can help, and the
/// server's reference. Never carries a secret.
public struct AgentNotice: Equatable, Sendable {
    public var message: String
    public var reference: String?
    public var failure: AgentFailure
    public var canRetry: Bool

    public init(message: String, reference: String? = nil, failure: AgentFailure = .other, canRetry: Bool = false) {
        self.message = message
        self.reference = reference
        self.failure = failure
        self.canRetry = canRetry
    }
}

public struct AgentListRow: Equatable, Identifiable, Sendable {
    public var id: String
    public var name: String
    /// The web's status word.
    public var status: String

    public init(id: String, name: String, status: String) { (self.id, self.name, self.status) = (id, name, status) }
}

/// G-06.01. Nil rows are not shown. Every string is untrusted agent text except the copy.
public struct AgentDetailRows: Equatable, Sendable {
    public var statusLine: String
    public var address: String
    public var credential: String
    public var lastContact: Date?
    public var card: String?
    public var skills: String?
    public var updates: String
    public var guarantee: String?

    public init(
        statusLine: String, address: String, credential: String, lastContact: Date?, card: String?, skills: String?,
        updates: String, guarantee: String?
    ) {
        (self.statusLine, self.address, self.credential, self.lastContact) = (statusLine, address, credential, lastContact)
        (self.card, self.skills, self.updates, self.guarantee) = (card, skills, updates, guarantee)
    }
}

public enum AgentSettingsPhase: Equatable, Sendable {
    case notSignedIn, loading, loaded, offline, sessionEnded
    case failed(AgentNotice)
}

/// Settings › Agents state (030-FR-029, 030-FR-030, 030-FR-036, 030-FR-038). Memory only; a result
/// is applied only while it still belongs to the account and the request that started it.
@MainActor
@Observable
public final class AgentSettingsModel {
    public private(set) var phase: AgentSettingsPhase
    public private(set) var account: LinkedAccount?
    public private(set) var connections: [AgentConnectionDTO] = []
    public private(set) var selectedID: String?
    public private(set) var isTesting = false
    public private(set) var notice: AgentNotice?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private let availability: AgentAvailability
    @ObservationIgnored private let makeRemote: @MainActor (LinkedAccount) -> any AgentSettingsRemote
    @ObservationIgnored private let log: any AgentLogSink

    public init(
        account: LinkedAccount?, availability: AgentAvailability,
        remote: @escaping @MainActor (LinkedAccount) -> any AgentSettingsRemote,
        log: any AgentLogSink = SystemAgentLog()
    ) {
        self.account = account
        self.availability = availability
        makeRemote = remote
        self.log = log
        phase = account == nil ? .notSignedIn : .loading
    }

    /// A different account drops everything and ignores any request still in flight.
    public func update(account new: LinkedAccount?) {
        guard new?.id != account?.id else { return account = new }
        account = new
        generation += 1
        connections = []
        selectedID = nil
        isTesting = false
        notice = nil
        phase = new == nil ? .notSignedIn : .loading
    }

    // MARK: derived state

    public var rows: [AgentListRow] {
        connections.map { AgentListRow(id: $0.id, name: $0.name, status: Self.status(of: $0)) }
    }

    public var selected: AgentConnectionDTO? { connections.first { $0.id == selectedID } }
    public var details: AgentDetailRows? { selected.map(Self.details) }
    /// 030-FR-036: no password on the account. An unreadable state keeps the controls; the server decides.
    public var isPasswordless: Bool { availability.passwordState == .none }
    public var controlsEnabled: Bool { phase == .loaded }
    public var canAdd: Bool { controlsEnabled && !isPasswordless }
    public var canTest: Bool { controlsEnabled && selected != nil && !isTesting }

    public func select(_ id: String?) {
        selectedID = connections.contains { $0.id == id } ? id : nil
    }

    /// Up/Down in the list (030-FR-040): the neighbouring agent, stopping at the ends. With nothing selected
    /// the first agent is chosen. Returns the new selection so the view can move focus with it.
    @discardableResult
    public func moveSelection(by offset: Int) -> String? {
        guard !connections.isEmpty else { return nil }
        let current = connections.firstIndex { $0.id == selectedID }
        let next = current.map { min(max($0 + offset, 0), connections.count - 1) } ?? 0
        selectedID = connections[next].id
        return selectedID
    }

    // MARK: reads

    /// The latest call wins; a late answer is dropped.
    public func reload() async {
        guard let account else { return }
        generation += 1
        let ticket = generation
        let started = ContinuousClock.now
        if phase != .loaded { phase = .loading }
        let result = await call { () async throws(APIError) -> [AgentConnectionDTO] in
            try await makeRemote(account).agentConnections()
        }
        guard ticket == generation, self.account?.id == account.id else { return record("reload", "discarded", started) }
        switch result {
        case .success(let list):
            connections = list.filter { $0.status != .disconnected }
            if selected == nil { selectedID = connections.first?.id }
            notice = nil
            phase = .loaded
            record("reload", "loaded", started)
        case .failure(let error):
            let reported = await report(error, passwordBearing: false)
            if error.kind == .unauthorized { return record("reload", "sessionEnded", started) }
            phase = error.agentFailure == .offline ? .offline : .failed(reported)
            record("reload", error.agentFailure == .offline ? "offline" : "failed", started, reference: error.referenceID)
        }
    }

    /// Test again (030-FR-030): the server test with no password, then the new status.
    public func testAgain() async {
        guard canTest, let account, let target = selected else { return }
        let key = UUID(), started = ContinuousClock.now, ticket = generation
        isTesting = true
        notice = nil
        let result = await call { () async throws(APIError) -> AgentConnectionDTO in
            try await makeRemote(account).testAgentConnection(id: target.id, idempotencyKey: key)
        }
        guard ticket == generation, self.account?.id == account.id else { return record("test", "discarded", started) }
        isTesting = false
        switch result {
        case .success(let fresh):
            apply(fresh, select: false)
            record("test", "tested", started)
        case .failure(let error):
            notice = await report(error, passwordBearing: false)
            record("test", "failed", started, reference: error.referenceID)
        }
    }

    // MARK: used by the editor

    public func remote() -> (any AgentSettingsRemote)? { account.map(makeRemote) }

    public func apply(_ connection: AgentConnectionDTO, select makeSelected: Bool = true) {
        if connection.status == .disconnected { return remove(connection.id) }
        if let index = connections.firstIndex(where: { $0.id == connection.id }) {
            connections[index] = connection
        } else {
            connections.append(connection)
        }
        if makeSelected { selectedID = connection.id }
    }

    public func remove(_ id: String) {
        connections.removeAll { $0.id == id }
        if selectedID == id { selectedID = connections.first?.id }
    }

    /// The words for a failed call, plus its consequences: a 401 ends the session, and the relay's
    /// flag-off 404 hides the surface and refreshes availability.
    public func report(_ error: APIError, passwordBearing: Bool) async -> AgentNotice {
        if error.kind == .unauthorized { phase = .sessionEnded }
        let failure = error.agentFailure
        if failure == .relayUnavailable { await availability.relayUnavailable() }
        return Self.notice(error, passwordBearing: passwordBearing)
    }

    public nonisolated static func notice(_ error: APIError, passwordBearing: Bool) -> AgentNotice {
        let failure = error.agentFailure
        let reference = error.referenceID
        switch failure {
        case .wrongPassword where passwordBearing:
            return AgentNotice(message: AgentsCopy.wrongPassword, reference: reference, failure: failure)
        case .staleRevision:
            return AgentNotice(message: AgentsCopy.staleRevision, reference: reference, failure: failure)
        case .rateLimited:
            return AgentNotice(message: AgentsCopy.rateLimited, reference: reference, failure: failure)
        case .offline:
            return AgentNotice(message: AgentsCopy.needsConnection, reference: reference, failure: failure, canRetry: true)
        default:
            // The server's own words for a rejected name or address (G-07.05); nothing else is quoted.
            let rejected: Bool
            switch error.kind {
            case .rejected, .duplicateName: rejected = true
            default: rejected = false
            }
            let message = rejected && failure == .other ? error.message : AgentsCopy.agentsFailed
            return AgentNotice(message: message, reference: reference, failure: .other, canRetry: error.isRetryable)
        }
    }

    // MARK: rows

    public nonisolated static func connection(_ dto: AgentConnectionDTO) -> AgentsCopy.Connection {
        AgentsCopy.Connection(
            status: Self.wire(dto.status), stale: dto.stale, agentChanged: dto.agentChanged,
            errorCode: dto.lastTestErrorCode, foundVersion: dto.card?.protocolVersion,
            scheme: nil, staleAfterSeconds: dto.staleAfterSeconds)
    }

    public nonisolated static func status(of dto: AgentConnectionDTO) -> String {
        AgentsCopy.statusLabel(connection(dto))
    }

    public nonisolated static func details(_ dto: AgentConnectionDTO) -> AgentDetailRows {
        let model = connection(dto)
        let sentence = dto.readyForHandoff && dto.status == .ready && !dto.stale && !dto.agentChanged
            ? AgentsCopy.readyForHandoff : AgentsCopy.statusDetail(model)
        let skills = (dto.card?.skills ?? []).compactMap(\.name).filter { !$0.isEmpty }.joined(separator: ", ")
        let tier: String? =
            switch dto.guaranteeTier {
            case .guaranteed: AgentsCopy.guaranteed
            case .bestEffort: AgentsCopy.bestEffort
            default: nil
            }
        let card = dto.card.flatMap { c in
            c.version.flatMap { v in c.protocolVersion.map { AgentsCopy.cardVersion(v, protocol: $0) } }
        }
        return AgentDetailRows(
            statusLine: "\(AgentsCopy.statusLabel(model)) · \(sentence)", address: dto.agentAddress,
            credential: AgentsCopy.credential(bearer: dto.authScheme == .bearer, header: dto.authHeaderName),
            lastContact: dto.lastContactAt, card: card, skills: skills.isEmpty ? nil : skills,
            updates: AgentsCopy.updates(streaming: dto.capabilities.streaming, push: dto.capabilities.pushNotifications),
            guarantee: tier)
    }

    private nonisolated static func wire(_ status: AgentConnectionStatus) -> String {
        switch status {
        case .untested: "untested"
        case .ready: "ready"
        case .invalidCredentials: "invalid_credentials"
        case .unreachable: "unreachable"
        case .unsupported: "unsupported"
        case .disconnected: "disconnected"
        case .unknown(let raw): raw
        }
    }

    public func call<T: Sendable>(_ op: () async throws(APIError) -> T) async -> Result<T, APIError> {
        do throws(APIError) { return .success(try await op()) } catch { return .failure(error) }
    }

    /// Stage, outcome, duration and reference only (030-FR-039): never a name, address or secret.
    private func record(_ stage: String, _ outcome: String, _ started: ContinuousClock.Instant, reference: String? = nil) {
        let parts = started.duration(to: .now).components
        let millis = parts.seconds * 1000 + parts.attoseconds / 1_000_000_000_000_000
        log.log("agent-settings stage=\(stage) outcome=\(outcome) ms=\(millis)" + (reference.map { " ref=\($0)" } ?? ""))
    }
}
