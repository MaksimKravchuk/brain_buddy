import XCTest

/// Last on purpose: after the 401s the account cannot be signed in again on a Rust-selected install
/// (see FINDING-SIGNIN-AGAIN), so nothing that needs the session may run after this class.
@MainActor
final class SessionRehearsalTests: XCTestCase {
    override func setUp() { continueAfterFailure = true }

    // MARK: Session expired (last: a Rust-selected install cannot sign in again)

    func testS4_90_sessionExpiredShowsSignInAgain() async throws {
        let d = Driver.launch(pilot: true)
        try await Rehearsal.setServer(.unauth)
        defer { Task { try? await Rehearsal.setServer(.up) } }
        d.openSettings()
        let syncNow = d.app.buttons["Sync now"]
        d.reveal(syncNow)
        if syncNow.isEnabled { syncNow.tap() }
        let again = d.anyContaining("Sign in again to sync")
        let seen = again.waitForExistence(timeout: 45)
        shot(d.app, "s4-90-session-expired")
        check("UX-06", seen, pass: "Every request answered 401: status reads \"Sign in again to sync\" and waiting changes stay with the account.",
              fail: "No \"Sign in again to sync\" after 401s. Status: \(d.syncStatusText() ?? "(none)")")
        try await Rehearsal.setServer(.up)
        let signInAgain = d.app.buttons["Sign in again"]
        d.reveal(signInAgain)
        if signInAgain.exists {
            signInAgain.tap()
            let refusal = d.anyContaining("This account change isn't available yet")
            // The sheet's password step: use the existing account's password.
            let usePassword = d.app.buttons["Use your password"]
            if usePassword.waitForExistence(timeout: 10) { usePassword.tap() }
            let password = d.app.secureTextFields["Password"]
            if password.waitForExistence(timeout: 5) {
                sleep(1)
                password.tap()
                sleep(1)
                d.typeSlowly(password, Rehearsal.accountA.password)
                shot(d.app, "s4-91-sign-in-again-typed")
                d.app.buttons.matching(NSPredicate(format: "label == 'Sign in'")).allElementsBoundByIndex.first(where: \.isHittable)?.tap()
            }
            let refused = refusal.waitForExistence(timeout: 20)
            shot(d.app, "s4-91-sign-in-again")
            Rehearsal.record("FINDING-SIGNIN-AGAIN", refused ? "FINDING" : "OBSERVED",
                             refused ? "On the Rust runtime \"Sign in again\" opens the sign-in sheet but signing in is refused: \"This account change isn't available yet. Your work is kept.\" The session cannot be renewed on this build." : "Settings > Sign in again opens the sign-in sheet (\"Sign in again\", account and server shown, email prefilled). The automation could not get the password field to take input on this sheet, so the submit and its outcome were not observed. Same code path as FINDING-SIGNIN (Workspace.beginSignIn refuses a Rust-selected workspace), so renewing an expired session is expected to be refused too: confirm by hand.")
        } else {
            Rehearsal.record("FINDING-SIGNIN-AGAIN", "OBSERVED", "No Sign in again button on the Settings screen after the 401s.")
        }
    }
}
