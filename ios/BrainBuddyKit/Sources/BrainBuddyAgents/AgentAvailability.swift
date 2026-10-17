import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Observation

/// The two reads availability makes (030-FR-002). `BrainBuddyAPIClient` is the production remote.
public protocol AgentAvailabilityRemote: Sendable {
    func me() async throws(APIError) -> MeDTO
    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO
}

extension BrainBuddyAPIClient: AgentAvailabilityRemote {}

public enum AgentPasswordState: Equatable, Sendable { case has, none, unknown }

/// Whether the agent surfaces show, and which controls (030-FR-001, 030-FR-002, 030-FR-036). Memory
/// only. A read applies only while it still belongs to the account that started it.
@MainActor
@Observable
public final class AgentAvailability {
    public static let activationThrottle: TimeInterval = 300
    public static let relayFlag = "external_agent_relay"

    public private(set) var ownerID: String?
    public private(set) var relayEnabled = false
    public private(set) var passwordState = AgentPasswordState.unknown
    public private(set) var isOnline = true
    /// The one-shot "show Add new agent" request: set by the sidebar, consumed by the Settings tab.
    public private(set) var addAgentRequested = false
    /// The one-shot "show the Agents tab" request (no Add sheet): set by the hand-off sheet.
    public private(set) var agentsTabRequested = false
    @ObservationIgnored private var account: LinkedAccount?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var lastRefresh: Date?
    @ObservationIgnored private let makeRemote: @MainActor (LinkedAccount) -> any AgentAvailabilityRemote
    @ObservationIgnored private let now: @MainActor () -> Date
    @ObservationIgnored private let log: any AgentLogSink

    public init(
        account: LinkedAccount?, remote: @escaping @MainActor (LinkedAccount) -> any AgentAvailabilityRemote,
        now: @escaping @MainActor () -> Date = { Date() }, log: any AgentLogSink = SystemAgentLog()
    ) {
        self.account = account
        ownerID = account?.id
        makeRemote = remote
        self.now = now
        self.log = log
    }

    /// The workspace's account changed (sign-in, sign-out, another account): everything is dropped.
    public func update(account new: LinkedAccount?) {
        let changed = new?.id != account?.id
        account = new
        guard changed else { return }
        generation += 1
        ownerID = new?.id
        relayEnabled = false
        passwordState = .unknown
        lastRefresh = nil
        addAgentRequested = false
        agentsTabRequested = false
    }

    /// At sign-in, and whenever a caller needs the answer now.
    public func refresh() async {
        guard let account else { return }
        generation += 1
        let ticket = generation
        let remote = makeRemote(account)
        async let flags = Self.readMe(remote)
        async let methods = Self.readMethods(remote)
        let (meResult, methodsResult) = await (flags, methods)
        guard ticket == generation, self.account?.id == account.id else { return record("discarded") }
        lastRefresh = now()
        var outcome = "loaded"
        switch meResult {
        case .success(let me) where me.id == account.id:
            relayEnabled = me.featureFlags[Self.relayFlag] ?? false
            isOnline = true
        case .success: outcome = "mismatch"
        case .failure(let error):
            isOnline = !error.isNetwork
            outcome = error.isNetwork ? "offline" : "failed"
        }
        // The flag keeps its last value while the read fails; the password state does not (FR-036).
        if case .success(let list) = methodsResult, list.accountID == account.id {
            passwordState = list.hasPassword ? .has : .none
        } else {
            passwordState = .unknown
        }
        record(outcome)
    }

    /// The main window became active: at most one read every five minutes (030-FR-002).
    public func activate() async {
        if let lastRefresh, now().timeIntervalSince(lastRefresh) < Self.activationThrottle { return }
        await refresh()
    }

    /// A person's action (Try again, Retry, opening the hand-off sheet) needs the answer now: a cached offline
    /// state never blocks it. Online callers pay nothing; offline ones bypass the throttle and read again.
    public func confirmOnline() async -> Bool {
        if !isOnline { await refresh() }
        return isOnline
    }

    /// A flagged route answered "External agent relay is not available.": hide, then read again.
    public func relayUnavailable() async {
        relayEnabled = false
        await refresh()
    }

    public func requestAddAgent() { addAgentRequested = true }

    /// "Open Settings" on the hand-off sheet: bring Settings › Agents forward, without opening Add.
    public func requestAgentsTab() { agentsTabRequested = true }

    /// True once per request.
    public func consumeAgentsTabRequest() -> Bool {
        defer { agentsTabRequested = false }
        return agentsTabRequested
    }

    /// True once per request.
    public func consumeAddAgentRequest() -> Bool {
        defer { addAgentRequested = false }
        return addAgentRequested
    }

    private nonisolated static func readMe(_ remote: any AgentAvailabilityRemote) async -> Result<MeDTO, APIError> {
        do throws(APIError) { return .success(try await remote.me()) } catch { return .failure(error) }
    }

    private nonisolated static func readMethods(
        _ remote: any AgentAvailabilityRemote
    ) async -> Result<AccountAuthMethodsDTO, APIError> {
        do throws(APIError) { return .success(try await remote.accountAuthMethods()) } catch { return .failure(error) }
    }

    /// Stage and outcome only (030-FR-039): never an account, name or flag value.
    private func record(_ outcome: String) { log.log("agent-availability stage=refresh outcome=\(outcome)") }
}

extension APIError {
    /// The request never got an answer: no connection (also read by the hand-off sheet's agent tests).
    var isNetwork: Bool {
        if case .network = kind { return true }
        return false
    }
}
