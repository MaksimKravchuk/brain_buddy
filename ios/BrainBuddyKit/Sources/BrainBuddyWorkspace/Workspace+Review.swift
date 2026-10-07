import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// The weekly review on the workspace (spec 020, contracts/ios-commands.md
/// §2, §5 – §8). Every rule is decided in Core (`GTDReducer`, `GTDQueries`,
/// the planners); this extension mints ids, picks the instant and zone the
/// rule is evaluated with, and keeps the device-local state
/// (`StoreDocument.local`), which is written with the next write and never
/// synced.
extension Workspace {
    // MARK: - Exposure and clocks

    /// Device-local review state, including edits not written yet.
    public var localReview: LocalReviewState { local }

    var local: LocalReviewState {
        guard !pendingEdits.isEmpty else { return document.local }
        var pending = document
        for edit in pendingEdits { edit(&pending) }
        return pending.local
    }

    /// Whether the weekly review is shown (§8): signed in, the `weekly_review`
    /// flag answered on `GET /review/state`; account-less, the release switch.
    public var reviewExposed: Bool {
        account != nil ? state.review.server?.exposed == true : accountlessReviewEnabled
    }

    /// The instant the rule is evaluated at: signed in, the device clock plus
    /// the last observed `server_now − device time` (http §5).
    public var reviewNow: Date {
        let instant = now()
        guard account != nil, let offset = local.serverClockOffset else { return instant }
        return instant.addingTimeInterval(offset)
    }

    /// The zone classification uses ("Which zone, for what", ios-commands §6):
    /// signed in, the owner's stored zone (nil = stored); account-less, the device's.
    var classificationZone: String? { account == nil ? deviceTimeZone().identifier : nil }

    // MARK: - Reading

    public func formulationClass(of id: TaskID) -> FormulationClass? {
        guard let task = state.tasks[id] else { return nil }
        return GTDQueries.formulationClass(
            of: task, now: reviewNow, settings: state.review.settings, timeZone: classificationZone
        )
    }

    public func derivedInstants(of id: TaskID) -> DerivedInstants? {
        guard let task = state.tasks[id] else { return nil }
        return GTDQueries.derivedInstants(of: task, settings: state.review.settings, timeZone: classificationZone)
    }

    public func decisionQueue() -> [TaskRecord] {
        GTDQueries.decisionQueue(in: state, now: reviewNow, timeZone: classificationZone)
    }

    public func askCount() -> Int { GTDQueries.askCount(in: state, now: reviewNow, timeZone: classificationZone) }
    public func unseenParks() -> [TaskRecord] { GTDQueries.unseenParks(in: state) }

    public func restartCandidates() -> [TaskRecord] {
        GTDQueries.restartCandidates(in: state, now: reviewNow, timeZone: classificationZone)
    }

    public func restartMode() -> Bool {
        state.review.server?.restartMode == true || GTDQueries.restartMode(in: state, now: reviewNow)
    }

    public func wins() -> [TaskRecord] { GTDQueries.wins(in: state, now: now()) }
    public func capacityMirror() -> CapacityMirror { GTDQueries.capacityMirror(in: state, now: now()) }
    public func waitingDue() -> [TaskRecord] { GTDQueries.waitingDue(in: state, now: now()) }
    public func somedayDue() -> SomedayQueue { GTDQueries.somedayDue(in: state, now: now()) }
    public func projectsNeedingNextAction() -> [ProjectSummary] { GTDQueries.projectsNeedingNextAction(in: state) }
    public func datesAhead() -> [DueDay] { GTDQueries.datesAhead(in: state, today: today) }
    public func lastCountedReview() -> Date? { GTDQueries.lastCountedReview(in: state) }
    public var explainerNeeded: Bool { GTDQueries.explainerNeeded(in: state, local: local) }

    /// FR-005: whether the card shows the third-stall offer for `id`.
    public func isThirdStall(_ id: TaskID) -> Bool {
        guard let task = state.tasks[id] else { return false }
        return GTDQueries.isThirdStall(task, now: reviewNow, settings: state.review.settings, timeZone: classificationZone)
    }

    /// FR-009: what "Keep 7 more days" would give `id` now (M-04), in the
    /// classification zone; nil when it is not allowed.
    public func extensionInstants(of id: TaskID) -> DerivedInstants? {
        guard let task = state.tasks[id] else { return nil }
        return GTDQueries.extensionInstants(
            of: task, now: reviewNow, settings: state.review.settings, timeZone: classificationZone
        )
    }

