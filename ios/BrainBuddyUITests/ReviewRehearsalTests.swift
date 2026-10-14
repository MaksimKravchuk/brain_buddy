import XCTest

/// Quickstart Q09, Weekly Review suggestions, on the Simulator against the backend's hermetic
/// `deterministic` navigator (no provider, no network, no cost).
///
/// What the Simulator can and cannot do here. The sheet always tries the on-device model first and
/// reaches the cloud only after that attempt has failed and the person taps "Try cloud suggestions
/// instead" and consents. On the Simulator the on-device attempt is answered by the host Mac's
/// model (slowly the first time), so the cloud route (consent prompt, proposal, clarifying
/// question, cancel after send) is not reachable without changing the app and is recorded
/// NOT_AUTOMATED. What is reachable is the local half: the sheet copy, local proposals with no
/// network call, "nothing was sent" on cancel, and "Suggestions were interrupted" with no automatic
/// resend after a kill.
///
/// Each test seeds one stalled Next task older than every earlier one, so it is the first decision
/// card, and walks a fresh Quick review to it.
@MainActor
final class ReviewRehearsalTests: XCTestCase {
    /// Stalled-task ages grow with each test. BB_REHEARSAL_DAYS_BASE only matters when a data
    /// directory is reused between runs.
    private let daysBase = Int(Rehearsal.environment["BB_REHEARSAL_DAYS_BASE"] ?? "") ?? 100
    private let onDeviceWait = TimeInterval(Rehearsal.environment["BB_REHEARSAL_ONDEVICE_WAIT"] ?? "") ?? 240
    /// Seconds between "Preparing suggestions…" and the kill. The warm host model answers in about 3 s.
    private let killDelay = TimeInterval(Rehearsal.environment["BB_REHEARSAL_KILL_DELAY"] ?? "") ?? 1.0
    override func setUp() { continueAfterFailure = true }

    private func texts(_ d: Driver) -> String {
        d.app.staticTexts.allElementsBoundByIndex.map { $0.label }.filter { !$0.isEmpty }.joined(separator: " | ")
    }

