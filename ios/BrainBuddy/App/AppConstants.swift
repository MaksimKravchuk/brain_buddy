import CoreFoundation
import Foundation

/// Identifiers shared by the app, the widget extension and App Intents.
///
/// The App Group and the background task identifier follow the build's
/// bundle and team settings (TestFlight builds use their own), so they are
/// read from the bundle rather than hard-coded. The widget extension derives
/// the same values in `Shared/SharedConstants.swift`; keep the two in step.
enum AppConstants {
    /// Info.plist key holding the App Group identifier.
    static let appGroupInfoKey = "BBAppGroupIdentifier"

    /// The App Group whose container holds the shared store file. Read from
    /// Info.plist `BBAppGroupIdentifier`, falling back to the default group.
    static let appGroupID: String = {
        let fallback = "group.com.brainbuddy.ios"
        guard let value = Bundle.main.object(forInfoDictionaryKey: appGroupInfoKey) as? String else {
            return fallback
        }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        // An unexpanded build setting ("$(BB_APP_GROUP)") is as good as missing.
        guard !trimmed.isEmpty, !trimmed.contains("$(") else { return fallback }
        return trimmed
    }()

    /// Darwin notification posted after any process writes the shared store.
    static let storeChangedNotification = appGroupID + ".store-changed"

    /// `BGAppRefreshTask` identifier. Must also be listed in Info.plist
    /// `BGTaskSchedulerPermittedIdentifiers` (as `$(PRODUCT_BUNDLE_IDENTIFIER).refresh`).
    static let backgroundRefreshTaskID = (Bundle.main.bundleIdentifier ?? "com.brainbuddy.ios") + ".refresh"

    static let defaultServerURL = URL(string: "https://brain-buddy-frontend.fly.dev/api")!

    /// URL scheme handled by `.onOpenURL` (widgets, Shortcuts, Control Center).
    static let urlScheme = "brainbuddy"

    /// Opens the capture sheet. `brainbuddy://capture?list=next` preselects a list.
    static let captureURL = URL(string: "brainbuddy://capture")!

    /// Launch argument that swaps the stored workspace for `Workspace.preview()`
    /// (sample data, nothing written), for UI tests and screenshots.
    static let previewDataLaunchArgument = "-BBUsePreviewData"

    /// Tells every process sharing the store (app, widgets, intents) that the
    /// file changed. Darwin notifications carry no payload.
    static func postStoreChanged() {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(storeChangedNotification as CFString),
            nil,
            nil,
            true
        )
    }
}
