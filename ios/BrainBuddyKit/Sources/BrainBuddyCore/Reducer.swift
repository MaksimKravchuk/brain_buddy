import Foundation

/// The single place GTD rules live. The same function applies a user's
/// command on the device, replays queued commands over newer server state,
/// and runs identically in the app, widgets and App Intents — so every GTD
/// action works without a network.
///
/// It mirrors the server (ADR-0006 lifecycle, `backend/app/modules/tasks`):
/// see `docs/native-ios-app.md` for the rule table.
public enum GTDReducer {
    /// Applies `command` as if issued at `date`.
    /// - Throws: `GTDValidationError` and leaves `state` untouched.
    @discardableResult
    public static func apply(
        _ command: GTDCommand, at date: Date, to state: inout GTDState, mode: ApplyMode = .interactive
    ) throws(GTDValidationError) -> ApplyOutcome {
        fatalError("GTDReducer.apply is not implemented yet")
    }
}
