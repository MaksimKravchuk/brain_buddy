import BrainBuddyCore
import Foundation
import Testing

/// The formulation clock in `GTDReducer` and the spec 020 commands
/// (contracts/ios-commands.md §2 – §4; tasks.md T051, T087, T108, T133).
@Suite("GTDReducer: formulation clock and review commands (spec 020)")
struct ReducerReviewTests {
    let t0 = Review.instant("2026-09-24T09:14:00Z")

    // MARK: - Clock maintenance in the existing commands (T051)

    @Test("020-FR-001 a task created in Next starts a formulation with the id the command minted")
    func createInNextStartsAClock() throws {
        var state = Review.state([])
        try Review.apply(.createTask(.init(taskID: "t1", title: "Call Bob", list: .next, newFormulationID: Review.form(7))), at: t0, to: &state)
        try Review.apply(.createTask(.init(taskID: "t2", title: "Idea", list: .inbox, newFormulationID: Review.form(8))), at: t0, to: &state)
        #expect(state.tasks["t1"]?.formulation == FormulationClock(id: Review.form(7), startedAt: t0))
        #expect(state.tasks["t2"]?.formulation == nil, "Inbox tasks have no clock")
        #expect(Review.form(7).rawValue.hasPrefix("form_") && ClientID.isValid(Review.form(7).rawValue, prefix: "form"))
    }

