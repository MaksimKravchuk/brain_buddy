import BrainBuddyCore
import Foundation
import Observation

// The state machine of the iPhone voice sheet (spec 031, design.md V-02.1 to V-02.9). The sheet
// renders `phase`, `heardText` and `steps` and calls the actions below; it holds no copy of the
// rules. Speech and step reading run on the device behind `SpeechCapturing` and `StepExtracting`;
// adding goes through the ordinary capture path (`BrainDumpCapturePort`). Nothing heard is logged.

@MainActor
@Observable
public final class VoiceBrainDumpModel {
    public enum Phase: Equatable, Sendable {
        case starting, listening, finishing, review, saving, saved(count: Int), permissionDenied, unavailable
    }

    public struct Step: Identifiable, Equatable, Sendable {
        public let id: String
        public var title: String
        public var project: BrainDumpProject?
        public var dueDate: CalendarDay?
        public var isEdited: Bool

        public init(id: String, title: String, project: BrainDumpProject? = nil, dueDate: CalendarDay? = nil,
                    isEdited: Bool = false) {
            (self.id, self.title, self.project, self.dueDate, self.isEdited) = (id, title, project, dueDate, isEdited)
        }
    }

    public private(set) var phase: Phase = .starting
    public var language: VoiceLanguage
    public private(set) var heardText = ""
    public private(set) var steps: [Step] = []
    public private(set) var errorMessage: String?

    /// "Add {n} to Inbox".
    public var addTitle: String { VoiceBrainDumpCopy.add(steps.count) }
    /// Steps are listed and nothing is starting, finishing or being saved.
    public var canAdd: Bool { !steps.isEmpty && (phase == .listening || phase == .review) }
    /// Words were heard or steps are listed, and they were not added.
    public var needsCloseConfirmation: Bool {
        if case .saved = phase { return false }
        return !steps.isEmpty || !heardText.allSatisfy(\.isWhitespace)
    }

    @ObservationIgnored private let speech: any SpeechCapturing
    @ObservationIgnored private let extractor: any StepExtracting
    @ObservationIgnored private let fallback: any StepExtracting
    @ObservationIgnored private let port: any BrainDumpCapturePort
    @ObservationIgnored private let makeID: @MainActor () -> String
    @ObservationIgnored private let debounce: Duration
    @ObservationIgnored private let sleep: @Sendable (Duration) async throws -> Void
    /// Text heard before the latest `start`; the current recognition continues after it.
    @ObservationIgnored private var earlierText = ""
    /// Normalised titles that must not come back: removed steps, and edited steps' read titles.
    @ObservationIgnored private var removedKeys: Set<String> = []
    @ObservationIgnored private var editedOriginals: [String: String] = [:]
    /// Bumped by `start` and `cancel`; speech callbacks of an older session are ignored.
    @ObservationIgnored private var session = 0
    /// Bumped whenever a newer read supersedes the one in flight (latest wins).
    @ObservationIgnored private var readGeneration = 0
    @ObservationIgnored private var isStarting = false
    /// The scheduled or running debounced read (internal so tests can await it).
    @ObservationIgnored var pendingRead: Task<Void, Never>?

    public init(
        speech: any SpeechCapturing, extractor: any StepExtracting,
        fallback: any StepExtracting = SentenceStepExtractor(),
        port: any BrainDumpCapturePort, language: VoiceLanguage,
        makeID: @escaping @MainActor () -> String = { UUID().uuidString },
        debounce: Duration = .milliseconds(700),
        sleep: @escaping @Sendable (Duration) async throws -> Void = { try await Task.sleep(for: $0) }
    ) {
        (self.speech, self.extractor, self.fallback, self.port) = (speech, extractor, fallback, port)
        (self.makeID, self.debounce, self.sleep) = (makeID, debounce, sleep)
        self.language = language
    }

    // MARK: Actions

    /// Starts listening; words heard now continue after the text heard earlier.
    public func start() async {
        guard !isStarting, ![.listening, .finishing, .saving].contains(phase) else { return }
        if case .saved = phase { return }
        isStarting = true
        defer { isStarting = false }
        session += 1
        let current = session
        phase = .starting
        errorMessage = nil
        earlierText = heardText
        do {
            try await speech.start(localeIdentifier: language.localeIdentifier) { [weak self] text in
                self?.heard(text, session: current)
            }
        } catch {
            guard current == session else { return }
            switch error {
            case .permissionDenied: phase = .permissionDenied
            case .recognitionUnavailable: phase = .unavailable
            case .microphoneUnavailable:
                phase = .review
                errorMessage = VoiceBrainDumpCopy.microphoneUnavailable
            }
            return
        }
        guard current == session else { return speech.cancel() }  // closed while starting
        if phase == .starting { phase = .listening }
    }

