import Foundation

// The formulation clock (spec 020, contracts/formulation-clock.md): the one
// shared rule the backend (`formulation.py`), this file and the web
// (`formulation.ts`) implement and run against the same vector file. Every
// function here is pure: no clock of its own, no storage. Instants are UTC
// `Date`s; "days" are exact 86 400-second spans, and only the start of a due
// day uses the owner's local calendar (§4).

public enum FormulationKind {}
public enum DecisionKind {}
public enum BulkReleaseKind {}
public enum ReviewSessionKind {}
public enum ProgressKind {}

/// `form_<lowercased UUID>`, minted in the command that starts a formulation
/// and sent as `new_formulation_id` (contracts/http.md "Client-supplied ids").
public typealias FormulationID = EntityID<FormulationKind>
/// `decision_<lowercased UUID>`.
public typealias DecisionID = EntityID<DecisionKind>
/// `bulk_<lowercased UUID>`.
public typealias BulkID = EntityID<BulkReleaseKind>
/// `review_<lowercased UUID>`.
public typealias ReviewSessionID = EntityID<ReviewSessionKind>
/// `progress_<lowercased UUID>`.
public typealias ProgressID = EntityID<ProgressKind>

/// The one shape of a client-supplied id: `<prefix>_<lowercased UUID>`, at most
/// 64 characters, so no free text can travel in an id (contracts/http.md).
public enum ClientID {
    public static func make(_ prefix: String, _ uuid: UUID) -> String { "\(prefix)_\(uuid.uuidString.lowercased())" }

    /// A deterministic id of the same shape, for a formulation a command
    /// written before spec 020 starts without carrying one (replay must give
    /// the same id every time).
    public static func derived(_ prefix: String, from seed: String) -> String {
        var first: UInt64 = 0xCBF2_9CE4_8422_2325
        var second: UInt64 = 0x8422_2325_CBF2_9CE4
        for byte in seed.utf8 {
            first = (first ^ UInt64(byte)) &* 0x0000_0100_0000_01B3
            second = (second ^ UInt64(byte)) &* 0x0000_0100_0000_01B3 &+ 0x9E37_79B9
        }
        func hex(_ value: UInt64) -> String {
            let digits = String(value, radix: 16)
            return String(repeating: "0", count: 16 - digits.count) + digits
        }
        let text = Array(hex(first) + hex(second))
        let groups = [0..<8, 8..<12, 12..<16, 16..<20, 20..<32].map { String(text[$0]) }
        return "\(prefix)_" + groups.joined(separator: "-")
    }

    /// Whether `value` is `<prefix>_<lowercased UUID>`.
    public static func isValid(_ value: String, prefix: String) -> Bool {
        guard value.hasPrefix(prefix + "_"), value.utf8.count <= 64 else { return false }
        let uuid = Array(value.utf8.dropFirst(prefix.utf8.count + 1))
        guard uuid.count == 36 else { return false }
        for (index, byte) in uuid.enumerated() {
            if [8, 13, 18, 23].contains(index) {
                guard byte == UInt8(ascii: "-") else { return false }
            } else {
                guard (48...57).contains(byte) || (97...102).contains(byte) else { return false }
            }
        }
        return true
    }
}

extension EntityID where Kind == FormulationKind {
    public static func make(_ uuid: UUID) -> FormulationID { FormulationID(ClientID.make("form", uuid)) }
}

extension EntityID where Kind == DecisionKind {
    public static func make(_ uuid: UUID) -> DecisionID { DecisionID(ClientID.make("decision", uuid)) }
}

extension EntityID where Kind == BulkReleaseKind {
    public static func make(_ uuid: UUID) -> BulkID { BulkID(ClientID.make("bulk", uuid)) }
}

extension EntityID where Kind == ReviewSessionKind {
    public static func make(_ uuid: UUID) -> ReviewSessionID { ReviewSessionID(ClientID.make("review", uuid)) }
}

extension EntityID where Kind == ProgressKind {
    public static func make(_ uuid: UUID) -> ProgressID { ProgressID(ClientID.make("progress", uuid)) }
}

// MARK: - §1 Formulation key