    @Test("020-FR-001 020-FR-002 a substantive title change restarts the clock; a cosmetic one does not")
    func titleChanges() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        let later = Review.now
        try Review.apply(
            .updateTask(.init(taskID: "t1", changes: TaskChanges(title: .set("call bob.")), newFormulationID: Review.form(2))),
            at: later, to: &state
        )
        #expect(state.tasks["t1"]?.formulation?.id == Review.form(1), "cosmetic: same formulation")
        try Review.apply(
            .updateTask(.init(taskID: "t1", changes: TaskChanges(title: .set("Email Bob the quote")), newFormulationID: Review.form(3))),
            at: later, to: &state
        )
        let task = try #require(state.tasks["t1"])
        #expect(task.formulation == FormulationClock(id: Review.form(3), startedAt: later))
        #expect(task.consecutiveStalledFormulations == 1, "the closed formulation had asked (T-001)")
    }

    @Test("020-FR-003 notes, tags, project and priority edits leave the clock alone; a due date raises the floor")
    func editsWithoutClockChange() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        state.projects["p1"] = ProjectRecord(id: "p1", name: "Flat", createdAt: t0)
        try Review.apply(
            .updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("notes"), projectID: .set("p1"), priority: .set(.high)))),
            to: &state
        )
        #expect(state.tasks["t1"]?.formulation == FormulationClock(id: Review.form(1), startedAt: t0))
        try Review.apply(
            .updateTask(.init(taskID: "t1", changes: TaskChanges(dueDate: .set(CalendarDay(year: 2026, month: 10, day: 20)!)))),
            to: &state
        )
        #expect(state.tasks["t1"]?.formulation?.parkFloorAt == Review.now.addingTimeInterval(7 * Review.day), "FR-046")
        #expect(state.tasks["t1"]?.formulation?.startedAt == t0)
    }

    @Test("020-FR-001 020-FR-005 leaving Next closes the formulation, returning starts one, leaving Someday drops the park")
    func listChanges() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        try Review.apply(.transitionTask(.init(taskID: "t1", action: .move, toList: .waiting, waitingFor: "Ann")), to: &state)
        #expect(state.tasks["t1"]?.formulation == nil)
        #expect(state.tasks["t1"]?.consecutiveStalledFormulations == 1)
        let back = Review.now.addingTimeInterval(3_600)
        try Review.apply(
            .transitionTask(.init(taskID: "t1", action: .move, toList: .next, newFormulationID: Review.form(5))), at: back,
            to: &state
        )
        #expect(state.tasks["t1"]?.formulation == FormulationClock(id: Review.form(5), startedAt: back))
        #expect(state.tasks["t1"]?.consecutiveStalledFormulations == 1, "the count survives leaving Next")
    }

    @Test("020-FR-001 a replay of the same outbox gives the same clocks (ids are minted in the command)")
    func replayIsDeterministic() {
        let outbox = [
            Review.op(.createTask(.init(taskID: "t1", title: "Call Bob", list: .next, newFormulationID: Review.form(1))), at: t0),
            Review.op(
                .updateTask(.init(taskID: "t1", changes: TaskChanges(title: .set("Email Bob")), newFormulationID: Review.form(2))),
                at: Review.now
            ),
            Review.op(.transitionTask(.init(taskID: "t1", action: .move, toList: .someday)), at: Review.now.addingTimeInterval(60)),
        ]
        let first = OutboxReplayer.replay(outbox, onto: Review.state([])).state
        let second = OutboxReplayer.replay(outbox, onto: Review.state([])).state
        #expect(first == second)
        #expect(first.tasks["t1"]?.state == .someday)
    }

    // MARK: - Decisions (T051)

    @Test("020-FR-006 020-FR-008 find a first step: new title, 'Was:' notes, always a new formulation")
    func firstStep() throws {
        var task = Review.nextTask("t1", title: "Renovate the bathroom", started: t0)
        task.details = "Tiles from the old shop"
        var state = Review.state([task])
        try Review.apply(
            Review.decide(.firstStep, "t1", formulation: Review.form(1), title: "Measure the bathroom wall", newFormulation: Review.form(2)),
            to: &state
        )
        let decided = try #require(state.tasks["t1"])
        #expect(decided.title == "Measure the bathroom wall")
        #expect(decided.details == "Was: Renovate the bathroom\n\nTiles from the old shop")
        #expect(decided.formulation?.id == Review.form(2))
        let record = try #require(state.review.decisions[Review.decision(1)])
        #expect(record.type == .firstStep && record.substantive == true)
        #expect(record.undo?.taskBefore == task)
    }

    @Test("020-FR-002 020-FR-006 a cosmetic reformulation ('Save anyway') is a decision without a clock change")
    func cosmeticReformulation() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        try Review.apply(
            Review.decide(.reformulate, "t1", formulation: Review.form(1), title: "call bob!", newFormulation: Review.form(2)),
            to: &state
        )
        #expect(state.tasks["t1"]?.formulation?.id == Review.form(1))
        #expect(state.review.decisions[Review.decision(1)]?.substantive == false)
    }

    @Test("020-FR-006 020-FR-032 each decision type applies the http §3 table and its receipt")
    func decisionTable() throws {
        let base = Review.state([
            Review.nextTask("n1", started: t0), Review.nextTask("n2", started: t0), Review.nextTask("n3", started: t0),
            Review.nextTask("n4", started: t0), Review.task("w1", title: "Drill from Sam", state: .waiting),
            Review.task("s1", title: "Raised bed", state: .someday),
        ])
        var state = base
        state.tasks["w1"]?.waitingFor = "Sam"
        try Review.apply(Review.decide(.waiting, "n1", decision: 1, formulation: Review.form(1), waitingFor: "Ann"), to: &state)
        try Review.apply(Review.decide(.someday, "n2", decision: 2, formulation: Review.form(1)), to: &state)
        try Review.apply(Review.decide(.complete, "n3", decision: 3), to: &state)
        try Review.apply(Review.decide(.cancel, "n4", decision: 4), to: &state)
        try Review.apply(Review.decide(.keepWaiting, "w1", decision: 5), to: &state)
        try Review.apply(Review.decide(.keepSomeday, "s1", decision: 6), to: &state)
        #expect(state.tasks["n1"]?.state == .waiting && state.tasks["n1"]?.waitingFor == "Ann")
        #expect(state.tasks["n2"]?.state == .someday && state.tasks["n2"]?.parked == nil, "a person's release is not a park")
        #expect(state.review.receipt(for: "n2", kind: .someday)?.source == .release)
        #expect(state.review.receipt(for: "n2", kind: .someday)?.hiddenUntil == Review.now.addingTimeInterval(30 * Review.day))
        #expect(state.tasks["n3"]?.state == .completed && state.tasks["n4"]?.state == .cancelled)
        #expect(state.review.receipt(for: "w1", kind: .waiting)?.hiddenUntil == Review.now.addingTimeInterval(7 * Review.day))
        #expect(state.review.receipt(for: "s1", kind: .someday)?.source == .keep)
        #expect(state.tasks["w1"] == base.tasks["w1"].map { var task = $0; task.waitingFor = "Sam"; return task })
    }

    @Test("020-FR-009 keep 7 more days needs a due ask, a reason, and works once")
    func extensionRules() throws {
        var state = Review.state([Review.nextTask("t1", started: t0), Review.nextTask("t2", started: Review.now.addingTimeInterval(-3 * Review.day))])
        try Review.apply(Review.decide(.extend, "t1", decision: 1, formulation: Review.form(1), reason: "Waiting for the quote"), to: &state)
        #expect(state.tasks["t1"]?.formulation?.extendedAt == Review.now)
        #expect(state.review.decisions[Review.decision(1)]?.reasonText == "Waiting for the quote")
        #expect(
            Review.error { try Review.apply(Review.decide(.extend, "t1", decision: 2, formulation: Review.form(1), reason: "Again"), to: &state) }
                == .extensionAlreadyUsed
        )
        #expect(
            Review.error { try Review.apply(Review.decide(.extend, "t2", decision: 3, formulation: Review.form(1), reason: "x"), to: &state) }
                == .extensionNotDue
        )
        #expect(
            Review.error { try Review.apply(Review.decide(.extend, "t2", decision: 4, formulation: Review.form(1), reason: "  "), to: &state) }
                == .extensionReasonRequired
        )
    }

    @Test("020-FR-006 020-FR-011 the new GTDValidationError cases")
    func validationErrors() throws {
        var state = Review.state([Review.nextTask("t1", started: t0), Review.task("w1", title: "Drill", state: .waiting)])
        state.tasks["w1"]?.waitingFor = "Sam"
        state.tasks["w1"]?.projectID = "old"
        state.projects["old"] = ProjectRecord(id: "old", name: "Old flat", state: .archived, createdAt: t0)
        #expect(Review.error { try Review.apply(Review.decide(.keepWaiting, "t1"), to: &state) } == .decisionNotAllowed)
        #expect(
            Review.error { try Review.apply(Review.decide(.someday, "t1", formulation: Review.form(9)), to: &state) }
                == .formulationChanged
        )
        #expect(
            Review.error {
                try Review.apply(Review.decide(.followUp, "w1", title: "Text Sam", newFormulation: Review.form(2), followUp: "task_f"), to: &state)
            } == .projectArchived
        )
        #expect(Review.error { try Review.apply(.undoDecision(Review.decision(42)), to: &state) } == .undoUnavailable)
        for error in [GTDValidationError.decisionNotAllowed, .extensionAlreadyUsed, .extensionNotDue, .formulationChanged, .undoUnavailable, .projectArchived] {
            #expect(!error.message.isEmpty && error.message.hasSuffix("."))
        }
    }

    /// `decide` carrying the stamp of the task as the card showed it.
    private func decide(_ type: DecisionType, shown: TaskRecord, decision: Int = 1) -> GTDCommand {
        .decideTask(
            .init(
                decisionID: Review.decision(decision), taskID: shown.id, type: type,
                formulationID: shown.formulation?.id, expectedTask: ShownTask(shown)
            )
        )
    }

    @Test("020-FR-011 a decision on a task that changed in any way since the card showed it is stale; unchanged applies")
    func decisionOnChangedTaskIsStale() throws {
        let asking = Review.nextTask("t1", started: t0, serverRevision: 4)
        let edits: [(String, TaskChanges)] = [
            ("notes", TaskChanges(details: .set("Tiles first"))),
            ("priority", TaskChanges(priority: .set(.high))),
            ("due date", TaskChanges(dueDate: .set(CalendarDay(year: 2026, month: 10, day: 20)!))),
            ("cosmetic title", TaskChanges(title: .set("call bob."))),
        ]
        for (what, changes) in edits {
            var state = Review.state([asking])
            let shown = try #require(state.tasks["t1"])
            // Another window edits the task while the card is open.
            try Review.apply(.updateTask(.init(taskID: "t1", changes: changes)), at: Review.now, to: &state)
            #expect(state.tasks["t1"]?.formulation?.id == shown.formulation?.id, "\(what): same wording")
            let before = state
            #expect(Review.error { try Review.apply(decide(.someday, shown: shown), to: &state) } == .formulationChanged, "\(what)")
            #expect(state == before, "\(what): nothing applied")
        }

        // A sync brings the server's newer revision with only the notes changed.
        var state = Review.state([asking])
        let shown = try #require(state.tasks["t1"])
        state.tasks["t1"]?.details = "Measured the wall"
        state.tasks["t1"]?.serverRevision = 5
        state.tasks["t1"]?.updatedAt = Review.now
        #expect(Review.error { try Review.apply(decide(.complete, shown: shown), to: &state) } == .formulationChanged)

        // Unchanged since the card showed it: applied.
        var unchanged = Review.state([asking])
        try Review.apply(decide(.someday, shown: try #require(unchanged.tasks["t1"])), to: &unchanged)
        #expect(unchanged.tasks["t1"]?.state == .someday)

        // Replay never re-checks it: there the server's revision and yield rule decide (http §3).
        var replayed = state
        try Review.apply(decide(.complete, shown: shown), to: &replayed, mode: .replay)
        #expect(replayed.tasks["t1"]?.state == .completed)
    }

    @Test("020-FR-011 an acknowledgement that moves only the revision and the server-set fields is not a change")
    func acknowledgementIsNotAChange() throws {
        var state = Review.state([Review.nextTask("t1", started: t0, serverRevision: 4)])
        let shown = try #require(state.tasks["t1"])
        // The server acknowledges an edit queued before the card opened.
        state.tasks["t1"]?.serverRevision = 5
        state.tasks["t1"]?.updatedAt = Review.now
        state.tasks["t1"]?.orderKey = 7
        try Review.apply(decide(.someday, shown: shown), to: &state)
        #expect(state.tasks["t1"]?.state == .someday)
    }

    @Test("020-FR-042 while the review is hidden a person's review actions are refused; replay still follows the server")
    func hiddenReviewRefusesInteractiveActions() throws {
        let asking = Review.nextTask("t1", started: t0, serverRevision: 4)
        var parked = Review.task("t2", title: "Update the CV", state: .someday)
        parked.parked = ParkMarker(at: t0, formulationID: Review.form(2))
        let refused: [(String, GTDCommand)] = [
            ("decision", decide(.someday, shown: asking)),
            ("review start", .review(.startSession(StartSession(sessionID: Review.session(1), mode: .quick, entry: .list)))),
            ("bulk release", .bulkRelease(.init(bulkID: Review.bulk(1), kind: .restart, taskIDs: ["t1"]))),
            ("park acknowledgement", .review(.acknowledgeParks([ParkAck(taskID: "t2", formulationID: Review.form(2), parkedAt: t0)]))),
            ("explainer", .review(.acknowledgeExplainer(timeZone: "UTC"))),
        ]
        // Signed in, the last gated read said the flag is off; account-less, the release switch is off.
        var signedIn = Review.state([asking, parked])
        signedIn.review.accountlessReleaseSwitch = nil
        signedIn.review.server = ReviewServerFacts(exposed: false)
        var accountless = Review.state([asking, parked])
        accountless.review.accountlessReleaseSwitch = false
        for hidden in [signedIn, accountless] {
            #expect(!hidden.review.isExposed)
            for (what, command) in refused {
                var state = hidden
                #expect(Review.error { try Review.apply(command, to: &state) } == .reviewUnavailable, "\(what)")
                #expect(state == hidden, "\(what): nothing applied")
            }
            // Replay of a command queued before the flag went off still applies (FR-040).
            var replayed = hidden
            try Review.apply(decide(.someday, shown: asking), to: &replayed, mode: .replay)
            #expect(replayed.tasks["t1"]?.state == .someday)
        }

        // Not refused while hidden: Undo of the person's own action, consent revocation, settings.
        var state = accountless
        state.review.navigatorConsents["openai"] = NavigatorConsent(
            provider: "openai", grantedAt: t0, revokedAt: nil, consentTextVersion: 1
        )
        try Review.apply(.review(.revokeNavigatorConsent(provider: "openai")), to: &state)
        #expect(state.review.navigatorConsents["openai"]?.allowsCloud == false, "a revocation always works")
        try Review.apply(.review(.updateSettings(ReviewSettingsChange(reviewWeekday: 2))), to: &state)
        #expect(state.review.settings.reviewWeekday == 2)

        // Exposed (either way): the decision applies.
        var exposedSignedIn = Review.state([asking])
        exposedSignedIn.review.accountlessReleaseSwitch = nil
        exposedSignedIn.review.server = ReviewServerFacts(exposed: true)
        var exposedAccountless = Review.state([asking])
        exposedAccountless.review.accountlessReleaseSwitch = true
        exposedAccountless.review.server = ReviewServerFacts(exposed: false)
        for var exposed in [exposedSignedIn, exposedAccountless] {
            #expect(exposed.review.isExposed, "account-less: the switch, not a stale server fact")
            try Review.apply(decide(.someday, shown: asking), to: &exposed)
            #expect(exposed.tasks["t1"]?.state == .someday)
        }
    }

    @Test("020-FR-042 the release switch is a device input: it is never encoded with the review state")
    func releaseSwitchIsNotEncoded() throws {
        var review = ReviewState()
        review.accountlessReleaseSwitch = true
        let data = try JSONEncoder().encode(review)
        #expect(!String(decoding: data, as: UTF8.self).contains("accountlessReleaseSwitch"))
        #expect(try JSONDecoder().decode(ReviewState.self, from: data).accountlessReleaseSwitch == nil)
    }

    @Test("020-FR-011 a subtask or comment added, edited or completed since the card showed the task makes the decision stale")
    func childChangesMakeDecisionStale() throws {
        var asking = Review.nextTask("t1", started: t0, serverRevision: 4)
        asking.subtasks = [SubtaskRecord(id: "s1", serverID: "subtask_1", serverRevision: 2, title: "Measure the wall", orderKey: 0)]
        asking.comments = [CommentRecord(id: "c1", serverID: "comment_1", serverRevision: 1, body: "Ask Ann", authorID: "u1", createdAt: t0)]
        asking.childrenSyncedAt = t0  // the card showed the task's children, hydrated
        // Another window: the reducer's child commands leave the parent as it is.
        let windowEdits: [(String, GTDCommand)] = [
            ("subtask added", .createSubtask(.init(taskID: "t1", subtaskID: "s2", title: "Buy tiles"))),
            ("subtask edited", .updateSubtask(.init(taskID: "t1", subtaskID: "s1", title: "Measure both walls"))),
            ("subtask completed", .transitionSubtask(.init(taskID: "t1", subtaskID: "s1", action: .complete))),
            ("comment added", .createComment(.init(taskID: "t1", commentID: "c2", body: "Tiles are in"))),
        ]
        for (what, edit) in windowEdits {
            var state = Review.state([asking])
            let shown = try #require(state.tasks["t1"])
            try Review.apply(edit, at: Review.now, to: &state)
            #expect(TaskStamp(shown).matches(state.tasks["t1"]), "\(what): the parent's stamp alone misses it")
            let before = state
            #expect(Review.error { try Review.apply(decide(.someday, shown: shown), to: &state) } == .formulationChanged, "\(what)")
            #expect(state == before, "\(what): nothing applied")
        }

        // By sync: the server changes a subtask without bumping the task's revision (http.md, data-model).
        let synced: [(String, (inout TaskRecord) -> Void)] = [
            ("subtask completed elsewhere", { $0.subtasks[0].state = .completed; $0.subtasks[0].serverRevision = 3 }),
            ("subtask added elsewhere", {
                $0.subtasks.append(SubtaskRecord(id: "s9", serverID: "subtask_9", serverRevision: 1, title: "Call the tiler", orderKey: 1))
            }),
            ("subtask deleted elsewhere", { $0.subtasks = [] }),
            ("comment edited elsewhere", { $0.comments[0].body = "Ask Ann and Bo"; $0.comments[0].editedAt = Review.now }),
        ]
        for (what, change) in synced {
            var state = Review.state([asking])
            let shown = try #require(state.tasks["t1"])
            change(&state.tasks["t1"]!)
            #expect(Review.error { try Review.apply(decide(.complete, shown: shown), to: &state) } == .formulationChanged, "\(what)")
        }

        // An acknowledgement that changes nothing visible (server ids and revisions) is not a change.
        var acknowledged = Review.state([asking])
        let shown = try #require(acknowledged.tasks["t1"])
        acknowledged.tasks["t1"]?.subtasks[0].serverRevision = 5
        acknowledged.tasks["t1"]?.comments[0].serverRevision = 2
        try Review.apply(decide(.someday, shown: shown), to: &acknowledged)
        #expect(acknowledged.tasks["t1"]?.state == .someday)

        // No change at all: applied.
        var unchanged = Review.state([asking])
        try Review.apply(decide(.someday, shown: try #require(unchanged.tasks["t1"])), to: &unchanged)
        #expect(unchanged.tasks["t1"]?.state == .someday)
    }

    @Test("020-FR-011 children hydrated after the card opened are not a change; a parent edit still is; local tasks know their children")
    func hydrationIsNotAChange() throws {
        // Pulled, not hydrated yet: the list endpoint carries no children.
        let unhydrated = Review.nextTask("t1", started: t0, serverRevision: 4)
        #expect(unhydrated.serverID != nil && unhydrated.childrenSyncedAt == nil)
        let existing = SubtaskRecord(id: "s1", serverID: "subtask_1", serverRevision: 2, title: "Measure the wall", orderKey: 0)
        let comment = CommentRecord(id: "c1", serverID: "comment_1", serverRevision: 1, body: "Ask Ann", authorID: "u1", createdAt: t0)

        // Hydration fills the children that already existed: the decision applies.
        var hydrated = Review.state([unhydrated])
        let shown = try #require(hydrated.tasks["t1"])
        hydrated.tasks["t1"]?.subtasks = [existing]
        hydrated.tasks["t1"]?.comments = [comment]
        hydrated.tasks["t1"]?.childrenSyncedAt = Review.now
        try Review.apply(decide(.someday, shown: shown), to: &hydrated)
        #expect(hydrated.tasks["t1"]?.state == .someday, "unknown children becoming known is not an edit")

        // A parent edit after an unhydrated snapshot is still stale.
        var edited = Review.state([unhydrated])
        try Review.apply(.updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("Tiles first")))), at: Review.now, to: &edited)
        #expect(Review.error { try Review.apply(decide(.someday, shown: shown), to: &edited) } == .formulationChanged)

        // A task the server has not seen yet: every child is on the device, so a child edit counts.
        var local = Review.nextTask("t2", started: t0)
        local.subtasks = [SubtaskRecord(id: "s2", title: "Buy tiles", orderKey: 0)]
        #expect(local.serverID == nil && local.childrenSyncedAt == nil)
        var state = Review.state([local])
        let shownLocal = try #require(state.tasks["t2"])
        try Review.apply(.transitionSubtask(.init(taskID: "t2", subtaskID: "s2", action: .complete)), at: Review.now, to: &state)
        #expect(Review.error { try Review.apply(decide(.someday, shown: shownLocal), to: &state) } == .formulationChanged)
    }

    @Test("020-FR-011 before full hydration the children the card did show still count: changed or deleted is stale, added is not")
    func shownChildrenCountBeforeHydration() throws {
        // Pulled, not fully hydrated, but already holding a cached subtask and comment.
        var cached = Review.nextTask("t1", started: t0, serverRevision: 4)
        cached.subtasks = [
            SubtaskRecord(id: "s1", serverID: "subtask_1", serverRevision: 2, title: "Measure the wall", orderKey: 0),
            SubtaskRecord(id: "s2", serverID: "subtask_2", serverRevision: 1, title: "Buy tiles", orderKey: 1),
        ]
        cached.comments = [CommentRecord(id: "c1", serverID: "comment_1", serverRevision: 1, body: "Ask Ann", authorID: "u1", createdAt: t0)]
        #expect(cached.childrenSyncedAt == nil)

        let changes: [(String, GTDCommand?, (inout TaskRecord) -> Void)] = [
            ("cached subtask completed in another window", .transitionSubtask(.init(taskID: "t1", subtaskID: "s1", action: .complete)), { _ in }),
            ("cached subtask renamed in another window", .updateSubtask(.init(taskID: "t1", subtaskID: "s2", title: "Buy blue tiles")), { _ in }),
            ("cached subtask deleted elsewhere", nil, { $0.subtasks.removeAll { $0.id == "s1" } }),
            ("cached comment edited elsewhere", nil, { $0.comments[0].body = "Ask Ann and Bo" }),
            ("cached comment deleted elsewhere", nil, { $0.comments = [] }),
            ("cached subtasks reordered elsewhere", nil, { $0.subtasks[0].orderKey = 5 }),
        ]
        for (what, command, change) in changes {
            var state = Review.state([cached])
            let shown = try #require(state.tasks["t1"])
            if let command { try Review.apply(command, at: Review.now, to: &state) }
            change(&state.tasks["t1"]!)
            #expect(Review.error { try Review.apply(decide(.someday, shown: shown), to: &state) } == .formulationChanged, "\(what)")
        }

        // Hydration adds the other children that already existed (and server order keys): applies.
        var hydrated = Review.state([cached])
        let shown = try #require(hydrated.tasks["t1"])
        hydrated.tasks["t1"]?.subtasks.append(
            SubtaskRecord(id: "s3", serverID: "subtask_3", serverRevision: 1, title: "Call the tiler", orderKey: 2)
        )
        hydrated.tasks["t1"]?.subtasks[0].orderKey = 10
        hydrated.tasks["t1"]?.subtasks[1].orderKey = 20
        hydrated.tasks["t1"]?.comments.append(
            CommentRecord(id: "c2", serverID: "comment_2", serverRevision: 1, body: "Tiles are in", authorID: "u2", createdAt: t0)
        )
        hydrated.tasks["t1"]?.childrenSyncedAt = Review.now
        try Review.apply(decide(.someday, shown: shown), to: &hydrated)
        #expect(hydrated.tasks["t1"]?.state == .someday, "children the card did not show are not a change; relative order kept")
    }

    /// `decide` with the card's snapshot taken with this device's child-edit count.
    private func decide(_ type: DecisionType, shown: ShownTask, taskID: TaskID = "t1") -> GTDCommand {
        .decideTask(
            .init(
                decisionID: Review.decision(1), taskID: taskID, type: type, formulationID: Review.form(1),
                expectedTask: shown
            )
        )
    }

    @Test("020-FR-011 a child this device creates or edits after the card opened makes the decision stale, acknowledged or not")
    func localChildEditsAreCounted() throws {
        var cached = Review.nextTask("t1", started: t0, serverRevision: 4)
        cached.subtasks = [SubtaskRecord(id: "s1", serverID: "subtask_1", serverRevision: 2, title: "Measure the wall", orderKey: 0)]
        #expect(cached.childrenSyncedAt == nil, "not fully hydrated")
        let edits: [(String, GTDCommand)] = [
            ("subtask created in another window", .createSubtask(.init(taskID: "t1", subtaskID: "s2", title: "Buy tiles"))),
            ("comment added in another window", .createComment(.init(taskID: "t1", commentID: "c2", body: "Tiles are in"))),
        ]
        for (what, edit) in edits {
            // Tracked, as the workspace does: the card captures the count.
            var state = Review.state([cached])
            state.localChildEdits = [:]
            let shown = ShownTask(try #require(state.tasks["t1"]), localChildEdits: 0)
            try Review.apply(edit, at: Review.now, to: &state)
            #expect(state.localChildEdits?["t1"] == 1, "\(what): counted")
            var unsent = state
            #expect(Review.error { try Review.apply(decide(.someday, shown: shown), to: &unsent) } == .formulationChanged, "\(what), not acknowledged")

            // The server acknowledges it before the decision: it now carries a
            // server id, like a child hydration brought in; the count still says.
            var acknowledged = state
            if let index = acknowledged.tasks["t1"]?.subtasks.firstIndex(where: { $0.id == "s2" }) {
                acknowledged.tasks["t1"]?.subtasks[index].serverID = "subtask_2"
                acknowledged.tasks["t1"]?.subtasks[index].serverRevision = 1
            }
            if let index = acknowledged.tasks["t1"]?.comments.firstIndex(where: { $0.id == "c2" }) {
                acknowledged.tasks["t1"]?.comments[index].serverID = "comment_2"
                acknowledged.tasks["t1"]?.comments[index].serverRevision = 1
            }
            #expect(
                Review.error { try Review.apply(decide(.someday, shown: shown), to: &acknowledged) } == .formulationChanged,
                "\(what), acknowledged"
            )
        }

        // Replay never counts: acknowledgement and recompute keep the device's count.
        var replayed = Review.state([cached])
        replayed.localChildEdits = [:]
        try Review.apply(.createSubtask(.init(taskID: "t1", subtaskID: "s2", title: "Buy tiles")), to: &replayed, mode: .replay)
        #expect(replayed.localChildEdits?["t1"] == nil)
        // Untracked states (nil) are never counted.
        var untracked = Review.state([cached])
        try Review.apply(.createSubtask(.init(taskID: "t1", subtaskID: "s2", title: "Buy tiles")), to: &untracked)
        #expect(untracked.localChildEdits == nil)

        // No child edit since the card opened, hydration bringing existing children: applies.
        var hydrated = Review.state([cached])
        hydrated.localChildEdits = ["t1": 3]
        let shownBefore = ShownTask(try #require(hydrated.tasks["t1"]), localChildEdits: 3)
        hydrated.tasks["t1"]?.subtasks.append(
            SubtaskRecord(id: "s3", serverID: "subtask_3", serverRevision: 1, title: "Call the tiler", orderKey: 1)
        )
        hydrated.tasks["t1"]?.childrenSyncedAt = Review.now
        try Review.apply(decide(.someday, shown: shownBefore), to: &hydrated)
        #expect(hydrated.tasks["t1"]?.state == .someday)

        // The shown child edited by sync is still caught after hydration.
        var synced = Review.state([cached])
        synced.localChildEdits = [:]
        let shownSynced = ShownTask(try #require(synced.tasks["t1"]), localChildEdits: 0)
        synced.tasks["t1"]?.subtasks[0].state = .completed
        synced.tasks["t1"]?.childrenSyncedAt = Review.now
        #expect(Review.error { try Review.apply(decide(.someday, shown: shownSynced), to: &synced) } == .formulationChanged)
    }

    @Test("020-FR-011 before full hydration a child hydration brings is not a change")
    func hydratedChildrenBeforeHydration() throws {
        var cached = Review.nextTask("t1", started: t0, serverRevision: 4)
        cached.subtasks = [SubtaskRecord(id: "s1", serverID: "subtask_1", serverRevision: 2, title: "Measure the wall", orderKey: 0)]
        #expect(cached.childrenSyncedAt == nil)

        // Hydration brings existing server children: applies.
        var hydrated = Review.state([cached])
        let shown = try #require(hydrated.tasks["t1"])
        hydrated.tasks["t1"]?.subtasks.append(
            SubtaskRecord(id: "s3", serverID: "subtask_3", serverRevision: 1, title: "Call the tiler", orderKey: 1)
        )
        hydrated.tasks["t1"]?.comments.append(
            CommentRecord(id: "c3", serverID: "comment_3", serverRevision: 1, body: "Ask Ann", authorID: "u2", createdAt: t0)
        )
        hydrated.tasks["t1"]?.childrenSyncedAt = Review.now
        try Review.apply(decide(.someday, shown: shown), to: &hydrated)
        #expect(hydrated.tasks["t1"]?.state == .someday)
    }

    @Test("020-FR-011 the stamp a card showed is local: it is never encoded into the queued command")
    func expectedTaskIsNotEncoded() throws {
        let shown = Review.nextTask("t1", started: t0, serverRevision: 4)
        let command = decide(.someday, shown: shown)
        let data = try JSONEncoder().encode(command)
        #expect(!String(decoding: data, as: UTF8.self).contains("expectedTask"))
        guard case .decideTask(let decoded) = try JSONDecoder().decode(GTDCommand.self, from: data) else {
            Issue.record("Expected a decision")
            return
        }
        #expect(decoded.expectedTask == nil && decoded.taskID == "t1" && decoded.type == .someday)
    }

    // MARK: - Undo (T051, FR-048)

    @Test("020-FR-048 undo restores the task field for field, clock included, and deletes an unchanged follow-up")
    func undoRestores() throws {
        let original = Review.nextTask("t1", title: "Renovate the bathroom", started: t0)
        var state = Review.state([original, Review.task("w1", title: "Drill", state: .waiting)])
        state.tasks["w1"]?.waitingFor = "Sam"
        let waiting = try #require(state.tasks["w1"])
        try Review.apply(Review.decide(.someday, "t1", decision: 1, formulation: Review.form(1)), to: &state)
        try Review.apply(
            Review.decide(.followUp, "w1", decision: 2, title: "Text Sam", newFormulation: Review.form(4), followUp: "task_follow"),
            to: &state
        )
        #expect(state.tasks["task_follow"]?.state == .next && state.tasks["task_follow"]?.formulation?.id == Review.form(4))
        let undoAt = Review.now.addingTimeInterval(4)
        try Review.apply(.undoDecision(Review.decision(1)), at: undoAt, to: &state)
        try Review.apply(.undoDecision(Review.decision(2)), at: undoAt, to: &state)
        // Field for field, `updatedAt` included (as compaction's cancel leaves it).
        #expect(state.tasks["t1"] == original)
        #expect(state.tasks["task_follow"] == nil)
        #expect(state.tasks["w1"]?.waitingFor == waiting.waitingFor)
        #expect(state.review.decisions.isEmpty)
        #expect(state.review.receipts.isEmpty, "the receipts the decisions wrote are gone")
    }

    @Test("020-FR-048 020-FR-046 undo into Next keeps a park floor written since the decision")
    func undoKeepsFloorWrittenSince() throws {
        let due = CalendarDay(year: 2026, month: 9, day: 20)
        var state = Review.state([Review.nextTask("t1", started: t0, due: due)])
        try Review.apply(Review.decide(.extend, "t1", decision: 1, formulation: Review.form(1), reason: "Waiting for the quote"), to: &state)
        // A time-zone change floors due-dated Next tasks without touching the task's revision or `updatedAt`.
        try Review.apply(.review(.updateSettings(.init(timeZone: "America/New_York"))), at: Review.now.addingTimeInterval(60), to: &state)
        let floor = try #require(state.tasks["t1"]?.formulation?.parkFloorAt)
        try Review.apply(.undoDecision(Review.decision(1)), at: Review.now.addingTimeInterval(120), to: &state)
        let clock = try #require(state.tasks["t1"]?.formulation)
        #expect(clock.extendedAt == nil && clock.extensionReason == nil, "the extension is undone")
        #expect(clock.parkFloorAt == floor, "the floor written after the decision survives")
    }

    @Test("020-FR-048 020-FR-016 a decision made before activation, undone after it, restores the clock with the activation clamp")
    func undoClampsToActivation() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)], settings: ReviewSettings())
        try Review.apply(Review.decide(.someday, "t1", decision: 1, formulation: Review.form(1)), to: &state)
        try Review.apply(.review(.acknowledgeExplainer(timeZone: "Europe/Berlin")), at: Review.now, to: &state)
        try Review.apply(.undoDecision(Review.decision(1)), at: Review.now.addingTimeInterval(60), to: &state)
        let clock = try #require(state.tasks["t1"]?.formulation)
        #expect(state.tasks["t1"]?.state == .next && clock.id == Review.form(1))
        #expect(clock.startedAt == Review.now)
        #expect(clock.parkFloorAt == Review.now.addingTimeInterval(14 * Review.day))
    }

    @Test("020-FR-048 undo is refused when the task or the follow-up changed since; an absent decision is already undone")
    func undoRefused() throws {
        var state = Review.state([Review.nextTask("t1", started: t0), Review.task("w1", title: "Drill", state: .waiting)])
        state.tasks["w1"]?.waitingFor = "Sam"
        try Review.apply(Review.decide(.someday, "t1", decision: 1, formulation: Review.form(1)), to: &state)
        try Review.apply(.updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("later")))), at: Review.now.addingTimeInterval(1), to: &state)
        #expect(Review.error { try Review.apply(.undoDecision(Review.decision(1)), to: &state) } == .undoUnavailable)
        try Review.apply(Review.decide(.followUp, "w1", decision: 2, title: "Text Sam", newFormulation: Review.form(4), followUp: "task_follow"), to: &state)
        try Review.apply(.updateTask(.init(taskID: "task_follow", changes: TaskChanges(details: .set("x")))), at: Review.now.addingTimeInterval(2), to: &state)
        #expect(Review.error { try Review.apply(.undoDecision(Review.decision(2)), to: &state) } == .undoUnavailable)
        var replayed = state
        #expect(try Review.apply(.undoDecision(Review.decision(9)), to: &replayed, mode: .replay) == .alreadySatisfied)
    }

    // MARK: - Compaction (T051, T133)

    @Test("020-FR-048 an unsent decision and its undo cancel in compaction")
    func decisionAndUndoCancel() {
        var outbox: [PendingOperation] = []
        outbox = OutboxCompactor.appending(Review.op(Review.decide(.someday, "t1", formulation: Review.form(1)), at: Review.now), to: outbox)
        outbox = OutboxCompactor.appending(Review.op(.undoDecision(Review.decision(1)), at: Review.now), to: outbox)
        #expect(outbox.isEmpty)
        var sent = Review.op(Review.decide(.someday, "t1", formulation: Review.form(1)), at: Review.now)
        sent.attempts = 1
        let kept = OutboxCompactor.appending(Review.op(.undoDecision(Review.decision(1)), at: Review.now), to: [sent])
        #expect(kept.count == 2, "a sent decision is never modified")
    }

    @Test("020-FR-001 once exposed, a title change or a move is never folded into an unsent creation")
    func clockAwareCompaction() {
        let create = Review.op(.createTask(.init(taskID: "t1", title: "Call Bob", list: .next, newFormulationID: Review.form(1))), at: t0)
        let rename = Review.op(.updateTask(.init(taskID: "t1", changes: TaskChanges(title: .set("Email Bob")), newFormulationID: Review.form(2))), at: Review.now)
        let move = Review.op(.transitionTask(.init(taskID: "t1", action: .move, toList: .someday)), at: Review.now)
        let notes = Review.op(.updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("x")))), at: Review.now)
        var aware = OutboxCompactor.appending(create, to: [], clockAware: true)
        aware = OutboxCompactor.appending(rename, to: aware, clockAware: true)
        aware = OutboxCompactor.appending(move, to: aware, clockAware: true)
        aware = OutboxCompactor.appending(notes, to: aware, clockAware: true)
        #expect(aware.count == 3, "the notes edit still folds; the rename and the move do not")
        var legacy = OutboxCompactor.appending(create, to: [])
        legacy = OutboxCompactor.appending(rename, to: legacy)
        #expect(legacy.count == 1, "without the review, folding is unchanged")
    }

    /// Compacted and uncompacted replays give identical clocks for every
    /// transition vector a queued task command expresses.
    @Test(
        "020-FR-001 020-FR-009 compacted vs uncompacted replays give identical formulation fields for every transition vector",
        arguments: ReviewVectors.section(ReviewVectors.formulation, "transitions")
    )
    func compactedReplayKeepsClocks(_ vector: Vector) throws {
        guard let scenario = try CompactionScenario(vector) else {
            // Owner-level events, the yield, the undos and refused events are
            // not a queued command of one task; FormulationTests runs every
            // one of the 67 vectors through the rule itself.
            #expect(Self.notQueued.contains(vector["event"]?["type"]?.string ?? "") || vector["expect"]?["error"] != nil
                || vector["expect"]?["applied"]?.bool == false, "\(vector.id) skipped without a reason")
            return
        }
        let plainResult = OutboxReplayer.replay(scenario.operations, onto: Review.state([], settings: scenario.settings))
        var compacted: [PendingOperation] = []
        for operation in scenario.operations {
            compacted = OutboxCompactor.appending(operation, to: compacted, clockAware: true)
        }
        let foldedResult = OutboxReplayer.replay(compacted, onto: Review.state([], settings: scenario.settings))
        #expect(plainResult.rejected.isEmpty, "\(vector.id): \(plainResult.rejected)")
        #expect(foldedResult.rejected.isEmpty, "\(vector.id): \(foldedResult.rejected)")
        let lhs = plainResult.state.tasks["t1"].map(ClockFields.init)
        let rhs = foldedResult.state.tasks["t1"].map(ClockFields.init)
        #expect(lhs == rhs)
        // And both match the vector where the queued scenario reproduces the
        // vector's starting point (state, formulation id and start).
        let expect = try #require(vector["expect"])
        let task = try #require(foldedResult.state.tasks["t1"])
        if let state = expect["state"]?.string { #expect(task.state.rawValue == state, "\(vector.id)") }
        if let id = expect["formulation_id"] {
            #expect(task.formulation?.id.rawValue == id.string, "\(vector.id)")
        }
        if let started = expect["formulation_started_at"], scenario.reproducesStart {
            #expect(task.formulation?.startedAt == ReviewVectors.instant(started), "\(vector.id)")
        }
        if let title = expect["title"]?.string { #expect(task.title == title, "\(vector.id)") }
    }

    static let notQueued: Set = [
        "activate", "yield_reversal", "time_zone_change", "repair", "sweep_gap", "threshold_change", "undo_decision",
        "bulk_release", "undo_bulk_release",
    ]

    @Test("020-FR-001 the compaction scenarios cover every queued-command vector")
    func compactionCoverage() throws {
        let vectors = ReviewVectors.section(ReviewVectors.formulation, "transitions")
        var covered = 0
        for vector in vectors where try CompactionScenario(vector) != nil { covered += 1 }
        let queued = vectors.filter { vector in
            !Self.notQueued.contains(vector["event"]?["type"]?.string ?? "") && vector["expect"]?["error"] == nil
                && vector["expect"]?["applied"]?.bool != false
        }
        #expect(covered == queued.count)
        #expect(vectors.count == 67)
    }

    struct ClockFields: Hashable {
        var state: TaskState
        var formulation: FormulationClock?
        var stalled: Int
        var parked: ParkMarker?

        init(_ task: TaskRecord) {
            state = task.state
            formulation = task.formulation
            stalled = task.consecutiveStalledFormulations
            parked = task.parked
        }
    }

    /// A transition vector as a queued outbox: the task's unsent creation at
    /// the formulation start, a move to its list, then the event.
    struct CompactionScenario {
        var settings: ReviewSettings
        var operations: [PendingOperation]
        /// The queued creation starts the clock where the vector's did (no
        /// activation clamp moves it).
        var reproducesStart = false

        init?(_ vector: Vector) throws {
            let before = try #require(vector["before"])
            let event = try #require(vector["event"])
            let expect = try #require(vector["expect"])
            guard expect["error"] == nil, expect["applied"]?.bool != false else { return nil }
            let now = try #require(ReviewVectors.instant(vector["now"]))
            let raw = try #require(vector["settings"])
            settings = ReviewSettings(
                thresholdDays: raw["threshold_days"]?.int ?? 14, timeZone: raw["time_zone"]?.string ?? "UTC",
                activatedAt: ReviewVectors.instant(raw["activated_at"]),
                ownerParkFloorAt: ReviewVectors.instant(raw["owner_park_floor_at"])
            )
            let start = ReviewVectors.instant(before["formulation_started_at"]) ?? now.addingTimeInterval(-10 * 86_400)
            let formulation = FormulationID(before["formulation_id"]?.string ?? "form_a")
            let state = before["state"]?.string.flatMap(TaskState.init(rawValue:)) ?? .next
            var operations = [
                Review.op(
                    .createTask(
                        .init(
                            taskID: "t1", title: before["title"]?.string ?? "Call Bob", list: .next,
                            dueDate: ReviewVectors.day(before["due_date"]), newFormulationID: formulation
                        )
                    ), at: start
                )
            ]
            if let list = state.openList, list != .next {
                operations.append(
                    Review.op(.transitionTask(.init(taskID: "t1", action: .move, toList: list, waitingFor: "Ann")), at: start.addingTimeInterval(60))
                )
            }
            let newID = event["new_formulation_id"]?.string.map { FormulationID($0) }
            if let started = ReviewVectors.instant(before["formulation_started_at"]) {
                reproducesStart = settings.activatedAt.map { started > $0 } ?? true
            }
            if event["type"]?.string == "create_in_next" {
                self.operations = [
                    Review.op(
                        .createTask(.init(taskID: "t1", title: event["title"]?.string ?? "Call Bob", list: .next, newFormulationID: newID)),
                        at: now
                    )
                ]
                reproducesStart = settings.activatedAt.map { now > $0 } ?? true
                return
            }
            let command: GTDCommand
            switch event["type"]?.string {
            case "update_title":
                command = .updateTask(.init(taskID: "t1", changes: TaskChanges(title: .set(event["title"]?.string ?? "")), newFormulationID: newID))
            case "update_due_date":
                let due: FieldChange<CalendarDay> = ReviewVectors.day(event["due_date"]).map { .set($0) } ?? .clear
                command = .updateTask(.init(taskID: "t1", changes: TaskChanges(dueDate: due)))
            case "update_other":
                command = .updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("notes"))))
            case "transition":
                guard let target = event["to"]?.string.flatMap(TaskState.init(rawValue:)) else { return nil }
                switch target {
                case .completed: command = .transitionTask(.init(taskID: "t1", action: .complete))
                case .cancelled: command = .transitionTask(.init(taskID: "t1", action: .cancel))
                default:
                    command = .transitionTask(
                        .init(taskID: "t1", action: .move, toList: target.openList, waitingFor: "Ann", newFormulationID: newID)
                    )
                }
            case "decide":
                guard let type = event["decision_type"]?.string.flatMap(DecisionType.init(rawValue:)) else { return nil }
                command = Review.decide(
                    type, "t1", formulation: type.decidesOnFormulation ? formulation : nil, title: event["title"]?.string,
                    waitingFor: event["waiting_for"]?.string, reason: event["reason"]?.string, newFormulation: newID
                )
            case "auto_park":
                command = .autoParkTask(.init(taskID: "t1", formulationID: formulation))
            default:
                // Owner-level events (activation, sweep gap, threshold or zone
                // change), the yield and the undos are not queued task commands.
                return nil
            }
            operations.append(Review.op(command, at: now))
            self.operations = operations
        }
    }

    // MARK: - Activation and auto-park (T087)

    @Test("020-FR-051 acknowledging the explainer writes only the activation instant and changes no task")
    func acknowledgeExplainer() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)], settings: ReviewSettings())
        let tasks = state.tasks
        try Review.apply(.review(.acknowledgeExplainer(timeZone: "Europe/Berlin")), to: &state)
        #expect(state.tasks == tasks)
        #expect(state.review.settings.activatedAt == Review.now)
        #expect(state.review.settings.timeZone == "Europe/Berlin")
        try Review.apply(.review(.acknowledgeExplainer(timeZone: "Pacific/Honolulu")), at: Review.now.addingTimeInterval(60), to: &state)
        #expect(state.review.settings.activatedAt == Review.now && state.review.settings.timeZone == "Europe/Berlin", "first wins")
    }

    @Test("020-FR-016 020-FR-051 the post-replay activation step clamps every Next clock whatever the fold order")
    func activationStep() {
        let activation = Review.now
        let create = Review.op(.createTask(.init(taskID: "t1", title: "Call Bob", list: .next, newFormulationID: Review.form(1))), at: t0)
        let notes = Review.op(.updateTask(.init(taskID: "t1", changes: TaskChanges(details: .set("x")))), at: t0.addingTimeInterval(60))
        let ack = Review.op(.review(.acknowledgeExplainer(timeZone: "Europe/Berlin")), at: activation)
        let base = Review.state([], settings: ReviewSettings())
        let first = OutboxReplayer.replay([create, notes, ack], onto: base).state
        let second = OutboxReplayer.replay([ack, create, notes], onto: base).state
        let folded = OutboxReplayer.replay(OutboxCompactor.appending(notes, to: [ack, create], clockAware: true), onto: base).state
        let expected = FormulationClock(
            id: Review.form(1), startedAt: activation, parkFloorAt: activation.addingTimeInterval(14 * Review.day)
        )
        #expect(first.tasks["t1"]?.formulation == expected)
        #expect(second.tasks["t1"]?.formulation == expected)
        #expect(folded.tasks["t1"]?.formulation == expected)
        // Account-less (local anchor only): the same clamp.
        let anchored = OutboxReplayer.replay([create, notes], onto: base, activatedAt: activation).state
        #expect(anchored.tasks["t1"]?.formulation == expected)
    }

    @Test("020-FR-012 020-FR-051 autoParkTask parks iff activated and park_due, storing the clock before it")
    func autoPark() throws {
        let task = Review.nextTask("t1", started: t0)
        let due = Review.instant("2026-10-15T09:14:00Z")
        var notActivated = Review.state([task], settings: Review.settings(activatedAt: nil))
        #expect(
            Review.error { try Review.apply(.autoParkTask(.init(taskID: "t1", formulationID: Review.form(1))), at: due, to: &notActivated) }
                == .decisionNotAllowed
        )
        #expect(GTDQueries.dueAutoParks(in: notActivated, now: due).isEmpty, "nothing parks before activation")
        var state = Review.state([task])
        #expect(
            Review.error {
                try Review.apply(.autoParkTask(.init(taskID: "t1", formulationID: Review.form(1))), at: due.addingTimeInterval(-1), to: &state)
            } == .decisionNotAllowed, "one second early"
        )
        #expect(GTDQueries.dueAutoParks(in: state, now: due).map(\.id) == ["t1"])
        try Review.apply(.autoParkTask(.init(taskID: "t1", formulationID: Review.form(1))), at: due, to: &state)
        let parked = try #require(state.tasks["t1"])
        #expect(parked.state == .someday && parked.formulation == nil)
        #expect(parked.parked?.clockBefore == task.formulation && parked.parked?.at == due)
        #expect(GTDQueries.unseenParks(in: state).map(\.id) == ["t1"])
        var replayed = state
        #expect(
            try Review.apply(.autoParkTask(.init(taskID: "t1", formulationID: Review.form(1))), at: due, to: &replayed, mode: .replay)
                == .alreadySatisfied, "already parked for that formulation"
        )
    }

    @Test("020-FR-015 a seen park stays seen; a repeat park of the same formulation is unseen again (data-model E6)")
    func repeatParkIsUnseen() throws {
        let due = Review.instant("2026-10-15T09:14:00Z")
        var state = Review.state([Review.nextTask("t1", started: t0)])
        try Review.apply(.autoParkTask(.init(taskID: "t1", formulationID: Review.form(1))), at: due, to: &state)
        let marker = try #require(state.tasks["t1"]?.parked)
        try Review.apply(.review(.acknowledgeParks([ParkAck(taskID: "t1", formulationID: Review.form(1), parkedAt: marker.at)])), to: &state)
        #expect(GTDQueries.unseenParks(in: state).isEmpty)
        // Yield: a decision made before the park on the parked formulation.
        try Review.apply(
            Review.decide(.reformulate, "t1", decision: 1, formulation: Review.form(1), title: "call bob.", newFormulation: Review.form(2)),
            at: due.addingTimeInterval(-60), to: &state, mode: .replay
        )
        #expect(state.tasks["t1"]?.state == .next && state.tasks["t1"]?.formulation?.id == Review.form(1))
        #expect(state.review.decisions[Review.decision(1)]?.yieldedAutoPark == true)
        try Review.apply(.undoDecision(Review.decision(1)), at: due.addingTimeInterval(120), to: &state)
        try Review.apply(.autoParkTask(.init(taskID: "t1", formulationID: Review.form(1))), at: due.addingTimeInterval(300), to: &state)
        #expect(GTDQueries.unseenParks(in: state).map(\.id) == ["t1"], "the repeat park shows again")
    }

    @Test("020-FR-018 020-FR-051 the explainer is needed until activation or a local sighting")
    func explainerNeeded() {
        let state = Review.state([], settings: ReviewSettings())
        #expect(GTDQueries.explainerNeeded(in: state, local: .empty))
        #expect(!GTDQueries.explainerNeeded(in: state, local: LocalReviewState(explainerSeenLocally: true)))
        #expect(!GTDQueries.explainerNeeded(in: Review.state([]), local: .empty))
    }

    // MARK: - Consent (T108)

    @Test("020-FR-024 granting and revoking consent are idempotent; a revoke blocks cloud use on the device at once")
    func consent() throws {
        var state = Review.state([])
        try Review.apply(.review(.grantNavigatorConsent(provider: "openai", consentTextVersion: 1)), to: &state)
        #expect(state.review.navigatorConsents["openai"]?.allowsCloud == true)
        var replay = state
        #expect(try Review.apply(.review(.grantNavigatorConsent(provider: "openai", consentTextVersion: 1)), to: &replay, mode: .replay) == .alreadySatisfied)
        try Review.apply(.review(.revokeNavigatorConsent(provider: "openai")), at: Review.now.addingTimeInterval(5), to: &state)
        #expect(state.review.navigatorConsents["openai"]?.allowsCloud == false)
        #expect(try Review.apply(.review(.revokeNavigatorConsent(provider: "openai")), to: &state, mode: .replay) == .alreadySatisfied)
    }

    // MARK: - Runs and bulk releases (T133)

    @Test("020-FR-029 020-SC-004 run commands: start, merged progress replay-safe by progressID, finish")
    func runCommands() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(1), mode: .quick, entry: .list))), to: &state)
        let progress = SessionProgress(
            sessionID: Review.session(1), progressID: Review.progress(1), currentStep: .inbox, step: .wins,
            stepStatus: .finished, activeStep: .wins, activeSeconds: 42, inboxProcessedDelta: 1
        )
        try Review.apply(.review(.progressSession(progress)), to: &state)
        var replayed = state
        #expect(try Review.apply(.review(.progressSession(progress)), to: &replayed, mode: .replay) == .alreadySatisfied)
        let session = try #require(state.review.sessions[Review.session(1)])
        #expect(session.activeSecondsByStep[.wins] == 42 && session.counts[.inboxProcessed] == 1)
        #expect(session.steps[.wins] == .finished && session.currentStep == .inbox)
        try Review.apply(.review(.finishSession(.init(sessionID: Review.session(1), clearStart: .yes))), to: &state)
        #expect(state.review.sessions[Review.session(1)]?.status == .completed)
        // A new start replaces an open review (replace_open).
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(2), mode: .full, entry: .list))), to: &state)
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(3), mode: .quick, entry: .widgetDecisions, skipSteps: [.wins, .inbox]))), to: &state)
        #expect(state.review.sessions[Review.session(2)]?.status == .abandoned)
        #expect(state.review.sessions[Review.session(3)]?.currentStep == .decisions)
    }

    @Test("020-FR-028 progress naming a step outside the review's mode is refused and queues nothing, whatever the status")
    func progressOutsideModeIsRefused() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(1), mode: .quick, entry: .list))), to: &state)
        let outOfMode: [SessionProgress] = [
            .init(sessionID: Review.session(1), progressID: Review.progress(1), step: .dates, stepStatus: .finished),
            .init(sessionID: Review.session(1), progressID: Review.progress(2), activeStep: .restOfNext, activeSeconds: 30),
        ]
        func expectRefusals() {
            for progress in outOfMode {
                let before = state
                #expect(Review.error { try Review.apply(.review(.progressSession(progress)), to: &state) } == .stepNotInReview)
                #expect(state == before, "the session is unchanged")
            }
        }
        expectRefusals()
        try Review.apply(.review(.finishSession(.init(sessionID: Review.session(1)))), to: &state)
        expectRefusals()
        // A mode's own steps are still merged.
        var full = Review.state([])
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(2), mode: .full, entry: .list))), to: &full)
        let inMode = SessionProgress(sessionID: Review.session(2), progressID: Review.progress(3), step: .dates, stepStatus: .skipped)
        try Review.apply(.review(.progressSession(inMode)), to: &full)
        #expect(full.review.sessions[Review.session(2)]?.steps[.dates] == .skipped)
        var quick = Review.state([])
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(3), mode: .quick, entry: .list))), to: &quick)
        let inQuick = SessionProgress(sessionID: Review.session(3), progressID: Review.progress(4), step: .wins, stepStatus: .finished, activeStep: .inbox, activeSeconds: 5)
        try Review.apply(.review(.progressSession(inQuick)), to: &quick)
        #expect(quick.review.sessions[Review.session(3)]?.steps[.wins] == .finished)
    }

    @Test("020-FR-029 progressSession is never folded into another one")
    func progressNeverFolds() {
        var outbox: [PendingOperation] = []
        for n in 1...3 {
            let progress = SessionProgress(sessionID: Review.session(1), progressID: Review.progress(n), currentStep: .decisions)
            outbox = OutboxCompactor.appending(Review.op(.review(.progressSession(progress)), at: Review.now), to: outbox, clockAware: true)
        }
        #expect(outbox.count == 3)
    }

    @Test("020-FR-017 020-FR-030 bulk release and its undo restore every clock exactly; an unsent pair cancels")
    func bulkRelease() throws {
        let old = Review.nextTask("old", started: Review.now.addingTimeInterval(-30 * Review.day), extendedAt: Review.now.addingTimeInterval(-15 * Review.day))
        let young = Review.nextTask("young", started: Review.now.addingTimeInterval(-20 * Review.day))
        var state = Review.state([old, young])
        state.review.settings.activatedAt = Review.instant("2026-08-01T08:00:00Z")
        let before = state.tasks
        try Review.apply(.bulkRelease(.init(bulkID: Review.bulk(1), kind: .restart, taskIDs: ["old", "young", "missing"])), to: &state)
        let record = try #require(state.review.bulkReleases[Review.bulk(1)])
        #expect(record.released.map(\.taskID) == ["old"])
        #expect(Set(record.skipped.map(\.taskID)) == ["young", "missing"], "too young or unknown: not eligible")
        #expect(state.tasks["old"]?.state == .someday && state.tasks["old"]?.parked == nil)
        try Review.apply(.undoBulkRelease(Review.bulk(1)), at: Review.now.addingTimeInterval(30), to: &state)
        #expect(state.tasks["old"]?.formulation == before["old"]?.formulation)
        #expect(state.tasks["old"]?.consecutiveStalledFormulations == before["old"]?.consecutiveStalledFormulations)
        #expect(state.tasks["old"]?.state == .next)
        var outbox = OutboxCompactor.appending(Review.op(.bulkRelease(.init(bulkID: Review.bulk(2), kind: .restart, taskIDs: ["old"])), at: Review.now), to: [])
        outbox = OutboxCompactor.appending(Review.op(.undoBulkRelease(Review.bulk(2)), at: Review.now), to: outbox)
        #expect(outbox.isEmpty)
    }

    @Test("020-SC-007 a decision naming a session the device knows counts in that session")
    func decisionCountsInSession() throws {
        var state = Review.state([Review.nextTask("t1", started: t0)])
        try Review.apply(.review(.startSession(.init(sessionID: Review.session(1), mode: .quick, entry: .list))), to: &state)
        try Review.apply(Review.decide(.someday, "t1", formulation: Review.form(1), session: Review.session(1)), to: &state)
        #expect(state.review.sessions[Review.session(1)]?.counts[.someday] == 1)
        #expect(state.review.sessions[Review.session(1)]?.qualifyingActivity == true)
        try Review.apply(.undoDecision(Review.decision(1)), to: &state)
        #expect(state.review.sessions[Review.session(1)]?.counts[.someday] == 0)
    }
}
