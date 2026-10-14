import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation

@testable import BrainBuddyWorkspace

/// One install of the app in the rehearsal: its own folder, session token store, fault plan and
/// `Workspace`, built the way production builds them (`RustRuntimeLauncher` with the pilot switch on,
/// `HostRustAccountLifecycle`, `RustSyncTransportProvider` → `RustSyncHost`). Two devices signed into
/// one account are "the phone" and "the Mac".
@MainActor
final class RehearsalDevice {
    let name: String
    let session: RehearsalSession
    let root: URL
    let tokens: InMemorySessionTokenStore
    let plan: FaultPlan
    private(set) var workspace: Workspace
    /// The running scenario's recorder, which learns why a settle gave up.
    var recorder: RehearsalRecorder?
    private let environment: RustRuntimeEnvironment
    private let pilot: RustRuntimePilotSwitch
    private let ownsRoot: Bool

    /// `legacyDocument` is written as the install's retired `store.json` first (the launch imports it);
    /// `offline` keeps the install off the network from its first request.
    static func launch(
        _ session: RehearsalSession, name: String, root: URL? = nil, legacyDocument: Data? = nil, offline: Bool = false
    ) async throws -> RehearsalDevice {
        let folder = root ?? FileManager.default.temporaryDirectory.appendingPathComponent("bb-rehearsal-\(name)-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let tokens = InMemorySessionTokenStore()
        let plan = FaultPlan()
        plan.offline = offline
        if let legacyDocument { try legacyDocument.write(to: folder.appendingPathComponent("store.json")) }
        let environment = RustRuntimeEnvironment(
            location: .directory(folder), legacyStoreURL: folder.appendingPathComponent("store.json"),
            bridge: try RustBridgeRuntime(),
            transports: RustSyncTransportProvider(
                tokenStore: tokens, identity: .iOS,
                transportWrapper: { FaultingRustSyncTransport(wrapping: $0, plan: plan) }),
            server: APIRustAccountServer(tokenStore: tokens, identity: .iOS))
        let pilot = RustRuntimePilotSwitch(suiteName: "bb-rehearsal-\(UUID().uuidString)")
        pilot.set(true)
        let workspace = try await Self.open(environment, pilot)
        return RehearsalDevice(name: name, session: session, root: folder, tokens: tokens, plan: plan, workspace: workspace,
                               environment: environment, pilot: pilot, ownsRoot: root == nil)
    }

    private init(name: String, session: RehearsalSession, root: URL, tokens: InMemorySessionTokenStore, plan: FaultPlan,
                 workspace: Workspace, environment: RustRuntimeEnvironment, pilot: RustRuntimePilotSwitch, ownsRoot: Bool) {
        self.name = name
        self.session = session
        self.root = root
        self.tokens = tokens
        self.plan = plan
        self.workspace = workspace
        self.environment = environment
        self.pilot = pilot
        self.ownsRoot = ownsRoot
    }

    /// The launch: select (or resume) the runtime, build the workspace over it, load.
    static func open(_ environment: RustRuntimeEnvironment, _ pilot: RustRuntimePilotSwitch) async throws -> Workspace {
        switch await RustRuntimeLauncher(environment: environment, pilot: pilot).resolve() {
        case .rust(let selection, let lifecycle):
            let workspace = Workspace(store: ControlledStore(), sync: nil, rust: selection, rustLifecycle: lifecycle)
            await workspace.load()
            return workspace
        case .legacy(let reason): throw RehearsalError.backend("the launch stayed legacy: \(reason)")
        case .unavailable(let code): throw RehearsalError.backend("the Rust store is unavailable: \(code)")
        }
    }

    /// Quits the app and starts it again over the same folder: the runtime closes, a new launch resumes
    /// the persisted selection.
    func relaunch() async throws {
        await workspace.closeRuntime()
        workspace = try await Self.open(environment, pilot)
    }

    func close() async {
        await workspace.closeRuntime()
        if ownsRoot { try? FileManager.default.removeItem(at: root) }
    }

    // MARK: Account

    /// Signs in through the production lifecycle (login, link, first-sign-in merge, sync host).
    func signIn(_ label: String) async throws {
        let account = session.account(label)
        // The login goes through the app's REST client, not the counted transport: count it here.
        guard RehearsalBudget.shared.spend() else { throw RehearsalError.budgetExhausted }
        try await workspace.signIn(serverURL: session.serverURL, email: account.email, password: account.password)
        // A prod run proves who it is signed in as before it writes anything.
        let signedIn = try session.email(token: token())
        guard session.accounts.values.contains(where: { $0.email.lowercased() == signedIn.email.lowercased() }) else {
            throw RehearsalError.unexpectedIdentity
        }
    }

    func token() throws -> String {
        guard let token = try tokens.token(for: session.serverURL) else { throw RehearsalError.backend("\(name) holds no session") }
        return token
    }

    // MARK: Work

    @discardableResult
    func capture(_ text: String) async throws -> TaskID {
        try await workspace.capture(CaptureDraft(text: text), editorID: "scene:\(name):capture")
    }

    func retitle(_ id: TaskID, _ title: String) async throws {
        await workspace.prepareTaskDetail(id)
        try await workspace.updateTask(id, TaskChanges(title: .set(title)), editorID: "scene:\(name):edit")
    }

    func move(_ id: TaskID, to list: OpenList) async throws {
        await workspace.prepareTaskDetail(id)
        try await workspace.moveTask(id, to: list, editorID: "scene:\(name):move")
    }

    /// Titles by open list as this device shows them now.
    func titles() async -> [OpenList: [String]] {
        var result: [OpenList: [String]] = [:]
        for list in OpenList.allCases {
            await workspace.prepareList(.list(list))
            result[list] = workspace.list(.list(list)).sections.flatMap(\.tasks).map(\.title)
        }
        return result
    }

    func allTitles() async -> [String] { await titles().values.flatMap { $0 }.sorted() }

    func taskID(titled title: String) async -> TaskID? {
        for list in OpenList.allCases {
            await workspace.prepareList(.list(list))
            if let task = workspace.list(.list(list)).sections.flatMap(\.tasks).first(where: { $0.title == title }) { return task.id }
        }
        return nil
    }

    func serverTitles() throws -> [String] { try session.titles(token: token()) }

    // MARK: Network

    /// Airplane mode: the host is told the network is gone, and nothing leaves the device.
    func setOffline(_ offline: Bool) async {
        plan.offline = offline
        workspace.networkAvailabilityChanged(isAvailable: !offline)
        await workspace.waitForNetworkUpdates()
    }

    /// Syncs until nothing waits (and `until` holds), or `timeout` passes. False on timeout.
    @discardableResult
    func settle(timeout: TimeInterval = 60, until: (() async -> Bool)? = nil) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            await workspace.syncNow()
            await workspace.refreshRustStatus()
            if workspace.pendingChangeCount == 0, await until?() ?? true { return true }
            try? await Task.sleep(for: .milliseconds(200))
        }
        recorder?.observe("settleFailed.\(name)", diagnostics)
        plan.events.compactMap(\.correlationID).prefix(3).forEach { recorder?.correlation($0) }
        return false
    }

    /// Status, queue, issues and what the fault plan saw: for a result record that did not settle.
    var diagnostics: String {
        var outcomes: [String: Int] = [:]
        for event in plan.events {
            let route = event.path.split(separator: "?").first.map(String.init)?.replacingOccurrences(of: "/api/sync/v1", with: "") ?? event.path
            outcomes["\(route) \(event.outcome)\(event.code.map { " " + $0 } ?? "")", default: 0] += 1
        }
        let histogram = outcomes.sorted { $0.key < $1.key }.map { "\($0.key)x\($0.value)" }.joined(separator: ",")
        return "status=\(workspace.syncStatus) pending=\(workspace.pendingChangeCount) issues=\(workspace.runtimeIssues.count) "
            + "transportUnavailable=\(workspace.runtimeTransportUnavailable) events=[\(histogram)]"
    }

    /// Settles every device; true when all did.
    static func settle(_ devices: RehearsalDevice...) async -> Bool {
        var all = true
        for device in devices { if await !device.settle() { all = false } }
        return all
    }

    /// Waits for `condition`, syncing between looks.
    func eventually(timeout: TimeInterval = 30, _ condition: () async -> Bool) async -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if await condition() { return true }
            await workspace.syncNow()
            try? await Task.sleep(for: .milliseconds(100))
        }
        return false
    }

    var pending: Int { workspace.pendingChangeCount }
}
