import Foundation

/// Spec 020: the formulation clock in every task command, decisions and their
/// Undo, auto-park, bulk releases and the review commands
/// (contracts/ios-commands.md §2 – §4). The rule itself is `FormulationRule`;
/// this file applies it to `TaskRecord`s and `GTDState.review`.
extension GTDReducer {
    // MARK: - Clock helpers

    /// The owner inputs of the rule, as this state holds them.
    static func clockSettings(_ state: GTDState) -> OwnerClockSettings { state.review.settings.clockSettings() }

    /// The task as the rule evaluates it: a formulation that started before
    /// the activation instant counts from that instant, with the activation
    /// grace floor (formulation-clock §3), so evaluating during a replay gives
    /// what the server computes after its activation clamp.
    public static func evaluationView(_ task: TaskRecord, settings: OwnerClockSettings) -> ClockedTask {
        let view = task.clocked
        guard let activatedAt = settings.activatedAt, let clock = view.formulation, clock.startedAt <= activatedAt
        else { return view }
        return FormulationRule.activateClock(view, activatedAt: activatedAt, formulationID: clock.id)
    }

    /// The formulation id a command carries, or one derived from the task and
    /// instant for a command written before spec 020 (replay stays deterministic).
    static func formulationID(_ id: FormulationID?, task: TaskID, at date: Date) -> FormulationID {
        id ?? FormulationID(ClientID.derived("form", from: "\(task.rawValue)|\(date.timeIntervalSinceReferenceDate)"))
    }

    static func startClock(_ task: inout TaskRecord, id: FormulationID, at date: Date) {
        task.formulation = FormulationClock(id: id, startedAt: date)
        task.parked = nil
    }

    /// Closes the open formulation with the FR-005 stalled-count rule,
    /// evaluated on `evaluating` (the task before the edit) when given.
    static func closeClock(
        _ task: inout TaskRecord, evaluating original: TaskRecord? = nil, settings: OwnerClockSettings, at date: Date
    ) {
        let source = original ?? task
        guard source.formulation != nil else {
            task.formulation = nil
            return
        }
        let reached = FormulationRule.reachedAsk(evaluationView(source, settings: settings), settings: settings, now: date)
        task.consecutiveStalledFormulations = reached ? source.consecutiveStalledFormulations + 1 : 0
        task.formulation = nil
    }

    static func raiseClockFloor(_ task: inout TaskRecord, to floor: Date) {
        guard var clock = task.formulation else { return }
        clock.parkFloorAt = max(clock.parkFloorAt ?? floor, floor)
        task.formulation = clock
    }

    /// The clock side of a list change (formulation-clock §3): leaving Next
    /// closes the formulation, leaving Someday drops the park marker,
    /// entering Next starts a formulation.
    static func changeList(
        of task: inout TaskRecord, from original: TaskRecord, settings: OwnerClockSettings, at date: Date,
        newFormulationID: FormulationID?
    ) {
        guard task.state != original.state else { return }
        if original.state == .next { closeClock(&task, evaluating: original, settings: settings, at: date) }
        if original.state == .someday { task.parked = nil }
        if task.state == .next {
            startClock(&task, id: formulationID(newFormulationID, task: task.id, at: date), at: date)
        }
    }

    // MARK: - Decisions