    /// Stops listening, reads the steps once more from everything heard, and shows them for review.
    public func stop() async {
        guard phase == .listening else { return }
        phase = .finishing
        pendingRead?.cancel()
        readGeneration += 1
        await speech.stop()
        guard phase == .finishing else { return }
        readGeneration += 1
        await read(readGeneration)
        if phase == .finishing { phase = .review }
    }

    public func rename(_ id: String, to title: String) {
        guard phase != .saving, let index = steps.firstIndex(where: { $0.id == id }) else { return }
        let trimmed = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return remove(id) }
        guard trimmed != steps[index].title else { return }
        if !steps[index].isEdited { editedOriginals[id] = Self.normalise(steps[index].title) }
        steps[index].title = trimmed
        steps[index].isEdited = true
    }

    public func remove(_ id: String) {
        guard phase != .saving, let index = steps.firstIndex(where: { $0.id == id }) else { return }
        removedKeys.insert(Self.normalise(steps[index].title))
        if let original = editedOriginals.removeValue(forKey: id) { removedKeys.insert(original) }
        steps.remove(at: index)
    }

    /// Captures each step in order (stopping first when listening). A saved step leaves the list;
    /// the first failure stops, keeps the rest and shows the error.
    public func add() async {
        guard canAdd else { return }
        if phase == .listening { await stop() }
        guard phase == .review, !steps.isEmpty else { return }
        phase = .saving
        errorMessage = nil
        var saved = 0
        for step in steps {
            let draft = CaptureDraft(text: step.title, list: .inbox, dueDate: step.dueDate,
                                     contextProjectID: step.project?.id)
            do {
                try await port.captureBrainDumpStep(draft, editorID: "voice-" + step.id)
            } catch {
                errorMessage = VoiceBrainDumpCopy.saveFailed
                phase = .review
                return
            }
            steps.removeAll { $0.id == step.id }
            saved += 1
        }
        phase = .saved(count: saved)
    }

    /// Stops speech without reading or saving (the sheet was closed).
    public func cancel() {
        session += 1
        readGeneration += 1
        pendingRead?.cancel()
        pendingRead = nil
        guard [.starting, .listening, .finishing].contains(phase) else { return }
        speech.cancel()
        phase = .review
    }

    // MARK: Reading

    private func heard(_ text: String, session current: Int) {
        guard current == session, [.starting, .listening, .finishing].contains(phase) else { return }
        heardText = [earlierText, text]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        if phase != .finishing { scheduleRead() }
    }

    private func scheduleRead() {
        pendingRead?.cancel()
        readGeneration += 1
        let generation = readGeneration
        let sleep = self.sleep
        let debounce = self.debounce
        pendingRead = Task { [weak self] in
            do { try await sleep(debounce) } catch { return }
            guard !Task.isCancelled else { return }
            await self?.read(generation)
        }
    }

    private func read(_ generation: Int) async {
        let text = heardText
        let projects = port.brainDumpProjects()
        let names = projects.map(\.name)
        let today = port.brainDumpToday
        var heard: [HeardStep] = []
        if !text.allSatisfy(\.isWhitespace) {
            do {
                heard = try await extractor.steps(in: text, projects: names, today: today)
            } catch {
                heard = (try? await fallback.steps(in: text, projects: names, today: today)) ?? []
            }
        }
        guard generation == readGeneration else { return }
        merge(heard, projects: projects)
    }

    /// The read replaces the steps the person has not edited, in the order said; edited steps keep
    /// their place; removed and edited titles never come back; an unchanged step keeps its id.
    private func merge(_ heard: [HeardStep], projects: [BrainDumpProject]) {
        var blocked = removedKeys.union(editedOriginals.values)
        var previous: [String: String] = [:]
        for step in steps {
            let key = Self.normalise(step.title)
            if step.isEdited { blocked.insert(key) } else if previous[key] == nil { previous[key] = step.id }
        }
        var fresh: [Step] = []
        for item in heard {
            let title = item.title.trimmingCharacters(in: .whitespacesAndNewlines)
            let key = Self.normalise(title)
            guard !key.isEmpty, blocked.insert(key).inserted else { continue }
            let wanted = item.projectName?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            let project = projects.first { $0.name.lowercased() == wanted }
            let id = previous.removeValue(forKey: key) ?? makeID()
            fresh.append(Step(id: id, title: title, project: project, dueDate: item.dueDate))
        }
        var merged: [Step] = []
        var rest = fresh[...]
        for step in steps {
            if step.isEdited {
                merged.append(step)
            } else if let next = rest.popFirst() {
                merged.append(next)
            }
        }
        merged.append(contentsOf: rest)
        steps = merged
    }

    /// Lower-cased, trimmed, inner whitespace collapsed, trailing punctuation dropped.
    static func normalise(_ title: String) -> String {
        var words = title.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ")
        while let last = words.last, last.isPunctuation || last.isWhitespace { words.removeLast() }
        return words
    }
}
