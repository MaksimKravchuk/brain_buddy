import BrainBuddyAPI
import BrainBuddyCore
import Foundation

// The weekly review on the fake server (spec 020, contracts/http.md §3 – §7):
// decisions with the yield rule and the matching-record answer to a retry after
// the idempotency retention, Undo, device auto-park and the sweep, the
// explainer and activation, settings, park acknowledgements, sessions with
// replay-safe progress, bulk releases and consent. The clock rule is Core's
// `FormulationRule`, so the fake cannot drift from the device's rule.

// MARK: - Tables

struct FakeReviewData: Sendable {
    var settings = ReviewSettings(revision: 1)
    var decisions: [String: FakeDecision] = [:]
    var sessions: [String: FakeSession] = [:]
    /// Keyed `task|kind`.
    var receipts: [String: FakeReceipt] = [:]
    /// Keyed `task|formulation` (data-model E6).
    var parkAcks: [String: FakeParkAck] = [:]
    var bulkReleases: [String: FakeBulkRelease] = [:]
    var consents: [String: NavigatorConsent] = [:]
    /// The owner's last effective sweep (the 24 h gap rule).
    var lastSweepAt: Date?
}

struct FakeDecision: Sendable {
    var id: String
    var taskID: String
    var type: DecisionType
    var formulationID: String?
    var sessionID: String?
    var decidedAt: Date
    var substantive: Bool?
    var stallReason: StallReason?
    var aiUse: AIUse
    var reasonText: String?
    var revisionAfter: Int
    var taskBefore: TaskRow
    var createdTaskID: String?
    var createdTaskRevision: Int?
    var receiptKey: String?
    var yielded: Bool
}

struct FakeReceipt: Sendable {
    var taskID: String
    var kind: ReceiptKind
    var taskRevision: Int
    var reviewedAt: Date
    var hiddenUntil: Date
    var source: ReceiptSource
}

struct FakeParkAck: Sendable {
    var parkedAt: Date
    var fromRevision: Int
    var seenAt: Date?
    var returnedAt: Date?
}

struct FakeSession: Sendable {
    var id: String
    var mode: ReviewMode
    var entry: ReviewEntry
    var origin: ReviewOrigin
    var status: ReviewSessionStatus
    var startedAt: Date
    var lastActivityAt: Date
    var endedAt: Date?
    var currentStep: ReviewStep?
    var steps: [ReviewStep: StepStatus]
    var activeSeconds: [ReviewStep: Int] = [:]
    var counts = SessionCounts()
    var setAside: [String] = []
    var qualifying = false
    var clearStart: ClearStart?
    var revision = 1
    /// `progress_id` → digest of the canonical body (http §6).
    var appliedProgress: [String: String] = [:]

    var dto: SessionDTO {
        SessionDTO(
            id: id, mode: mode, entry: entry, origin: origin, status: status, startedAt: startedAt,
            lastActivityAt: lastActivityAt, endedAt: endedAt, currentStep: currentStep, steps: steps,
            activeSecondsByStep: activeSeconds, counts: counts, setAsideCount: setAside.count, qualifyingActivity: qualifying,
            clearStart: clearStart, revision: revision
        )
    }

    mutating func end(_ end: SessionEnd, at now: Date) {
        status = ReviewSessionStatus.ended(by: end, qualifyingActivity: qualifying)
        endedAt = now
        appliedProgress = [:]
        revision += 1
    }
}

struct FakeBulkRelease: Sendable {
    struct Released: Sendable {
        var taskID: String
        var revisionAfter: Int
        var previousState: TaskState
        var clockBefore: ReleasedClock?
    }

    var id: String
    var kind: BulkReleaseKindCode
    var taskIDs: Set<String>
    var released: [Released]
    var skipped: [BulkSkippedItemDTO]
    var undoResult: BulkReleaseUndoResponseDTO?

    var response: BulkReleaseResponseDTO {
        BulkReleaseResponseDTO(
            id: id, released: released.map { BulkReleasedItemDTO(taskID: $0.taskID, revisionAfter: $0.revisionAfter) },
            skipped: skipped
        )
    }
}

/// What a test reads about the account's review on the server.
public struct FakeReviewSnapshot: Hashable, Sendable {
    public var settings: ReviewSettings
    public var decisionIDs: Set<String>
    public var sessions: [String: SessionDTO]
    public var unseenParks: Set<String>
    public var bulkReleaseIDs: Set<String>
    public var consents: [String: NavigatorConsent]
}

extension FakeBrainBuddyServer {
    /// Switches the `weekly_review` flag for the account (rollback, cohort).
    public func setWeeklyReview(email: String, enabled: Bool) {
        state.withLock { state in
            guard let id = state.accountIDsByEmail[email.lowercased()] else { return }
            state.accounts[id]?.weeklyReview = enabled
        }
    }

    /// One run of the exposure part of the maintenance sweep for every
    /// activated owner whose flag is on (formulation-clock §3): after a gap of
    /// 24 h or more since the owner's last effective run, every park is
    /// floored for 7 days; a Next task without a clock is repaired with 14
    /// days of grace; then every due task parks.
    @discardableResult
    public func runAutoParkSweep() -> Int {
        let date = FakeBrainBuddyServer.serverTime(now())
        return state.withLock { state in
            var parked = 0
            for owner in state.owners.keys.sorted() where state.accounts[owner]?.weeklyReview == true {
                guard var data = state.owners[owner], data.review.settings.activatedAt != nil else { continue }
                if let last = data.review.lastSweepAt, date.timeIntervalSince(last) >= FakeBrainBuddyServer.sweepGap {
                    let floored = FormulationRule.applySweepGap(data.clockSettings, now: date)
                    data.review.settings.ownerParkFloorAt = floored.ownerParkFloorAt
                }
                for id in data.tasks.keys.sorted() {
                    guard var task = data.tasks[id] else { continue }
                    if task.state == .next, task.formulation == nil {
                        let repairID = FormulationID(ClientID.derived("form", from: "repair|\(id)|\(task.revision)"))
                        task.clocked = FormulationRule.repairClock(task.clocked, now: date, formulationID: repairID)
                    }
                    if data.park(&task, now: date) { parked += 1 }
                    data.tasks[id] = task
                }
                data.review.lastSweepAt = date
                state.owners[owner] = data
            }
            return parked
        }
    }