/// FR-002: `formulation_key(title)` — NFKC, every punctuation scalar (`Pc Pd Ps
/// Pe Pi Pf Po`) to one space, whitespace collapsed as Python's `split()`,
/// then Python's `casefold()`. It is `NameNormalizer.project` with the one
/// extra punctuation step, reusing its collapse and case folding.
public enum FormulationKey {
    public static func key(_ title: String) -> String {
        var spaced = String.UnicodeScalarView()
        for scalar in title.precomposedStringWithCompatibilityMapping.unicodeScalars {
            spaced.append(isPunctuation(scalar) ? " " : scalar)
        }
        return NameNormalizer.caseFolded(NameNormalizer.collapsed(String(spaced)))
    }

    /// General Category P* (`Pc Pd Ps Pe Pi Pf Po`); symbols, digits,
    /// letters, marks and emoji are kept.
    static func isPunctuation(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .connectorPunctuation, .dashPunctuation, .openPunctuation, .closePunctuation, .initialPunctuation,
            .finalPunctuation, .otherPunctuation:
            true
        default:
            false
        }
    }

    /// A title change is substantive iff the keys differ.
    public static func isSubstantive(from old: String, to new: String) -> Bool {
        key(old) != key(new)
    }
}

// MARK: - §2 Clock fields

/// The clock of the current formulation of a task in Next (§2).
public struct FormulationClock: Hashable, Sendable, Codable {
    public var id: FormulationID
    public var startedAt: Date
    public var extendedAt: Date?
    public var extensionReason: String?
    public var parkFloorAt: Date?

    public init(
        id: FormulationID, startedAt: Date, extendedAt: Date? = nil, extensionReason: String? = nil,
        parkFloorAt: Date? = nil
    ) {
        self.id = id
        self.startedAt = startedAt
        self.extendedAt = extendedAt
        self.extensionReason = extensionReason
        self.parkFloorAt = parkFloorAt
    }
}

/// `parked`: written only by auto-park. `clockBefore` is the clock as it was
/// immediately before the park closed it (local parks; a pulled park carries
/// none, the server keeps its own), so a yield reversal restores it exactly.
public struct ParkMarker: Hashable, Sendable, Codable {
    public var at: Date
    public var formulationID: FormulationID
    public var fromRevision: Int?
    public var clockBefore: FormulationClock?
    public var stalledBefore: Int

    public init(
        at: Date, formulationID: FormulationID, fromRevision: Int? = nil, clockBefore: FormulationClock? = nil,
        stalledBefore: Int = 0
    ) {
        self.at = at
        self.formulationID = formulationID
        self.fromRevision = fromRevision
        self.clockBefore = clockBefore
        self.stalledBefore = stalledBefore
    }
}

/// A Next task's clock as a bulk-release record stores it (data-model E7).
public struct ReleasedClock: Hashable, Sendable, Codable {
    public var clock: FormulationClock
    public var stalledBefore: Int

    public init(clock: FormulationClock, stalledBefore: Int) {
        self.clock = clock
        self.stalledBefore = stalledBefore
    }
}

/// The owner-level inputs of the rule (§2).
public struct OwnerClockSettings: Hashable, Sendable {
    public static let allowedThresholds: Set<Int> = [7, 14, 21, 28]

    public var thresholdDays: Int
    /// The IANA name as stored (`UTC` stays `UTC`).
    public var timeZoneIdentifier: String
    public var ownerParkFloorAt: Date?
    /// While nil the owner is not activated: every task is `none`, nothing parks.
    public var activatedAt: Date?

    public init(thresholdDays: Int, timeZoneIdentifier: String, ownerParkFloorAt: Date? = nil, activatedAt: Date? = nil) {
        self.thresholdDays = thresholdDays
        self.timeZoneIdentifier = timeZoneIdentifier
        self.ownerParkFloorAt = ownerParkFloorAt
        self.activatedAt = activatedAt
    }

    /// The zone due days start in; an unknown name counts as UTC.
    public var timeZone: TimeZone {
        TimeZone(identifier: timeZoneIdentifier) ?? TimeZone(secondsFromGMT: 0)!
    }
}

