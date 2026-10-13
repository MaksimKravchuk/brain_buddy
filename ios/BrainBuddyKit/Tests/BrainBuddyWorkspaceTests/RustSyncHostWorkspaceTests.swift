import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

/// The Rust sync loop driven by the Apple host (`RustSyncHost`) under a selected-runtime Workspace,
/// over a stubbed sync-v1 server (026 PR-40): a local edit is sent, a change committed elsewhere is
/// pulled and shown, a rebuild takes a snapshot, and a newer server reads as "update needed".
@Suite("Rust sync host under a Workspace (026-FR-004, 026-FR-005, 026-FR-010)")
struct RustSyncHostWorkspaceTests {
    @Test("026-FR-005 026-FR-004: a local edit is sent through the host and a change committed elsewhere appears")
    @MainActor
    func editIsSentAndPulledChangeAppears() async throws {
        let rig = try await Rig.start()
        defer { rig.cleanup() }
        let workspace = rig.workspace
        await workspace.load()
        #expect(workspace.isRustBound)

        // The first foreground round takes the recovery snapshot of an empty account.
        await workspace.syncNow()
        #expect(rig.server.requests.contains { $0.method == "POST" && $0.url.path == "/api/sync/v1/snapshots" })

        _ = try await workspace.capture(CaptureDraft(text: "Written offline"), editorID: "scene:host:capture")
        // The save woke the loop; the send happens on the sync worker, not on this actor.
        #expect(rig.server.wait(timeout: 20) { requests, _ in
            requests.contains { $0.method == "POST" && $0.url.path == "/api/sync/v1/commands" }
        })
        await workspace.syncNow()
        await workspace.refreshRustStatus()
        #expect(workspace.pendingChangeCount == 0, "the server's receipt settled it")
        #expect(rig.model.commandsSeen == 1)
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Written offline"])

        // Every call carried the session cookie from the token store (the core never saw it).
        #expect(rig.server.requests.allSatisfy { $0.header("Cookie") == "brainbuddy_session=tok-1" })

        // A change another device committed is pulled and shown.
        rig.model.commitExternal(taskID: "task_00000000-0000-4000-8000-0000000000aa", title: "From another device")
        await workspace.syncNow()
        // The runtime's subscription re-queries on its own; wait for the list to follow.
        let shown = await eventually(workspace) { titles in titles == ["Written offline", "From another device"] }
        #expect(shown == ["Written offline", "From another device"])
        await workspace.closeRuntime()
    }

    @Test("026-FR-010: rebuild synced copy takes a snapshot, keeps the waiting change and reports it")
    @MainActor
    func rebuildKeepsWaitingChanges() async throws {
        let rig = try await Rig.start(sendsAnswer: .offline)
        defer { rig.cleanup() }
        let workspace = rig.workspace
        await workspace.load()
        await workspace.syncNow()
        _ = try await workspace.capture(CaptureDraft(text: "Kept through the rebuild"), editorID: "scene:host:rebuild")
        let snapshots = { rig.server.requests.filter { $0.method == "POST" && $0.url.path == "/api/sync/v1/snapshots" }.count }
        let before = snapshots()

        let result = await workspace.rebuildSyncedCopy()
        #expect(result == .rebuilt)
        #expect(snapshots() == before + 1)
        #expect(workspace.syncRecovery.rebuild == .idle)
        await workspace.refreshRustStatus()
        #expect(workspace.pendingChangeCount == 1, "a rebuild never drops a waiting change")
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Kept through the rebuild"])
        await workspace.closeRuntime()
    }

    @Test("026-FR-017: a server newer than this build stops sync as update needed and keeps the edit")
    @MainActor
    func newerServerIsUpdateNeeded() async throws {
        let rig = try await Rig.start(protocolVersions: [99])
        defer { rig.cleanup() }
        let workspace = rig.workspace
        await workspace.load()
        await workspace.syncNow()
        #expect(workspace.runtimeSyncNeedsUpdate)
        #expect(workspace.syncRecovery.syncNeedsUpdate)
        #expect(workspace.syncRecovery.needsAttention)

        // Saving still works; nothing is sent.
        _ = try await workspace.capture(CaptureDraft(text: "Saved while sync is stopped"), editorID: "scene:host:update")
        await workspace.refreshRustStatus()
        #expect(workspace.pendingChangeCount == 1)
        #expect(rig.model.commandsSeen == 0)
        await workspace.closeRuntime()
    }

    @Test("026-FR-005: a 401 from the server is a session that ended, and the edit stays queued")
    @MainActor
    func unauthorizedNeedsSignIn() async throws {
        let rig = try await Rig.start(unauthorized: true)
        defer { rig.cleanup() }
        let workspace = rig.workspace
        await workspace.load()
        await workspace.syncNow()
        #expect(workspace.syncStatus == .needsSignIn)
        _ = try await workspace.capture(CaptureDraft(text: "Waits for sign-in"), editorID: "scene:host:401")
        await workspace.refreshRustStatus()
        #expect(workspace.pendingChangeCount == 1)
        await workspace.closeRuntime()
    }

    @Test("026-FR-001: closing the workspace stops the host: later requests are unavailable and nothing more is sent")
    @MainActor
    func closeStopsTheHost() async throws {
        let rig = try await Rig.start()
        defer { rig.cleanup() }
        await rig.workspace.load()
        await rig.workspace.syncNow()
        await rig.workspace.closeRuntime()
        let count = rig.server.requests.count
        #expect(await rig.host.request(.manual) == .transportUnavailable)
        #expect(await rig.host.rebuildSyncedCopy() == .transportUnavailable)
        await rig.host.setNetworkAvailable(true)
        #expect(rig.server.requests.count == count)
    }
}

