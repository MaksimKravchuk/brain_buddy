#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAgents
    import BrainBuddyAPI
    import Foundation
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// The colour role of a run: the All runs card and the Waiting for row share one mapping.
    @Suite("030 Agent run tone")
    struct AgentRunToneTests {
        private func item(_ label: String) -> AgentRunItem {
            AgentRunItem(
                stepTitle: "Compare van hire prices", taskServerID: "task_1", runID: "run_1", connectionID: "conn_1",
                agentName: "Hermes", state: AgentPrimaryState(wireValue: label), questionText: nil,
                sentAt: nil, lastContactAt: nil)
        }

        @Test("030_FR_041 a run that stopped reporting takes the warning role, not secondary text")
        func stoppedReportingIsWarning() {
            #expect(AgentRunRow.tone(for: item("Stopped reporting")) == .warning)
        }

        @Test("030_FR_041 only your moves get colour: Needs you accent, Failed danger, the rest secondary")
        func otherRoles() {
            #expect(AgentRunRow.tone(for: item("Needs you")) == .accent)
            #expect(AgentRunRow.tone(for: item("Failed")) == .danger)
            #expect(AgentRunRow.tone(for: item("Running")) == .secondary)
            #expect(AgentRunRow.tone(for: item("Queued")) == .secondary)
        }
    }
#endif
