import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// What a 2xx answered with.
enum ServerRecord: Sendable {
    case project(ProjectDTO)
    case tag(TagDTO)
    case task(TaskDTO)
    case subtask(SubtaskDTO)
    case comment(CommentDTO)
    // Spec 020.
    case decision(DecisionResponseDTO)
    case undoneDecision(UndoDecisionResponseDTO)
    case autoPark(AutoParkResponseDTO)
    case reviewState(ReviewStateDTO)
    case reviewSettings(ReviewSettingsDTO)
    case session(SessionDTO)
    case bulkRelease(BulkReleaseResponseDTO)
    case bulkUndo(BulkReleaseUndoResponseDTO)
    /// A 2xx without a body to keep (204), or a 404 that means the goal
    /// already holds (an Undo already undone).
    case accepted
}

/// One queued command resolved against the base: server ids in place of
/// client ids, `expected_revision` from the base record, and the values the
/// reducer stored rather than the raw input (titles trimmed, empty notes
/// cleared), so the server ends up with what the device shows.
enum PlannedRequest: Sendable {
    case createProject(name: String, color: String?, desiredOutcome: String?)
    case updateProject(id: String, name: String?, color: FieldChange<String>, desiredOutcome: FieldChange<String>, revision: Int)
    case archiveProject(id: String, revision: Int)
    case unarchiveProject(id: String, revision: Int)
    case createTag(name: String)
    case renameTag(id: String, name: String, revision: Int)
    case deleteTag(id: String, revision: Int)
    case createTask(TaskCreateBody)
    case updateTask(id: String, TaskUpdateBody)
    case transitionTask(id: String, TaskTransitionBody)
    case createSubtask(taskID: String, title: String)
    case updateSubtask(taskID: String, subtaskID: String, title: String, revision: Int)
    case transitionSubtask(taskID: String, subtaskID: String, action: SubtaskTransitionAction, revision: Int)
    case createComment(taskID: String, body: String)
    case updateComment(taskID: String, commentID: String, body: String, revision: Int)
    // Spec 020.
    case decide(taskID: String, DecisionRequestBody)
    case undoDecision(id: String, expectedTaskRevision: Int)
    case autoPark(taskID: String, formulationID: String)
    case acknowledgeExplainer(timeZone: String?)
    case updateReviewSettings(ReviewSettingsUpdateBody)
    case acknowledgeParks([ParkAcknowledgementItem])
    case startSession(SessionStartBody)
    case progressSession(id: String, SessionProgressBody)
    case finishSession(id: String, clearStart: ClearStart?)
    case bulkRelease(BulkReleaseBody)
    case undoBulkRelease(id: String)
    case grantNavigatorConsent(provider: String, version: Int)
    case revokeNavigatorConsent

