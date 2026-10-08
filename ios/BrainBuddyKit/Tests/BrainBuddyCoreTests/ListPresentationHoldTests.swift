import Testing

@testable import BrainBuddyCore

@Suite("ListPresentationHold")
struct ListPresentationHoldTests {
    @Test("021-FR-009 a pull that moves the held row keeps it at its index while every other row takes its new place")
    func heldRowKeepsItsIndex() {
        let order = ListPresentationHold.order(
            onScreen: ["a", "b", "c", "d"], incoming: ["c", "a", "d", "b"], held: "b")
        #expect(order == ["c", "b", "a", "d"])
    }

    @Test("021-FR-009 release applies the full new order")
    func releaseAppliesTheNewOrder() {
        let incoming = ["c", "a", "d", "b"]
        #expect(ListPresentationHold.order(onScreen: ["a", "b", "c", "d"], incoming: incoming, held: nil) == incoming)
    }

    @Test("021-FR-009 a held row that left the list stays until release")
    func heldRowThatLeftStays() {
        let order = ListPresentationHold.order(onScreen: ["a", "b", "c"], incoming: ["a", "c", "d"], held: "b")
        #expect(order == ["a", "b", "c", "d"])
    }

    @Test("021-FR-009 new rows appear, and a short list puts the held row last")
    func newRowsAndShortLists() {
        #expect(ListPresentationHold.order(onScreen: ["a", "b", "c", "d"], incoming: ["d", "x"], held: "d") == ["x", "d"])
        #expect(ListPresentationHold.order(onScreen: ["a", "b"], incoming: ["x", "a", "b"], held: "a") == ["a", "x", "b"])
    }

    @Test("021-FR-009 a hold on a row that was not on screen holds nothing")
    func holdOnAnUnknownRow() {
        #expect(ListPresentationHold.order(onScreen: ["a"], incoming: ["b", "a"], held: "z") == ["b", "a"])
    }
}
