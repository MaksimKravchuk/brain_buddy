import AppIntents
import SwiftUI
import WidgetKit

/// Control Center, Lock Screen and Action button control that opens the app
/// on the capture sheet. `OpenCaptureIntent` is compiled into the app as well,
/// as controls that open their app require.
struct CaptureControl: ControlWidget {
    static let kind = "brainbuddy.ios.control.capture"

    var body: some ControlWidgetConfiguration {
        StaticControlConfiguration(kind: Self.kind) {
            ControlWidgetButton(action: OpenCaptureIntent()) {
                Label("Capture", systemImage: "square.and.pencil")
            }
        }
        .displayName("Capture")
        .description("Open Brain Buddy ready to capture a task.")
    }
}
