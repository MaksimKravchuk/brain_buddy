import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore
@testable import BrainBuddyWorkspace

/// The Mac's offline journeys on the kit (T105), ported from the XCTest suite that ran against the
/// old local store (tasks.md "XCTest ledger"): every case runs account-less over a real
/// `store.json` and `mac-local.json` in a temporary folder, with a transport that would record any
/// request; none is sent. REST paging is gone: the Mac reads its own document.
@Suite("Offline workspace")
@MainActor
struct OfflineWorkspaceTests {
    /// The app over `folder`, loaded, as at launch.
    @MainActor
    final class App {
        let folder: TemporaryFolder
        let clock: TestClock
        let transport = CountingTransport()
        private(set) var host: WorkspaceHost
        private(set) var model: BrainBuddyModel

        init(folder: TemporaryFolder = TemporaryFolder(), clock: TestClock = TestClock()) async {
            self.folder = folder
            self.clock = clock
            (host, model) = Self.make(folder, clock: clock, transport: transport)
            await host.workspace.load()
        }

        private static func make(_ folder: TemporaryFolder, clock: TestClock, transport: CountingTransport) -> (WorkspaceHost, BrainBuddyModel) {
            let host = WorkspaceHost(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: SpyTokenStore(),
                transport: transport, now: clock.provider
            )
            return (host, BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState, now: clock.provider))
        }

        var workspace: Workspace { host.workspace }

        /// Quits (everything written) and opens the app again over the same folder.
        func restart() async {
            await host.workspace.flush()
            (host, model) = Self.make(folder, clock: clock, transport: transport)
            await host.workspace.load()
        }

        func task(_ title: String) throws -> TaskRecord {
            try #require(workspace.state.tasks.values.first { $0.title == title }, "no task “\(title)”")
        }

        func titles(_ list: OpenList) -> [String] {
            workspace.list(.list(list)).sections.flatMap(\.tasks).map(\.title)
        }

