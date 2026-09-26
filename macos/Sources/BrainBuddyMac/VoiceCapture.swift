import AppKit
import AVFoundation
import SwiftUI
import WhisperKit

@MainActor
final class VoiceCaptureModel: ObservableObject {
    @Published var recording = false
    @Published var transcribing = false
    @Published var preparingModel = false
    @Published var transcript = ""
    @Published var error: String?

    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private var whisper: WhisperKit?

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
            guard newRecorder.record() else {
                throw APIError(message: "The microphone could not start recording.")
            }
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
        preparingModel = whisper == nil
        error = nil
        defer {
            transcribing = false
            preparingModel = false
            try? FileManager.default.removeItem(at: url)
        }
        do {
            if whisper == nil {
                guard let resources = Bundle.main.resourceURL else {
                    throw APIError(message: "The local speech model is missing from this app.")
                }
                let speechResources = resources.appendingPathComponent("Whisper", isDirectory: true)
                let modelFolder = speechResources.appendingPathComponent("openai_whisper-base", isDirectory: true)
                let tokenizerFolder = speechResources.appendingPathComponent("whisper-base", isDirectory: true)
                guard FileManager.default.fileExists(atPath: modelFolder.path),
                      FileManager.default.fileExists(atPath: tokenizerFolder.appendingPathComponent("tokenizer.json").path) else {
                    throw APIError(message: "The local speech model is missing from this app.")
                }
                whisper = try await WhisperKit(WhisperKitConfig(
                    modelFolder: modelFolder.path,
                    tokenizerFolder: tokenizerFolder,
                    download: false
                ))
            }
            preparingModel = false
            guard let whisper else { return }
            let options = DecodingOptions(task: .transcribe, language: language == "auto" ? nil : language)
            let segments = try await whisper.transcribe(audioPath: url.path, decodeOptions: options)
            transcript = segments.map(\.text).joined(separator: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
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

struct VoiceCaptureView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var model = VoiceCaptureModel()
    @State private var language = "ru"
    let onUseAsTask: ((String) -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Voice to task draft").font(.title2.bold())
                Spacer()
                Button("Close") { dismiss() }
            }
            Picker("Language", selection: $language) {
                Text("Russian").tag("ru")
                Text("English").tag("en")
                Text("Auto").tag("auto")
            }
            .pickerStyle(.segmented)
            .disabled(model.recording || model.transcribing)
            HStack {
                if model.recording {
                    Button("Stop & transcribe") {
                        Task { await model.stopAndTranscribe(language: language) }
                    }
                    .buttonStyle(.borderedProminent)
                    Button("Discard") { model.discard() }
                } else {
                    Button("Record") { Task { await model.start() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.transcribing)
                }
                if model.transcribing {
                    ProgressView(model.preparingModel ? "Loading local speech model…" : "Transcribing on this Mac…")
                }
            }
            if let error = model.error {
                Text(error).foregroundStyle(.red)
            }
            if !model.transcript.isEmpty {
                TextEditor(text: $model.transcript)
                    .font(.body)
                    .frame(minHeight: 88, maxHeight: 150)
                    .accessibilityLabel("Editable transcript")
            }
            HStack(spacing: 10) {
                if let onUseAsTask {
                    Button("Use as task draft") {
                        onUseAsTask(model.transcript.trimmingCharacters(in: .whitespacesAndNewlines))
                        dismiss()
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                Spacer()
                if !model.transcript.isEmpty {
                    Menu("More") {
                        Button("Record again") { model.discard(); Task { await model.start() } }
                        Button("Copy transcript") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(model.transcript, forType: .string)
                        }
                        Button("Discard transcript", role: .destructive) { model.discard() }
                    }
                }
            }
        }
        .padding(22)
        .frame(minWidth: 460, minHeight: 220)
        .onDisappear { model.cancel() }
    }
}
