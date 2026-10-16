import BrainBuddyCore
import Foundation
import Observation

/// Where the Mac's one-time first run (029) stands. `undecided` shows the normal window.
package enum FirstRunPhase: Hashable, Sendable {
    case undecided, welcome, firstStep(TaskID), landing, done
}

/// What the launch knows about this Mac, read without any network call (029-FR-014).
struct FirstRunLaunchFacts: Sendable {
    var hasAccount = false
    /// `workspaceFirstWrittenAt` was already set before this launch.
    var workspaceWrittenBefore = false
    var legacyImportBroughtTasks = false
    /// Nil while the count is not ready; the synchronous signals alone decide then.
    var openTaskCount: Int?
    var projectCount: Int?
    var hasInboxItem = false
}

/// The two writes the first run makes, both through the existing task commands.
@MainActor
package protocol FirstRunTaskWriting: AnyObject {
    /// An Inbox item with exactly this text; nil when the save failed.
    func captureFirstItem(_ text: String) async -> TaskID?
    /// Sets the step as the title, keeps `original` in the details and moves the task to Next
    /// actions; false (task unchanged) when the save failed. Never creates a project.
    func saveFirstStep(_ id: TaskID, step: String, original: String) async -> Bool
}

/// 029-FR-001 – 029-FR-015: decides once per Mac whether the first run shows, walks it, and
/// records only dates and an outcome in `mac-local.json`. No network, no AI, no permission.
@MainActor
@Observable
package final class FirstRunModel {
    package private(set) var phase: FirstRunPhase = .undecided
    package private(set) var record: FirstRunRecord?
    /// In memory only (never in the record): the text the person captured.
    @ObservationIgnored private var capturedText: String?
    /// Read by the welcome hint and the landing tip; set by the window (PR-02).
    package var hotkeyAvailable = true
    package var speechAvailable = true
    @ObservationIgnored private let store: MacLocalStateStore
    @ObservationIgnored private let now: @Sendable () -> Date

    package init(store: MacLocalStateStore, now: @escaping @Sendable () -> Date = { Date() }) {
        self.store = store
        self.now = now
        record = store.load()?.firstRun
    }

    /// The Inbox while the welcome or the question shows, Next actions for the tip, otherwise nil
    /// (the model's default).
    package var launchDestination: WorkspaceDestination? {
        switch phase {
        case .welcome, .firstStep: .list(.inbox)
        case .landing: .list(.next)
        case .undecided, .done: nil
        }
    }

    package var showsFirstRunSidebar: Bool {
        switch phase {
        case .welcome, .firstStep, .landing: true
        case .undecided, .done: false
        }
    }

    package var landingTip: String { FirstRunCopy.landingTip(hotkeyAvailable: hotkeyAvailable) }

    // MARK: Decision

    func decide(_ facts: FirstRunLaunchFacts) {
        guard phase == .undecided else { return }
        if let known = record {
            decideKnown(known, facts)
            return
        }
        let clean = !facts.hasAccount && !facts.workspaceWrittenBefore && !facts.legacyImportBroughtTasks
            && (facts.openTaskCount ?? 0) == 0 && (facts.projectCount ?? 0) == 0
        let decidedAt = now()
        guard clean else {
            _ = write { $0 = FirstRunRecord(decidedAt: decidedAt, outcome: .notNeeded) }
            phase = .done
            return
        }
        // A record that cannot be written would show the welcome on every launch: skip it instead.
        let remembered = write { $0 = FirstRunRecord(decidedAt: decidedAt, outcome: .inProgress) }
        phase = remembered ? .welcome : .done
    }

    private func decideKnown(_ known: FirstRunRecord, _ facts: FirstRunLaunchFacts) {
        switch known.outcome {
        case .inProgress:
            finish(facts.hasAccount ? .signedIn : (facts.hasInboxItem ? .notYet : .skipped))
        case .firstStep where known.tipDismissedAt == nil:
            if facts.hasAccount { finish(.signedIn) } else { phase = .landing }
        case .notNeeded, .skipped, .notYet, .firstStep, .signedIn:
            phase = .done
        }
    }

    // MARK: Steps

    /// F-01.03: one Inbox item with exactly the typed text (trimmed), then the question.
    @discardableResult
    package func capture(_ text: String, using writer: any FirstRunTaskWriting) async -> Bool {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard phase == .welcome, !trimmed.isEmpty else { return false }
        guard let id = await writer.captureFirstItem(trimmed) else { return false }
        capturedText = trimmed
        phase = .firstStep(id)
        return true
    }

    /// F-01.07: Esc in the welcome.
    package func skip() {
        guard phase == .welcome else { return }
        finish(.skipped)
    }

    /// F-02.06: "Not yet" or Esc in the step field; the item stays in the Inbox unchanged.
    package func notYet() {
        guard case .firstStep = phase else { return }
        finish(.notYet)
    }

    /// F-02.04: "Make it my next step". A failed save leaves the phase and the item as they were.
    @discardableResult
    package func makeNextStep(_ step: String, using writer: any FirstRunTaskWriting) async -> Bool {
        let trimmed = step.trimmingCharacters(in: .whitespacesAndNewlines)
        guard case .firstStep(let id) = phase, !trimmed.isEmpty else { return false }
        guard await writer.saveFirstStep(id, step: trimmed, original: capturedText ?? trimmed) else { return false }
        _ = write { $0?.outcome = .firstStep }
        phase = .landing
        return true
    }

    /// F-03.03: "Got it".
    package func dismissTip() {
        guard phase == .landing else { return }
        let dismissedAt = now()
        _ = write { $0?.tipDismissedAt = dismissedAt }
        phase = .done
    }

    /// 029-FR-013: an account was linked at any step.
    package func accountLinked() {
        switch phase {
        case .welcome, .firstStep, .landing: finish(.signedIn)
        case .undecided, .done: break
        }
    }

    // MARK: Composition

    /// The change the first step makes (029-FR-009): the step becomes the title; the original
    /// capture text goes first in the details unless it equals the step. No other field changes.
    package static func stepChanges(step: String, original: String, existingDetails: String?) -> TaskChanges {
        var changes = TaskChanges(title: .set(step))
        guard original != step else { return changes }
        let existing = existingDetails?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        changes.details = .set(existing.isEmpty ? original : "\(original)\n\n\(existing)")
        return changes
    }

    // MARK: Record

    private func finish(_ outcome: FirstRunRecord.Outcome) {
        _ = write { $0?.outcome = outcome }
        phase = .done
    }

    /// Writes only `firstRun`; false (nothing changed) when the file cannot be written.
    private func write(_ change: (inout FirstRunRecord?) -> Void) -> Bool {
        do {
            let saved = try store.update { local in
                var current = local.firstRun
                change(&current)
                local.firstRun = current
            }
            record = saved.firstRun
            return true
        } catch {
            return false
        }
    }
}