/// The Inbox titles once `done` holds (the last seen ones if it never does within 10 s).
@MainActor
private func eventually(_ workspace: Workspace, _ done: (Set<String>) -> Bool) async -> Set<String> {
    var titles = Set<String>()
    for _ in 0..<200 {
        await workspace.prepareList(.list(.inbox))
        titles = Set(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title))
        if done(titles) { break }
        try? await Task.sleep(for: .milliseconds(50))
    }
    return titles
}

// MARK: - Rig

private final class Rig: Sendable {
    enum Sends: Sendable { case accept, offline }

    let root: URL
    let server: StubServer
    let model: SyncModel
    let host: RustSyncHost
    let workspace: Workspace

    private init(root: URL, server: StubServer, model: SyncModel, host: RustSyncHost, workspace: Workspace) {
        self.root = root
        self.server = server
        self.model = model
        self.host = host
        self.workspace = workspace
    }

    func cleanup() { try? FileManager.default.removeItem(at: root) }

    @MainActor
    static func start(
        protocolVersions: [Int] = [1], unauthorized: Bool = false, sendsAnswer: Sends = .accept
    ) async throws -> Rig {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let server = StubServer()
        let model = SyncModel(protocolVersions: protocolVersions)
        server.respond { request in
            if unauthorized { return .response(status: 401, body: Data("{}".utf8)) }
            if sendsAnswer == .offline, request.method == "POST", request.url.path.hasSuffix("/commands") {
                return .fail(.notConnectedToInternet)
            }
            return model.answer(request)
        }

        // An account's store: the legacy import records the account link the sync session needs.
        let account = LinkedAccount(id: "acct-1", email: "a@example.com", serverURL: server.serverURL,
            linkedAt: Date(timeIntervalSince1970: 1_789_000_000))
        let source = root.appendingPathComponent("document.json")
        try StoreDocumentCoding.makeEncoder().encode(StoreDocument(base: .empty, account: account)).write(to: source)
        let database = root.appendingPathComponent("store.sqlite3")
        let bridge = try RustBridgeRuntime()
        _ = try await bridge.importLegacyStore(.init(workspaceID: "acct-1", databasePath: database.path,
            sourcePath: source.path, now: "2026-09-21T00:00:00Z"))
        let runtime = try await bridge.openStore(workspaceID: "acct-1", databaseURL: database)

        let instant = Date(timeIntervalSince1970: 1_790_000_000)
        let policy = Data(#"{"weekly_review":false,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8)
        let host = try await RustSyncHost.start(
            workspaceID: "acct-1", databaseURL: database,
            binding: .init(accountID: "acct-1", scopeID: "scope-1", deviceID: "device-1", freshAuthentication: true),
            context: RustWorkspaceContext(now: instant, timeZone: "UTC", actorID: "acct-1", policy: policy),
            serverURL: server.serverURL,
            tokenStore: InMemorySessionTokenStore(tokens: [server.serverURL: "tok-1"]),
            urlSessionConfiguration: server.sessionConfiguration, manualRoundTimeout: 20)
        let selection = RustWorkspaceSelection(runtime: runtime,
            facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
            transport: host, account: account, startup: .prepared)
        let workspace = Workspace(store: ControlledStore(), sync: nil, rust: selection, now: { instant })
        return Rig(root: root, server: server, model: model, host: host, workspace: workspace)
    }
}

// MARK: - A small sync-v1 server

/// Just enough of sync-v1 for one scope: capabilities, an empty recovery snapshot, device
/// registration, command intake that commits what it is sent, and the feed of what was committed.
private final class SyncModel: Sendable {
    private struct Transaction {
        var seq: Int
        var source: String
        var changes: [[String: Any]]
    }

