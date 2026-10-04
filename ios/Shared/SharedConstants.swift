import Foundation

/// Values the app and the widget extension must agree on. Compiled into both
/// targets; the app's `AppConstants` is app-only, so shared code (App Intents,
/// widgets) reads these instead.
///
/// The App Group comes from each target's Info.plist (`BBAppGroupIdentifier`,
/// set from a build setting so TestFlight builds can use their own team's
/// group). Both targets must carry the same value, or the widget and the app
/// open different files.
enum SharedConstants {
    static let fallbackAppGroupID = "group.brainbuddy.ios"

    /// App Group holding the shared store document.
    static let appGroupID: String = {
        let configured = Bundle.main.object(forInfoDictionaryKey: "BBAppGroupIdentifier") as? String
        // An unexpanded "$(SETTING)" means the build setting was never defined.
        guard let configured, !configured.isEmpty, !configured.hasPrefix("$(") else {
            return fallbackAppGroupID
        }
        return configured
    }()

    /// Darwin notification posted after a widget or App Intent writes the
    /// store. The app observes it and calls `Workspace.reloadIfChangedExternally()`.
    static let storeChangedNotification = appGroupID + ".store-changed"

    /// Custom URL scheme the app registers (`CFBundleURLTypes`).
    static let urlScheme = "brainbuddy"

    /// Opens the app on the capture sheet; the app handles it in `.onOpenURL`.
    static let captureURL = URL(string: "\(urlScheme)://capture")!

    /// Open the app on the Next actions and Today tabs (`AppRouter.handle`).
    static let nextURL = URL(string: "\(urlScheme)://next")!
    static let todayURL = URL(string: "\(urlScheme)://today")!
}
