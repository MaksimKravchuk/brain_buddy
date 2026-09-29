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

public enum CapturePlanner {
    public static func preview(_ draft: CaptureDraft, in state: GTDState) -> CapturePreview {
        fatalError("CapturePlanner.preview is not implemented yet")
    }

    /// Resolves tokens against active projects and tags (by normalized name)
    /// and creates the missing ones. An archived project's name cannot be
    /// reused by capture (`GTDValidationError.projectNotActive`).
    public static func plan(
        _ draft: CaptureDraft, in state: GTDState, makeTaskID: () -> TaskID = { .random() },
        makeProjectID: () -> ProjectID = { .random() }, makeTagID: () -> TagID = { .random() }
    ) throws(GTDValidationError) -> CapturePlan {
        fatalError("CapturePlanner.plan is not implemented yet")
    }
}