/// The fields of a task the rule reads and writes (§2 plus state, title and
/// the server's revision, which only the vectors and the fake server count).
public struct ClockedTask: Hashable, Sendable {
    public var state: TaskState?
    public var title: String?
    public var revision: Int
    public var formulation: FormulationClock?
    public var consecutiveStalledFormulations: Int
    public var dueDate: CalendarDay?
    public var parked: ParkMarker?

    public init(
        state: TaskState?, title: String?, revision: Int = 1, formulation: FormulationClock? = nil,
        consecutiveStalledFormulations: Int = 0, dueDate: CalendarDay? = nil, parked: ParkMarker? = nil
    ) {
        self.state = state
        self.title = title
        self.revision = revision
        self.formulation = formulation
        self.consecutiveStalledFormulations = consecutiveStalledFormulations
        self.dueDate = dueDate
        self.parked = parked
    }
}

/// §4 instants; `start` is the effective start (due day included).
public struct DerivedInstants: Hashable, Sendable {
    public var start: Date
    public var ageingAt: Date
    public var askAt: Date
    public var parkDueAt: Date
    public var tomorrowAt: Date
    public var pausedUntil: Date?
}

/// §5 classes, with the wire spelling as raw value.
public enum FormulationClass: String, Hashable, Sendable, Codable, CaseIterable {
    case none, paused
    case parkDue = "park_due"
    case movesTomorrow = "moves_tomorrow"
    case asks, ageing, fresh

    /// The one "asks for a decision" aggregate (FR-004): asks, moves
    /// tomorrow and a park that is due but not applied yet.
    public var asksForDecision: Bool { self == .asks || self == .movesTomorrow || self == .parkDue }
}

/// The decision types of contracts/http.md §3.
public enum DecisionType: String, Hashable, Sendable, Codable, CaseIterable {
    case complete, reformulate
    case firstStep = "first_step"
    case waiting, someday, cancel, extend
    case keepWaiting = "keep_waiting"
    case followUp = "follow_up"
    case returnToNext = "return_to_next"
    case keepSomeday = "keep_someday"

    /// The lists a task may be in for this decision.
    public var allowedStates: Set<TaskState> {
        switch self {
        case .complete, .cancel: [.inbox, .next, .waiting, .someday]
        case .reformulate, .firstStep, .waiting, .someday, .extend: [.next]
        case .keepWaiting, .followUp: [.waiting]
        case .returnToNext: [.waiting, .someday]
        case .keepSomeday: [.someday]
        }
    }

    /// Decisions on the current formulation of a Next task, which name it.
    public var decidesOnFormulation: Bool {
        switch self {
        case .reformulate, .firstStep, .waiting, .someday, .extend: true
        case .complete, .cancel, .keepWaiting, .followUp, .returnToNext, .keepSomeday: false
        }
    }
}

/// A decision the rule refuses; `reason` is the HTTP `detail.reason`.
public enum FormulationRuleError: Error, Hashable, Sendable {
    case decisionNotAllowed
    case extensionAlreadyUsed
    case extensionNotDue

    public var reason: String {
        switch self {
        case .decisionNotAllowed: "decision_not_allowed"
        case .extensionAlreadyUsed: "extension_already_used"
        case .extensionNotDue: "extension_not_due"
        }
    }
}

// MARK: - The rule

public enum FormulationRule {
    public static let day: TimeInterval = 86_400
    public static let parkAfterAsk = 7 * day
    public static let extensionLength = 7 * day
    public static let movesTomorrowWindow = day
    public static let dueDateFloor = 7 * day
    public static let thresholdChangeFloor = 7 * day
    public static let sweepGapFloor = 7 * day
    public static let activationGrace = 14 * day
    public static let repairGrace = 14 * day
    public static let restartAge = 28 * day
    public static let stallsBeforeThird = 2

    // MARK: §4 Derived instants

    /// The first instant of `day` in `zone`: midnight, or the end of a
    /// daylight-saving gap that swallows it (Python's `fold=0`).
    public static func dueStart(_ day: CalendarDay, in zone: TimeZone) -> Date {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        return day.startDate(in: calendar)
    }