    /// Sends the request with `key` as its `Idempotency-Key`.
    func send(with client: BrainBuddyAPIClient, key: UUID) async throws(APIError) -> ServerRecord {
        switch self {
        case .createProject(let name, let color, let desiredOutcome):
            return .project(
                try await client.createProject(
                    name: name, color: color, desiredOutcome: desiredOutcome, idempotencyKey: key
                )
            )
        case .updateProject(let id, let name, let color, let desiredOutcome, let revision):
            return .project(
                try await client.updateProject(
                    id: id, name: name, color: color, desiredOutcome: desiredOutcome, expectedRevision: revision,
                    idempotencyKey: key
                )
            )
        case .archiveProject(let id, let revision):
            return .project(try await client.archiveProject(id: id, expectedRevision: revision, idempotencyKey: key))
        case .unarchiveProject(let id, let revision):
            return .project(try await client.unarchiveProject(id: id, expectedRevision: revision, idempotencyKey: key))
        case .createTag(let name):
            return .tag(try await client.createTag(name: name, idempotencyKey: key))
        case .renameTag(let id, let name, let revision):
            return .tag(try await client.updateTag(id: id, name: name, expectedRevision: revision, idempotencyKey: key))
        case .deleteTag(let id, let revision):
            return .tag(try await client.deleteTag(id: id, expectedRevision: revision, idempotencyKey: key))
        case .createTask(let body):
            return .task(try await client.createTask(body, idempotencyKey: key))
        case .updateTask(let id, let body):
            return .task(try await client.updateTask(id: id, body, idempotencyKey: key))
        case .transitionTask(let id, let body):
            return .task(try await client.transitionTask(id: id, body, idempotencyKey: key))
        case .createSubtask(let taskID, let title):
            return .subtask(try await client.createSubtask(taskID: taskID, title: title, idempotencyKey: key))
        case .updateSubtask(let taskID, let subtaskID, let title, let revision):
            return .subtask(
                try await client.updateSubtask(
                    taskID: taskID, subtaskID: subtaskID, title: title, expectedRevision: revision, idempotencyKey: key
                )
            )
        case .transitionSubtask(let taskID, let subtaskID, let action, let revision):
            return .subtask(
                try await client.transitionSubtask(
                    taskID: taskID, subtaskID: subtaskID, action: action, expectedRevision: revision, idempotencyKey: key
                )
            )
        case .createComment(let taskID, let body):
            return .comment(try await client.createComment(taskID: taskID, body: body, idempotencyKey: key))
        case .updateComment(let taskID, let commentID, let body, let revision):
            return .comment(
                try await client.updateComment(
                    taskID: taskID, commentID: commentID, body: body, expectedRevision: revision, idempotencyKey: key
                )
            )
        case .decide(let taskID, let body):
            return .decision(try await client.decide(taskID: taskID, body, idempotencyKey: key))
        case .undoDecision(let id, let revision):
            return .undoneDecision(try await client.undoDecision(id: id, expectedTaskRevision: revision, idempotencyKey: key))
        case .autoPark(let taskID, let formulationID):
            return .autoPark(try await client.autoPark(taskID: taskID, formulationID: formulationID, idempotencyKey: key))
        case .acknowledgeExplainer(let timeZone):
            return .reviewState(try await client.acknowledgeExplainer(timeZone: timeZone, idempotencyKey: key))
        case .updateReviewSettings(let body):
            return .reviewSettings(try await client.updateReviewSettings(body, idempotencyKey: key))
        case .acknowledgeParks(let items):
            try await client.acknowledgeParks(items, idempotencyKey: key)
            return .accepted
        case .startSession(let body):
            return .session(try await client.startSession(body, idempotencyKey: key))
        case .progressSession(let id, let body):
            return .session(try await client.progressSession(id: id, body, idempotencyKey: key))
        case .finishSession(let id, let clearStart):
            return .session(try await client.finishSession(id: id, clearStart: clearStart, idempotencyKey: key))
        case .bulkRelease(let body):
            return .bulkRelease(try await client.bulkRelease(body, idempotencyKey: key))
        case .undoBulkRelease(let id):
            return .bulkUndo(try await client.undoBulkRelease(id: id, idempotencyKey: key))
        case .grantNavigatorConsent(let provider, let version):
            try await client.grantNavigatorConsent(provider: provider, consentTextVersion: version, idempotencyKey: key)
            return .accepted
        case .revokeNavigatorConsent:
            try await client.revokeNavigatorConsent(idempotencyKey: key)
            return .accepted
        }
    }
}

/// Builds the request for the first queued operation. Everything it needs
/// is in the base: the outbox is ordered, so whatever a command references
/// was acknowledged before the command reached the front.
enum PushPlanner {
    /// A reference the base cannot resolve (it should not happen; the
    /// operation is set aside rather than blocking the queue).
    struct Unresolvable: Error, Sendable {
        var message = "This change refers to an item that isn't on the server."
    }

    /// The request for `operation` (its issue time is a decision's `client_decided_at`).
    static func plan(_ operation: PendingOperation, base: GTDState) throws(Unresolvable) -> PlannedRequest {
        if let review = try planReview(operation, base: base) { return review }
        return try plan(operation.command, base: base)
    }

