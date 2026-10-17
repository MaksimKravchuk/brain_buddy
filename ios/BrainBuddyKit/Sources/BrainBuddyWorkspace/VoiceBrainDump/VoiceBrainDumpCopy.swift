// The voice sheet's words (spec 031, design.md "Copy" and "State inventory"). English, as the app.

public enum VoiceBrainDumpCopy {
    public static let title = "What feels heaviest?"
    /// "Steps I heard · Not saved yet", drawn as a leading and a trailing part.
    public static let stepsHeading = "Steps I heard"
    public static let notSavedYet = "Not saved yet"
    public static let footer = "Tap a step to edit it. Nothing reaches your lists until you add it."
    public static let empty = "Nothing to add yet."
    public static func add(_ count: Int) -> String { "Add \(count) to Inbox" }
    public static func toast(_ count: Int) -> String { "Added \(count) to Inbox" }
    // Close confirmation.
    public static let discardTitle = "Discard what you said?"
    public static let discardMessage = "Nothing has been added to your lists."
    public static let discard = "Discard"
    public static let keepTalking = "Keep talking"
    // Status words in the glass bar.
    public static let starting = "Starting…"
    public static let listening = "Listening"
    public static let finishing = "Finishing…"
    public static let talkAgain = "Tap to talk again"
    public static let adding = "Adding…"
    // Permission denied and unavailable.
    public static let permissionDenied = "Allow the microphone and speech recognition for Brain Buddy in Settings."
    public static let openSettings = "Open Settings"
    public static func unavailable(_ language: VoiceLanguage) -> String {
        "Speech recognition for \(language.title) isn't available on this iPhone."
    }
    public static func tryLanguage(_ language: VoiceLanguage) -> String { "Try \(language.title)" }
    // Errors shown above the steps; design.md's table has no words for them.
    public static let microphoneUnavailable = "The microphone isn't available right now."
    public static let saveFailed = "Some steps weren't added. Try again."
    // VoiceOver.
    public static let talk = "Talk"
    public static let stopListening = "Stop listening"
    public static let edit = "Edit"
    public static func remove(_ title: String) -> String { "Remove \(title)" }
}
