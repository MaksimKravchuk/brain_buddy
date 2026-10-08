import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

/// A request that takes `duration` to answer (the fake server answers at once, so the shared
/// clock moves instead): only the task pull, the long part of a cycle.
final class PullTimingTransport: HTTPTransport {
    private let inner: any HTTPTransport
    private let clock: ManualClock
    private let duration: TimeInterval

    init(_ inner: any HTTPTransport, clock: ManualClock, duration: TimeInterval) {
        self.inner = inner
        self.clock = clock
        self.duration = duration
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let response = try await inner.send(request)
        if request.method == .get, request.url.path.hasSuffix("/tasks") { clock.advance(by: duration) }
        return response
    }
}

/// One app on one device, wired as the apps wire it: a real `SyncEngine` with the device's
/// `ClientIdentity` over the store its `Workspace` writes, on manual timers and the world's
/// shared clock and server. The foreground tick is driven by hand: `tick()` is the 15 s timer
/// firing, with the clock moved to it first.
@MainActor
final class WiredDevice {
    let world: World
    let identity: ClientIdentity
    let store: any DocumentStore
    let tokens: any SessionTokenStore
    /// This device's connection to the shared server; its log is what this device sent.
    let fake: FakeServerTransport
    let transport: any HTTPTransport
    let ids: IDSequence
    private(set) var engineScheduler = ManualSyncScheduler()
    private(set) var tickScheduler = ManualSyncScheduler()
    private(set) var engine: SyncEngine
    private(set) var workspace: Workspace
    /// When the foreground tick fires next.
    private(set) var nextTick = Date.distantFuture

    init(
        world: World, identity: ClientIdentity, namespace: Int, store: any DocumentStore = InMemoryDocumentStore(),
        tokens: any SessionTokenStore = InMemorySessionTokenStore(), pullDuration: TimeInterval = 0,
        wrapping wrap: (any HTTPTransport) -> any HTTPTransport = { $0 }
    ) {
        self.world = world
        self.identity = identity
        self.store = store
        self.tokens = tokens
        fake = world.server.makeTransport()
        transport = wrap(PullTimingTransport(fake, clock: world.clock, duration: pullDuration))
        ids = IDSequence(namespace: namespace)
        (engine, workspace) = Self.assemble(
            world: world, identity: identity, store: store, tokens: tokens, transport: transport, ids: ids,
            engineScheduler: engineScheduler, tickScheduler: tickScheduler)
    }

    private static func assemble(
        world: World, identity: ClientIdentity, store: any DocumentStore, tokens: any SessionTokenStore,
        transport: any HTTPTransport, ids: IDSequence, engineScheduler: ManualSyncScheduler,
        tickScheduler: ManualSyncScheduler
    ) -> (SyncEngine, Workspace) {
        let engine = SyncEngine(
            store: store, tokenStore: tokens, transport: transport, now: world.clock.provider,
            configuration: SyncConfiguration(
                scheduler: engineScheduler, jitter: { 0.5 }, pullInterval: SyncTiming.pullAge, clientVersion: "test"),
            identity: identity)
        let workspace = Workspace(
            store: store, sync: engine, now: world.clock.provider, makeID: { ids.next() }, tickScheduler: tickScheduler)
        return (engine, workspace)
    }

    /// Loads the store, as the app does at launch, and waits for that first sync.
    func launch() async {
        await workspace.load()
        await settle()
    }

    /// Quits and opens the app again over the same store and session. It is back in the
    /// foreground, with the network the path monitor reports.
    func relaunch(isOnline: Bool = true) async {
        await settle()
        engineScheduler = ManualSyncScheduler()
        tickScheduler = ManualSyncScheduler()
        (engine, workspace) = Self.assemble(
            world: world, identity: identity, store: store, tokens: tokens, transport: transport, ids: ids,
            engineScheduler: engineScheduler, tickScheduler: tickScheduler)
        // The path monitor reports only after launch; until then requests fail.
        if !isOnline { fake.inject(.offline, times: 1_000) }
        await launch()
        if !isOnline { await networkChanged(isAvailable: false) }
        await foreground()
    }

