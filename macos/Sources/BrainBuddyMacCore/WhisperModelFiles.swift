import Foundation

/// Where the optional Whisper model lives and whether it is whole (spec 037). Files only, no
/// network: the download itself is `WhisperDownload` in the app target, which fills `staging`
/// and calls `install(modelFolder:)` only once everything arrived (037-FR-007).
package struct WhisperModelFiles: Sendable {
    /// The one model offered (D1): WhisperKit's Core ML build of OpenAI's Whisper base.
    package static let variant = "openai_whisper-base"
    /// About 145 MB; shown before the download starts.
    package static let approximateMegabytes = 145
    static let marker = "installed.json"

    /// The installed model's root: `<data folder>/Whisper/`.
    package let root: URL
    /// The download's working folder; replaced, never merged, so a cancel leaves nothing half-done.
    package let staging: URL

    /// This Mac's install: beside `store.json`, in the folder `MacHostConfiguration` picks.
    package static var current: WhisperModelFiles {
        let directory = (try? MacHostConfiguration.fromEnvironment())?.directory ?? MacHostConfiguration.defaultDirectory
        return WhisperModelFiles(dataDirectory: directory)
    }

    package init(dataDirectory: URL) {
        root = dataDirectory.appendingPathComponent("Whisper", isDirectory: true)
        staging = dataDirectory.appendingPathComponent("Whisper.partial", isDirectory: true)
    }

    /// The model folder of a complete install, or `nil` when there is none (or it was damaged).
    package var modelFolder: URL? {
        guard let data = try? Data(contentsOf: root.appendingPathComponent(Self.marker)),
              let record = try? JSONDecoder().decode(Installed.self, from: data)
        else { return nil }
        let folder = root.appendingPathComponent(record.model, isDirectory: true)
        let files = FileManager.default
        let parts = ["AudioEncoder.mlmodelc", "MelSpectrogram.mlmodelc", "TextDecoder.mlmodelc"]
        guard parts.allSatisfy({ files.fileExists(atPath: folder.appendingPathComponent($0).path) }),
              files.fileExists(atPath: tokenizerFile(in: root).path)
        else { return nil }
        return folder
    }

    /// The folder WhisperKit searches for the tokenizer: the root, in Hugging Face's layout.
    package var tokenizerFolder: URL { root }

    package var isInstalled: Bool { modelFolder != nil }

    /// Empties `staging` before a download starts.
    package func prepareStaging() throws {
        try discardStaging()
        try FileManager.default.createDirectory(at: staging, withIntermediateDirectories: true)
    }

    /// Removes whatever a cancelled or failed download left.
    package func discardStaging() throws {
        if FileManager.default.fileExists(atPath: staging.path) { try FileManager.default.removeItem(at: staging) }
    }

    /// Makes the finished download in `staging` the installed model. `modelFolder` is the folder the
    /// download reported, inside `staging`. Throws, leaving the old state, when anything is missing.
    package func install(modelFolder: URL) throws {
        let base = staging.standardizedFileURL.path + "/"
        let path = modelFolder.standardizedFileURL.path
        guard path.hasPrefix(base) else { throw Problem.outsideStaging }
        guard FileManager.default.fileExists(atPath: tokenizerFile(in: staging).path) else { throw Problem.incomplete }
        let record = Installed(model: String(path.dropFirst(base.count)))
        try JSONEncoder().encode(record).write(to: staging.appendingPathComponent(Self.marker))
        try remove()
        try FileManager.default.moveItem(at: staging, to: root)
        guard isInstalled else {
            try? remove()
            throw Problem.incomplete
        }
    }

    /// Deletes the installed model (037-FR-008).
    package func remove() throws {
        if FileManager.default.fileExists(atPath: root.path) { try FileManager.default.removeItem(at: root) }
    }

    private func tokenizerFile(in base: URL) -> URL {
        base.appendingPathComponent("models/openai/whisper-base/tokenizer.json")
    }

    package enum Problem: Error, Equatable {
        case outsideStaging, incomplete
    }

    private struct Installed: Codable {
        let model: String
    }
}
