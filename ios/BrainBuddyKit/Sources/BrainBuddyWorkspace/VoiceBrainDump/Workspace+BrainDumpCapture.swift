import BrainBuddyCore

// The workspace side of the voice brain dump (spec 031): today, active projects, and the
// ordinary capture path, so a voice step is a task like any other.
extension Workspace: BrainDumpCapturePort {
    public var brainDumpToday: CalendarDay { today }

    public func brainDumpProjects() -> [BrainDumpProject] {
        projects(archived: false)
            .filter { $0.project.state == .active }
            .map { BrainDumpProject(id: $0.id, name: $0.project.name) }
    }

    public func captureBrainDumpStep(_ draft: CaptureDraft, editorID: String) async throws {
        _ = try await capture(draft, editorID: editorID)
    }
}
