import BrainBuddyAPI
import Foundation
import Testing

@testable import BrainBuddyMacCore

@Suite("030 Agent run groups")
struct AgentRunGroupTests {
    private static let now = Date(timeIntervalSince1970: 1_800_000_000)
    private static let calendar: Calendar = {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        calendar.locale = Locale(identifier: "en_US_POSIX")
        return calendar
    }()

    private func item(
        _ label: String, question: String? = nil, sent: TimeInterval? = nil, contact: TimeInterval? = nil
    ) -> AgentRunItem {
        AgentRunItem(
            stepTitle: "Compare van hire prices", taskServerID: "task_1", runID: "run_1", connectionID: "conn_1",
            agentName: "Hermes", state: AgentPrimaryState(wireValue: label), questionText: question,
            sentAt: sent.map { Self.now.addingTimeInterval(-$0) }, lastContactAt: contact.map { Self.now.addingTimeInterval(-$0) })
    }

    @Test("030_FR_006 030_SC_003 all 15 labels land in the clarified groups")
    func groupTable() {
        let table: [(String, AgentRunGroup)] = [
            ("Needs you", .needsYou), ("Delivery unconfirmed", .needsYou),
            ("Sent", .running), ("Accepted", .running), ("Running", .running), ("Cancellation requested", .running),
            ("Queued", .queued), ("Not sent", .queued),
            ("Agent reported complete", .toReview), ("Failed", .toReview), ("Cancelled", .toReview),
            ("Agent no longer reports this run", .toReview), ("Connection disconnected", .toReview),
            ("Content expired under retention policy", .toReview),
            ("Stopped reporting", .lostContact),
        ]
        #expect(table.count == 15)
        for (label, group) in table {
            #expect(AgentRunGroup(AgentPrimaryState(wireValue: label)) == group, "\(label)")
        }
    }

    @Test("030_FR_006 Lost contact holds only Stopped reporting and the groups keep their order")
    func lostContactAndOrder() {
        let members = ["Needs you", "Delivery unconfirmed", "Sent", "Accepted", "Running", "Cancellation requested", "Queued", "Not sent",
                       "Agent reported complete", "Failed", "Cancelled", "Agent no longer reports this run",
                       "Connection disconnected", "Content expired under retention policy", "Stopped reporting"]
        let lost = members.filter { AgentRunGroup(AgentPrimaryState(wireValue: $0)) == .lostContact }
        #expect(lost == ["Stopped reporting"])
        #expect(AgentRunGroup.allCases.map(\.title) == ["Needs you", "Running", "Queued", "To review", "Lost contact"])
    }

    @Test("030_FR_006 a label this build does not know sits under To review and shows verbatim")
    func unknownLabel() {
        let unknown = item("Paused by agent")
        #expect(unknown.group == .toReview)
        #expect(unknown.detail(now: Self.now) == "Paused by agent")
        #expect(unknown.compactState(now: Self.now, calendar: Self.calendar) == "Paused by agent")
    }

    @Test("030_FR_007 the canvas detail follows the label")
    func canvasDetail() {
        #expect(item("Needs you", question: "Which card?\nThe blue one or red one").detail(now: Self.now) == "Which card?")
        #expect(item("Needs you").detail(now: Self.now) == "Needs you")
        #expect(item("Delivery unconfirmed").detail(now: Self.now) == "Delivery unconfirmed")
        #expect(item("Running", sent: 240).detail(now: Self.now) == "4 min")
        #expect(item("Queued").detail(now: Self.now) == "Waiting for a free connection slot; nothing has been sent yet")
        #expect(item("Failed").detail(now: Self.now) == "Failed")
        #expect(item("Agent no longer reports this run").detail(now: Self.now) == "Agent no longer reports this run")
        #expect(item("Content expired under retention policy").detail(now: Self.now) == "Content expired under retention policy")
        #expect(item("Stopped reporting", contact: 2 * 86_400).detail(now: Self.now) == "Stopped reporting · 2 days")
        #expect(item("Running", sent: 240).subtitle(now: Self.now) == "Hermes · 4 min")
    }

    @Test("030_FR_010 the compact Waiting for words at fixed times")
    func compactState() {
        func compact(_ item: AgentRunItem) -> String { item.compactState(now: Self.now, calendar: Self.calendar) }
        #expect(compact(item("Needs you")) == "Needs you")
        #expect(compact(item("Running", sent: 240)) == "Running · 4 min")
        #expect(compact(item("Running", sent: 5)) == "Running · 1 min")
        #expect(compact(item("Running", sent: 7_300)) == "Running · 2 h")
        #expect(compact(item("Queued")) == "Queued")
        #expect(compact(item("Agent reported complete", contact: 60)) == "Reported · today")
        #expect(compact(item("Agent reported complete", contact: 86_400)) == "Reported · yesterday")
        #expect(compact(item("Stopped reporting", contact: 86_400)) == "Lost contact · 1 day")
        #expect(compact(item("Stopped reporting", contact: 172_800)) == "Lost contact · 2 days")
        for label in ["Failed", "Cancelled", "Agent no longer reports this run", "Connection disconnected", "Sent",
                      "Accepted", "Cancellation requested", "Not sent", "Delivery unconfirmed"] {
            #expect(compact(item(label)) == label)
        }
    }

    @Test("030_FR_024 only the ended labels stop being polled")
    func endedLabels() {
        let ended = ["Agent reported complete", "Failed", "Cancelled", "Agent no longer reports this run",
                     "Connection disconnected", "Content expired under retention policy"]
        for label in ended { #expect(AgentPrimaryState(wireValue: label).isEnded, "\(label)") }
        for label in ["Needs you", "Running", "Sent", "Queued", "Stopped reporting", "Cancellation requested"] {
            #expect(!AgentPrimaryState(wireValue: label).isEnded, "\(label)")
        }
    }
}