    /// FR-015: why `id` cannot return to Next from "While you were away".
    public func parkReturnProblem(of id: TaskID, shown: ParkAck? = nil) -> ParkReturnProblem? {
        GTDQueries.parkReturnProblem(of: id, shown: shown, in: state)
    }

    /// Tasks listed once on "While you were away" because linking dropped
    /// their unsent "Keep 7 more days" (ios-commands §7).
    public var linkedExtensionNotices: [TaskID] { local.linkedExtensionNotices }

    /// The screens a review entry opens with (design.md entry order).
    public func reviewEntryScreens(for entry: ReviewEntry) -> [ReviewScreen] {
        ReviewEntryPlanner.start(
            for: entry,
            state: ReviewEntryState(
                explainerNeeded: explainerNeeded, onboarded: state.review.settings.onboardedAt != nil,
                hasUnseenParks: !unseenParks().isEmpty || !local.linkedExtensionNotices.isEmpty,
                restartMode: restartMode(), openSession: state.review.openSession
            )
        )
    }

    /// FR-015: "While you were away" at app open, once per local day.
    public func whileAwayShouldShowAtAppOpen() -> Bool {
        WhileAwayPresentation.shouldShowAtAppOpen(
            lastShownDay: local.wywaLastShownDay, today: today,
            hasUnseen: !unseenParks().isEmpty || !local.linkedExtensionNotices.isEmpty
        )
    }

    /// The next weekly notification, in the device's current zone (FR-036).
    public func nextReviewReminder() -> Date? {
        ReviewReminderPlanner.nextFireDate(
            settings: state.review.settings, lastCountedReview: lastCountedReview(), now: now(),
            timeZone: deviceTimeZone()
        )
    }

    // MARK: - Decisions

    /// Records a decision on `taskID` (http §3) and returns its id. Next-only
    /// decisions are made on `formulationID`, the wording the card or form
    /// was opened on, when given (FR-011): if the task was reformulated since
    /// (a sync, another window), the reducer refuses it with
    /// `.formulationChanged` and nothing is applied, so text written for the
    /// old wording never lands on the new one. Without it, the task's current
    /// formulation. `expectedTask` is the task as the card showed it: any
    /// change since (notes, dates, project, tags, subtasks, a cosmetic title
    /// edit) is refused the same way. While the review is not exposed every
    /// decision is refused with `.reviewUnavailable`. Saving removes the
    /// task's decision-form drafts (FR-052); a refusal keeps them.
    @discardableResult
    public func decide(
        _ type: DecisionType, on taskID: TaskID, title: String? = nil, waitingFor: String? = nil, reason: String? = nil,
        stallReason: StallReason? = nil, aiUse: AIUse = .none, navigatorRequestID: String? = nil,
        sessionID: ReviewSessionID? = nil, formulationID opened: FormulationID? = nil, expectedTask: TaskStamp? = nil
    ) throws(GTDValidationError) -> DecisionID {
        // Nothing of the review acts while it is not exposed (the flag or
        // release switch turned off with a card or form open); drafts stay.
        guard reviewExposed else { throw .reviewUnavailable }
        guard let task = state.tasks[taskID] else { throw .taskNotFound }
        let decisionID = DecisionID.make(makeID())
        let startsFormulation: Set<DecisionType> = [.reformulate, .firstStep, .returnToNext, .followUp]
        let current = task.formulation?.id ?? task.parked?.formulationID
        let command = GTDCommand.DecideTask(
            decisionID: decisionID, taskID: taskID, type: type,
            formulationID: type.decidesOnFormulation ? (opened ?? current) : nil,
            newFormulationID: startsFormulation.contains(type) ? FormulationID.make(makeID()) : nil,
            stallReason: stallReason, title: title, waitingFor: waitingFor, reason: reason, sessionID: sessionID,
            aiUse: aiUse, navigatorRequestID: navigatorRequestID,
            followUpTaskID: type == .followUp ? TaskID(ClientID.make("task", makeID())) : nil, expectedTask: expectedTask
        )
        try perform(.decideTask(command))
        edit { document in
            document.local.formDrafts = document.local.formDrafts.filter { $0.key.taskID != taskID }
        }
        return decisionID
    }

