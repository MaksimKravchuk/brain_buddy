import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// The first sign-in of a device whose work was done without an account (the Mac after its
/// upgrade, spec 021), through `Workspace`, a real sync engine and the fake server: what happens
/// when its projects meet the account's by name (contracts/kit-commands.md §3), and that the
/// content behind a review mark survives the upload, the pull and a sign-out and sign-in.
@MainActor
@Suite("First sign-in: merge by name and stable content")
struct FirstSignInMergeTests {
    /// The account holder: a device that is signed in and has "Old flat" with `state` and an outcome.
    private func account(
        _ world: World, state: ProjectState = .active, outcome: String? = nil
    ) async throws -> AppDevice {
        let phone = await world.device()
        try await phone.signIn()
        let id = try phone.workspace.createProject(name: "Old flat")
        if let outcome { try phone.workspace.setProjectOutcome(id, outcome: outcome) }
        _ = try phone.workspace.capture(CaptureDraft(text: "Existing task", contextProjectID: id))
        if state == .archived { try phone.workspace.archiveProject(id) }
        await phone.workspace.syncNow()
        await phone.settle()
        return phone
    }

    /// The legacy import's outbox shape: the project, three tasks in it, then its archive.
    private func importedFlat(
        on mac: AppDevice, archived: Bool = true, outcome: String? = nil, afterArchive: [GTDCommand] = []
    ) throws {
        let commands: [GTDCommand] =
            [.createProject(.init(projectID: "mac-flat", name: "Old flat", desiredOutcome: outcome))]
            + ["Paint", "Sand", "Tile"].map {
                .createTask(.init(taskID: TaskID("mac-\($0)"), title: $0, list: .next, projectID: "mac-flat"))
            } + (archived ? [.archiveProject("mac-flat")] : []) + afterArchive
        try mac.workspace.apply(commands)
    }

    private func flats(_ server: FakeServerSnapshot) -> [ProjectDTO] { server.projects.values.filter { $0.name == "Old flat" } }

    @Test("021-FR-003 021-SC-003 an archived local project meets an active account project: every task joins it, nothing is archived, one issue")
    func archivedAgainstActive() async throws {
        let world = World()
        _ = try await account(world)
        let mac = await world.device()
        try importedFlat(on: mac)
        try await mac.signIn()

        let server = world.snapshot
        let flat = try #require(flats(server).first)
        #expect(flats(server).count == 1 && flat.state == .active && flat.revision == 1, "never archived")
        for title in ["Paint", "Sand", "Tile", "Existing task"] {
            #expect(server.task(titled: title)?.projectID == flat.id, "\(title) kept its project")
        }
        let onMac = mac.workspace.state
        #expect(onMac.tasks.values.allSatisfy { $0.projectID != nil } && onMac.projects.count == 1)
        #expect(mac.workspace.issues.map(\.message) == [GTDValidationError.archiveNotMerged("Old flat").message])
        #expect(mac.workspace.issues.first.map { if case .archiveProject = $0.command { true } else { false } } == true)
        #expect(mac.rejectedRequests.isEmpty)
        try mac.expectInSyncWithServer()
    }

    @Test("021-FR-003 021-SC-003 the same when the account's project appeared after the device's first pull (409 duplicate name)")
    func archivedAgainstActiveThrough409() async throws {
        let world = World()
        let mac = await world.device()
        try importedFlat(on: mac)
        // The first push fails, so the device has pulled an account without "Old flat" when it appears there.
        mac.transport.inject(.offline, times: 100, matching: FakeServerTransport.isMutation)
        try await mac.signIn()
        _ = try await account(world)
        mac.transport.clearFaults()
        await mac.workspace.syncNow()
        await mac.settle()

        #expect(mac.transport.exchanges.contains { $0.statusCode == 409 }, "the server refused the duplicate name")
        let server = world.snapshot
        let flat = try #require(flats(server).first)
        #expect(flats(server).count == 1 && flat.state == .active)
        for title in ["Paint", "Sand", "Tile", "Existing task"] {
            #expect(server.task(titled: title)?.projectID == flat.id)
        }
        #expect(mac.workspace.issues.map(\.message) == [GTDValidationError.archiveNotMerged("Old flat").message])
        #expect(mac.workspace.state.tasks.values.allSatisfy { $0.projectID != nil })
        try mac.expectInSyncWithServer()
    }

