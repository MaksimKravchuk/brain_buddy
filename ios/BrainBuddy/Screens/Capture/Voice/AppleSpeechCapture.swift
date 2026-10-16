import AVFoundation
import BrainBuddyWorkspace
import Foundation
import Speech

/// The microphone for the voice sheet: an `AVAudioEngine` tap feeds an on-device
/// `SFSpeechRecognizer`, and every partial result delivers the whole text heard so far.
///
/// Recognition never leaves the device (`requiresOnDeviceRecognition`; a language the device
/// cannot recognise offline is `.recognitionUnavailable`). Nothing is written to a file and
/// nothing heard is logged.
@MainActor
final class AppleSpeechCapture: SpeechCapturing {
    /// How long `stop()` waits for the recogniser's last words.
    private static let finalWait: Duration = .seconds(2)

    private let engine = AVAudioEngine()
    private var task: SFSpeechRecognitionTask?
    private var audio: AudioSink?
    private var onHeard: (@MainActor (String) -> Void)?
    private var waiter: CheckedContinuation<Void, Never>?
    /// Bumped on every start and cancel, so a late callback of an earlier session is ignored.
    private var generation = 0
    private var isTapping = false

    func start(
        localeIdentifier: String,
        onHeard: @escaping @MainActor (String) -> Void
    ) async throws(SpeechCaptureError) {
        cancel()
        guard await AVAudioApplication.requestRecordPermission(),
            await Self.requestSpeechAccess()
        else { throw .permissionDenied }

        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeIdentifier)),
            recognizer.isAvailable, recognizer.supportsOnDeviceRecognition
        else { throw .recognitionUnavailable }

        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .measurement, options: [])
            try session.setActive(true)
        } catch {
            throw .microphoneUnavailable
        }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            deactivateSession()
            throw .microphoneUnavailable
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = true
        let sink = AudioSink(request)
        generation += 1
        let current = generation
        self.onHeard = onHeard
        audio = sink
        task = Self.recognize(recognizer, request: request) { [weak self] text, isFinal in
            Task { @MainActor in self?.heard(text, isFinal: isFinal, generation: current) }
        }
        input.installTap(onBus: 0, bufferSize: 4096, format: format, block: Self.tapBlock(for: sink))
        isTapping = true
        engine.prepare()
        do {
            try engine.start()
        } catch {
            cancel()
            throw .microphoneUnavailable
        }
    }

    func stop() async {
        guard audio != nil else { return }
        stopEngine()
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            waiter = continuation
            audio?.endAudio()
            let current = generation
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: Self.finalWait)
                if self?.generation == current { self?.resumeWaiter() }
            }
        }
        finish()
    }

    func cancel() {
        generation += 1
        stopEngine()
        audio?.endAudio()
        task?.cancel()
        resumeWaiter()
        finish()
    }

    // MARK: Private

    /// `text` is nil when the recogniser errored: the session ends, and what was heard stays.
    private func heard(_ text: String?, isFinal: Bool, generation current: Int) {
        guard current == generation else { return }
        if let text { onHeard?(text) }
        if isFinal { resumeWaiter() }
    }

    private func resumeWaiter() {
        waiter?.resume()
        waiter = nil
    }

    private func stopEngine() {
        guard isTapping else { return }
        isTapping = false
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
    }

    private func finish() {
        task?.cancel()
        task = nil
        audio = nil
        onHeard = nil
        deactivateSession()
    }

    private func deactivateSession() {
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // These are nonisolated on purpose: the system calls their blocks on its own queues, and a
    // closure written inside this main-actor class would be main-actor isolated and trap.

    private nonisolated static func tapBlock(for sink: AudioSink) -> AVAudioNodeTapBlock {
        { buffer, _ in sink.append(buffer) }
    }

    private nonisolated static func requestSpeechAccess() async -> Bool {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }

    /// An error ends the session like a final result, with no text, so the transcript heard so far
    /// is kept (the recogniser also errors on silence).
    private nonisolated static func recognize(
        _ recognizer: SFSpeechRecognizer,
        request: SFSpeechAudioBufferRecognitionRequest,
        deliver: @escaping @Sendable (String?, Bool) -> Void
    ) -> SFSpeechRecognitionTask {
        recognizer.recognitionTask(with: request) { result, error in
            if let result {
                deliver(result.bestTranscription.formattedString, result.isFinal)
            } else if error != nil {
                deliver(nil, true)
            }
        }
    }
}

/// Hands the audio thread's buffers to the recognition request.
///
/// `@unchecked Sendable` is safe because the request is touched only while holding `lock`: the
/// tap thread calls `append`, the main actor calls `endAudio`.
private final class AudioSink: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    init(_ request: SFSpeechAudioBufferRecognitionRequest) { self.request = request }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.withLock { request?.append(buffer) }
    }

    func endAudio() {
        lock.withLock {
            request?.endAudio()
            request = nil
        }
    }
}
