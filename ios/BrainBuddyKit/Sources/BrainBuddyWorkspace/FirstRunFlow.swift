import BrainBuddyCore
import Foundation
import Observation

/// Where the iPhone's one-time first run (boards 01–04, the iPhone side of spec 029) stands.
/// `undecided` until the workspace has loaded; `done` shows the app as it always was.
public enum FirstRunPhase: Hashable, Sendable {
    /// Board 01: the logo, "Start" and "I have an account".
    case welcome
    /// Board 02: "What feels heaviest?" with the field focused.
    case capture
    /// Board 03: the item just captured and "What is the first step you could take?".
    case firstStep(TaskID)
    /// Board 04: Next actions with the step on top and one tip.
    case landing
    case undecided, done
}

/// When the first run was decided, how it ended and when its tip was dismissed. Only dates and
/// an outcome: never the text the person wrote.
public struct FirstRunRecord: Codable, Hashable, Sendable {
    public enum Outcome: String, Codable, Sendable {
        case notNeeded, inProgress, skipped, notYet, firstStep, signedIn
    }

    public var decidedAt: Date
    public var outcome: Outcome
    public var tipDismissedAt: Date?

    public init(decidedAt: Date, outcome: Outcome, tipDismissedAt: Date? = nil) {
        self.decidedAt = decidedAt
        self.outcome = outcome
        self.tipDismissedAt = tipDismissedAt
    }
}

/// Keeps the one `FirstRunRecord` of this device.
@MainActor
public protocol FirstRunRecordStore: AnyObject {
    func load() -> FirstRunRecord?
    func save(_ record: FirstRunRecord) throws
}

/// The record as JSON under one `UserDefaults` key: the app's own defaults, never the App
/// Group, so the widget and App Intents never see or decide it.
@MainActor
public final class UserDefaultsFirstRunRecordStore: FirstRunRecordStore {
    public static let key = "BBFirstRunRecord"
    private let defaults: UserDefaults

    public init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
    }

    public func load() -> FirstRunRecord? {
        guard let data = defaults.data(forKey: Self.key) else { return nil }
        return try? JSONDecoder().decode(FirstRunRecord.self, from: data)
    }

    public func save(_ record: FirstRunRecord) throws {
        defaults.set(try JSONEncoder().encode(record), forKey: Self.key)
    }
}

/// What the device already holds at launch, read from the loaded workspace without any network
/// call.
public struct FirstRunLaunchFacts: Hashable, Sendable {
    public var hasAccount: Bool
    /// A Rust-selected workspace was imported from an earlier store: never a fresh install.
    public var isRustSelected: Bool
    public var taskCount: Int
    public var projectCount: Int
    public var tagCount: Int
    public var hasInboxItem: Bool

    public init(
        hasAccount: Bool = false, isRustSelected: Bool = false, taskCount: Int = 0, projectCount: Int = 0,
        tagCount: Int = 0, hasInboxItem: Bool = false
    ) {
        self.hasAccount = hasAccount
        self.isRustSelected = isRustSelected
        self.taskCount = taskCount
        self.projectCount = projectCount
        self.tagCount = tagCount
        self.hasInboxItem = hasInboxItem
    }

    /// Nothing at all on this device: no account, no task in any state, no project, no tag.
    var isClean: Bool { !hasAccount && !isRustSelected && taskCount == 0 && projectCount == 0 && tagCount == 0 }
}

extension FirstRunLaunchFacts {
    /// The facts of a loaded workspace. Completed and cancelled tasks count: a device that was
    /// ever used is not new.
    @MainActor
    public init(_ workspace: Workspace) {
        let tasks = workspace.state.tasks.values
        self.init(
            hasAccount: workspace.account != nil, isRustSelected: workspace.isRustSelected,
            taskCount: tasks.count, projectCount: workspace.state.projects.count,
            tagCount: workspace.state.tags.count, hasInboxItem: tasks.contains { $0.state == .inbox }
        )
    }
}

/// Decides once per device whether the iPhone's first run shows, walks it, and records only
/// dates and an outcome. No network, no AI, no permission prompt (board "Carry On · first run").
/// The two writes it makes go through the existing task commands: a plain `createTask` in the
/// Inbox, then an `updateTask` and a move to Next actions.
@MainActor
@Observable
public final class FirstRunFlow {
    public private(set) var phase: FirstRunPhase = .undecided
    public private(set) var record: FirstRunRecord?
    /// In memory only: the words the person captured, shown above the first-step question.
    public private(set) var capturedText: String?
    @ObservationIgnored private let store: any FirstRunRecordStore
    @ObservationIgnored private let now: () -> Date

    public init(store: any FirstRunRecordStore, now: @escaping () -> Date = { Date() }) {
        self.store = store
        self.now = now
        record = store.load()
    }

    /// Boards 01 to 03 cover the whole screen; the app's tabs are not shown under them.
    public var coversApp: Bool {
        switch phase {
        case .welcome, .capture, .firstStep: true
        case .landing, .undecided, .done: false
        }
    }

    public var showsLandingTip: Bool { phase == .landing }

    // MARK: Decision

