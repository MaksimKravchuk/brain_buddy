# Implementation Plan: iPhone voice brain dump

**Branch**: `031-ios-voice-brain-dump` · **Date**: 2026-10-16 · **Spec**: [spec.md](spec.md)

## Summary

A voice sheet on iPhone, drawn as Carry On screen 11, over the existing voice brain dump
protocol. Three layers, each in its own slice: a typed client for the protocol in the
shared kit (`BrainBuddyAPI`), a platform-neutral state machine the sheet renders
(`BrainBuddyWorkspace`, tested on Linux with a fake server and a fake recorder), and the
app's sheet, recorder and capture-bar button (`ios/BrainBuddy`, compiled by CI's
`ios-app` lane).

## Technical Context

- Swift 6, strict concurrency, iOS 26, no third-party dependency (ios/AGENTS.md).
- Audio: `AVAudioEngine` input tap written to an `AVAudioFile` as AAC (MPEG-4), mono,
  16 kHz, 32 kbit/s, at most 30 minutes (about 7.2 MB, under the server's 10 MiB chunk
  limit), so one recording uploads as chunk 0. An MP4 file cannot be split into chunks
  whose prefixes the server can read, so uploading during recording is not attempted.
- Live text: `SFSpeechRecognizer` with `requiresOnDeviceRecognition = true`, fed from the
  same tap. Locale `ru-RU` when the first language hint is Russian, else `en-US`, as the
  web. When on-device recognition is unavailable no request is made and no text shows.
- SHA-256: Foundation has none on Linux and the kit takes no dependency, so the API layer
  carries a small FIPS 180-4 implementation (`SHA256Digest`), checked against the
  standard vectors.
- Flag: `BrainBuddyAPIClient.me().featureFlags["voice_brain_dump"]`.

## Constitution Check

