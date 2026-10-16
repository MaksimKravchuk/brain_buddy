import XCTest

extension XCUIElement {
    /// The label, or a marker when the element is not on screen (reading `label` of a missing element fails the test).
    var safeLabel: String { exists ? label : "(absent)" }
}

/// Navigation and entry helpers. Elements are found by their visible copy; the app has no
/// accessibility identifiers for these screens and none were added for the rehearsal.
@MainActor
struct Driver {
    let app: XCUIApplication

    /// Launches the app with the Rust runtime pilot switch on (a `UserDefaults` argument, the same
    /// switch Settings > Pilot flips) and closes the first-run Weekly Review explainer if it shows.
    static func launch(pilot: Bool = true, extraArguments: [String] = []) -> Driver {
        let app = XCUIApplication()
        // An explicit NO, because the switch is a persisted default: it must not leak between runs.
        app.launchArguments += ["-BBRustRuntimePilot", pilot ? "YES" : "NO"] + extraArguments
        app.launch()
        let driver = Driver(app: app)
        driver.dismissExplainer()
        return driver
    }

    func dismissExplainer() {
        let gotIt = app.buttons["Got it"]
        if gotIt.waitForExistence(timeout: 12) { gotIt.tap() }
        _ = app.tabBars.buttons["Lists"].waitForExistence(timeout: 10)
    }

    func text(_ label: String) -> XCUIElement { app.staticTexts[label] }

    func textContaining(_ part: String) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", part)).firstMatch
    }

    /// Anything on screen (static text, button, alert text) whose label contains `part`.
    func anyContaining(_ part: String) -> XCUIElement {
        app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS %@", part)).firstMatch
    }

    func tab(_ name: String) {
        let button = app.tabBars.buttons[name]
        // The tab bar collapses while a list is scrolled; scrolling back up restores it.
        for _ in 0..<3 where !button.exists || !button.isHittable { app.collectionViews.firstMatch.swipeDown() }
        button.tap()
    }

    func openSettings() {
        tab("Lists")
        let settings = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Settings'")).firstMatch
        for _ in 0..<6 where !settings.isHittable { app.collectionViews.firstMatch.swipeUp() }
        settings.tap()
        _ = app.navigationBars["Settings"].waitForExistence(timeout: 5)
    }

    /// Leaves Settings (or any pushed screen) with the back button, or closes
    /// the task sheet with its Close button.
    func back() {
        let close = app.navigationBars.buttons["Close"].firstMatch
        if close.exists {
            close.tap()
            return
        }
        let button = app.navigationBars.buttons.firstMatch
        if button.exists { button.tap() }
    }

    /// Scrolls the visible list until `element` is hittable.
    func reveal(_ element: XCUIElement, maxSwipes: Int = 6) {
        for _ in 0..<maxSwipes where !element.exists || !element.isHittable {
            let scrollable = app.collectionViews.firstMatch.exists ? app.collectionViews.firstMatch : app.scrollViews.firstMatch
            scrollable.swipeUp()
        }
    }

    /// The Settings > Sync "Status" value, e.g. "Synced just now".
    func syncStatusText() -> String? {
        let row = app.descendants(matching: .any).matching(NSPredicate(format: "label BEGINSWITH 'Status'")).firstMatch
        return row.exists ? row.label : nil
    }

    // MARK: Sign in

    /// Settings > Sign in > Advanced > server address > password sign-in.
    func signIn(_ account: Rehearsal.Account, server: String = Rehearsal.api) {
        openSettings()
        app.buttons["Sign in"].firstMatch.tap()
        let advanced = app.buttons["Advanced"]
        XCTAssertTrue(advanced.waitForExistence(timeout: 10), "sign-in sheet")
        if !app.textFields["Server address"].exists { advanced.tap() }
        let address = app.textFields["Server address"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        address.coordinate(withNormalizedOffset: CGVector(dx: 0.98, dy: 0.5)).tap()
        let current = (address.value as? String) ?? ""
        address.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: current.count) + server)
        app.buttons["Use your password"].tap()
        let email = app.textFields["Email"]
        XCTAssertTrue(email.waitForExistence(timeout: 5))
        email.tap()
        email.typeText(account.email)
        let password = app.secureTextFields["Password"]
        password.tap()
        password.typeText(account.password)
        app.buttons.matching(NSPredicate(format: "label == 'Sign in'")).allElementsBoundByIndex.first(where: \.isHittable)?.tap()
    }

    func signOutKeepingNothing() {
        openSettings()
        let signOut = app.buttons["Sign out"]
        reveal(signOut)
        signOut.tap()
        let confirm = app.buttons["Sign out"].exists ? app.sheets.buttons["Sign out"] : app.buttons["Sign out and remove"]
        if confirm.waitForExistence(timeout: 5) { confirm.tap() }
    }

    // MARK: Capture

    var captureButton: XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Add to inbox'")).firstMatch
    }

    /// Adds a task to the Inbox through the capture accessory.
    func capture(_ title: String, slowly: Bool = true) {
        captureButton.tap()
        let input = app.textViews.firstMatch.waitForExistence(timeout: 5) ? app.textViews.firstMatch : app.textFields.firstMatch
        XCTAssertTrue(input.waitForExistence(timeout: 5), "capture input")
        Thread.sleep(forTimeInterval: 1)
        if slowly { typeSlowly(input, title) } else { input.typeText(title) }
        Thread.sleep(forTimeInterval: 0.5)
        input.typeText("\n")
        XCTAssertTrue(anyContaining("Added").waitForExistence(timeout: 8), "capture confirmed 'Added'")
        app.buttons["Close"].firstMatch.tap()
    }

    /// One keystroke at a time. Fast `typeText` into the capture field loses characters (see the
    /// rehearsal report), so everything that needs an exact title types like this.
    func typeSlowly(_ element: XCUIElement, _ text: String) {
        for character in text {
            element.typeText(String(character))
            Thread.sleep(forTimeInterval: 0.15)
        }
    }

    /// Polls the screen until some element's label contains `part`.
    func waitFor(_ part: String, timeout: TimeInterval = 20) -> Bool {
        anyContaining(part).waitForExistence(timeout: timeout)
    }

    /// The row button of a task in the visible list.
    func row(_ title: String) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label == %@", title)).firstMatch
    }
}