    func signIn(email: String = World.email, password: String = World.password) async throws {
        try await workspace.signIn(serverURL: FakeBrainBuddyServer.baseURL, email: email, password: password)
        await settle()
    }

    /// The app became active: one pull now and the tick from here on.
    func foreground() async {
        let armedAt = world.clock.now()
        await workspace.setForegroundActive(true)
        nextTick = armedAt.addingTimeInterval(SyncTiming.periodicTick)
        await settle()
    }

    /// The tick timer's 15 s are up: time reaches the tick, the engine gets `.periodic`, and the
    /// next tick is 15 s after this one.
    ///
    /// `openTask`: the title of the task whose detail the person has open. A child written on the
    /// server leaves its task's revision alone, so the list pull never shows it; the open detail
    /// asks for the task again (`refreshTaskDetails`) on the tick.
    func tick(refreshing openTask: String? = nil) async {
        if world.clock.now() < nextTick { world.clock.set(nextTick) }
        nextTick = world.clock.now().addingTimeInterval(SyncTiming.periodicTick)
        await tickScheduler.runNext()
        if let openTask, let id = workspace.task(titled: openTask)?.id { await workspace.refreshTaskDetails(id) }
        await settle()
    }

    func networkChanged(isAvailable: Bool) async {
        workspace.networkAvailabilityChanged(isAvailable: isAvailable)
        await settle()
    }

    /// Waits until connectivity updates reached the engine, no cycle runs, and every change the
    /// workspace applied is in the store.
    func settle() async {
        await workspace.waitForNetworkUpdates()
        await engine.waitUntilIdle()
        await workspace.flush()
    }

    /// Runs the sync timer that is waiting (the debounce, or a retry) and the cycle it starts.
    func fireNextTimer() async {
        await engineScheduler.runNext()
        await settle()
    }

    /// Task pulls this device has made.
    var pulls: Int { fake.requests.filter { $0.method == .get && $0.url.path.hasSuffix("/tasks") }.count }

    /// Expects the device to show exactly what the server holds, record for record.
    func expectInSyncWithServer(sourceLocation: SourceLocation = #_sourceLocation) throws {
        let onDevice = try AccountData(device: workspace.state)
        let onServer = AccountData(server: world.snapshot).restrictingInactive(to: onDevice)
        #expect(onDevice == onServer, sourceLocation: sourceLocation)
    }
}

/// Two apps on one account, the Mac's (`brainbuddy-macos`) and the iPhone's (`brainbuddy-ios`),
/// converging through one fake server under the cadences of contracts/sync-status.md §1:
/// 2 s debounce, 15 s ticks, 30 s pull age and a 1.5 s pull.
@MainActor
@Suite("Mac and iPhone converge")
struct MacIPhoneConvergenceTests {
    struct Change {
        var name: String
        var apply: @MainActor (Workspace) throws -> Void
        var arrived: @MainActor (Workspace) -> Bool
        /// The title of the task whose detail is open on the receiver, for changes only a detail read shows.
        var openDetail: String?
    }

    static let pullDuration: TimeInterval = 1.5

    /// A Mac and an iPhone, both signed in and in the foreground, holding the same baseline.
    static func pair(_ world: World) async throws -> (mac: WiredDevice, phone: WiredDevice) {
        let mac = WiredDevice(
            world: world, identity: .macOS(version: "0.1.0"), namespace: 1, pullDuration: pullDuration)
        let phone = WiredDevice(world: world, identity: .iOS, namespace: 2, pullDuration: pullDuration)
        await mac.launch()
        await phone.launch()
        try await mac.signIn()
        let app = mac.workspace
        try app.createProject(name: "Garden")
        for name in ["Rename me", "Recolour me", "Outcome me", "Archive me"] { try app.createProject(name: name) }
        for name in ["calls", "Rename tag", "Delete tag"] { try app.createTag(name: name) }
        for title in [
            "Retitle me", "Write notes", "Plan trip", "Assign project", "Tag me", "Date me", "Finish me", "Drop me",
            "Subtask host", "Comment host",
        ] {
            try app.capture(CaptureDraft(text: title, list: .next))
        }
        await mac.settle()
        await mac.workspace.syncNow()
        try await phone.signIn()
        await phone.foreground()
        await mac.foreground()
        try mac.expectInSyncWithServer()
        try phone.expectInSyncWithServer()
        return (mac, phone)
    }

