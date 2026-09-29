import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// Subtasks and comments. None of these writes touches the parent task (its
/// revision and `updated_at` stay), which is why clients hydrate children
/// per task. A replayed key answers with the *current* child when it is at
/// least as new as the stored one (`_subtask_result`, `_comment_result`).
extension ServerState {
    // MARK: - Subtasks

    mutating func createSubtask(_ taskID: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError)
        -> Reply
    {
        let body = try RequestBody(request.body, allowing: ["title"])
        let title = try body.string("title", required: true, min: 1, max: GTDLimits.title) ?? ""
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        _ = try data.task(taskID)
        let command = "create_subtask:\(taskID)"
        let fingerprint = body.fingerprint(command: command)
        if case .subtask(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(201, data.current(stored).dto)
        }
        let siblings = data.subtasks.values.filter { $0.taskID == taskID }
        let subtask = SubtaskRow(
            id: mint("subtask"), taskID: taskID, title: title, orderKey: (siblings.map(\.orderKey).max() ?? -1) + 1,
            state: .open, createdAt: now, updatedAt: now, revision: 1
        )
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .subtask(subtask), now: now)
        data.subtasks[subtask.id] = subtask
        commit(data, owner: owner)
        return .json(201, subtask.dto)
    }

    mutating func updateSubtask(
        _ taskID: String, _ subtaskID: String, _ request: HTTPRequest, owner: String, now: Date
    ) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["title", "expected_revision"])
        let title = try body.string("title", min: 1, max: GTDLimits.title)
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "update_subtask:\(taskID):\(subtaskID)"
        let fingerprint = body.fingerprint(command: command)
        if case .subtask(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.current(stored).dto)
        }
        _ = try data.task(taskID)
        var subtask = try data.subtask(subtaskID, of: taskID)
        guard subtask.revision == expected else { throw .stale("Subtask", subtaskID) }
        if let title { subtask.title = title }
        subtask.updatedAt = now
        subtask.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .subtask(subtask), now: now)
        data.subtasks[subtaskID] = subtask
        commit(data, owner: owner)
        return .json(200, subtask.dto)
    }

    mutating func transitionSubtask(
        _ taskID: String, _ subtaskID: String, _ request: HTTPRequest, owner: String, now: Date
    ) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["action", "expected_revision"])
        guard let action = try body.value("action", as: SubtaskTransitionAction.self) else {
            throw .validation(["body", "action"], "Field required", type: "missing")
        }
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "transition_subtask:\(taskID):\(subtaskID)"
        let fingerprint = body.fingerprint(command: command)
        if case .subtask(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.current(stored).dto)
        }
        _ = try data.task(taskID)
        var subtask = try data.subtask(subtaskID, of: taskID)
        guard subtask.revision == expected else { throw .stale("Subtask", subtaskID) }
        guard subtask.state != action.targetState else {
            throw .rejected("Subtask transition requires a different state.")
        }
        subtask.state = action.targetState
        subtask.updatedAt = now
        subtask.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .subtask(subtask), now: now)
        data.subtasks[subtaskID] = subtask
        commit(data, owner: owner)
        return .json(200, subtask.dto)
    }

    // MARK: - Comments

    mutating func createComment(_ taskID: String, _ request: HTTPRequest, owner: String, now: Date) throws(FakeHTTPError)
        -> Reply
    {
        let body = try RequestBody(request.body, allowing: ["body"])
        let text = try body.string("body", required: true, min: 1, max: GTDLimits.comment) ?? ""
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        _ = try data.task(taskID)
        let command = "create_comment:\(taskID)"
        let fingerprint = body.fingerprint(command: command)
        if case .comment(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(201, data.current(stored).dto)
        }
        let comment = CommentRow(
            id: mint("comment"), taskID: taskID, actorID: owner, body: text, createdAt: now, editedAt: nil, revision: 1
        )
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .comment(comment), now: now)
        data.comments[comment.id] = comment
        commit(data, owner: owner)
        return .json(201, comment.dto)
    }

    mutating func updateComment(
        _ taskID: String, _ commentID: String, _ request: HTTPRequest, owner: String, now: Date
    ) throws(FakeHTTPError) -> Reply {
        let body = try RequestBody(request.body, allowing: ["body", "expected_revision"])
        let text = try body.string("body", required: true, min: 1, max: GTDLimits.comment) ?? ""
        let expected = try body.int("expected_revision", minimum: 1)
        let key = try idempotencyKey(request)
        var data = beginWrite(owner, now: now)
        let command = "update_comment:\(taskID):\(commentID)"
        let fingerprint = body.fingerprint(command: command)
        if case .comment(let stored)? = try data.replay(key: key, command: command, fingerprint: fingerprint) {
            return .json(200, data.current(stored).dto)
        }
        _ = try data.task(taskID)
        var comment = try data.comment(commentID, of: taskID)
        guard comment.revision == expected else { throw .stale("Comment", commentID) }
        comment.body = text
        comment.editedAt = now
        comment.revision += 1
        data.remember(key: key, command: command, fingerprint: fingerprint, result: .comment(comment), now: now)
        data.comments[commentID] = comment
        commit(data, owner: owner)
        return .json(200, comment.dto)
    }
}

extension OwnerData {
    func subtask(_ id: String, of taskID: String) throws(FakeHTTPError) -> SubtaskRow {
        guard let subtask = subtasks[id], subtask.taskID == taskID else { throw .notFound("Task subtask", id) }
        return subtask
    }

    func comment(_ id: String, of taskID: String) throws(FakeHTTPError) -> CommentRow {
        guard let comment = comments[id], comment.taskID == taskID else { throw .notFound("Task comment", id) }
        return comment
    }

    func current(_ stored: SubtaskRow) -> SubtaskRow {
        guard let current = subtasks[stored.id], current.revision >= stored.revision else { return stored }
        return current
    }

    func current(_ stored: CommentRow) -> CommentRow {
        guard let current = comments[stored.id], current.revision >= stored.revision else { return stored }
        return current
    }
}
