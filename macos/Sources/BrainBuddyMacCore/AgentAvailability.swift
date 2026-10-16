import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Observation

/// The two reads availability makes (030-FR-002). `BrainBuddyAPIClient` is the production remote.
package protocol AgentAvailabilityRemote: Sendable {
    func me() async throws(APIError) -> MeDTO
    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO
}

extension BrainBuddyAPIClient: AgentAvailabilityRemote {}

package enum AgentPasswordState: Equatable, Sendable { case has, none, unknown }

/// Whether the agent surfaces show, and which controls (030-FR-001, 030-FR-002, 030-FR-036). Memory
/// only. A read applies only while it still belongs to the account that started it.
@MainActor
@Observable
package final class AgentAvailability {
    package static let activationThrottle: TimeInterval = 300
    package static let relayFlag = "external_agent_relay"

    package private(set) var ownerID: String?
    package private(set) var relayEnabled = false
    package private(set) var passwordState = AgentPasswordState.unknown
    package private(set) var isOnline = true
    /// The one-shot "show Add new agent" request: set by the sidebar, consumed by the Settings tab.
    package private(set) var addAgentRequested = false
    @ObservationIgnored private var account: LinkedAccount?
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private var lastRefresh: Date?
    @ObservationIgnored private let makeRemote: @MainActor (LinkedAccount) -> any AgentAvailabilityRemote
    @ObservationIgnored private let now: @MainActor () -> Date
    @ObservationIgnored private let log: any MacLogSink

    package init(
        account: LinkedAccount?, remote: @escaping @MainActor (LinkedAccount) -> any AgentAvailabilityRemote,
        now: @escaping @MainActor () -> Date = { Date() }, log: any MacLogSink = SystemMacLog()
    ) {
        self.account = account
        ownerID = account?.id
        makeRemote = remote
        self.now = now
        self.log = log
    }

    /// The workspace's account changed (sign-in, sign-out, another account): everything is dropped.
    package func update(account new: LinkedAccount?) {
        let changed = new?.id != account?.id
        account = new
        guard changed else { return }
        generation += 1
        ownerID = new?.id
        relayEnabled = false
        passwordState = .unknown
        lastRefresh = nil
        addAgentRequested = false
    }

    /// At sign-in, and whenever a caller needs the answer now.
    package func refresh() async {
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
    package func activate() async {
        if let lastRefresh, now().timeIntervalSince(lastRefresh) < Self.activationThrottle { return }
        await refresh()
    }

    /// A flagged route answered "External agent relay is not available.": hide, then read again.
    package func relayUnavailable() async {
        relayEnabled = false
        await refresh()
    }

    package func requestAddAgent() { addAgentRequested = true }

    /// True once per request.
    package func consumeAddAgentRequest() -> Bool {
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
    private func record(_ outcome: String) { log.log(.sync, "agent-availability stage=refresh outcome=\(outcome)") }
}

extension APIError {
    fileprivate var isNetwork: Bool {
        if case .network = kind { return true }
        return false
    }
}
