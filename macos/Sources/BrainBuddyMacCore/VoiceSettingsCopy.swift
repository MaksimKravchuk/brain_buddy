/// The words of Settings › Voice (design S-05) and the voice sheet's new notes (V-01c, V-01f).
package enum VoiceSettingsCopy {
    package static let tabName = "Voice"
    package static let speechLabel = "Speech"
    package static let speechValue = "Apple speech recognition, on this Mac"
    package static let whisperLabel = "Whisper"
    package static let notDownloaded = "Not downloaded"
    package static let downloaded = "Downloaded"
    package static let whisperDetail =
        "For languages Apple doesn't recognise on this Mac, and Auto. About \(WhisperModelFiles.approximateMegabytes) MB from Hugging Face. What you say never leaves this Mac."
    package static let download = "Download"
    package static let cancel = "Cancel"
    package static let remove = "Remove"
    package static let tryAgain = "Try again"
    package static let openSettings = "Download in Settings…"

    package static func downloading(percent: Int) -> String { "Downloading… \(percent)%" }
    package static func failed(_ reason: String) -> String { "Couldn't download Whisper: \(reason)" }

    /// V-01c: the chosen language has no recogniser on this Mac yet.
    package static func needsWhisper(_ language: String) -> String {
        "\(language) needs Whisper, a free speech model you can download (about \(WhisperModelFiles.approximateMegabytes) MB)."
    }

    /// V-01f: the person declined, or restricted, speech recognition.
    package static let speechNotAllowed =
        "Speech recognition is off for Brain Buddy. Turn it on in System Settings › Privacy & Security › Speech Recognition."
}
