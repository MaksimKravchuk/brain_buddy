import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// A canonical Review read. Collection methods expose one page; the UI asks
/// for another explicitly and renders readiness separately from emptiness.
public enum WorkspaceReviewRead: Hashable, Sendable {
    case state
    case summary(ReviewSessionID?)
    case formulation(TaskID)
    case queue(ReviewStep, ReviewSessionID?)
    case restart
    case projects
    case parkReturn(TaskID, ParkAck?)
    case releases(BulkReleaseKindCode, ReviewSessionID?)
}

/// The weekly review on the workspace (spec 020, contracts/ios-commands.md
/// §2, §5 – §8). Legacy workspaces retain their established commands and
/// local document state. Selected workspaces render bounded canonical pages
/// and await durable runtime saves; this extension owns presentation only.
extension Workspace {
    // MARK: - Exposure and clocks

    /// Device-local review state, including edits not written yet.
    public var localReview: LocalReviewState { local }

    var local: LocalReviewState {
        if isRustSelected { return rustLocalReview }
        guard !pendingEdits.isEmpty else { return document.local }
        var pending = document
        for edit in pendingEdits { edit(&pending) }
        return pending.local
    }

    /// Whether the weekly review is shown (§8): signed in, the `weekly_review`
    /// flag answered on `GET /review/state`; account-less, the release switch.
    /// Core's `ReviewState.isExposed` with the same input the reducer gets.
    public var reviewExposed: Bool {
        if isRustSelected { return isRustBound && rustReviewState?.server.exposed == true }
        var review = state.review
        review.accountlessReleaseSwitch = accountlessReleaseSwitch
        return review.isExposed
    }

    /// The task as a decision card or form shows it now (FR-011), with this
    /// device's child edits on it; pass it to `decide(expectedTask:)`.
    public func shownTask(of task: TaskRecord) -> ShownTask {
        if isRustSelected { return rustShownTask(of: task) }
        return ShownTask(task, localChildEdits: localChildEdits[task.id] ?? 0)
    }

