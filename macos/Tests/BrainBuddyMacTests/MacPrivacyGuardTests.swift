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
            #expect(text.contains("download: false"), "the speech model is the bundled one, never downloaded")
            #expect(!text.contains("download: true"))
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
}
