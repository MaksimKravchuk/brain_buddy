import BrainBuddyCore
import Foundation

// The seams of the iPhone voice brain dump (spec 031). The app supplies on-device speech
// recognition and the on-device step extractor; the workspace supplies projects and capture.
// Nothing here imports a speech or model framework, so the model runs and is tested on Linux.

/// One step read from what was heard.
public struct HeardStep: Hashable, Sendable {
    public var title: String
    public var projectName: String?
    public var dueDate: CalendarDay?

    public init(title: String, projectName: String? = nil, dueDate: CalendarDay? = nil) {
        self.title = title
        self.projectName = projectName
        self.dueDate = dueDate
    }
}

/// Turns heard text into steps, in the order said. `projects` are active project names.
public protocol StepExtracting: Sendable {
    func steps(in text: String, projects: [String], today: CalendarDay) async throws -> [HeardStep]
}

/// One step per sentence, no project or day: the fallback when the on-device model is
/// unavailable or fails (D4).
public struct SentenceStepExtractor: StepExtracting {
    public init() {}

    public func steps(in text: String, projects: [String], today: CalendarDay) async throws -> [HeardStep] {
        text.split(whereSeparator: { ".!?;".contains($0) || $0.isNewline })
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .map { HeardStep(title: $0.prefix(1).uppercased() + $0.dropFirst()) }
    }
}

public enum SpeechCaptureError: Error, Equatable, Sendable {
    case permissionDenied, recognitionUnavailable, microphoneUnavailable
}

/// On-device recognition. `onHeard` delivers the whole text heard since `start`.
@MainActor
public protocol SpeechCapturing: AnyObject {
    func start(localeIdentifier: String, onHeard: @escaping @MainActor (String) -> Void)
        async throws(SpeechCaptureError)
    /// Stops; any final text is delivered through `onHeard` before this returns.
    func stop() async
    func cancel()
}

/// An active project the steps may name.
public struct BrainDumpProject: Hashable, Sendable {
    public let id: ProjectID
    public let name: String

    public init(id: ProjectID, name: String) {
        self.id = id
        self.name = name
    }
}

/// What the model needs from the workspace; `Workspace` conforms.
@MainActor
public protocol BrainDumpCapturePort: AnyObject {
    var brainDumpToday: CalendarDay { get }
    /// Active projects only.
    func brainDumpProjects() -> [BrainDumpProject]
    /// One ordinary capture; the same `editorID` after an unknown outcome never adds twice.
    func captureBrainDumpStep(_ draft: CaptureDraft, editorID: String) async throws
}

/// The languages the sheet offers for recognition.
public enum VoiceLanguage: String, CaseIterable, Sendable {
    case russian, english

    public var title: String { self == .russian ? "Russian" : "English" }
    public var localeIdentifier: String { self == .russian ? "ru-RU" : "en-US" }
    /// The other offered language ("Try {other language}").
    public var other: VoiceLanguage { self == .russian ? .english : .russian }

    /// The device language when it is one of the offered ones, else English.
    public static func preferred(_ languageCode: String?) -> VoiceLanguage {
        let base = languageCode?.lowercased().split(whereSeparator: { $0 == "-" || $0 == "_" }).first
        return base == "ru" ? .russian : .english
    }
}