    /// §4 for a started clock in Next of an activated owner, else nil.
    public static func derivedInstants(of task: ClockedTask, settings: OwnerClockSettings) -> DerivedInstants? {
        guard settings.activatedAt != nil, task.state == .next, let clock = task.formulation else { return nil }
        var start = clock.startedAt
        var pausedUntil: Date?
        if let dueDate = task.dueDate {
            let due = dueStart(dueDate, in: settings.timeZone)
            if due > start {
                start = due
                pausedUntil = due
            }
        }
        let threshold = TimeInterval(settings.thresholdDays) * day
        var askAt = start.addingTimeInterval(threshold)
        if let extended = clock.extendedAt { askAt = max(askAt, extended).addingTimeInterval(extensionLength) }
        var parkDueAt = askAt.addingTimeInterval(parkAfterAsk)
        if let floor = clock.parkFloorAt { parkDueAt = max(parkDueAt, floor) }
        if let floor = settings.ownerParkFloorAt { parkDueAt = max(parkDueAt, floor) }
        return DerivedInstants(
            start: start, ageingAt: start.addingTimeInterval(threshold / 2), askAt: askAt, parkDueAt: parkDueAt,
            tomorrowAt: parkDueAt.addingTimeInterval(-movesTomorrowWindow), pausedUntil: pausedUntil
        )
    }

    // MARK: §5 Classification

    public static func classify(_ instants: DerivedInstants?, at now: Date) -> FormulationClass {
        guard let instants else { return .none }
        if let paused = instants.pausedUntil, now < paused { return .paused }
        if now >= instants.parkDueAt { return .parkDue }
        if now >= instants.tomorrowAt { return .movesTomorrow }
        if now >= instants.askAt { return .asks }
        if now >= instants.ageingAt { return .ageing }
        return .fresh
    }

    public static func classify(_ task: ClockedTask, settings: OwnerClockSettings, now: Date) -> FormulationClass {
        classify(derivedInstants(of: task, settings: settings), at: now)
    }

    /// FR-017: not paused and at least 28 days since the effective start.
    public static func isRestartEligible(_ task: ClockedTask, settings: OwnerClockSettings, now: Date) -> Bool {
        guard let instants = derivedInstants(of: task, settings: settings),
            classify(instants, at: now) != .paused
        else { return false }
        return now.timeIntervalSince(instants.start) >= restartAge
    }

    /// FR-005: asking with at least two stalled formulations before this one.
    public static func isThirdStall(_ task: ClockedTask, settings: OwnerClockSettings, now: Date) -> Bool {
        classify(task, settings: settings, now: now).asksForDecision
            && task.consecutiveStalledFormulations >= stallsBeforeThird
    }

    /// The ids of the tasks that ask for a decision, earliest-asking first:
    /// ascending `ask_at`, then ascending start, then id (§5).
    public static func decisionQueue<ID: Comparable>(
        _ tasks: [(id: ID, task: ClockedTask)], settings: OwnerClockSettings, now: Date
    ) -> [ID] {
        var asking: [(askAt: Date, startedAt: Date, id: ID)] = []
        for (id, task) in tasks {
            guard let instants = derivedInstants(of: task, settings: settings), let started = task.formulation?.startedAt,
                classify(instants, at: now).asksForDecision
            else { continue }
            asking.append((instants.askAt, started, id))
        }
        asking.sort { lhs, rhs in
            if lhs.askAt != rhs.askAt { return lhs.askAt < rhs.askAt }
            if lhs.startedAt != rhs.startedAt { return lhs.startedAt < rhs.startedAt }
            return lhs.id < rhs.id
        }
        return asking.map(\.id)
    }

    // MARK: §3 Transitions

    /// A new formulation at `now`; extension, floor and park cleared.
    public static func startFormulation(_ task: ClockedTask, id: FormulationID, now: Date) -> ClockedTask {
        var started = task
        started.formulation = FormulationClock(id: id, startedAt: now)
        started.parked = nil
        return started
    }

    /// Whether the open formulation reached "asks for a decision" by `now`
    /// (FR-005): it was extended (only possible once it asked) or `now >= ask_at`.
    public static func reachedAsk(_ task: ClockedTask, settings: OwnerClockSettings, now: Date) -> Bool {
        guard let clock = task.formulation else { return false }
        if clock.extendedAt != nil { return true }
        var inNext = task
        inNext.state = .next
        guard let instants = derivedInstants(of: inNext, settings: settings) else { return false }
        return now >= instants.askAt
    }