    /// The gap after which a sweep floors every park (formulation-clock §3).
    public static let sweepGap: TimeInterval = 86_400

    /// Test hook: a Next task loses its clock, as an old client's save or a
    /// rollback leaves it (the sweep repairs it).
    public func dropClock(email: String, title: String) {
        state.withLock { state in
            guard let owner = state.accountIDsByEmail[email.lowercased()], var data = state.owners[owner],
                let id = data.tasks.values.first(where: { $0.title == title })?.id
            else { return }
            data.tasks[id]?.formulation = nil
            state.owners[owner] = data
        }
    }

    public func reviewSnapshot(email: String) -> FakeReviewSnapshot {
        state.withLock { state in
            let data = state.accountIDsByEmail[email.lowercased()].flatMap { state.owners[$0] } ?? OwnerData()
            return FakeReviewSnapshot(
                settings: data.review.settings, decisionIDs: Set(data.review.decisions.keys),
                sessions: data.review.sessions.mapValues(\.dto),
                unseenParks: Set(data.unseenParks.map(\.taskID)), bulkReleaseIDs: Set(data.review.bulkReleases.keys),
                consents: data.review.consents
            )
        }
    }
}

// MARK: - Clock rules on owner data

extension OwnerData {
    var clockSettings: OwnerClockSettings { review.settings.clockSettings() }

    /// The formulation clock for a task write (formulation-clock §3): a list
    /// change relocates it, a substantive title change in Next restarts it, a
    /// due-date change in Next raises the floor.
    func maintainClock(of task: inout TaskRow, from old: TaskRow, newFormulationID: String?, now: Date) {
        let settings = clockSettings
        let newID = FormulationID(newFormulationID ?? ClientID.derived("form", from: "\(task.id)|\(old.revision + 1)"))
        if task.state != old.state {
            let relocated = FormulationRule.relocate(old.clocked, to: task.state, settings: settings, now: now, newFormulationID: newID)
            task.formulation = relocated.formulation
            task.consecutiveStalledFormulations = relocated.consecutiveStalledFormulations
            task.parked = relocated.parked
            return
        }
        guard task.state == .next else { return }
        if task.title != old.title, FormulationKey.isSubstantive(from: old.title, to: task.title) {
            let closed = FormulationRule.closeFormulation(old.clocked, settings: settings, now: now)
            task.consecutiveStalledFormulations = closed.consecutiveStalledFormulations
            task.formulation = FormulationClock(id: newID, startedAt: now)
        }
        if task.dueDate != old.dueDate {
            task.clocked = FormulationRule.raiseTaskFloor(task.clocked, to: now.addingTimeInterval(FormulationRule.dueDateFloor))
        }
    }

    /// Parks `task` iff the owner is activated and its class is `park_due`,
    /// writing the park row in the same step (a repeat park of a formulation
    /// resets "seen", data-model E6). Returns whether it parked.
    mutating func park(_ task: inout TaskRow, now: Date) -> Bool {
        guard review.settings.activatedAt != nil, task.state == .next,
            let parked = FormulationRule.autoPark(task.clocked, settings: clockSettings, now: now),
            let marker = parked.parked
        else { return false }
        task.clocked = parked
        task.waitingFor = nil
        task.waitingSince = nil
        task.updatedAt = now
        review.parkAcks["\(task.id)|\(marker.formulationID.rawValue)"] = FakeParkAck(
            parkedAt: now, fromRevision: marker.fromRevision ?? task.revision - 1
        )
        return true
    }

    /// E3 / FR-029 on the server's rows (as `ReviewRules.hasNothingToDecide`).
    func hasNothingToDecide(_ step: ReviewStep, now: Date) -> Bool {
        func hidden(_ task: TaskRow, _ kind: ReceiptKind) -> Bool {
            guard let receipt = review.receipts["\(task.id)|\(kind.rawValue)"] else { return false }
            return now < receipt.hiddenUntil && receipt.taskRevision == task.revision
        }
        switch step {
        case .summary: return false
        case .wins, .mindSweep, .restOfNext, .dates: return true
        case .inbox: return !tasks.values.contains { $0.state == .inbox }
        case .decisions:
            return !tasks.values.contains { task in
                task.state == .next && FormulationRule.classify(task.clocked, settings: clockSettings, now: now).asksForDecision
            }
        case .waiting:
            return !tasks.values.contains { task in
                guard task.state == .waiting, let since = task.waitingSince else { return false }
                return now.timeIntervalSince(since) > ReviewRules.waitingAge && !hidden(task, .waiting)
            }
        case .someday:
            return !tasks.values.contains { task in
                guard task.state == .someday else { return false }
                if let parked = task.parked, now.timeIntervalSince(parked.at) < ReviewRules.recentPark { return false }
                return !hidden(task, .someday)
            }
        case .projects:
            return !projects.values.contains { project in
                project.state == .active && !tasks.values.contains { $0.projectID == project.id && $0.state == .next }
            }
        }
    }

    var unseenParks: [UnseenParkDTO] {
        tasks.values.compactMap { task in
            guard task.state == .someday, let marker = task.parked,
                review.parkAcks["\(task.id)|\(marker.formulationID.rawValue)"]?.seenAt == nil
            else { return nil }
            return UnseenParkDTO(taskID: task.id, formulationID: marker.formulationID.rawValue, parkedAt: marker.at)
        }
        .sorted { ($0.parkedAt, $0.taskID) < ($1.parkedAt, $1.taskID) }
    }

