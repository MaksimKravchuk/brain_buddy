import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// User journeys through the real stack: `Workspace` over a document store,
/// a real `SyncEngine` on manual timers, and one `FakeBrainBuddyServer` that
/// every device talks to. Each journey checks what the person would see
/// (lists, badges, sync status, pending changes, sync issues) and what the
/// server ends up holding.
@MainActor
@Suite("Workspace end to end")
struct WorkspaceEndToEndTests {
    // MARK: Local first

    @Test("Work done without an account survives a relaunch and is uploaded on sign-in under the same ids")
    func localOnlyWorkIsUploadedOnSignIn() async throws {
        let world = World()
        let phone = await world.device()
        var app = phone.workspace

        // Capture: Smart Add creates the project and the tag on the spot.
        let draft = CaptureDraft(text: "Draft the agenda @Offsite #calls")
        let preview = app.capturePreview(draft)
        #expect(preview.title == "Draft the agenda")
        #expect(preview.project == ClassificationPreview(name: "Offsite", isNew: true))
        #expect(preview.tags == [ClassificationPreview(name: "calls", isNew: true)])
        let agenda = try app.capture(draft)
        let passport = try app.capture(CaptureDraft(text: "Renew passport"))
        let plumber = try app.capture(CaptureDraft(text: "Call the plumber #calls"))
        let italian = try app.capture(CaptureDraft(text: "Learn Italian"))
        let milk = try app.capture(CaptureDraft(text: "Buy milk"))
        let website = try app.capture(CaptureDraft(text: "Rewrite the website"))
        let offsite = try #require(app.task(agenda)?.projectID)
        let calls = try #require(app.tags().first { $0.tag.name == "calls" }).id
        #expect(app.task(plumber)?.tagIDs == [calls], "an existing tag is reused, not created twice")
        #expect(
            app.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.id) == [passport, plumber, italian, milk, website],
            "a task with a project is not in the Inbox"
        )
        #expect(app.counts().inbox == 5)

        // Process the inbox, one item at a time.
        world.clock.advance(by: 60)
        try app.moveTask(passport, to: .next)
        try app.moveTask(plumber, to: .waiting, waitingFor: "  Plumber to call back ")
        try app.moveTask(italian, to: .someday)
        try app.completeTask(milk)
        try app.cancelTask(website)
        try app.updateTask(passport, TaskChanges(dueDate: .set(app.today), priority: .set(.high)))
        #expect(app.list(.list(.inbox)).isEmpty)
        #expect(app.counts() == ListCounts(inbox: 0, next: 1, waiting: 1, someday: 1, overdue: 0, today: 1))
        #expect(app.task(plumber)?.waitingFor == "Plumber to call back")

        // Subtasks and comments.
        let photos = try app.addSubtask(to: passport, title: "Take photos")
        let form = try app.addSubtask(to: passport, title: "Fill the form")
        try app.transitionSubtask(photos, in: passport, .complete)
        try app.renameSubtask(form, in: passport, to: "Fill in the form")
        let note = try app.addComment(to: passport, body: "The office opens at 9.")
        try app.editComment(note, in: passport, body: "The office opens at 9, closed on Mondays.")

        // Organise: rename a project, archive another, delete a tag.
        try app.renameProject(offsite, to: "Team offsite")
        let garage = try app.createProject(name: "Garage")
        let shelves = try app.capture(CaptureDraft(text: "Sort the shelves", list: .next, contextProjectID: garage))
        try app.archiveProject(garage)
        let stamps = try app.capture(CaptureDraft(text: "Buy stamps #errands", list: .next))
        let errands = try #require(app.task(stamps)?.tagIDs.first)
        try app.deleteTag(errands)
        #expect(app.task(shelves)?.projectID == nil, "archiving removes the project from its tasks")
        #expect(app.projects().map(\.project.name) == ["Team offsite"])
        #expect(app.projects(archived: true).map(\.project.name) == ["Garage"])
        #expect(app.task(stamps)?.tagIDs == [])
        #expect(app.tags().map(\.tag.name) == ["calls"])

        await phone.settle()
        #expect(app.syncStatus == .localOnly)
        #expect(phone.transport.requests.isEmpty, "nothing needed the network")
        let before = VisibleState(app)
        #expect(before.titles(on: .project(offsite)) == ["Draft the agenda"])
        #expect(before.titles(on: .list(.inbox)) == ["Buy milk", "Rewrite the website"], "finished from the Inbox")
        #expect(before.titles(on: .tag(calls)) == ["Call the plumber", "Draft the agenda"])
        let pending = app.pendingChangeCount
        #expect(pending > 0)

        // Relaunch: the same data, read back from the store.
        await phone.relaunch()
        app = phone.workspace
        #expect(VisibleState(app) == before)
        #expect(app.pendingChangeCount == pending)
        #expect(app.syncStatus == .localOnly)
        #expect(phone.transport.requests.isEmpty)

        // Sign in: everything goes up, and the device keeps its own ids.
        world.clock.advance(by: 60)
        try await phone.signIn()
        #expect(app.account?.email == World.email)
        #expect(app.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        #expect(app.pendingChangeCount == 0)
        #expect(app.issues.isEmpty)
        #expect(phone.rejectedRequests.isEmpty)
        #expect(VisibleState(app) == before)
        try phone.expectInSyncWithServer()

        let server = world.snapshot
        #expect(
            server.tasks.values.map(\.title).sorted() == [
                "Buy milk", "Buy stamps", "Call the plumber", "Draft the agenda", "Learn Italian", "Renew passport",
                "Rewrite the website", "Sort the shelves",
            ]
        )
        let passportOnServer = try #require(server.task(titled: "Renew passport"))
        #expect(passportOnServer.state == .next)
        #expect(passportOnServer.priority == .high)
        #expect(passportOnServer.dueDate == app.today)
        #expect(passportOnServer.subtasks.map(\.title) == ["Take photos", "Fill in the form"])
        #expect(passportOnServer.subtasks.map(\.state) == [.completed, .open])
        #expect(passportOnServer.comments.map(\.body) == ["The office opens at 9, closed on Mondays."])
        #expect(server.task(titled: "Call the plumber")?.waitingFor == "Plumber to call back")
        #expect(server.task(titled: "Learn Italian")?.state == .someday)
        #expect(server.task(titled: "Buy milk")?.state == .completed)
        #expect(server.task(titled: "Rewrite the website")?.state == .cancelled)
        #expect(server.task(titled: "Draft the agenda")?.projectID == server.project(named: "Team offsite")?.id)
        #expect(server.task(titled: "Sort the shelves")?.projectID == nil)
        #expect(server.project(named: "Garage")?.state == .archived)
        #expect(server.task(titled: "Buy stamps")?.tagIDs == [])
        #expect(server.tag(named: "errands")?.state == .deleted)
        #expect(server.projects.count == 2)
        #expect(server.tags.count == 2)
    }

    @Test("Signing in where the account already has data merges projects and tags by name")
    func signInMergesWithTheAccountByName() async throws {
        let world = World()
        let laptop = await world.device()
        try await laptop.signIn()
        let report = try laptop.workspace.capture(CaptureDraft(text: "Quarterly report @Work #home", list: .next))
        await laptop.workspace.syncNow()

        world.clock.advance(by: 3_600)
        let phone = await world.device()
        let app = phone.workspace
        let plan = try app.capture(CaptureDraft(text: "Plan the week @work #Home", list: .next))
        let tulips = try app.capture(CaptureDraft(text: "Plant tulips @Garden", list: .someday))
        let localWork = try #require(app.task(plan)?.projectID)
        let localHome = try #require(app.task(plan)?.tagIDs.first)
        #expect(app.projects().map(\.project.name) == ["Garden", "work"])

        try await phone.signIn()

        let server = world.snapshot
        #expect(server.projects.values.map(\.name).sorted() == ["Garden", "Work"], "no second Work")
        #expect(server.tags.values.map(\.name) == ["home"])
        #expect(server.tasks.values.map(\.title).sorted() == ["Plan the week", "Plant tulips", "Quarterly report"])
        let work = try #require(server.project(named: "Work"))
        let home = try #require(server.tag(named: "home"))
        #expect(server.task(titled: "Plan the week")?.projectID == work.id)
        #expect(server.task(titled: "Plan the week")?.tagIDs == [home.id])
        #expect(phone.rejectedRequests.isEmpty, "merged before sending, not after a conflict")

        // The phone shows the account's project and tag in place of its own.
        #expect(app.projects().map(\.project.name) == ["Garden", "Work"])
        #expect(app.tags().map(\.tag.name) == ["home"])
        #expect(app.project(localWork) == nil)
        #expect(app.tag(localHome) == nil)
        let workOnPhone = try #require(app.projects().first { $0.project.name == "Work" })
        #expect(workOnPhone.openTaskCount == 2)
        #expect(VisibleState(app).titles(on: .project(workOnPhone.id)) == ["Plan the week", "Quarterly report"])
        #expect(app.task(plan)?.projectID == workOnPhone.id)
        #expect(app.task(tulips)?.state == .someday, "tasks keep their ids")
        #expect(app.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        #expect(app.pendingChangeCount == 0)
        #expect(app.issues.isEmpty)
        try phone.expectInSyncWithServer()

        // The laptop sees the phone's task in its own Work.
        world.clock.advance(by: 60)
        await laptop.workspace.syncNow()
        let workOnLaptop = try #require(laptop.workspace.task(report)?.projectID)
        #expect(VisibleState(laptop.workspace).titles(on: .project(workOnLaptop)) == ["Plan the week", "Quarterly report"])
        #expect(laptop.workspace.projects().count == 2)
        try laptop.expectInSyncWithServer()
    }

    // MARK: Offline while signed in

    @Test("Changes made while the server is unreachable wait, survive a relaunch, and go out once it answers")
    func changesWaitWhileTheServerIsUnreachable() async throws {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        var app = phone.workspace
        let dentist = try app.capture(CaptureDraft(text: "Book the dentist", list: .next))
        await app.syncNow()
        let syncedAt = world.clock.now()
        #expect(app.syncStatus == .idle(lastSyncedAt: syncedAt))

        // The connection drops; the path monitor has not noticed.
        world.clock.advance(by: 60)
        phone.transport.inject(.offline, times: 1_000)
        let call = try app.capture(CaptureDraft(text: "Call Sam"))
        let stamps = try app.capture(CaptureDraft(text: "Buy stamps", list: .next))
        try app.completeTask(dentist)
        await phone.settle()
        #expect(phone.scheduler.pendingDelays == [.seconds(2)], "a sync is due 2 s after the last change")
        await phone.fireNextTimer()
        #expect(app.syncStatus == .offline(lastSyncedAt: syncedAt))
        #expect(app.pendingChangeCount == 3)
        #expect(phone.scheduler.pendingDelays == [.seconds(2)], "a retry with backoff")

        // More work offline: shown at once. The first create was attempted, so
        // its edit waits on its own; the edit of the unsent one folds into it.
        try app.updateTask(call, TaskChanges(title: .set("Call Sam about Friday")))
        try app.updateTask(stamps, TaskChanges(priority: .set(.low)))
        await phone.settle()
        #expect(app.pendingChangeCount == 4)
        #expect(app.task(call)?.title == "Call Sam about Friday")
        #expect(app.issues.isEmpty)

        // Quit and reopen while still offline: nothing is lost.
        let before = VisibleState(app)
        await phone.relaunch()
        app = phone.workspace
        #expect(VisibleState(app) == before)
        #expect(app.syncStatus == .offline(lastSyncedAt: syncedAt))
        #expect(app.pendingChangeCount == 4)
        #expect(world.snapshot.tasks.count == 1)

        // The server answers again; the next retry sends everything.
        world.clock.advance(by: 30)
        phone.transport.clearFaults()
        await phone.fireNextTimer()
        #expect(app.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        #expect(app.pendingChangeCount == 0)
        #expect(VisibleState(app) == before)
        let server = world.snapshot
        #expect(
            server.tasks.values.map(\.title).sorted() == ["Book the dentist", "Buy stamps", "Call Sam about Friday"],
            "an attempt that never arrived is not duplicated"
        )
        #expect(server.task(titled: "Book the dentist")?.state == .completed)
        #expect(server.task(titled: "Buy stamps")?.priority == .low)
        try phone.expectInSyncWithServer()
    }

    @Test("When the device knows it is offline, nothing is attempted until the network returns")
    func nothingIsAttemptedWhileTheNetworkIsDown() async throws {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        let app = phone.workspace
        let syncedAt = world.clock.now()
        await phone.networkChanged(isAvailable: false)
        #expect(app.syncStatus == .offline(lastSyncedAt: syncedAt))
        phone.transport.clearLog()

        world.clock.advance(by: 60)
        let plants = try app.capture(CaptureDraft(text: "Water the plants @Home", list: .next))
        try app.capture(CaptureDraft(text: "Buy compost"))
        await phone.settle()
        await phone.fireNextTimer()
        await app.syncNow()
        #expect(phone.transport.requests.isEmpty)
        #expect(app.syncStatus == .offline(lastSyncedAt: syncedAt))
        #expect(app.pendingChangeCount == 3)
        #expect(app.counts().next == 1)

        world.clock.advance(by: 60)
        await phone.networkChanged(isAvailable: true)
        #expect(app.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        #expect(app.pendingChangeCount == 0)
        #expect(world.snapshot.tasks.values.map(\.title).sorted() == ["Buy compost", "Water the plants"])
        #expect(world.snapshot.task(titled: "Water the plants")?.projectID == world.snapshot.project(named: "Home")?.id)
        #expect(app.task(plants)?.serverID != nil)
        try phone.expectInSyncWithServer()
    }

    // MARK: Two devices

    @Test("Two devices edit different fields of one task offline: both edits are kept")
    func twoDevicesEditDifferentFields() async throws {
        let (world, phone, tablet, onPhone, onTablet) = try await phoneAndTabletOffline()
        try phone.workspace.updateTask(onPhone, TaskChanges(title: .set("Renew passport before May")))
        try tablet.workspace.updateTask(onTablet, TaskChanges(details: .set("Photos first"), priority: .set(.high)))

        await reconnect(world, first: phone, then: tablet)

        #expect(world.snapshot.tasks.count == 1)
        let server = try #require(world.snapshot.tasks.values.first)
        #expect(server.title == "Renew passport before May")
        #expect(server.details == "Photos first")
        #expect(server.priority == .high)
        for (device, id) in [(phone, onPhone), (tablet, onTablet)] {
            let task = try #require(device.workspace.task(id))
            #expect(task.title == "Renew passport before May")
            #expect(task.details == "Photos first")
            #expect(task.priority == .high)
            #expect(device.workspace.state.tasks.count == 1)
            #expect(device.workspace.issues.isEmpty)
            #expect(device.workspace.pendingChangeCount == 0)
            try device.expectInSyncWithServer()
        }
        #expect(phone.rejectedRequests.isEmpty)
        #expect(tablet.rejectedRequests.count == 1, "one stale revision, resolved by re-reading the task")
    }

    @Test("Two devices edit the same field offline: the edit that reaches the server last wins")
    func twoDevicesEditTheSameField() async throws {
        let (world, phone, tablet, onPhone, onTablet) = try await phoneAndTabletOffline()
        try phone.workspace.updateTask(onPhone, TaskChanges(title: .set("Renew passport in April")))
        try tablet.workspace.updateTask(onTablet, TaskChanges(title: .set("Renew passport in May")))

        await reconnect(world, first: phone, then: tablet)

        #expect(world.snapshot.tasks.values.map(\.title) == ["Renew passport in May"])
        #expect(phone.workspace.task(onPhone)?.title == "Renew passport in May")
        #expect(tablet.workspace.task(onTablet)?.title == "Renew passport in May")
        for device in [phone, tablet] {
            #expect(device.workspace.state.tasks.count == 1)
            #expect(device.workspace.issues.isEmpty)
            #expect(device.workspace.pendingChangeCount == 0)
            try device.expectInSyncWithServer()
        }
    }

    @Test("A task completed on one device while another moves it: the move becomes a sync issue")
    func completeOnOneDeviceWhileTheOtherMoves() async throws {
        let (world, phone, tablet, onPhone, onTablet) = try await phoneAndTabletOffline()
        try phone.workspace.completeTask(onPhone)
        try tablet.workspace.moveTask(onTablet, to: .someday)
        #expect(VisibleState(tablet.workspace).titles(on: .list(.someday)) == ["Renew passport"])

        await reconnect(world, first: phone, then: tablet)

        #expect(world.snapshot.tasks.count == 1)
        let server = try #require(world.snapshot.tasks.values.first)
        #expect(server.state == .completed)
        #expect(server.revision == 2, "only the completion changed the task")

        // The tablet: a completed task cannot be moved, so the move is set
        // aside where the person can read why; nothing is duplicated.
        let tabletApp = tablet.workspace
        #expect(tabletApp.task(onTablet)?.state == .completed)
        #expect(tabletApp.list(.list(.someday)).isEmpty)
        #expect(tabletApp.list(.history(.completed)).sections.flatMap(\.tasks).map(\.id) == [onTablet])
        #expect(tabletApp.state.tasks.count == 1)
        #expect(tabletApp.issues.map(\.message) == [GTDValidationError.taskNotOpen.message])
        #expect(tabletApp.issues.map(\.command) == [.transitionTask(.init(taskID: onTablet, action: .move, toList: .someday))])
        #expect(tabletApp.pendingChangeCount == 0)
        #expect(tabletApp.syncStatus.isIdle, "a change set aside does not make sync fail")
        try tablet.expectInSyncWithServer()

        #expect(phone.workspace.task(onPhone)?.state == .completed)
        #expect(phone.workspace.issues.isEmpty)
        try phone.expectInSyncWithServer()

        // Dismissing the issue removes it for good.
        let issue = try #require(tabletApp.issues.first)
        tabletApp.dismissIssue(issue.id)
        await tablet.settle()
        #expect(tabletApp.issues.isEmpty)
        #expect(try await tablet.store.load()?.issues.isEmpty == true)
    }

    @Test("A capture offline with a tag another device deleted keeps its task and subtask, without the tag, everywhere")
    func captureWithATagDeletedElsewhere() async throws {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        try phone.workspace.capture(CaptureDraft(text: "Buy stamps #errand", list: .next))
        await phone.workspace.syncNow()
        world.clock.advance(by: 60)
        let tablet = await world.device()
        try await tablet.signIn()
        let errandOnTablet = try #require(tablet.workspace.tags().first { $0.tag.name == "errand" }).id
        await tablet.networkChanged(isAvailable: false)

        // On the tablet, offline: Smart Add reuses the tag it knows.
        world.clock.advance(by: 60)
        let milk = try tablet.workspace.capture(CaptureDraft(text: "Buy milk #errand", list: .next))
        _ = try tablet.workspace.addSubtask(to: milk, title: "Oat milk")
        #expect(tablet.workspace.task(milk)?.tagIDs == [errandOnTablet])

        // Meanwhile the phone deletes the tag.
        let errandOnPhone = try #require(phone.workspace.tags().first { $0.tag.name == "errand" }).id
        try phone.workspace.deleteTag(errandOnPhone)
        await phone.workspace.syncNow()
        #expect(world.snapshot.tag(named: "errand")?.state == .deleted)

        world.clock.advance(by: 60)
        await tablet.networkChanged(isAvailable: true)

        // The tablet: the task is kept, without the tag; nothing needs attention.
        let tabletApp = tablet.workspace
        #expect(tablet.rejectedRequests == ["POST /api/tasks → 400"], "refused once for the deleted tag")
        #expect(tabletApp.issues.isEmpty)
        #expect(tabletApp.pendingChangeCount == 0)
        #expect(tabletApp.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        #expect(tabletApp.task(milk)?.tagIDs == [])
        #expect(tabletApp.task(milk)?.subtasks.map(\.title) == ["Oat milk"])
        #expect(tabletApp.tags().isEmpty)
        #expect(VisibleState(tabletApp).titles(on: .list(.next)) == ["Buy milk", "Buy stamps"])
        try tablet.expectInSyncWithServer()

        let server = try #require(world.snapshot.task(titled: "Buy milk"))
        #expect(server.tagIDs == [])
        #expect(server.subtasks.map(\.title) == ["Oat milk"])

        // The phone picks it up as it is.
        world.clock.advance(by: 60)
        await phone.workspace.syncNow()
        await phone.settle()
        #expect(phone.workspace.task(titled: "Buy milk")?.tagIDs == [])
        #expect(phone.workspace.issues.isEmpty)
        try phone.expectInSyncWithServer()
    }

    // MARK: Session

    @Test("A revoked session asks to sign in again, keeps every change, and sends them after signing in")
    func revokedSessionKeepsChangesUntilSignIn() async throws {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        let app = phone.workspace
        let plants = try app.capture(CaptureDraft(text: "Water the plants", list: .next))
        await app.syncNow()

        // Signed out everywhere from the web (or the session expired).
        world.server.revokeSessions(email: World.email)
        world.clock.advance(by: 60)
        let tulips = try app.capture(CaptureDraft(text: "Plant tulips @Garden", list: .next))
        try app.completeTask(plants)
        await app.syncNow()

        #expect(app.syncStatus == .needsSignIn)
        #expect(app.pendingChangeCount == 3)
        #expect(app.issues.isEmpty)
        #expect(app.task(tulips)?.title == "Plant tulips")
        #expect(app.task(plants)?.state == .completed)
        #expect(app.account?.email == World.email, "still linked: only the session is gone")
        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(world.snapshot.tasks.values.map(\.state) == [.next])

        // Nothing is attempted until the person signs in, whatever asks for a sync.
        phone.transport.clearLog()
        try app.capture(CaptureDraft(text: "Buy bulbs"))
        await phone.settle()
        await phone.fireNextTimer()
        await app.syncNow()
        await phone.networkChanged(isAvailable: true)
        #expect(phone.transport.requests.isEmpty)
        #expect(app.syncStatus == .needsSignIn)
        #expect(app.pendingChangeCount == 4)
        let before = VisibleState(app)

        world.clock.advance(by: 60)
        try await phone.signIn()
        #expect(app.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        #expect(app.pendingChangeCount == 0)
        #expect(app.issues.isEmpty)
        #expect(VisibleState(app) == before)
        let server = world.snapshot
        #expect(server.tasks.values.map(\.title).sorted() == ["Buy bulbs", "Plant tulips", "Water the plants"])
        #expect(server.task(titled: "Water the plants")?.state == .completed)
        #expect(server.task(titled: "Plant tulips")?.projectID == server.project(named: "Garden")?.id)
        try phone.expectInSyncWithServer()
    }

    // MARK: Widgets and App Intents

    @Test("A task completed from a widget shows in the app, and the app's engine pushes it")
    func widgetChangeIsShownAndPushedByTheApp() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("BrainBuddy/store.json")
        let world = World()
        let phone = await world.device(store: FileDocumentStore(fileURL: url))
        try await phone.signIn()
        let app = phone.workspace
        let bins = try app.capture(CaptureDraft(text: "Take out the bins", list: .next))
        await app.syncNow()
        #expect(world.snapshot.task(titled: "Take out the bins")?.state == .next)
        #expect(phone.scheduler.pendingDelays.isEmpty)

        // The widget's process: the same file, sync disabled.
        world.clock.advance(by: 60)
        let widget = await world.extensionWorkspace(store: FileDocumentStore(fileURL: url))
        #expect(widget.task(bins)?.title == "Take out the bins")
        try widget.completeTask(bins)
        await widget.flush()
        #expect(world.snapshot.task(titled: "Take out the bins")?.state == .next, "a widget never talks to the server")

        // The widget's notification reaches the app, which is in the foreground.
        await app.reloadIfChangedExternally()
        #expect(app.task(bins)?.state == .completed)
        #expect(app.list(.list(.next)).isEmpty)
        #expect(app.pendingChangeCount == 1)
        #expect(
            phone.scheduler.pendingDelays == [.seconds(2)],
            "a change made on this device syncs 2 s later, whichever process made it"
        )

        await phone.fireNextTimer()
        #expect(world.snapshot.task(titled: "Take out the bins")?.state == .completed)
        #expect(app.pendingChangeCount == 0)
        #expect(app.syncStatus == .idle(lastSyncedAt: world.clock.now()))
        try phone.expectInSyncWithServer()

        // The widget's next timeline reads the acknowledged task.
        await widget.reloadIfChangedExternally()
        #expect(widget.pendingChangeCount == 0)
        #expect(widget.task(bins)?.serverRevision == world.snapshot.task(titled: "Take out the bins")?.revision)
    }

    // MARK: Signing out

    @Test("Signing out with unsynced changes needs confirmation; discarding them leaves an empty local device")
    func signOutWithUnsyncedChanges() async throws {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        let app = phone.workspace
        let rent = try app.capture(CaptureDraft(text: "Pay rent", list: .next))
        await app.syncNow()
        let syncedAt = world.clock.now()

        world.clock.advance(by: 60)
        phone.transport.inject(.offline, times: 1_000)
        try app.capture(CaptureDraft(text: "Draft the newsletter @Writing"))
        try app.completeTask(rent)
        await phone.settle()
        await phone.fireNextTimer()
        #expect(app.syncStatus == .offline(lastSyncedAt: syncedAt))
        #expect(app.pendingChangeCount == 3)

        await #expect(throws: WorkspaceError.unsyncedChanges(count: 3)) {
            try await app.signOut(discardUnsyncedChanges: false)
        }
        #expect(app.account?.email == World.email)
        #expect(app.pendingChangeCount == 3)
        #expect(app.task(rent)?.state == .completed)
        #expect(try await phone.store.load()?.outbox.count == 3)

        try await app.signOut(discardUnsyncedChanges: true)
        #expect(try await phone.store.load() == nil)
        #expect(app.state == .empty)
        #expect(app.account == nil)
        #expect(app.syncStatus == .localOnly)
        #expect(app.pendingChangeCount == 0)
        #expect(app.issues.isEmpty)
        #expect(app.counts() == ListCounts())
        #expect(VisibleState(app).tasks.isEmpty)
        #expect(app.projects().isEmpty)
        #expect(try phone.tokens.token(for: FakeBrainBuddyServer.baseURL) == nil, "signing out works offline")
        // The server keeps what was synced; the discarded changes never arrive.
        #expect(world.snapshot.tasks.values.map(\.title) == ["Pay rent"])
        #expect(world.snapshot.tasks.values.first?.state == .next)
        #expect(world.snapshot.projects.isEmpty)

        // The device carries on without an account.
        phone.transport.clearFaults()
        phone.transport.clearLog()
        let local = try app.capture(CaptureDraft(text: "Local again"))
        await phone.settle()
        await app.syncNow()
        #expect(phone.transport.requests.isEmpty)
        #expect(app.syncStatus == .localOnly)
        #expect(app.task(local)?.title == "Local again")
        #expect(try await phone.store.load()?.account == nil)
    }

    // MARK: Helpers

    /// A phone and a tablet signed in to one account, both showing "Renew
    /// passport" (captured on the phone), then both offline.
    private func phoneAndTabletOffline() async throws -> (World, AppDevice, AppDevice, TaskID, TaskID) {
        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        let onPhone = try phone.workspace.capture(CaptureDraft(text: "Renew passport", list: .next))
        await phone.workspace.syncNow()
        world.clock.advance(by: 60)
        let tablet = await world.device()
        try await tablet.signIn()
        let onTablet = try #require(tablet.workspace.task(titled: "Renew passport")).id
        #expect(onTablet != onPhone, "each device has its own client ids")
        await phone.networkChanged(isAvailable: false)
        await tablet.networkChanged(isAvailable: false)
        world.clock.advance(by: 60)
        return (world, phone, tablet, onPhone, onTablet)
    }

    /// Back online one after the other; then the first syncs again to pick
    /// up what the second sent.
    private func reconnect(_ world: World, first: AppDevice, then second: AppDevice) async {
        world.clock.advance(by: 60)
        await first.networkChanged(isAvailable: true)
        world.clock.advance(by: 60)
        await second.networkChanged(isAvailable: true)
        world.clock.advance(by: 60)
        await first.workspace.syncNow()
        await first.settle()
    }
}
