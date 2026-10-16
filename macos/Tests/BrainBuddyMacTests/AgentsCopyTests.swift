import Testing

@testable import BrainBuddyMacCore

@Suite("030 Agents copy")
struct AgentsCopyTests {
    @Test("030_FR_030 status words and sentences match the web's")
    func statusWordsMatchTheWeb() {
        typealias C = AgentsCopy.Connection
        let cases: [(C, String)] = [
            (C(status: "ready"), "Tested ready"), (C(status: "ready", stale: true), "Stale"),
            (C(status: "untested"), "Not tested"), (C(status: "untested", agentChanged: true), "Agent changed"),
            (C(status: "invalid_credentials"), "Invalid credentials"), (C(status: "unreachable"), "Unreachable"),
            (C(status: "unsupported"), "Unsupported"), (C(status: "disconnected"), "Disconnected"),
            (C(status: "disconnected", disconnectReason: "superseded_wire_contract"), "Superseded wire contract"),
            (C(status: "unreachable", errorCode: "a2a_rate_limited"), "Rate limited"),
        ]
        for (connection, label) in cases { #expect(AgentsCopy.statusLabel(connection) == label) }
        #expect(AgentsCopy.statusDetail(C(status: "ready")) == "The last test reached this agent and it authenticated.")
        #expect(
            AgentsCopy.statusDetail(C(status: "ready", stale: true, staleAfterSeconds: 3600))
                == "The last contact is older than the 1 hour staleness threshold. Test it again before a hand-off.")
        #expect(
            AgentsCopy.statusDetail(C(status: "unsupported", errorCode: "a2a_protocol_version_unsupported", foundVersion: "0.3"))
                == "The card declares A2A 0.3. BrainBuddy speaks protocol version 1.0.x only.")
        #expect(
            AgentsCopy.statusDetail(C(status: "unsupported"))
                == "No JSON-RPC interface BrainBuddy can use over HTTPS.")
    }

    @Test("030_FR_041 the copy keeps the design's counts and words")
    func copyCounts() {
        #expect(AgentsCopy.runCount(1) == "1 run" && AgentsCopy.runCount(3) == "3 runs")
        #expect(AgentsCopy.waitingHeader(people: 1, agents: 4) == "1 person, 4 agents")
        #expect(AgentsCopy.waitingHeader(people: 2, agents: 1) == "2 people, 1 agent")
        #expect(AgentsCopy.send(to: "Hermes") == "Send to Hermes")
        #expect(AgentsCopy.updates(streaming: true, push: false) == "Streaming · no push")
        #expect(AgentsCopy.credential(bearer: false, header: "X-Key") == "API key in X-Key · stored sealed")
    }
}