    static func plan(_ command: GTDCommand, base: GTDState) throws(Unresolvable) -> PlannedRequest {
        let resolver = Resolver(base: base)
        switch command {
        case .createProject(let create):
            return .createProject(
                name: create.name, color: create.color, desiredOutcome: outcome(create.desiredOutcome)
            )
        case .updateProject(let update):
            let project = try resolver.project(update.projectID)
            return .updateProject(
                id: project.id, name: update.name, color: update.color, desiredOutcome: .unchanged,
                revision: project.revision
            )
        case .setProjectOutcome(let id, let value):
            let project = try resolver.project(id)
            return .updateProject(
                id: project.id, name: nil, color: .unchanged,
                desiredOutcome: outcome(value).map { .set($0) } ?? .clear, revision: project.revision
            )
        case .archiveProject(let id):
            let project = try resolver.project(id)
            return .archiveProject(id: project.id, revision: project.revision)
        case .unarchiveProject(let id):
            let project = try resolver.project(id)
            return .unarchiveProject(id: project.id, revision: project.revision)
        case .createTag(let create):
            return .createTag(name: create.name)
        case .renameTag(let rename):
            let tag = try resolver.tag(rename.tagID)
            return .renameTag(id: tag.id, name: rename.name, revision: tag.revision)
        case .deleteTag(let id):
            let tag = try resolver.tag(id)
            return .deleteTag(id: tag.id, revision: tag.revision)
        case .createTask(var create):
            create.title = NameNormalizer.stripped(create.title)
            if create.details?.isEmpty == true { create.details = nil }
            do {
                return .createTask(
                    try TaskCreateBody(create, projectServerID: resolver.projectID, tagServerID: resolver.tagID)
                )
            } catch {
                throw Unresolvable()
            }
        case .updateTask(let update):
            let task = try resolver.task(update.taskID)
            var changes = update.changes
            if case .set(let title) = changes.title { changes.title = .set(NameNormalizer.stripped(title)) }
            if changes.details == .set("") { changes.details = .clear }
            do {
                var body = try TaskUpdateBody(
                    changes: changes, expectedRevision: task.revision, projectServerID: resolver.projectID,
                    tagServerID: resolver.tagID
                )
                if changes.title.isChanged { body.newFormulationID = update.newFormulationID?.rawValue }
                return .updateTask(id: task.id, body)
            } catch {
                throw Unresolvable()
            }
        case .transitionTask(let transition):
            let task = try resolver.task(transition.taskID)
            return .transitionTask(id: task.id, TaskTransitionBody(transition, expectedRevision: task.revision))
        case .createSubtask(let create):
            return .createSubtask(
                taskID: try resolver.task(create.taskID).id, title: NameNormalizer.stripped(create.title)
            )
        case .updateSubtask(let update):
            let task = try resolver.task(update.taskID)
            let subtask = try resolver.subtask(update.subtaskID, in: update.taskID)
            return .updateSubtask(
                taskID: task.id, subtaskID: subtask.id, title: NameNormalizer.stripped(update.title),
                revision: subtask.revision
            )
        case .transitionSubtask(let transition):
            let task = try resolver.task(transition.taskID)
            let subtask = try resolver.subtask(transition.subtaskID, in: transition.taskID)
            return .transitionSubtask(
                taskID: task.id, subtaskID: subtask.id, action: transition.action, revision: subtask.revision
            )
        case .createComment(let create):
            return .createComment(taskID: try resolver.task(create.taskID).id, body: create.body)
        case .updateComment(let update):
            let task = try resolver.task(update.taskID)
            let comment = try resolver.comment(update.commentID, in: update.taskID)
            return .updateComment(taskID: task.id, commentID: comment.id, body: update.body, revision: comment.revision)
        case .decideTask, .undoDecision, .autoParkTask, .bulkRelease, .undoBulkRelease, .review:
            // Planned by `planReview(_:base:)`, which also needs the issue time.
            throw Unresolvable()
        }
    }

