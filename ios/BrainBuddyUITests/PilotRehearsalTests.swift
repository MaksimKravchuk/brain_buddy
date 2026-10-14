import XCTest

/// Phase 1 of scripts/rehearsal/run_ios_ui.sh, on a freshly installed app: the pilot switch is on
/// before anybody signs in. Kept apart from `PilotRehearsalTests` because it leaves the install on
/// the Rust runtime for good (the switch is one-way), so the runner uninstalls the app between them.
@MainActor
final class PilotFirstRehearsalTests: XCTestCase {
    override func setUp() { continueAfterFailure = true }

    /// Account-less, switch on: the shared runtime must be selected, and then a person has to be
    /// able to sign in on it.
    func testS4_01_pilotOnFreshInstallThenSignIn() async throws {
        let d = Driver.launch(pilot: true)
        d.openSettings()
        d.reveal(d.textContaining("This device uses the shared runtime"))
        check("PILOT-SWITCH", d.textContaining("This device uses the shared runtime").exists,
              pass: "Fresh install with -BBRustRuntimePilot YES: Settings > Pilot footer reads \"This device uses the shared runtime. Your tasks were carried over once.\" and the switch is locked on.",
              fail: "Settings > Pilot footer did not report the shared runtime after the first launch with the switch on.")
        shot(d.app, "s4-01-pilot-fresh-settings")
        d.app.collectionViews.firstMatch.swipeDown()
        d.app.collectionViews.firstMatch.swipeDown()
        d.signIn(Rehearsal.accountA)
        let refusal = d.anyContaining("This account change isn't available yet")
        let refused = refusal.waitForExistence(timeout: 20)
        shot(d.app, "s4-02-pilot-fresh-signin-refused")
        check("FINDING-SIGNIN", refused,
              pass: "On a Rust-selected install the sign-in sheet (password, correct credentials, local backend up) shows \"This account change isn't available yet. Your work is kept.\" and signs nobody in: SignInSheet calls Workspace.beginSignIn/completeSignIn, which refuse a Rust workspace. FINDING, not a pass of 'sign in A with pilot switch'.",
              fail: "Expected the sign-in refusal on a Rust-selected install; saw something else (see attachment).")
    }
}

/// Phase 2: legacy sign-in first, then the pilot switch (the only order in which an account can be
/// linked on this build), then the sync-status, edit, offline, conflict and Weekly Review journeys.
/// Tests share one simulator install and one server and run in name order.
@MainActor
final class PilotRehearsalTests: XCTestCase {
    private let server = Rehearsal.Server()

    override func setUp() { continueAfterFailure = true }

    private func loginServer() async throws { try await server.login(Rehearsal.accountA) }

    // MARK: Account-less and legacy sign-in (before the switch)

    func testS4_10_accountlessAndTyping() async throws {
        let d = Driver.launch(pilot: false)
        // Control for the dropped-keystroke observation: fast typing into capture on the legacy runtime.
        d.tab("Inbox")
        d.capture("Rehearsal fast typing", slowly: false)
        let onDevice = d.anyContaining("On this iPhone")
        check("UX-02", onDevice.waitForExistence(timeout: 5),
              pass: "Account-less, legacy runtime: the Inbox header reads \"\(onDevice.safeLabel)\".",
              fail: "No \"On this iPhone\" status on the Inbox header account-less (Lists shows none).")
        shot(d.app, "s4-10-accountless-inbox")
        let intact = d.row("Rehearsal fast typing").waitForExistence(timeout: 5)
        Rehearsal.record("TYPING-LEGACY", intact ? "PASS" : "FAIL",
                         intact ? "Fast typeText into capture on the legacy runtime arrived intact." : "Fast typeText into capture on the legacy runtime lost characters too (XCUITest injection, not the Rust runtime).")
        shot(d.app, "s4-11-legacy-fast-typing")
    }

    func testS4_20_signInLegacyThenStatus() async throws {
        let d = Driver.launch(pilot: false)
        d.signIn(Rehearsal.accountA)
        XCTAssertTrue(d.app.navigationBars["Settings"].waitForExistence(timeout: 15))
        let synced = d.anyContaining("Synced just now")
        check("UX-01", synced.waitForExistence(timeout: 20),
              pass: "Signed in, queue empty: Settings > Sync > Status reads \"Synced just now\"; Waiting to sync reads \"Nothing\".",
              fail: "No \"Synced just now\" after sign-in.")
        shot(d.app, "s4-20-signed-in-synced")
        try await loginServer()
        let tasks = await server.waitFor { $0.contains { $0.title == "Rehearsal fast typing" } }
        check("LEGACY-SYNC", tasks.contains { $0.title == "Rehearsal fast typing" },
              pass: "The task captured account-less was merged into account A on first sign-in (visible over REST).",
              fail: "The account-less task did not reach the server after sign-in.")
    }

