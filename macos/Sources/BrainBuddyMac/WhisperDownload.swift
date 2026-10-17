import BrainBuddyMacCore
import Combine
import Foundation
// `@preconcurrency` for the same reason as in VoiceCapture.swift: WhisperKit 0.18.0's API has no
// `Sendable` annotations. Only its static functions are called here, from `fetch`, off the main
// actor; only a URL and the progress fraction come back.
@preconcurrency import WhisperKit

/// The optional Whisper download (037-FR-006, -007, -008, -009). This is the only file that asks
/// WhisperKit to fetch anything: the model from `argmaxinc/whisperkit-coreml` and its tokenizer from
/// `openai/whisper-base` on Hugging Face. It starts only from the Download button, carries no audio
/// and no text, and installs the model only once every file arrived.
@MainActor
final class WhisperDownload: ObservableObject {
    enum State: Equatable {
        case notDownloaded
        case downloading(fraction: Double)
        case downloaded
        case failed(String)
    }

    /// One per app, shared by Settings › Voice and the voice sheet.
    static let shared = WhisperDownload(files: .current)

    @Published private(set) var state: State
    /// True after Cancel until the download task has stopped and its files are gone.
    @Published private(set) var cancelling = false
    let files: WhisperModelFiles
    private var task: Task<Void, Never>?

    init(files: WhisperModelFiles) {
        self.files = files
        state = files.isInstalled ? .downloaded : .notDownloaded
    }

    func start() {
        guard task == nil else { return }
        state = .downloading(fraction: 0)
        let files = files
        task = Task { [weak self] in
            let outcome: State
            do {
                try files.prepareStaging()
                let model = try await Self.fetch(into: files) { [weak self] fraction in
                    Task { @MainActor [weak self] in self?.progressed(fraction) }
                }
                try Task.checkCancellation()
                try files.install(modelFolder: model)
                outcome = .downloaded
            } catch {
                try? files.discardStaging()
                outcome = Task.isCancelled ? .notDownloaded : .failed(error.localizedDescription)
            }
            self?.finished(outcome)
        }
    }

    /// Fetches the model, then the tokenizer, into `files.staging` and returns the model folder.
    /// Off the main actor, so WhisperKit's non-`Sendable` callback and tokenizer never cross into it;
    /// only the progress fraction (a `Double`) does.
    nonisolated private static func fetch(
        into files: WhisperModelFiles, progress: @escaping @Sendable (Double) -> Void
    ) async throws -> URL {
        let model = try await WhisperKit.download(variant: WhisperModelFiles.variant, downloadBase: files.staging) {
            progress($0.fractionCompleted)
        }
        try Task.checkCancellation()
        _ = try await ModelUtilities.loadTokenizer(for: .base, tokenizerFolder: files.staging)
        return model
    }

    func cancel() {
        guard let task else { return }
        cancelling = true
        task.cancel()
    }

    func remove() {
        guard task == nil else { return }
        do {
            try files.remove()
            state = .notDownloaded
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func progressed(_ fraction: Double) {
        guard case .downloading = state, !cancelling else { return }
        state = .downloading(fraction: min(max(fraction, 0), 1))
    }

    private func finished(_ outcome: State) {
        task = nil
        cancelling = false
        state = files.isInstalled ? .downloaded : (outcome == .downloaded ? .failed("The download was incomplete.") : outcome)
    }
}

/// Lets the voice sheet's "Download in Settings…" bring Settings › Voice forward, whether the
/// Settings window is open or not (it reads the request when it appears or is told).
@MainActor
enum VoiceSettingsRoute {
    static let notification = Notification.Name("BrainBuddyMac.openVoiceSettings")
    private static var pending = false

    static func request() {
        pending = true
        NotificationCenter.default.post(name: notification, object: nil)
    }

    static func consume() -> Bool {
        defer { pending = false }
        return pending
    }
}