    /// One change of each kind FR-007 lists, applied on the sender and looked for on the receiver by name.
    static let changes: [Change] = [
        Change(
            name: "a new task",
            apply: { try $0.capture(CaptureDraft(text: "Brand new task", list: .next)) },
            arrived: { $0.task(titled: "Brand new task") != nil }),
        Change(
            name: "a task's title",
            apply: { try $0.updateTask(try taskID($0, "Retitle me"), TaskChanges(title: .set("Retitled"))) },
            arrived: { $0.task(titled: "Retitled") != nil }),
        Change(
            name: "a task's notes",
            apply: { try $0.updateTask(try taskID($0, "Write notes"), TaskChanges(details: .set("Bring the keys"))) },
            arrived: { $0.task(titled: "Write notes")?.details == "Bring the keys" }),
        Change(
            name: "a task moved to Waiting for",
            apply: { try $0.moveTask(try taskID($0, "Plan trip"), to: .waiting, waitingFor: "Ana") },
            arrived: { $0.task(titled: "Plan trip")?.state == .waiting && $0.task(titled: "Plan trip")?.waitingFor == "Ana" }),
        Change(
            name: "a task's project",
            apply: {
                try $0.updateTask(
                    try taskID($0, "Assign project"), TaskChanges(projectID: .set(try projectID($0, "Garden"))))
            },
            arrived: { projectName(of: "Assign project", in: $0) == "Garden" }),
        Change(
            name: "a task's tags",
            apply: {
                try $0.updateTask(try taskID($0, "Tag me"), TaskChanges(tagIDs: .set([try tagID($0, "calls")])))
            },
            arrived: { w in (w.task(titled: "Tag me")?.tagIDs ?? []).compactMap { w.tag($0)?.name } == ["calls"] }),
        Change(
            name: "a task's due date and priority",
            apply: {
                try $0.updateTask(
                    try taskID($0, "Date me"), TaskChanges(dueDate: .set($0.today.adding(days: 3)), priority: .set(.high)))
            },
            arrived: { w in
                w.task(titled: "Date me")?.priority == .high && w.task(titled: "Date me")?.dueDate == w.today.adding(days: 3)
            }),
        Change(
            name: "a completed task",
            apply: { try $0.completeTask(try taskID($0, "Finish me")) },
            arrived: { $0.task(titled: "Finish me")?.state == .completed }),
        Change(
            name: "a cancelled task",
            apply: { try $0.cancelTask(try taskID($0, "Drop me")) },
            arrived: { $0.task(titled: "Drop me")?.state == .cancelled }),
        Change(
            name: "a subtask",
            apply: { try $0.addSubtask(to: try taskID($0, "Subtask host"), title: "Pack") },
            arrived: { $0.task(titled: "Subtask host")?.subtasks.map(\.title) == ["Pack"] },
            openDetail: "Subtask host"),
        Change(
            name: "a comment",
            apply: { try $0.addComment(to: try taskID($0, "Comment host"), body: "Mind the gap") },
            arrived: { $0.task(titled: "Comment host")?.comments.map(\.body) == ["Mind the gap"] },
            openDetail: "Comment host"),
        Change(
            name: "a new project",
            apply: { try $0.createProject(name: "Brand new project") },
            arrived: { w in w.projects().contains { $0.project.name == "Brand new project" } }),
        Change(
            name: "a project's name",
            apply: { try $0.renameProject(try projectID($0, "Rename me"), to: "Renamed") },
            arrived: { w in w.projects().contains { $0.project.name == "Renamed" } }),
        Change(
            name: "a project's colour",
            apply: { try $0.setProjectColor(try projectID($0, "Recolour me"), color: "#22C55E") },
            arrived: { w in w.projects().first { $0.project.name == "Recolour me" }?.project.color == "#22C55E" }),
        Change(
            name: "a project's desired outcome",
            apply: { try $0.setProjectOutcome(try projectID($0, "Outcome me"), outcome: "Done by May") },
            arrived: { w in w.projects().first { $0.project.name == "Outcome me" }?.project.desiredOutcome == "Done by May" }),
        Change(
            name: "an archived project",
            apply: { try $0.archiveProject(try projectID($0, "Archive me")) },
            arrived: { w in w.projects(archived: true).contains { $0.project.name == "Archive me" } }),
        Change(
            name: "a new tag",
            apply: { try $0.createTag(name: "fresh") },
            arrived: { w in w.tags().contains { $0.tag.name == "fresh" } }),
        Change(
            name: "a tag's name",
            apply: { try $0.renameTag(try tagID($0, "Rename tag"), to: "Renamed tag") },
            arrived: { w in w.tags().contains { $0.tag.name == "Renamed tag" } }),
        Change(
            name: "a deleted tag",
            apply: { try $0.deleteTag(try tagID($0, "Delete tag")) },
            arrived: { w in !w.tags().contains { $0.tag.name == "Delete tag" } }),
    ]

