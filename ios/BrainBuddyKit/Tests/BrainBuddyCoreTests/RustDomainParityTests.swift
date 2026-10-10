import Foundation
import Testing

@testable import BrainBuddyCore

// The Apple facade over the shared Rust rules (spec 026, T017). The compiled `bb-swift`
// library is linked for real, on Linux and on Apple platforms. The rules themselves are held
// by the `bb-domain` parity suites; these tests are about the seam:
//
// * every command and query is decided by exactly one image: `RuleEpoch.rust` never reaches
//   the Swift handlers, `RuleEpoch.legacy` never reaches the core;
// * where the Swift rules and the shared rules are one rule, the two images give the same
//   result. Comparing them is the job of this test target only: no mutation runs both;
// * the mapping (identifiers, instants, PATCH members, refusals) is exact.
//
// `rust/bindings/swift/tests/apple_wire.rs` runs the same scenario and wire shapes against the
// core from the Rust side.

private let utcCalendar: Calendar = {
    var calendar = Calendar(identifier: .gregorian)
    calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
    return calendar
}()

/// 2026-09-21T14:13:20Z.
private let start = Date(timeIntervalSince1970: 1_790_000_000)

private func moment(_ minutes: Int) -> Date { start.addingTimeInterval(Double(minutes) * 60) }

private func uuid(_ number: Int) -> String {
    let digits = String(number)
    return "00000000-0000-4000-8000-" + String(repeating: "0", count: 12 - digits.count) + digits
}

private func taskID(_ number: Int) -> TaskID { TaskID(uuid(number)) }
private func projectID(_ number: Int) -> ProjectID { ProjectID(uuid(number)) }
private func tagID(_ number: Int) -> TagID { TagID(uuid(number)) }

private func makeFacade() throws -> RustDomainFacade {
    RustDomainFacade(runtime: try RustBridgeRuntime(), context: RustDomainContext(deviceTimeZone: "UTC"))
}

/// What a state shows of its rules, without the fields only one image maintains (instants,
/// revisions, order keys): one line per record, sorted.
private func shape(_ state: GTDState) -> [String] {
    var lines: [String] = []
    for task in state.tasks.values {
        let tags = task.tagIDs.map(\.rawValue).sorted().joined(separator: ",")
        let fields: [String] = [
            task.id.rawValue, task.title, task.state.rawValue, task.projectID?.rawValue ?? "-", tags,
            task.dueDate?.isoString ?? "-", task.priority.rawValue, task.details ?? "-", task.waitingFor ?? "-",
            task.formulation?.id.rawValue ?? "-", task.lastOpenList?.rawValue ?? "-",
        ]
        lines.append("task " + fields.joined(separator: " | "))
        for subtask in task.subtasks {
            lines.append("subtask \(subtask.id.rawValue) | \(subtask.title) | \(subtask.state.rawValue)")
        }
        for comment in task.comments {
            lines.append("comment \(comment.id.rawValue) | \(comment.body)")
        }
    }
    for project in state.projects.values {
        lines.append(
            "project \(project.id.rawValue) | \(project.name) | \(project.state.rawValue) | \(project.color ?? "-") | "
                + (project.desiredOutcome ?? "-"))
    }
    for tag in state.tags.values {
        lines.append("tag \(tag.id.rawValue) | \(tag.name) | \(tag.state.rawValue)")
    }
    return lines.sorted()
}

/// The layout of a list result: its sections and the tasks in them, in order.
private func layout(_ result: TaskListResult) -> [String] {
    result.sections.map { section in
        "\(section.id)=" + section.tasks.map(\.id.rawValue).joined(separator: ",")
    } + ["open=\(result.openCount)"]
}

/// A state built by the Swift reducer: the same rules both images start from in the query tests.
private func seededState() throws -> GTDState {
    let today = CalendarDay(date: start, calendar: utcCalendar)
    let commands: [GTDCommand] = [
        .createProject(.init(projectID: projectID(1), name: "Home")),
        .createTag(.init(tagID: tagID(1), name: "errands")),
        .createTask(.init(taskID: taskID(1), title: "Buy milk", list: .inbox, dueDate: today.adding(days: -1))),
        .createTask(.init(taskID: taskID(2), title: "Pay rent", list: .inbox, projectID: projectID(1))),
        .createTask(.init(taskID: taskID(3), title: "Call Sam", list: .next, dueDate: today, tagIDs: [tagID(1)])),
        .createTask(.init(taskID: taskID(4), title: "Plan trip", list: .next, dueDate: today.adding(days: 3))),
        .createTask(.init(taskID: taskID(5), title: "Parcel", list: .waiting, waitingFor: "Courier")),
        .createTask(.init(taskID: taskID(6), title: "Learn piano", list: .someday)),
        .createTask(.init(taskID: taskID(7), title: "Old chore", list: .next)),
        .transitionTask(.init(taskID: taskID(7), action: .complete)),
    ]
    var state = GTDState.empty
    for (index, command) in commands.enumerated() {
        try GTDReducer.apply(command, at: moment(index), to: &state)
    }
    return state
}