    /// Undoes a decision while the task is unchanged since (FR-048).
    public func undoDecision(_ id: DecisionID) throws(GTDValidationError) {
        try perform(.undoDecision(id))
    }

    // MARK: - Explainer, onboarding, settings, zone

    /// Dismissing the auto-park explainer (M-26) activates the clocks
    /// (FR-051): account-less at this instant, signed in at the server's
    /// first acknowledgement. The zone sent is recorded as observed.
    public func acknowledgeExplainer() throws(GTDValidationError) {
        let zone = deviceTimeZone().identifier
        let issuedAt = Self.storedPrecision(now())
        let accountless = account == nil
        try perform(.review(.acknowledgeExplainer(timeZone: zone)))
        edit { document in
            if accountless, document.local.activatedAt == nil { document.local.activatedAt = issuedAt }
            document.local.explainerSeenLocally = true
            document.local.lastObservedTimeZone = zone
        }
    }

    /// Onboarding (M-12): the chosen rhythm and threshold, with the device's zone.
    public func completeReviewOnboarding(
        thresholdDays: Int? = nil, reviewWeekday: Int? = nil, reviewTime: String? = nil
    ) throws(GTDValidationError) {
        let zone = deviceTimeZone().identifier
        try perform(
            .review(
                .updateSettings(
                    ReviewSettingsChange(
                        thresholdDays: thresholdDays, reviewWeekday: reviewWeekday, reviewTime: reviewTime, timeZone: zone,
                        onboarded: true
                    )
                )
            )
        )
        edit { $0.local.lastObservedTimeZone = zone }
    }

    public func updateReviewSettings(_ change: ReviewSettingsChange) throws(GTDValidationError) {
        guard !change.isEmpty else { return }
        try perform(.review(.updateSettings(change)))
        if let zone = change.timeZone { edit { $0.local.lastObservedTimeZone = zone } }
    }

    /// Sends the device's zone only when the device's own zone changed since
    /// it last observed one (owner decision 2026-10-06, FR-035, FR-046); a
    /// device that never recorded one records it without sending. Returns
    /// whether a change was queued.
    @discardableResult
    public func sendDeviceTimeZoneIfChanged() -> Bool {
        let current = deviceTimeZone()
        let lastObserved = local.lastObservedTimeZone
        guard let lastObserved else {
            edit { $0.local.lastObservedTimeZone = current.identifier }
            return false
        }
        guard let changed = DeviceZoneTracker.change(lastObserved: lastObserved, current: current) else { return false }
        do {
            try perform(.review(.updateSettings(ReviewSettingsChange(timeZone: changed.identifier))))
        } catch {
            return false
        }
        edit { $0.local.lastObservedTimeZone = changed.identifier }
        return true
    }

    // MARK: - While you were away

    /// Marks "While you were away" as shown today (at app open). Nothing is
    /// recorded while the review is not exposed: a sheet the flag took away
    /// was not shown.
    public func markWhileAwayShown() {
        guard reviewExposed else { return }
        let day = today
        edit { $0.local.wywaLastShownDay = day }
    }

    /// The unseen parks as M-09 lists them; pass the ones a sheet showed to
    /// `dismissWhileAway(shown:)`.
    public func unseenParkAcks() -> [ParkAck] { GTDQueries.unseenParkAcks(in: state) }

    /// Continue on "While you were away" (M-09): the parks it `shown` are
    /// seen (a park that arrived while it was open is not), linking notices
    /// go, and the next batch of due parks may apply.
    public func dismissWhileAway(shown: [ParkAck]) throws(GTDValidationError) {
        let acks = GTDQueries.whileAwayAcknowledgements(shown: shown, in: state)
        // At most 200 items per request (http §5).
        let chunks = stride(from: 0, to: acks.count, by: ReviewLimits.parkAcknowledgements).map {
            Array(acks[$0..<min($0 + ReviewLimits.parkAcknowledgements, acks.count)])
        }
        if !chunks.isEmpty { try perform(chunks.map { .review(.acknowledgeParks($0)) }) }
        let day = today
        edit { document in
            document.local.linkedExtensionNotices = []
            document.local.parkBatchWaiting = false
            document.local.wywaLastShownDay = day
        }
    }