    static func taskID(_ workspace: Workspace, _ title: String) throws -> TaskID {
        try #require(workspace.task(titled: title), "no task \(title)").id
    }

    static func projectID(_ workspace: Workspace, _ name: String) throws -> ProjectID {
        try #require(workspace.projects(archived: false).first { $0.project.name == name }, "no project \(name)").id
    }

    static func tagID(_ workspace: Workspace, _ name: String) throws -> TagID {
        try #require(workspace.tags().first { $0.tag.name == name }, "no tag \(name)").id
    }

    static func projectName(of title: String, in workspace: Workspace) -> String? {
        workspace.task(titled: title)?.projectID.flatMap { workspace.project($0)?.name }
    }

    /// Applies `change` on `sender` at the worst phase for `receiver`, then lets time run as it does
    /// until the receiver holds it, and returns how long that took.
    ///
    /// The worst phase: `receiver`'s next tick is the one that pulls, and the change is made 2 s
    /// before it, so the sender's debounce lands just after that pull has read the server.
    static func secondsToConverge(
        _ world: World, sender: WiredDevice, receiver: WiredDevice, _ change: Change
    ) async throws -> TimeInterval {
        func lastPull() -> Date { receiver.workspace.document.sync.lastPullAt ?? .distantPast }
        while receiver.nextTick.timeIntervalSince(lastPull()) < SyncTiming.pullAge {
            await receiver.tick(refreshing: change.openDetail)
        }
        let pullAt = receiver.nextTick
        let start = pullAt.addingTimeInterval(-1.99)
        if world.clock.now() < start { world.clock.set(start) }
        let began = world.clock.now()
        try change.apply(sender.workspace)
        await sender.workspace.flush()

        let debounceFires = began.addingTimeInterval(2)
        var sent = false
        while !change.arrived(receiver.workspace), world.clock.now().timeIntervalSince(began) < 120 {
            if !sent, debounceFires <= receiver.nextTick {
                if world.clock.now() < debounceFires { world.clock.set(debounceFires) }
                await sender.fireNextTimer()
                sent = true
            } else {
                await receiver.tick(refreshing: change.openDetail)
            }
        }
        return world.clock.now().timeIntervalSince(began)
    }

