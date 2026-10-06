import BrainBuddyCore
import Foundation
import Testing

/// Account linking and local auto-parks (contracts/ios-commands.md §7, owner
/// decision 2026-10-06; tasks.md T091).
@Suite("ReviewAccountLinking (spec 020)")
struct ReviewAccountLinkingTests {
    let t0 = Review.instant("2026-09-01T09:00:00Z")
    let park = Review.instant("2026-10-15T09:00:00Z")

    func operation(_ command: GTDCommand, at date: Date, sent: Bool = false) -> PendingOperation {
        var operation = Review.op(command, at: date)
        if sent { operation.attempts = 1 }
        return operation
    }

    @Test("020-FR-014 unsent auto-parks become plain moves to Someday, counted as seen; an unsent extend is dropped and listed")
    func conversion() throws {
        let outbox = [
            operation(.review(.acknowledgeExplainer(timeZone: "Europe/Berlin")), at: t0),
            operation(.autoParkTask(.init(taskID: "p1", formulationID: Review.form(1))), at: park),
            operation(Review.decide(.reformulate, "n1", decision: 1, formulation: Review.form(5), title: "New wording", newFormulation: Review.form(6)), at: park),
            operation(.autoParkTask(.init(taskID: "p2", formulationID: Review.form(2))), at: park.addingTimeInterval(1)),
            operation(Review.decide(.extend, "n2", decision: 2, formulation: Review.form(7), reason: "Waiting for the quote"), at: park.addingTimeInterval(2)),
            operation(.undoDecision(Review.decision(2)), at: park.addingTimeInterval(3)),
            operation(
                .review(.acknowledgeParks([ParkAck(taskID: "p1", formulationID: Review.form(1)), ParkAck(taskID: "x", formulationID: Review.form(9))])),
                at: park.addingTimeInterval(4)
            ),
            operation(.review(.acknowledgeParks([ParkAck(taskID: "p2", formulationID: Review.form(2))])), at: park.addingTimeInterval(5)),
            operation(.review(.startSession(.init(sessionID: Review.session(1), mode: .quick, entry: .list))), at: park.addingTimeInterval(6)),
        ]
        var document = StoreDocument(outbox: outbox)
        document.local.issuedAutoParks = ["p1": Review.form(1), "p2": Review.form(2)]
        let linked = ReviewAccountLinking.convertLocalAutoParks(document)
        let commands = linked.outbox.map(\.command)
        #expect(
            commands == [
                .review(.acknowledgeExplainer(timeZone: "Europe/Berlin")),
                .transitionTask(.init(taskID: "p1", action: .move, toList: .someday)),
                Review.decide(.reformulate, "n1", decision: 1, formulation: Review.form(5), title: "New wording", newFormulation: Review.form(6)),
                .transitionTask(.init(taskID: "p2", action: .move, toList: .someday)),
                .review(.acknowledgeParks([ParkAck(taskID: "x", formulationID: Review.form(9))])),
                .review(.startSession(.init(sessionID: Review.session(1), mode: .quick, entry: .list))),
            ]
        )
        #expect(linked.outbox[1].issuedAt == park && linked.outbox[1].id == outbox[1].id, "same position, issuedAt and id")
        #expect(linked.local.linkedExtensionNotices == ["n2"])
        #expect(linked.local.issuedAutoParks.isEmpty)
        #expect(ReviewAccountLinking.convertLocalAutoParks(document) == linked, "deterministic")
    }

    @Test("020-FR-014 operations that may have reached a server are never rewritten")
    func sentOperationsStay() {
        let sentPark = operation(.autoParkTask(.init(taskID: "p1", formulationID: Review.form(1))), at: park, sent: true)
        let document = StoreDocument(outbox: [sentPark])
        #expect(ReviewAccountLinking.convertLocalAutoParks(document).outbox == [sentPark])
    }

    @Test("020-FR-014 020-FR-040 after conversion the task is in Someday without a park marker, nothing back in Next")
    func replayAfterConversion() throws {
        let create = operation(.createTask(.init(taskID: "p1", title: "Call Bob", list: .next, newFormulationID: Review.form(1))), at: t0)
        let ack = operation(.review(.acknowledgeExplainer(timeZone: "Europe/Berlin")), at: t0)
        let autoPark = operation(.autoParkTask(.init(taskID: "p1", formulationID: Review.form(1))), at: park)
        let before = StoreDocument(outbox: [ack, create, autoPark])
        let parked = before.replayed().state
        #expect(parked.tasks["p1"]?.parked != nil && GTDQueries.unseenParks(in: parked).count == 1)
        let linked = ReviewAccountLinking.convertLocalAutoParks(before).replayed().state
        #expect(linked.tasks["p1"]?.state == .someday)
        #expect(linked.tasks["p1"]?.parked == nil)
        #expect(GTDQueries.unseenParks(in: linked).isEmpty, "converted parks are not offered on While you were away")
    }
}
