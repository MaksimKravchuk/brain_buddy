import BrainBuddyCore
import Foundation

/// Which inspector a task gets, from its state (boards "13 Next action", "16 What is it?",
/// "18 Waiting for", "19 Someday" and "20 Done").
package enum TaskInspectorVariant: Equatable, Sendable {
    case inbox, next, waiting, someday
    /// Completed or cancelled: read-only, with "Reopen…".
    case finished(cancelled: Bool)

    package init(state: TaskState) {
        switch state {
        case .inbox: self = .inbox
        case .next: self = .next
        case .waiting: self = .waiting
        case .someday: self = .someday
        case .completed: self = .finished(cancelled: false)
        case .cancelled: self = .finished(cancelled: true)
        }
    }

    package var isReadOnly: Bool {
        if case .finished = self { return true }
        return false
    }
}

/// The typed fields of the inspector: the one with keyboard focus is never overwritten by a
/// change that arrives meanwhile.
package enum TaskInspectorField: Hashable, Sendable {
    case title, details, waitingFor
}

/// What one save sends: the touched fields, and the list to move to when the save is a move.
package struct TaskAutosaveRequest: Equatable, Sendable {
    package let changes: TaskChanges
    package let moveTo: TaskList?
}

/// The inspector's "Saved as you type": a `TaskEditDraft` plus when it was last edited and whether
/// a save is in flight. Field edits save once the person pauses (`delay`), or at once on a flush
/// (selection change, a list action, closing, ⌘S, the app going to the background); a list move
/// saves at once with whatever fields are pending. Only touched fields are sent (FR-009), and a
/// change arriving from elsewhere never overwrites a field the person is typing in. The clock is
/// the caller's, so the debounce is decided here and tested without waiting.
package struct TaskAutosave: Equatable, Sendable {
    /// The pause after the last keystroke before a field edit saves.
    package static let delay: TimeInterval = 0.6

    package let taskID: TaskID
    package private(set) var draft: TaskEditDraft
    /// The task's state when last seen; a move to the same list is not a move.
    package private(set) var state: TaskState
    /// The last edit not yet covered by a save; nil once saved (or after a failed save, so a
    /// refused change is not retried in a loop: the next edit or flush tries again).
    package private(set) var lastEditAt: Date?
    /// When the save in flight was asked for; nil while none is.
    package private(set) var savingSince: Date?

    package init(task: TaskRecord) {
        taskID = task.id
        draft = TaskEditDraft(task)
        state = task.state
    }

    package var isSaving: Bool { savingSince != nil }

    // MARK: Editing

    /// One edit by the person at `now`.
    package mutating func set<Value: Equatable>(_ field: WritableKeyPath<TaskEditDraft, Value>, to value: Value, at now: Date) {
        guard draft[keyPath: field] != value else { return }
        draft[keyPath: field] = value
        lastEditAt = now
    }

    /// The draft as it is saved: the title trimmed, so spaces alone are not a change.
    private var normalized: TaskEditDraft {
        var normalized = draft
        normalized.title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
        return normalized
    }

    /// Some field differs from the task as last saved or seen.
    package var isDirty: Bool { normalized.changes().hasChanges }

    /// Whether the fields can be saved as they are: a title, every text within its limit, and the
    /// person or thing a Waiting task waits for.
    package var isValid: Bool { problem == nil }

    /// Why the fields cannot be saved yet, in words for the inspector; nil when they can.
    package var problem: String? {
        let title = normalized.title
        if title.isEmpty { return "A task needs a title. Changes save once it has one." }
        if !EditorLimits.fits(title, EditorLimits.title) { return "Use \(EditorLimits.title) characters or fewer for the title." }
        if !EditorLimits.fits(draft.details ?? "", EditorLimits.details) {
            return "Use \(EditorLimits.details) characters or fewer for the notes."
        }
        if state == .waiting {
            let waiting = (draft.waitingFor ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if waiting.isEmpty { return "Say who or what this is waiting for. Changes save once it does." }
            if !EditorLimits.fits(waiting, EditorLimits.waitingFor) {
                return "Use \(EditorLimits.waitingFor) characters or fewer for who it waits for."
            }
        }
        return nil
    }

    // MARK: Debounce

    /// When the pending field edits save on their own; nil when nothing is pending.
    package var deadline: Date? {
        guard isDirty, let lastEditAt else { return nil }
        return lastEditAt.addingTimeInterval(Self.delay)
    }

    /// Whether the debounce has run out at `now` and the edits can save: no save in flight, and
    /// the fields valid.
    package func isDue(at now: Date) -> Bool {
        guard !isSaving, isValid, let deadline else { return false }
        return now >= deadline
    }

    // MARK: Saving

    /// The save to send now, or nil when there is nothing to send, a save is in flight, or the
    /// fields are not valid. `moveTo` makes it a move as well; the current list is not a move.
    package func saveRequest(moveTo list: TaskList? = nil) -> TaskAutosaveRequest? {
        guard !isSaving, isValid else { return nil }
        let move = list.flatMap { $0.taskState == state ? nil : $0 }
        let changes = normalized.changes()
        guard changes.hasChanges || move != nil else { return nil }
        return TaskAutosaveRequest(changes: changes, moveTo: move)
    }

    /// `saveRequest(moveTo:)`, marked in flight at `now`.
    package mutating func beginSave(moveTo list: TaskList? = nil, at now: Date) -> TaskAutosaveRequest? {
        guard let request = saveRequest(moveTo: list) else { return nil }
        savingSince = now
        return request
    }

    /// The save finished. On success the saved task becomes the baseline and every field keeps what
    /// the person has now, so typing during the save is never undone; an edit made after the save
    /// was asked for stays pending.
    package mutating func finishSave(succeeded: Bool, current: TaskRecord?) {
        let askedAt = savingSince
        savingSince = nil
        if succeeded, let current, current.id == taskID {
            var rebased = TaskEditDraft(current)
            rebased.title = draft.title
            rebased.details = draft.details
            rebased.projectID = draft.projectID
            rebased.tagIDs = draft.tagIDs
            rebased.dueDate = draft.dueDate
            rebased.waitingFor = draft.waitingFor
            draft = rebased
            state = current.state
        }
        if let lastEditAt, let askedAt, lastEditAt > askedAt { return }
        lastEditAt = nil
    }

    /// A change to the task arrived (a pull, or this Mac's own save): untouched fields take the
    /// incoming value, touched ones keep what the person typed, and the field being typed in is
    /// kept whatever it holds.
    package mutating func rebase(onto incoming: TaskRecord, typingIn field: TaskInspectorField?) {
        guard incoming.id == taskID else { return }
        var rebased = draft.rebased(onto: incoming)
        switch field {
        case .title: rebased.title = draft.title
        case .details: rebased.details = draft.details
        case .waitingFor: rebased.waitingFor = draft.waitingFor
        case nil: break
        }
        draft = rebased
        state = incoming.state
    }
}
