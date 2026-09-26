import Foundation
import XCTest
@testable import BrainBuddyMac

final class OfflineWorkspaceTests: XCTestCase {
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
}
