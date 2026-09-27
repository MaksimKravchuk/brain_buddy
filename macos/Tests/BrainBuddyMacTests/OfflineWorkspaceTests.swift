import Foundation
import XCTest
@testable import BrainBuddyMac

final class OfflineWorkspaceTests: XCTestCase {
    @MainActor
    func testQuickOpenDistinguishesTypesAndFindsTaskBeyondFirstPage() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-quick-open-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalGTDStore(fileURL: directory.appendingPathComponent("tasks.json"))
        let project = try await store.createProject(name: "Review", idempotencyKey: UUID())
        let tag = try await store.createTag(name: "Review", idempotencyKey: UUID())
        var lastTask: BrainBuddyTask?
        for index in 0..<101 {
            lastTask = try await store.createTask(
                title: "Review item \(index)", state: .next,
                waitingFor: nil, idempotencyKey: UUID()
            )
        }
        let model = BrainBuddyModel(store: store)
        await model.restore()

        let results = try await model.quickOpenResults("Review")
        XCTAssertEqual(results.count, 103)
        XCTAssertEqual(results.first(where: { $0.id == "project:\(project.id)" })?.subtitle, "Project")
        XCTAssertEqual(results.first(where: { $0.id == "tag:\(tag.id)" })?.subtitle, "Tag")
        let task = try XCTUnwrap(lastTask)
        XCTAssertEqual(results.first(where: { $0.id == "task:\(task.id)" })?.subtitle, "Task · Next actions")
        let opened = await model.quickOpenTask(task.id)
        XCTAssertEqual(opened?.id, task.id)
    }

    @MainActor
    func testLocalWorkspaceOpensAndKeepsTaskAfterRestartWithoutWebSession() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-offline-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let unreachableWeb = APIClient(baseURL: URL(string: "http://127.0.0.1:1/api")!)

        let first = BrainBuddyModel(api: unreachableWeb, store: LocalGTDStore(fileURL: fileURL))
        XCTAssertEqual(first.account?.display_name, "On this Mac")
        await first.restore()
        first.draft = "Call the landlord"
        await first.createTask()
        XCTAssertEqual(first.tasks.map(\.title), ["Call the landlord"])
        XCTAssertTrue(FileManager.default.fileExists(atPath: fileURL.path))

        let reopened = BrainBuddyModel(api: unreachableWeb, store: LocalGTDStore(fileURL: fileURL))
        await reopened.restore()
        XCTAssertEqual(reopened.tasks.map(\.title), ["Call the landlord"])
        XCTAssertEqual(reopened.openCounts?.next, 1)
    }

    @MainActor
    func testQuickMoveRequiresWaitingReasonAndPreservesTaskAfterRestart() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-quick-move-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let task = try await store.createTask(
            title: "Ask Sam for the draft", state: .next, waitingFor: nil, idempotencyKey: UUID()
        )
        let model = BrainBuddyModel(store: store)
        await model.restore()

        let rejected = await model.moveTask(task, to: .waiting, waitingFor: "  ")
        XCTAssertFalse(rejected)
        let unchanged = try await store.getTask(task.id)
        XCTAssertEqual(unchanged.state, "next")
        let moved = await model.moveTask(task, to: .waiting, waitingFor: "  Sam to reply  ")
        XCTAssertTrue(moved)
        let waiting = try await store.getTask(task.id)
        XCTAssertEqual(waiting.state, "waiting")
        XCTAssertEqual(waiting.waiting_for, "Sam to reply")
        XCTAssertEqual(model.taskDetails[task.id]?.revision, waiting.revision)

        let reopenedStore = LocalGTDStore(fileURL: fileURL)
        let reopened = BrainBuddyModel(store: reopenedStore)
        await reopened.restore()
        await reopened.choose(.list(.waiting))
        XCTAssertEqual(reopened.tasks.map(\.id), [task.id])
        let returned = await reopened.moveTask(waiting, to: .next)
        XCTAssertTrue(returned)
        let next = try await LocalGTDStore(fileURL: fileURL).getTask(task.id)
        XCTAssertEqual(next.state, "next")
        XCTAssertNil(next.waiting_for)
        XCTAssertNil(next.waiting_since)
    }

    @MainActor
    func testWaitingReviewLoadsEveryPageAndKeepsFollowUpSeparate() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-waiting-review-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let project = try await store.createProject(name: "Move house", idempotencyKey: UUID())
        let source = try await store.smartAddTask(
            title: "Receive landlord's answer", state: .waiting,
            waitingFor: "Landlord", project: .id(project.id), idempotencyKey: UUID()
        ).task
        for index in 0..<100 {
            _ = try await store.createTask(
                title: "Other reply \(index)", state: .waiting,
                waitingFor: "Another person", idempotencyKey: UUID()
            )
        }
        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.list(.next))
        let loadedReview = await model.loadWaitingReviewTasks()
        let review = try XCTUnwrap(loadedReview)
        XCTAssertEqual(review.count, 101)
        XCTAssertTrue(review.contains { $0.id == source.id })

        let rejected = await model.createFollowUp(for: source, title: "  ")
        XCTAssertFalse(rejected)
        let emptyNext = try await store.listTasks(query: TaskQuery(state: .next))
        XCTAssertEqual(emptyNext.items.count, 0)
        let created = await model.createFollowUp(for: source, title: "  Ask landlord for an update  ")
        XCTAssertTrue(created)
        let original = try await store.getTask(source.id)
        XCTAssertEqual(original.state, "waiting")
        XCTAssertEqual(original.waiting_for, "Landlord")
        let next = try await store.listTasks(query: TaskQuery(state: .next))
        XCTAssertEqual(next.items.map(\.title), ["Ask landlord for an update"])
        XCTAssertEqual(next.items.first?.project_id, project.id)

        let reopened = BrainBuddyModel(store: LocalGTDStore(fileURL: fileURL))
        await reopened.restore()
        let loadedReopenedReview = await reopened.loadWaitingReviewTasks()
        let reopenedReview = try XCTUnwrap(loadedReopenedReview)
        XCTAssertEqual(reopenedReview.count, 101)
        XCTAssertEqual(reopened.sidebarCounts?.next, 1)

        _ = try await store.archiveProject(project, idempotencyKey: UUID())
        await model.loadCollections()
        let archivedFollowUp = await model.createFollowUp(for: source, title: "Ask landlord again")
        XCTAssertFalse(archivedFollowUp)
        XCTAssertEqual(model.error, "Restore this project before creating a follow-up in it.")
    }

    @MainActor
    func testWaitingReviewReturnAndCancelPersistAcrossRestart() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-waiting-decisions-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let returned = try await store.createTask(
            title: "Wait for revised draft", state: .waiting,
            waitingFor: "Sam", idempotencyKey: UUID()
        )
        let cancelled = try await store.createTask(
            title: "Wait for obsolete quote", state: .waiting,
            waitingFor: "Vendor", idempotencyKey: UUID()
        )
        let model = BrainBuddyModel(store: store)
        await model.restore()
        let moved = await model.saveTask(
            returned, changes: TaskChanges(title: .set("Read Sam's revised draft")),
            destinationState: .next
        )
        XCTAssertTrue(moved)
        let staleFollowUp = await model.createFollowUp(for: returned, title: "Ask Sam again")
        XCTAssertFalse(staleFollowUp)
        let didCancel = await model.cancelTask(cancelled)
        XCTAssertTrue(didCancel)

        let reopenedStore = LocalGTDStore(fileURL: fileURL)
        let reopened = BrainBuddyModel(store: reopenedStore)
        await reopened.restore()
        let waitingReview = await reopened.loadWaitingReviewTasks()
        XCTAssertTrue(try XCTUnwrap(waitingReview).isEmpty)
        let next = try await reopenedStore.getTask(returned.id)
        XCTAssertEqual(next.title, "Read Sam's revised draft")
        XCTAssertEqual(next.state, "next")
        XCTAssertNil(next.waiting_for)
        XCTAssertNil(next.waiting_since)
        let cancelledAfterRestart = try await reopenedStore.getTask(cancelled.id)
        XCTAssertEqual(cancelledAfterRestart.state, "cancelled")
    }

    @MainActor
    func testSidebarCountsStayGlobalWhileBrowsingOneProject() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-counts-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalGTDStore(fileURL: directory.appendingPathComponent("tasks.json"))
        let project = try await store.createProject(name: "House move", idempotencyKey: UUID())
        _ = try await store.smartAddTask(
            title: "Book a van", state: .next,
            project: .id(project.id), idempotencyKey: UUID()
        )
        _ = try await store.createTask(
            title: "Sort inbox", state: .inbox, waitingFor: nil, idempotencyKey: UUID()
        )
        _ = try await store.smartAddTask(
            title: "Filed before processing", state: .inbox,
            project: .id(project.id), idempotencyKey: UUID()
        )

        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.project(project.id))

        XCTAssertEqual(model.openCounts?.total, 2)
        XCTAssertEqual(model.sidebarCounts?.next, 1)
        XCTAssertEqual(model.sidebarCounts?.inbox, 1)
        await model.choose(.list(.inbox))
        XCTAssertEqual(model.tasks.map(\.title), ["Sort inbox"])
        XCTAssertEqual(model.sidebarCounts?.inbox, 1)
    }

    @MainActor
    func testProjectOverviewShowsOutcomeAndNextOutsideFilteredFirstPage() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-project-overview-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let project = try await store.createProject(name: "Garage ready", idempotencyKey: UUID())
        for index in 0..<101 {
            _ = try await store.smartAddTask(
                title: "Unclarified item \(index)", state: .inbox,
                project: .id(project.id), idempotencyKey: UUID()
            )
        }
        let action = try await store.smartAddTask(
            title: "Call Vasya about the fridge", state: .next,
            project: .id(project.id), idempotencyKey: UUID()
        ).task
        let model = BrainBuddyModel(store: store)
        await model.restore()
        let saved = await model.saveProjectOutcome(
            project.id, to: "  The car can be parked in the garage.  "
        )
        XCTAssertTrue(saved)
        model.searchText = "Unclarified"
        await model.choose(.project(project.id))
        XCTAssertEqual(model.tasks.count, 100)
        XCTAssertFalse(model.tasks.contains { $0.id == action.id })
        XCTAssertEqual(model.projectNextAction?.id, action.id)
        XCTAssertEqual(model.projectOverviewCounts?.inbox, 101)
        XCTAssertEqual(model.projectOverviewCounts?.next, 1)
        XCTAssertEqual(model.projects.first?.desired_outcome, "The car can be parked in the garage.")

        let reopened = BrainBuddyModel(store: LocalGTDStore(fileURL: fileURL))
        await reopened.restore()
        await reopened.choose(.project(project.id))
        XCTAssertEqual(reopened.projects.first?.desired_outcome, model.projects.first?.desired_outcome)
        XCTAssertEqual(reopened.projectNextAction?.id, action.id)
    }

    @MainActor
    func testProjectReviewLoadsAllActionsAndResumesAfterRestart() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-project-review-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let first = try await store.createProject(name: "First", idempotencyKey: UUID())
        let second = try await store.createProject(name: "Second", idempotencyKey: UUID())
        for index in 0..<101 {
            _ = try await store.smartAddTask(
                title: "Action \(index)", state: .next,
                project: .id(first.id), idempotencyKey: UUID()
            )
        }
        let model = BrainBuddyModel(store: store)
        await model.restore()
        let loadedInitial = await model.loadProjectReview()
        let initial = try XCTUnwrap(loadedInitial)
        XCTAssertEqual(initial.map(\.project.name), ["First", "Second"])
        XCTAssertEqual(initial.first?.tasks.count, 101)
        XCTAssertEqual(initial.first?.nextCount, 101)
        let marked = await model.markProjectReviewed(first, decision: .keep)
        XCTAssertTrue(marked)

        let reopenedStore = LocalGTDStore(fileURL: fileURL)
        let reopened = BrainBuddyModel(store: reopenedStore)
        await reopened.restore()
        let loadedRemaining = await reopened.loadProjectReview()
        let remaining = try XCTUnwrap(loadedRemaining)
        XCTAssertEqual(remaining.map(\.project.id), [second.id])
        XCTAssertEqual(remaining.first?.project.last_reviewed_at, nil)
        let reviewed = try XCTUnwrap(reopened.projects.first { $0.id == first.id })
        XCTAssertEqual(reviewed.last_review_decision, .keep)
        XCTAssertEqual(reviewed.open_task_count, 101)
        _ = try await reopenedStore.smartAddTask(
            title: "New action after review", state: .next,
            project: .id(first.id), idempotencyKey: UUID()
        )
        let loadedChangedReview = await reopened.loadProjectReview()
        let changedReview = try XCTUnwrap(loadedChangedReview)
        XCTAssertEqual(changedReview.map(\.project.id), [first.id, second.id])
        XCTAssertTrue(changedReview.first?.project.review_has_changes == true)
    }

    @MainActor
    func testInboxClarificationLoadsEveryUnassignedPageAndCreatesProject() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-inbox-clarify-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let existingProject = try await store.createProject(name: "Existing", idempotencyKey: UUID())
        let source = try await store.createTask(
            title: "Clear the garage", state: .inbox,
            waitingFor: nil, idempotencyKey: UUID()
        )
        for index in 0..<100 {
            _ = try await store.createTask(
                title: "Unclarified \(index)", state: .inbox,
                waitingFor: nil, idempotencyKey: UUID()
            )
        }
        _ = try await store.smartAddTask(
            title: "Already in a project", state: .inbox,
            project: .id(existingProject.id), idempotencyKey: UUID()
        )
        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.list(.inbox))
        let review = await model.loadInboxClarificationTasks()
        XCTAssertEqual(review?.count, 101)
        XCTAssertTrue(review?.contains(where: { $0.id == source.id }) == true)

        let created = await model.clarifyInboxAsProject(
            source, projectName: "Garage ready",
            outcome: "The car fits inside the garage.",
            firstAction: "Call Vasya about the fridge"
        )
        XCTAssertTrue(created)
        XCTAssertEqual(model.destination, .list(.inbox))
        XCTAssertEqual(model.sidebarCounts?.inbox, 100)
        XCTAssertEqual(model.projects.first(where: { $0.name == "Garage ready" })?.desired_outcome,
                       "The car fits inside the garage.")
        let converted = try await store.getTask(source.id)
        XCTAssertEqual(converted.title, "Call Vasya about the fridge")
        XCTAssertEqual(converted.state, "next")

        let reopened = BrainBuddyModel(store: LocalGTDStore(fileURL: fileURL))
        await reopened.restore()
        await reopened.choose(.project(try XCTUnwrap(converted.project_id)))
        XCTAssertEqual(reopened.projectNextAction?.id, source.id)
        XCTAssertEqual(reopened.projects.first(where: { $0.id == converted.project_id })?.desired_outcome,
                       "The car fits inside the garage.")
    }

    @MainActor
    func testProjectCaptureStaysInInboxAndVisibleInProjectOffline() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-project-capture-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let fileURL = directory.appendingPathComponent("tasks.json")
        let store = LocalGTDStore(fileURL: fileURL)
        let project = try await store.createProject(name: "House move", idempotencyKey: UUID())
        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.project(project.id))
        XCTAssertEqual(model.selectedList, .inbox)
        model.draft = "Call insurer"
        await model.createTask()

        XCTAssertNil(model.error)
        XCTAssertEqual(model.destination, .project(project.id))
        XCTAssertEqual(model.tasks.map(\.title), ["Call insurer"])
        XCTAssertEqual(model.tasks.first?.state, "inbox")
        XCTAssertEqual(model.tasks.first?.project_id, project.id)

        let reopened = BrainBuddyModel(store: LocalGTDStore(fileURL: fileURL))
        await reopened.restore()
        await reopened.choose(.project(project.id))
        XCTAssertEqual(reopened.tasks.map(\.title), ["Call insurer"])
    }

    @MainActor
    func testAssigningProjectToInboxTaskOpensProjectAfterSave() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-inbox-project-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalGTDStore(fileURL: directory.appendingPathComponent("tasks.json"))
        let project = try await store.createProject(name: "House move", idempotencyKey: UUID())
        let task = try await store.createTask(
            title: "Call insurer", state: .inbox, waitingFor: nil, idempotencyKey: UUID()
        )
        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.list(.inbox))
        let saved = await model.saveTask(
            task, changes: TaskChanges(projectID: .set(project.id)), destinationState: .inbox
        )
        XCTAssertTrue(saved)
        XCTAssertEqual(model.destination, .project(project.id))
        XCTAssertEqual(model.tasks.map(\.title), ["Call insurer"])
        XCTAssertEqual(model.tasks.first?.project_id, project.id)
    }

    @MainActor
    func testArchivedProjectRemainsBrowsableAndCanBeRestoredOffline() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-archive-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalGTDStore(fileURL: directory.appendingPathComponent("tasks.json"))
        let project = try await store.createProject(name: "House move", idempotencyKey: UUID())
        let task = try await store.smartAddTask(
            title: "Book a van", state: .next,
            project: .id(project.id), idempotencyKey: UUID()
        ).task
        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.project(project.id))
        model.draft = "Call the landlord"
        let blocked = await model.archiveProject(project.id)
        XCTAssertFalse(blocked)
        XCTAssertEqual(model.draft, "Call the landlord")
        XCTAssertEqual(model.projects.map(\.id), [project.id])
        model.draft = ""

        let archived = await model.archiveProject(project.id)
        XCTAssertTrue(archived)
        XCTAssertEqual(model.destination, .list(.next))
        XCTAssertEqual(model.selectedList, .next)
        model.draft = "Review moving plan"
        await model.createTask()
        XCTAssertNil(model.error)
        XCTAssertEqual(model.tasks.first(where: { $0.title == "Review moving plan" })?.state, "next")
        XCTAssertTrue(model.projects.isEmpty)
        XCTAssertEqual(model.archivedProjects.map(\.id), [project.id])
        await model.choose(.project(project.id))
        XCTAssertEqual(model.tasks.map(\.id), [task.id])
        XCTAssertFalse(model.hasAppliedTaskFilter)
        model.searchText = "no match"
        XCTAssertFalse(model.hasAppliedTaskFilter)
        await model.reload()
        XCTAssertTrue(model.hasAppliedTaskFilter)
        XCTAssertTrue(model.tasks.isEmpty)

        let restored = await model.unarchiveProject(project.id)
        XCTAssertTrue(restored)
        XCTAssertEqual(model.projects.map(\.id), [project.id])
        XCTAssertTrue(model.archivedProjects.isEmpty)
    }

    @MainActor
    func testDeletingViewedTagKeepsQuickCaptureInNextActions() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-delete-tag-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalGTDStore(fileURL: directory.appendingPathComponent("tasks.json"))
        let tag = try await store.createTag(name: "home", idempotencyKey: UUID())
        let model = BrainBuddyModel(store: store)
        await model.restore()
        await model.choose(.tag(tag.id))
        XCTAssertEqual(model.selectedList, .inbox)

        let deleted = await model.deleteTag(tag.id)
        XCTAssertTrue(deleted)
        XCTAssertEqual(model.destination, .list(.next))
        XCTAssertEqual(model.selectedList, .next)
        model.draft = "Call the landlord"
        await model.createTask()
        XCTAssertNil(model.error)
        XCTAssertEqual(model.tasks.first?.title, "Call the landlord")
        XCTAssertEqual(model.tasks.first?.state, "next")
    }

    @MainActor
    func testCaptureExplainsWhenSavedTaskIsHiddenByCurrentResults() async throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("brainbuddy-hidden-capture-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let store = LocalGTDStore(fileURL: directory.appendingPathComponent("tasks.json"))
        let model = BrainBuddyModel(store: store)
        await model.restore()
        model.searchText = "unrelated"
        await model.reload()
        model.draft = "Book a van"

        await model.createTask()

        XCTAssertNil(model.error)
        XCTAssertTrue(model.tasks.isEmpty)
        XCTAssertEqual(
            model.captureNotice,
            "Saved to Next actions. Search, priority filters, or another page may hide it from these results."
        )
        let saved = try await store.listTasks(query: TaskQuery(state: .next))
        XCTAssertEqual(saved.items.map(\.title), ["Book a van"])
        await model.clearTaskFilters()
        XCTAssertNil(model.captureNotice)
        XCTAssertEqual(model.searchText, "")
        XCTAssertTrue(model.tasks.contains(where: { $0.title == "Book a van" }))
        model.priorityFilter = .high
        await model.reload()
        model.draft = "Get a quote"
        await model.createTask()
        XCTAssertTrue(model.tasks.isEmpty)
        XCTAssertNotNil(model.captureNotice)

        model.priorityFilter = .all
        await model.reload()
        model.draft = "Visible task"
        XCTAssertNil(model.captureNotice)
        await model.createTask()
        XCTAssertTrue(model.tasks.contains(where: { $0.title == "Visible task" }))
        XCTAssertNil(model.captureNotice)
    }
}
