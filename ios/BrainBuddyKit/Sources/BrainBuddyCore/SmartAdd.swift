import Foundation

/// What the capture sheet holds. `text` may contain Smart Add tokens
/// (`#tag`, `@project`, quoted `@"Two words"`), parsed exactly like the web
/// (`frontend/src/features/tasks/smartAdd.ts`, spec 003, ADR-0007).
public struct CaptureDraft: Hashable, Sendable, Codable {
    public var text: String
    public var list: OpenList
    public var waitingFor: String
    public var details: String
    public var dueDate: CalendarDay?
    public var priority: TaskPriority
    /// The project or tag screen the capture started from; applied unless a
    /// token overrides it.
    public var contextProjectID: ProjectID?
    public var contextTagID: TagID?

    public init(
        text: String = "", list: OpenList = .inbox, waitingFor: String = "", details: String = "",
        dueDate: CalendarDay? = nil, priority: TaskPriority = .none, contextProjectID: ProjectID? = nil,
        contextTagID: TagID? = nil
    ) {
        self.text = text
        self.list = list
        self.waitingFor = waitingFor
        self.details = details
        self.dueDate = dueDate
        self.priority = priority
        self.contextProjectID = contextProjectID
        self.contextTagID = contextTagID
    }

    public var isBlank: Bool {
        text.allSatisfy(\.isWhitespace) && details.allSatisfy(\.isWhitespace)
            && waitingFor.allSatisfy(\.isWhitespace)
    }
}

/// A recognised token, for highlighting in the text field.
public struct SmartAddToken: Hashable, Sendable {
    public enum Kind: Hashable, Sendable { case project, tag }
    public var kind: Kind
    /// Offsets in UTF-16 code units, so they convert directly to `NSRange`.
    public var utf16Range: Range<Int>
    public var name: String

    public init(kind: Kind, utf16Range: Range<Int>, name: String) {
        self.kind = kind
        self.utf16Range = utf16Range
        self.name = name
    }
}

public struct ClassificationPreview: Hashable, Sendable {
    public var name: String
    /// True when capture will create it.
    public var isNew: Bool
    public init(name: String, isNew: Bool) {
        self.name = name
        self.isNew = isNew
    }
}

public struct CapturePreview: Hashable, Sendable {
    /// The task title after tokens are removed.
    public var title: String
    public var project: ClassificationPreview?
    public var tags: [ClassificationPreview]
    public var tokens: [SmartAddToken]
    /// Nil when capture would succeed.
    public var problem: GTDValidationError?

    public var isValid: Bool { problem == nil }

    public init(
        title: String, project: ClassificationPreview?, tags: [ClassificationPreview],
        tokens: [SmartAddToken], problem: GTDValidationError?
    ) {
        self.title = title
        self.project = project
        self.tags = tags
        self.tokens = tokens
        self.problem = problem
    }
}

/// Commands that capture one task: new projects/tags first, then the task.
public struct CapturePlan: Hashable, Sendable {
    public var commands: [GTDCommand]
    public var taskID: TaskID
    public init(commands: [GTDCommand], taskID: TaskID) {
        self.commands = commands
        self.taskID = taskID
    }
}

/// Smart Add on the device (`SmartAddParser` for the grammar; resolution and
/// validation in `SmartAdd+Resolution.swift`). Validation mirrors the reducer's
/// `createProject` / `createTag` / `createTask` rules without calling it, so the
/// preview can say why capture is blocked before anything is applied.
public enum CapturePlanner {
    /// What capture would do right now: the clean title, the project and tags
    /// it would use or create, the tokens to highlight, and the first problem.
    /// A blank draft reports `.emptyTitle`; the sheet decides whether to show
    /// it yet (for example while `CaptureDraft.isBlank`).
    public static func preview(_ draft: CaptureDraft, in state: GTDState) -> CapturePreview {
        let resolution = resolve(draft, in: state)
        return CapturePreview(
            title: resolution.title, project: resolution.project?.preview, tags: resolution.tags.map(\.preview),
            tokens: resolution.tokens, problem: resolution.problem
        )
    }

    /// Resolves tokens against active projects and tags (by normalized name)
    /// and creates the missing ones. An archived project's name cannot be
    /// reused by capture (`GTDValidationError.projectNotActive`).
    ///
    /// Commands come in apply order: `createProject` (when new), `createTag`
    /// for each new tag, then `createTask`. Ids are minted in that order too.
    public static func plan(
        _ draft: CaptureDraft, in state: GTDState, makeTaskID: () -> TaskID = { .random() },
        makeProjectID: () -> ProjectID = { .random() }, makeTagID: () -> TagID = { .random() }
    ) throws(GTDValidationError) -> CapturePlan {
        let resolution = resolve(draft, in: state)
        if let problem = resolution.problem { throw problem }

        var commands: [GTDCommand] = []
        var projectID: ProjectID?
        switch resolution.project {
        case .existing(let id, _):
            projectID = id
        case .new(let name):
            let id = makeProjectID()
            commands.append(.createProject(.init(projectID: id, name: name)))
            projectID = id
        case nil:
            break
        }

        var tagIDs: [TagID] = []
        for tag in resolution.tags {
            switch tag {
            case .existing(let id, _):
                tagIDs.append(id)
            case .new(let name):
                let id = makeTagID()
                commands.append(.createTag(.init(tagID: id, name: name)))
                tagIDs.append(id)
            }
        }

        let taskID = makeTaskID()
        commands.append(
            .createTask(
                .init(
                    taskID: taskID, title: resolution.title, details: resolution.details, list: draft.list,
                    waitingFor: resolution.waitingFor, dueDate: draft.dueDate, priority: draft.priority,
                    projectID: projectID, tagIDs: tagIDs
                )
            )
        )
        return CapturePlan(commands: commands, taskID: taskID)
    }
}