@Suite("Rust domain facade (026-FR-002, 026-FR-009, 026-FR-016, 026-SC-001)")
struct RustDomainParityTests {
    // MARK: - The mapping

    @Test("026-FR-002: instants round trip through the wire format to the microsecond")
    func instantsRoundTrip() throws {
        #expect(RustInstant.format(start) == "2026-09-21T14:13:20Z")
        #expect(RustInstant.format(Date(timeIntervalSince1970: 0)) == "1970-01-01T00:00:00Z")
        let fractional = Date(timeIntervalSince1970: -86_400.5)
        #expect(RustInstant.format(fractional) == "1969-12-30T23:59:59.500000Z")
        for date in [start, fractional, start.addingTimeInterval(0.000_001)] {
            #expect(RustInstant.parse(RustInstant.format(date)) == date)
        }
        #expect(RustInstant.parse("2026-09-21T16:13:20+02:00") == start)
        #expect(RustInstant.parse("2026-09-21T14:13:20.25Z") == start.addingTimeInterval(0.25))
        for bad in ["2026-09-21", "2026-09-21T14:13:20", "2026-13-21T14:13:20Z", "2026-09-21T24:13:20Z", "yesterday"] {
            #expect(RustInstant.parse(bad) == nil, "\(bad)")
        }
    }

    @Test("026-FR-002: a record always crosses with the same canonical prefixed identifier and maps back")
    func canonicalIdentifiers() {
        var ids = RustIDTable()
        let wire = ids.wire(uuid(1), prefix: "task")
        #expect(wire == "task_" + uuid(1))
        #expect(ids.swift(wire) == uuid(1))
        // Deterministic: the read set and the command name a record the same way.
        #expect(ids.task(taskID(1)) == wire)
        #expect(RustIDTable().task(taskID(1)) == wire)
        #expect(ids.project(projectID(1)) == "project_" + uuid(1))
        #expect(ids.swift("project_" + uuid(1)) == uuid(1))
        // An identifier of the right shape, or of no shape the core could accept, is left alone.
        #expect(ids.wire("task_" + uuid(2), prefix: "task") == "task_" + uuid(2))
        #expect(ids.wire("not a uuid", prefix: "task") == "not a uuid")
        #expect(ids.swift("task_" + uuid(2)) == "task_" + uuid(2))
    }

    @Test("026-FR-002: edits keep omitted, null and value apart and tag edits name the difference")
    func patchMembers() throws {
        var state = GTDState.empty
        state.tasks[taskID(1)] = TaskRecord(
            id: taskID(1), title: "Buy milk", state: .inbox, tagIDs: [tagID(1), tagID(2)], orderKey: 0,
            createdAt: start, updatedAt: start)
        var ids = RustIDTable()
        let edit = GTDCommand.updateTask(
            .init(
                taskID: taskID(1),
                changes: TaskChanges(
                    title: .set("  Buy oat milk  "), details: .clear, tagIDs: .set([tagID(2), tagID(3)]),
                    priority: .set(.high))))
        let encoded = try RustCommandEncoder.encode(edit, at: moment(1), in: state, scopeID: "local", ids: &ids)
        #expect(encoded.type == "task.update")
        #expect(encoded.entityID == "task_" + uuid(1))
        #expect(encoded.payload["title"] as? String == "Buy oat milk")
        #expect(encoded.payload["details"] is NSNull)
        #expect(encoded.payload["priority"] as? String == "high")
        #expect(encoded.payload["project_id"] == nil)
        #expect(encoded.payload["due_date"] == nil)
        let tagChanges = try #require(encoded.payload["tag_changes"] as? [String: [String]])
        #expect(tagChanges["add_tag_ids"] == ["tag_" + uuid(3)])
        #expect(tagChanges["remove_tag_ids"] == ["tag_" + uuid(1)])
        // The edit is checked against the revision the state holds for the target.
        #expect(encoded.target?.entityType == "task")
        #expect(encoded.target?.id == "task_" + uuid(1))
        #expect(encoded.target?.revision == 0)
    }