    /// `GET /review/state`.
    func reviewState(now: Date) -> ReviewStateDTO {
        let settings = review.settings
        let sessions = review.sessions.values
        let counted = sessions.compactMap { session -> Date? in
            guard session.status.isCounted(qualifyingActivity: session.qualifying) else { return nil }
            return session.status == .completed ? session.endedAt ?? session.lastActivityAt : session.lastActivityAt
        }
        let last = sessions.filter { $0.status == .completed || $0.status == .partial }
            .max { ($0.endedAt ?? $0.lastActivityAt) < ($1.endedAt ?? $1.lastActivityAt) }
        let zone = TimeZone(identifier: settings.timeZone) ?? TimeZone(secondsFromGMT: 0)!
        var asks = 0
        var tomorrow = 0
        for task in tasks.values where task.state == .next {
            let klass = FormulationRule.classify(task.clocked, settings: clockSettings, now: now)
            if klass.asksForDecision { asks += 1 }
            if klass == .movesTomorrow { tomorrow += 1 }
        }
        return ReviewStateDTO(
            settings: settingsDTO, explainerSeen: settings.activatedAt != nil, graceUntil: settings.graceUntil,
            lastCountedReviewAt: counted.max(),
            lastCountedReview: last.map {
                LastCountedReviewDTO(
                    sessionID: $0.id, status: $0.status, origin: $0.origin, endedAt: $0.endedAt, counts: $0.counts,
                    clearStart: $0.clearStart
                )
            },
            nextReviewAt: ReviewReminderPlanner.nextFireDate(settings: settings, lastCountedReview: counted.max(), now: now, timeZone: zone)
                ?? now,
            restartMode: ReviewRules.restartMode(onboardedAt: settings.onboardedAt, lastCountedReviewAt: counted.max(), now: now),
            openSession: sessions.first { $0.status == .open }?.dto, unseenParks: unseenParks,
            counts: ReviewStateCountsDTO(asksForDecision: asks, movesTomorrow: tomorrow),
            receipts: review.receipts.values.filter { now < $0.hiddenUntil }.sorted { $0.taskID < $1.taskID }.map {
                ReceiptDTO(taskID: $0.taskID, kind: $0.kind, hiddenUntil: $0.hiddenUntil, taskRevision: $0.taskRevision)
            },
            serverNow: now
        )
    }

    var settingsDTO: ReviewSettingsDTO {
        let settings = review.settings
        return ReviewSettingsDTO(
            thresholdDays: settings.thresholdDays, reviewWeekday: settings.reviewWeekday, reviewTime: settings.reviewTime,
            timeZone: settings.timeZone, onboardedAt: settings.onboardedAt, activatedAt: settings.activatedAt,
            ownerParkFloorAt: settings.ownerParkFloorAt, revision: settings.revision ?? 1
        )
    }

    func decisionResponse(_ decision: FakeDecision) throws(FakeHTTPError) -> DecisionResponseDTO {
        let receipt = decision.receiptKey.flatMap { review.receipts[$0] }
        return DecisionResponseDTO(
            decision: DecisionRecordDTO(
                id: decision.id, type: decision.type, taskID: decision.taskID, sessionID: decision.sessionID,
                decidedAt: decision.decidedAt, substantive: decision.substantive, stallReason: decision.stallReason,
                aiUse: decision.aiUse, yieldedAutoPark: decision.yielded
            ),
            task: try task(decision.taskID).dto(), createdTask: decision.createdTaskID.flatMap { tasks[$0]?.dto() },
            receipt: receipt.map {
                ReceiptDTO(taskID: $0.taskID, kind: $0.kind, hiddenUntil: $0.hiddenUntil, taskRevision: $0.taskRevision)
            },
            sessionCounts: decision.sessionID.flatMap { review.sessions[$0]?.counts }
        )
    }

    mutating func writeReceipt(
        _ task: TaskRow, kind: ReceiptKind, source: ReceiptSource, now: Date
    ) -> String {
        let key = "\(task.id)|\(kind.rawValue)"
        review.receipts[key] = FakeReceipt(
            taskID: task.id, kind: kind, taskRevision: task.revision, reviewedAt: now,
            hiddenUntil: now.addingTimeInterval(kind.hiddenFor), source: source
        )
        return key
    }
}

// MARK: - Routes

extension FakeHTTPError {
    static let reviewDisabled = FakeHTTPError(
        status: 404, message: "Not found", detail: .object(["reason": .string("weekly_review_disabled")])
    )

    static func reason(_ status: Int, _ reason: String, _ message: String) -> FakeHTTPError {
        FakeHTTPError(status: status, message: message, detail: .object(["reason": .string(reason)]))
    }

    static let idConflict = reason(409, "id_conflict", "This id is already used by another record.")
}

extension RequestBody {
    /// A client-supplied id: `<prefix>_<lowercase uuid>` only (422 otherwise).
    func clientID(_ key: String, prefix: String) throws(FakeHTTPError) -> String? {
        guard let value = try string(key) else { return nil }
        guard ClientID.isValid(value, prefix: prefix) else {
            throw .validation(["body", key], "String should match pattern", type: "string_pattern_mismatch")
        }
        return value
    }

    /// A reference: the client shape or the server-minted `<prefix>_<12 hex>`.
    func reference(_ key: String, prefix: String) throws(FakeHTTPError) -> String? {
        guard let value = try string(key) else { return nil }
        let rest = value.dropFirst(prefix.count + 1)
        let serverShape = value.hasPrefix(prefix + "_") && rest.count == 12 && rest.allSatisfy(\.isHexDigit)
        guard ClientID.isValid(value, prefix: prefix) || serverShape else {
            throw .validation(["body", key], "String should match pattern", type: "string_pattern_mismatch")
        }
        return value
    }