    /// Close or swipe-down on "While you were away" (M-09): the parks stay
    /// unseen and come back another day (FR-015); the account-linking
    /// notices are information, shown once, so they go (T093). A close
    /// caused by the review no longer being exposed (the flag turned off
    /// while the sheet was up) records nothing.
    public func closeWhileAway() {
        guard reviewExposed else { return }
        let day = today
        edit { document in
            document.local.linkedExtensionNotices = []
            document.local.wywaLastShownDay = day
        }
    }

    // MARK: - Review runs

    @discardableResult
    public func startReview(
        mode: ReviewMode, entry: ReviewEntry, skipping skipSteps: [ReviewStep] = []
    ) throws(GTDValidationError) -> ReviewSessionID {
        let id = ReviewSessionID.make(makeID())
        try perform(.review(.startSession(StartSession(sessionID: id, mode: mode, entry: entry, skipSteps: skipSteps))))
        return id
    }

    /// One progress change, with a fresh `progressID` (http §6).
    public func recordReviewProgress(
        _ sessionID: ReviewSessionID, currentStep: ReviewStep? = nil, step: ReviewStep? = nil,
        stepStatus: StepStatus? = nil, activeStep: ReviewStep? = nil, activeSeconds: Int? = nil,
        setAsideTaskID: TaskID? = nil, inboxProcessedDelta: Int? = nil, snapshotDecisionQueue: Bool = false
    ) throws(GTDValidationError) {
        let progress = SessionProgress(
            sessionID: sessionID, progressID: ProgressID.make(makeID()), currentStep: currentStep, step: step,
            stepStatus: stepStatus, activeStep: activeStep, activeSeconds: activeSeconds, setAsideTaskID: setAsideTaskID,
            inboxProcessedDelta: inboxProcessedDelta, snapshotDecisionQueue: snapshotDecisionQueue
        )
        try perform(.review(.progressSession(progress)))
    }

    /// Done on the summary.
    public func finishReview(_ sessionID: ReviewSessionID, clearStart: ClearStart? = nil) throws(GTDValidationError) {
        try perform(.review(.finishSession(FinishSession(sessionID: sessionID, clearStart: clearStart))))
    }

    // MARK: - Bulk releases

    /// Releases `taskIDs` in requests of at most 500 tasks (http §6), all or
    /// nothing; returns one id per request, which `undoBulkRelease` takes back.
    @discardableResult
    public func bulkRelease(
        _ kind: BulkReleaseKindCode, taskIDs: [TaskID], sessionID: ReviewSessionID? = nil
    ) throws(GTDValidationError) -> [BulkID] {
        let chunks = stride(from: 0, to: taskIDs.count, by: ReviewLimits.bulkReleaseItems).map {
            Array(taskIDs[$0..<min($0 + ReviewLimits.bulkReleaseItems, taskIDs.count)])
        }
        let commands = chunks.map { chunk in
            GTDCommand.BulkRelease(bulkID: BulkID.make(makeID()), kind: kind, sessionID: sessionID, taskIDs: chunk)
        }
        try perform(commands.map { .bulkRelease($0) })
        return commands.map(\.bulkID)
    }

    public func undoBulkRelease(_ ids: [BulkID]) throws(GTDValidationError) {
        try perform(ids.map { .undoBulkRelease($0) })
    }

    // MARK: - Navigator consent (FR-024)

    public func grantNavigatorConsent(provider: String, consentTextVersion: Int) throws(GTDValidationError) {
        try perform(.review(.grantNavigatorConsent(provider: provider, consentTextVersion: consentTextVersion)))
    }

    /// Blocks cloud use on this device at once, offline too.
    public func revokeNavigatorConsent(provider: String) throws(GTDValidationError) {
        try perform(.review(.revokeNavigatorConsent(provider: provider)))
    }

    public func navigatorAllowsCloud(provider: String) -> Bool {
        state.review.navigatorConsents[provider]?.allowsCloud == true
    }

    // MARK: - Form drafts (FR-052)

    /// Keeps unsaved form text on this device only: never sent, never in an
    /// outbox operation, never logged.
    public func saveDraft(_ text: String, for key: DraftKey) {
        let savedAt = now()
        edit { document in
            if text.isEmpty {
                document.local.formDrafts[key] = nil
            } else {
                document.local.formDrafts[key] = FormDraft(text: text, savedAt: savedAt)
            }
        }
    }

