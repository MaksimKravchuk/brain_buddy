import AppKit
import AVFoundation
import BrainBuddyDesign
import SwiftUI
// `@preconcurrency`, documented as research R2 asks: WhisperKit 0.18.0 declares `WhisperKit` as an
// `open class` with no `Sendable` conformance and no isolation, so every `await` on it from an actor
// is reported as sending a non-Sendable value. It is safe here because the one instance is created,
// held and called only inside `VoiceTranscriber`, never escapes it, and `VoiceTranscriber` refuses a
// second transcription while one is running, so the instance is never used by two tasks at once.
@preconcurrency import WhisperKit

/// Why a recording could not become text, in the words the sheet shows.
struct VoiceCaptureError: LocalizedError {
    let message: String
    var errorDescription: String? { message }

    static let modelMissing = VoiceCaptureError(message: "The local speech model is missing from this app.")
    static let microphone = VoiceCaptureError(message: "The microphone could not start recording.")
    static let busy = VoiceCaptureError(message: "Wait for the current transcription to finish.")
}

/// The only place WhisperKit runs (research R2): the model loads once, on first use, and
/// transcribes one recording at a time on this Mac. Nothing leaves the device.
actor VoiceTranscriber {
    private var whisper: WhisperKit?
    private var isTranscribing = false

    /// Whether the next `transcribe` loads the model first.
    var needsModel: Bool { whisper == nil }

    /// The bundled model and tokenizer folders, or `nil` when the app was built without them.
    nonisolated static func bundledModel(in bundle: Bundle = .main) -> (model: URL, tokenizer: URL)? {
        guard let resources = bundle.resourceURL else { return nil }
        let speech = resources.appendingPathComponent("Whisper", isDirectory: true)
        let model = speech.appendingPathComponent("openai_whisper-base", isDirectory: true)
        let tokenizer = speech.appendingPathComponent("whisper-base", isDirectory: true)
        let files = FileManager.default
        guard files.fileExists(atPath: model.path),
              files.fileExists(atPath: tokenizer.appendingPathComponent("tokenizer.json").path)
        else { return nil }
        return (model, tokenizer)
    }

    /// Transcribes the recording at `audio`; `language` is a Whisper language code, or `nil` to detect it.
    func transcribe(audio: URL, language: String?, model: URL, tokenizer: URL) async throws -> String {
        guard !isTranscribing else { throw VoiceCaptureError.busy }
        isTranscribing = true
        defer { isTranscribing = false }
        let whisper = try await loadedModel(model: model, tokenizer: tokenizer)
        let options = DecodingOptions(task: .transcribe, language: language)
        let segments = try await whisper.transcribe(audioPath: audio.path, decodeOptions: options)
        return segments.map(\.text).joined(separator: " ").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func loadedModel(model: URL, tokenizer: URL) async throws -> WhisperKit {
        if let whisper { return whisper }
        let loaded = try await WhisperKit(WhisperKitConfig(modelFolder: model.path, tokenizerFolder: tokenizer, download: false))
        whisper = loaded
        return loaded
    }
}

@MainActor
final class VoiceCaptureModel: ObservableObject {
    @Published var recording = false
    @Published var transcribing = false
    @Published var preparingModel = false
    @Published var transcript = ""
    @Published var error: String?

    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private let transcriber = VoiceTranscriber()

    func start() async {
        error = nil
        let permitted = await AVCaptureDevice.requestAccess(for: .audio)
        guard permitted else {
            error = "Microphone access is required to record."
            return
        }
        do {
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("brainbuddy-\(UUID().uuidString).wav")
            let settings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 16_000.0,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
            let newRecorder = try AVAudioRecorder(url: url, settings: settings)
            guard newRecorder.record() else { throw VoiceCaptureError.microphone }
            recorder = newRecorder
            recordingURL = url
            transcript = ""
            recording = true
        } catch {
            self.error = error.localizedDescription
        }
    }

    func stopAndTranscribe(language: String) async {
        guard recording, let url = recordingURL else { return }
        recorder?.stop()
        recorder = nil
        recording = false
        recordingURL = nil
        transcribing = true
        preparingModel = await transcriber.needsModel
        error = nil
        defer {
            transcribing = false
            preparingModel = false
            try? FileManager.default.removeItem(at: url)
        }
        do {
            guard let bundled = VoiceTranscriber.bundledModel() else { throw VoiceCaptureError.modelMissing }
            transcript = try await transcriber.transcribe(
                audio: url, language: language == "auto" ? nil : language,
                model: bundled.model, tokenizer: bundled.tokenizer
            )
        } catch {
            self.error = error.localizedDescription
        }
    }

    func cancel() {
        recorder?.stop()
        recorder = nil
        recording = false
        if let recordingURL { try? FileManager.default.removeItem(at: recordingURL) }
        recordingURL = nil
    }

    func discard() {
        cancel()
        transcript = ""
        error = nil
    }
}

/// The voice sheet in Carry On (board "11 Voice capture"): `MacVoiceCaptureCard` over this model.
struct VoiceCaptureView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = VoiceCaptureModel()
    @State private var language = "ru"
    let onUseAsTask: ((String) -> Void)?

    private static let languages = [
        MacChoice(value: "ru", title: "Russian"),
        MacChoice(value: "en", title: "English"),
        MacChoice(value: "auto", title: "Auto"),
    ]

    private var phase: MacVoicePhase {
        if model.recording { return .recording }
        if model.transcribing { return model.preparingModel ? .preparingModel : .transcribing }
        return .idle
    }

    private var cleanTranscript: String { model.transcript.trimmingCharacters(in: .whitespacesAndNewlines) }

    /// "Use as task draft": hands the transcript as it is when chosen to the caller, then closes.
    private var useAsTask: (() -> Void)? {
        guard let onUseAsTask else { return nil }
        return {
            onUseAsTask(cleanTranscript)
            dismiss()
        }
    }

    var body: some View {
        MacVoiceCaptureCard(
            phase: phase, languages: Self.languages, language: $language, error: model.error,
            hasTranscript: !model.transcript.isEmpty, canUseTranscript: !cleanTranscript.isEmpty,
            onRecord: { Task { await model.start() } },
            onStop: { Task { await model.stopAndTranscribe(language: language) } },
            onDiscardRecording: { model.discard() },
            onUseAsTask: useAsTask,
            onClose: { dismiss() }
        ) {
            TextEditor(text: $model.transcript)
                .font(MacCaptureFont.field)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .scrollContentBackground(.hidden)
                .frame(minHeight: 88, maxHeight: 150)
                .accessibilityLabel("Editable transcript")
        } more: {
            Menu {
                Button("Record again") { model.discard(); Task { await model.start() } }
                Button("Copy transcript") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(model.transcript, forType: .string)
                }
                Button("Discard transcript", role: .destructive) { model.discard() }
            } label: {
                Text("More")
                    .font(MacRowFont.pill)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .onDisappear { model.cancel() }
    }
}