    /// Closes the current formulation with the FR-005 stalled-count rule; a
    /// clock that never started leaves the count alone.
    public static func closeFormulation(_ task: ClockedTask, settings: OwnerClockSettings, now: Date) -> ClockedTask {
        var closed = task
        if task.formulation != nil {
            closed.consecutiveStalledFormulations =
                reachedAsk(task, settings: settings, now: now) ? task.consecutiveStalledFormulations + 1 : 0
        }
        closed.formulation = nil
        return closed
    }

    private static func bump(_ task: ClockedTask) -> ClockedTask {
        var bumped = task
        bumped.revision += 1
        return bumped
    }

    /// A task created in Next starts its first formulation (revision 1).
    public static func createInNext(title: String, formulationID: FormulationID, now: Date) -> ClockedTask {
        ClockedTask(
            state: .next, title: title, revision: 1, formulation: FormulationClock(id: formulationID, startedAt: now)
        )
    }

    /// A title edit: a substantive change in Next closes and restarts the clock.
    public static func changeTitle(
        _ task: ClockedTask, to title: String, settings: OwnerClockSettings, now: Date, newFormulationID: FormulationID
    ) -> ClockedTask {
        var changed = task
        if task.state == .next, FormulationKey.isSubstantive(from: task.title ?? "", to: title) {
            changed = closeFormulation(task, settings: settings, now: now)
            changed = startFormulation(changed, id: newFormulationID, now: now)
        }
        changed.title = title
        return bump(changed)
    }

    /// Due date set, moved or removed: in Next the task floor rises (FR-046).
    public static func changeDueDate(_ task: ClockedTask, to dueDate: CalendarDay?, now: Date) -> ClockedTask {
        var changed = task
        changed.dueDate = dueDate
        if task.state == .next { changed = raiseTaskFloor(changed, to: now.addingTimeInterval(dueDateFloor)) }
        return bump(changed)
    }

    /// Notes, tags, project, priority, subtasks, comments, waiting-for (FR-003).
    public static func editWithoutClock(_ task: ClockedTask) -> ClockedTask { bump(task) }

    public static func raiseTaskFloor(_ task: ClockedTask, to floor: Date) -> ClockedTask {
        guard var clock = task.formulation else { return task }
        clock.parkFloorAt = max(clock.parkFloorAt ?? floor, floor)
        var raised = task
        raised.formulation = clock
        return raised
    }

    /// A move between lists without the revision bump.
    public static func relocate(
        _ task: ClockedTask, to target: TaskState, settings: OwnerClockSettings, now: Date,
        newFormulationID: FormulationID?
    ) -> ClockedTask {
        guard target != task.state else { return task }
        var changed = task
        if task.state == .next { changed = closeFormulation(changed, settings: settings, now: now) }
        if task.state == .someday { changed.parked = nil }
        if target == .next {
            changed = startFormulation(changed, id: newFormulationID ?? FormulationID("form_missing"), now: now)
        }
        changed.state = target
        return changed
    }

    /// A move, reopen, completion or cancellation (one task write).
    public static func move(
        _ task: ClockedTask, to target: TaskState, settings: OwnerClockSettings, now: Date,
        newFormulationID: FormulationID? = nil
    ) throws(FormulationRuleError) -> ClockedTask {
        bump(relocate(task, to: target, settings: settings, now: now, newFormulationID: newFormulationID))
    }

    /// The one-time "keep 7 more days" (FR-009), checked in a fixed order.
    public static func extend(
        _ task: ClockedTask, reason: String, settings: OwnerClockSettings, now: Date
    ) throws(FormulationRuleError) -> ClockedTask {
        guard task.state == .next, var clock = task.formulation else { throw .decisionNotAllowed }
        guard clock.extendedAt == nil else { throw .extensionAlreadyUsed }
        guard classify(task, settings: settings, now: now).asksForDecision else { throw .extensionNotDue }
        clock.extendedAt = now
        clock.extensionReason = reason
        var extended = task
        extended.formulation = clock
        return bump(extended)
    }

