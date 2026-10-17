#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAPI
    import Foundation
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// 030-FR-004: the sidebar agent rows as the DSAgents board draws them.
    @Suite("030 Agents sidebar rows")
    struct AgentsSidebarRowsTests {
        private func run(_ id: String, label: String, agent: String = "Hermes", connection: String = "conn_1") -> AgentRunItem {
            AgentRunItem(
                stepTitle: "Step", taskServerID: "task_\(id)", runID: id, connectionID: connection, agentName: agent,
                state: AgentPrimaryState(wireValue: label))
        }

        private func connection(_ id: String, _ name: String, _ status: String) -> AgentListRow {
            AgentListRow(id: id, name: name, status: status)
        }

        @Test("030-FR-004 an agent with a Needs-you run shows the accent dot and its count")
        func the030_FR_004_needsYouRunShowsDotAndCount() {
            let rows = AgentSidebarRow.rows(
                runs: [run("a", label: "Running"), run("b", label: "Needs you")], counts: ["conn_1": 2], connections: [])
            #expect(rows == [AgentSidebarRow(id: "conn_1", name: "Hermes", trailing: "2", needsYou: true)])
        }

        @Test("030-FR-004 an agent whose runs do not need you has a count and no dot")
        func the030_FR_004_otherRunsShowNoDot() {
            let rows = AgentSidebarRow.rows(
                runs: [run("a", label: "Running")], counts: ["conn_1": 1],
                connections: [connection("conn_1", "Hermes", "Stale")])
            #expect(rows == [AgentSidebarRow(id: "conn_1", name: "Hermes", trailing: "1", needsYou: false)])
        }

        @Test("030-FR-004 an agent with no listed runs shows its status word unless it is Tested ready")
        func the030_FR_004_noRunsShowsStatusWord() {
            let rows = AgentSidebarRow.rows(
                runs: [], counts: [:],
                connections: [connection("c2", "Home server", "Stale"), connection("c1", "Alpha", "Tested ready")])
            #expect(
                rows == [
                    AgentSidebarRow(id: "c1", name: "Alpha", trailing: nil),
                    AgentSidebarRow(id: "c2", name: "Home server", trailing: "Stale"),
                ])
        }

        @Test("030_FR_040 arrowing onto an agent row opens it, and the row already showing is left alone")
        func the030_FR_040_selectionOpensAgentDestination() {
            let agent = WorkspaceDestination.agentRuns(.agent("conn_1"))
            #expect(WorkspaceDestination.opened(bySelecting: .agentRuns(.all), current: .list(.waiting)) == .agentRuns(.all))
            #expect(WorkspaceDestination.opened(bySelecting: agent, current: .agentRuns(.all)) == agent)
            #expect(WorkspaceDestination.opened(bySelecting: agent, current: agent) == nil)
            #expect(WorkspaceDestination.opened(bySelecting: nil, current: agent) == nil)
        }
    }
#endif
