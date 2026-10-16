# Implementation Plan: iPhone voice brain dump

**Branch**: `031-ios-voice-brain-dump` · **Date**: 2026-10-16 · **Spec**: [spec.md](spec.md)

## Summary

A voice sheet on iPhone, drawn as Carry On screen 11, that runs entirely on the device.
Two layers: a platform-neutral model in the shared kit (`BrainBuddyWorkspace`) that owns
the live steps, edits, removals and adding, tested on Linux with fakes; and the app's
speech capture (Apple Speech, on-device), step extractor (Foundation Models), sheet and
capture-bar button (`ios/BrainBuddy`, compiled by CI's `ios-app` lane).

## Technical Context

- Swift 6, strict concurrency, iOS 26, no third-party dependency (ios/AGENTS.md).
- Speech: `SFSpeechRecognizer(locale:)` with `requiresOnDeviceRecognition = true` and an
  `SFSpeechAudioBufferRecognitionRequest` fed by an `AVAudioEngine` input tap; partial
  results deliver the whole text so far. Unavailable when `supportsOnDeviceRecognition` is
  false for the locale. No file is written.
- Steps: `SystemLanguageModel.default` through a `LanguageModelSession` that generates a
  `@Generable` list of steps (title, optional project name chosen from the given names,
  optional ISO day). The precedent is `AppleOnDeviceExecutor` in
  `ios/BrainBuddy/Screens/Review/ReviewSuggestionSheet.swift`.
- Fallback: `SentenceStepExtractor` in the kit (sentences split on `.`, `!`, `?`, `;` and
  line breaks; trimmed; first letter upper-cased; empty pieces dropped).
- Adding: `Workspace.capture(_:editorID:)` with `CaptureDraft(text:list:.inbox, dueDate:,
  contextProjectID:)`, one stable editor id per step.

## Constitution Check

- Principle II: every rule (live re-reading, merge with edits and removals, project match,
  adding and partial failure) is in the kit model and tested on Linux. The app layer is
  thin glue over system frameworks; CI compiles it.
- No GTD rule moves: capture goes through the existing reducer path.
- Privacy: nothing leaves the device; no audio is stored; nothing heard is logged.
- No backend change.

## Architecture

### Kit model (`BrainBuddyWorkspace/VoiceBrainDump/`) — PR-02

```swift
/// One step read from what was heard.
public struct HeardStep: Hashable, Sendable {
    public var title: String
    public var projectName: String?
    public var dueDate: CalendarDay?
    public init(title: String, projectName: String? = nil, dueDate: CalendarDay? = nil)
}

/// Turns heard text into steps, in the order said. `projects` are active project names.
public protocol StepExtracting: Sendable {
    func steps(in text: String, projects: [String], today: CalendarDay) async throws -> [HeardStep]
}

/// One step per sentence, no project or day (the fallback, D4).
public struct SentenceStepExtractor: StepExtracting { public init() }

public enum SpeechCaptureError: Error, Equatable, Sendable {
    case permissionDenied, recognitionUnavailable, microphoneUnavailable
}

/// On-device recognition. `onHeard` delivers the whole text heard since `start`.
@MainActor public protocol SpeechCapturing: AnyObject {
    func start(localeIdentifier: String, onHeard: @escaping @MainActor (String) -> Void)
        async throws(SpeechCaptureError)
    /// Stops; any final text is delivered through `onHeard` before this returns.
    func stop() async
    func cancel()
}

/// What the model needs from the workspace; `Workspace` conforms.
@MainActor public protocol BrainDumpCapturePort: AnyObject {
    var brainDumpToday: CalendarDay { get }
    func brainDumpProjects() -> [BrainDumpProject]          // id + name, active only
    func captureBrainDumpStep(_ draft: CaptureDraft, editorID: String) async throws
}
public struct BrainDumpProject: Hashable, Sendable { public let id: ProjectID; public let name: String }

public enum VoiceLanguage: String, CaseIterable, Sendable {
    case russian, english
    public var title: String            // "Russian", "English"
    public var localeIdentifier: String // "ru-RU", "en-US"
    public static func preferred(_ languageCode: String?) -> VoiceLanguage   // "ru" → .russian, else .english
}

@MainActor @Observable public final class VoiceBrainDumpModel {
    public enum Phase: Equatable, Sendable {
        case starting, listening, finishing, review, saving, saved(count: Int), permissionDenied, unavailable
    }
    public struct Step: Identifiable, Equatable, Sendable {
        public let id: String
        public var title: String
        public var project: BrainDumpProject?
        public var dueDate: CalendarDay?
        public var isEdited: Bool
    }

    public private(set) var phase: Phase
    public var language: VoiceLanguage
    public private(set) var heardText: String
    public private(set) var steps: [Step]
    public private(set) var errorMessage: String?
    public var addTitle: String { get }          // "Add {n} to Inbox"
    public var canAdd: Bool { get }              // n > 0, phase listening/review
    public var needsCloseConfirmation: Bool { get }   // heard text or steps, not saved

    public init(speech: any SpeechCapturing, extractor: any StepExtracting,
                fallback: any StepExtracting = SentenceStepExtractor(),
                port: any BrainDumpCapturePort, language: VoiceLanguage,
                makeID: @escaping @MainActor () -> String = { UUID().uuidString },
                debounce: Duration = .milliseconds(700),
                sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) })

    public func start() async          // listening; heard text continues after earlier text
    public func stop() async           // finishing → final read → review
    public func rename(_ id: String, to title: String)
    public func remove(_ id: String)
    public func add() async            // stops first when listening; captures in order → saved(count)
    public func cancel()               // stops speech without saving (sheet closed)
}
```

Rules the model owns:

- Live reading: each `onHeard` replaces the current segment of `heardText` (text heard
  before the latest `start` is kept in front); a read is scheduled after `debounce` of
  quiet, cancelling the previous one; `stop()` reads once more at once. Reads run the
  extractor on the whole heard text; on any thrown error, the fallback.
- Merge: the read's steps, in order, replace the non-edited steps; edited steps keep their
  place relative to the read (stay where they were, new ones after); a read step whose
  normalised title (lower-cased, trimmed, inner whitespace collapsed, trailing punctuation
  dropped) equals a removed title or an edited step's original title is dropped; a read step
  whose normalised title equals a previous non-edited step's keeps that step's id.
- Project: case-insensitive match of `projectName` against `brainDumpProjects()`; no match
  → nil.
- Adding: for each step in order, `CaptureDraft(text: title, list: .inbox, dueDate:,
  contextProjectID: project?.id)` with editor id `"voice-" + step.id`; a success removes the
  step from the list; the first failure stops, sets `errorMessage` and returns to review.
  All saved → `.saved(count:)`.
- Errors from speech: `.permissionDenied` → phase `.permissionDenied`;
  `.recognitionUnavailable` → `.unavailable`; `.microphoneUnavailable` → review with an error
  message.
- Copy lives in `VoiceBrainDumpCopy` (design.md table).

### App — PR-03 speech and steps, PR-04 sheet

- `AppleSpeechCapture` (`SpeechCapturing`): `AVAudioSession` `.record`/`.measurement`,
  `AVAudioEngine` tap → `SFSpeechAudioBufferRecognitionRequest` (on-device only, partial
  results); asks microphone (`AVAudioApplication.requestRecordPermission()`) and speech
  (`SFSpeechRecognizer.requestAuthorization`) permission on first start; denial →
  `.permissionDenied`.
- `AppleStepExtractor` (`StepExtracting`): Foundation Models; throws when the model is not
  available, so the model falls back to sentences. Instructions: split what the person said
  into concrete next actions, verb first, in the language spoken, drop filler and
  duplicates; pick a project only from the given names; give a day only when one was said,
  as ISO date relative to today.
- `VoiceCaptureSheet` + `VoiceCaptureParts` (rows, voice button face): renders the model
  per design.md; on `.saved(n)` shows the toast and dismisses both sheets.
- `CaptureSheet`: the voice button in the glass bar's leading slot, presenting the sheet.
- `project.yml`: `NSMicrophoneUsageDescription`, `NSSpeechRecognitionUsageDescription`.

## Delivery phases

PR-01 (spec) → PR-02 (model) → PR-03 (speech, steps) ∥ PR-04 (sheet, after PR-02) → PR-05
(close: acceptance, traceability, report after Max's device check).

## Project Structure

### Documentation (this feature)

`specs/031-ios-voice-brain-dump/`: intake, spec, design, plan, tasks, checklists.

### Source Code (repository root)

```text
ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/VoiceBrainDump/*.swift
ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift
ios/BrainBuddy/Screens/Capture/Voice/AppleSpeechCapture.swift
ios/BrainBuddy/Screens/Capture/Voice/AppleStepExtractor.swift
ios/BrainBuddy/Screens/Capture/Voice/VoiceCaptureSheet.swift
ios/BrainBuddy/Screens/Capture/Voice/VoiceCaptureParts.swift
ios/BrainBuddy/Screens/Capture/CaptureSheet.swift
ios/project.yml
```

## Verification

- `sh ios/scripts/swift-linux.sh test --filter VoiceBrainDumpModelTests`
- CI `ios-app` lane builds the app.
- On a device (Max): say three actions in Russian and in English, add them, see them in
  the Inbox, offline and signed out.

## Risks

- Apple's model handles Russian poorly: the fallback and editing keep the sheet useful;
  D4 decides further work.
- Re-reading the whole text on every pause costs model time on long dumps: the debounce and
  cancelling the previous read bound it to one read at a time.

## Complexity Tracking

None.
