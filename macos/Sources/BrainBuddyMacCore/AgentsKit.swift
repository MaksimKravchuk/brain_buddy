// The agent models moved to the kit's BrainBuddyAgents (spec 034 PR-01) so the iPhone shares them;
// re-exported here so the Mac's code and tests keep reading them as before.
@_exported import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyCore

/// The Mac keeps its agent lines under `com.brainbuddy.mac`, category `sync` (030-FR-039).
extension SystemMacLog: AgentLogSink {
    package func log(_ message: String) { log(.sync, message) }
}

extension CapturingMacLog: AgentLogSink {
    package func log(_ message: String) { log(.sync, message) }
}

extension AgentSettingsModel {
    /// Settings › Agents over the account's server with the Mac's token store and log.
    package convenience init(account: LinkedAccount?, availability: AgentAvailability) {
        self.init(account: account, availability: availability, remote: Self.liveRemote, log: SystemMacLog())
    }

    package static func liveRemote(for account: LinkedAccount) -> any AgentSettingsRemote {
        BrainBuddyAPIClient(
            baseURL: account.serverURL, tokenStore: WorkspaceHost.systemTokenStore(), identity: WorkspaceHost.clientIdentity)
    }
}
