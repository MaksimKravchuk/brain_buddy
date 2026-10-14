import BrainBuddyCore
import Foundation

/// What decoding a page needs from the workspace, copied on the main actor so the decoding itself
/// can run elsewhere. `revision` is the state's revision at the copy: a page decoded against an
/// older state is decoded again rather than applied.
struct RustDecodeContext: Sendable {
    let facade: RustDomainFacade
    let state: GTDState
    let revision: UInt64
    let now: Date
}

/// A page's answer already turned into records, ready for the main actor to adopt without parsing
/// anything. Review pages and anything undecodable are not prepared; the main actor handles those.
struct RustPreparedPage: Sendable {
    enum Payload: Sendable {
        case list([TaskRecord])
        case task(TaskRecord)
        case projects([ProjectSummary])
        case tags([TagSummary])
        case tasks([TaskRecord])
        case records(GTDState)
        /// The answer parses; it is kept as it is.
        case checked
    }

    let revision: UInt64
    let frames: [RustWorkspaceTaskFrame]
    let payload: Payload

    /// Pure: no workspace state is read or written. Nil leaves the page to the main actor, which
    /// decodes it again and reports whatever is wrong with it.
    static func decode(query: Data, page: RustWorkspacePage, context: RustDecodeContext) -> RustPreparedPage? {
        guard let root = try? JSONSerialization.jsonObject(with: query) as? [String: Any],
              let kind = root["kind"] as? String else { return nil }
        let facade = context.facade, state = context.state, now = context.now
        do {
            let frames = try facade.workspaceTaskFrames(from: page)
            let payload: Payload
            switch kind {
            case "list_mode":
                payload = .list(try facade.workspaceList(from: page, keeping: state, at: now).list.sections.flatMap(\.tasks))
            case "task_detail":
                payload = .task(try facade.workspaceTask(from: page.result, detail: true, at: now))
            case "projects", "native_projects":
                payload = .projects(try facade.workspaceProjects(from: page.result, keeping: state, at: now))
            case "tags", "native_tags":
                payload = .tags(try facade.workspaceTags(from: page.result, keeping: state, at: now))
            case "task_list", "native_task_views":
                payload = .tasks(try facade.workspaceRenderedTasks(from: page, at: now))
            case "records":
                let requests = try Workspace.rustRecordRequests(from: query)
                var owned = GTDState.empty
                try facade.workspaceApplyRecords(from: page.result, requests: requests, to: &owned, at: now)
                payload = .records(owned)
            case "list_counts":
                _ = try facade.workspaceCounts(from: page.result)
                payload = .checked
            case "capture_preview":
                _ = try facade.workspaceCapturePreview(from: page.result, in: state)
                payload = .checked
            default:
                return nil
            }
            return RustPreparedPage(revision: context.revision, frames: frames, payload: payload)
        } catch {
            return nil
        }
    }
}