    /// Core's exposure input (`ReviewState.accountlessReleaseSwitch`): the
    /// account-less release switch, nil when signed in (the pulled
    /// `review.server.exposed`, persisted in the base, decides).
    var accountlessReleaseSwitch: Bool? { account == nil ? accountlessReviewEnabled : nil }

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
        if isRustSelected { return rustFormulation(id)?.classification }
        guard let task = state.tasks[id] else { return nil }
        return GTDQueries.formulationClass(
            of: task, now: reviewNow, settings: state.review.settings, timeZone: classificationZone
        )
    }

    public func derivedInstants(of id: TaskID) -> DerivedInstants? {
        if isRustSelected { return rustFormulation(id)?.derived }
        guard let task = state.tasks[id] else { return nil }
        return GTDQueries.derivedInstants(of: task, settings: state.review.settings, timeZone: classificationZone)
    }

    public func decisionQueue() -> [TaskRecord] {
        if isRustSelected { return rustQueue(.decisions)?.tasks ?? [] }
        return GTDQueries.decisionQueue(in: state, now: reviewNow, timeZone: classificationZone)
    }

    public func askCount() -> Int {
        if isRustSelected { return rustReviewState?.askCount ?? 0 }
        return GTDQueries.askCount(in: state, now: reviewNow, timeZone: classificationZone)
    }
    public func unseenParks() -> [TaskRecord] {
        if isRustSelected { return (rustReviewState?.unseenParks ?? []).compactMap { state.tasks[$0.taskID] } }
        return GTDQueries.unseenParks(in: state)
    }

    public func restartCandidates() -> [TaskRecord] {
        if isRustSelected { return rustRead(.restart) { try $0.workspaceTasks(from: $1, keeping: state, at: now()) } ?? [] }
        return GTDQueries.restartCandidates(in: state, now: reviewNow, timeZone: classificationZone)
    }

    public func restartMode() -> Bool {
        if isRustSelected { return rustReviewState?.server.restartMode == true }
        return state.review.server?.restartMode == true || GTDQueries.restartMode(in: state, now: reviewNow)
    }

    public func wins() -> [TaskRecord] {
        if isRustSelected { return rustQueue(.wins)?.tasks ?? [] }
        return GTDQueries.wins(in: state, now: now())
    }
    public func capacityMirror() -> CapacityMirror {
        if isRustSelected {
            return rustQueue(.restOfNext)?.capacity ?? CapacityMirror(nextCount: 0, weeksOfHistory: 0, weeklyAverage4w: nil, impliedWeeks: nil)
        }
        return GTDQueries.capacityMirror(in: state, now: now())
    }
    public func waitingDue() -> [TaskRecord] {
        if isRustSelected { return rustQueue(.waiting)?.tasks ?? [] }
        return GTDQueries.waitingDue(in: state, now: now())
    }
    public func somedayDue() -> SomedayQueue {
        if isRustSelected {
            let queue = rustQueue(.someday)
            return SomedayQueue(eligibleTotal: queue?.somedayTotal ?? 0, shown: queue?.tasks ?? [])
        }
        return GTDQueries.somedayDue(in: state, now: now())
    }
    public func projectsNeedingNextAction() -> [ProjectSummary] {
        if isRustSelected { return rustRead(.projects) { try $0.workspaceProjects(from: $1, keeping: state, at: now()) } ?? [] }
        return GTDQueries.projectsNeedingNextAction(in: state)
    }
    public func datesAhead() -> [DueDay] {
        if isRustSelected { return rustQueue(.dates)?.dueDays ?? [] }
        return GTDQueries.datesAhead(in: state, today: today)
    }
    public func lastCountedReview() -> Date? {
        if isRustSelected { return rustReviewState?.server.lastCountedReviewAt }
        return GTDQueries.lastCountedReview(in: state)
    }
    public func daysSinceLastReview() -> Int? {
        if isRustSelected { return rustSummary()?.daysSinceLastReview }
        return GTDQueries.daysSinceLastReview(in: state, today: today)
    }
    public func reviewEntryNotice() -> ReviewEntryNotice? {
        if isRustSelected { return rustSummary()?.entryNotice }
        return GTDQueries.entryNotice(in: state)
    }
    public func openRestartReleases() -> [BulkReleaseRecord] {
        if isRustSelected { return rustReleases(.restart) }
        return GTDQueries.openRestartReleases(in: state)
    }

    public func openInboxReleases(in session: ReviewSession) -> [BulkReleaseRecord] {
        if isRustSelected { return rustReleases(.inboxRemainder, session: session.id) }
        return GTDQueries.openInboxReleases(in: state, session: session)
    }

    public func decisionStep(in session: ReviewSession) -> DecisionStepOutcome {
        if isRustSelected { return rustSummary(session: session.id)?.decisionStep ?? .nothingAsks }
        return GTDQueries.decisionStep(in: state, session: session, now: reviewNow, timeZone: classificationZone)
    }
    public var explainerNeeded: Bool {
        if isRustSelected { return rustSummary()?.explainerNeeded ?? false }
        return GTDQueries.explainerNeeded(in: state, local: local)
    }

    /// FR-005: whether the card shows the third-stall offer for `id`.
    public func isThirdStall(_ id: TaskID) -> Bool {
        if isRustSelected { return rustFormulation(id)?.thirdStall ?? false }
        guard let task = state.tasks[id] else { return false }
        return GTDQueries.isThirdStall(task, now: reviewNow, settings: state.review.settings, timeZone: classificationZone)
    }

    /// FR-009: what "Keep 7 more days" would give `id` now (M-04), in the
    /// classification zone; nil when it is not allowed.
    public func extensionInstants(of id: TaskID) -> DerivedInstants? {
        if isRustSelected { return rustFormulation(id)?.extensionInstants }
        guard let task = state.tasks[id] else { return nil }
        return GTDQueries.extensionInstants(
            of: task, now: reviewNow, settings: state.review.settings, timeZone: classificationZone
        )
    }

    /// FR-015: why `id` cannot return to Next from "While you were away".
    public func parkReturnProblem(of id: TaskID, shown: ParkAck? = nil) -> ParkReturnProblem? {
        if isRustSelected { return rustRead(.parkReturn(id, shown)) { try $0.workspaceParkReturnProblem(from: $1) } ?? nil }
        return GTDQueries.parkReturnProblem(of: id, shown: shown, in: state)
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
                hasUnseenParks: hasUnseenReviewParks || !local.linkedExtensionNotices.isEmpty,
                restartMode: restartMode(), openSession: state.review.openSession
            )
        )
    }

    /// FR-015: "While you were away" at app open, once per local day.
    public func whileAwayShouldShowAtAppOpen() -> Bool {
        WhileAwayPresentation.shouldShowAtAppOpen(
            lastShownDay: local.wywaLastShownDay, today: today,
            hasUnseen: hasUnseenReviewParks || !local.linkedExtensionNotices.isEmpty
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
    /// edit) is refused the same way. While the review is not exposed the
    /// reducer refuses it with `.reviewUnavailable`. Saving removes the
    /// task's decision-form drafts (FR-052); a refusal keeps them.
    @discardableResult
    public func decide(
        _ type: DecisionType, on taskID: TaskID, title: String? = nil, waitingFor: String? = nil, reason: String? = nil,
        stallReason: StallReason? = nil, aiUse: AIUse = .none, navigatorRequestID: String? = nil,
        sessionID: ReviewSessionID? = nil, formulationID opened: FormulationID? = nil, expectedTask: ShownTask? = nil
    ) throws(GTDValidationError) -> DecisionID {
        guard !isRustSelected else { throw .asynchronousSaveRequired }
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
        guard !isRustSelected else { return false }
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
        guard !isRustSelected else { presentationDraftError = "ASYNCHRONOUS_SAVE_REQUIRED"; return }
        guard reviewExposed else { return }
        let day = today
        edit { $0.local.wywaLastShownDay = day }
    }

    /// The unseen parks as M-09 lists them; pass the ones a sheet showed to
    /// `dismissWhileAway(shown:)`.
    public func unseenParkAcks() -> [ParkAck] {
        if isRustSelected { return rustReviewState?.unseenParks ?? [] }
        return GTDQueries.unseenParkAcks(in: state)
    }

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
        guard !isRustSelected else { presentationDraftError = "ASYNCHRONOUS_SAVE_REQUIRED"; return }
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
        if isRustSelected { return state.review.navigatorConsents[provider]?.allowsCloud == true }
        return state.review.navigatorConsents[provider]?.allowsCloud == true
    }

    // MARK: - Form drafts (FR-052)

    /// Keeps unsaved form text on this device only: never sent, never in an
    /// outbox operation, never logged.
    public func saveDraft(_ text: String, for key: DraftKey) {
        guard !isRustSelected else { presentationDraftError = "ASYNCHRONOUS_SAVE_REQUIRED"; return }
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
        if isRustSelected { return nil }
        guard let draft = local.formDrafts[key], Self.isLive(key, draft, in: state, now: now()) else { return nil }
        return draft.text
    }

    public func discardDraft(for key: DraftKey) {
        guard !isRustSelected else { presentationDraftError = "ASYNCHRONOUS_SAVE_REQUIRED"; return }
        edit { $0.local.formDrafts[key] = nil }
    }

    /// The unsaved weekly-review drafts a sign-out would remove, for its confirmation to name (spec
    /// 021, FR-018): the drafts still shown (`draft(for:)`), not expired or outdated ones. They live
    /// in the store the sign-out destroys, and are never synced.
    public var unsavedReviewDraftCount: Int {
        if isRustSelected { return rustReviewDraftCount }
        let instant = now()
        let current = state
        return local.formDrafts.filter { Self.isLive($0.key, $0.value, in: current, now: instant) }.count
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
        guard !isRustSelected else { return }
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
        guard !isRustSelected else { return }
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
        guard !isRustSelected else { return 0 }
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
        guard !isRustSelected else { return }
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
        guard !isRustSelected else { return }
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

extension Workspace {
    // MARK: Canonical Review reads

    private var hasUnseenReviewParks: Bool {
        isRustSelected ? (rustReviewState?.unseenParkTotal ?? 0) > 0 : !unseenParks().isEmpty
    }

    private func rustReviewQuery(_ read: WorkspaceReviewRead) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let bindings = rustIdentityBindings
        switch read {
        case .state: return try facade.workspaceReadQuery("review_state")
        case .summary(let session):
            return try facade.workspaceReviewSummaryQuery(session: session,
                explainerSeenLocally: local.explainerSeenLocally, activatedAt: local.activatedAt, bindings: bindings)
        case .formulation(let task):
            return try facade.workspaceReadQuery("task_formulation", taskID: task, bindings: bindings)
        case .queue(let step, let session):
            return try facade.workspaceReviewQueueQuery(step, session: session, bindings: bindings)
        case .projects: return try facade.workspaceReadQuery("projects", filter: "needs_next_action")
        case .restart: return try facade.workspaceReadQuery("restart_candidates")
        case .parkReturn(let task, let shown):
            return try facade.workspaceParkReturnQuery(task, shown: shown, bindings: bindings)
        case .releases(let kind, let session):
            return try facade.workspaceOpenReleasesQuery(kind, session: session, bindings: bindings)
        }
    }

    private func rustRead<Value>(_ read: WorkspaceReviewRead,
                                 decode: (RustDomainFacade, Data) throws -> Value) -> Value? {
        guard let facade = rustFacade, let query = try? rustReviewQuery(read),
              let page = rustPage(for: query) else { return nil }
        // Publication validated this owned page. Failure is represented by
        // query readiness, never another implementation of the read.
        return try? decode(facade, page.result)
    }

    private func rustQueue(_ step: ReviewStep, session: ReviewSessionID? = nil) -> RustWorkspaceReviewQueue? {
        rustRead(.queue(step, session)) { try $0.workspaceReviewQueue(from: $1, keeping: state, at: now()) }
    }

    private func rustFormulation(_ task: TaskID) -> RustWorkspaceFormulation? {
        rustRead(.formulation(task)) { try $0.workspaceFormulation(from: $1) }
    }

    private func rustSummary(session: ReviewSessionID? = nil) -> RustWorkspaceReviewSummary? {
        rustRead(.summary(session)) { try $0.workspaceReviewSummary(from: $1) }
    }

    private func rustReleases(_ kind: BulkReleaseKindCode, session: ReviewSessionID? = nil) -> [BulkReleaseRecord] {
        rustRead(.releases(kind, session)) { try $0.workspaceOpenReleases(from: $1, keeping: state, at: now()) } ?? []
    }

    public func reviewReadiness(_ read: WorkspaceReviewRead) -> WorkspaceQueryReadiness {
        guard isRustSelected else { return .ready }
        guard let query = try? rustReviewQuery(read) else { return .failed("WORKSPACE_NOT_READY") }
        _ = rustPage(for: query)
        return rustReadiness(for: query)
    }

    public func prepareReviewRead(_ read: WorkspaceReviewRead) async throws {
        guard isRustSelected else { return }
        let query = try rustReviewQuery(read)
        await prepareRustQuery(query)
        if case .state = read { try await hydrateShownParks(query) }
    }

    public func nextReviewPage(_ read: WorkspaceReviewRead) async throws {
        let query = try rustReviewQuery(read)
        await rustQueries?.nextPage(query)
        if case .state = read { try await hydrateShownParks(query) }
    }

    public func previousReviewPage(_ read: WorkspaceReviewRead) async throws {
        let query = try rustReviewQuery(read)
        await rustQueries?.previousPage(query)
        if case .state = read { try await hydrateShownParks(query) }
    }

    private func hydrateShownParks(_ query: Data) async throws {
        guard let facade = rustFacade, let page = rustPage(for: query),
              rustReadiness(for: query) == .ready else { return }
        let review = try facade.workspaceReviewState(from: page.result, keeping: state, at: now())
        let requests = review.unseenParks.map {
            facade.workspaceRecordRequest("task", localID: $0.taskID.rawValue, bindings: rustIdentityBindings)
        }
        guard !requests.isEmpty else { rustAdoptTasks([], for: query); return }
        let binding = runtimeBindingID
        let records = try await rustReadRecords(requests)
        guard binding == runtimeBindingID, rustPage(for: query) == page else { return }
        var owned = GTDState.empty
        try facade.workspaceApplyRecords(from: records.result, requests: requests, to: &owned, at: now())
        rustAdoptTasks(review.unseenParks.compactMap { owned.tasks[$0.taskID] }, for: query)
    }

    /// Called only after the lifecycle/cache generation fence has passed.
    func adoptRustReviewPage(query: Data, page: RustWorkspacePage) throws {
        guard let facade = rustFacade,
              let root = try JSONSerialization.jsonObject(with: query) as? [String: Any],
              let kind = root["kind"] as? String else { throw RustDomainError.malformedResult }
        switch kind {
        case "review_state":
            let review = try facade.workspaceReviewState(from: page.result, keeping: state, at: now())
            rustReviewState = review
            rustMutateShown {
                $0.review.settings = review.settings
                $0.review.server = review.server
                $0.review.sessions = review.openSession.map { [$0.id: $0] } ?? [:]
            }
        case "review_queue":
            let queue = try facade.workspaceReviewQueue(from: page.result, keeping: state, at: now())
            rustAdoptTasks(queue.tasks, for: query)
        case "restart_candidates":
            rustAdoptTasks(try facade.workspaceTasks(from: page.result, keeping: state, at: now()), for: query)
        case "task_formulation": _ = try facade.workspaceFormulation(from: page.result)
        case "park_return_shown": _ = try facade.workspaceParkReturnProblem(from: page.result)
        case "review_summary": _ = try facade.workspaceReviewSummary(from: page.result)
        case "open_releases": _ = try facade.workspaceOpenReleases(from: page.result, keeping: state, at: now())
        default: break
        }
    }

    // MARK: Durable Review actions

    private func reviewIntent(_ kind: String, _ fields: [String: Any] = [:]) throws -> Data {
        try JSONSerialization.data(withJSONObject: ["kind": kind, "fields": fields], options: [.sortedKeys])
    }

    private func reviewSave(_ commands: [GTDCommand], editorID: String, intent: Data,
                            shown: GTDState) async throws -> RustWorkspaceSavedGesture {
        try await performAsync(commands, editorID: editorID, authoredIntent: intent, shown: shown)
    }

    @discardableResult
    public func decide(
        _ type: DecisionType, on taskID: TaskID, title: String? = nil, waitingFor: String? = nil, reason: String? = nil,
        stallReason: StallReason? = nil, aiUse: AIUse = .none, navigatorRequestID: String? = nil,
        sessionID: ReviewSessionID? = nil, formulationID opened: FormulationID? = nil, expectedTask: ShownTask? = nil,
        editorID: String
    ) async throws -> DecisionID {
        guard isRustSelected else {
            guard let task = state.tasks[taskID] else { throw GTDValidationError.taskNotFound }
            let id = DecisionID.make(makeID())
            let starts: Set<DecisionType> = [.reformulate, .firstStep, .returnToNext, .followUp]
            let command = GTDCommand.DecideTask(decisionID: id, taskID: taskID, type: type,
                formulationID: type.decidesOnFormulation ? (opened ?? task.formulation?.id ?? task.parked?.formulationID) : nil,
                newFormulationID: starts.contains(type) ? .make(makeID()) : nil,
                stallReason: stallReason, title: title, waitingFor: waitingFor, reason: reason, sessionID: sessionID,
                aiUse: aiUse, navigatorRequestID: navigatorRequestID,
                followUpTaskID: type == .followUp ? TaskID(ClientID.make("task", makeID())) : nil,
                expectedTask: expectedTask)
            try await performLegacyDurably([.decideTask(command)], editorID: editorID, edits: [{ document in
                document.local.formDrafts = document.local.formDrafts.filter { $0.key.taskID != taskID }
            }])
            return id
        }
        let shown = state
        let binding = runtimeBindingID
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let task = shown.tasks[taskID]
        let formulation = opened ?? expectedTask?.content.formulation?.id ?? task?.formulation?.id ?? task?.parked?.formulationID
        let starts: Set<DecisionType> = [.reformulate, .firstStep, .returnToNext, .followUp]
        let command = GTDCommand.DecideTask(decisionID: .make(makeID()), taskID: taskID, type: type,
            formulationID: type.decidesOnFormulation ? formulation : nil,
            newFormulationID: starts.contains(type) ? .make(makeID()) : nil,
            stallReason: stallReason, title: title, waitingFor: waitingFor, reason: reason, sessionID: sessionID,
            aiUse: aiUse, navigatorRequestID: navigatorRequestID,
            followUpTaskID: type == .followUp ? TaskID(ClientID.make("task", makeID())) : nil, expectedTask: expectedTask)
        let intent = try reviewIntent("decide", ["task": taskID.rawValue, "type": type.rawValue,
            "title": title as Any? ?? NSNull(), "waiting_for": waitingFor as Any? ?? NSNull(),
            "reason": reason as Any? ?? NSNull(), "stall_reason": stallReason?.rawValue as Any? ?? NSNull(),
            "ai_use": aiUse.rawValue, "navigator_request": navigatorRequestID as Any? ?? NSNull(),
            "session": sessionID?.rawValue as Any? ?? NSNull(), "formulation": opened?.rawValue as Any? ?? NSNull()])
        let saved = try await reviewSave([.decideTask(command)], editorID: editorID, intent: intent, shown: shown)
        guard let actual = saved.commands.first(where: { $0.commandType == "review.decide" }),
              let payload = try? JSONSerialization.jsonObject(with: actual.payload) as? [String: Any],
              let rawID = payload["decision_id"] as? String else {
            throw RustBridgeError(code: "SAVED_RESULT_UNAVAILABLE")
        }
        let id = DecisionID(facade.workspaceLocalID(rawID))
        if binding == runtimeBindingID, let actualTask = actual.entityID {
            await clearSavedTaskDrafts(TaskID(facade.workspaceLocalID(actualTask)))
        }
        return id
    }

    public func undoDecision(_ id: DecisionID, editorID: String) async throws {
        guard isRustSelected else {
            try await performLegacyDurably([.undoDecision(id)], editorID: editorID)
            return
        }
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let frozen = state
        let request = facade.workspaceRecordRequest("review_decision", localID: id.rawValue, bindings: rustIdentityBindings)
        // The decision identifies its task; its canonical public record is not
        // a private Undo snapshot. Never fabricate the unavailable snapshot.
        let page = try await rustReadRecords([request])
        var shown = frozen
        try facade.workspaceApplyRecords(from: page.result, requests: [request], to: &shown, at: now())
        _ = try await reviewSave([.undoDecision(id)], editorID: editorID,
            intent: reviewIntent("undo_decision", ["id": id.rawValue]), shown: shown)
    }

    public func acknowledgeExplainer(editorID: String) async throws {
        guard isRustSelected else {
            let zone = deviceTimeZone().identifier, instant = Self.storedPrecision(now()), accountless = account == nil
            try await performLegacyDurably([.review(.acknowledgeExplainer(timeZone: zone))], editorID: editorID, edits: [{ document in
                if accountless, document.local.activatedAt == nil { document.local.activatedAt = instant }
                document.local.explainerSeenLocally = true
                document.local.lastObservedTimeZone = zone
            }])
            return
        }
        let shown = state, zone = deviceTimeZone().identifier, instant = Self.storedPrecision(now())
        let binding = runtimeBindingID, accountless = account == nil
        _ = try await reviewSave([.review(.acknowledgeExplainer(timeZone: zone))], editorID: editorID,
            intent: reviewIntent("explainer", ["zone": zone]), shown: shown)
        await maintainReviewPresentation(binding: binding) {
            if accountless, $0.activatedAt == nil { $0.activatedAt = instant }
            $0.explainerSeenLocally = true
            $0.lastObservedTimeZone = zone
        }
    }

    public func completeReviewOnboarding(
        thresholdDays: Int? = nil, reviewWeekday: Int? = nil, reviewTime: String? = nil, editorID: String
    ) async throws {
        guard isRustSelected else {
            let zone = deviceTimeZone().identifier
            let command = ReviewSettingsChange(thresholdDays: thresholdDays, reviewWeekday: reviewWeekday,
                reviewTime: reviewTime, timeZone: zone, onboarded: true)
            try await performLegacyDurably([.review(.updateSettings(command))], editorID: editorID,
                edits: [{ $0.local.lastObservedTimeZone = zone }])
            return
        }
        try await updateReviewSettings(ReviewSettingsChange(thresholdDays: thresholdDays,
            reviewWeekday: reviewWeekday, reviewTime: reviewTime, timeZone: deviceTimeZone().identifier, onboarded: true), editorID: editorID)
    }

    public func updateReviewSettings(_ change: ReviewSettingsChange, editorID: String) async throws {
        guard isRustSelected else {
            guard !change.isEmpty else { return }
            let edits: [@Sendable (inout StoreDocument) -> Void] = change.timeZone.map { zone in
                [{ $0.local.lastObservedTimeZone = zone }]
            } ?? []
            try await performLegacyDurably([.review(.updateSettings(change))], editorID: editorID, edits: edits)
            return
        }
        guard !change.isEmpty else { return }
        let shown = state
        let binding = runtimeBindingID
        let intent = try reviewIntent("settings", ["threshold": change.thresholdDays as Any? ?? NSNull(),
            "weekday": change.reviewWeekday as Any? ?? NSNull(), "time": change.reviewTime as Any? ?? NSNull(),
            "zone": change.timeZone as Any? ?? NSNull(), "onboarded": change.onboarded])
        _ = try await reviewSave([.review(.updateSettings(change))], editorID: editorID, intent: intent, shown: shown)
        if let zone = change.timeZone { await maintainReviewPresentation(binding: binding) { $0.lastObservedTimeZone = zone } }
    }

    @discardableResult
    public func sendDeviceTimeZoneIfChanged(editorID: String) async throws -> Bool {
        guard isRustSelected else {
            let current = deviceTimeZone()
            guard let observed = local.lastObservedTimeZone else {
                try await performLegacyDurably([], editorID: editorID,
                    edits: [{ $0.local.lastObservedTimeZone = current.identifier }])
                return false
            }
            guard let changed = DeviceZoneTracker.change(lastObserved: observed, current: current) else { return false }
            try await performLegacyDurably([.review(.updateSettings(ReviewSettingsChange(timeZone: changed.identifier)))],
                editorID: editorID, edits: [{ $0.local.lastObservedTimeZone = changed.identifier }])
            return true
        }
        let current = deviceTimeZone(), observed = local.lastObservedTimeZone
        guard let observed else {
            try await saveReviewPresentation { $0.lastObservedTimeZone = current.identifier }
            return false
        }
        guard let zone = DeviceZoneTracker.change(lastObserved: observed, current: current) else { return false }
        try await updateReviewSettings(ReviewSettingsChange(timeZone: zone.identifier), editorID: editorID)
        return true
    }

    public func dismissWhileAway(shown: [ParkAck], editorID: String) async throws {
        guard isRustSelected else {
            let acks = GTDQueries.whileAwayAcknowledgements(shown: shown, in: state), day = today
            let commands = stride(from: 0, to: acks.count, by: ReviewLimits.parkAcknowledgements).map {
                GTDCommand.review(.acknowledgeParks(Array(acks[$0..<min($0 + ReviewLimits.parkAcknowledgements, acks.count)])))
            }
            try await performLegacyDurably(commands, editorID: editorID, edits: [{ document in
                document.local.linkedExtensionNotices = []; document.local.parkBatchWaiting = false
                document.local.wywaLastShownDay = day
            }])
            return
        }
        let current = state, day = today
        let binding = runtimeBindingID
        let chunks = stride(from: 0, to: shown.count, by: ReviewLimits.parkAcknowledgements).map {
            Array(shown[$0..<min($0 + ReviewLimits.parkAcknowledgements, shown.count)])
        }
        if !chunks.isEmpty {
            let rows = shown.map { ["task": $0.taskID.rawValue, "formulation": $0.formulationID.rawValue] }
            _ = try await reviewSave(chunks.map { .review(.acknowledgeParks($0)) }, editorID: editorID,
                intent: reviewIntent("parks", ["shown": rows]), shown: current)
        }
        await maintainReviewPresentation(binding: binding) {
            $0.linkedExtensionNotices = []; $0.parkBatchWaiting = false; $0.wywaLastShownDay = day
        }
    }

    public func markWhileAwayShown(editorID: String) async throws {
        guard isRustSelected else {
            guard reviewExposed else { return }
            let day = today
            try await performLegacyDurably([], editorID: editorID, edits: [{ $0.local.wywaLastShownDay = day }])
            return
        }
        guard reviewExposed else { return }
        let day = today
        try await saveReviewPresentation { $0.wywaLastShownDay = day }
    }

    public func closeWhileAway(editorID: String) async throws {
        guard isRustSelected else {
            guard reviewExposed else { return }
            let day = today
            try await performLegacyDurably([], editorID: editorID, edits: [{ document in
                document.local.linkedExtensionNotices = []; document.local.wywaLastShownDay = day
            }])
            return
        }
        guard reviewExposed else { return }
        let day = today
        try await saveReviewPresentation { $0.linkedExtensionNotices = []; $0.wywaLastShownDay = day }
    }

    @discardableResult
    public func startReview(mode: ReviewMode, entry: ReviewEntry, skipping skipSteps: [ReviewStep] = [], editorID: String) async throws -> ReviewSessionID {
        guard isRustSelected else {
            let id = ReviewSessionID.make(makeID())
            try await performLegacyDurably([.review(.startSession(StartSession(sessionID: id, mode: mode,
                entry: entry, skipSteps: skipSteps)))], editorID: editorID)
            return id
        }
        let shown = state
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let command = StartSession(sessionID: .make(makeID()), mode: mode, entry: entry, skipSteps: skipSteps)
        let result = try await reviewSave([.review(.startSession(command))], editorID: editorID,
            intent: reviewIntent("start", ["mode": mode.rawValue, "entry": entry.rawValue, "skip": skipSteps.map(\.rawValue)]), shown: shown)
        guard let actual = result.receipts.first else { throw RustBridgeError(code: "SAVED_RESULT_UNAVAILABLE") }
        return ReviewSessionID(facade.workspaceLocalID(actual.entityID))
    }

    public func recordReviewProgress(
        _ sessionID: ReviewSessionID, currentStep: ReviewStep? = nil, step: ReviewStep? = nil,
        stepStatus: StepStatus? = nil, activeStep: ReviewStep? = nil, activeSeconds: Int? = nil,
        setAsideTaskID: TaskID? = nil, inboxProcessedDelta: Int? = nil, snapshotDecisionQueue: Bool = false, editorID: String
    ) async throws {
        guard isRustSelected else {
            let command = SessionProgress(sessionID: sessionID, progressID: .make(makeID()), currentStep: currentStep,
                step: step, stepStatus: stepStatus, activeStep: activeStep, activeSeconds: activeSeconds,
                setAsideTaskID: setAsideTaskID, inboxProcessedDelta: inboxProcessedDelta, snapshotDecisionQueue: snapshotDecisionQueue)
            try await performLegacyDurably([.review(.progressSession(command))], editorID: editorID)
            return
        }
        let shown = state
        let command = SessionProgress(sessionID: sessionID, progressID: .make(makeID()), currentStep: currentStep,
            step: step, stepStatus: stepStatus, activeStep: activeStep, activeSeconds: activeSeconds,
            setAsideTaskID: setAsideTaskID, inboxProcessedDelta: inboxProcessedDelta, snapshotDecisionQueue: snapshotDecisionQueue)
        let intent = try reviewIntent("progress", ["session": sessionID.rawValue,
            "current": currentStep?.rawValue as Any? ?? NSNull(), "step": step?.rawValue as Any? ?? NSNull(),
            "status": stepStatus?.rawValue as Any? ?? NSNull(), "active": activeStep?.rawValue as Any? ?? NSNull(),
            "seconds": activeSeconds as Any? ?? NSNull(), "aside": setAsideTaskID?.rawValue as Any? ?? NSNull(),
            "inbox": inboxProcessedDelta as Any? ?? NSNull(), "snapshot": snapshotDecisionQueue])
        _ = try await reviewSave([.review(.progressSession(command))], editorID: editorID,
            intent: intent, shown: shown)
    }

    public func finishReview(_ sessionID: ReviewSessionID, clearStart: ClearStart? = nil, editorID: String) async throws {
        guard isRustSelected else {
            try await performLegacyDurably([.review(.finishSession(FinishSession(sessionID: sessionID, clearStart: clearStart)))], editorID: editorID)
            return
        }
        let shown = state
        _ = try await reviewSave([.review(.finishSession(FinishSession(sessionID: sessionID, clearStart: clearStart)))],
            editorID: editorID,
            intent: reviewIntent("finish", ["session": sessionID.rawValue, "clear": clearStart?.rawValue as Any? ?? NSNull()]), shown: shown)
    }

    @discardableResult
    public func bulkRelease(_ kind: BulkReleaseKindCode, taskIDs: [TaskID], sessionID: ReviewSessionID? = nil, editorID: String) async throws -> [BulkID] {
        guard isRustSelected else {
            let commands = stride(from: 0, to: taskIDs.count, by: ReviewLimits.bulkReleaseItems).map {
                GTDCommand.BulkRelease(bulkID: .make(makeID()), kind: kind, sessionID: sessionID,
                    taskIDs: Array(taskIDs[$0..<min($0 + ReviewLimits.bulkReleaseItems, taskIDs.count)]))
            }
            guard !commands.isEmpty else { return [] }
            try await performLegacyDurably(commands.map { .bulkRelease($0) }, editorID: editorID)
            return commands.map(\.bulkID)
        }
        let shown = state
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let commands = stride(from: 0, to: taskIDs.count, by: ReviewLimits.bulkReleaseItems).map {
            GTDCommand.bulkRelease(GTDCommand.BulkRelease(bulkID: .make(makeID()), kind: kind, sessionID: sessionID,
                taskIDs: Array(taskIDs[$0..<min($0 + ReviewLimits.bulkReleaseItems, taskIDs.count)])))
        }
        guard !commands.isEmpty else { return [] }
        let result = try await reviewSave(commands, editorID: editorID,
            intent: reviewIntent("bulk", ["kind": kind.rawValue, "tasks": taskIDs.map(\.rawValue),
                "session": sessionID?.rawValue as Any? ?? NSNull()]), shown: shown)
        return result.receipts.map { BulkID(facade.workspaceLocalID($0.entityID)) }
    }

    public func undoBulkRelease(_ ids: [BulkID], editorID: String) async throws {
        guard isRustSelected else {
            guard !ids.isEmpty else { return }
            try await performLegacyDurably(ids.map { .undoBulkRelease($0) }, editorID: editorID)
            return
        }
        let shown = state
        guard !ids.isEmpty else { return }
        _ = try await reviewSave(ids.map { .undoBulkRelease($0) }, editorID: editorID,
            intent: reviewIntent("bulk_undo", ["ids": ids.map(\.rawValue)]), shown: shown)
    }

    public func grantNavigatorConsent(provider: String, consentTextVersion: Int, editorID: String) async throws {
        guard isRustSelected else {
            try await performLegacyDurably([.review(.grantNavigatorConsent(provider: provider,
                consentTextVersion: consentTextVersion))], editorID: editorID)
            return
        }
        let shown = state
        let binding = runtimeBindingID
        _ = try await reviewSave([.review(.grantNavigatorConsent(provider: provider, consentTextVersion: consentTextVersion))],
            editorID: editorID,
            intent: reviewIntent("consent", ["provider": provider, "version": consentTextVersion]), shown: shown)
        await refreshSavedConsent(provider, binding: binding)
    }

    public func revokeNavigatorConsent(provider: String, editorID: String) async throws {
        guard isRustSelected else {
            try await performLegacyDurably([.review(.revokeNavigatorConsent(provider: provider))], editorID: editorID)
            return
        }
        let shown = state
        let binding = runtimeBindingID
        _ = try await reviewSave([.review(.revokeNavigatorConsent(provider: provider))], editorID: editorID,
            intent: reviewIntent("revoke", ["provider": provider]), shown: shown)
        await refreshSavedConsent(provider, binding: binding)
    }
}

extension Workspace {
    /// Only presentation facts share this draft. Form text has independent
    /// runtime rows and a store-owned live count, so it never becomes a blob
    /// or a second frontend index.
    private func saveReviewPresentation(_ edit: (inout LocalReviewState) -> Void) async throws {
        guard let runtime = rustRuntime, isRustBound else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        guard !rustReviewPresentationSaving else { throw RustBridgeError(code: "BUSY", retryable: true) }
        let binding = runtimeBindingID
        rustReviewPresentationSaving = true
        defer { if binding == runtimeBindingID { rustReviewPresentationSaving = false } }
        var next = rustLocalReview
        next.formDrafts = [:]
        edit(&next)
        let fields = try StoreDocumentCoding.makeEncoder().encode(next)
        do {
            try await runtime.saveDraft(RustWorkspaceDraft(draftID: "runtime:local-review", editorKind: "runtime_review_local",
                fields: fields, updatedAt: ISO8601DateFormatter().string(from: now())))
            guard binding == runtimeBindingID else { return }
            rustLocalReview = next
            presentationDraftError = nil
        } catch {
            if binding == runtimeBindingID { presentationDraftError = (error as? RustBridgeError)?.code ?? "DRAFT_SAVE_FAILED" }
            throw error
        }
    }

    /// A presentation cleanup failure is separate from the known committed
    /// command result. Its text/error remains available for explicit retry.
    private func maintainReviewPresentation(binding: UUID, _ edit: (inout LocalReviewState) -> Void) async {
        guard binding == runtimeBindingID else { return }
        do { try await saveReviewPresentation(edit) }
        catch {
            if binding == runtimeBindingID { presentationDraftError = (error as? RustBridgeError)?.code ?? "DRAFT_SAVE_FAILED" }
        }
    }
}

extension Workspace {
    public func prepareNavigatorConsent(provider: String) async throws {
        guard isRustSelected else { return }
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let binding = runtimeBindingID
        let request = RustWorkspaceRecordRequest(entityType: "review_navigator_consent", recordKey: [provider])
        let page = try await rustReadRecords([request])
        guard binding == runtimeBindingID else { return }
        var owned = GTDState.empty
        try facade.workspaceApplyRecords(from: page.result, requests: [request], to: &owned, at: now())
        rustMutateShown { $0.review.navigatorConsents[provider] = owned.review.navigatorConsents[provider] }
    }

    private func refreshSavedConsent(_ provider: String, binding: UUID) async {
        guard binding == runtimeBindingID else { return }
        do { try await prepareNavigatorConsent(provider: provider) }
        catch {
            if binding == runtimeBindingID { markRustQueryError((error as? RustBridgeError)?.code ?? "CONSENT_QUERY_FAILED") }
        }
    }
}

extension Workspace {
    // MARK: Runtime form drafts

    public func draft(for key: DraftKey, editorID: String) async throws -> String? {
        guard isRustSelected else { return draft(for: key) }
        guard let runtime = rustRuntime, isRustBound else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let binding = runtimeBindingID
        let loaded = try await runtime.loadReviewForm(key.rawValue, now: now())
        guard binding == runtimeBindingID else { throw RustBridgeError(code: "WORKSPACE_CLOSED") }
        publishReviewDraftCount(loaded.liveCount, generation: loaded.projectionGeneration)
        return loaded.draft?.text
    }

    public func saveDraft(_ text: String, for key: DraftKey, editorID: String) async throws {
        guard isRustSelected else {
            let instant = now()
            try await performLegacyDurably([], editorID: editorID, edits: [{ document in
                document.local.formDrafts[key] = text.isEmpty ? nil : FormDraft(text: text, savedAt: instant)
            }])
            return
        }
        guard let runtime = rustRuntime, isRustBound else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let binding = runtimeBindingID, instant = now()
        do {
            // This resolves immutable imported identity proof, not a new task
            // revision or a replacement of the card's displayed frame.
            let loaded = try await runtime.loadReviewForm(key.rawValue, now: instant)
            guard binding == runtimeBindingID else { throw RustBridgeError(code: "WORKSPACE_CLOSED") }
            let form = text.isEmpty ? nil : FormDraft(text: text, savedAt: instant)
            let result = try await runtime.saveReviewForm(key.rawValue, sourceKey: loaded.sourceKey, draft: form, now: instant)
            guard binding == runtimeBindingID else { return }
            publishReviewDraftCount(result.liveCount, generation: result.projectionGeneration)
            presentationDraftError = nil
        } catch {
            if binding == runtimeBindingID { presentationDraftError = (error as? RustBridgeError)?.code ?? "DRAFT_SAVE_FAILED" }
            throw error
        }
    }

    public func discardDraft(for key: DraftKey, editorID: String) async throws {
        try await saveDraft("", for: key, editorID: editorID)
    }

    public func prepareReviewDraftCount() async throws {
        guard isRustSelected else { return }
        guard let runtime = rustRuntime, isRustBound else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        let binding = runtimeBindingID
        let result = try await runtime.reviewFormCount(now: now())
        guard binding == runtimeBindingID else { return }
        publishReviewDraftCount(result.liveCount, generation: result.projectionGeneration)
    }

    private func publishReviewDraftCount(_ count: Int, generation: String) {
        guard let generation = UInt64(generation), generation >= (rustQueries?.generationFloor ?? 0) else {
            markRustQueryError("DRAFT_COUNT_REFRESH_REQUIRED")
            return
        }
        rustReviewDraftCount = count
    }

    private func clearSavedTaskDrafts(_ taskID: TaskID) async {
        guard let runtime = rustRuntime, isRustBound else { return }
        let binding = runtimeBindingID
        do {
            // One store transaction shadows all matching imported/runtime
            // forms. Their absent text cannot reappear after reopening.
            let result = try await runtime.clearReviewFormsForTask(taskID.rawValue, now: now())
            guard binding == runtimeBindingID else { return }
            publishReviewDraftCount(result.liveCount, generation: result.projectionGeneration)
            presentationDraftError = nil
        } catch {
            if binding == runtimeBindingID { presentationDraftError = (error as? RustBridgeError)?.code ?? "DRAFT_CLEAR_FAILED" }
        }
    }
}