    /// The draft for `key`, unless it expired or its formulation changed.
    public func draft(for key: DraftKey) -> String? {
        guard let draft = local.formDrafts[key], Self.isLive(key, draft, in: state, now: now()) else { return nil }
        return draft.text
    }

    public func discardDraft(for key: DraftKey) {
        edit { $0.local.formDrafts[key] = nil }
    }

    nonisolated static func isLive(_ key: DraftKey, _ draft: FormDraft, in state: GTDState, now: Date) -> Bool {
        guard now.timeIntervalSince(draft.savedAt) < localRetention else { return false }
        guard let task = key.taskID else { return true }
        guard let record = state.tasks[task] else { return false }
        guard let formulation = key.formulationID else { return true }
        return record.formulation?.id == formulation || record.parked?.formulationID == formulation
    }

    // MARK: - Upkeep (load, foreground, after pull, background refresh)

    /// Content-bearing local copies live 7 days (R15).
    nonisolated static let localRetention: TimeInterval = 7 * 86_400
    /// At most this many parks per call (the device safety valve, ios-commands §5).
    public nonisolated static let parkBatchLimit = 10
    /// A park follows at least this long a "Moves to Someday tomorrow" (SC-006).
    public nonisolated static let parkWarningLead: TimeInterval = 86_400

    /// Local retention and the idle close always run (data-model local
    /// retention, FR-043), whether or not the review is shown; the formulation
    /// ids, the zone and auto-park only while it is exposed.
    public func runReviewUpkeep() {
        guard isLoaded, loadError == nil else { return }
        runLocalReviewMaintenance()
        guard reviewExposed else { return }
        stampUnsentFormulationIDs()
        sendDeviceTimeZoneIfChanged()
        applyDueAutoParks()
    }

    /// Once the review is exposed, every unsent operation that starts a
    /// formulation names the id the device derived for it, so the server
    /// starts the same formulation and a queued decision on it is not
    /// refused as stale (operations queued before exposure, a store migrated
    /// from v1). Sent operations keep the body their key is bound to.
    func stampUnsentFormulationIDs() {
        let pending = (document.outbox + unpersisted).filter { !$0.hasBeenSent }
        guard pending.contains(where: { ReviewAccountLinking.stampingDerivedFormulationID($0) != $0 }) else { return }
        edit { document in
            document.outbox = document.outbox.map { operation in
                operation.hasBeenSent ? operation : ReviewAccountLinking.stampingDerivedFormulationID(operation)
            }
        }
    }

    /// Applies the parks that are due (ios-commands §5): never before
    /// activation, never without 24 hours of "Moves to Someday tomorrow",
    /// never twice for one formulation, at most 10 per call. Online and
    /// signed in, the park is sent and shown only once the server applied it.
    /// Returns how many parks were issued.
    @discardableResult
    public func applyDueAutoParks() -> Int {
        guard isLoaded, reviewExposed else { return 0 }
        let instant = Self.storedPrecision(reviewNow)
        let zone = classificationZone
        let local = self.local
        let settings = state.review.settings
        // Record when each formulation was first seen one day (or less) from its park.
        var warnings: [TaskID: ParkWarning] = [:]
        for task in state.tasks.values where task.state == .next {
            guard let clock = task.formulation else { continue }
            let kind = GTDQueries.formulationClass(of: task, now: instant, settings: settings, timeZone: zone)
            guard kind == .movesTomorrow || kind == .parkDue else { continue }
            if let known = local.parkWarnings[task.id], known.formulationID == clock.id {
                warnings[task.id] = known
            } else {
                warnings[task.id] = ParkWarning(formulationID: clock.id, since: instant)
            }
        }
        let due = GTDQueries.dueAutoParks(in: state, now: instant, timeZone: zone).filter { task in
            guard let clock = task.formulation, local.issuedAutoParks[task.id] != clock.id,
                let warning = warnings[task.id], warning.formulationID == clock.id
            else { return false }
            return instant.timeIntervalSince(warning.since) >= Self.parkWarningLead
        }
        var issued: [TaskID: FormulationID] = [:]
        if !local.parkBatchWaiting {
            let optimistic = account == nil || !networkIsAvailable
            for task in due.prefix(Self.parkBatchLimit) {
                guard let clock = task.formulation else { continue }
                let park = GTDCommand.AutoParkTask(
                    taskID: task.id, formulationID: clock.id, observedAt: instant, optimistic: optimistic
                )
                do {
                    try perform(.autoParkTask(park))
                    issued[task.id] = clock.id
                } catch {
                    continue
                }
            }
        }
        let waiting = local.parkBatchWaiting || due.count > issued.count
        let keptWarnings = warnings.filter { issued[$0.key] == nil }
        guard !issued.isEmpty || keptWarnings != local.parkWarnings || waiting != local.parkBatchWaiting else { return 0 }
        let issuedParks = issued
        edit { document in
            document.local.parkWarnings = keptWarnings
            document.local.issuedAutoParks.merge(issuedParks) { _, new in new }
            document.local.parkBatchWaiting = waiting
        }
        return issued.count
    }

