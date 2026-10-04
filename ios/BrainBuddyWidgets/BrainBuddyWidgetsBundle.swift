import SwiftUI
import WidgetKit

/// The widget extension's entry point: Home Screen and Lock Screen widgets and
/// the Control Center capture control. Everything here reads the App Group
/// store with sync off, and writes only through App Intents.
@main
struct BrainBuddyWidgetsBundle: WidgetBundle {
    var body: some Widget {
        NextActionsWidget()
        InboxWidget()
        CaptureControl()
    }
}