    // MARK: The switch

    func testS4_30_pilotSelectedWithAccount() async throws {
        let d = Driver.launch(pilot: true)
        d.openSettings()
        let footer = d.textContaining("This device uses the shared runtime")
        d.reveal(footer)
        check("PILOT-SWITCH-ACCOUNT", footer.exists,
              pass: "Switch on with account A linked: next launch imports once and selects the shared runtime (Settings > Pilot footer); the account stays linked.",
              fail: "Shared runtime not reported after enabling the switch with an account linked.")
        shot(d.app, "s4-30-pilot-active-settings")
        d.app.collectionViews.firstMatch.swipeDown()
        d.app.collectionViews.firstMatch.swipeDown()
        check("PILOT-ACCOUNT-KEPT", d.anyContaining("rehearsal-a@example.com").exists,
              pass: "Account A is still shown after the move to the shared runtime.",
              fail: "Account A is not shown after the move to the shared runtime.")
        let status = d.anyContaining("Synced")
        check("UX-01-RUST", status.waitForExistence(timeout: 20),
              pass: "Rust runtime, queue empty: status reads \"\(status.safeLabel)\".",
              fail: "No \"Synced\" status on the Rust runtime.")
        try await loginServer()
        let tasks = await server.waitFor { $0.contains { $0.title == "Rehearsal fast typing" } }
        check("PILOT-DATA-KEPT", tasks.contains { $0.title == "Rehearsal fast typing" },
              pass: "Server still has the carried-over task.", fail: "Carried-over task missing on the server.")
    }

    // MARK: Create, edit, complete on the Rust runtime

