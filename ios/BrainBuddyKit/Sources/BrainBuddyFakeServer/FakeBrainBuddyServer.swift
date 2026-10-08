import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization

/// An in-memory Brain Buddy API for tests: the task module's REST surface
/// (`backend/app/api/tasks.py`, `backend/app/modules/tasks/service.py`) and
/// the session endpoints, with the same rules the sync engine depends on:
///
/// - `brainbuddy_session` cookie sessions; every task route is owner-scoped
///   and answers 401 without one.
/// - Server-minted ids (`task_1a2b3c4d5e6f`), revisions that go up by one per
///   mutation, and an exact `expected_revision` or 409 "has newer changes".
/// - `Idempotency-Key` per owner: the same key and body replay the stored
///   result, the same key with another body is 409, and keys expire after 24
///   hours of the injected clock (purged on the owner's next write).
/// - Unique active project and tag names (normalized) or 409; archiving a
///   project keeps it on every task (ADR-0020) and deleting a tag removes it
///   from every task, bumping those tasks' revisions; subtask and comment
///   writes leave the parent task alone.
/// - `GET /tasks` pages with `limit` and an opaque cursor, items without
///   children; `GET /tasks/{id}` includes them.
///
/// Several devices can share one server: give each its own
/// `makeTransport()`, which also injects faults (see `FakeServerTransport`).
public final class FakeBrainBuddyServer: Sendable {
    /// A base URL the server answers on (any host works; the path must start with `/api`).
    public static let baseURL = URL(string: "https://fake.brainbuddy.test/api")!
    /// How long the server keeps an `Idempotency-Key` (`IDEMPOTENCY_RETENTION`).
    public static let idempotencyRetention: TimeInterval = 24 * 3600

    let state: Mutex<ServerState>
    let now: @Sendable () -> Date

    /// - Parameters:
    ///   - now: the server's clock; share a `ManualClock` with the engine.
    ///   - seed: seeds the minted ids, so runs are reproducible.
    public init(now: @escaping @Sendable () -> Date = { Date() }, seed: UInt64 = 0x5EED_B0DD) {
        self.now = now
        state = Mutex(ServerState(ids: IDGenerator(seed: seed)))
    }

    /// Registers an account and returns its user id (`user_…`).
    @discardableResult
    public func addAccount(email: String, password: String, displayName: String? = nil) -> String {
        state.withLock { state in
            let key = email.lowercased()
            if let existing = state.accountIDsByEmail[key] { return existing }
            let id = state.mint("user")
            state.accounts[id] = FakeAccount(id: id, email: email, password: password, displayName: displayName)
            state.accountIDsByEmail[key] = id
            state.owners[id] = OwnerData()
            return id
        }
    }

    /// Ends every session of the account, as an expiry or a sign-out elsewhere would.
    public func revokeSessions(email: String) {
        state.withLock { state in
            guard let id = state.accountIDsByEmail[email.lowercased()] else { return }
            state.sessions = state.sessions.filter { $0.value != id }
        }
    }

    /// Sessions of the account the server still accepts.
    public func liveSessionCount(email: String) -> Int {
        state.withLock { state in
            guard let id = state.accountIDsByEmail[email.lowercased()] else { return 0 }
            return state.sessions.values.filter { $0 == id }.count
        }
    }

    /// Schedules the account for deletion (`DELETE /account` with its grace
    /// period): the next login cancels that and says so (`deletion_cancelled`).
    public func scheduleDeletion(email: String) {
        state.withLock { state in
            guard let id = state.accountIDsByEmail[email.lowercased()] else { return }
            state.accounts[id]?.deletionScheduled = true
        }
    }

    /// A transport for one device, with its own fault queue and request log.
    public func makeTransport() -> FakeServerTransport { FakeServerTransport(server: self) }

    /// Answers one request as the backend would (no faults).
    public func respond(to request: HTTPRequest) -> HTTPResponse {
        let date = FakeBrainBuddyServer.serverTime(now())
        return state.withLock { $0.respond(to: request, now: date) }
    }

    /// Everything the account owns, in the API's own shapes: tasks as
    /// `GET /tasks/{id}` returns them (with children), projects and tags in
    /// every state.
    public func snapshot(email: String) -> FakeServerSnapshot {
        state.withLock { state in
            guard let id = state.accountIDsByEmail[email.lowercased()], let data = state.owners[id] else {
                return FakeServerSnapshot()
            }
            return FakeServerSnapshot(
                tasks: data.tasks.mapValues { data.detailDTO($0) },
                projects: data.projects.mapValues { data.projectDTO($0) },
                tags: data.tags.mapValues { data.tagDTO($0) }
            )
        }
    }

    /// Idempotency keys the server still holds for the account.
    public func idempotencyKeyCount(email: String) -> Int {
        state.withLock { state in
            state.accountIDsByEmail[email.lowercased()].flatMap { state.owners[$0]?.idempotency.count } ?? 0
        }
    }

    /// Server timestamps carry microseconds, like Python's `datetime`.
    static func serverTime(_ date: Date) -> Date {
        Date(timeIntervalSince1970: (date.timeIntervalSince1970 * 1_000_000).rounded() / 1_000_000)
    }
}

/// The server's data for one account, keyed by server id.
public struct FakeServerSnapshot: Hashable, Sendable {
    public var tasks: [String: TaskDTO]
    public var projects: [String: ProjectDTO]
    public var tags: [String: TagDTO]

    public init(tasks: [String: TaskDTO] = [:], projects: [String: ProjectDTO] = [:], tags: [String: TagDTO] = [:]) {
        self.tasks = tasks
        self.projects = projects
        self.tags = tags
    }
}