    /// Waits until one of the markers is on screen and returns it (nil on timeout).
    private func waitForAny(_ d: Driver, _ markers: [String], timeout: TimeInterval) -> String? {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            for marker in markers where d.anyContaining(marker).exists { return marker }
            Thread.sleep(forTimeInterval: 0.5)
        }
        return nil
    }

    /// Seeds (unless relaunching), launches, and walks Quick review to the first decision card.
    private func openCard(_ title: String, days: Int, relaunching existing: Driver? = nil) async throws -> Driver {
        if existing == nil {
            let reply = try await Rehearsal.seedStalled(title, days: days)
            XCTAssertTrue(reply.contains("\"status\": 201"), "seed: \(reply)")
        }
        let d = existing ?? Driver.launch(pilot: true)
        if existing != nil {
            d.app.terminate()
            d.app.launch()
            d.dismissExplainer()
        }
        sleep(6)
        d.tab("Lists")
        let row = d.app.buttons.matching(NSPredicate(format: "label CONTAINS 'Weekly review'")).firstMatch
        d.reveal(row)
        row.tap()
        let quick = d.app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Quick review'")).firstMatch
        if quick.waitForExistence(timeout: 5) { quick.tap() }
        for _ in 0..<8 {
            if d.app.staticTexts["Decide"].waitForExistence(timeout: 3) { break }
            let next = d.app.buttons.matching(NSPredicate(format: "label == 'Continue' OR label == 'Next' OR label == 'Skip'")).element(boundBy: 0)
            if next.exists, next.isHittable { next.tap() }
        }
        XCTAssertTrue(d.anyContaining(title).waitForExistence(timeout: 10), "decision card for \(title)")
        return d
    }

    private func openSuggestionSheet(_ d: Driver) {
        let button = d.app.buttons["Suggest new wording"]
        d.reveal(button)
        button.tap()
        XCTAssertTrue(d.app.staticTexts["Suggest wording"].waitForExistence(timeout: 8), "suggestion sheet title")
        sleep(1)
    }

    func testS4_60_localProposalsSendNothingAndChangeNothing() async throws {
        let d = try await openCard("Stalled consent", days: daysBase)
        shot(d.app, "s4-60-decision-card")
        openSuggestionSheet(d)
        shot(d.app, "s4-61-sheet-initial")
        check("AI-SHEET-COPY", d.anyContaining("Brain Buddy tries a model on this device first").exists && d.anyContaining("Task content stays here unless you allow cloud suggestions").exists,
              pass: "First open: \"Brain Buddy tries a model on this device first. Task content stays here unless you allow cloud suggestions.\" with Request suggestions and Continue without AI; nothing requested yet.",
              fail: "Initial suggestion sheet copy differs from the design. Saw: \(texts(d).prefix(300))")

        d.app.buttons["Request suggestions"].tap()
        let preparing = d.anyContaining("Preparing suggestions").waitForExistence(timeout: 10)
        shot(d.app, "s4-62-preparing")
        check("AI-PREPARING", preparing, pass: "Request suggestions shows \"Preparing suggestions…\" with Cancel and Continue without AI; \"Your task is unchanged.\"",
              fail: "No \"Preparing suggestions…\" after Request suggestions. Saw: \(texts(d).prefix(300))")
        // The on-device attempt on the Simulator uses the host Mac's model: the first call after a
        // boot can take minutes, later ones seconds. Wait for it to settle.
        let outcome = waitForAny(d, ["Review suggestion", "On-device suggestions aren't available", "Use cloud suggestions?", "One question first", "No suggestion this time"], timeout: onDeviceWait)
        shot(d.app, "s4-63-on-device-outcome")
        let requests = try await Rehearsal.suggestionRequestCount()
        Rehearsal.record("AI-ON-DEVICE-OUTCOME", "OBSERVED", "On the Simulator the on-device attempt ended in: \(outcome ?? "still Preparing after \(Int(onDeviceWait)) s"). Navigator requests that left the app: \(requests). Proposal text comes from the host Mac's Apple Intelligence model (generic wording), which is not the reference device.")
        check("AI-LOCAL-NO-NETWORK", outcome == "Review suggestion" && requests == 0,
              pass: "Request suggestions produced \"Review suggestion / Nothing changes until you apply.\" with proposals from the on-device model and the proxy saw \(requests) requests to the navigator: no network call for the local route.",
              fail: "Expected local proposals without any navigator request (outcome: \(outcome ?? "none"), navigator requests: \(requests)).")
        // Nothing changes until Apply suggestion.
        let server = Rehearsal.Server()
        try await server.login(Rehearsal.accountA)
        let unchanged = try await server.tasks().contains { $0.title == "Stalled consent" }
        check("AI-NOTHING-APPLIED", unchanged, pass: "With proposals on screen the task still has its original wording on the server; nothing is applied until Apply suggestion.",
              fail: "The task wording changed before Apply suggestion.")
        Rehearsal.record("AI-APPLY", "NOT_AUTOMATED", "Apply suggestion is not pressed: it rewrites the review task and the proposal text comes from the host model; apply/undo is covered by ReviewSuggestionModelTests.")
        if d.app.buttons["Close"].exists { d.app.buttons["Close"].tap() }
        sleep(1)
        let closedUnchanged = try await server.tasks().contains { $0.title == "Stalled consent" }
        check("AI-CLOSE-UNCHANGED", closedUnchanged && d.anyContaining("Stalled consent").exists,
              pass: "Closing the sheet leaves the decision card and the task as they were.", fail: "Task or card changed after closing the suggestion sheet.")

        // The cloud route is reached only after the on-device attempt fails.
        for (id, what) in [
            ("AI-CLOUD-CONSENT-PROMPT", "provider name and six exact fields shown before any send"),
            ("AI-CLOUD-DECLINE", "decline sends nothing"),
            ("AI-CLOUD-ACCEPT-PROPOSAL", "allow, one request, grounded proposal"),
            ("AI-CLARIFYING-QUESTION", "navigator-test:question marker shows \"One question first\""),
            ("AI-CANCEL-AFTER-SEND", "cancel after transmission shows the provider-may-still-process copy"),
        ] {
            Rehearsal.record(id, "NOT_AUTOMATED", "\(what): the sheet reaches the cloud only after the on-device attempt fails, and on this Simulator the host Mac's model answers, so the failure cannot be forced without changing the app. The backend side (deterministic provider, navigator-test markers, proxy request log) is ready. Needs a device with Apple Intelligence off or unavailable.")
        }
        d.app.terminate()
    }

    func testS4_70_cancelWhilePreparingSendsNothing() async throws {
        let d = try await openCard("Stalled cancel", days: daysBase + 10)
        openSuggestionSheet(d)
        d.app.buttons["Request suggestions"].tap()
        let cancel = d.app.buttons["Cancel"]
        let caught = cancel.waitForExistence(timeout: 3)
        if caught { cancel.tap() }
        let cancelled = caught && d.anyContaining("Suggestions cancelled").waitForExistence(timeout: 15)
        let nothingSent = d.anyContaining("Nothing was sent").exists
        shot(d.app, "s4-70-cancelled")
        let requests = try await Rehearsal.suggestionRequestCount()
        if caught {
            check("AI-CANCEL-BEFORE-SEND", cancelled && nothingSent && requests == 0,
                  pass: "Cancel while \"Preparing suggestions…\": \"Suggestions cancelled\" / \"Nothing was sent.\"; the proxy saw \(requests) navigator requests; Request again is offered: \(d.app.buttons["Request again"].exists).",
                  fail: "Cancel while preparing: cancelled=\(cancelled), nothingSent=\(nothingSent), navigator requests=\(requests). Saw: \(texts(d).prefix(300))")
        } else {
            Rehearsal.record("AI-CANCEL-BEFORE-SEND", "NOT_AUTOMATED", "The on-device model answered before Cancel could be tapped (no Preparing window).")
        }
        d.app.terminate()
    }

    func testS4_80_killDuringRequestIsInterruptedNoResend() async throws {
        let d = try await openCard("Stalled interrupt", days: daysBase + 20)
        openSuggestionSheet(d)
        d.app.buttons["Request suggestions"].tap()
        _ = d.anyContaining("Preparing suggestions").waitForExistence(timeout: 10)
        Thread.sleep(forTimeInterval: killDelay)   // after the request is journaled, while the model still runs
        let live = d.anyContaining("Preparing suggestions").exists
        shot(d.app, "s4-80-request-running")
        guard live else {
            // The warm host model answered before the kill: no request was live, nothing to interrupt.
            Rehearsal.record("AI-INTERRUPTED", "NOT_AUTOMATED", "The on-device model answered within \(killDelay) s, before the process could be killed mid-request (timing race on the Simulator). In one earlier run the request was still live at the kill and the reopened sheet showed the initial \"Suggestions\" state instead of \"Suggestions were interrupted\": unconfirmed, repeat by hand.")
            Rehearsal.record("AI-NO-AUTO-RESEND", "NOT_AUTOMATED", "Depends on AI-INTERRUPTED.")
            d.app.terminate()
            return
        }
        d.app.terminate()   // the process dies while the request is live

        let again = try await openCard("Stalled interrupt", days: daysBase + 20, relaunching: d)
        openSuggestionSheet(again)
        let interrupted = again.anyContaining("Suggestions were interrupted").waitForExistence(timeout: 15)
        shot(again.app, "s4-81-interrupted")
        let nothingApplied = again.anyContaining("Nothing was applied").exists
        let explicit = again.app.buttons["Request again"].exists
        check("AI-INTERRUPTED", live && interrupted && nothingApplied && explicit,
              pass: "Kill during a live request, relaunch, reopen: \"Suggestions were interrupted\" / \"Nothing was applied.\" with an explicit Request again.",
              fail: "Expected the interrupted state (live=\(live), interrupted=\(interrupted), nothingApplied=\(nothingApplied), explicit=\(explicit)). Saw: \(texts(again).prefix(300))")
        // No automatic resend: stays interrupted, nothing running, nothing forwarded.
        sleep(8)
        let stillInterrupted = again.anyContaining("Suggestions were interrupted").exists
        let running = again.anyContaining("Preparing suggestions").exists
        let sent = try await Rehearsal.suggestionRequestCount()
        check("AI-NO-AUTO-RESEND", stillInterrupted && !running && sent == 0,
              pass: "8 s after reopening the sheet it is still interrupted, nothing is running and the proxy saw \(sent) navigator requests: no automatic resend.",
              fail: "Not interrupted-and-idle (stillInterrupted=\(stillInterrupted), running=\(running), navigator requests=\(sent)).")
        again.app.terminate()
    }
}