    @Test("021-SC-001 021-FR-007 021-FR-032 021-FR-006 every kind of change reaches the other device within 60 s at the worst tick phase, both ways")
    func changesConvergeWithinAMinute() async throws {
        var slowest: TimeInterval = 0
        for (senderIsMac, label) in [(true, "Mac to iPhone"), (false, "iPhone to Mac")] {
            let world = World()
            let (mac, phone) = try await Self.pair(world)
            let (sender, receiver) = senderIsMac ? (mac, phone) : (phone, mac)
            for change in Self.changes {
                let seconds = try await Self.secondsToConverge(world, sender: sender, receiver: receiver, change)
                #expect(change.arrived(receiver.workspace), "\(label): \(change.name) never arrived")
                #expect(seconds <= 60, "\(label): \(change.name) took \(seconds) s")
                slowest = max(slowest, seconds)
            }
            await receiver.settle()
            await sender.settle()
            try mac.expectInSyncWithServer()
            try phone.expectInSyncWithServer()
            #expect(sender.fake.requests.allSatisfy { $0.header("X-Client")?.hasPrefix(sender.identity.name) == true })
        }
        #expect(slowest > 40, "the worst phase is the slow one: a pull every 45 s, plus the debounce")
    }

    @Test("021-SC-002 021-FR-008 021-FR-010 20 changes offline, a relaunch, a lost reply and a reconnect: each is on the server once, and the iPhone shows the same")
    func offlineMatrix() async throws {
        let world = World()
        let (mac, phone) = try await Self.pair(world)
        await mac.networkChanged(isAvailable: false)
        world.clock.advance(by: 60)
        let app = mac.workspace

        for number in 1...6 { try app.capture(CaptureDraft(text: "Offline task \(number)", list: .next)) }  // 6
        try app.capture(CaptureDraft(text: "Offline with project @Garden #calls", list: .next))  // 7
        try app.updateTask(try Self.taskID(app, "Retitle me"), TaskChanges(title: .set("Edited offline")))  // 8
        try app.updateTask(try Self.taskID(app, "Write notes"), TaskChanges(details: .set("Notes offline")))  // 9
        try app.updateTask(try Self.taskID(app, "Date me"), TaskChanges(dueDate: .set(app.today), priority: .set(.high)))  // 10
        try app.completeTask(try Self.taskID(app, "Finish me"))  // 11
        try app.cancelTask(try Self.taskID(app, "Drop me"))  // 12
        let host = try Self.taskID(app, "Subtask host")
        let step = try app.addSubtask(to: host, title: "Offline subtask")  // 13
        try app.transitionSubtask(step, in: host, .complete)  // 14
        let commentHost = try Self.taskID(app, "Comment host")
        let note = try app.addComment(to: commentHost, body: "Offline comment")  // 15
        try app.editComment(note, in: commentHost, body: "Offline comment, edited")  // 16
        try app.renameProject(try Self.projectID(app, "Rename me"), to: "Renamed offline")  // 17
        try app.archiveProject(try Self.projectID(app, "Archive me"))  // 18
        try app.createTag(name: "offline tag")  // 19
        try app.deleteTag(try Self.tagID(app, "Delete tag"))  // 20
        await mac.settle()
        let before = VisibleState(app)
        #expect(app.pendingChangeCount > 0)
        #expect(world.snapshot.tasks.count == 10, "nothing reached the server")

        // Quit and open again, still offline: nothing is lost.
        await mac.relaunch(isOnline: false)
        #expect(VisibleState(mac.workspace) == before)
        #expect(mac.workspace.pendingChangeCount > 0)

        // The network is back. The first create is applied by the server but its reply is lost.
        world.clock.advance(by: 120)
        mac.fake.clearFaults()
        mac.fake.inject(.dropResponse, matching: { $0.method == .post && $0.url.path.hasSuffix("/tasks") })
        await mac.networkChanged(isAvailable: true)
        for _ in 0..<5 where mac.workspace.pendingChangeCount > 0 {
            world.clock.advance(by: 30)
            await mac.fireNextTimer()
        }

        #expect(mac.workspace.pendingChangeCount == 0)
        #expect(mac.workspace.issues.isEmpty)
        let server = world.snapshot
        let titles = server.tasks.values.map(\.title)
        #expect(Set(titles).count == titles.count, "no change applied twice")
        for number in 1...6 { #expect(titles.filter { $0 == "Offline task \(number)" }.count == 1) }
        #expect(titles.filter { $0 == "Offline with project" }.count == 1)
        #expect(server.tasks.count == 17)
        #expect(server.task(titled: "Edited offline") != nil)
        #expect(server.task(titled: "Write notes")?.details == "Notes offline")
        #expect(server.task(titled: "Date me")?.priority == .high)
        #expect(server.task(titled: "Finish me")?.state == .completed)
        #expect(server.task(titled: "Drop me")?.state == .cancelled)
        #expect(server.task(titled: "Subtask host")?.subtasks.map(\.title) == ["Offline subtask"])
        #expect(server.task(titled: "Subtask host")?.subtasks.map(\.state) == [.completed])
        #expect(server.task(titled: "Comment host")?.comments.map(\.body) == ["Offline comment, edited"])
        #expect(server.project(named: "Renamed offline") != nil)
        #expect(server.project(named: "Archive me")?.state == .archived)
        #expect(server.tag(named: "offline tag") != nil)
        #expect(server.tag(named: "Delete tag")?.state == .deleted)
        try mac.expectInSyncWithServer()

        // The iPhone gets the same set. A child written on the server leaves its task alone, so the
        // iPhone reads subtasks and comments when the task's detail opens.
        await phone.workspace.syncNow()
        for title in ["Subtask host", "Comment host"] {
            await phone.workspace.refreshTaskDetails(try Self.taskID(phone.workspace, title))
        }
        await phone.settle()
        try phone.expectInSyncWithServer()
        #expect(phone.workspace.task(titled: "Edited offline") != nil)
        #expect(phone.workspace.task(titled: "Offline with project") != nil)
    }

    @Test("021-FR-011 the same field edited offline on both resolves to the last to reach the server, field by field")
    func sameFieldEditedOfflineOnBoth() async throws {
        let world = World()
        let (mac, phone) = try await Self.pair(world)
        await mac.networkChanged(isAvailable: false)
        await phone.networkChanged(isAvailable: false)
        try mac.workspace.updateTask(
            try Self.taskID(mac.workspace, "Retitle me"), TaskChanges(title: .set("Mac title"), details: .set("Mac notes")))
        try phone.workspace.updateTask(
            try Self.taskID(phone.workspace, "Retitle me"), TaskChanges(title: .set("Phone title"), priority: .set(.high)))
        await mac.settle()
        await phone.settle()

        await mac.networkChanged(isAvailable: true)
        await phone.networkChanged(isAvailable: true)  // reaches the server last
        await mac.workspace.syncNow()
        await mac.settle()

        let server = try #require(world.snapshot.tasks.values.first { $0.state == .next && $0.title == "Phone title" })
        #expect(server.details == "Mac notes", "a field only one device touched survives")
        #expect(server.priority == .high)
        #expect(world.snapshot.task(titled: "Mac title") == nil)
        for device in [mac, phone] {
            #expect(device.workspace.issues.isEmpty)
            let task = try #require(device.workspace.task(titled: "Phone title"))
            #expect(task.details == "Mac notes")
            #expect(task.priority == .high)
            try device.expectInSyncWithServer()
        }
    }

    @Test("021-SC-006 archiving on one device and unarchiving on the other keeps every membership")
    func archiveAndUnarchiveKeepMemberships() async throws {
        let world = World()
        let (mac, phone) = try await Self.pair(world)
        let app = mac.workspace
        let garden = try Self.projectID(app, "Garden")
        for title in ["Assign project", "Tag me"] {
            try app.updateTask(try Self.taskID(app, title), TaskChanges(projectID: .set(garden)))
        }
        await app.syncNow()
        await phone.workspace.syncNow()
        #expect(Self.projectName(of: "Tag me", in: phone.workspace) == "Garden")

        try app.archiveProject(garden)
        await app.syncNow()
        await phone.workspace.syncNow()
        #expect(phone.workspace.projects(archived: true).contains { $0.project.name == "Garden" })
        #expect(Self.projectName(of: "Assign project", in: phone.workspace) == "Garden", "archiving keeps the project on its tasks")
        let archivedOnPhone = try #require(phone.workspace.projects(archived: true).first { $0.project.name == "Garden" }).id

        try phone.workspace.unarchiveProject(archivedOnPhone)
        await phone.workspace.syncNow()
        await app.syncNow()

        #expect(app.projects().contains { $0.project.name == "Garden" })
        for device in [mac, phone] {
            for title in ["Assign project", "Tag me"] { #expect(Self.projectName(of: title, in: device.workspace) == "Garden") }
            try device.expectInSyncWithServer()
        }
        let server = world.snapshot
        #expect(server.project(named: "Garden")?.state == .active)
        #expect(server.task(titled: "Tag me")?.projectID == server.project(named: "Garden")?.id)
        #expect(server.task(titled: "Assign project")?.projectID == server.project(named: "Garden")?.id)
    }

    @Test("021-FR-011 an offline capture into a project archived elsewhere lands without it, under one issue that says so")
    func captureIntoAProjectArchivedElsewhere() async throws {
        let world = World()
        let (mac, phone) = try await Self.pair(world)
        await mac.networkChanged(isAvailable: false)
        let garden = try Self.projectID(mac.workspace, "Garden")
        try mac.workspace.capture(CaptureDraft(text: "Order soil", list: .next, contextProjectID: garden))
        await mac.settle()

        try phone.workspace.archiveProject(try Self.projectID(phone.workspace, "Garden"))
        await phone.workspace.syncNow()
        await mac.networkChanged(isAvailable: true)
        await mac.workspace.syncNow()

        let task = try #require(world.snapshot.task(titled: "Order soil"))
        #expect(task.projectID == nil, "it lands without the project")
        let issue = try #require(mac.workspace.issues.first)
        #expect(mac.workspace.issues.count == 1)
        #expect(issue.message == "Project “Garden” was archived on another device, so the task was added without a project.")
        #expect(issue.referenceID?.isEmpty == false)
        #expect(SyncIssueDescriber.describe(issue, in: mac.workspace.state).attempted == "Add “Order soil” to Next actions")
        #expect(mac.workspace.pendingChangeCount == 0)
    }

    @Test("021-FR-004 a Mac with changes waiting for one account refuses another's sign-in and sends nothing")
    func accountSwitchIsRefused() async throws {
        let world = World()
        world.server.addAccount(email: "bob@example.com", password: "hunter2 hunter2", displayName: "Bob")
        let (mac, _) = try await Self.pair(world)
        await mac.networkChanged(isAvailable: false)
        try mac.workspace.capture(CaptureDraft(text: "For Ana only", list: .next))
        await mac.settle()
        mac.fake.clearLog()

        await #expect(
            throws: WorkspaceError.signInFailed(
                message: "Sign out first to use another account. Changes from the other account are still waiting on this Mac.",
                referenceID: nil)
        ) {
            try await mac.signIn(email: "bob@example.com", password: "hunter2 hunter2")
        }
        #expect(world.server.snapshot(email: "bob@example.com").tasks.isEmpty)
        #expect(mac.fake.requests.filter(FakeServerTransport.isMutation).isEmpty)
        #expect(mac.workspace.account?.email == World.email)
        #expect(mac.workspace.pendingChangeCount == 1)
        // Bob's session is ended, though only once the network is back.
        #expect(try mac.tokens.pendingLogouts().count == 1)
        await mac.networkChanged(isAvailable: true)
        #expect(world.server.liveSessionCount(email: "bob@example.com") == 0)
    }
}
