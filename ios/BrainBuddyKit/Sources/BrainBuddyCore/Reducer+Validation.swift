import Foundation

/// Field rules shared by the command handlers. Lengths count Unicode scalars,
/// as Python's `len` does on the server, not grapheme clusters; a supplied
/// value is length-checked as sent, like the server's request schemas do.
enum FieldRules {
    static func length(_ value: String) -> Int { value.unicodeScalars.count }

    /// Task and subtask titles are trimmed (every client trims before sending)
    /// and must keep 1…500 characters.
    static func title(_ raw: String) throws(GTDValidationError) -> String {
        let value = NameNormalizer.stripped(raw)
        guard !value.isEmpty else { throw .emptyTitle }
        guard length(raw) <= GTDLimits.title else { throw .titleTooLong }
        return value
    }

    /// Notes are stored verbatim; an empty string means no notes.
    static func details(_ raw: String?) throws(GTDValidationError) -> String? {
        guard let raw, !raw.isEmpty else { return nil }
        guard length(raw) <= GTDLimits.details else { throw .detailsTooLong }
        return raw
    }

    /// The server validates a supplied `waiting_for` even when it then drops it.
    static func checkWaitingForLength(_ raw: String?) throws(GTDValidationError) {
        if let raw, length(raw) > GTDLimits.waitingFor { throw .waitingForTooLong }
    }

    /// `TaskService._waiting_for`: trimmed and non-blank.
    static func waitingFor(_ raw: String?) throws(GTDValidationError) -> String {
        try checkWaitingForLength(raw)
        let value = NameNormalizer.stripped(raw ?? "")
        guard !value.isEmpty else { throw .waitingForRequired }
        return value
    }

    /// The waiting note of a task entering `list`: required for Waiting,
    /// silently dropped for every other list (as the server does).
    static func waitingFor(_ raw: String?, entering list: OpenList) throws(GTDValidationError) -> String? {
        try checkWaitingForLength(raw)
        guard list == .waiting else { return nil }
        return try waitingFor(raw)
    }

    /// A project or tag name in the display form the server stores.
    static func name(_ raw: String, display: (String) -> String) throws(GTDValidationError) -> String {
        let value = display(raw)
        guard !value.isEmpty else { throw .emptyName }
        guard length(raw) <= GTDLimits.name, length(value) <= GTDLimits.name else { throw .nameTooLong }
        return value
    }

    static func color(_ raw: String?) throws(GTDValidationError) -> String? {
        if let raw, length(raw) > GTDLimits.color { throw .colorTooLong }
        return raw
    }

    /// Comment bodies are stored verbatim: the server neither trims them nor
    /// rejects whitespace, only the empty string.
    static func comment(_ body: String) throws(GTDValidationError) -> String {
        guard !body.isEmpty else { throw .emptyComment }
        guard length(body) <= GTDLimits.comment else { throw .commentTooLong }
        return body
    }
}

extension GTDReducer {
    /// A command whose goal already holds: satisfied while replaying, `error` for a user action.
    static func satisfied(_ mode: ApplyMode, else error: GTDValidationError) throws(GTDValidationError)
        -> ApplyOutcome
    {
        guard mode == .replay else { throw error }
        return .alreadySatisfied
    }

    /// `TaskService._assert_active_references` for the references a command sets.
    static func checkReferences(project: ProjectID?, tags: [TagID]?, in state: GTDState) throws(GTDValidationError) {
        if let project {
            guard let record = state.projects[project] else { throw .projectNotFound }
            guard record.state == .active else { throw .projectNotActive }
        }
        guard let tags else { return }
        guard Set(tags).count == tags.count else { throw .duplicateTag }
        for tag in tags {
            guard let record = state.tags[tag] else { throw .tagNotFound }
            guard record.state == .active else { throw .tagNotActive }
        }
    }
}
