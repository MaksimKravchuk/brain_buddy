import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The voice sheet's chips and the engine behind each (spec 037): Apple first, Whisper on request.
@Suite("Voice language plan")
struct VoiceLanguagePlanTests {
    private static let apple = ["en-US", "en-GB", "de-DE", "ru-RU"]
    private static let whisper: Set<String> = ["en", "de", "ru", "uk", "kk"]

    @Test("037-FR-003 chips are up to three preferred languages, then English, then Auto only with Whisper")
    func the037_FR_003_chips() {
        let without = VoiceLanguagePlan(
            preferredLanguages: ["uk-UA", "ru-RU", "de-DE", "fr-FR"], appleLocales: Self.apple, whisperLanguages: [])
        #expect(without.chips == ["uk", "ru", "de", "en"])
        let with = VoiceLanguagePlan(
            preferredLanguages: ["en-GB", "en-US", "ru_RU"], appleLocales: Self.apple, whisperLanguages: Self.whisper)
        #expect(with.chips == ["en", "ru", VoiceLanguagePlan.auto])
    }

    @Test("037-FR-003 the initial chip is the first one that can be transcribed now")
    func the037_FR_003_initialChip() {
        let plan = VoiceLanguagePlan(preferredLanguages: ["kk-KZ", "ru-RU"], appleLocales: Self.apple, whisperLanguages: [])
        #expect(plan.initial == "ru")
        let none = VoiceLanguagePlan(preferredLanguages: ["kk-KZ"], appleLocales: [], whisperLanguages: [])
        #expect(none.initial == "kk", "with nothing ready the first chip stays, and the sheet offers Whisper")
    }

    @Test("037-FR-004 Apple transcribes what it recognises on device; Whisper the rest, and Auto")
    func the037_FR_004_enginePerLanguage() {
        let plan = VoiceLanguagePlan(preferredLanguages: ["uk-UA", "ru-RU"], appleLocales: Self.apple, whisperLanguages: Self.whisper)
        #expect(plan.engine(for: "ru") == .apple)
        #expect(plan.engine(for: "en") == .apple)
        #expect(plan.engine(for: "uk") == .whisper)
        #expect(plan.engine(for: VoiceLanguagePlan.auto) == .whisper)
        #expect(plan.engine(for: "ja") == nil)
    }

    @Test("037-FR-005 without Whisper a language Apple can't recognise has no engine, and there is no Auto")
    func the037_FR_005_noEngineWithoutWhisper() {
        let plan = VoiceLanguagePlan(preferredLanguages: ["uk-UA"], appleLocales: Self.apple, whisperLanguages: [])
        #expect(plan.engine(for: "uk") == nil)
        #expect(plan.engine(for: VoiceLanguagePlan.auto) == nil)
        #expect(!plan.chips.contains(VoiceLanguagePlan.auto))
    }

    @Test("037-FR-002 Apple recognises in the person's own region when this Mac has it")
    func the037_FR_002_appleLocale() {
        let plan = VoiceLanguagePlan(preferredLanguages: ["en-GB"], appleLocales: Self.apple, whisperLanguages: [])
        #expect(plan.appleLocale(for: "en", preferredLanguages: ["en-GB"]) == "en-GB")
        #expect(plan.appleLocale(for: "en", preferredLanguages: ["en-AU"]) == "en-US")
        #expect(plan.appleLocale(for: "uk", preferredLanguages: ["uk-UA"]) == nil)
    }

    @Test("037-FR-003 language codes and chip titles")
    func the037_FR_003_codesAndTitles() {
        #expect(VoiceLanguagePlan.languageCode("zh-Hans-CN") == "zh")
        #expect(VoiceLanguagePlan.languageCode("en_GB") == "en")
        #expect(VoiceLanguagePlan.title(for: "ru") == "Russian")
        #expect(VoiceLanguagePlan.title(for: VoiceLanguagePlan.auto) == "Auto")
    }
}
