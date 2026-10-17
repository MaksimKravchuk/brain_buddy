import Foundation

/// Which recogniser turns a recording into text (spec 037).
package enum VoiceEngine: Equatable, Sendable {
    /// Apple's speech recognition with on-device recognition required.
    case apple
    /// The optional Whisper model the person downloaded.
    case whisper
}

/// The voice sheet's language chips and the engine behind each one (037-FR-003, -004, -005).
/// Pure: the sheet supplies what this Mac can recognise, so the rules are tested without a Mac.
package struct VoiceLanguagePlan: Equatable, Sendable {
    /// The chip that lets Whisper detect the language.
    package static let auto = "auto"

    /// Language codes in chip order ("ru", "en", …), then `auto` while Whisper is downloaded.
    package let chips: [String]
    /// The chip chosen when the sheet opens: the first one that can be transcribed now.
    package let initial: String

    private let appleLocales: [String]
    private let whisperLanguages: Set<String>

    /// - Parameters:
    ///   - preferredLanguages: the person's languages in order, as `Locale.preferredLanguages` gives them.
    ///   - appleLocales: locale identifiers Apple recognises on device on this Mac ("en-US", "ru-RU", …).
    ///   - whisperLanguages: Whisper's language codes; empty when Whisper is not downloaded.
    package init(preferredLanguages: [String], appleLocales: [String], whisperLanguages: Set<String>) {
        self.appleLocales = appleLocales
        self.whisperLanguages = whisperLanguages
        var codes: [String] = []
        for identifier in preferredLanguages {
            let code = Self.languageCode(identifier)
            if !code.isEmpty, !codes.contains(code) { codes.append(code) }
            if codes.count == 3 { break }
        }
        if !codes.contains("en") { codes.append("en") }
        if !whisperLanguages.isEmpty { codes.append(Self.auto) }
        chips = codes
        let ready = { (code: String) in Self.engine(code, appleLocales: appleLocales, whisper: whisperLanguages) != nil }
        initial = codes.first(where: ready) ?? codes[0]
    }

    /// The engine that transcribes `code`, or `nil` when neither can (the sheet then offers Whisper).
    package func engine(for code: String) -> VoiceEngine? {
        Self.engine(code, appleLocales: appleLocales, whisper: whisperLanguages)
    }

    /// The Apple locale to recognise `code` with: the person's own region first ("ru-RU" for a
    /// person whose list says "ru-RU"), else the first on-device locale of that language.
    package func appleLocale(for code: String, preferredLanguages: [String]) -> String? {
        let candidates = appleLocales.filter { Self.languageCode($0) == code }
        let normalized = preferredLanguages.map { $0.replacingOccurrences(of: "_", with: "-") }
        for preferred in normalized where Self.languageCode(preferred) == code {
            if let match = candidates.first(where: { $0.replacingOccurrences(of: "_", with: "-") == preferred }) {
                return match
            }
        }
        return candidates.first
    }

    private static func engine(_ code: String, appleLocales: [String], whisper: Set<String>) -> VoiceEngine? {
        if code == auto { return whisper.isEmpty ? nil : .whisper }
        if appleLocales.contains(where: { languageCode($0) == code }) { return .apple }
        return whisper.contains(code) ? .whisper : nil
    }

    /// "ru-RU" → "ru", "zh-Hans-CN" → "zh", "en_GB" → "en".
    package static func languageCode(_ identifier: String) -> String {
        String(identifier.split(whereSeparator: { $0 == "-" || $0 == "_" }).first ?? "").lowercased()
    }

    /// The chip's title in the app's language (English): "Russian", "English", "Auto".
    package static func title(for code: String) -> String {
        if code == auto { return "Auto" }
        return Locale(identifier: "en").localizedString(forLanguageCode: code) ?? code
    }
}
