import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The optional Whisper model's files (spec 037): whole or absent, never half-installed.
@Suite("Whisper model files")
struct WhisperModelFilesTests {
    private let data: URL
    private let files: WhisperModelFiles

    init() throws {
        data = FileManager.default.temporaryDirectory.appendingPathComponent("bb-whisper-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: data, withIntermediateDirectories: true)
        files = WhisperModelFiles(dataDirectory: data)
    }

    /// Writes what a finished download leaves in `staging` and returns the model folder it reports.
    private func fillStaging(tokenizer: Bool = true, parts: [String]? = nil) throws -> URL {
        try files.prepareStaging()
        let model = files.staging.appendingPathComponent(
            "models/argmaxinc/whisperkit-coreml/\(WhisperModelFiles.variant)", isDirectory: true)
        for part in parts ?? ["AudioEncoder.mlmodelc", "MelSpectrogram.mlmodelc", "TextDecoder.mlmodelc"] {
            let folder = model.appendingPathComponent(part, isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try Data("x".utf8).write(to: folder.appendingPathComponent("coremldata.bin"))
        }
        if tokenizer {
            let folder = files.staging.appendingPathComponent("models/openai/whisper-base", isDirectory: true)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            try Data("{}".utf8).write(to: folder.appendingPathComponent("tokenizer.json"))
        }
        return model
    }

    @Test("037-FR-001 037-FR-007 nothing is installed until a complete download is moved into place")
    func the037_FR_007_installsOnlyWhole() throws {
        #expect(!files.isInstalled)
        let model = try fillStaging()
        #expect(!files.isInstalled, "staging alone is not an install")
        try files.install(modelFolder: model)
        #expect(files.isInstalled)
        #expect(files.modelFolder?.lastPathComponent == WhisperModelFiles.variant)
        #expect(files.tokenizerFolder == files.root)
        #expect(!FileManager.default.fileExists(atPath: files.staging.path))
    }

    @Test("037-FR-007 a download missing its tokenizer or a model part is refused and installs nothing")
    func the037_FR_007_refusesIncomplete() throws {
        let noTokenizer = try fillStaging(tokenizer: false)
        #expect(throws: WhisperModelFiles.Problem.incomplete) { try files.install(modelFolder: noTokenizer) }
        #expect(!files.isInstalled)
        let noDecoder = try fillStaging(parts: ["AudioEncoder.mlmodelc", "MelSpectrogram.mlmodelc"])
        #expect(throws: WhisperModelFiles.Problem.incomplete) { try files.install(modelFolder: noDecoder) }
        #expect(!files.isInstalled)
    }

    @Test("037-FR-007 a folder outside staging is never installed")
    func the037_FR_007_outsideStaging() throws {
        _ = try fillStaging()
        #expect(throws: WhisperModelFiles.Problem.outsideStaging) {
            try files.install(modelFolder: data.appendingPathComponent("elsewhere"))
        }
    }

    @Test("037-FR-007 a cancelled or failed download leaves no partial files")
    func the037_FR_007_discardStaging() throws {
        _ = try fillStaging()
        try files.discardStaging()
        #expect(!FileManager.default.fileExists(atPath: files.staging.path))
        #expect(!files.isInstalled)
    }

    @Test("037-FR-008 Remove deletes the downloaded model")
    func the037_FR_008_remove() throws {
        try files.install(modelFolder: try fillStaging())
        try files.remove()
        #expect(!files.isInstalled)
        #expect(!FileManager.default.fileExists(atPath: files.root.path))
    }

    @Test("037-FR-006 the copy states the size and that speech stays on this Mac")
    func the037_FR_006_copy() {
        #expect(VoiceSettingsCopy.whisperDetail.contains("\(WhisperModelFiles.approximateMegabytes) MB"))
        #expect(VoiceSettingsCopy.whisperDetail.contains("never leaves this Mac"))
        #expect(VoiceSettingsCopy.needsWhisper("Ukrainian").hasPrefix("Ukrainian needs Whisper"))
        #expect(VoiceSettingsCopy.downloading(percent: 42) == "Downloading… 42%")
    }
}