    func optionalInt(_ key: String) throws(FakeHTTPError) -> Int? {
        guard let raw = fields[key], raw != .null else { return nil }
        guard case .number(let number) = raw, number.rounded() == number else {
            throw .validation(["body", key], "Input should be a valid integer", type: "int_type")
        }
        return Int(number)
    }

    func bool(_ key: String) throws(FakeHTTPError) -> Bool? {
        switch fields[key] {
        case nil, .null?: return nil
        case .bool(let value)?: return value
        default: throw .validation(["body", key], "Input should be a valid boolean", type: "bool_type")
        }
    }

    func instant(_ key: String) throws(FakeHTTPError) -> Date? {
        guard let raw = try string(key) else { return nil }
        guard raw.hasSuffix("Z") || raw.contains("+"), let date = WireDate.parse(raw) else {
            throw .validation(["body", key], "Input should have timezone info", type: "timezone_aware")
        }
        return date
    }

    /// The canonical body without `progress_id`, for replay protection.
    var progressDigest: String {
        RequestBody(fields: fields.filter { $0.key != "progress_id" }).fingerprint(command: "progress")
    }
}

extension ServerState {
    func weeklyReview(_ owner: String) -> Bool { accounts[owner]?.weeklyReview ?? false }

    /// `_serialized_write` for a review command: replay by key, otherwise run
    /// `work`, remember its answer under the key, and commit.
    mutating func idempotentReview(
        _ request: HTTPRequest, body: RequestBody, owner: String, command: String, now: Date,
        _ work: (inout OwnerData) throws(FakeHTTPError) -> Reply
    ) throws(FakeHTTPError) -> Reply {
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let fingerprint = body.fingerprint(command: command)
        if case .response(let status, let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return status == 204 ? .noContent() : Reply(status: status, body: stored)
        }
        let reply = try work(&data)
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .response(status: reply.status, body: reply.body), now: now)
        commit(data, owner: owner)
        return reply
    }

    mutating func routeReview(_ method: HTTPMethod, _ path: [String], _ request: HTTPRequest, owner: String, now: Date)
        throws(FakeHTTPError) -> Reply
    {
        let rest = Array(path.dropFirst())
        switch (method, rest.count) {
        case (.get, 1) where rest[0] == "state":
            guard weeklyReview(owner) else { throw .reviewDisabled }
            return .json(200, data(owner).reviewState(now: now))
        case (.post, 2) where rest == ["explainer", "acknowledge"]:
            return try acknowledgeExplainer(request, owner: owner, now: now)
        case (.put, 1) where rest[0] == "settings":
            return try updateSettings(request, owner: owner, now: now)
        case (.post, 2) where rest == ["parks", "acknowledge"]:
            return try acknowledgeParks(request, owner: owner, now: now)
        case (.post, 3) where rest[0] == "decisions" && rest[2] == "undo":
            return try undoDecision(rest[1], request, owner: owner, now: now)
        case (.post, 1) where rest[0] == "sessions":
            return try startSession(request, owner: owner, now: now)
        case (.get, 2) where rest[0] == "sessions":
            guard weeklyReview(owner) else { throw .reviewDisabled }
            guard let session = data(owner).review.sessions[rest[1]] else { throw .notFound("review_session", rest[1]) }
            return .json(200, session.dto)
        case (.patch, 2) where rest[0] == "sessions":
            return try progressSession(rest[1], request, owner: owner, now: now)
        case (.post, 3) where rest[0] == "sessions" && rest[2] == "finish":
            return try finishSession(rest[1], request, owner: owner, now: now)
        case (.post, 1) where rest[0] == "bulk-releases":
            return try bulkRelease(request, owner: owner, now: now)
        case (.post, 3) where rest[0] == "bulk-releases" && rest[2] == "undo":
            return try undoBulkRelease(rest[1], request, owner: owner, now: now)
        case (.get, 1) where rest[0] == "navigator":
            return .json(200, navigatorStatus(owner))
        case (.post, 2) where rest == ["navigator", "consent"]:
            guard weeklyReview(owner) else { throw .reviewDisabled }
            return try grantConsent(request, owner: owner, now: now)
        case (.delete, 2) where rest == ["navigator", "consent"]:
            return try revokeConsent(request, owner: owner, now: now)
        default:
            throw .routeNotFound
        }
    }

    // MARK: Decisions (http §3)

    mutating func decide(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(
            request.body,
            allowing: [
                "decision_id", "type", "expected_revision", "formulation_id", "stall_reason", "title", "waiting_for", "reason",
                "session_id", "ai_use", "navigator_request_id", "client_decided_at", "new_formulation_id", "follow_up_task_id",
            ]
        )
        let decisionID = try body.clientID("decision_id", prefix: "decision")
        guard let type = try body.value("type", as: DecisionType.self) else {
            throw .validation(["body", "type"], "Field required", type: "missing")
        }
        let expected = try body.int("expected_revision", minimum: 1)
        let formulationID = try body.reference("formulation_id", prefix: "form")
        let stallReason = try body.value("stall_reason", as: StallReason.self)
        let title = try body.string("title", min: 1, max: 500)
        let waitingFor = try body.string("waiting_for", min: 1, max: 500)
        let reason = try body.string("reason", max: 500).map(PythonText.strip)
        let sessionID = try body.reference("session_id", prefix: "review")
        let aiUse = try body.value("ai_use", as: AIUse.self) ?? AIUse.none
        // The navigator's request id is the 36-character lowercase UUID it answered with.
        if let request = try body.string("navigator_request_id"), !ClientID.isValid("n_" + request, prefix: "n") {
            throw .validation(["body", "navigator_request_id"], "String should match pattern", type: "string_pattern_mismatch")
        }
        let clientDecidedAt = try body.instant("client_decided_at")
        let newFormulationID = try body.clientID("new_formulation_id", prefix: "form")
        let followUpID = try body.clientID("follow_up_task_id", prefix: "task")
        if let reason, reason.isEmpty { throw .validation(["body", "reason"], "String should have at least 1 character") }
        let required: [String: Bool] = [
            "title": [.reformulate, .firstStep, .followUp, .returnToNext].contains(type) && title == nil,
            "waiting_for": type == .waiting && waitingFor == nil, "reason": type == .extend && reason == nil,
            "formulation_id": type.decidesOnFormulation && formulationID == nil,
        ]
        if let missing = required.filter(\.value).keys.sorted().first {
            throw .validation(["body", missing], "Decision \(type.rawValue) needs: \(missing).")
        }
        let mintedDecision = decisionID == nil ? mint("decision") : ""
        let mintedTask = type == .followUp && followUpID == nil ? mint("task") : ""
        return try idempotentReview(request, body: body, owner: owner, command: "decide_task:\(id)", now: now) { data throws(FakeHTTPError) in
            // The matching-record check runs first, before the revision and
            // eligibility checks: a retry after the retention carries the
            // stale state of its first delivery (http "Retry after the idempotency retention").
            if let decisionID, let stored = data.review.decisions[decisionID] {
                guard stored.taskID == id, stored.type == type, stored.formulationID == (type.decidesOnFormulation ? formulationID : stored.formulationID)
                else { throw .idConflict }
                return .json(200, try data.decisionResponse(stored))
            }
            var task = try data.task(id)
            let settings = data.clockSettings
            var yielded = false
            if type.decidesOnFormulation, task.state == .someday, let marker = task.parked,
                marker.formulationID.rawValue == formulationID, let from = marker.fromRevision, from <= expected,
                expected <= task.revision, let decidedAt = clientDecidedAt, decidedAt < marker.at
            {
                // The yield rule: reverse the park exactly, then decide.
                do { task.clocked = try FormulationRule.reversePark(task.clocked) } catch { throw .stale("Task", id) }
                yielded = true
            } else {
                guard task.revision == expected else { throw .stale("Task", id) }
            }
            guard type.allowedStates.contains(task.state) else {
                throw .reason(400, "decision_not_allowed", "This decision isn't available for this task's current list.")
            }
            if type.decidesOnFormulation, task.formulation?.id.rawValue != formulationID { throw .stale("Task", id) }
            let before = task
            let newID = FormulationID(newFormulationID ?? ClientID.derived("form", from: "\(id)|\(task.revision + 1)"))
            var decided = task.clocked
            do throws(FormulationRuleError) {
                decided = try FormulationRule.decide(
                    decided, type, settings: settings, now: now, title: title.map(PythonText.strip), reason: reason,
                    newFormulationID: newID
                )
            } catch {
                throw .reason(400, error.reason, "This decision isn't available for this task now.")
            }
            task.clocked = decided
            var substantive: Bool?
            var receiptKey: String?
            var createdID: String?
            switch type {
            case .complete, .cancel:
                task.completedAt = type == .complete ? now : nil
                task.cancelledAt = type == .cancel ? now : nil
                task.waitingFor = nil
                task.waitingSince = nil
            case .waiting:
                task.waitingFor = try Self.waitingFor(waitingFor)
                task.waitingSince = now
            case .someday:
                receiptKey = data.writeReceipt(task, kind: .someday, source: .release, now: now)
            case .returnToNext:
                task.waitingFor = nil
                task.waitingSince = nil
            case .reformulate:
                substantive = FormulationKey.isSubstantive(from: before.title, to: task.title)
            case .firstStep:
                substantive = true
                task.details = "Was: \(before.title)" + (before.details.map { "\n\n" + $0 } ?? "")
            case .extend:
                break
            case .keepWaiting:
                receiptKey = data.writeReceipt(task, kind: .waiting, source: .keep, now: now)
            case .keepSomeday:
                receiptKey = data.writeReceipt(task, kind: .someday, source: .keep, now: now)
            case .followUp:
                if let project = task.projectID, data.projects[project]?.state != .active {
                    throw .reason(400, "project_archived", "Restore this archived project first.")
                }
                let created = followUpID ?? mintedTask
                let row = TaskRow(
                    id: created, title: PythonText.strip(title ?? ""), state: .next, projectID: task.projectID, tagIDs: [],
                    priority: .none, orderKey: data.nextOrderKey(.next), createdAt: now, updatedAt: now, revision: 1,
                    formulation: FormulationClock(id: newID, startedAt: now)
                )
                data.tasks[created] = row
                createdID = created
                receiptKey = data.writeReceipt(task, kind: .waiting, source: .keep, now: now)
            }
            // The rule bumps the revision of every decision that writes the
            // task; keep, follow-up and a cosmetic save write receipts only.
            if task.revision != before.revision { task.updatedAt = now }
            data.tasks[id] = task
            if let key = receiptKey { data.review.receipts[key]?.taskRevision = task.revision }
            var session = sessionID.flatMap { data.review.sessions[$0] }
            if var known = session {
                known.counts[type.countsAs] += 1
                known.qualifying = true
                known.revision += 1
                data.review.sessions[known.id] = known
                session = known
            }
            let decision = FakeDecision(
                id: decisionID ?? mintedDecision, taskID: id,
                type: type, formulationID: formulationID, sessionID: session?.id, decidedAt: now, substantive: substantive,
                stallReason: stallReason, aiUse: aiUse, reasonText: type == .extend ? reason : nil, revisionAfter: task.revision,
                taskBefore: before, createdTaskID: createdID, createdTaskRevision: createdID.map { _ in 1 },
                receiptKey: receiptKey, yielded: yielded
            )
            data.review.decisions[decision.id] = decision
            return .json(200, try data.decisionResponse(decision))
        }
    }

    mutating func undoDecision(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["expected_task_revision"])
        let expected = try body.int("expected_task_revision", minimum: 1)
        return try idempotentReview(request, body: body, owner: owner, command: "undo_decision:\(id)", now: now) { data throws(FakeHTTPError) in
            guard let decision = data.review.decisions[id] else { throw .notFound("review_decision", id) }
            let unavailable = FakeHTTPError.reason(409, "undo_unavailable", "This decision can no longer be undone.")
            let task = try data.task(decision.taskID)
            guard task.revision == decision.revisionAfter, expected == task.revision else { throw unavailable }
            if let created = decision.createdTaskID, let row = data.tasks[created] {
                guard row.revision == decision.createdTaskRevision else { throw unavailable }
                data.tasks[created] = nil
            }
            var restored = decision.taskBefore
            restored.revision = task.revision + 1
            restored.updatedAt = now
            data.tasks[task.id] = restored
            if let key = decision.receiptKey { data.review.receipts[key] = nil }
            if let session = decision.sessionID {
                data.review.sessions[session]?.counts[decision.type.countsAs] -= 1
            }
            data.review.decisions[id] = nil
            return .json(
                200,
                UndoDecisionResponseDTO(
                    task: restored.dto(), undoneDecisionID: id, deletedTaskID: decision.createdTaskID,
                    sessionCounts: decision.sessionID.flatMap { data.review.sessions[$0]?.counts }
                )
            )
        }
    }

    // MARK: Auto-park (http §4)

    mutating func autoPark(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["formulation_id"])
        guard let formulationID = try body.reference("formulation_id", prefix: "form") else {
            throw .validation(["body", "formulation_id"], "Field required", type: "missing")
        }
        let enabled = weeklyReview(owner)
        return try idempotentReview(request, body: body, owner: owner, command: "auto-park-device:\(id)", now: now) { data throws(FakeHTTPError) in
            var task = try data.task(id)
            // The server re-evaluates with its own clock; `applied: false` is a success.
            guard enabled, task.formulation?.id.rawValue == formulationID, data.park(&task, now: now) else {
                return .json(200, AutoParkResponseDTO(applied: false, task: task.dto()))
            }
            data.tasks[id] = task
            return .json(200, AutoParkResponseDTO(applied: true, task: task.dto()))
        }
    }

    // MARK: State and settings (http §5)

    mutating func acknowledgeExplainer(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["time_zone"])
        let zone = try body.string("time_zone", min: 1, max: 64)
        if let zone, TimeZone(identifier: zone) == nil {
            throw .reason(400, "invalid_time_zone", "Unknown time zone.")
        }
        return try idempotentReview(request, body: body, owner: owner, command: "explainer_ack", now: now) { data throws(FakeHTTPError) in
            // First acknowledgement wins; the activation clamp runs in the
            // same step without bumping any task revision. The settings
            // revision does go up, as `_activated_settings` bumps it, so a
            // settings change queued before activation is answered 409.
            if data.review.settings.activatedAt == nil {
                data.review.settings.activatedAt = now
                data.review.settings.revision = (data.review.settings.revision ?? 1) + 1
                if let zone { data.review.settings.timeZone = zone }
                for (taskID, task) in data.tasks where task.state == .next {
                    let id = task.formulation?.id ?? FormulationID(ClientID.derived("form", from: "activation|\(taskID)"))
                    data.tasks[taskID]?.clocked = FormulationRule.activateClock(task.clocked, activatedAt: now, formulationID: id)
                }
            }
            return .json(200, data.reviewState(now: now))
        }
    }

    mutating func updateSettings(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(
            request.body,
            allowing: ["threshold_days", "review_weekday", "review_time", "time_zone", "onboarded", "expected_revision"]
        )
        let threshold = try body.optionalInt("threshold_days")
        if let threshold, !OwnerClockSettings.allowedThresholds.contains(threshold) {
            throw .validation(["body", "threshold_days"], "Input should be 7, 14, 21 or 28", type: "literal_error")
        }
        let weekday = try body.optionalInt("review_weekday")
        if let weekday, !(1...7).contains(weekday) {
            throw .validation(["body", "review_weekday"], "Input should be between 1 and 7", type: "less_than_equal")
        }
        let time = try body.string("review_time")
        if let time, ReviewClock.wallTime(time) == nil {
            throw .validation(["body", "review_time"], "String should match pattern", type: "string_pattern_mismatch")
        }
        let zone = try body.string("time_zone", min: 1, max: 64)
        let onboarded = try body.bool("onboarded")
        let expected = try body.int("expected_revision", minimum: 1)
        if let zone, TimeZone(identifier: zone) == nil { throw .reason(400, "invalid_time_zone", "Unknown time zone.") }
        return try idempotentReview(request, body: body, owner: owner, command: "review_settings", now: now) { data throws(FakeHTTPError) in
            var settings = data.review.settings
            // `ReviewService.update_settings` raises `ConflictError("Review
            // settings", owner_id, "Review settings have newer changes; reload
            // before saving.")`: exactly that message, detail `{resource:
            // "Review settings", id: <owner>}` and no `reason` (golden trace
            // TR-005). `APIError.conflictKind` recognises it as stale.
            guard settings.revision == expected else {
                throw .conflict("Review settings", owner, "Review settings have newer changes; reload before saving.")
            }
            var changed = false
            if let threshold, threshold != settings.thresholdDays {
                settings.thresholdDays = threshold
                let floor = now.addingTimeInterval(FormulationRule.thresholdChangeFloor)
                settings.ownerParkFloorAt = max(settings.ownerParkFloorAt ?? floor, floor)
                changed = true
            }
            if let weekday, weekday != settings.reviewWeekday {
                settings.reviewWeekday = weekday
                changed = true
            }
            if let time, time != settings.reviewTime {
                settings.reviewTime = time
                changed = true
            }
            if let zone, zone != settings.timeZone {
                settings.timeZone = zone
                changed = true
                for (id, task) in data.tasks where task.state == .next {
                    data.tasks[id]?.clocked = FormulationRule.raiseDueFloor(task.clocked, now: now)
                }
            }
            if onboarded == true, settings.onboardedAt == nil {
                settings.onboardedAt = now
                changed = true
            }
            if changed { settings.revision = (settings.revision ?? 1) + 1 }
            data.review.settings = settings
            return .json(200, data.settingsDTO)
        }
    }

    mutating func acknowledgeParks(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["items"])
        let items = body.fields["items"].flatMap { value -> [JSONValue]? in
            if case .array(let items) = value { items } else { nil }
        } ?? []
        return try idempotentReview(request, body: body, owner: owner, command: "park_ack", now: now) { data throws(FakeHTTPError) in
            for item in items {
                guard let task = item["task_id"]?.stringValue, let form = item["formulation_id"]?.stringValue else { continue }
                data.review.parkAcks["\(task)|\(form)"]?.seenAt = now
            }
            return .noContent()
        }
    }

    // MARK: Sessions (http §6)

    mutating func startSession(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["id", "mode", "entry", "origin", "skip_steps", "replace_open"])
        let id = try body.clientID("id", prefix: "review")
        guard let mode = try body.value("mode", as: ReviewMode.self), let entry = try body.value("entry", as: ReviewEntry.self),
            let origin = try body.value("origin", as: ReviewOrigin.self)
        else { throw .validation(["body"], "Field required", type: "missing") }
        let skip = (try body.stringList("skip_steps") ?? []).compactMap(ReviewStep.init(rawValue:))
        let replaceOpen = try body.bool("replace_open") ?? false
        let minted = mint("review")
        return try idempotentReview(request, body: body, owner: owner, command: "review_session", now: now) { data throws(FakeHTTPError) in
            if let id, let stored = data.review.sessions[id] {
                guard stored.mode == mode, stored.origin == origin else { throw .idConflict }
                return .json(201, stored.dto)
            }
            if let open = data.review.sessions.values.first(where: { $0.status == .open }) {
                guard replaceOpen else { throw .reason(409, "open_session_exists", "A review is already open.") }
                data.review.sessions[open.id]?.end(.replace, at: now)
            }
            var steps: [ReviewStep: StepStatus] = [:]
            for step in mode.steps { steps[step] = skip.contains(step) ? .skipped : .pending }
            let session = FakeSession(
                id: id ?? minted, mode: mode, entry: entry, origin: origin, status: .open, startedAt: now, lastActivityAt: now,
                currentStep: mode.steps.first { !skip.contains($0) }, steps: steps
            )
            data.review.sessions[session.id] = session
            return .json(201, session.dto)
        }
    }

    mutating func progressSession(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(
            request.body,
            allowing: [
                "progress_id", "current_step", "step", "active_seconds", "set_aside_task_id", "inbox_processed_delta",
                "snapshot_decision_queue",
            ]
        )
        guard let progressID = try body.clientID("progress_id", prefix: "progress") else {
            throw .validation(["body", "progress_id"], "Field required", type: "missing")
        }
        let currentStep = try body.value("current_step", as: ReviewStep.self)
        let step = body.fields["step"]
        let active = body.fields["active_seconds"]
        let setAside = try body.reference("set_aside_task_id", prefix: "task")
        let delta = try body.optionalInt("inbox_processed_delta")
        let digest = body.progressDigest
        return try idempotentReview(request, body: body, owner: owner, command: "review_progress:\(id)", now: now) { data throws(FakeHTTPError) in
            guard var session = data.review.sessions[id] else { throw .notFound("review_session", id) }
            if let known = session.appliedProgress[progressID] {
                // Replay-safe at any age: the same change is merged once.
                guard known == digest else { throw .idConflict }
                return .json(200, session.dto)
            }
            guard session.status == .open else { return .json(200, session.dto) }
            if let currentStep { session.currentStep = currentStep }
            if let code = step?["code"]?.stringValue.flatMap(ReviewStep.init(rawValue:)),
                let status = step?["status"]?.stringValue.flatMap(StepStatus.init(rawValue:))
            {
                session.steps[code] = (session.steps[code] ?? .pending).merged(with: status)
                // E3: a finished step qualifies only when it had nothing to decide.
                if status == .finished, data.hasNothingToDecide(code, now: now) { session.qualifying = true }
            }
            if let code = active?["code"]?.stringValue.flatMap(ReviewStep.init(rawValue:)),
                case .number(let seconds)? = active?["seconds"]
            {
                session.activeSeconds[code, default: 0] += Int(seconds)
            }
            if let setAside, data.tasks[setAside]?.state.isOpen == true, !session.setAside.contains(setAside) {
                session.setAside.append(setAside)
            }
            if let delta {
                session.counts[.inboxProcessed] = max(0, session.counts[.inboxProcessed] + delta)
                if delta > 0 { session.qualifying = true }
            }
            session.appliedProgress[progressID] = digest
            session.lastActivityAt = now
            session.revision += 1
            data.review.sessions[id] = session
            return .json(200, session.dto)
        }
    }

    mutating func finishSession(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["clear_start"])
        let clearStart = try body.value("clear_start", as: ClearStart.self)
        return try idempotentReview(request, body: body, owner: owner, command: "review_finish:\(id)", now: now) { data throws(FakeHTTPError) in
            guard var session = data.review.sessions[id] else { throw .notFound("review_session", id) }
            if session.status == .open {
                session.end(.finish, at: now)
                session.lastActivityAt = now
                session.clearStart = clearStart
                data.review.sessions[id] = session
            }
            return .json(200, session.dto)
        }
    }

    // MARK: Bulk releases (http §6)

    mutating func bulkRelease(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["id", "kind", "session_id", "items"])
        let id = try body.clientID("id", prefix: "bulk")
        guard let kind = try body.value("kind", as: BulkReleaseKindCode.self) else {
            throw .validation(["body", "kind"], "Field required", type: "missing")
        }
        let items: [(String, Int)] = (body.fields["items"].flatMap { value -> [JSONValue]? in
            if case .array(let items) = value { items } else { nil }
        } ?? []).compactMap { item in
            guard let task = item["task_id"]?.stringValue, case .number(let revision)? = item["expected_revision"] else {
                return nil
            }
            return (task, Int(revision))
        }
        let minted = mint("bulk")
        return try idempotentReview(request, body: body, owner: owner, command: "bulk_release", now: now) { data throws(FakeHTTPError) in
            if let id, let stored = data.review.bulkReleases[id] {
                guard stored.kind == kind, stored.taskIDs == Set(items.map(\.0)) else { throw .idConflict }
                return .json(200, stored.response)
            }
            let settings = data.clockSettings
            var record = FakeBulkRelease(id: id ?? minted, kind: kind, taskIDs: Set(items.map(\.0)), released: [], skipped: [])
            for (taskID, revision) in items {
                guard var task = data.tasks[taskID] else {
                    record.skipped.append(BulkSkippedItemDTO(taskID: taskID, reason: "not_eligible"))
                    continue
                }
                let eligible =
                    switch kind {
                    case .restart: task.state == .next && FormulationRule.isRestartEligible(task.clocked, settings: settings, now: now)
                    case .inboxRemainder: task.state == .inbox
                    }
                guard eligible else {
                    record.skipped.append(BulkSkippedItemDTO(taskID: taskID, reason: "not_eligible"))
                    continue
                }
                guard task.revision == revision else {
                    record.skipped.append(BulkSkippedItemDTO(taskID: taskID, reason: "stale"))
                    continue
                }
                let previous = task.state
                let (released, snapshot) = FormulationRule.release(task.clocked, settings: settings, now: now)
                task.clocked = released
                task.waitingFor = nil
                task.waitingSince = nil
                task.updatedAt = now
                data.tasks[taskID] = task
                _ = data.writeReceipt(task, kind: .someday, source: .release, now: now)
                record.released.append(.init(taskID: taskID, revisionAfter: task.revision, previousState: previous, clockBefore: snapshot))
            }
            data.review.bulkReleases[record.id] = record
            return .json(200, record.response)
        }
    }

    mutating func undoBulkRelease(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = RequestBody(fields: [:])
        return try idempotentReview(request, body: body, owner: owner, command: "undo_bulk_release:\(id)", now: now) { data throws(FakeHTTPError) in
            guard var record = data.review.bulkReleases[id] else { throw .notFound("review_bulk_release", id) }
            if let result = record.undoResult { return .json(200, result) }
            var restored: [String] = []
            var skipped: [BulkSkippedItemDTO] = []
            for item in record.released {
                guard var task = data.tasks[item.taskID], task.revision == item.revisionAfter else {
                    skipped.append(BulkSkippedItemDTO(taskID: item.taskID, reason: "stale"))
                    continue
                }
                task.clocked = FormulationRule.undoRelease(task.clocked, to: item.previousState, restoring: item.clockBefore)
                task.updatedAt = now
                data.tasks[item.taskID] = task
                data.review.receipts["\(item.taskID)|someday"] = nil
                restored.append(item.taskID)
            }
            let result = BulkReleaseUndoResponseDTO(restored: restored, skipped: skipped)
            record.undoResult = result
            data.review.bulkReleases[id] = record
            return .json(200, result)
        }
    }

    // MARK: Navigator consent (http §7)

    static let navigatorProvider = "openai"
    static let consentTextVersion = 1

    func navigatorStatus(_ owner: String) -> NavigatorStatusDTO {
        let consent = data(owner).review.consents[Self.navigatorProvider]
        return NavigatorStatusDTO(
            provider: Self.navigatorProvider,
            consent: consent?.grantedAt.map {
                NavigatorConsentDTO(grantedAt: $0, revokedAt: consent?.revokedAt, consentTextVersion: consent?.consentTextVersion ?? 1)
            },
            consentCurrent: consent?.allowsCloud == true && consent?.consentTextVersion == Self.consentTextVersion,
            consentTextVersion: Self.consentTextVersion, available: true
        )
    }

    mutating func grantConsent(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["provider", "consent_text_version"])
        let provider = try body.string("provider", required: true) ?? ""
        let version = try body.int("consent_text_version", minimum: 1)
        guard provider == Self.navigatorProvider else { throw .reason(400, "provider_mismatch", "Unknown provider.") }
        guard version == Self.consentTextVersion else { throw .reason(400, "consent_text_outdated", "Outdated consent text.") }
        return try idempotentReview(request, body: body, owner: owner, command: "navigator_consent", now: now) { data throws(FakeHTTPError) in
            if data.review.consents[provider]?.allowsCloud != true {
                data.review.consents[provider] = NavigatorConsent(provider: provider, grantedAt: now, consentTextVersion: version)
            }
            return .json(200, ["ok": true])
        }
    }

    mutating func revokeConsent(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        try idempotentReview(request, body: RequestBody(fields: [:]), owner: owner, command: "navigator_revoke", now: now) { data throws(FakeHTTPError) in
            if data.review.consents[Self.navigatorProvider]?.allowsCloud == true {
                data.review.consents[Self.navigatorProvider]?.revokedAt = now
            }
            return .noContent()
        }
    }
}
