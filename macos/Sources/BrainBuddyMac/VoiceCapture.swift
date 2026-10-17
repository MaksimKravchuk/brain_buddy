import AppKit
import AVFoundation
import BrainBuddyDesign
import Combine
import BrainBuddyMacCore
import Speech
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

    static let modelMissing = VoiceCaptureError(message: "Whisper isn't downloaded. Download it in Settings › Voice.")
    static let microphone = VoiceCaptureError(message: "The microphone could not start recording.")
    static let busy = VoiceCaptureError(message: "Wait for the current transcription to finish.")
    static let notAllowed = VoiceCaptureError(message: VoiceSettingsCopy.speechNotAllowed)
    static let unavailable = VoiceCaptureError(
        message: "Speech recognition for this language isn't available on this Mac right now.")
}

/// Apple's speech recognition, on this Mac only (037-FR-002): `requiresOnDeviceRecognition`, so a
/// language the Mac cannot recognise offline is refused instead of being sent anywhere.
enum AppleSpeech {
    /// The locales Apple recognises on device on this Mac ("en-US", "ru-RU", …), read at run time
    /// because the list differs between Macs and macOS versions.
    static func onDeviceLocales() -> [String] {
        SFSpeechRecognizer.supportedLocales()
            .filter { SFSpeechRecognizer(locale: $0)?.supportsOnDeviceRecognition == true }
            .map(\.identifier)
            .sorted()
    }

    /// Asks once; afterwards answers from the setting the person chose.
    static func authorize() async -> Bool {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: return true
        case .notDetermined:
            return await withCheckedContinuation { continuation in
                SFSpeechRecognizer.requestAuthorization { continuation.resume(returning: $0 == .authorized) }
            }
        default: return false
        }
    }

    /// Transcribes the recording at `audio` in `locale`, on this Mac.
    static func transcribe(audio: URL, locale: String) async throws -> String {
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: locale)),
              recognizer.isAvailable, recognizer.supportsOnDeviceRecognition
        else { throw VoiceCaptureError.unavailable }
        let request = SFSpeechURLRecognitionRequest(url: audio)
        request.requiresOnDeviceRecognition = true
        request.shouldReportPartialResults = false
        request.addsPunctuation = true
        let once = ResumeOnce()
        return try await withCheckedThrowingContinuation { continuation in
            once.task = recognize(recognizer, request: request) { result in
                guard once.claim() else { return }
                continuation.resume(with: result)
            }
        }
    }

    /// Speech calls the block on its own queue, so it only hands the answer on. `ResumeOnce` holds
    /// the task until the one answer is delivered.
    private static func recognize(
        _ recognizer: SFSpeechRecognizer, request: SFSpeechURLRecognitionRequest,
        deliver: @escaping @Sendable (Result<String, Error>) -> Void
    ) -> SFSpeechRecognitionTask {
        recognizer.recognitionTask(with: request) { result, error in
            if let result, result.isFinal {
                deliver(.success(result.bestTranscription.formattedString))
            } else if let error {
                deliver(.failure(error))
            }
        }
    }
}

/// Lets the recognition callback resume its continuation exactly once.
///
/// `@unchecked Sendable` is safe because `done` and `task` are touched only while holding `lock`.
private final class ResumeOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var done = false
    private var heldTask: SFSpeechRecognitionTask?

    var task: SFSpeechRecognitionTask? {
        get { lock.withLock { heldTask } }
        set { lock.withLock { heldTask = done ? nil : newValue } }
    }

    func claim() -> Bool {
        lock.withLock {
            guard !done else { return false }
            done = true
            heldTask = nil
            return true
        }
    }
}