    /// The spec 020 requests: server ids for task references, the client's
    /// own ids for decisions, sessions, bulk releases and formulations (the
    /// server adopts them), revisions from the base.
    static func planReview(_ operation: PendingOperation, base: GTDState) throws(Unresolvable) -> PlannedRequest? {
        let resolver = Resolver(base: base)
        switch operation.command {
        case .decideTask(let decide):
            let task = try resolver.task(decide.taskID)
            let body = DecisionRequestBody(
                decisionID: decide.decisionID.rawValue, type: decide.type, expectedRevision: task.revision,
                formulationID: decide.formulationID?.rawValue, stallReason: decide.stallReason,
                title: decide.title.map(NameNormalizer.stripped), waitingFor: decide.waitingFor.map(NameNormalizer.stripped),
                reason: decide.reason.map(NameNormalizer.stripped), sessionID: decide.sessionID?.rawValue, aiUse: decide.aiUse,
                navigatorRequestID: decide.navigatorRequestID, clientDecidedAt: operation.issuedAt,
                newFormulationID: decide.newFormulationID?.rawValue, followUpTaskID: decide.followUpTaskID?.rawValue
            )
            return .decide(taskID: task.id, body)
        case .undoDecision(let id):
            guard let decision = base.review.decisions[id] else { throw Unresolvable() }
            return .undoDecision(id: id.rawValue, expectedTaskRevision: try resolver.task(decision.taskID).revision)
        case .autoParkTask(let park):
            return .autoPark(taskID: try resolver.task(park.taskID).id, formulationID: park.formulationID.rawValue)
        case .bulkRelease(let release):
            let items = release.taskIDs.compactMap { id -> BulkReleaseItemBody? in
                guard let task = try? resolver.task(id) else { return nil }
                return BulkReleaseItemBody(taskID: task.id, expectedRevision: task.revision)
            }
            return .bulkRelease(
                BulkReleaseBody(id: release.bulkID.rawValue, kind: release.kind, sessionID: release.sessionID?.rawValue, items: items)
            )
        case .undoBulkRelease(let id):
            return .undoBulkRelease(id: id.rawValue)
        case .review(let command):
            switch command {
            case .acknowledgeExplainer(let timeZone):
                return .acknowledgeExplainer(timeZone: timeZone)
            case .updateSettings(let change):
                return .updateReviewSettings(ReviewSettingsUpdateBody(change, expectedRevision: base.review.settings.revision ?? 1))
            case .acknowledgeParks(let acks):
                // A task the server does not hold is ignored there anyway.
                let items = acks.compactMap { ack -> ParkAcknowledgementItem? in
                    guard let task = try? resolver.task(ack.taskID) else { return nil }
                    return ParkAcknowledgementItem(taskID: task.id, formulationID: ack.formulationID.rawValue)
                }
                return .acknowledgeParks(items)
            case .startSession(let start):
                return .startSession(
                    SessionStartBody(
                        id: start.sessionID.rawValue, mode: start.mode, entry: start.entry, origin: start.origin,
                        skipSteps: start.skipSteps, replaceOpen: true
                    )
                )
            case .progressSession(let progress):
                var body = SessionProgressBody(
                    progressID: progress.progressID.rawValue, currentStep: progress.currentStep,
                    inboxProcessedDelta: progress.inboxProcessedDelta,
                    snapshotDecisionQueue: progress.snapshotDecisionQueue ? true : nil
                )
                if let step = progress.step, let status = progress.stepStatus {
                    body.step = StepUpdateBody(code: step, status: status)
                }
                if let step = progress.activeStep, let seconds = progress.activeSeconds {
                    body.activeSeconds = ActiveSecondsBody(code: step, seconds: seconds)
                }
                body.setAsideTaskID = progress.setAsideTaskID.flatMap { try? resolver.task($0).id }
                return .progressSession(id: progress.sessionID.rawValue, body)
            case .finishSession(let finish):
                return .finishSession(id: finish.sessionID.rawValue, clearStart: finish.clearStart)
            case .grantNavigatorConsent(let provider, let version):
                return .grantNavigatorConsent(provider: provider, version: version)
            case .revokeNavigatorConsent:
                return .revokeNavigatorConsent
            }
        default:
            return nil
        }
    }

    /// The outcome as the reducer stored it: trimmed, and nil when blank.
    private static func outcome(_ raw: String?) -> String? {
        let value = NameNormalizer.stripped(raw ?? "")
        return value.isEmpty ? nil : value
    }

    /// Server id and revision of base records.
    private struct Resolver {
        let base: GTDState

        struct Reference {
            var id: String
            var revision: Int
        }

        private static func reference(_ record: (any ServerBacked)?) throws(Unresolvable) -> Reference {
            guard let record, let id = record.serverID, let revision = record.serverRevision else { throw Unresolvable() }
            return Reference(id: id, revision: revision)
        }

        func task(_ id: TaskID) throws(Unresolvable) -> Reference { try Self.reference(base.tasks[id]) }
        func project(_ id: ProjectID) throws(Unresolvable) -> Reference { try Self.reference(base.projects[id]) }
        func tag(_ id: TagID) throws(Unresolvable) -> Reference { try Self.reference(base.tags[id]) }

        func subtask(_ id: SubtaskID, in task: TaskID) throws(Unresolvable) -> Reference {
            try Self.reference(base.tasks[task]?.subtasks.first { $0.id == id })
        }

        func comment(_ id: CommentID, in task: TaskID) throws(Unresolvable) -> Reference {
            try Self.reference(base.tasks[task]?.comments.first { $0.id == id })
        }

        func projectID(_ id: ProjectID) throws(Unresolvable) -> String { try project(id).id }
        func tagID(_ id: TagID) throws(Unresolvable) -> String { try tag(id).id }
    }
}