    /// "Find a first step" always starts a new formulation (FR-008).
    public static func firstStep(
        _ task: ClockedTask, title: String, settings: OwnerClockSettings, now: Date, newFormulationID: FormulationID
    ) -> ClockedTask {
        var started = startFormulation(closeFormulation(task, settings: settings, now: now), id: newFormulationID, now: now)
        started.title = title
        return bump(started)
    }

    /// The clock effect of a decision of the http §3 type table.
    /// `keep_waiting`, `keep_someday` and `follow_up` leave the decided task
    /// unchanged (they write a receipt or create another task).
    public static func decide(
        _ task: ClockedTask, _ type: DecisionType, settings: OwnerClockSettings, now: Date, title: String? = nil,
        reason: String? = nil, newFormulationID: FormulationID? = nil
    ) throws(FormulationRuleError) -> ClockedTask {
        guard let state = task.state, type.allowedStates.contains(state) else { throw .decisionNotAllowed }
        let newID = newFormulationID ?? FormulationID("form_missing")
        switch type {
        case .extend:
            return try extend(task, reason: reason ?? "", settings: settings, now: now)
        case .reformulate:
            return changeTitle(task, to: title ?? task.title ?? "", settings: settings, now: now, newFormulationID: newID)
        case .firstStep:
            return firstStep(task, title: title ?? task.title ?? "", settings: settings, now: now, newFormulationID: newID)
        case .complete:
            return try move(task, to: .completed, settings: settings, now: now)
        case .cancel:
            return try move(task, to: .cancelled, settings: settings, now: now)
        case .waiting:
            return try move(task, to: .waiting, settings: settings, now: now)
        case .someday:
            return try move(task, to: .someday, settings: settings, now: now)
        case .returnToNext:
            var moved = try move(task, to: .next, settings: settings, now: now, newFormulationID: newID)
            if let title { moved.title = title }
            return moved
        case .keepWaiting, .keepSomeday, .followUp:
            return task
        }
    }

    /// Parks a task whose own evaluation is `park_due`; nil if it is not due.
    /// The clock is captured before it is closed, so a yield reversal can
    /// restore it without closing the formulation twice.
    public static func autoPark(_ task: ClockedTask, settings: OwnerClockSettings, now: Date) -> ClockedTask? {
        guard classify(task, settings: settings, now: now) == .parkDue, let clock = task.formulation else { return nil }
        let marker = ParkMarker(
            at: now, formulationID: clock.id, fromRevision: task.revision, clockBefore: clock,
            stalledBefore: task.consecutiveStalledFormulations
        )
        var parked = closeFormulation(task, settings: settings, now: now)
        parked.state = .someday
        parked.parked = marker
        return bump(parked)
    }

    public struct NotParked: Error, Hashable, Sendable {}

    /// Yield reversal: restores `clock_before` exactly, without the revision
    /// bump (the yielding decision bumps it).
    public static func reversePark(_ task: ClockedTask) throws(NotParked) -> ClockedTask {
        guard let marker = task.parked, var clock = marker.clockBefore else { throw NotParked() }
        clock.id = marker.formulationID
        var restored = task
        restored.state = .next
        restored.formulation = clock
        restored.consecutiveStalledFormulations = marker.stalledBefore
        restored.parked = nil
        return restored
    }

    /// A person's release to Someday (restart or Inbox-remainder bulk
    /// release): the released task and, for a Next task with a clock, the
    /// clock the bulk-release record stores.
    public static func release(
        _ task: ClockedTask, settings: OwnerClockSettings, now: Date
    ) -> (task: ClockedTask, released: ReleasedClock?) {
        var snapshot: ReleasedClock?
        if task.state == .next, let clock = task.formulation {
            snapshot = ReleasedClock(clock: clock, stalledBefore: task.consecutiveStalledFormulations)
        }
        var released = relocate(task, to: .someday, settings: settings, now: now, newFormulationID: nil)
        released.parked = nil
        return (bump(released), snapshot)
    }

    /// Returns a released task to its list with its stored clock, exactly.
    public static func undoRelease(_ task: ClockedTask, to previous: TaskState, restoring released: ReleasedClock?)
        -> ClockedTask
    {
        var restored = task
        restored.state = previous
        restored.parked = nil
        if let released {
            restored.formulation = released.clock
            restored.consecutiveStalledFormulations = released.stalledBefore
        }
        return bump(restored)
    }