    @Test("026-FR-002: a null title or priority is the request error the server reports")
    func nullTitleAndPriority() {
        var ids = RustIDTable()
        var state = GTDState.empty
        state.tasks[taskID(1)] = TaskRecord(
            id: taskID(1), title: "Buy milk", state: .inbox, orderKey: 0, createdAt: start, updatedAt: start)
        let clearTitle = GTDCommand.updateTask(.init(taskID: taskID(1), changes: TaskChanges(title: .clear)))
        #expect(throws: GTDValidationError.emptyTitle) {
            try RustCommandEncoder.encode(clearTitle, at: start, in: state, scopeID: "local", ids: &ids)
        }
        let clearPriority = GTDCommand.updateTask(.init(taskID: taskID(1), changes: TaskChanges(priority: .clear)))
        #expect(throws: GTDValidationError.priorityRequired) {
            try RustCommandEncoder.encode(clearPriority, at: start, in: state, scopeID: "local", ids: &ids)
        }
    }

    @Test("026-FR-002: the state crosses as the core's read set, counters as decimal strings")
    func readSetShape() throws {
        var state = try seededState()
        state.tasks[taskID(1)]?.serverRevision = 9_007_199_254_740_993
        var ids = RustIDTable()
        let readSet = RustReadSet.make(state, actorID: "device", ids: &ids)
        let tasks = try #require(readSet["tasks"] as? WireObject)
        #expect(tasks.count == 7)
        // Every record and every reference to it carries the canonical wire ID.
        let milk = try #require(tasks["task_" + uuid(1)] as? WireObject)
        #expect(milk["id"] as? String == "task_" + uuid(1))
        let rent = try #require(tasks["task_" + uuid(2)] as? WireObject)
        #expect(rent["project_id"] as? String == "project_" + uuid(1))
        let projects = try #require(readSet["projects"] as? WireObject)
        #expect(projects["project_" + uuid(1)] != nil)
        let call = try #require(tasks["task_" + uuid(3)] as? WireObject)
        #expect(call["tag_ids"] as? [String] == ["tag_" + uuid(1)])
        #expect(milk["revision"] as? String == "9007199254740993")
        #expect(milk["due_date"] as? String == "2026-09-20")
        #expect(milk["created_at"] as? String == "2026-09-21T14:15:20Z")
        #expect(milk["parked"] is NSNull)
        // Settings nobody changed are not stored; the core then uses its defaults.
        #expect(readSet["settings"] == nil)
        // The wire form is valid JSON the core accepts.
        _ = try RustJSON.data(readSet)
    }

    // MARK: - One image decides

    @Test("026-FR-002: the migrated epoch never reaches the Swift rules and the legacy epoch never the core")
    func epochsAreExclusive() async throws {
        let runtime = try RustBridgeRuntime()
        runtime.close()
        let closed = RustDomainFacade(runtime: runtime)
        let command = GTDCommand.createTask(.init(taskID: taskID(1), title: "Buy milk", list: .inbox))

        // The legacy image decides without asking a core that cannot answer.
        var legacy = GTDState.empty
        try await GTDReducer.apply(command, at: start, to: &legacy, rules: .legacy)
        #expect(legacy.tasks.count == 1)

        // The migrated image does not fall back to the Swift handlers when the core cannot answer.
        var migrated = GTDState.empty
        do {
            try await GTDReducer.apply(command, at: start, to: &migrated, rules: .rust(closed))
            Issue.record("a closed core must not be answered by the Swift rules")
        } catch let error as RustBridgeError {
            #expect(error.code == "WORKSPACE_CLOSED")
        }
        #expect(migrated.tasks.isEmpty)
    }

    @Test("026-FR-002: replay is the runtime's in the migrated epoch and is not decided here")
    func replayIsNotDecided() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        let command = GTDCommand.createTask(.init(taskID: taskID(1), title: "Buy milk", list: .inbox))
        do {
            try await GTDReducer.apply(command, at: start, to: &state, mode: .replay, rules: .rust(facade))
            Issue.record("replay must not be decided by the facade")
        } catch let error as RustDomainError {
            #expect(error == .replayIsRuntimeOwned)
        }
        #expect(state.tasks.isEmpty)
    }

    @Test("026-FR-002: the same commands give the same state and the same refusals in both images")
    func commandsAgree() async throws {
        let facade = try makeFacade()
        var legacy = GTDState.empty
        var migrated = GTDState.empty
        let today = CalendarDay(date: start, calendar: utcCalendar)
        let call = taskID(2)
        let steps: [GTDCommand] = [
            .createProject(.init(projectID: projectID(1), name: "  Home  ")),
            .createTag(.init(tagID: tagID(1), name: "@errands")),
            .createTask(
                .init(
                    taskID: taskID(1), title: "  Buy milk  ", details: "From the shop", list: .inbox,
                    dueDate: today.adding(days: 70), priority: .high, projectID: projectID(1), tagIDs: [tagID(1)])),
            .createTask(.init(taskID: call, title: "Call Sam", list: .next)),
            .updateTask(.init(taskID: call, changes: TaskChanges(title: .set("Call Sam about the invoice")))),
            // Waiting needs a note: both images refuse, then accept.
            .transitionTask(.init(taskID: call, action: .move, toList: .waiting)),
            .transitionTask(.init(taskID: call, action: .move, toList: .waiting, waitingFor: "  Sam  ")),
            .transitionTask(.init(taskID: call, action: .complete)),
            .transitionTask(.init(taskID: call, action: .reopen, toList: .next)),
            // An archived project takes no new task.
            .archiveProject(projectID(1)),
            .createTask(.init(taskID: taskID(3), title: "Dust", list: .inbox, projectID: projectID(1))),
            .unarchiveProject(project: projectID(1)),
            .createSubtask(.init(taskID: taskID(1), subtaskID: SubtaskID(uuid(1)), title: "Oat milk")),
            .transitionSubtask(.init(taskID: taskID(1), subtaskID: SubtaskID(uuid(1)), action: .complete)),
            .createComment(.init(taskID: taskID(1), commentID: CommentID(uuid(1)), body: "Ask for the big bottle")),
            .updateComment(.init(taskID: taskID(1), commentID: CommentID(uuid(1)), body: "Ask for two")),
            // Deleting a tag takes it off every task.
            .deleteTag(tagID(1)),
            .setProjectOutcome(project: projectID(1), outcome: "Calm home"),
            .updateTask(
                .init(
                    taskID: taskID(1),
                    changes: TaskChanges(details: .clear, dueDate: .clear, priority: .set(.low)))),
            // A name another active project holds, and records that are not there.
            .createProject(.init(projectID: projectID(2), name: "home")),
            .updateTask(.init(taskID: taskID(99), changes: TaskChanges(title: .set("Nope")))),
            .createTask(.init(taskID: taskID(4), title: "   ", list: .inbox)),
            .createTask(.init(taskID: taskID(5), title: String(repeating: "x", count: 501), list: .inbox)),
            .transitionTask(.init(taskID: taskID(1), action: .move, toList: .inbox)),
        ]
        var refusals = 0
        for (index, command) in steps.enumerated() {
            let date = moment(index)
            var legacyError: GTDValidationError?
            do {
                try GTDReducer.apply(command, at: date, to: &legacy)
            } catch {
                legacyError = error
            }
            var rustError: GTDValidationError?
            do {
                try await GTDReducer.apply(command, at: date, to: &migrated, rules: .rust(facade))
            } catch let error as GTDValidationError {
                rustError = error
            }
            #expect(legacyError == rustError, "step \(index): \(command)")
            #expect(shape(legacy) == shape(migrated), "step \(index): \(command)")
            if legacyError != nil { refusals += 1 }
        }
        #expect(refusals == 7)
        // A refusal left both untouched; what was decided is there.
        #expect(migrated.tasks[taskID(1)]?.title == "Buy milk")
        #expect(migrated.tasks[taskID(1)]?.tagIDs == [])
        #expect(migrated.tasks[call]?.state == .next)
        #expect(migrated.projects[projectID(1)]?.desiredOutcome == "Calm home")
    }

    @Test("026-FR-009: a new task goes after the last of its list and a closed task remembers its list")
    func orderingAndLastOpenList() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        for number in 1...3 {
            try await facade.apply(
                .createTask(.init(taskID: taskID(number), title: "Task \(number)", list: .inbox)),
                at: moment(number), to: &state)
        }
        #expect([1, 2, 3].map { state.tasks[taskID($0)]?.orderKey } == [0, 1, 2])
        try await facade.apply(.transitionTask(.init(taskID: taskID(2), action: .complete)), at: moment(4), to: &state)
        #expect(state.tasks[taskID(2)]?.state == .completed)
        #expect(state.tasks[taskID(2)]?.lastOpenList == .inbox)
        #expect(state.tasks[taskID(2)]?.completedAt == moment(4))
        // The core is the revision authority of the epoch.
        #expect(state.tasks[taskID(2)]?.serverRevision == 2)
        try await facade.apply(
            .transitionTask(.init(taskID: taskID(2), action: .reopen, toList: .next)), at: moment(5), to: &state)
        #expect(state.tasks[taskID(2)]?.lastOpenList == nil)
        #expect(state.tasks[taskID(2)]?.formulation != nil)
    }

    @Test("026-FR-002: a refusal throws and leaves the state exactly as it was")
    func refusalLeavesStateUntouched() async throws {
        let facade = try makeFacade()
        var state = try seededState()
        let before = state
        await #expect(throws: GTDValidationError.waitingForRequired) {
            try await facade.apply(
                .transitionTask(.init(taskID: taskID(4), action: .move, toList: .waiting)), at: moment(20), to: &state)
        }
        #expect(state == before)
        // A task the state does not hold is the core's `not_found`, worded as the app always has.
        await #expect(throws: GTDValidationError.taskNotFound) {
            try await facade.apply(
                .transitionTask(.init(taskID: taskID(99), action: .complete)), at: moment(21), to: &state)
        }
        #expect(state == before)
    }

    @Test("026-FR-002: creating an ID the state already holds is refused in both images and never overwrites it")
    func repeatedCreateIsRefused() async throws {
        let facade = try makeFacade()
        var legacy = try seededState()
        var migrated = legacy
        // Children exist in both images before they are created a second time.
        let children: [GTDCommand] = [
            .createSubtask(.init(taskID: taskID(1), subtaskID: SubtaskID(uuid(1)), title: "Oat milk")),
            .createComment(.init(taskID: taskID(1), commentID: CommentID(uuid(1)), body: "Ask for the big bottle")),
        ]
        for (index, command) in children.enumerated() {
            try GTDReducer.apply(command, at: moment(30 + index), to: &legacy)
            try await facade.apply(command, at: moment(30 + index), to: &migrated)
        }
        let repeats: [GTDCommand] = [
            .createTask(.init(taskID: taskID(1), title: "Another", list: .inbox)),
            .createProject(.init(projectID: projectID(1), name: "Elsewhere")),
            .createTag(.init(tagID: tagID(1), name: "elsewhere")),
            .createSubtask(.init(taskID: taskID(1), subtaskID: SubtaskID(uuid(1)), title: "Again")),
            .createComment(.init(taskID: taskID(1), commentID: CommentID(uuid(1)), body: "Again")),
        ]
        for command in repeats {
            let kept = migrated
            var legacyError: GTDValidationError?
            do {
                try GTDReducer.apply(command, at: moment(40), to: &legacy)
            } catch {
                legacyError = error
            }
            var rustError: GTDValidationError?
            do {
                try await GTDReducer.apply(command, at: moment(40), to: &migrated, rules: .rust(facade))
            } catch let error as GTDValidationError {
                rustError = error
            }
            #expect(legacyError == .idAlreadyExists, "\(command)")
            #expect(rustError == .idAlreadyExists, "\(command)")
            #expect(migrated == kept, "\(command)")
        }
        #expect(shape(migrated) == shape(legacy))
        #expect(migrated.tasks[taskID(1)]?.title == "Buy milk")
        #expect(migrated.projects[projectID(1)]?.name == "Home")
    }

    @Test("026-FR-016: a park the device observed online changes nothing until the server answers")
    func nonOptimisticAutoPark() async throws {
        let facade = try makeFacade()
        var seed = GTDState.empty
        seed.review.accountlessReleaseSwitch = true
        seed.review.settings.activatedAt = start.addingTimeInterval(-200 * 86_400)
        let old = start.addingTimeInterval(-100 * 86_400)
        let formulation = FormulationID("form_" + uuid(1))
        seed.tasks[taskID(1)] = TaskRecord(
            id: taskID(1), title: "Call Sam", state: .next, orderKey: 0, createdAt: old, updatedAt: old,
            formulation: FormulationClock(id: formulation, startedAt: old))
        let observed = GTDCommand.autoParkTask(
            .init(taskID: taskID(1), formulationID: formulation, optimistic: false))

        var legacy = seed
        try GTDReducer.apply(observed, at: start, to: &legacy)
        #expect(legacy == seed, "the Swift reducer leaves the task alone")

        var migrated = seed
        try await GTDReducer.apply(observed, at: start, to: &migrated, rules: .rust(facade))
        #expect(migrated == seed)
        #expect(migrated.tasks[taskID(1)]?.state == .next)
        #expect(migrated.tasks[taskID(1)]?.parked == nil)
    }

    @Test("026-FR-002: a blank title or name is told apart from an overlong note or outcome, in the order the app checks")
    func invalidPayloadsAreClassifiedByTheirField() async throws {
        let facade = try makeFacade()
        let longNotes = String(repeating: "n", count: GTDLimits.details + 1)
        let longOutcome = String(repeating: "o", count: GTDLimits.outcome + 1)
        let cases: [(GTDCommand, GTDValidationError)] = [
            (.createTask(.init(taskID: taskID(1), title: "   ", details: longNotes, list: .inbox)), .emptyTitle),
            (.createTask(.init(taskID: taskID(1), title: "Buy milk", details: longNotes, list: .inbox)), .detailsTooLong),
            (.createProject(.init(projectID: projectID(1), name: "", desiredOutcome: longOutcome)), .emptyName),
            (.createProject(.init(projectID: projectID(1), name: "Home", desiredOutcome: longOutcome)), .outcomeTooLong),
        ]
        for (command, expected) in cases {
            var legacy = GTDState.empty
            var legacyError: GTDValidationError?
            do {
                try GTDReducer.apply(command, at: start, to: &legacy)
            } catch {
                legacyError = error
            }
            var migrated = GTDState.empty
            var rustError: GTDValidationError?
            do {
                try await facade.apply(command, at: start, to: &migrated)
            } catch let error as GTDValidationError {
                rustError = error
            }
            #expect(legacyError == expected, "legacy: \(command)")
            #expect(rustError == expected, "core: \(command)")
            #expect(migrated == .empty)
        }
    }

    @Test("026-FR-002: one facade serves many concurrent tasks")
    func concurrentApplies() async throws {
        let facade = try makeFacade()
        let counts = try await withThrowingTaskGroup(of: Int.self) { group in
            for number in 1...32 {
                group.addTask {
                    var state = GTDState.empty
                    try await facade.apply(
                        .createTask(.init(taskID: taskID(number), title: "Task \(number)", list: .inbox)),
                        at: moment(number), to: &state)
                    return state.tasks.count
                }
            }
            var counts: [Int] = []
            for try await count in group { counts.append(count) }
            return counts
        }
        #expect(counts.count == 32)
        #expect(counts.allSatisfy { $0 == 1 })
    }

    // MARK: - Queries

    @Test("026-SC-001: counts, projects, tags and every list agree between the Swift read model and the core")
    func queriesAgree() async throws {
        let state = try seededState()
        let rules = RuleEpoch.rust(try makeFacade())
        let today = CalendarDay(date: start, calendar: utcCalendar)

        #expect(
            try await GTDQueries.counts(in: state, now: start, calendar: utcCalendar, rules: rules)
                == GTDQueries.counts(in: state, today: today))
        let projects = try await GTDQueries.projects(in: state, now: start, calendar: utcCalendar, rules: rules)
        #expect(
            projects.map { "\($0.id.rawValue):\($0.openTaskCount):\($0.nextActionCount)" }
                == GTDQueries.projects(in: state).map { "\($0.id.rawValue):\($0.openTaskCount):\($0.nextActionCount)" })
        let tags = try await GTDQueries.tags(in: state, now: start, calendar: utcCalendar, rules: rules)
        #expect(
            tags.map { "\($0.id.rawValue):\($0.openTaskCount)" }
                == GTDQueries.tags(in: state).map { "\($0.id.rawValue):\($0.openTaskCount)" })
        let display = try await GTDQueries.projectDisplay(
            projectID(1), in: state, now: start, calendar: utcCalendar, rules: rules)
        #expect(display == GTDQueries.projectDisplay(projectID(1), in: state))
        let none = try await GTDQueries.projectDisplay(
            projectID(9), in: state, now: start, calendar: utcCalendar, rules: rules)
        #expect(none == nil)

        let destinations: [Destination] = [
            .list(.inbox), .list(.next), .list(.waiting), .list(.someday), .project(projectID(1)), .agenda,
            .dateView(.today), .dateView(.overdue), .dateView(.upcoming), .history(.completed), .search("milk"),
        ]
        for destination in destinations {
            let legacy = GTDQueries.list(destination, options: ListOptions(), in: state, today: today)
            let migrated = try await GTDQueries.list(
                destination, options: ListOptions(), in: state, now: start, calendar: utcCalendar, rules: rules)
            #expect(layout(migrated) == layout(legacy), "\(destination)")
            // The seed has a task for every one of them, so an agreement is not an empty one.
            #expect(!layout(legacy).dropLast().isEmpty, "\(destination)")
        }
        // The legacy epoch answers with the Swift read model itself.
        let viaEpoch = try await GTDQueries.list(
            .list(.next), options: ListOptions(), in: state, now: start, calendar: utcCalendar, rules: .legacy)
        #expect(layout(viaEpoch) == layout(GTDQueries.list(.list(.next), options: ListOptions(), in: state, today: today)))
    }

    @Test("026-SC-001: a destination or option the shared queries cannot answer is refused, not answered by Swift")
    func unsupportedQueries() async throws {
        let state = try seededState()
        let facade = try makeFacade()
        await #expect(throws: RustDomainError.unsupportedQuery("tag")) {
            try await facade.list(.tag(tagID(1)), options: ListOptions(), in: state, now: start, zone: "UTC")
        }
        await #expect(throws: RustDomainError.unsupportedQuery("open list options")) {
            try await facade.list(
                .list(.next), options: ListOptions(groupByProject: true), in: state, now: start, zone: "UTC")
        }
    }

    // MARK: - Smart Add

    @Test("026-SC-001: Smart Add previews and captures the same in both images")
    func smartAddAgrees() async throws {
        let state = try seededState()
        let rules = RuleEpoch.rust(try makeFacade())
        let draft = CaptureDraft(text: "Buy bread @Home #errands #bakery", list: .inbox)

        let legacyPreview = CapturePlanner.preview(draft, in: state)
        let preview = try await CapturePlanner.preview(draft, in: state, rules: rules)
        #expect(preview == legacyPreview)
        #expect(preview.title == "Buy bread")
        #expect(preview.tags.map(\.isNew) == [false, true])

        var legacy = state
        var migrated = state
        let legacyID = try await CapturePlanner.capture(
            draft, at: moment(30), to: &legacy, rules: .legacy, makeTaskID: { taskID(20) },
            makeProjectID: { projectID(20) }, makeTagID: { tagID(20) })
        let rustID = try await CapturePlanner.capture(
            draft, at: moment(30), to: &migrated, rules: rules, makeTaskID: { taskID(20) },
            makeProjectID: { projectID(20) }, makeTagID: { tagID(20) })
        #expect(legacyID == rustID)
        #expect(shape(migrated) == shape(legacy))
        #expect(migrated.tasks[rustID]?.projectID == projectID(1))
        #expect(migrated.tags[tagID(20)]?.name == "bakery")
        #expect(Set(migrated.tasks[rustID]?.tagIDs ?? []) == [tagID(1), tagID(20)])
    }

    @Test("026-SC-001: a blocked draft is refused with the app's wording and changes nothing")
    func blockedCapture() async throws {
        let state = try seededState()
        let facade = try makeFacade()
        let blocked = CaptureDraft(text: "@Home", list: .inbox)
        let preview = try await facade.preview(blocked, in: state)
        #expect(preview.problem == .emptyTitle)
        var next = state
        await #expect(throws: GTDValidationError.emptyTitle) {
            try await facade.capture(blocked, at: moment(31), to: &next)
        }
        #expect(next == state)
    }

    // MARK: - Review

    @Test("026-FR-016: the review's own entries stay refused while it is not exposed")
    func reviewEntriesNeedExposure() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        await #expect(throws: GTDValidationError.reviewUnavailable) {
            try await facade.apply(.review(.acknowledgeExplainer(timeZone: "UTC")), at: start, to: &state)
        }
        // Settings are not a review entry.
        try await facade.apply(.review(.updateSettings(ReviewSettingsChange(thresholdDays: 21))), at: start, to: &state)
        #expect(state.review.settings.thresholdDays == 21)
        #expect(state.review.settings.thresholdChangedAt == start)
    }

    @Test("026-FR-016: activation, a review run, a decision and its session count are decided by the core")
    func reviewRun() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        state.review.accountlessReleaseSwitch = true
        let call = taskID(1)
        try await facade.apply(.createTask(.init(taskID: call, title: "Call Sam", list: .next)), at: moment(0), to: &state)

        try await facade.apply(.review(.acknowledgeExplainer(timeZone: "UTC")), at: moment(1), to: &state)
        #expect(state.review.settings.activatedAt == moment(1))

        let session = ReviewSessionID("review_" + uuid(1))
        try await facade.apply(
            .review(.startSession(StartSession(sessionID: session, mode: .quick, entry: .list))), at: moment(2),
            to: &state)
        #expect(state.review.sessions[session]?.status == .open)
        #expect(state.review.sessions[session]?.currentStep == .wins)

        let progress = ProgressID("progress_" + uuid(1))
        try await facade.apply(
            .review(
                .progressSession(
                    SessionProgress(
                        sessionID: session, progressID: progress, step: .wins, stepStatus: .finished,
                        activeStep: .wins, activeSeconds: 12))),
            at: moment(3), to: &state)
        #expect(state.review.sessions[session]?.steps[.wins] == .finished)
        #expect(state.review.sessions[session]?.activeSecondsByStep[.wins] == 12)
        #expect(state.review.sessions[session]?.appliedProgress.contains(progress) == true)

        let decision = DecisionID("decision_" + uuid(1))
        try await facade.apply(
            .decideTask(.init(decisionID: decision, taskID: call, type: .complete, sessionID: session)),
            at: moment(4), to: &state)
        #expect(state.tasks[call]?.state == .completed)
        #expect(state.review.decisions[decision]?.type == .complete)
        #expect(state.review.decisions[decision]?.taskAfter.serverRevision == state.tasks[call]?.serverRevision)
        #expect(state.review.sessions[session]?.counts[.done] == 1)

        // The device holds no authoritative Undo snapshot: the core says so instead of fabricating one.
        let before = state
        await #expect(throws: GTDValidationError.undoUnavailable) {
            try await facade.apply(.undoDecision(decision), at: moment(5), to: &state)
        }
        #expect(state == before)

        try await facade.apply(
            .review(.finishSession(FinishSession(sessionID: session))), at: moment(6), to: &state)
        #expect(state.review.sessions[session]?.status != .open)
    }

    @Test("026-FR-016: a bulk release moves the eligible tasks and records what it did")
    func bulkRelease() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        state.review.accountlessReleaseSwitch = true
        try await facade.apply(.createTask(.init(taskID: taskID(1), title: "Sort mail", list: .inbox)), at: moment(0), to: &state)
        let bulk = BulkID("bulk_" + uuid(1))
        try await facade.apply(
            .bulkRelease(.init(bulkID: bulk, kind: .inboxRemainder, taskIDs: [taskID(1)])), at: moment(1), to: &state)
        #expect(state.tasks[taskID(1)]?.state == .someday)
        let record = try #require(state.review.bulkReleases[bulk])
        #expect(record.released.map(\.taskID) == [taskID(1)])
        #expect(record.released.first?.previousState == .inbox)
        #expect(state.review.receipt(for: taskID(1), kind: .someday)?.bulkID == bulk)
    }

    @Test("026-FR-016: Navigator consent is granted and revoked owner-wide by the core")
    func navigatorConsent() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        try await facade.apply(
            .review(.grantNavigatorConsent(provider: "apple", consentTextVersion: 2)), at: moment(0), to: &state)
        #expect(state.review.navigatorConsents["apple"]?.allowsCloud == true)
        #expect(state.review.navigatorConsents["apple"]?.consentTextVersion == 2)
        try await facade.apply(.review(.revokeNavigatorConsent(provider: "apple")), at: moment(1), to: &state)
        #expect(state.review.navigatorConsents["apple"]?.allowsCloud == false)
    }

    @Test("026-FR-016: the review's derived facts are the core's")
    func reviewState() async throws {
        let facade = try makeFacade()
        var state = GTDState.empty
        let off = try await facade.reviewState(in: state, now: start, zone: "UTC")
        #expect(!off.exposed)
        state.review.accountlessReleaseSwitch = true
        let on = try await facade.reviewState(in: state, now: start, zone: "UTC")
        #expect(on.exposed)
        #expect(on.nextReviewAt != nil)
        #expect(on.openSessionID == nil)
    }
}
