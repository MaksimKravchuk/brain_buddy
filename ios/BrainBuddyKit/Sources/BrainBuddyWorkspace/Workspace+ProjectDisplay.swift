import BrainBuddyCore
import Foundation

extension Workspace {
    private func rustProjectDisplayKey(_ id: ProjectID) throws -> Data {
        guard let facade = rustFacade else { throw RustBridgeError(code: "WORKSPACE_NOT_READY") }
        return try facade.workspaceProjectDisplayQuery(id, bindings: rustIdentityBindings)
    }

    /// Prepare the owning query's whole-project presentation, independent of task pages.
    public func prepareProjectDisplay(_ id: ProjectID) async {
        guard isRustSelected else { return }
        await prepareOwnedQuery({ try rustProjectDisplayKey(id) },
            identities: [.init(entityType: "project", localID: id.rawValue)])
        // Validate the owned DTO before callers treat preparation as ready.
        if projectDisplayReadiness(id) == .ready { _ = projectDisplay(id) }
    }

    public func projectDisplayReadiness(_ id: ProjectID) -> WorkspaceQueryReadiness {
        rustQueryPageState { try rustProjectDisplayKey(id) }.readiness
    }

    public func projectDisplay(_ id: ProjectID) -> ProjectDisplay? {
        guard isRustSelected else { return GTDQueries.projectDisplay(id, in: state) }
        guard let key = try? rustProjectDisplayKey(id), let page = rustPage(for: key), let facade = rustFacade else { return nil }
        do { return try facade.workspaceProjectDisplay(from: page.result) }
        catch {
            rustQueries?.recordFailure(key, code: (error as? RustBridgeError)?.code ?? "MALFORMED_QUERY_RESULT")
            markRustQueryError(error)
            return nil
        }
    }
}