    @Test("021-FR-003 an active local project beside an archived-only account project is a second, active project")
    func activeAgainstArchivedOnly() async throws {
        let world = World()
        _ = try await account(world, state: .archived)
        let mac = await world.device()
        try importedFlat(on: mac, archived: false)
        try await mac.signIn()

        let server = world.snapshot
        #expect(flats(server).map(\.state).sorted { $0.rawValue < $1.rawValue } == [.active, .archived])
        let active = try #require(flats(server).first { $0.state == .active })
        #expect(server.task(titled: "Paint")?.projectID == active.id)
        #expect(mac.workspace.issues.isEmpty)
        try mac.expectInSyncWithServer()
    }

    @Test("021-SC-003 an archived local project beside an archived-only account project gives two archived projects, and no active duplicate")
    func archivedAgainstArchivedOnly() async throws {
        let world = World()
        _ = try await account(world, state: .archived)
        let mac = await world.device()
        try importedFlat(on: mac)
        try await mac.signIn()

        let server = world.snapshot
        #expect(flats(server).count == 2 && flats(server).allSatisfy { $0.state == .archived })
        let activeNames = server.projects.values.filter { $0.state == .active }.map { NameNormalizer.project($0.name) }
        #expect(Set(activeNames).count == activeNames.count, "duplicates are counted on active names only")
        let own = try #require(flats(server).first { $0.openTaskCount == 3 })
        #expect(["Paint", "Sand", "Tile"].allSatisfy { server.task(titled: $0)?.projectID == own.id })
        #expect(mac.workspace.issues.isEmpty)
        try mac.expectInSyncWithServer()
    }

    @Test("021-FR-003 021-FR-028 both sides have an outcome: the account's stays and the issue holds the local one in full")
    func bothHaveAnOutcome() async throws {
        let world = World()
        _ = try await account(world, outcome: "Theirs")
        let mac = await world.device()
        let outcome = String(repeating: "o", count: 1_000)
        try importedFlat(on: mac, outcome: outcome)
        try await mac.signIn()

        #expect(flats(world.snapshot).first?.desiredOutcome == "Theirs")
        let kept = try #require(mac.workspace.issues.first { $0.message == GTDValidationError.outcomeKept.message })
        let description = SyncIssueDescriber.describe(kept, in: mac.workspace.state)
        #expect(description.keptOutcome == outcome && description.keptOutcome?.count == 1_000)
        #expect(!mac.transport.requests.contains { $0.method == .patch && String(decoding: $0.body ?? Data(), as: UTF8.self).contains(outcome) })
    }

    @Test("021-FR-003 021-FR-028 an outcome set after the local archive leaves the account's unchanged, and no PATCH carries the local one")
    func outcomeAfterTheArchive() async throws {
        let world = World()
        _ = try await account(world, outcome: "Theirs")
        let mac = await world.device()
        try importedFlat(on: mac, outcome: "First", afterArchive: [.setProjectOutcome(project: "mac-flat", outcome: "Later")])
        try await mac.signIn()

        #expect(flats(world.snapshot).first?.desiredOutcome == "Theirs")
        #expect(!mac.transport.requests.contains { $0.method == .patch && String(decoding: $0.body ?? Data(), as: UTF8.self).contains("Later") })
        let kept = try #require(mac.workspace.issues.first { $0.message == GTDValidationError.outcomeKept.message })
        #expect(SyncIssueDescriber.describe(kept, in: mac.workspace.state).keptOutcome == "Later")
    }

    @Test("021-FR-003 021-FR-028 a survivor without an outcome gets the later local one, once")
    func survivorWithoutAnOutcome() async throws {
        let world = World()
        _ = try await account(world)
        let mac = await world.device()
        try importedFlat(on: mac, outcome: "First", afterArchive: [.setProjectOutcome(project: "mac-flat", outcome: "Later")])
        try await mac.signIn()

        #expect(flats(world.snapshot).first?.desiredOutcome == "Later")
        let patches = mac.transport.requests.filter { $0.method == .patch && String(decoding: $0.body ?? Data(), as: UTF8.self).contains("desired_outcome") }
        #expect(patches.count == 1)
        #expect(mac.workspace.issues.map(\.message) == [GTDValidationError.archiveNotMerged("Old flat").message])
    }

    // MARK: Review marks

