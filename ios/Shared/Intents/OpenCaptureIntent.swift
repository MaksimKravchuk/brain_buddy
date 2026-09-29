import AppIntents
import Foundation

/// Opens the app on the capture sheet. Used by the Control Center control, the
/// Action button and Shortcuts.
///
/// `openAppWhenRun` brings the app forward and runs `perform` in the app's
/// process (the intent is compiled into the app as well as the widget
/// extension, as controls that open the app require). `perform` then opens
/// `brainbuddy://capture`, which the app routes to the capture sheet in
/// `.onOpenURL`, so every entry point shares one deep link.
nonisolated struct OpenCaptureIntent: AppIntent {
    static let title: LocalizedStringResource = "Open capture"

    static let description = IntentDescription("Opens Brain Buddy ready to capture a task.")

    static let openAppWhenRun: Bool = true

    init() {}

    func perform() async throws -> some IntentResult & OpensIntent {
        .result(opensIntent: OpenURLIntent(SharedConstants.captureURL))
    }
}
