import Foundation
import Testing

/// Voice stays on this Mac (contracts/mac-app-host.md §8; FR-029, FR-010): the voice sources, where
/// the `VoiceTranscriber` actor runs WhisperKit, have no way to reach a network.
@Suite("Privacy guard")
struct MacPrivacyGuardTests {
    static let voiceSources = ["BrainBuddyMac/VoiceCapture.swift"]
    static let networkReach = ["URLSession", "import Network", "BrainBuddyAPI", "BrainBuddySync", "URLRequest", "NWConnection"]

    static func source(_ name: String) throws -> String {
        try String(contentsOf: MacPresentationGuardTests.sourcesRoot.appendingPathComponent(name), encoding: .utf8)
    }

    @Test("021-FR-029 021-FR-010 the voice sources and the VoiceTranscriber actor contain no network API")
    func voiceSourcesHaveNoNetwork() throws {
        for name in Self.voiceSources {
            let text = try Self.source(name)
            #expect(text.contains("actor VoiceTranscriber"), "\(name) holds the transcriber")
            for token in Self.networkReach {
                #expect(!text.contains(token), "\(name) contains \(token)")
            }
            #expect(text.contains("download: false"), "transcription never fetches a model")
            #expect(!text.contains("download: true"))
            #expect(!text.contains("WhisperKit.download"), "the optional download lives in WhisperDownload.swift")
        }
        // Nothing else declares the transcriber, so the check above covers it wherever it is.
        let others = try MacPresentationGuardTests.sources().filter { !Self.voiceSources.contains($0.name) }
        #expect(others.allSatisfy { !$0.text.contains("actor VoiceTranscriber") })
    }

    @Test("021-FR-029 the guard catches a network call seeded into a scratch copy of the voice source")
    func seededNetworkCallFails() throws {
        let text = try Self.source(Self.voiceSources[0])
        for seed in ["\nlet session = URLSession.shared\n", "\nimport Network\n", "\nimport BrainBuddyAPI\n"] {
            let copy = text + seed
            #expect(Self.networkReach.contains { copy.contains($0) })
        }
    }

    @Test("037-FR-009 only WhisperDownload.swift fetches anything, and only the Whisper model")
    func the037_FR_009_downloadIsIsolated() throws {
        let download = try Self.source("BrainBuddyMac/WhisperDownload.swift")
        #expect(download.contains("WhisperKit.download("))
        #expect(download.contains("variant: WhisperModelFiles.variant"))
        for token in Self.networkReach {
            #expect(!download.contains(token), "WhisperDownload.swift contains \(token)")
        }
        for banned in ["AVAudio", "recording", "transcribe("] {
            #expect(!download.contains(banned), "the download touches no audio or text: \(banned)")
        }
        let others = try MacPresentationGuardTests.sources().filter { $0.name != "BrainBuddyMac/WhisperDownload.swift" }
        #expect(others.allSatisfy { !$0.text.contains("WhisperKit.download(") && !$0.text.contains("loadTokenizer(") })
    }

    @Test("037-FR-001 037-SC-001 the app bundle carries no speech model")
    func the037_FR_001_noBundledModel() throws {
        let script = try String(
            contentsOf: MacPresentationGuardTests.sourcesRoot.deletingLastPathComponent().appendingPathComponent("build_app.sh"),
            encoding: .utf8)
        #expect(!script.contains(".mlmodelc"))
        #expect(!script.contains("WHISPERKIT_MODEL_SOURCE"))
        #expect(!script.contains("tokenizer.json"))
    }

    @Test("037-FR-010 the recording is deleted after transcription, discard or close, whichever engine ran")
    func the037_FR_010_recordingIsDeleted() throws {
        let text = try Self.source(Self.voiceSources[0])
        let stop = try #require(text.range(of: "func stopAndTranscribe"))
        let rest = text[stop.lowerBound...]
        let engines = try #require(rest.range(of: "switch plan.engine(for: language)"))
        let cleanup = try #require(rest.range(of: "try? FileManager.default.removeItem(at: url)"))
        #expect(rest[..<engines.lowerBound].contains("defer {"), "the delete is deferred before either engine runs")
        #expect(cleanup.lowerBound < engines.lowerBound)
        #expect(text.contains("if let recordingURL { try? FileManager.default.removeItem(at: recordingURL) }"))
    }
}
