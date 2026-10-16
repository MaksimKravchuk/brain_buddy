import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The account's agent client: the same server and Keychain session the sync uses.
enum AgentsClient {
    @MainActor static func make(for account: LinkedAccount) -> BrainBuddyAPIClient {
        BrainBuddyAPIClient(baseURL: account.serverURL, tokenStore: KeychainSessionTokenStore())
    }
}

/// Run reads for whichever account the workspace has when the call is made (signed out: 401).
private struct WorkspaceAgentRuns: AgentRunsRemote {
    let workspace: Workspace

    private func signedIn() async throws(APIError) -> BrainBuddyAPIClient {
        guard let client = await MainActor.run(body: { workspace.account.map(AgentsClient.make(for:)) }) else {
            throw APIError(kind: .unauthorized, message: "Signed out.", requestMayHaveBeenSent: false)
        }
        return client
    }

    func agentRunSummaries(taskIDs: [String]) async throws(APIError) -> [String: AgentRunSummaryDTO] {
        try await signedIn().agentRunSummaries(taskIDs: taskIDs)
    }

    func agentRun(id: String) async throws(APIError) -> AgentRunDTO { try await signedIn().agentRun(id: id) }
}

extension AgentsSession {
    /// The iPhone's session over `workspace` (034-FR-002, 034-FR-003).
    @MainActor static func live(_ workspace: Workspace) -> AgentsSession {
        AgentsSession(
            account: { workspace.account }, steps: { await AgentStepRef.open(in: workspace) },
            availabilityRemote: { AgentsClient.make(for: $0) }, runsRemote: WorkspaceAgentRuns(workspace: workspace))
    }
}

/// Holds one `AgentsSession` per workspace and keeps it current: refreshed at launch, on sign-in and
/// sign-out and when the app comes to the foreground; polling only while active and online.
struct AgentsHost: ViewModifier {
    let workspace: Workspace
    @State private var session: AgentsSession?
    @Environment(\.scenePhase) private var scenePhase

    func body(content: Content) -> some View {
        content
            .environment(session)
            .task(id: ObjectIdentifier(workspace)) {
                let next = AgentsSession.live(workspace)
                session = next
                next.setForeground(scenePhase == .active)
                await next.refresh()
                await next.runs.run()
            }
            .onChange(of: workspace.account?.id) { _, _ in
                Task { await session?.refresh() }
            }
            .onChange(of: scenePhase) { _, phase in
                session?.setForeground(phase == .active)
                if phase == .active { Task { await session?.refresh() } }
            }
            .task(id: ObjectIdentifier(workspace)) {
                for await isAvailable in SystemEvents.networkAvailability() {
                    session?.setOnline(isAvailable)
                }
            }
    }
}