        @discardableResult
        func add(_ title: String, _ list: OpenList = .next, project: ProjectID? = nil, tags: [TagID] = [], waitingFor: String? = nil) throws -> TaskID {
            let id = TaskID.random()
            try workspace.apply([
                .createTask(.init(taskID: id, title: title, list: list, waitingFor: waitingFor, projectID: project, tagIDs: tags)),
            ])
            return id
        }
    }

    @Test("021-FR-009 021-FR-010 a quick title rename keeps the task's content; an edit made from an older view sends only what was touched")
    func quickTitleRename() async throws {
        let app = await App()
        let id = try app.add("Ask for a quote")
        try app.workspace.updateTask(id, TaskChanges(details: .set("Bring the bike serial number")))
        _ = try app.workspace.addSubtask(to: id, title: "Find serial number")
        let opened = try #require(app.workspace.task(id))

        #expect(await app.model.saveTask(id, changes: TaskChanges(title: .set("Call workshop for a quote"))))
        await app.restart()
        let persisted = try app.task("Call workshop for a quote")
        #expect(persisted.details == "Bring the bike serial number" && persisted.state == .next)
        #expect(persisted.subtasks.map(\.title) == ["Find serial number"])

        // The editor opened before another change landed; its draft rebases instead of overwriting.
        var draft = TaskEditDraft(opened)
        draft.priority = .high
        try app.workspace.updateTask(id, TaskChanges(details: .set("Serial number is on the frame")))
        let rebased = draft.rebased(onto: try #require(app.workspace.task(id)))
        #expect(await app.model.saveTask(id, changes: rebased.changes()))
        let current = try #require(app.workspace.task(id))
        #expect(current.title == "Call workshop for a quote", "an untouched field keeps the newer value")
        #expect(current.details == "Serial number is on the frame" && current.priority == .high)
    }

    @Test("021-FR-010 quick capture saves to Inbox offline without touching the main draft or the screen")
    func quickCapture() async throws {
        let app = await App()
        app.model.draft = "Keep this unfinished Next draft"
        try await app.model.quickCaptureInbox("  Remember the idea  ")
        #expect(app.titles(.inbox) == ["Remember the idea"])
        #expect(app.model.draft == "Keep this unfinished Next draft" && app.model.destination == .list(.next))
        await app.restart()
        #expect(app.titles(.inbox) == ["Remember the idea"])
        #expect(app.transport.requests.isEmpty)
    }

    @Test("021-FR-010 Quick Open tells projects, tags and tasks apart and finds any task, with no pages")
    func quickOpen() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Review")
        let tag = try app.workspace.createTag(name: "Review")
        var last = TaskID("none")
        for index in 0..<101 { last = try app.add("Review item \(index)") }

        let results = app.model.quickOpenResults("Review")
        #expect(results.count == 103)
        #expect(results.first { $0.id == "project:\(project.rawValue)" }?.subtitle == "Project")
        #expect(results.first { $0.id == "tag:\(tag.rawValue)" }?.subtitle == "Tag")
        #expect(results.first { $0.id == "task:\(last.rawValue)" }?.subtitle == "Task · Next actions")
        #expect(app.model.destination(showing: try #require(app.workspace.task(last))) == .list(.next))
    }

    @Test("021-FR-002 the Mac opens account-less, keeps its tasks across a restart and sends nothing")
    func accountLessRestart() async throws {
        let app = await App()
        #expect(app.model.syncLine.text == "On this Mac · Sign in to sync")
        app.model.draft = "Call the landlord"
        await app.model.createTask()
        #expect(app.model.tasks.map(\.title) == ["Call the landlord"])
        await app.workspace.flush()
        #expect(MacFiles.exists(app.folder.store))
        await app.restart()
        #expect(app.model.tasks.map(\.title) == ["Call the landlord"] && app.model.openTaskCount == 1)
        #expect(app.transport.requests.isEmpty)
    }

    @Test("021-FR-010 a quick move to Waiting needs a reason, and survives a restart")
    func quickMoveToWaiting() async throws {
        let app = await App()
        let id = try app.add("Ask Sam for the draft")
        #expect(await app.model.moveTask(id, to: .waiting, waitingFor: "  ") == false)
        #expect(app.model.error == GTDValidationError.waitingForRequired.message)
        #expect(app.workspace.task(id)?.state == .next)
        #expect(await app.model.moveTask(id, to: .waiting, waitingFor: "  Sam to reply  "))
        #expect(app.workspace.task(id)?.waitingFor == "Sam to reply")

        await app.restart()
        app.model.choose(.list(.waiting))
        #expect(app.model.tasks.map(\.id) == [id])
        #expect(await app.model.moveTask(id, to: .next))
        let next = try #require(app.workspace.task(id))
        #expect(next.state == .next && next.waitingFor == nil && next.waitingSince == nil)
    }

    @Test("021-FR-023 the Waiting review lists every due item and a follow-up stays a separate Next action")
    func waitingReviewAndFollowUp() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Move house")
        let source = try app.add("Receive landlord's answer", .waiting, project: project, waitingFor: "Landlord")
        for index in 0..<100 { try app.add("Other reply \(index)", .waiting, waitingFor: "Another person") }

        let review = await app.model.loadWaitingReviewTasks()
        #expect(review.count == 101 && review.contains { $0.id == source })
        #expect(await app.model.createFollowUp(for: source, title: "  ") == false)
        #expect(app.titles(.next).isEmpty)
        #expect(await app.model.createFollowUp(for: source, title: "  Ask landlord for an update  "))
        let original = try #require(app.workspace.task(source))
        #expect(original.state == .waiting && original.waitingFor == "Landlord")
        #expect(app.titles(.next) == ["Ask landlord for an update"])
        #expect(try app.task("Ask landlord for an update").projectID == project)

        await app.restart()
        let reopened = await app.model.loadWaitingReviewTasks()
        #expect(reopened.count == 100 && !reopened.contains { $0.id == source })
        #expect(app.model.sidebarCounts.next == 1)
        try app.workspace.archiveProject(project)
        #expect(await app.model.createFollowUp(for: source, title: "Ask landlord again") == false)
        #expect(app.model.error == "Unarchive this project before creating a follow-up in it.")
    }

    @Test("021-FR-010 021-FR-023 a reviewed follow-up is one change: one Next action, the Waiting item unchanged and marked reviewed")
    func reviewedFollowUpIsOneChange() async throws {
        let app = await App()
        let source = try app.add("Wait for Sam", .waiting, waitingFor: "Sam")
        let before = try #require(app.workspace.task(source))
        await app.workspace.flush()
        let outbox = app.workspace.pendingChangeCount
        #expect(await app.model.createFollowUp(for: source, title: "Ask Sam for an update"))
        #expect(app.workspace.pendingChangeCount == outbox + 1, "one command")
        #expect(app.workspace.task(source) == before)
        await app.restart()
        #expect(app.titles(.next) == ["Ask Sam for an update"])
        #expect(await app.model.loadWaitingReviewTasks().isEmpty)
    }

    @Test("021-FR-010 returning a Waiting item to Next and cancelling another persist across a restart")
    func waitingReturnAndCancel() async throws {
        let app = await App()
        let returned = try app.add("Wait for revised draft", .waiting, waitingFor: "Sam")
        let cancelled = try app.add("Wait for obsolete quote", .waiting, waitingFor: "Vendor")
        #expect(await app.model.saveTask(returned, changes: TaskChanges(title: .set("Read Sam's revised draft")), moveTo: .next))
        #expect(await app.model.createFollowUp(for: returned, title: "Ask Sam again") == false)
        #expect(await app.model.cancelTask(cancelled))

        await app.restart()
        #expect(await app.model.loadWaitingReviewTasks().isEmpty)
        let next = try app.task("Read Sam's revised draft")
        #expect(next.state == .next && next.waitingFor == nil && next.waitingSince == nil)
        #expect(app.workspace.task(cancelled)?.state == .cancelled)
    }

    @Test("021-FR-023 keep waiting holds for 7 days and across a restart, and a changed task is due again")
    func keepWaiting() async throws {
        let app = await App()
        let id = try app.add("Wait for a reply", .waiting, waitingFor: "Sam")
        let since = try #require(app.workspace.task(id)?.waitingSince)
        #expect(await app.model.keepWaiting(try #require(app.workspace.task(id))))
        #expect(await app.model.loadWaitingReviewTasks().isEmpty)

        await app.restart()
        #expect(await app.model.loadWaitingReviewTasks().isEmpty)
        try app.workspace.updateTask(id, TaskChanges(title: .set("Wait for Sam's revised reply")))
        #expect(await app.model.loadWaitingReviewTasks().map(\.id) == [id])
        #expect(await app.model.keepWaiting(try #require(app.workspace.task(id))))
        #expect(await app.model.loadWaitingReviewTasks().isEmpty)
        app.clock.advance(7 * TestClock.day)
        #expect(await app.model.loadWaitingReviewTasks().map(\.id) == [id], "due again after 7 days")
        #expect(app.workspace.task(id)?.waitingSince == since, "a review mark never touches the task")
    }

    @Test("021-FR-023 the Someday review resumes across a restart and a task change")
    func somedayReview() async throws {
        let app = await App()
        let source = try app.add("Build a small greenhouse", .someday)
        for index in 0..<100 { try app.add("Future idea \(index)", .someday) }
        #expect(await app.model.loadSomedayReviewTasks().count == 101)
        #expect(await app.model.keepSomeday(try #require(app.workspace.task(source))))

        await app.restart()
        #expect(await app.model.loadSomedayReviewTasks().count == 100)
        try app.workspace.updateTask(source, TaskChanges(title: .set("Build a greenhouse next spring")))
        #expect(await app.model.loadSomedayReviewTasks().count == 101)
        #expect(await app.model.keepSomeday(try #require(app.workspace.task(source))))
        #expect(await app.model.loadSomedayReviewTasks().count == 100)
    }

    private func selectedReviewModel(in folder: TemporaryFolder, clock: TestClock) async throws -> BrainBuddyModel {
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: folder.file("store.sqlite3"))
        let workspace = Workspace(store: InMemoryDocumentStore(), sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")),
                startup: .freshAccountless), now: clock.provider)
        workspace.deviceTimeZone = { TimeZone(secondsFromGMT: 0)! }
        await workspace.load()
        return BrainBuddyModel(workspace: workspace, localStateStore: MacLocalStateStore(directory: folder.url), now: clock.provider)
    }

    @Test("026-FR-025 Mac Review never makes old displayed Waiting or Someday items ready after their query generation changes",
        arguments: [TaskList.waiting, .someday])
    func selectedTaskReviewRetainsDisplayedGeneration(_ list: TaskList) async throws {
        let folder = TemporaryFolder()
        let model = try await selectedReviewModel(in: folder, clock: TestClock())
        let id = TaskID.random()
        try await model.workspace.apply([.createTask(.init(taskID: id, title: "Original shown content", list: list,
            waitingFor: list == .waiting ? "Sam" : nil))], editorID: "review-fixture:capture")
        let shown = list == .waiting ? await model.loadWaitingReviewTasks() : await model.loadSomedayReviewTasks()
        let task = try #require(shown.first)
        #expect(model.reviewListReadiness(list) == .ready)
        let originalGeneration = model.reviewListPageState(list).projectionGeneration

        try await model.workspace.updateTask(task.id, TaskChanges(title: .set("Changed unseen content")), editorID: "review-fixture:edit")
        await model.workspace.prepareList(.list(list))
        _ = try await model.workspace.prepareReviewContentStamps(key: model.localState.installSalt, tasks: [task.id])
        #expect(model.reviewListPageState(list).projectionGeneration != originalGeneration)
        #expect(model.reviewListReadiness(list) == .failed("REVIEW_PAGE_CHANGED"))
        let kept = list == .waiting ? await model.keepWaiting(task) : await model.keepSomeday(task)
        #expect(!kept)
        #expect(model.localState.waitingReviews.isEmpty && model.localState.somedayReviews.isEmpty)
        await model.workspace.closeRuntime()
    }

    @Test("026-FR-025 Mac Project Review keeps a catalog larger than the query cache usable and prepares only the displayed actions")
    func selectedProjectReviewLoadsOnlyDisplayedPage() async throws {
        let folder = TemporaryFolder()
        let model = try await selectedReviewModel(in: folder, clock: TestClock())
        for number in 0..<70 {
            _ = try await model.workspace.createProject(name: "Project \(number)", editorID: "review-fixture:project:\(number)")
        }
        let items = await model.loadProjectReview()
        #expect(items.count == 70)
        #expect(model.projectReviewReadiness == .ready)
        #expect(items.allSatisfy { $0.tasks.isEmpty && $0.taskPageState.readiness == .notRequested })
        func actionQueryCount() throws -> Int {
            try #require(model.workspace.rustQueries).entries.keys.filter { key in
                let query = (try? JSONSerialization.jsonObject(with: key)) as? [String: Any]
                let mode = query?["mode"] as? [String: Any]
                return query?["kind"] as? String == "list_mode" && mode?["type"] as? String == "project"
            }.count
        }
        #expect(try actionQueryCount() == 0)
        let first = await model.reloadProjectReviewTaskPage(try #require(items.first))
        #expect(first.taskPageState.readiness == .ready)
        #expect(model.projectReviewTaskPageState(first).readiness == .ready)
        #expect(model.projectReviewReadiness == .ready)
        #expect(try actionQueryCount() == 1)
        let last = await model.reloadProjectReviewTaskPage(try #require(items.last))
        #expect(model.projectReviewTaskPageState(last).readiness == .ready)
        #expect(model.projectReviewReadiness == .ready)
        #expect(try actionQueryCount() == 2)

        // Loading a task page after a write cannot attach new unseen actions to the old signature.
        try await model.workspace.apply([.createTask(.init(taskID: .random(), title: "Changed unseen action", list: .next,
            projectID: first.id))], editorID: "review-fixture:changed-action")
        let changed = await model.reloadProjectReviewTaskPage(first)
        #expect(changed.tasks.isEmpty)
        #expect(changed.taskPageState.readiness == .failed("REVIEW_PAGE_CHANGED"))
        await model.workspace.closeRuntime()
    }

    @Test("021-FR-010 making a Someday item a Next action is one change; a second try is refused")
    func somedayActivation() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Garden")
        let tag = try app.workspace.createTag(name: "outside")
        let source = try app.add("Garden redesign", .someday, project: project, tags: [tag])
        await app.workspace.flush()
        let outbox = app.workspace.pendingChangeCount

        #expect(await app.model.activateSomeday(source, title: "  Sketch the first garden bed  "))
        #expect(app.workspace.pendingChangeCount == outbox + 2, "the edit and the move, applied together")
        let activated = try #require(app.workspace.task(source))
        #expect(activated.title == "Sketch the first garden bed" && activated.state == .next)
        #expect(activated.projectID == project && activated.tagIDs == [tag])
        await app.restart()
        #expect(app.titles(.next) == ["Sketch the first garden bed"])
        #expect(await app.model.activateSomeday(source, title: "Another action") == false)
    }

    @Test("021-FR-024 a Someday item of an archived project keeps its project when it becomes a Next action")
    func somedayActivationKeepsArchivedProject() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Garden")
        let source = try app.add("Redesign garden", .someday, project: project)
        try app.workspace.archiveProject(project)
        #expect(await app.model.activateSomeday(source, title: "Sketch garden beds"))
        await app.restart()
        let persisted = try #require(app.workspace.task(source))
        #expect(persisted.state == .next && persisted.projectID == project)
    }

    @Test("021-FR-010 the sidebar counts stay global while one project is open")
    func sidebarCounts() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "House move")
        try app.add("Book a van", project: project)
        try app.add("Sort inbox", .inbox)
        try app.add("Filed before processing", .inbox, project: project)

        app.model.choose(.project(project))
        #expect(app.model.openTaskCount == 2)
        #expect(app.model.sidebarCounts.next == 1 && app.model.sidebarCounts.inbox == 1)
        app.model.choose(.list(.inbox))
        #expect(app.model.tasks.map(\.title) == ["Sort inbox"])
        #expect(app.model.sidebarCounts.inbox == 1)
    }

    @Test("021-FR-028 the project overview shows the outcome and the first Next action, whatever the list filter")
    func projectOverview() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Garage ready")
        for index in 0..<101 { try app.add("Unclarified item \(index)", .inbox, project: project) }
        let action = try app.add("Call Vasya about the fridge", project: project)
        #expect(await app.model.saveProjectOutcome(project, to: "  The car can be parked in the garage.  "))

        app.model.searchText = "Unclarified"
        app.model.choose(.project(project))
        #expect(app.model.tasks.count == 101 && !app.model.tasks.contains { $0.id == action })
        let overview = try #require(app.model.projectOverview(project))
        #expect(overview.nextAction?.id == action)
        #expect(overview.openCounts[.inbox] == 101 && overview.openCounts[.next] == 1)
        #expect(overview.project.desiredOutcome == "The car can be parked in the garage.")

        await app.restart()
        app.model.choose(.project(project))
        #expect(app.model.projectOverview(project)?.project.desiredOutcome == "The car can be parked in the garage.")
        #expect(app.model.projectOverview(project)?.nextAction?.id == action)
    }

    @Test("021-FR-023 the Project review lists every action and resumes after a restart; a change brings it back first")
    func projectReview() async throws {
        let app = await App()
        let first = try app.workspace.createProject(name: "First")
        let second = try app.workspace.createProject(name: "Second")
        for index in 0..<101 { try app.add("Action \(index)", project: first) }

        let initial = await app.model.loadProjectReview()
        #expect(initial.map(\.project.name) == ["First", "Second"])
        #expect(initial.first?.tasks.count == 101 && initial.first?.nextCount == 101)
        #expect(app.model.markProjectReviewed(try #require(initial.first), decision: .keep))

        await app.restart()
        let remaining = await app.model.loadProjectReview()
        #expect(remaining.map(\.id) == [second] && remaining.first?.lastReview == nil)
        let reviewed = try #require(app.workspace.project(first))
        #expect(app.model.localState.projectMark(for: reviewed)?.decision == .keep)
        #expect(app.workspace.projects().first { $0.id == first }?.openTaskCount == 101)
        try app.add("New action after review", project: first)
        let changed = await app.model.loadProjectReview()
        #expect(changed.map(\.id) == [first, second])
        #expect(changed.first?.hasChanges == true)
    }

    @Test("021-FR-023 a project review decision is refused once the project's actions changed after the review opened")
    func projectReviewRejectsChangedActions() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Move house")
        let action = try app.add("Call mover", project: project)
        let opened = try #require(await app.model.loadProjectReview().first)
        try app.workspace.updateTask(action, TaskChanges(title: .set("Book mover")))

        #expect(!app.model.markProjectReviewed(opened, decision: .keep))
        #expect(app.model.error == "Project changed elsewhere. Reopen the review to inspect its current actions.")
        let stillDue = try #require(await app.model.loadProjectReview().first)
        #expect(stillDue.lastReview == nil && stillDue.tasks.first?.title == "Book mover")
        #expect(app.model.markProjectReviewed(stillDue, decision: .keep))
    }

    @Test("021-FR-028 clarifying an Inbox item as a project creates the project, its outcome and the first Next action at once")
    func inboxClarificationAsProject() async throws {
        let app = await App()
        let existing = try app.workspace.createProject(name: "Existing")
        let source = try app.add("Clear the garage", .inbox)
        for index in 0..<100 { try app.add("Unclarified \(index)", .inbox) }
        try app.add("Already in a project", .inbox, project: existing)

        app.model.choose(.list(.inbox))
        let review = await app.model.loadInboxClarificationTasks()
        #expect(review.count == 101 && review.contains { $0.id == source })
        #expect(
            await app.model.clarifyInboxAsProject(
                source, projectName: "Garage ready", outcome: "The car fits inside the garage.", firstAction: "Call Vasya about the fridge"
            )
        )
        #expect(app.model.destination == .list(.inbox) && app.model.sidebarCounts.inbox == 100)
        let converted = try #require(app.workspace.task(source))
        #expect(converted.title == "Call Vasya about the fridge" && converted.state == .next)
        let projectID = try #require(converted.projectID)
        #expect(app.workspace.project(projectID)?.desiredOutcome == "The car fits inside the garage.")

        await app.restart()
        app.model.choose(.project(projectID))
        #expect(app.model.projectOverview(projectID)?.nextAction?.id == source)
    }

    @Test("021-FR-028 clarifying an Inbox item as a project without a desired outcome leaves the outcome unset")
    func inboxClarificationAsProjectWithoutOutcome() async throws {
        let app = await App()
        let blank = try app.add("Plan the offsite", .inbox)
        let missing = try app.add("Renew passports", .inbox)

        #expect(await app.model.clarifyInboxAsProject(blank, projectName: "Offsite", outcome: "  \n ", firstAction: "Pick dates"))
        #expect(await app.model.clarifyInboxAsProject(missing, projectName: "Passports", outcome: nil, firstAction: "Find old passports"))
        for (id, name) in [(blank, "Offsite"), (missing, "Passports")] {
            let task = try #require(app.workspace.task(id))
            let projectID = try #require(task.projectID)
            let project = try #require(app.workspace.project(projectID))
            #expect(project.name == name && project.desiredOutcome == nil && task.state == .next)
        }

        await app.restart()
        let reloaded = try #require(app.workspace.task(blank)?.projectID)
        #expect(app.workspace.project(reloaded)?.desiredOutcome == nil)
    }

    @Test("021-FR-028 a project chosen while clarifying is applied together with Next, Waiting for or Someday")
    func inboxClarificationWithStagedProject() async throws {
        let app = await App()
        let project = try #require(await app.model.createProject("House move"))
        let next = try app.add("Call movers", .inbox)
        let waiting = try app.add("Quote from movers", .inbox)
        let someday = try app.add("Build a shed", .inbox)
        let leftAlone = try app.add("Skim the manual", .inbox)

        app.model.choose(.list(.inbox))
        #expect(await app.model.loadInboxClarificationTasks().count == 4)
        #expect(await app.model.saveTask(next, changes: TaskChanges(projectID: .set(project)), moveTo: .next))
        #expect(
            await app.model.saveTask(
                waiting, changes: TaskChanges(projectID: .set(project), waitingFor: .set("The mover")), moveTo: .waiting
            )
        )
        #expect(await app.model.saveTask(someday, changes: TaskChanges(projectID: .set(project)), moveTo: .someday))

        let movedNext = try #require(app.workspace.task(next))
        #expect(movedNext.state == .next && movedNext.projectID == project)
        let movedWaiting = try #require(app.workspace.task(waiting))
        #expect(movedWaiting.state == .waiting && movedWaiting.projectID == project && movedWaiting.waitingFor == "The mover")
        let movedSomeday = try #require(app.workspace.task(someday))
        #expect(movedSomeday.state == .someday && movedSomeday.projectID == project)
        // Items that got a project leave the Inbox; the one left alone stays, still without a project.
        #expect(await app.model.loadInboxClarificationTasks().map(\.id) == [leftAlone])
        #expect(app.workspace.task(leftAlone)?.projectID == nil)
    }

    @Test("021-FR-010 capture from a project stays in Inbox and shows in the project, offline")
    func projectCapture() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "House move")
        app.model.choose(.project(project))
        #expect(app.model.selectedList == .inbox)
        app.model.draft = "Call insurer"
        await app.model.createTask()
        #expect(app.model.error == nil && app.model.destination == .project(project))
        let task = try app.task("Call insurer")
        #expect(app.model.tasks.map(\.title) == ["Call insurer"] && task.state == .inbox && task.projectID == project)

        await app.restart()
        app.model.choose(.project(project))
        #expect(app.model.tasks.map(\.title) == ["Call insurer"])
    }

    @Test("021-FR-010 Smart Add in Inbox naming a project keeps the item in Inbox and opens the project")
    func inboxCaptureWithProject() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "House move")
        app.model.choose(.list(.inbox))
        app.model.draft = "Call insurer @\"House move\""
        await app.model.createTask()
        #expect(app.model.error == nil && app.model.destination == .project(project))
        #expect(app.model.tasks.map(\.title) == ["Call insurer"])
        #expect(try app.task("Call insurer").state == .inbox)
    }

    @Test("021-FR-010 giving an Inbox item a project opens that project after the save")
    func assigningProjectOpensIt() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "House move")
        let id = try app.add("Call insurer", .inbox)
        app.model.choose(.list(.inbox))
        #expect(await app.model.saveTask(id, changes: TaskChanges(projectID: .set(project)), moveTo: .inbox))
        #expect(app.model.destination == .project(project))
        #expect(app.model.tasks.map(\.title) == ["Call insurer"] && app.workspace.task(id)?.projectID == project)
    }

    @Test("021-FR-024 021-FR-025 021-FR-026 an archived project stays browsable with its tasks, refuses new ones, and unarchives offline")
    func archivedProjectBrowseAndUnarchive() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "House move")
        let task = try app.add("Book a van", project: project)
        app.model.choose(.project(project))
        app.model.draft = "Call the landlord"
        #expect(await app.model.archiveProject(project) == false, "not while the capture draft holds text")
        #expect(app.model.draft == "Call the landlord" && app.model.projects.map(\.id) == [project])
        app.model.draft = ""

        #expect(await app.model.archiveProject(project))
        #expect(app.model.destination == .project(project), "the screen stays on it, now archived (X-06 archived just now)")
        #expect(app.model.isArchivedProjectDestination && app.model.localState.sidebar.archivedProjectsExpanded)
        #expect(app.model.projects.isEmpty && app.model.archivedProjects.map(\.id) == [project])
        #expect(app.model.tasks.map(\.id) == [task], "every task keeps the project (ADR-0020)")
        #expect(app.model.projectLabel(project) == "House move · archived")
        app.model.draft = "Review moving plan"
        await app.model.createTask()
        #expect(app.model.error == "Unarchive “House move” before adding a task to it.")
        app.model.choose(.list(.next))
        await app.model.createTask()
        #expect(app.model.error == nil)
        #expect(try app.task("Review moving plan").state == .next)

        app.model.choose(.project(project))
        #expect(!app.model.hasAppliedTaskFilter)
        app.model.searchText = "no match"
        #expect(!app.model.hasAppliedTaskFilter, "search applies on submit")
        app.model.reload()
        #expect(app.model.hasAppliedTaskFilter && app.model.tasks.isEmpty)

        #expect(await app.model.unarchiveProject(project))
        #expect(app.model.projects.map(\.id) == [project] && app.model.archivedProjects.isEmpty)
        #expect(app.transport.requests.isEmpty)
    }

    @Test("021-FR-026 unarchive is refused at once while an active project has the name; Rename… on the archived one clears it")
    func unarchiveNameClash() async throws {
        let app = await App()
        let old = try app.workspace.createProject(name: "Old flat")
        try app.workspace.archiveProject(old)
        _ = try app.workspace.createProject(name: "Old flat")
        app.model.choose(.project(old))

        #expect(await app.model.unarchiveProject(old) == false)
        #expect(app.model.unarchiveRefusal == UnarchiveRefusal(projectID: old, message: "Another active project is already called “Old flat”. Rename one first."))
        #expect(app.model.error == nil, "a refusal, not an error: no Retry")
        // The kit renames an archived project without a uniqueness check (the server's rule), so a
        // name that still clashes is saved and the next Unarchive is refused again.
        #expect(await app.model.renameProject(old, to: "old  flat") && app.model.unarchiveRefusal == nil)
        #expect((await app.model.unarchiveProject(old)) == false && app.model.unarchiveRefusal?.projectID == old)
        #expect(await app.model.renameProject(old, to: "Old flat (before the move)"))
        #expect(app.model.unarchiveRefusal == nil)
        #expect(await app.model.unarchiveProject(old))
        #expect(app.workspace.project(old)?.state == .active)
    }

    @Test("021-FR-024 the File-menu archive is unavailable while a task edit is unsaved or the capture draft holds text")
    func fileMenuArchiveGuard() async throws {
        let app = await App()
        let project = try app.workspace.createProject(name: "Garden")
        #expect(app.model.canArchiveProject)
        app.model.taskEditInProgress = true
        #expect(!app.model.canArchiveProject)
        #expect(await app.model.archiveProject(project) == false)
        app.model.taskEditInProgress = false
        app.model.draft = "  "
        #expect(app.model.canArchiveProject, "a blank draft does not count")
        #expect(await app.model.archiveProject(project))
    }

    @Test("021-FR-010 deleting the tag on screen goes back to Next actions, where capture lands")
    func deletingViewedTag() async throws {
        let app = await App()
        let tag = try app.workspace.createTag(name: "home")
        app.model.choose(.tag(tag))
        #expect(app.model.selectedList == .inbox)
        #expect(await app.model.deleteTag(tag))
        #expect(app.model.destination == .list(.next) && app.model.selectedList == .next)
        app.model.draft = "Call the landlord"
        await app.model.createTask()
        #expect(app.model.error == nil && app.model.tasks.first?.title == "Call the landlord")
        #expect(app.model.tasks.first?.state == .next)
    }

    @Test("021-FR-010 a capture hidden by the current search or priority filter says so")
    func hiddenCaptureExplained() async throws {
        let app = await App()
        app.model.searchText = "unrelated"
        app.model.reload()
        app.model.draft = "Book a van"
        await app.model.createTask()
        #expect(app.model.error == nil && app.model.tasks.isEmpty)
        #expect(app.model.captureNotice == "Saved to Next actions. Search or priority filters may hide it from these results.")
        #expect(app.titles(.next) == ["Book a van"])
        app.model.clearTaskFilters()
        #expect(app.model.captureNotice == nil && app.model.searchText.isEmpty)
        #expect(app.model.tasks.contains { $0.title == "Book a van" })

        app.model.priorityFilter = .high
        app.model.reload()
        app.model.draft = "Get a quote"
        await app.model.createTask()
        #expect(app.model.tasks.isEmpty && app.model.captureNotice != nil)
        app.model.priorityFilter = .all
        app.model.reload()
        app.model.draft = "Visible task"
        #expect(app.model.captureNotice == nil)
        await app.model.createTask()
        #expect(app.model.tasks.contains { $0.title == "Visible task" } && app.model.captureNotice == nil)
    }

    @Test("021-FR-010 the editors' limits are the kit's: 500 for titles and names, 20,000 for notes and comments, 1,000 for an outcome")
    func editorLimitsAreTheKits() async throws {
        #expect(EditorLimits.title == GTDLimits.title && EditorLimits.name == GTDLimits.name)
        #expect(EditorLimits.details == GTDLimits.details && EditorLimits.comment == GTDLimits.comment)
        #expect(EditorLimits.outcome == GTDLimits.outcome && EditorLimits.waitingFor == GTDLimits.waitingFor)
        let app = await App()
        let id = try app.add("Short")
        #expect(await app.model.saveTask(id, changes: TaskChanges(title: .set(String(repeating: "x", count: 500)))))
        #expect(await app.model.saveTask(id, changes: TaskChanges(title: .set(String(repeating: "x", count: 501)))) == false)
        #expect(await app.model.addComment(to: id, body: String(repeating: "c", count: 20_000)))
        #expect(await app.model.addComment(to: id, body: String(repeating: "c", count: 20_001)) == false)
        let project = try #require(await app.model.createProject("Garden"))
        #expect(await app.model.saveProjectOutcome(project, to: String(repeating: "o", count: 1_001)) == false)
        #expect(EditorLimits.fits("👍🏽", 2) && !EditorLimits.fits("👍🏽", 1), "scalars, as the server counts")
    }
}