    /// Decision Undo: the snapshot at `revision + 1`, keeping the bookkeeping
    /// written since the decision (FR-048, §3 "decision undo"). A task restored
    /// into Next keeps the larger of the snapshot's park floor and the current
    /// task's (counted only while it is in Next), and a formulation that
    /// started before the activation instant gets the activation clamp.
    public static func restore(_ task: ClockedTask, from snapshot: ClockedTask, settings: OwnerClockSettings) -> ClockedTask {
        var restored = snapshot
        restored.revision = task.revision + 1
        guard restored.state == .next else { return restored }
        let floors = [snapshot.formulation?.parkFloorAt, task.state == .next ? task.formulation?.parkFloorAt : nil]
        if let floor = floors.compactMap({ $0 }).max() { restored.formulation?.parkFloorAt = floor }
        if let activatedAt = settings.activatedAt, let clock = restored.formulation, clock.startedAt < activatedAt {
            restored = activateClock(restored, activatedAt: activatedAt, formulationID: clock.id)
        }
        return restored
    }

    // MARK: Clock bookkeeping (no revision bump)

    /// The activation clamp for one task (FR-016).
    public static func activateClock(_ task: ClockedTask, activatedAt: Date, formulationID: FormulationID) -> ClockedTask {
        guard task.state == .next else { return task }
        var changed = task
        if let clock = task.formulation {
            var clamped = clock
            clamped.startedAt = max(clock.startedAt, activatedAt)
            changed.formulation = clamped
        } else {
            changed = startFormulation(task, id: formulationID, now: activatedAt)
        }
        return raiseTaskFloor(changed, to: activatedAt.addingTimeInterval(activationGrace))
    }

    /// Starts a missing clock on a Next task (old-client save, rollback).
    public static func repairClock(_ task: ClockedTask, now: Date, formulationID: FormulationID) -> ClockedTask {
        guard task.state == .next, task.formulation == nil else { return task }
        var repaired = startFormulation(task, id: formulationID, now: now)
        repaired.formulation?.parkFloorAt = now.addingTimeInterval(repairGrace)
        return repaired
    }

    /// Time-zone change: a due-dated Next task cannot park within 7 days.
    public static func raiseDueFloor(_ task: ClockedTask, now: Date) -> ClockedTask {
        guard task.state == .next, task.dueDate != nil else { return task }
        return raiseTaskFloor(task, to: now.addingTimeInterval(dueDateFloor))
    }

    // MARK: Owner settings

    /// First acknowledgement wins; a later one returns `settings` unchanged.
    public static func activateOwner(_ settings: OwnerClockSettings, at: Date, timeZone: String? = nil)
        -> OwnerClockSettings
    {
        guard settings.activatedAt == nil else { return settings }
        var activated = settings
        activated.activatedAt = at
        if let timeZone { activated.timeZoneIdentifier = timeZone }
        return activated
    }

    private static func raiseOwnerFloor(_ settings: OwnerClockSettings, to floor: Date) -> OwnerClockSettings {
        var raised = settings
        raised.ownerParkFloorAt = max(settings.ownerParkFloorAt ?? floor, floor)
        return raised
    }

    /// After a sweep gap of 24 h or more, no park within 7 days (SC-006).
    public static func applySweepGap(_ settings: OwnerClockSettings, now: Date) -> OwnerClockSettings {
        raiseOwnerFloor(settings, to: now.addingTimeInterval(sweepGapFloor))
    }

    /// FR-039: a real change floors every park for 7 days; equal is no change.
    public static func changeThreshold(_ settings: OwnerClockSettings, to days: Int, now: Date) -> OwnerClockSettings {
        guard days != settings.thresholdDays else { return settings }
        var changed = settings
        changed.thresholdDays = days
        return raiseOwnerFloor(changed, to: now.addingTimeInterval(thresholdChangeFloor))
    }

    /// A zone equal to the stored one is no change.
    public static func changeTimeZone(_ settings: OwnerClockSettings, to zone: String) -> OwnerClockSettings {
        guard zone != settings.timeZoneIdentifier else { return settings }
        var changed = settings
        changed.timeZoneIdentifier = zone
        return changed
    }
}
