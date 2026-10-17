import BrainBuddyAPI
import Foundation
import Testing

@testable import BrainBuddyAgents

/// The run sheet shows only the blocks and controls the run's label and `controls` allow; the iPhone
/// and the Mac read the same `AgentRunBlock`.
@Suite("034 iPhone run sheet content")
struct AgentRunBlockTests {
    private let now = Date(timeIntervalSince1970: 1_000_000)

    @Test("034_FR_006 Needs you shows the agent's question with Reply and Stop run")
    func needsYou() {
        let block = AgentRunBlock(SessionFixture.run(task: "t", label: "Needs you", question: "Card or cash?"), now: now, relay: true)
        #expect(block.label == "Needs you")
        #expect(block.tone == .accent)
        #expect(block.question == "Card or cash?")
        #expect(block.reply && block.stop)
        #expect(!block.markDone && !block.showsResult)
    }

    @Test("034_FR_007 a reported result offers Mark step done and, with the relay on, Hand off again")
    func reportedComplete() {
        let run = SessionFixture.run(task: "t", label: "Agent reported complete")
        let on = AgentRunBlock(run, now: now, relay: true)
        #expect(on.label.hasPrefix(AgentsCopy.reportedComplete))
        #expect(on.showsResult && on.markDone && on.handOffAgain)
        #expect(!on.reply)
        #expect(!AgentRunBlock(run, now: now, relay: false).handOffAgain)
    }

    @Test("034_FR_008 other labels show verbatim with only the controls they allow")
    func otherLabels() {
        let lost = AgentRunBlock(SessionFixture.run(task: "t", label: "Stopped reporting"), now: now, relay: true)
        #expect(lost.tone == .warning && lost.stop && lost.handOffAgain)
        let unconfirmed = AgentRunBlock(SessionFixture.run(task: "t", label: "Delivery unconfirmed"), now: now, relay: true)
        #expect(unconfirmed.check && !unconfirmed.reply && !unconfirmed.stop)
        let future = AgentRunBlock(SessionFixture.run(task: "t", label: "Paused by agent"), now: now, relay: true)
        #expect(future.label == "Paused by agent")
        #expect(!future.reply && !future.stop && !future.markDone)
    }

    @Test("034_FR_008 content past its expiry shows only the expired label")
    func expired() {
        let block = AgentRunBlock(SessionFixture.run(task: "t", label: "Needs you", question: "Q"), now: Date.distantFuture, relay: true)
        #expect(block.isExpired && block.label == AgentsCopy.expired && block.question == nil)
    }
}
