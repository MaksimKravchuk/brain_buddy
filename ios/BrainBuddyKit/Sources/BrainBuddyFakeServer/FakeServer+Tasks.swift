import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// Tasks (`TaskService.create_task`, `update_task`, `transition_task`, `get_task_detail`).
extension ServerState {
    static let openStates: Set<String> = ["inbox", "next", "waiting", "someday"]

    func getTask(_ id: String, owner: String) throws(FakeHTTPError) -> Reply {
        let data = data(owner)
        return .json(200, data.detailDTO(try data.task(id)))
    }

    mutating func createTask(_ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(
            request.body,
            allowing: [
                "title", "details", "state", "project_id", "tag_ids", "due_date", "priority", "waiting_for",
                "source_capture_ids",
            ]
        )
        let title = try body.string("title", required: true, min: 1, max: GTDLimits.title) ?? ""
        let details = try body.string("details", max: GTDLimits.details)
        let state = try body.value("state", as: TaskState.self, allowed: Self.openStates) ?? .inbox
        let projectID = try body.string("project_id")
        let tagIDs = try body.stringList("tag_ids") ?? []
        let dueDate = try body.day("due_date")
        let priority = try body.value("priority", as: TaskPriority.self) ?? TaskPriority.none
        let waitingFor = try body.string("waiting_for", max: GTDLimits.waitingFor)
        let sourceCaptures = try body.stringList("source_capture_ids") ?? []
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "create_task"
        let fingerprint = body.fingerprint(command: command)
        if case .task(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(201, stored.dto())
        }
        try data.assertActiveReferences(project: projectID, tags: tagIDs)
        let note = try state == .waiting ? Self.waitingFor(waitingFor) : nil
        guard sourceCaptures.isEmpty else {
            throw .rejected("source_capture_ids require owner-scoped Capture validation.")
        }
        let task = TaskRow(
            id: mint("task"), title: title, details: details, state: state, projectID: projectID, tagIDs: tagIDs,
            dueDate: dueDate, priority: priority, waitingFor: note, waitingSince: note == nil ? nil : now,
            orderKey: data.nextOrderKey(state), createdAt: now, updatedAt: now, revision: 1
        )
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .task(task), now: now)
        data.tasks[task.id] = task
        commit(data, owner: owner)
        return .json(201, task.dto())
    }

    /// `PATCH /tasks/{id}`: omitted keys are kept, `null` clears (title and
    /// priority cannot be null), and the result's references must be active.
    /// There is no "nothing changed" check: every accepted PATCH bumps the revision.
    mutating func updateTask(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(
            request.body,
            allowing: [
                "title", "details", "project_id", "tag_ids", "due_date", "priority", "waiting_for", "expected_revision",
            ]
        )
        let title = try body.string("title", min: 1, max: GTDLimits.title)
        let details = try body.string("details", max: GTDLimits.details)
        let projectID = try body.string("project_id")
        let tagIDs = try body.stringList("tag_ids")
        let dueDate = try body.day("due_date")
        let priority = try body.value("priority", as: TaskPriority.self)
        let waitingFor = try body.string("waiting_for", max: GTDLimits.waitingFor)
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "update_task:\(id)"
        let fingerprint = body.fingerprint(command: command)
        if case .task(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, stored.dto())
        }
        var task = try data.task(id)
        guard task.revision == expected else { throw .stale("Task", id) }
        if body.has("title"), title == nil { throw .rejected("Task title cannot be null.") }
        if body.has("priority"), priority == nil { throw .rejected("Task priority cannot be null.") }
        if body.has("waiting_for") {
            guard task.state == .waiting else { throw .rejected("waiting_for can only be edited on Waiting tasks.") }
            task.waitingFor = try Self.waitingFor(waitingFor)
        }
        if body.has("project_id") { task.projectID = projectID }
        if body.has("tag_ids") { task.tagIDs = tagIDs ?? [] }
        try data.assertActiveReferences(project: task.projectID, tags: task.tagIDs)
        if let title { task.title = title }
        if body.has("details") { task.details = details }
        if body.has("due_date") { task.dueDate = dueDate }
        if let priority { task.priority = priority }
        task.updatedAt = now
        task.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .task(task), now: now)
        data.tasks[id] = task
        commit(data, owner: owner)
        return .json(200, task.dto())
    }

    /// `POST /tasks/{id}/transitions`: move / complete / cancel / reopen, with
    /// the server's own messages. Order, project, tags, due date, priority and
    /// notes never change.
    mutating func transitionTask(_ id: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError)
        -> Reply
    {
        let body = try RequestBody(request.body, allowing: ["action", "to_state", "waiting_for", "expected_revision"])
        guard let action = try body.value("action", as: TaskTransitionAction.self) else {
            throw .validation(["body", "action"], "Field required", type: "missing")
        }
        let toState = try body.value("to_state", as: TaskState.self, allowed: Self.openStates)
        let waitingFor = try body.string("waiting_for", max: GTDLimits.waitingFor)
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "transition_task:\(id)"
        let fingerprint = body.fingerprint(command: command)
        if case .task(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, stored.dto())
        }
        var task = try data.task(id)
        guard task.revision == expected else { throw .stale("Task", id) }
        switch action {
        case .complete, .cancel:
            guard task.state.isOpen else {
                throw .rejected(action == .complete ? "Only open tasks can be completed." : "Only open tasks can be cancelled.")
            }
            task.state = action == .complete ? .completed : .cancelled
            task.completedAt = action == .complete ? now : nil
            task.cancelledAt = action == .cancel ? now : nil
            task.waitingFor = nil
            task.waitingSince = nil
        case .reopen:
            guard task.state.isTerminal, let toState else {
                throw .rejected("Reopen requires a terminal task and an open destination.")
            }
            let note = try toState == .waiting ? Self.waitingFor(waitingFor) : nil
            task.state = toState
            task.completedAt = nil
            task.cancelledAt = nil
            task.waitingFor = note
            task.waitingSince = note == nil ? nil : now
        case .move:
            guard task.state.isOpen, let toState else { throw .rejected("Move requires an open task and destination.") }
            guard task.state != toState else { throw .rejected("Move requires a different open destination.") }
            let note = try toState == .waiting ? Self.waitingFor(waitingFor) : nil
            task.state = toState
            task.waitingFor = note
            task.waitingSince = note == nil ? nil : now
        }
        task.updatedAt = now
        task.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .task(task), now: now)
        data.tasks[id] = task
        commit(data, owner: owner)
        return .json(200, task.dto())
    }

    /// `TaskService._waiting_for`: trimmed and non-blank.
    static func waitingFor(_ raw: String?) throws(FakeHTTPError) -> String {
        let value = PythonText.strip(raw ?? "")
        guard !value.isEmpty else { throw .rejected("Waiting tasks require waiting_for.") }
        return value
    }
}

extension OwnerData {
    /// `TaskRepository.next_order_key`: one past the highest key in the state.
    func nextOrderKey(_ state: TaskState) -> Int {
        (tasks.values.filter { $0.state == state }.map(\.orderKey).max() ?? -1) + 1
    }

    /// `TaskService._assert_active_references`.
    func assertActiveReferences(project: String?, tags tagIDs: [String]) throws(FakeHTTPError) {
        if let project {
            guard try self.project(project).state == .active else { throw .rejected("Task project must be active.") }
        }
        guard Set(tagIDs).count == tagIDs.count else { throw .rejected("Task contexts/tags cannot contain duplicates.") }
        for id in tagIDs {
            guard try tag(id).state == .active else {
                throw .rejected("Task contexts must be active; task tags must be active.")
            }
        }
    }
}
