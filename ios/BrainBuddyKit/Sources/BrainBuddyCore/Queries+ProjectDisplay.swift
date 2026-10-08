import Foundation

/// How a project presents itself, decided once so the Mac (X-06) and the iPhone (M-02) never
/// re-derive it (FR-025, FR-027).
public struct ProjectDisplay: Hashable, Sendable {
    public var isArchived: Bool
    /// False for an archived project: capture into it is refused until it is unarchived.
    public var acceptsNewTasks: Bool
    /// The marker says an archive cleared its tasks' project before archives kept them, and no task
    /// of the project is left in any state: the screen explains why it looks empty.
    public var showsPreLosslessLine: Bool
    /// The name, with " · archived" after an archived project's.
    public var label: String
}

extension GTDQueries {
    /// The presentation of project `id`; nil for a project the state does not hold.
    public static func projectDisplay(_ id: ProjectID, in state: GTDState) -> ProjectDisplay? {
        guard let project = state.projects[id] else { return nil }
        let archived = project.state == .archived
        return ProjectDisplay(
            isArchived: archived, acceptsNewTasks: !archived,
            showsPreLosslessLine: project.archivedBeforeLossless && !state.tasks.values.contains { $0.projectID == id },
            label: archived ? "\(project.name) · archived" : project.name
        )
    }
}
