import Foundation

/// Every F- string of the 029 design (§ Copy), so views and tests read one source (029-FR-031).
package enum FirstRunCopy {
    // F-01 welcome
    package static let appName = "Carry On"
    package static let heading = "What feels heaviest?"
    package static let intro = "Write it as it is and press Return. It goes to the Inbox; you sort it in a moment."
    package static let placeholder = "Type, or press the mic to speak"
    package static let hotkeyHint = "Capture from any app, without switching to Carry On."
    package static let hotkeyUnavailable = "⌃⌥⇧B is unavailable. Use File › Quick Capture."
    package static let speechHint = "Speech becomes text on this Mac. It asks for the microphone the first time."
    package static let noAccount = "No account needed. Your tasks stay on this Mac until you sign in."
    package static let typingLine = "Goes to Inbox, as you wrote it"
    package static let typingKeys = "Return to add · Esc to skip"
    // F-02 first step
    package static let listHeader = "1 thing to sort"
    package static let inspectorHeader = "Inbox · 1 of 1"
    package static let question = "What is the first step you could take?"
    package static let helper = "Small enough to start today. Not sure yet? Leave it in the Inbox."
    package static let makeNextStep = "Make it my next step"
    package static let notYet = "Not yet"
    // F-03 landing
    package static let landingHeader = "Next actions · 1 step"
    package static let nowLabel = "Now"
    package static let gotIt = "Got it"
    // F-04 sidebar footer (existing words)
    package static let sidebarFooter = "On this Mac · Sign in to sync"

    private static let tipStart = "This is your next step. When it is done, press Done. Anything else on your mind: ⌘N here"
    private static let tipEnd = "⌘O finds any step."

    /// F-03.01 / F-03.02: the ⌃⌥⇧B clause only when the shortcut is registered.
    package static func landingTip(hotkeyAvailable: Bool) -> String {
        "\(tipStart)\(hotkeyAvailable ? ", or ⌃⌥⇧B from any app" : ""). \(tipEnd)"
    }
}
