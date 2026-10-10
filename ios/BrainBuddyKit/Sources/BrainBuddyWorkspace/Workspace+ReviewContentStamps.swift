import BrainBuddyCore
import Foundation

extension Workspace {
    private func rustReviewContentStampsKey(key: Data, tasks: [TaskID], projects: [ProjectID]) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceReviewContentStampsQuery(key: key, tasks: tasks, projects: projects, bindings: rustIdentityBindings)
    }

    /// Complete content stamps are separate from the bounded display-task pages.
    /// Pass the unchanged raw installSalt Data. No key or stamp is saved here.
    @discardableResult
    public func prepareReviewContentStamps(key: Data, tasks: [TaskID] = [], projects: [ProjectID] = []) async throws -> RustWorkspaceReviewContentStamps {
        guard isRustSelected else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        guard key.count <= 8 * 1024 * 1024 else { throw RustBridgeError(code: "INVALID_REQUEST", field: "key") }
        guard tasks.count + projects.count <= 200 else { throw RustBridgeError(code: "TOO_MANY_ITEMS") }
        let identities = tasks.map { RustWorkspaceIdentityRequest(entityType: "task", localID: $0.rawValue) }
            + projects.map { RustWorkspaceIdentityRequest(entityType: "project", localID: $0.rawValue) }
        await prepareOwnedQuery({ try rustReviewContentStampsKey(key: key, tasks: tasks, projects: projects) }, identities: identities)
        guard let value = reviewContentStamps(key: key, tasks: tasks, projects: projects) else {
            if case .failed(let code) = reviewContentStampsReadiness(key: key, tasks: tasks, projects: projects) { throw RustBridgeError(code: code) }
            throw RustBridgeError(code: Task.isCancelled ? "CANCELLED" : "WORKSPACE_NOT_READY")
        }
        return value
    }

    public func reviewContentStampsReadiness(key: Data, tasks: [TaskID] = [], projects: [ProjectID] = []) -> WorkspaceQueryReadiness {
        guard isRustSelected else { return .notRequested }
        return rustQueryPageState { try rustReviewContentStampsKey(key: key, tasks: tasks, projects: projects) }
            .readiness
    }

    public func reviewContentStamps(key: Data, tasks: [TaskID] = [], projects: [ProjectID] = []) -> RustWorkspaceReviewContentStamps? {
        guard isRustSelected, let query = try? rustReviewContentStampsKey(key: key, tasks: tasks, projects: projects),
              let page = rustPage(for: query), let facade = rustFacade else { return nil }
        do { return try facade.workspaceReviewContentStamps(from: page) }
        catch {
            rustQueries?.recordFailure(query, code: (error as? RustBridgeError)?.code ?? "MALFORMED_QUERY_RESULT")
            markRustQueryError(error)
            return nil
        }
    }
}
