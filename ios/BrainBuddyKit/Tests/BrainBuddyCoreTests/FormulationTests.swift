import BrainBuddyCore
import Foundation
import Testing

/// Every section of the shared formulation vectors (contracts/formulation-clock.md
/// §6: "Swift — all sections"), run against the pure rule in `Formulation.swift`
/// exactly as `backend/tests/test_review_formulation_vectors.py` runs them
/// against `formulation.py`.
@Suite("Formulation clock: shared vectors (spec 020)")
struct FormulationTests {
    static let vectors = ReviewVectors.formulation

    // MARK: - Normalisation

    @Test(
        "020-FR-002 a title change is substantive iff the formulation keys differ",
        arguments: ReviewVectors.section(vectors, "normalisation")
    )
    func normalisation(_ vector: Vector) throws {
        let old = try #require(vector["old"]?.string)
        let new = try #require(vector["new"]?.string)
        #expect(FormulationKey.key(old) == vector["old_key"]?.string)
        #expect(FormulationKey.key(new) == vector["new_key"]?.string)
        #expect(FormulationKey.isSubstantive(from: old, to: new) == vector["substantive"]?.bool)
    }

    // MARK: - Classification

    @Test(
        "020-FR-004 020-FR-005 020-FR-009 020-FR-012 020-FR-016 020-FR-039 020-FR-046 020-FR-051 class and derived instants",
        arguments: ReviewVectors.section(vectors, "classification")
    )
    func classification(_ vector: Vector) throws {
        let task = try Self.clock(try #require(vector["task"]))
        let settings = try Self.settings(try #require(vector["settings"]))
        let now = try #require(ReviewVectors.instant(vector["now"]))
        #expect(Self.derivedView(task, settings, now) == vector["expect"])
    }

    // MARK: - Transitions

    @Test(
        "020-FR-001 020-FR-002 020-FR-009 020-FR-012 020-FR-016 020-FR-039 020-FR-046 every writer applies the transition table",
        arguments: ReviewVectors.section(vectors, "transitions")
    )
    func transition(_ vector: Vector) throws {
        let before = try #require(vector["before"])
        let expect = try #require(vector["expect"])
        let outcome = Self.run(vector)
        if let reason = expect["error"]?.string {
            guard case .refused(let error) = outcome else {
                Issue.record("expected \(reason), got \(outcome)")
                return
            }
            #expect(error.reason == reason)
            return
        }
        if expect["applied"]?.bool == false {
            guard case .notApplied = outcome else {
                Issue.record("expected the auto-park not to apply, got \(outcome)")
                return
            }
            return
        }
        guard case .done(let result, let settings, let released) = outcome else {
            Issue.record("expected a result, got \(outcome)")
            return
        }
        var expected = before.object
        for (key, value) in expect.object where !["error", "applied", "bulk_clock_before"].contains(key) {
            expected[key] = value
        }
        #expect(Self.encode(result) == .object(expected))
        if let stored = expect["bulk_clock_before"] {
            #expect(released.map(Self.encode) == stored)
        }
        var expectedSettings = try #require(vector["settings"]).object
        for (key, value) in vector["expect_settings"]?.object ?? [:] { expectedSettings[key] = value }
        #expect(Self.encode(settings) == .object(expectedSettings), "the revision rule and owner inputs")
        if let derived = vector["expect_derived"] {
            let now = try #require(ReviewVectors.instant(vector["now"]))
            let view = Self.derivedView(result, settings, now).object
            #expect(VectorValue.object(view.filter { derived.keys.contains($0.key) }) == derived)
        }
    }

    @Test(
        "020-FR-005 a chained transition starts where its predecessor ended",
        arguments: ReviewVectors.section(vectors, "transitions").filter { $0["follows"] != nil }
    )
    func chainedTransition(_ vector: Vector) throws {
        let predecessorID = try #require(vector["follows"]?.string)
        let predecessor = try #require(ReviewVectors.section(Self.vectors, "transitions").first { $0.id == predecessorID })
        guard case .done(let previous, _, _) = Self.run(predecessor) else {
            Issue.record("\(predecessorID) did not produce a task")
            return
        }
        #expect(Self.encode(previous) == vector["before"])
    }

    // MARK: - Queue order

    @Test(
        "020-FR-004 the asks_for_decision aggregate, earliest-asking first",
        arguments: ReviewVectors.section(vectors, "queue_order")
    )
    func queueOrder(_ vector: Vector) throws {
        let settings = try Self.settings(try #require(vector["settings"]))
        let now = try #require(ReviewVectors.instant(vector["now"]))
        let tasks = try (vector["tasks"]?.array ?? []).map { raw in
            (id: raw["id"]?.string ?? "", task: try Self.clock(raw, taskID: raw["id"]?.string ?? ""))
        }
        let order = FormulationRule.decisionQueue(tasks, settings: settings, now: now)
        #expect(order == (vector["expect"]?.array.compactMap(\.string) ?? []))
    }

    @Test("020-FR-004 the vector file holds exactly the sections this suite runs, none empty, ids unique")
    func everySectionIsExercised() {
        let sections = Set(Self.vectors.object.filter { if case .array = $0.value { true } else { false } }.keys)
        #expect(Self.vectors["schema"]?.string == "brainbuddy-formulation-vectors/v1")
        #expect(sections == ["normalisation", "classification", "transitions", "queue_order"])
        let ids = sections.flatMap { ReviewVectors.section(Self.vectors, $0).map(\.id) }
        #expect(!ids.isEmpty && Set(ids).count == ids.count)
        #expect(sections.allSatisfy { !ReviewVectors.section(Self.vectors, $0).isEmpty })
    }

    // MARK: - Reading and writing vector values

    enum Outcome: CustomStringConvertible {
        case done(ClockedTask, OwnerClockSettings, ReleasedClock?)
        case notApplied
        case refused(FormulationRuleError)
        case invalid(String)

        var description: String {
            switch self {
            case .done(let task, _, _): "task \(FormulationTests.encode(task))"
            case .notApplied: "auto-park not applied"
            case .refused(let error): "refused \(error.reason)"
            case .invalid(let reason): "invalid vector: \(reason)"
            }
        }
    }

    struct BadVector: Error, CustomStringConvertible {
        var description: String
    }

    static func run(_ vector: Vector) -> Outcome {
        do {
            let task = try clock(vector["before"] ?? .null)
            let settings = try settings(vector["settings"] ?? .null)
            guard let now = ReviewVectors.instant(vector["now"]) else { throw BadVector(description: "now") }
            return try apply(vector["event"] ?? .null, to: task, settings: settings, now: now)
        } catch let error as FormulationRuleError {
            return .refused(error)
        } catch {
            return .invalid(String(describing: error))
        }
    }

    /// Interprets one vector event, as `apply_event` does in the pytest twin.
    static func apply(
        _ event: VectorValue, to task: ClockedTask, settings: OwnerClockSettings, now: Date
    ) throws -> Outcome {
        func formulationID(_ key: String = "new_formulation_id") -> FormulationID? {
            event[key]?.string.map { FormulationID($0) }
        }
        switch event["type"]?.string {
        case "create_in_next":
            let created = FormulationRule.createInNext(
                title: event["title"]?.string ?? "", formulationID: formulationID() ?? "form_missing", now: now
            )
            return .done(created, settings, nil)
        case "update_title":
            let changed = FormulationRule.changeTitle(
                task, to: event["title"]?.string ?? "", settings: settings, now: now,
                newFormulationID: formulationID() ?? "form_missing"
            )
            return .done(changed, settings, nil)
        case "update_due_date":
            return .done(FormulationRule.changeDueDate(task, to: ReviewVectors.day(event["due_date"]), now: now), settings, nil)
        case "update_other":
            return .done(FormulationRule.editWithoutClock(task), settings, nil)
        case "transition":
            guard let target = event["to"]?.string.flatMap(TaskState.init(rawValue:)) else { throw BadVector(description: "to") }
            let moved = try FormulationRule.move(
                task, to: target, settings: settings, now: now, newFormulationID: formulationID()
            )
            return .done(moved, settings, nil)
        case "decide":
            return .done(try decide(task, event, settings, now), settings, nil)
        case "undo_decision":
            return .done(FormulationRule.restore(task, from: try clock(event["task_before"] ?? .null), settings: settings), settings, nil)
        case "auto_park":
            guard let parked = FormulationRule.autoPark(task, settings: settings, now: now) else { return .notApplied }
            return .done(parked, settings, nil)
        case "yield_reversal":
            let restored = try FormulationRule.reversePark(task)
            return .done(try decide(restored, event["decision"] ?? .null, settings, now), settings, nil)
        case "bulk_release":
            let (released, snapshot) = FormulationRule.release(task, settings: settings, now: now)
            return .done(released, settings, snapshot)
        case "undo_bulk_release":
            guard let previous = event["previous_state"]?.string.flatMap(TaskState.init(rawValue:)) else {
                throw BadVector(description: "previous_state")
            }
            let snapshot = try releasedClock(event["clock_before"] ?? .null)
            return .done(FormulationRule.undoRelease(task, to: previous, restoring: snapshot), settings, nil)
        case "activate":
            guard let at = ReviewVectors.instant(event["at"]) else { throw BadVector(description: "at") }
            let activated = FormulationRule.activateOwner(settings, at: at, timeZone: event["time_zone"]?.string)
            var result = task
            if activated != settings {
                result = FormulationRule.activateClock(
                    task, activatedAt: at, formulationID: formulationID() ?? "form_missing"
                )
            }
            return .done(result, activated, nil)
        case "repair":
            let repaired = FormulationRule.repairClock(task, now: now, formulationID: formulationID() ?? "form_missing")
            return .done(repaired, settings, nil)
        case "sweep_gap":
            return .done(task, FormulationRule.applySweepGap(settings, now: now), nil)
        case "threshold_change":
            guard let days = event["to"]?.int else { throw BadVector(description: "to") }
            return .done(task, FormulationRule.changeThreshold(settings, to: days, now: now), nil)
        case "time_zone_change":
            guard let zone = event["to"]?.string else { throw BadVector(description: "to") }
            let changed = FormulationRule.changeTimeZone(settings, to: zone)
            let result = changed == settings ? task : FormulationRule.raiseDueFloor(task, now: now)
            return .done(result, changed, nil)
        case let other:
            throw BadVector(description: "unknown event \(other ?? "nil")")
        }
    }

    static func decide(
        _ task: ClockedTask, _ decision: VectorValue, _ settings: OwnerClockSettings, _ now: Date
    ) throws -> ClockedTask {
        guard let type = decision["decision_type"]?.string.flatMap(DecisionType.init(rawValue:)) else {
            throw BadVector(description: "decision_type")
        }
        return try FormulationRule.decide(
            task, type, settings: settings, now: now, title: decision["title"]?.string,
            reason: decision["reason"]?.string,
            newFormulationID: decision["new_formulation_id"]?.string.map { FormulationID($0) }
        )
    }

    static func settings(_ raw: VectorValue) throws -> OwnerClockSettings {
        guard let days = raw["threshold_days"]?.int, let zone = raw["time_zone"]?.string else {
            throw BadVector(description: "settings")
        }
        return OwnerClockSettings(
            thresholdDays: days, timeZoneIdentifier: zone, ownerParkFloorAt: ReviewVectors.instant(raw["owner_park_floor_at"]),
            activatedAt: ReviewVectors.instant(raw["activated_at"])
        )
    }

    static func encode(_ settings: OwnerClockSettings) -> VectorValue {
        .object([
            "threshold_days": .number(Double(settings.thresholdDays)), "time_zone": .string(settings.timeZoneIdentifier),
            "owner_park_floor_at": ReviewVectors.iso(settings.ownerParkFloorAt),
            "activated_at": ReviewVectors.iso(settings.activatedAt),
        ])
    }

    /// A clock from a transition `before` or a classification `task`; a started
    /// clock without an id gets `form_<task id>`, as `clock_from` does.
    static func clock(_ raw: VectorValue, taskID: String = "task_vector") throws -> ClockedTask {
        let started = ReviewVectors.instant(raw["formulation_started_at"])
        var formulation: FormulationClock?
        if let started {
            formulation = FormulationClock(
                id: FormulationID(raw["formulation_id"]?.string ?? "form_\(taskID)"), startedAt: started,
                extendedAt: ReviewVectors.instant(raw["formulation_extended_at"]),
                extensionReason: raw["formulation_extension_reason"]?.string,
                parkFloorAt: ReviewVectors.instant(raw["formulation_park_floor_at"])
            )
        }
        var parked: ParkMarker?
        if let marker = raw["parked"], !marker.isNull {
            let before = try #require(marker["clock_before"])
            let formulationID = FormulationID(marker["formulation_id"]?.string ?? "")
            parked = ParkMarker(
                at: try #require(ReviewVectors.instant(marker["at"])), formulationID: formulationID,
                fromRevision: marker["from_revision"]?.int,
                clockBefore: FormulationClock(
                    id: formulationID, startedAt: try #require(ReviewVectors.instant(before["started_at"])),
                    extendedAt: ReviewVectors.instant(before["extended_at"]),
                    extensionReason: before["extension_reason"]?.string,
                    parkFloorAt: ReviewVectors.instant(before["park_floor_at"])
                ),
                stalledBefore: before["stalled_before"]?.int ?? 0
            )
        }
        return ClockedTask(
            state: raw["state"]?.string.flatMap(TaskState.init(rawValue:)), title: raw["title"]?.string,
            revision: raw["revision"]?.int ?? 1, formulation: formulation,
            consecutiveStalledFormulations: raw["consecutive_stalled_formulations"]?.int ?? 0,
            dueDate: ReviewVectors.day(raw["due_date"]), parked: parked
        )
    }

    static func encode(_ task: ClockedTask) -> VectorValue {
        let clock = task.formulation
        var parked = VectorValue.null
        if let marker = task.parked {
            let before = marker.clockBefore
            parked = .object([
                "at": ReviewVectors.iso(marker.at), "formulation_id": .string(marker.formulationID.rawValue),
                "from_revision": marker.fromRevision.map { .number(Double($0)) } ?? .null,
                "clock_before": .object([
                    "started_at": ReviewVectors.iso(before?.startedAt), "extended_at": ReviewVectors.iso(before?.extendedAt),
                    "extension_reason": before?.extensionReason.map(VectorValue.string) ?? .null,
                    "park_floor_at": ReviewVectors.iso(before?.parkFloorAt),
                    "stalled_before": .number(Double(marker.stalledBefore)),
                ]),
            ])
        }
        return .object([
            "state": task.state.map { .string($0.rawValue) } ?? .null,
            "title": task.title.map(VectorValue.string) ?? .null,
            "revision": .number(Double(task.revision)),
            "formulation_id": clock.map { .string($0.id.rawValue) } ?? .null,
            "formulation_started_at": ReviewVectors.iso(clock?.startedAt),
            "formulation_extended_at": ReviewVectors.iso(clock?.extendedAt),
            "formulation_extension_reason": clock?.extensionReason.map(VectorValue.string) ?? .null,
            "formulation_park_floor_at": ReviewVectors.iso(clock?.parkFloorAt),
            "consecutive_stalled_formulations": .number(Double(task.consecutiveStalledFormulations)),
            "due_date": task.dueDate.map { .string($0.isoString) } ?? .null,
            "parked": parked,
        ])
    }

    static func releasedClock(_ raw: VectorValue) throws -> ReleasedClock {
        ReleasedClock(
            clock: FormulationClock(
                id: FormulationID(raw["formulation_id"]?.string ?? ""),
                startedAt: try #require(ReviewVectors.instant(raw["started_at"])),
                extendedAt: ReviewVectors.instant(raw["extended_at"]), extensionReason: raw["extension_reason"]?.string,
                parkFloorAt: ReviewVectors.instant(raw["park_floor_at"])
            ),
            stalledBefore: raw["stalled_before"]?.int ?? 0
        )
    }

    static func encode(_ released: ReleasedClock) -> VectorValue {
        .object([
            "formulation_id": .string(released.clock.id.rawValue), "started_at": ReviewVectors.iso(released.clock.startedAt),
            "extended_at": ReviewVectors.iso(released.clock.extendedAt),
            "extension_reason": released.clock.extensionReason.map(VectorValue.string) ?? .null,
            "park_floor_at": ReviewVectors.iso(released.clock.parkFloorAt),
            "stalled_before": .number(Double(released.stalledBefore)),
        ])
    }

    /// Class, derived instants and aggregates as a classification `expect`.
    static func derivedView(_ task: ClockedTask, _ settings: OwnerClockSettings, _ now: Date) -> VectorValue {
        let instants = FormulationRule.derivedInstants(of: task, settings: settings)
        let klass = FormulationRule.classify(instants, at: now)
        return .object([
            "class": .string(klass.rawValue), "ageing_at": ReviewVectors.iso(instants?.ageingAt),
            "ask_at": ReviewVectors.iso(instants?.askAt), "park_due_at": ReviewVectors.iso(instants?.parkDueAt),
            "paused_until": ReviewVectors.iso(instants?.pausedUntil), "asks_for_decision": .bool(klass.asksForDecision),
            "restart_eligible": .bool(FormulationRule.isRestartEligible(task, settings: settings, now: now)),
            "third_stall": .bool(FormulationRule.isThirdStall(task, settings: settings, now: now)),
        ])
    }
}
