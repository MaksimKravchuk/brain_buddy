import Foundation

/// FR-009's pointer clause: while a row is held (under the pointer, or being edited), a pull that
/// moves it does not move it on screen. Every other row takes its new place; releasing the hold
/// is asking for the incoming order itself.
public enum ListPresentationHold {
    /// The order to show. The `held` row keeps its index from `onScreen`, even when `incoming` no
    /// longer lists it (its row stays, for the view to dim, until release). A hold on a row that
    /// was not on screen holds nothing.
    public static func order<ID: Hashable>(onScreen: [ID], incoming: [ID], held: ID?) -> [ID] {
        guard let held, let index = onScreen.firstIndex(of: held) else { return incoming }
        var order = incoming.filter { $0 != held }
        order.insert(held, at: min(index, order.count))
        return order
    }
}