    /// Decides once, after the workspace has loaded. A record that cannot be written would show
    /// the welcome on every launch, so a clean device whose record fails to save skips it.
    public func decide(_ facts: FirstRunLaunchFacts) {
        guard phase == .undecided else { return }
        if let known = record {
            decideKnown(known, facts)
            return
        }
        let decidedAt = now()
        guard facts.isClean else {
            _ = write(FirstRunRecord(decidedAt: decidedAt, outcome: .notNeeded))
            phase = .done
            return
        }
        phase = write(FirstRunRecord(decidedAt: decidedAt, outcome: .inProgress)) ? .welcome : .done
    }

    /// Sample data and UI test launches: the app opens as usual and nothing is recorded.
    public func suppress() {
        guard phase == .undecided else { return }
        phase = .done
    }

    /// The first run never resumes after the capture: an item already in the Inbox stays there
    /// and the app opens as usual. A device that is still clean (the app was closed on the
    /// welcome or before adding) starts at the welcome again.
    private func decideKnown(_ known: FirstRunRecord, _ facts: FirstRunLaunchFacts) {
        switch known.outcome {
        case .inProgress:
            if facts.hasAccount {
                finish(.signedIn)
            } else if facts.isClean {
                phase = .welcome
            } else {
                finish(facts.hasInboxItem ? .notYet : .skipped)
            }
        case .firstStep where known.tipDismissedAt == nil:
            if facts.hasAccount { finish(.signedIn) } else { phase = .landing }
        case .notNeeded, .skipped, .notYet, .firstStep, .signedIn:
            phase = .done
        }
    }

    // MARK: Steps

    /// Board 01 "Start".
    public func start() {
        guard phase == .welcome else { return }
        phase = .capture
    }

    /// Board 02 "Skip": nothing is added and the Inbox is empty.
    public func skip() {
        switch phase {
        case .welcome, .capture: finish(.skipped)
        default: break
        }
    }

    /// Board 02 "Add to Inbox": one Inbox item with exactly the typed text (trimmed), no Smart
    /// Add parse, then the question. Returns false without writing when the text is empty or
    /// the run is elsewhere; throws when the save failed (nothing changed).
    @discardableResult
    public func capture(_ text: String, in workspace: Workspace, editorID: String = UUID().uuidString) async throws -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard phase == .capture, !trimmed.isEmpty else { return false }
        let id = TaskID.random()
        try await workspace.apply([.createTask(.init(taskID: id, title: trimmed, list: .inbox))], editorID: editorID)
        // The run may have ended meanwhile (a linked account); the item stays in the Inbox.
        guard phase == .capture else { return true }
        capturedText = trimmed
        phase = .firstStep(id)
        return true
    }

    /// Board 03 "Not yet": the item stays in the Inbox unchanged.
    public func notYet() {
        guard case .firstStep = phase else { return }
        finish(.notYet)
    }

    /// Board 03 "Make it my next step": the step becomes the item's text, the captured words go
    /// to its note, and it moves to Next actions, in one save. No project is created. A failed
    /// save throws and leaves the item and the phase as they were.
    @discardableResult
    public func makeNextStep(_ step: String, in workspace: Workspace, editorID: String = UUID().uuidString) async throws -> Bool {
        let trimmed = step.trimmingCharacters(in: .whitespacesAndNewlines)
        guard case .firstStep(let id) = phase, !trimmed.isEmpty else { return false }
        let changes = Self.stepChanges(
            step: trimmed, original: capturedText ?? trimmed, existingDetails: workspace.task(id)?.details)
        try await workspace.apply(
            [
                .updateTask(.init(taskID: id, changes: changes)),
                .transitionTask(.init(taskID: id, action: .move, toList: .next)),
            ], editorID: editorID)
        // The run may have ended while the step was saving; keep that outcome.
        guard phase == .firstStep(id) else { return true }
        if var known = record {
            known.outcome = .firstStep
            _ = write(known)
        }
        phase = .landing
        return true
    }

    /// Board 04 "Got it": the tip never shows again.
    public func dismissTip() {
        guard phase == .landing else { return }
        if var known = record {
            known.tipDismissedAt = now()
            _ = write(known)
        }
        phase = .done
    }

    /// An account was linked at any step ("I have an account", or Settings during the landing).
    public func accountLinked() {
        switch phase {
        case .welcome, .capture, .firstStep, .landing: finish(.signedIn)
        case .undecided, .done: break
        }
    }

    // MARK: Composition

    /// The change the first step makes: the step becomes the title; the captured text goes
    /// first in the note unless it equals the step. No other field changes.
    public static func stepChanges(step: String, original: String, existingDetails: String?) -> TaskChanges {
        var changes = TaskChanges(title: .set(step))
        guard original != step else { return changes }
        let existing = existingDetails?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        changes.details = .set(existing.isEmpty ? original : "\(original)\n\n\(existing)")
        return changes
    }

    // MARK: Record

    private func finish(_ outcome: FirstRunRecord.Outcome) {
        var known = record ?? FirstRunRecord(decidedAt: now(), outcome: outcome)
        known.outcome = outcome
        _ = write(known)
        capturedText = nil
        phase = .done
    }

    /// False (nothing changed) when the record cannot be saved.
    private func write(_ next: FirstRunRecord) -> Bool {
        do {
            try store.save(next)
            record = next
            return true
        } catch {
            return false
        }
    }
}
