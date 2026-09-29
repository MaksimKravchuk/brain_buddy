import AppIntents

/// App Shortcuts: available in Siri, Spotlight, Shortcuts and the Action
/// button as soon as the app is installed. App target only; the intents
/// themselves live in `Shared/` so widgets and controls can run them too.
nonisolated struct BrainBuddyShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: CaptureTaskIntent(),
            phrases: [
                "Add a task to \(.applicationName)",
                "Capture in \(.applicationName)",
                "Add a task to \(\.$list) in \(.applicationName)",
            ],
            shortTitle: "Add a task",
            systemImageName: "plus.circle"
        )
        AppShortcut(
            intent: CompleteTaskIntent(),
            phrases: [
                "Complete a task in \(.applicationName)",
            ],
            shortTitle: "Complete a task",
            systemImageName: "checkmark.circle"
        )
        AppShortcut(
            intent: OpenCaptureIntent(),
            phrases: [
                "Open capture in \(.applicationName)",
            ],
            shortTitle: "Open capture",
            systemImageName: "square.and.pencil"
        )
    }
}
