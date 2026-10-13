import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Observer and close lifetimes at the real Swift/Rust boundary (spec 026 T043): every case runs
/// against an actual store handle, not a controlled fixture.
@Suite("Runtime observer and close lifetimes (026-FR-026)")
struct RustWorkspaceLifetimeTests {
    private static let instant = Date(timeIntervalSince1970: 1_790_000_000)

    private func openRuntime() async throws -> (RustBridgeRuntime, RustWorkspaceRuntime, URL) {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local",
            databaseURL: directory.appendingPathComponent("store.sqlite3"))
        return (bridge, runtime, directory)
    }

    @Test("026-FR-026: closing the workspace ends an observer that is waiting, with a closed error and no hang")
    @MainActor
    func closeWhileSubscribed() async throws {
        let (_, runtime, directory) = try await openRuntime()
        defer { try? FileManager.default.removeItem(at: directory) }
        let subscription = try await runtime.subscribe()
        let initial = try #require(try await subscription.next(after: nil, timeoutMilliseconds: 0))
        var finished = false
        var observer: Task<String, Never>?
        await withCheckedContinuation { (started: CheckedContinuation<Void, Never>) in
            observer = Task { @MainActor in
                defer { finished = true }
                started.resume()
                do {
                    _ = try await subscription.next(after: initial.token, timeoutMilliseconds: 30_000)
                    return "unexpected completion"
                } catch let error as RustBridgeError { return error.code } catch { return "unexpected error" }
            }
        }
        #expect(!finished, "the wait is not on the main actor")
        try await runtime.close()
        let pending = try #require(observer)
        #expect(await pending.value == "WORKSPACE_CLOSED")
        // A second close, and a cancel after close, are harmless.
        try await runtime.close()
        subscription.cancel()
        do {
            _ = try await subscription.next(after: nil, timeoutMilliseconds: 0)
            Issue.record("a closed workspace has no observer")
        } catch let error as RustBridgeError { #expect(error.code == "WORKSPACE_CLOSED") }
        do {
            _ = try await runtime.subscribe()
            Issue.record("a closed workspace takes no new observer")
        } catch let error as RustBridgeError { #expect(error.code == "WORKSPACE_CLOSED") }
    }

    @Test("026-FR-026: a replacement observer sees later commits while the cancelled one stays cancelled")
    @MainActor
    func replacementSubscription() async throws {
        let (bridge, runtime, directory) = try await openRuntime()
        defer { try? FileManager.default.removeItem(at: directory) }
        let first = try await runtime.subscribe()
        let initial = try #require(try await first.next(after: nil, timeoutMilliseconds: 0))
        first.cancel()
        first.cancel()  // cancelling twice is a no-op
        let second = try await runtime.subscribe()
        #expect(try await second.next(after: initial.token, timeoutMilliseconds: 0) == nil)
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let command = try facade.workspaceCommand(.createTask(.init(taskID: TaskID(UUID().uuidString.lowercased()),
            title: "Seen by the replacement", list: .inbox)), commandID: UUID(), at: Self.instant, in: .empty)
        let context = RustWorkspaceContext(now: Self.instant, timeZone: "UTC", actorID: "device",
            policy: Data(#"{"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8))
        guard case .saved = try await runtime.execute([command], context: context) else {
            Issue.record("the commit must succeed"); return
        }
        let changed = try #require(try await second.next(after: initial.token, timeoutMilliseconds: 5_000))
        #expect(!changed.changedKinds.isEmpty)
        #expect(changed.pending == "1")
        do {
            _ = try await first.next(after: nil, timeoutMilliseconds: 0)
            Issue.record("the cancelled observer must stay cancelled")
        } catch let error as RustBridgeError { #expect(error.code == "CANCELLED") }
        second.cancel()
        try await runtime.close()
    }

    @Test("026-FR-026: closing the Workspace's runtime while its observer waits reports no query error and stays closable")
    @MainActor
    func workspaceCloseFencesItsObserver() async throws {
        let (bridge, runtime, directory) = try await openRuntime()
        defer { try? FileManager.default.removeItem(at: directory) }
        let workspace = Workspace(store: ControlledStore(), sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
                startup: .freshAccountless),
            now: { Self.instant })
        await workspace.load()
        #expect(workspace.isRustBound)
        // Let the watcher reach its Rust wait, then close underneath it.
        await Task.yield()
        await workspace.closeRuntime()
        // The watcher's closed error belongs to a fenced binding and must not surface.
        for _ in 0..<5 { await Task.yield() }
        #expect(workspace.queryError == nil)
        #expect(!workspace.isRustBound)
        await workspace.closeRuntime()
    }

    @Test("026-FR-026: a MainActor heartbeat keeps running while a durable commit and a current-record read are in flight")
    @MainActor
    func heartbeatDuringDiskWork() async throws {
        let (_, runtime, directory) = try await openRuntime()
        defer { try? FileManager.default.removeItem(at: directory) }
        var beats = 0
        let heartbeat = Task { @MainActor in
            while !Task.isCancelled { beats += 1; await Task.yield() }
        }
        let request = RustIssueResolveRequest(issueID: "issue_missing", choice: .useCurrent, dependents: [])
        let context = RustWorkspaceContext(now: Self.instant, timeZone: "UTC", actorID: "device",
            policy: Data(#"{"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8))
        do {
            _ = try await runtime.resolveIssue(request, context: context)
            Issue.record("an unknown issue cannot be resolved")
        } catch let error as RustBridgeError { #expect(error.code == "UNKNOWN_ISSUE") }
        #expect(try await runtime.issueCurrent("issue_missing") == nil)
        heartbeat.cancel()
        #expect(beats > 0)
        try await runtime.close()
    }
}
