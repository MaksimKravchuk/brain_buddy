import BrainBuddyCore
import Foundation
import Testing

/// Shared helpers for the spec 020 Core tests.
enum Review {
    /// Fri 9 Oct 2026, 14:02 UTC: "today" in the design's example data.
    static let now = instant("2026-10-09T14:02:00Z")
    static let day: TimeInterval = 86_400

    static func instant(_ text: String) -> Date {
        guard let date = try? Date(text, strategy: .iso8601) else { fatalError("bad instant \(text)") }
        return date
    }

    static func form(_ n: Int) -> FormulationID { .make(uuid(n)) }
    static func decision(_ n: Int) -> DecisionID { .make(uuid(n)) }
    static func bulk(_ n: Int) -> BulkID { .make(uuid(n)) }
    static func session(_ n: Int) -> ReviewSessionID { .make(uuid(n)) }
    static func progress(_ n: Int) -> ProgressID { .make(uuid(n)) }

    static func uuid(_ n: Int) -> UUID {
        let digits = String(n)
        return UUID(uuidString: "00000000-0000-4000-8000-" + String(repeating: "0", count: 12 - digits.count) + digits)!
    }

    /// Settings of an owner activated at `activatedAt`.
    static func settings(threshold: Int = 14, zone: String = "Europe/Berlin", activatedAt: Date? = instant("2026-09-01T08:00:00Z"))
        -> ReviewSettings
    {
        ReviewSettings(thresholdDays: threshold, timeZone: zone, activatedAt: activatedAt)
    }

    /// A state with `tasks` and the given review settings, with the review
    /// exposed (as on an account-less device whose release switch is on).
    static func state(_ tasks: [TaskRecord], settings: ReviewSettings = settings()) -> GTDState {
        var review = ReviewState(settings: settings)
        review.accountlessReleaseSwitch = true
        return GTDState(tasks: Dictionary(uniqueKeysWithValues: tasks.map { ($0.id, $0) }), review: review)
    }

    /// A Next task whose formulation started at `started`.
    static func nextTask(
        _ id: TaskID, title: String = "Call Bob", started: Date, formulation: FormulationID = form(1),
        stalled: Int = 0, extendedAt: Date? = nil, due: CalendarDay? = nil, project: ProjectID? = nil,
        serverRevision: Int? = nil, orderKey: Int = 0
    ) -> TaskRecord {
        TaskRecord(
            id: id, serverID: serverRevision.map { _ in "task_\(id.rawValue)" }, serverRevision: serverRevision,
            title: title, state: .next, projectID: project, dueDate: due, orderKey: orderKey, createdAt: started,
            updatedAt: started,
            formulation: FormulationClock(
                id: formulation, startedAt: started, extendedAt: extendedAt,
                extensionReason: extendedAt == nil ? nil : "Waiting for the quote"
            ),
            consecutiveStalledFormulations: stalled
        )
    }

    static func task(_ id: TaskID, title: String, state: TaskState, at date: Date = now, orderKey: Int = 0) -> TaskRecord {
        TaskRecord(id: id, title: title, state: state, orderKey: orderKey, createdAt: date, updatedAt: date)
    }

    static func op(_ command: GTDCommand, at date: Date) -> PendingOperation {
        PendingOperation(command: command, issuedAt: date)
    }

    @discardableResult
    static func apply(
        _ command: GTDCommand, at date: Date = now, to state: inout GTDState, mode: ApplyMode = .interactive
    ) throws(GTDValidationError) -> ApplyOutcome {
        try GTDReducer.apply(command, at: date, to: &state, mode: mode)
    }

    static func decide(
        _ type: DecisionType, _ task: TaskID, decision: Int = 1, formulation: FormulationID? = nil, title: String? = nil,
        waitingFor: String? = nil, reason: String? = nil, newFormulation: FormulationID? = nil, session: ReviewSessionID? = nil,
        followUp: TaskID? = nil
    ) -> GTDCommand {
        .decideTask(
            .init(
                decisionID: Review.decision(decision), taskID: task, type: type, formulationID: formulation,
                newFormulationID: newFormulation, title: title, waitingFor: waitingFor, reason: reason, sessionID: session,
                followUpTaskID: followUp
            )
        )
    }

    /// The error `body` throws, if any.
    static func error(_ body: () throws -> Void) -> GTDValidationError? {
        do {
            try body()
            return nil
        } catch let error as GTDValidationError {
            return error
        } catch {
            Issue.record("unexpected error \(error)")
            return nil
        }
    }
}