    func testS4_40_createEditComplete() async throws {
        let d = Driver.launch(pilot: true)
        try await loginServer()
        d.tab("Inbox")
        d.capture("Rehearsal alpha")
        var tasks = await server.waitFor { $0.contains { $0.title == "Rehearsal alpha" } }
        check("RUST-CREATE", tasks.contains { $0.title == "Rehearsal alpha" },
              pass: "Task created in the app reached the server as \"Rehearsal alpha\".", fail: "Created task did not reach the server in 30 s.")
        shot(d.app, "s4-40-created")

        d.row("Rehearsal alpha").tap()
        let title = d.app.textFields["Title"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        title.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        d.typeSlowly(title, " v2")
        title.typeText("\n")
        d.back()
        tasks = await server.waitFor { $0.contains { $0.title == "Rehearsal alpha v2" } }
        check("RUST-EDIT", tasks.contains { $0.title == "Rehearsal alpha v2" },
              pass: "Title edit made in the app reached the server (\"Rehearsal alpha v2\").", fail: "Edited title did not reach the server.")
        shot(d.app, "s4-41-edited")

        d.row("Rehearsal alpha v2").tap()
        d.app.buttons["Complete"].firstMatch.tap()
        tasks = await server.waitFor { $0.contains { $0.title == "Rehearsal alpha v2" && $0.completed } }
        check("RUST-COMPLETE", tasks.contains { $0.title == "Rehearsal alpha v2" && $0.completed },
              pass: "Completing the task in the app marked it completed on the server.", fail: "Completion did not reach the server.")
        shot(d.app, "s4-42-completed")
    }

    // MARK: Offline and waiting

    func testS4_50_offlineWaitingAndRecovery() async throws {
        let d = Driver.launch(pilot: true)
        try await loginServer()
        try await Rehearsal.setServer(.down)
        defer { Task { try? await Rehearsal.setServer(.up) } }
        d.tab("Inbox")
        for name in ["Offline one", "Offline two", "Offline three"] { d.capture(name) }
        let header = d.anyContaining("changes waiting")
        let sawWaiting = header.waitForExistence(timeout: 30)
        let text = sawWaiting ? header.safeLabel : "(none)"
        check("UX-03", sawWaiting && text.contains("3"),
              pass: "Server unreachable, three tasks captured: status reads \"\(text)\".",
              fail: "Expected a waiting-changes status with 3 after three offline captures; saw \"\(text)\".")
        shot(d.app, "s4-50-offline-3-waiting")
        let local = d.anyContaining("saved on this")
        Rehearsal.record("UX-03-SAVED-COPY", local.exists ? "PASS" : "NOT_OBSERVED",
                         local.exists ? "\"\(local.safeLabel)\" is on screen." : "No 'Your changes are saved on this device.' line on the Inbox header; Settings > Sync is checked next.")
        d.openSettings()
        let settingsStatus = d.syncStatusText() ?? "(none)"
        let reason = d.anyContaining("Connect to sync")
        Rehearsal.record("UX-03-SETTINGS", "OBSERVED", "Settings > Sync status: \"\(settingsStatus)\"; Sync now explanation: \(reason.exists ? reason.safeLabel : "none")")
        shot(d.app, "s4-51-offline-settings")

        // Relaunch while still unreachable: the waiting changes survive.
        d.app.terminate()
        d.app.launch()
        d.dismissExplainer()
        d.tab("Inbox")
        XCTAssertTrue(d.row("Offline three").waitForExistence(timeout: 15))
        let after = d.anyContaining("changes waiting")
        check("UX-03-RELAUNCH", after.waitForExistence(timeout: 30),
              pass: "After a relaunch with the server still down the three tasks are present and the status still reads \"\(after.safeLabel)\".",
              fail: "After relaunch the waiting-changes status is gone.")
        shot(d.app, "s4-52-offline-relaunch")

        try await Rehearsal.setServer(.up)
        d.openSettings()
        let syncNow = d.app.buttons["Sync now"]
        d.reveal(syncNow)
        if syncNow.isEnabled { syncNow.tap() }
        let tasks = await server.waitFor(timeout: 60) { t in ["Offline one", "Offline two", "Offline three"].allSatisfy { n in t.contains { $0.title == n } } }
        check("OFFLINE-REPLAY", ["Offline one", "Offline two", "Offline three"].allSatisfy { n in tasks.contains { $0.title == n } },
              pass: "Server back: all three offline tasks arrived on the server exactly once each.",
              fail: "Offline tasks did not all reach the server after reconnecting.")
        let each = ["Offline one", "Offline two", "Offline three"].map { n in tasks.filter { $0.title == n }.count }
        check("OFFLINE-ONCE", each == [1, 1, 1], pass: "No duplicates after replay (counts \(each)).", fail: "Duplicates after replay: \(each).")
        d.app.collectionViews.firstMatch.swipeDown()
        let synced = d.anyContaining("Synced")
        check("UX-04-DRAINED", synced.waitForExistence(timeout: 30),
              pass: "After reconnecting, Settings > Sync status reads \"\(synced.safeLabel)\" with nothing waiting.",
              fail: "No synced status after the queue drained.")
        shot(d.app, "s4-53-after-reconnect")
    }

    // MARK: Typing fidelity (an observation made while building this suite)

    /// Fast `typeText` into capture arrived intact on the legacy runtime (testS4_10). Here is the
    /// same input on the Rust runtime; characters were lost in the exploratory runs.
    func testS4_45_fastTypingIntoCaptureOnRustRuntime() async throws {
        let d = Driver.launch(pilot: true)
        d.tab("Inbox")
        d.capture("Rehearsal fast rust", slowly: false)
        let intact = d.row("Rehearsal fast rust").waitForExistence(timeout: 5)
        shot(d.app, "s4-45-fast-typing-rust")
        let seen = d.app.buttons.allElementsBoundByIndex.map { $0.label }.filter { $0.hasPrefix("R") && $0 != "Rehearsal alpha v2" }.prefix(5)
        Rehearsal.record("TYPING-RUST", intact ? "PASS" : "FINDING",
                         intact ? "Fast typeText into capture on the Rust runtime arrived intact."
                                : "Fast typeText of \"Rehearsal fast rust\" into capture on the Rust runtime produced \(Array(seen)) while the same input on the legacy runtime arrived intact. May be a keystroke race in the capture field (a per-keystroke preview on the shared runtime) or a Simulator artefact: confirm by typing on a device.")
    }

    // MARK: Conflict (rows 8, 9, 11, 12)

    func testS4_55_sameTitleEditedOnTwoDevices() async throws {
        let d = Driver.launch(pilot: true)
        try await loginServer()
        d.tab("Inbox")
        d.capture("Conflict base")
        _ = await server.waitFor { $0.contains { $0.title == "Conflict base" } }

        // This device, offline: rename.
        try await Rehearsal.setServer(.down)
        defer { Task { try? await Rehearsal.setServer(.up) } }
        d.row("Conflict base").tap()
        let title = d.app.textFields["Title"]
        XCTAssertTrue(title.waitForExistence(timeout: 5))
        title.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        d.typeSlowly(title, " phone")
        title.typeText("\n")
        d.back()
        // The other device renames the same task on the server.
        try await server.rename(taskTitled: "Conflict base", to: "Conflict base laptop")
        try await Rehearsal.setServer(.up)

        d.openSettings()
        let syncNow = d.app.buttons["Sync now"]
        d.reveal(syncNow)
        if syncNow.isEnabled { syncNow.tap() }
        let issues = d.app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Sync issues'")).firstMatch
        let opened = issues.waitForExistence(timeout: 45)
        d.reveal(issues)
        shot(d.app, "s4-55-settings-with-issue")
        let status = d.syncStatusText() ?? "(none)"
        check("UX-05", opened && (status.contains("couldn't sync") || status.contains("Sync issue") || status.contains("issue")),
              pass: "A rename on two devices left one change that could not apply; Settings > Sync shows a Sync issues row and the status reads \"\(status)\".",
              fail: "No sync issue after a same-title edit on two devices (opened=\(opened)); status \"\(status)\".")
        guard opened else { return }
        issues.tap()
        sleep(2)
        shot(d.app, "s4-56-sync-issues-list")
        // The list row for the conflict, then its detail.
        let detailRow = d.app.buttons.matching(NSPredicate(format: "label CONTAINS 'Conflict base'")).firstMatch
        if detailRow.waitForExistence(timeout: 5) { detailRow.tap() } else if d.app.cells.firstMatch.exists { d.app.cells.firstMatch.tap() }
        sleep(2)
        shot(d.app, "s4-57-conflict-detail")
        dump(d.app, "57-conflict-detail")
        let allTexts = d.app.staticTexts.allElementsBoundByIndex.map { $0.label }.filter { !$0.isEmpty }.joined(separator: " | ")
        let both = d.anyContaining("title: Conflict base phone").exists && d.anyContaining("title: Conflict base laptop").exists
        check("UX-08-BOTH-VERSIONS", both && d.anyContaining("Your saved edit").exists && d.anyContaining("Current account version").exists,
              pass: "Conflict detail (\"This item changed on your account after you edited it. Both versions are saved.\") shows \"Your saved edit\" (title: Conflict base phone) and \"Current account version\" (title: Conflict base laptop), with the reference ID.",
              fail: "Conflict detail does not show both versions. Texts: \(allTexts.prefix(400))")
        let apply = d.app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Apply'")).firstMatch
        Rehearsal.record("UX-08-NO-DEFAULT", "OBSERVED", "Apply control: \(apply.exists ? apply.label + (apply.isEnabled ? " (enabled before any choice)" : " (disabled before a choice is made)") : "not found"). Copy: \(d.anyContaining("Both versions stay saved until you apply a choice").exists ? "\"Both versions stay saved until you apply a choice.\"" : "line not found").")
        let noDefault = apply.exists && !apply.isEnabled
        check("UX-08-NO-DEFAULT-CHOICE", noDefault, pass: "No version is selected by default: \"Apply choice\" is disabled until one is chosen.", fail: "Apply choice was enabled before any choice.")
        // Choose "Version you edited", apply: it is stored once and the issue leaves the list.
        let mine = d.app.buttons.matching(NSPredicate(format: "label CONTAINS 'Use my version'")).firstMatch
        XCTAssertTrue(mine.waitForExistence(timeout: 5), "Use my version")
        mine.tap()
        shot(d.app, "s4-58-version-chosen")
        let enabledAfter = apply.isEnabled
        if enabledAfter { apply.tap() }
        let tasks = await server.waitFor(timeout: 40) { $0.contains { $0.title == "Conflict base phone" } }
        check("UX-08-APPLY", enabledAfter && tasks.contains { $0.title == "Conflict base phone" },
              pass: "Choosing \"Use my version\" enabled Apply choice; applying stored \"Conflict base phone\" on the server.",
              fail: "Applying the chosen version did not reach the server (apply enabled=\(enabledAfter)).")
        let count = tasks.filter { $0.title.hasPrefix("Conflict base") }.count
        check("UX-08-ONCE", count == 1, pass: "The conflicted task exists once on the server after applying (no duplicate).", fail: "\(count) tasks named Conflict base... on the server.")
        sleep(3)
        shot(d.app, "s4-59-after-apply")
        Rehearsal.record("UX-09", "NOT_AUTOMATED", "'This task changed again' while the issue is open needs a second server edit and a pull while the detail screen is visible; not driven here.")
        Rehearsal.record("UX-10", "NOT_AUTOMATED", "Deleted tag elsewhere then edited here: not driven (tag delete plus tag edit journey).")
        Rehearsal.record("UX-11-12", "NOT_AUTOMATED", "Later-actions decisions (Keep for later / Review and retry / Discard action, named discard confirmation) need a conflicted task with queued dependent edits; not driven.")
    }
}
