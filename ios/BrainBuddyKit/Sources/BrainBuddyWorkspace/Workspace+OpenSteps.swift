import BrainBuddyCore
import Foundation

/// One open step: the id the app knows it by and the id the server knows it by.
public struct OpenStepServerID: Hashable, Sendable {
    public let taskID: TaskID
    /// `nil` only for a legacy step that has never synced.
    public let serverID: String?
}

extension Workspace {
    /// Every open (not completed or cancelled) step with its server id, read-only. The legacy workspace
    /// reads its document. A Rust-selected workspace pages the open lists and the project views of the
    /// runtime (`state.tasks` there holds only the rendered window and never carries `serverID`); the
    /// canonical id is the server id, and `taskID` is the local id when an identity binding names one.
    public func openStepServerIDs() async throws -> [OpenStepServerID] {
        guard isRustSelected else {
            return state.tasks.values.filter(\.isOpen)
                .map { OpenStepServerID(taskID: $0.id, serverID: $0.serverID) }
                .sorted { $0.taskID.rawValue < $1.taskID.rawValue }
        }
        guard let facade = rustFacade, let runtime = rustRuntime, isRustBound else {
            throw RustBridgeError(code: "WORKSPACE_NOT_READY")
        }
        let binding = runtimeBindingID
        let instant = now()
        let inputs = try facade.workspaceQueryInputs(at: instant, zone: deviceTimeZone().identifier,
            reviewExposed: rustSelection?.reviewEnabled == true)
        let local = rustIdentityBindings.reduce(into: [String: String]()) { map, row in
            if row.entityType == "task", let canonical = row.canonicalID { map[canonical] = row.localID }
        }
        var destinations = OpenList.allCases.map { Destination.list($0) }
        for archived in [false, true] {
            let key = try facade.workspaceProjectsQuery(archived: archived, bindings: rustIdentityBindings)
            for page in try await rustOpenStepPages(key, facade: facade, runtime: runtime, inputs: inputs) {
                destinations += try facade.workspaceProjects(from: page.result, keeping: state, at: instant)
                    .map { Destination.project($0.project.id) }
            }
        }
        var found: [String: OpenStepServerID] = [:]
        for destination in destinations {
            let key = try facade.workspaceListQuery(destination, options: ListOptions(), bindings: rustIdentityBindings)
            for page in try await rustOpenStepPages(key, facade: facade, runtime: runtime, inputs: inputs) {
                let rows = try facade.workspaceList(from: page, keeping: state, at: instant).list
                for task in rows.sections.flatMap(\.tasks) where task.isOpen {
                    let canonical = task.id.rawValue
                    found[canonical] = OpenStepServerID(taskID: TaskID(local[canonical] ?? canonical), serverID: canonical)
                }
            }
        }
        guard binding == runtimeBindingID else { throw RustBridgeError(code: "CLOSED") }
        return found.values.sorted { $0.taskID.rawValue < $1.taskID.rawValue }
    }

    /// Every page of one canonical query, following its cursor.
    private func rustOpenStepPages(_ key: Data, facade: RustDomainFacade, runtime: RustWorkspaceRuntime,
                                   inputs: Data) async throws -> [RustWorkspacePage] {
        let canonical = try await facade.workspaceResolveReferences(key, runtime: runtime)
        var pages: [RustWorkspacePage] = []
        var cursor: String?
        repeat {
            switch try await runtime.query(canonical, inputs: inputs, collectionLimit: 200, collectionAfter: cursor) {
            case .answered(let page):
                pages.append(page)
                cursor = page.collectionNextCursor
            case .refused(let refusal, _):
                throw RustBridgeError(code: refusal.reason)
            }
        } while cursor != nil
        return pages
    }
}