    private struct State {
        var transactions: [Transaction] = []
        var commands = 0
        /// Snapshot ID to its watermark. Every snapshot has its own ID, as the server's do.
        var snapshots: [String: Int] = [:]
    }

    private static let scope = "scope-1"
    private static let generation = "generation-1"
    private static let now = "2026-10-10T09:00:00Z"
    /// sha-256 of `[]`, the stream of an empty snapshot.
    private static let emptyDigest = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"

    private let state = Mutex(State())
    private let versions: [Int]

    init(protocolVersions: [Int]) { versions = protocolVersions }

    var commandsSeen: Int { state.withLock { $0.commands } }

    func commitExternal(taskID: String, title: String) {
        state.withLock { state in
            let seq = state.transactions.count + 1
            state.transactions.append(
                Transaction(seq: seq, source: UUID().uuidString.lowercased(),
                            changes: [Self.taskChange(id: taskID, title: title, version: seq)]))
        }
    }

    func answer(_ request: StubRequest) -> StubReply {
        let path = request.url.path.replacingOccurrences(of: "/api/sync/v1", with: "")
        let query = URLComponents(url: request.url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        func param(_ name: String) -> String { query.first { $0.name == name }?.value ?? "" }
        switch (request.method, path) {
        case ("GET", "/capabilities"):
            return json([
                "protocol_versions": versions, "command_versions": [], "rule_version": 1,
                "projection_schema_version": 1, "storage_epoch": 1, "feed_generation": "feed-1",
                "scope_enabled": true, "limits": [String: Any](), "recovery": [String: Any](),
            ])
        case ("GET", "/changes"):
            let cursor = Int(param("cursor").replacingOccurrences(of: "cursor-", with: "")) ?? 0
            let rest = state.withLock { $0.transactions.filter { $0.seq > cursor } }
            return json([
                "from_cursor": param("cursor"),
                "transactions": rest.map {
                    ["transaction_id": "tx-\($0.seq)", "commit_seq": String($0.seq), "source_command_id": $0.source,
                     "changes": $0.changes] as [String: Any]
                },
                "has_more": false, "next_cursor": "cursor-\(rest.last?.seq ?? cursor)",
                "high_watermark": String(state.withLock { $0.transactions.count }),
            ])
        case ("POST", "/snapshots"):
            // Only ever taken with an empty base in these tests: the digest is that of `[]`.
            let (id, watermark) = state.withLock { state -> (String, Int) in
                let id = "snap-\(state.snapshots.count + 1)"
                state.snapshots[id] = state.transactions.count
                return (id, state.transactions.count)
            }
            return json([
                "snapshot_id": id, "watermark": String(watermark), "cursor": "cursor-\(watermark)",
                "page_count": 1, "record_count": 0, "total_bytes": 2, "sha256": Self.emptyDigest,
                "expires_at": "2026-10-10T09:30:00Z", "first_page_token": "token-0",
            ])
        case ("GET", _) where path.hasPrefix("/snapshots/"):
            let id = String(path.dropFirst("/snapshots/".count))
            let watermark = state.withLock { $0.snapshots[id] ?? 0 }
            return json([
                "snapshot_id": id, "watermark": String(watermark), "page_index": 0,
                "payload_base64": Data("[]".utf8).base64EncodedString(), "page_sha256": Self.emptyDigest,
                "has_more": false, "next_page_token": NSNull(),
            ])
        case ("POST", "/devices"):
            let body = (try? JSONSerialization.jsonObject(with: request.body)) as? [String: Any] ?? [:]
            return json([
                "device_id": body["device_id"] ?? "", "device_epoch": body["device_epoch"] ?? "",
                "epoch_status": "active",
            ])
        case ("POST", "/commands"):
            return commit(request.body)
        case ("GET", _) where path.hasPrefix("/commands/"):
            return json(["status": "not_found", "command_id": String(path.dropFirst("/commands/".count))])
        default:
            return .response(status: 404, body: Data("{}".utf8))
        }
    }

    /// Commits a `create_task` the way the server would: a transaction with the task, and a receipt.
    private func commit(_ body: Data) -> StubReply {
        let envelope = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any] ?? [:]
        let command = envelope["command_id"] as? String ?? ""
        let entity = envelope["entity_id"] as? String ?? ""
        let payload = envelope["payload"] as? [String: Any] ?? [:]
        let title = payload["title"] as? String ?? "Created"
        let seq = state.withLock { state -> Int in
            state.commands += 1
            let seq = state.transactions.count + 1
            state.transactions.append(
                Transaction(seq: seq, source: command, changes: [Self.taskChange(id: entity, title: title, version: seq)]))
            return seq
        }
        return json([
            "command_id": command, "outcome": "accepted", "has_changes": true, "commit_seq": String(seq),
            "result_versions": [Any](), "id_bindings": [Any](), "result_redacted": false,
            "result": NSNull(), "error": NSNull(),
        ])
    }