- Principle II (tested delivery): every requirement the kit decides is tested in the
  package on Linux (API requests and decoding, the model's whole state machine). The
  sheet and the recorder are thin; CI compiles them; their behaviour is the model's.
- No GTD rule moves to the client: proposals, `committable` and recovery actions are the
  server's; the client renders them.
- Privacy: audio stays a temporary file; descriptions redact speech; consent precedes any
  upload (015, ADR-0002).
- No backend change (the Python backend is frozen).

## Architecture

### Kit API (`BrainBuddyAPI/BrainDumpAPI.swift`) — PR-01

DTOs (`BrainDumpOperationDTO`, `BrainDumpProposalDTO`, `BrainDumpProvidersDTO`, …), the
status words and labels, `BrainDumpConsent.cloud(_:languageHints:)`,
`BrainDumpManifest.hash(_:expectedChunks:)`, and one client method per route:
`brainDumpProviders()`, `startBrainDump`, `brainDump(id:)`, `appendBrainDumpTranscript`,
`uploadBrainDumpAudio` (raw body, media type, `X-Content-SHA256`), `sealBrainDump`,
`updateBrainDumpProposal`, `brainDumpCommand`. `Endpoint` gains a content type and extra
headers for the upload.

### Kit model (`BrainBuddyWorkspace/VoiceBrainDump/`) — PR-02

```swift
public protocol BrainDumpRemote: Sendable {            // BrainBuddyAPIClient conforms
    func me() async throws(APIError) -> MeDTO
    func brainDumpProviders() async throws(APIError) -> BrainDumpProvidersDTO
    func startBrainDump(consent: BrainDumpConsent, idempotencyKey: UUID) async throws(APIError) -> BrainDumpOperationDTO
    func brainDump(id: String) async throws(APIError) -> BrainDumpOperationDTO
    func appendBrainDumpTranscript(id: String, segments: [BrainDumpSegmentInput], idempotencyKey: UUID) async throws(APIError) -> BrainDumpOperationDTO
    func uploadBrainDumpAudio(id: String, chunkNumber: Int, audio: Data, mimeType: String) async throws(APIError) -> BrainDumpOperationDTO
    func sealBrainDump(id: String, expectedRevision: Int, expectedChunks: Int, manifestHash: String, idempotencyKey: UUID) async throws(APIError) -> BrainDumpOperationDTO
    func updateBrainDumpProposal(id: String, proposalID: String, change: BrainDumpProposalChange, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> BrainDumpOperationDTO
    func brainDumpCommand(id: String, _ command: BrainDumpCommand, expectedRevision: Int, idempotencyKey: UUID) async throws(APIError) -> BrainDumpOperationDTO
}

public struct RecordedAudio: Sendable, Equatable { public var data: Data; public var mimeType: String }
public enum VoiceRecordingError: Error, Equatable, Sendable { case permissionDenied, microphoneUnavailable, tooLong, failed }

@MainActor public protocol VoiceRecording: AnyObject {
    /// Starts the microphone. `onHeard(text, isFinal)` delivers on-device results; `onLimit`
    /// fires once when the 30-minute limit stops capture.
    func start(localeIdentifier: String, onHeard: @escaping @MainActor (String, Bool) -> Void,
               onLimit: @escaping @MainActor () -> Void) async throws(VoiceRecordingError)
    /// Whether on-device recognition runs for this recording (known after `start`).
    var hasLivePreview: Bool { get }
    func stop() async throws(VoiceRecordingError) -> RecordedAudio
    func cancel()
}

public enum VoiceLanguage: CaseIterable, Sendable { case russianAndEnglish, russian, english }
// title ("Russian + English", "Russian", "English"), hints (["ru","en"], ["ru"], ["en"]), localeIdentifier

@MainActor @Observable public final class VoiceBrainDumpModel {
    public enum Phase: Equatable, Sendable {
        case loadingProviders, providersFailed, ready, starting, recording, processing,
             review, emptyReview, failure, saving, completed(count: Int), permissionDenied
    }
    public struct Step: Identifiable, Equatable, Sendable {
        public let id: String; public var title: String
        public var conflict: (mine: String?, suggestion: String?)?   // as an Equatable struct
    }
    public enum Confirmation: Equatable, Sendable { case discardRecording, cancelProcessing, discardAll, deleteRecording }

    public private(set) var phase: Phase
    public var consentAllowed: Bool            // starts false
    public var language: VoiceLanguage         // starts .russianAndEnglish
    public private(set) var consentText: String?
    public private(set) var heardText: String
    public private(set) var hasLivePreview: Bool
    public private(set) var statusLabel: String?       // processing words
    public private(set) var steps: [Step]
    public private(set) var banner: String?            // provisional / not saveable
    public private(set) var failureTitle: String?, failureMessage: String?   // one per line
    public private(set) var recoveryActions: [(action: BrainDumpRecoveryAction, title: String)]
    public private(set) var errorMessage: String?      // server message + " Ref: …"
    public var addTitle: String { get }                // "Add {n} to Inbox"
    public var canAdd: Bool { get }
    public var conflictNotice: String? { get }
    /// The dialog closing needs, or nil when nothing would be lost.
    public var closeConfirmation: Confirmation? { get }

    public init(remote: any BrainDumpRemote, recorder: any VoiceRecording,
                makeKey: @escaping @Sendable () -> UUID = { UUID() },
                sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) })
    public static func isAvailable(remote: any BrainDumpRemote) async -> Bool   // me() flag, false on any error
    public func load() async
    public func record() async
    public func stopAndReview() async
    public func rename(_ stepID: String, to title: String) async
    public func remove(_ stepID: String) async
    public func resolve(_ stepID: String, keepMine: Bool) async
    public func add() async                     // commit → .completed(count)
    public func discard() async                 // cancel → fresh .ready
    public func recover(_ action: BrainDumpRecoveryAction) async
    public func closeDiscarding() async         // cancel any open operation, cancel the recorder
}
```

Rules the model owns: consent and providers gate `record()`; one in-flight request at a
time per operation, proposal edits serialized on the latest revision; responses with a
lower revision are ignored; a 409 refetches the operation then shows the message; polling
1.5 s doubling to 8 s while `status.isProcessing`; live segments: interim results reuse
the open sequence, a final result closes it, sequences start after the server's highest;
the phase mapping is the web's order (completed, processing, failure, review, recording).
Copy lives in `VoiceBrainDumpCopy` (the strings in design.md).

### App (`ios/BrainBuddy/Screens/Capture/Voice/`) — PR-03

- `AppleVoiceRecorder`: `VoiceRecording` over `AVAudioSession` (`.record`, `.measurement`),
  `AVAudioEngine`, `AVAudioFile` (AAC settings above, temporary directory, deleted after
  `stop` reads it or on `cancel`) and `SFSpeechRecognizer`; asks microphone and speech
  permission on first `start`.
- `VoiceCaptureSheet`: renders the model per design.md; confirmations with
  `confirmationDialog`; on `.completed(n)` shows the toast, asks the workspace to sync,
  and dismisses.
- `CaptureSheet`: the voice button in the glass bar's leading slot when signed in and
  `VoiceBrainDumpModel.isAvailable` said yes (asked once per sheet).
- `project.yml`: `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`.
- The voice button face is drawn in the sheet's file from tokens (`coVoiceBg`, `coVoiceFg`,
  `coVoiceLiveRing`); a shared component is proposed to the "Carry On на iOS" thread
  (it owns BrainBuddyDesign) rather than added here.

## Delivery phases

PR-01 (spec and API) → PR-02 (model) → PR-03 (app). PR-04 closes the feature (acceptance,
traceability, report) after Max's device check.

## Project Structure

### Documentation (this feature)

`specs/031-ios-voice-brain-dump/`: intake, spec, design, plan, tasks, checklists.

### Source Code (repository root)

```text
ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainDumpAPI.swift
ios/BrainBuddyKit/Sources/BrainBuddyAPI/BrainBuddyAPIClient.swift      (Endpoint headers)
ios/BrainBuddyKit/Tests/BrainBuddyAPITests/BrainDumpAPITests.swift
ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/VoiceBrainDump/*.swift
ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift
ios/BrainBuddy/Screens/Capture/Voice/*.swift
ios/BrainBuddy/Screens/Capture/CaptureSheet.swift
ios/project.yml
```

## Verification

- `sh ios/scripts/swift-linux.sh test --filter BrainDumpAPITests`
- `sh ios/scripts/swift-linux.sh test --filter VoiceBrainDumpModelTests`
- CI `ios-app` lane builds the app.
- On a device with the flag on (Max): record three actions, add them, see them in Inbox.

## Risks

- The server's audio inspection rejects the MP4 the device writes: the API test pins the
  request; the device check proves the format. Fallback: WAV in one chunk (30 min at 16 kHz
  16-bit is 57.6 MB, over the chunk limit, so the limit would drop to about 5 minutes).
- On-device recognition is missing for Russian on some devices: the sheet still records.

## Complexity Tracking

None.