    /// Keeps the device copy within the server's retention bounds, signed in
    /// or not (ios-commands §5): undo and bulk-release snapshots are nulled 7
    /// days after they were taken (unsent operations stop retaining theirs
    /// unless a queued Undo needs them), open runs idle for 7 days are
    /// closed, and expired or orphaned drafts go.
    public func runLocalReviewMaintenance() {
        let instant = now()
        let signedIn = account != nil
        let idle = ReviewSessionUpkeep.idleSessions(in: state, now: instant)
        let current = state
        let local = self.local
        let staleDrafts = local.formDrafts.filter { !Self.isLive($0.key, $0.value, in: current, now: instant) }.map(\.key)
        // Recorded idle closes stay while the run underneath is still open,
        // read from `state` (which shows them closed): no extra replay.
        let keptClosed = ReviewSessionUpkeep.recordedIdleCloses(local.idleClosedSessions, in: current)
        let closed = keptClosed + idle.filter { !keptClosed.contains($0) }
        // What a queued Undo names keeps what it needs: a decision record in
        // the base (answered by the server, not replayed as already done) and
        // the snapshot of an unsent decision or release (`ReviewRetention`).
        let pending = document.outbox + unpersisted
        let undos = ReviewRetention.QueuedUndos(pending)
        let expiresSnapshots =
            ReviewRetention.isDue(document.base.review, now: instant, signedIn: signedIn, keeping: undos.decisions)
            || pending.contains { ReviewRetention.expiringSnapshot(of: $0, now: instant, undos: undos) != nil }
        guard expiresSnapshots || !staleDrafts.isEmpty || closed != local.idleClosedSessions else { return }
        edit { document in
            // The stored outbox plus the operations not yet written with it.
            let undos = ReviewRetention.QueuedUndos(document.outbox + pending)
            ReviewRetention.apply(to: &document.base.review, now: instant, signedIn: signedIn, keeping: undos.decisions)
            document.outbox = document.outbox.map { operation in
                ReviewRetention.expiringSnapshot(of: operation, now: instant, undos: undos) ?? operation
            }
            for key in staleDrafts { document.local.formDrafts[key] = nil }
            document.local.idleClosedSessions = closed
        }
    }

    // MARK: - Account linking (ios-commands §7)

    /// Before an account-less store is uploaded: unsent local parks become
    /// plain moves to Someday, unsent extensions are dropped and listed, and
    /// formulations the device derived are named. Runs when the review was
    /// used on this device. A store that cannot be written stops the sign-in
    /// (`WorkspaceError.storage`): uploading the unconverted outbox would send
    /// parks the server answers `applied: false`.
    func convertLocalAutoParksForLinking() async throws {
        guard accountlessReviewEnabled || local.activatedAt != nil else { return }
        let pending = document.outbox + unpersisted
        let affected = pending.contains { operation in
            guard !operation.hasBeenSent else { return false }
            switch operation.command {
            case .autoParkTask: return true
            case .decideTask(let decide) where decide.type == .extend: return true
            default: return ReviewAccountLinking.stampingDerivedFormulationID(operation) != operation
            }
        }
        guard affected else { return }
        await flush()
        if let storageError { throw WorkspaceError.storage(storageError) }
        do {
            _ = try await store.update { document in
                document = ReviewAccountLinking.convertLocalAutoParks(document)
            }
        } catch {
            throw WorkspaceError.storage(Self.storageMessage(for: error))
        }
        await refreshFromStore()
    }
}