    private func json(_ body: [String: Any]) -> StubReply {
        var body = body
        body["correlation_id"] = "corr-1"
        body["scope_id"] = Self.scope
        body["server_generation"] = Self.generation
        body["server_now"] = Self.now
        let data = (try? JSONSerialization.data(withJSONObject: body)) ?? Data()
        return .response(status: 200, headers: ["Content-Type": "application/json"], body: data)
    }

    /// A task upsert as the feed carries it (the record shape the core's projection stores).
    private static func taskChange(id: String, title: String, version: Int) -> [String: Any] {
        [
            "entity_type": "task", "record_key": [id], "record_version": String(version),
            "edit_revision": "1", "operation": "upsert",
            "value": [
                "id": id, "title": title, "details": NSNull(), "state": "inbox", "project_id": NSNull(),
                "tag_ids": [Any](), "due_date": NSNull(), "priority": "none", "waiting_for": NSNull(),
                "waiting_since": NSNull(), "order_key": "0", "source_capture_ids": [Any](),
                "created_at": "2026-09-21T14:13:20Z", "updated_at": "2026-09-21T14:13:20Z",
                "completed_at": NSNull(), "cancelled_at": NSNull(), "revision": "1",
                "consecutive_stalled_formulations": 0, "formulation": NSNull(), "parked": NSNull(),
            ] as [String: Any],
        ]
    }
}