    /// The content bytes of the tasks a mark would be on, by title, and of the project's tasks.
    private func marks(_ workspace: Workspace) throws -> [String: [UInt8]] {
        var result: [String: [UInt8]] = [:]
        for title in ["Quote", "Learn Italian", "Dig"] {
            let task = try #require(workspace.task(titled: title))
            result[title] = RecordContentForm.bytes(of: task, in: workspace.state)
        }
        let project = try #require(workspace.state.projects.values.first { $0.name == "Garden" })
        result["Garden"] = RecordContentForm.bytes(ofTasksIn: project.id, in: workspace.state)
        return result
    }

    @Test("021-FR-023 the content behind Waiting, Someday and Project marks is the same after the upload, the pull, and a sign-out and sign-in")
    func reviewMarksSurviveTheAccount() async throws {
        let world = World()
        let mac = await world.device()
        let app = mac.workspace
        let garden = try app.createProject(name: "Garden")
        try app.apply([
            .createTask(.init(taskID: "dig", title: "Dig", list: .next, projectID: garden, tagIDs: [])),
            .createTask(.init(taskID: "quote", title: "Quote", list: .waiting, waitingFor: "Harbour Hall")),
            .createTask(.init(taskID: "italian", title: "Learn Italian", list: .someday)),
            .createSubtask(.init(taskID: "dig", subtaskID: "step", title: "Find the spade")),
        ])
        let before = try marks(app)

        world.clock.advance(by: 60)
        try await mac.signIn()
        #expect(try marks(app) == before, "after the upload")
        world.clock.advance(by: 120)
        await app.syncNow()
        await mac.settle()
        #expect(try marks(app) == before, "after a pull")

        try await app.signOut(discardUnsyncedChanges: false)
        await mac.settle()
        #expect(app.state.tasks.isEmpty)
        try await mac.signIn()
        #expect(try marks(app) == before, "after sign-out and sign-in to the same account")
    }

    // MARK: The real import

    /// The Mac importer's output over its populated fixture (review c2, G21), kept byte-identical by
    /// `macos/Tests/BrainBuddyMacTests/LegacyStoreImporterTests.swift`.
    private func goldenImport() throws -> StoreDocument {
        let url = try #require(Bundle.module.url(forResource: "legacy-import-golden", withExtension: "json", subdirectory: "Resources"))
        return try StoreDocumentCoding.decode(Data(contentsOf: url))
    }

    @Test("021-FR-003 021-SC-003 the imported Mac store signs in against an account with Old flat, garden and Calls: no duplicate, nothing missing")
    func goldenImportSignsIn() async throws {
        let document = try goldenImport()
        let imported = document.replayed().state
        #expect(imported.tasks.count == 18 && imported.projects.count == 6, "the importer's real output")

        let world = World()
        let phone = await world.device()
        try await phone.signIn()
        _ = try phone.workspace.createProject(name: "Old flat")
        _ = try phone.workspace.createProject(name: "garden")
        _ = try phone.workspace.createTag(name: "Calls")
        await phone.workspace.syncNow()
        await phone.settle()

        let mac = await world.device(store: InMemoryDocumentStore(document: document))
        #expect(mac.workspace.state.tasks.count == 18)
        try await mac.signIn()

        let server = world.snapshot
        let activeProjects = server.projects.values.filter { $0.state == .active }.map { NameNormalizer.project($0.name) }
        #expect(Set(activeProjects).count == activeProjects.count, "0 duplicate active projects")
        let activeTags = server.tags.values.filter { $0.state == .active }.map { NameNormalizer.tag($0.name) }
        #expect(Set(activeTags).count == activeTags.count, "0 duplicate active tags")
        for task in imported.tasks.values {
            #expect(server.task(titled: task.title) != nil, "“\(task.title)” reached the account")
        }
        #expect(server.tasks.count == imported.tasks.count, "0 missing, none doubled")
        let flat = try #require(server.projects.values.first { $0.name == "Old flat" })
        #expect(flat.state == .active, "the archived Mac project merged into the account's active one")
        for title in ["Paint the hallway", "Return the keys", "Sell the old sofa"] {
            #expect(server.task(titled: title)?.projectID == flat.id)
        }
        #expect(mac.workspace.issues.map(\.message) == [GTDValidationError.archiveNotMerged("Old flat").message])
        #expect(mac.rejectedRequests.isEmpty)
        try mac.expectInSyncWithServer()
    }
}