/// The only place WhisperKit transcribes (research R2): the downloaded model loads once, on first
/// use, and transcribes one recording at a time on this Mac. Nothing leaves the device; the model
/// is read from disk and never fetched here (`download: false`; the download is `WhisperDownload`).
actor VoiceTranscriber {
    private var whisper: WhisperKit?
    private var isTranscribing = false

    /// Whether the next `transcribe` loads the model first.
    var needsModel: Bool { whisper == nil }

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

    /// The chips and the engine behind each (037-FR-003, -004); rebuilt when Whisper comes or goes.
    @Published private(set) var plan: VoiceLanguagePlan

    private var recorder: AVAudioRecorder?
    private var recordingURL: URL?
    private let transcriber = VoiceTranscriber()
    private let whisper: WhisperDownload
    private let appleLocales: [String]
    private var watch: AnyCancellable?

    init(whisper: WhisperDownload = .shared) {
        self.whisper = whisper
        let locales = AppleSpeech.onDeviceLocales()
        appleLocales = locales
        plan = Self.plan(appleLocales: locales, whisperReady: whisper.state == .downloaded)
        // `WhisperDownload` publishes only on the main actor.
        watch = whisper.$state.dropFirst().sink { [weak self] state in
            MainActor.assumeIsolated { self?.whisperChanged(state) }
        }
    }

    private func whisperChanged(_ state: WhisperDownload.State) {
        plan = Self.plan(appleLocales: appleLocales, whisperReady: state == .downloaded)
    }

    private static func plan(appleLocales: [String], whisperReady: Bool) -> VoiceLanguagePlan {
        VoiceLanguagePlan(
            preferredLanguages: Locale.preferredLanguages, appleLocales: appleLocales,
            whisperLanguages: whisperReady ? Constants.languageCodes : [])
    }

    func start(language: String) async {
        error = nil
        // 037-FR-005: a language nothing can transcribe here is never recorded.
        guard let engine = plan.engine(for: language) else { return }
        if engine == .apple, !(await AppleSpeech.authorize()) {
            error = VoiceSettingsCopy.speechNotAllowed
            return
        }
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
        error = nil
        defer {
            transcribing = false
            preparingModel = false
            try? FileManager.default.removeItem(at: url)
        }
        do {
            switch plan.engine(for: language) {
            case .apple:
                guard let locale = plan.appleLocale(for: language, preferredLanguages: Locale.preferredLanguages)
                else { throw VoiceCaptureError.unavailable }
                transcript = try await AppleSpeech.transcribe(audio: url, locale: locale)
            case .whisper:
                guard let model = whisper.files.modelFolder else { throw VoiceCaptureError.modelMissing }
                preparingModel = await transcriber.needsModel
                transcript = try await transcriber.transcribe(
                    audio: url, language: language == VoiceLanguagePlan.auto ? nil : language,
                    model: model, tokenizer: whisper.files.tokenizerFolder
                )
            case nil:
                throw VoiceCaptureError.modelMissing
            }
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
    @Environment(\.openSettings) private var openSettings
    @StateObject private var model = VoiceCaptureModel()
    @State private var language = ""
    let onUseAsTask: ((String) -> Void)?

    private var languages: [MacChoice<String>] {
        model.plan.chips.map { MacChoice(value: $0, title: VoiceLanguagePlan.title(for: $0)) }
    }

    /// V-01c: the chosen language needs Whisper, which is not downloaded.
    private var needsWhisper: MacVoiceNote? {
        guard !language.isEmpty, model.plan.engine(for: language) == nil else { return nil }
        return MacVoiceNote(
            text: VoiceSettingsCopy.needsWhisper(VoiceLanguagePlan.title(for: language)),
            action: VoiceSettingsCopy.openSettings,
            perform: {
                VoiceSettingsRoute.request()
                openSettings()
            })
    }

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
            phase: phase, languages: languages, language: $language, error: model.error,
            hasTranscript: !model.transcript.isEmpty, canUseTranscript: !cleanTranscript.isEmpty,
            onRecord: { Task { await model.start(language: language) } },
            onStop: { Task { await model.stopAndTranscribe(language: language) } },
            onDiscardRecording: { model.discard() },
            onUseAsTask: useAsTask,
            onClose: { dismiss() },
            canRecord: needsWhisper == nil, note: needsWhisper
        ) {
            TextEditor(text: $model.transcript)
                .font(MacCaptureFont.field)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .scrollContentBackground(.hidden)
                .frame(minHeight: 88, maxHeight: 150)
                .accessibilityLabel("Editable transcript")
        } more: {
            Menu {
                Button("Record again") { model.discard(); Task { await model.start(language: language) } }
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
        .onAppear { language = model.plan.initial }
        // A chip that went away (Auto after Whisper was removed) falls back to the first usable one.
        .onChange(of: model.plan) { _, plan in
            if !plan.chips.contains(language) { language = plan.initial }
        }
        .onDisappear { model.cancel() }
    }
}
