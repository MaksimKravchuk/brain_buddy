import AppKit
import SwiftUI

@main
struct BrainBuddyMacApp: App {
    init() {
        NSApplication.shared.setActivationPolicy(.regular)
    }

    var body: some Scene {
        Window("Brain Buddy", id: "main") {
            ContentView()
                .frame(minWidth: 720, minHeight: 480)
        }
        .defaultSize(width: 960, height: 640)
    }
}