    /// `POST /tasks/{id}/decisions`: applies the http §3 table and records the
    /// decision with an Undo snapshot (and the follow-up it created).
    static func decideTask(
        _ command: GTDCommand.DecideTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        try requireReviewExposed(state, mode: mode)
        if state.review.decisions[command.decisionID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
        guard var task = state.tasks[command.taskID] else { throw .taskNotFound }
        // FR-011: a person's decision on a task that changed in any way since
        // the card showed it (`ShownTask`: notes, dates, project, tags, a cosmetic
        // title edit, subtasks, comments) is stale. Replay leaves this
        // to the server's `expected_revision` and yield rule (http §3).
        if mode == .interactive, let shown = command.expectedTask, !shown.matches(task) { throw .formulationChanged }
        let settings = clockSettings(state)
        var yielded = false
        /// The clock before the park is not on this device (another device or
        /// the sweep parked the task): the server, which keeps it, decides.
        var clockUnknown = false
        if command.type.decidesOnFormulation, task.state == .someday, let marker = task.parked,
            marker.formulationID == command.formulationID, date < marker.at
        {
            // The yield rule (http §3): a decision made before the park on the
            // parked formulation reverses it. The server decides on push; the
            // device shows the same outcome meanwhile.
            clockUnknown = marker.clockBefore == nil
            var clock = marker.clockBefore ?? FormulationClock(id: marker.formulationID, startedAt: marker.at)
            clock.id = marker.formulationID
            task.state = .next
            task.formulation = clock
            task.consecutiveStalledFormulations = marker.stalledBefore
            task.parked = nil
            yielded = true
        }
        guard command.type.allowedStates.contains(task.state) else { throw .decisionNotAllowed }
        if command.type.decidesOnFormulation {
            guard let id = command.formulationID, task.formulation?.id == id else { throw .formulationChanged }
        }
        var working = state
        working.tasks[command.taskID] = task
        let before = task
        var substantive: Bool?
        var createdTaskID: TaskID?
        var receipt: (kind: ReceiptKind, source: ReceiptSource)?
        var reasonText: String?
        switch command.type {
        case .complete, .cancel:
            let action: TaskTransitionAction = command.type == .complete ? .complete : .cancel
            _ = try transitionTask(.init(taskID: task.id, action: action), at: date, in: &working, mode: .interactive)
        case .waiting:
            _ = try transitionTask(
                .init(taskID: task.id, action: .move, toList: .waiting, waitingFor: command.waitingFor), at: date,
                in: &working, mode: .interactive
            )
        case .someday:
            _ = try transitionTask(
                .init(taskID: task.id, action: .move, toList: .someday), at: date, in: &working, mode: .interactive
            )
            receipt = (.someday, .release)
        case .returnToNext:
            // http §3 requires `title`; an archived project is refused as for a follow-up.
            let title = try FieldRules.title(command.title ?? "")
            if let project = task.projectID, working.projects[project]?.state == .archived { throw .projectArchived }
            _ = try transitionTask(
                .init(taskID: task.id, action: .move, toList: .next, newFormulationID: command.newFormulationID), at: date,
                in: &working, mode: .interactive
            )
            working.tasks[task.id]?.title = title
        case .reformulate:
            let title = try FieldRules.title(command.title ?? "")
            let isSubstantive = FormulationKey.isSubstantive(from: task.title, to: title)
            substantive = isSubstantive
            var updated = task
            updated.title = title
            if isSubstantive {
                closeClock(&updated, evaluating: task, settings: settings, at: date)
                startClock(&updated, id: formulationID(command.newFormulationID, task: task.id, at: date), at: date)
            }
            if updated != task { updated.updatedAt = date }
            working.tasks[task.id] = updated
        case .firstStep:
            let title = try FieldRules.title(command.title ?? "")
            var updated = task
            updated.title = title
            updated.details = try FieldRules.details("Was: \(task.title)" + (task.details.map { "\n\n" + $0 } ?? ""))
            closeClock(&updated, evaluating: task, settings: settings, at: date)
            startClock(&updated, id: formulationID(command.newFormulationID, task: task.id, at: date), at: date)
            updated.updatedAt = date
            working.tasks[task.id] = updated
            substantive = true
        case .extend:
            let reason = NameNormalizer.stripped(command.reason ?? "")
            guard !reason.isEmpty else { throw .extensionReasonRequired }
            guard FieldRules.length(reason) <= GTDLimits.title else { throw .extensionReasonTooLong }
            // A yield whose clock the device lacks skips the class checks:
            // the server, which has the clock, accepts or refuses it.
            if !clockUnknown {
                do {
                    _ = try FormulationRule.extend(evaluationView(task, settings: settings), reason: reason, settings: settings, now: date)
                } catch {
                    switch error {
                    case .decisionNotAllowed: throw .decisionNotAllowed
                    case .extensionAlreadyUsed: throw .extensionAlreadyUsed
                    case .extensionNotDue: throw .extensionNotDue
                    }
                }
            }
            var updated = task
            updated.formulation?.extendedAt = date
            updated.formulation?.extensionReason = reason
            updated.updatedAt = date
            working.tasks[task.id] = updated
            reasonText = reason
        case .keepWaiting:
            receipt = (.waiting, .keep)
        case .keepSomeday:
            receipt = (.someday, .keep)
        case .followUp:
            guard let followUpID = command.followUpTaskID else { throw .decisionNotAllowed }
            if let project = task.projectID, working.projects[project]?.state != .active { throw .projectArchived }
            _ = try createTask(
                .init(
                    taskID: followUpID, title: command.title ?? "", list: .next, projectID: task.projectID,
                    newFormulationID: command.newFormulationID
                ),
                at: date, in: &working, mode: .interactive
            )
            createdTaskID = followUpID
            receipt = (.waiting, .keep)
        }
        var replaced: ReviewReceipt?
        if let receipt, let decided = working.tasks[task.id] {
            replaced = working.review.receipt(for: task.id, kind: receipt.kind)
            working.review.setReceipt(
                ReviewReceipt(
                    taskID: task.id, kind: receipt.kind, reviewedAt: date,
                    hiddenUntil: date.addingTimeInterval(receipt.kind.hiddenFor), source: receipt.source,
                    taskUpdatedAt: decided.updatedAt, decisionID: command.decisionID
                )
            )
        }
        guard let after = working.tasks[task.id] else { throw .taskNotFound }
        var sessionBefore: DecisionUndo.SessionBefore?
        if let sessionID = command.sessionID, var session = working.review.sessions[sessionID] {
            let qualifiedBefore = session.qualifyingActivity
            let activityBefore = session.lastActivityAt
            session.counts[command.type.countsAs] += 1
            session.qualifyingActivity = true
            session.lastActivityAt = max(session.lastActivityAt, date)
            working.review.sessions[sessionID] = session
            sessionBefore = DecisionUndo.SessionBefore(
                qualifyingActivity: qualifiedBefore, lastActivityAt: activityBefore, lastActivityAfter: session.lastActivityAt
            )
        }
        let undo =
            command.undoRetained
            ? DecisionUndo(
                taskBefore: before, createdTaskID: createdTaskID,
                createdTaskAfter: createdTaskID.flatMap { working.tasks[$0] }.map(TaskStamp.init),
                receiptWritten: receipt?.kind, receiptReplaced: replaced, sessionBefore: sessionBefore
            ) : nil
        working.review.decisions[command.decisionID] = ReviewDecision(
            id: command.decisionID, taskID: task.id, type: command.type, sessionID: command.sessionID, decidedAt: date,
            formulationID: command.formulationID, stallReason: command.stallReason, substantive: substantive,
            aiUse: command.aiUse, reasonText: reasonText, undo: undo, taskAfter: TaskStamp(after),
            yieldedAutoPark: yielded
        )
        state = working
        return .applied
    }

    /// `POST /review/decisions/{id}/undo`: restores the snapshot field for
    /// field (clock included), removes the decision, and deletes a follow-up
    /// it created only while that is unchanged (FR-048). An absent decision
    /// is the replay goal: it was already undone.
    static func undoDecision(
        _ id: DecisionID, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard let decision = state.review.decisions[id] else { return try satisfied(mode, else: .undoUnavailable) }
        if decision.undo == nil, decision.snapshotOnServer, mode == .replay {
            // Only the server has the snapshot (`snapshotOnServer`): keep the
            // queued Undo for the server to answer (200, 409 undo_unavailable
            // with its Ref, or 404 naming the decision: already undone).
            // Nothing changes here until that answer arrives.
            return .applied
        }
        guard let undo = decision.undo, let task = state.tasks[decision.taskID], decision.taskAfter.matches(task) else {
            throw .undoUnavailable
        }
        var working = state
        if let created = undo.createdTaskID, let createdTask = working.tasks[created] {
            guard undo.createdTaskAfter?.matches(createdTask) ?? false else { throw .undoUnavailable }
            working.tasks[created] = nil
        }
        var restored = undo.taskBefore
        restored.serverID = task.serverID
        restored.serverRevision = task.serverRevision
        restored.subtasks = task.subtasks
        restored.comments = task.comments
        restored.childrenSyncedAt = task.childrenSyncedAt
        // Field for field, `updatedAt` included: on this device an undone
        // decision leaves the task as unchanged as a cancelled one, so later
        // "changed since" checks (a release's Undo, a receipt) agree with
        // compaction's cancel. The server's revision moves; its answer wins.
        working.tasks[task.id] = restored
        if let kind = undo.receiptWritten {
            working.review.removeReceipt(for: task.id, kind: kind)
            if let previous = undo.receiptReplaced { working.review.setReceipt(previous) }
        }
        if let sessionID = decision.sessionID, var session = working.review.sessions[sessionID] {
            session.counts[decision.type.countsAs] = max(0, session.counts[decision.type.countsAs] - 1)
            // Nothing happened in the run since: it is as the decision found it.
            if let before = undo.sessionBefore, session.lastActivityAt == before.lastActivityAfter {
                session.qualifyingActivity = before.qualifyingActivity
                session.lastActivityAt = before.lastActivityAt
            }
            working.review.sessions[sessionID] = session
        }
        working.review.decisions[id] = nil
        state = working
        return .applied
    }

    // MARK: - Auto-park

    /// `POST /tasks/{id}/auto-park`: parks iff the owner is activated and the
    /// evaluation at `observedAt` is `park_due`, storing the clock before it.
    /// The replay goal holds once the task left Next or is parked for that
    /// formulation. A non-optimistic park changes nothing on the device: the
    /// server's answer does.
    static func autoParkTask(
        _ command: GTDCommand.AutoParkTask, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard var task = state.tasks[command.taskID] else { throw .taskNotFound }
        guard task.state == .next, let clock = task.formulation, clock.id == command.formulationID else {
            return try satisfied(mode, else: .formulationChanged)
        }
        let settings = clockSettings(state)
        let view = evaluationView(task, settings: settings)
        guard let parked = FormulationRule.autoPark(view, settings: settings, now: command.observedAt ?? date) else {
            return try satisfied(mode, else: .decisionNotAllowed)
        }
        guard command.optimistic else { return .applied }
        task.clocked = parked
        task.waitingFor = nil
        task.waitingSince = nil
        task.updatedAt = date
        state.tasks[command.taskID] = task
        // A new park is unseen, even of a formulation parked before (data-model E6).
        state.review.parkAcks.removeAll { $0.taskID == command.taskID }
        return .applied
    }

    // MARK: - Bulk releases

    /// `POST /review/bulk-releases`: moves each eligible task to Someday (no
    /// park marker) and keeps its previous list and clock in the record.
    static func bulkRelease(
        _ command: GTDCommand.BulkRelease, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        try requireReviewExposed(state, mode: mode)
        if state.review.bulkReleases[command.bulkID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
        guard command.taskIDs.count <= ReviewLimits.bulkReleaseItems else { throw .tooManyItems }
        let settings = clockSettings(state)
        var working = state
        var released: [BulkReleasedTask] = []
        var skipped: [BulkSkippedTask] = []
        var seen = Set<TaskID>()
        for id in command.taskIDs where seen.insert(id).inserted {
            guard var task = working.tasks[id], let previous = task.openList,
                Self.isEligible(task, for: command.kind, settings: settings, at: date)
            else {
                skipped.append(BulkSkippedTask(taskID: id, reason: "not_eligible"))
                continue
            }
            let original = task
            let snapshot = task.formulation.map {
                ReleasedClock(clock: $0, stalledBefore: task.consecutiveStalledFormulations)
            }
            task.state = .someday
            task.waitingFor = nil
            task.waitingSince = nil
            changeList(of: &task, from: original, settings: settings, at: date, newFormulationID: nil)
            task.updatedAt = date
            working.tasks[id] = task
            let replacedReceipt = working.review.receipt(for: id, kind: .someday)
            working.review.setReceipt(
                ReviewReceipt(
                    taskID: id, kind: .someday, reviewedAt: date, hiddenUntil: date.addingTimeInterval(ReceiptKind.someday.hiddenFor),
                    source: .release, taskUpdatedAt: date, bulkID: command.bulkID
                )
            )
            released.append(
                BulkReleasedTask(
                    taskID: id, previousState: previous, clockBefore: command.undoRetained ? snapshot : nil,
                    taskAfter: TaskStamp(task), receiptReplaced: replacedReceipt
                )
            )
        }
        working.review.bulkReleases[command.bulkID] = BulkReleaseRecord(
            id: command.bulkID, kind: command.kind, sessionID: command.sessionID, createdAt: date, released: released,
            skipped: skipped
        )
        state = working
        return .applied
    }

    /// Restart: in Next and restart-eligible; Inbox remainder: in Inbox.
    static func isEligible(
        _ task: TaskRecord, for kind: BulkReleaseKindCode, settings: OwnerClockSettings, at date: Date
    ) -> Bool {
        switch kind {
        case .restart:
            task.state == .next
                && FormulationRule.isRestartEligible(evaluationView(task, settings: settings), settings: settings, now: date)
        case .inboxRemainder:
            task.state == .inbox
        }
    }

    /// `POST /review/bulk-releases/{id}/undo`: each released task whose state
    /// is unchanged returns to its list with its clock exactly; the rest are
    /// skipped. An undone release is the replay goal.
    static func undoBulkRelease(
        _ id: BulkID, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard var record = state.review.bulkReleases[id] else { throw .reviewNotFound }
        if record.undoneAt != nil { return try satisfied(mode, else: .undoUnavailable) }
        var working = state
        var restored: [TaskID] = []
        var skipped: [TaskID] = []
        for item in record.released {
            guard var task = working.tasks[item.taskID], item.taskAfter.matches(task) else {
                skipped.append(item.taskID)
                continue
            }
            // A snapshot nulled by retention: the Undo is no longer available.
            // A snapshot the device never had: the server restores the clock.
            if item.previousState == .next, item.clockBefore == nil, item.clockKnown { throw .undoUnavailable }
            task.state = item.previousState.taskState
            task.parked = nil
            if let clock = item.clockBefore {
                task.formulation = clock.clock
                task.consecutiveStalledFormulations = clock.stalledBefore
            }
            task.updatedAt = date
            working.tasks[item.taskID] = task
            if working.review.receipt(for: item.taskID, kind: .someday)?.bulkID == id {
                working.review.removeReceipt(for: item.taskID, kind: .someday)
                if let previous = item.receiptReplaced { working.review.setReceipt(previous) }
            }
            restored.append(item.taskID)
        }
        record.undoneAt = date
        record.undoResult = BulkUndoResult(restored: restored, skipped: skipped)
        working.review.bulkReleases[id] = record
        state = working
        return .applied
    }

    // MARK: - Review commands

    /// The non-interactive off state (FR-042, ios/AGENTS.md): while the
    /// review is not exposed on this device (`ReviewState.isExposed`) a
    /// person's review action is refused. It covers what only the review's
    /// own surfaces offer (a decision, starting a review, a bulk release,
    /// "While you were away" Continue, the explainer). Undo of the person's
    /// own action, consent revocation, settings (also the device zone hook),
    /// a running review's progress and finish, and device auto-parks are not
    /// review entries and stay as they are. Replay is never refused: queued
    /// commands follow the server (FR-040).
    static func requireReviewExposed(_ state: GTDState, mode: ApplyMode) throws(GTDValidationError) {
        if mode == .interactive, !state.review.isExposed { throw .reviewUnavailable }
    }

    static func review(
        _ command: ReviewCommand, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        switch command {
        case .acknowledgeExplainer, .acknowledgeParks, .startSession:
            try requireReviewExposed(state, mode: mode)
        case .updateSettings, .progressSession, .finishSession, .grantNavigatorConsent, .revokeNavigatorConsent:
            break
        }
        switch command {
        case .acknowledgeExplainer(let timeZone):
            // First acknowledgement wins; a duplicate is harmless (FR-051).
            guard state.review.settings.activatedAt == nil else { return mode == .replay ? .alreadySatisfied : .applied }
            state.review.settings.activatedAt = date
            if let timeZone, TimeZone(identifier: timeZone) != nil { state.review.settings.timeZone = timeZone }
            return .applied
        case .updateSettings(let change):
            updateSettings(change, at: date, in: &state)
            return .applied
        case .acknowledgeParks(let items):
            guard items.count <= ReviewLimits.parkAcknowledgements else { throw .tooManyItems }
            let new = items.filter { !state.review.parkAcks.contains($0) }
            guard !new.isEmpty else { return mode == .replay ? .alreadySatisfied : .applied }
            state.review.parkAcks += new
            return .applied
        case .startSession(let start):
            return try startSession(start, at: date, in: &state, mode: mode)
        case .progressSession(let progress):
            return try progressSession(progress, at: date, in: &state, mode: mode)
        case .finishSession(let finish):
            guard var session = state.review.sessions[finish.sessionID] else {
                return try satisfied(mode, else: .reviewNotFound)
            }
            guard session.status == .open else { return mode == .replay ? .alreadySatisfied : .applied }
            session.status = ReviewSessionStatus.ended(by: .finish, qualifyingActivity: session.qualifyingActivity)
            session.endedAt = date
            session.lastActivityAt = max(session.lastActivityAt, date)
            session.clearStart = finish.clearStart
            state.review.sessions[finish.sessionID] = session
            return .applied
        case .grantNavigatorConsent(let provider, let version):
            let current = state.review.navigatorConsents[provider]
            if current?.allowsCloud == true, current?.consentTextVersion == version {
                return mode == .replay ? .alreadySatisfied : .applied
            }
            state.review.navigatorConsents[provider] = NavigatorConsent(
                provider: provider, grantedAt: date, revokedAt: nil, consentTextVersion: version
            )
            return .applied
        case .revokeNavigatorConsent(let provider):
            // Takes effect on this device at once, offline too (FR-024).
            guard var consent = state.review.navigatorConsents[provider], consent.allowsCloud else {
                return mode == .replay ? .alreadySatisfied : .applied
            }
            consent.revokedAt = date
            state.review.navigatorConsents[provider] = consent
            return .applied
        }
    }

    /// `PUT /review/settings`: a threshold change floors every park for 7 days
    /// (FR-039); a zone change floors due-dated Next tasks (FR-046); values
    /// equal to the stored ones are no change.
    static func updateSettings(_ change: ReviewSettingsChange, at date: Date, in state: inout GTDState) {
        var settings = state.review.settings
        if let days = change.thresholdDays, OwnerClockSettings.allowedThresholds.contains(days), days != settings.thresholdDays {
            settings.thresholdDays = days
            settings.thresholdChangedAt = date
            let floor = date.addingTimeInterval(FormulationRule.thresholdChangeFloor)
            settings.ownerParkFloorAt = max(settings.ownerParkFloorAt ?? floor, floor)
        }
        if let weekday = change.reviewWeekday, (1...7).contains(weekday) { settings.reviewWeekday = weekday }
        if let time = change.reviewTime, ReviewClock.wallTime(time) != nil { settings.reviewTime = time }
        if let zone = change.timeZone, TimeZone(identifier: zone) != nil, zone != settings.timeZone {
            settings.timeZone = zone
            let floor = date.addingTimeInterval(FormulationRule.dueDateFloor)
            for task in state.tasks.values where task.state == .next && task.dueDate != nil {
                raiseClockFloor(&state.tasks[task.id]!, to: floor)
            }
        }
        if change.onboarded, settings.onboardedAt == nil { settings.onboardedAt = date }
        state.review.settings = settings
    }

    /// `POST /review/sessions` with `replace_open: true`: an open review is
    /// ended first (partial or abandoned, FR-029).
    static func startSession(
        _ start: StartSession, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        if state.review.sessions[start.sessionID] != nil { return try satisfied(mode, else: .idAlreadyExists) }
        for session in state.review.sessions.values where session.status == .open {
            var ended = session
            ended.status = ReviewSessionStatus.ended(by: .replace, qualifyingActivity: session.qualifyingActivity)
            ended.endedAt = date
            state.review.sessions[session.id] = ended
        }
        var steps: [ReviewStep: StepStatus] = [:]
        for step in start.mode.steps { steps[step] = start.skipSteps.contains(step) ? .skipped : .pending }
        state.review.sessions[start.sessionID] = ReviewSession(
            id: start.sessionID, mode: start.mode, entry: start.entry, origin: start.origin, startedAt: date,
            currentStep: start.mode.steps.first { !start.skipSteps.contains($0) }, steps: steps
        )
        return .applied
    }

    /// `PATCH /review/sessions/{id}`: merged, never a conflict, each
    /// `progressID` once (http §6 "Progress is replay-safe").
    static func progressSession(
        _ progress: SessionProgress, at date: Date, in state: inout GTDState, mode: ApplyMode
    ) throws(GTDValidationError) -> ApplyOutcome {
        guard var session = state.review.sessions[progress.sessionID] else {
            return try satisfied(mode, else: .reviewNotFound)
        }
        if session.appliedProgress.contains(progress.progressID) {
            return mode == .replay ? .alreadySatisfied : .applied
        }
        session.appliedProgress.insert(progress.progressID)
        defer { state.review.sessions[progress.sessionID] = session }
        // Progress on a finished session is accepted and ignored.
        guard session.status == .open else { return .applied }
        if let step = progress.currentStep { session.currentStep = step }
        if let step = progress.step, let status = progress.stepStatus {
            session.steps[step] = (session.steps[step] ?? .pending).merged(with: status)
            if status == .finished, ReviewRules.hasNothingToDecide(step, in: state, now: date) {
                session.qualifyingActivity = true
            }
        }
        if let step = progress.activeStep, let seconds = progress.activeSeconds, seconds > 0 {
            session.activeSecondsByStep[step, default: 0] += seconds
        }
        if let task = progress.setAsideTaskID, !session.setAsideTaskIDs.contains(task) {
            session.setAsideTaskIDs.append(task)
            session.setAsideCount = session.setAsideTaskIDs.count
        }
        if let delta = progress.inboxProcessedDelta {
            session.counts[.inboxProcessed] = max(0, session.counts[.inboxProcessed] + delta)
            if delta > 0 { session.qualifyingActivity = true }
        }
        if progress.snapshotDecisionQueue, session.decisionQueue == nil {
            session.decisionQueue = GTDQueries.decisionQueue(in: state, now: date).map(\.id)
        }
        session.lastActivityAt = max(session.lastActivityAt, date)
        return .applied
    }
}

/// The deterministic post-replay activation step (contracts/ios-commands.md
/// §3, FR-016, FR-051): once an activation instant is known, every Next
/// formulation that started before it is clamped to it with the 14-day grace
/// floor, whatever order the operations were folded in. Without an account
/// a Next task without a clock (written before spec 020) starts one at the
/// activation instant; signed in, the server repairs such a task, and it
/// stays unclassified until it does (it can never park early).
public enum ReviewActivation {
    public static func apply(to state: inout GTDState, activatedAt: Date?, startsMissingClocks: Bool) {
        guard let activatedAt else { return }
        for task in state.tasks.values where task.state == .next {
            if let clock = task.formulation {
                guard clock.startedAt <= activatedAt else { continue }
                state.tasks[task.id]?.clocked = FormulationRule.activateClock(
                    task.clocked, activatedAt: activatedAt, formulationID: clock.id
                )
            } else if startsMissingClocks {
                let id = FormulationID(ClientID.derived("form", from: "activation|\(task.id.rawValue)"))
                state.tasks[task.id]?.clocked = FormulationRule.activateClock(
                    task.clocked, activatedAt: activatedAt, formulationID: id
                )
            }
        }
    }
}
