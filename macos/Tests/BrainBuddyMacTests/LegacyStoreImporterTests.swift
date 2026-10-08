import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The one-time import of the pre-021 Mac store (contracts/mac-legacy-import.md §6; data-model
/// E7.1, E8): the import and its verification (T092), and the durable state machine that never
/// writes into, merges with or replaces a workspace in use (T093).
@Suite("Legacy store import")
struct LegacyStoreImporterTests {
    // MARK: - Helpers

    private func task(_ state: GTDState, _ title: String) throws -> TaskRecord {
        try #require(state.tasks.values.first { $0.title == title }, "no task “\(title)”")
    }

    private func project(_ state: GTDState, _ name: String, archived: Bool) throws -> ProjectRecord {
        try #require(state.projects.values.first { $0.name == name && ($0.state == .archived) == archived })
    }

    private func importRecord(_ folder: TemporaryFolder) -> LegacyImportRecord? {
        MacLocalStateStore(directory: folder.url).load()?.legacyImport
    }

    private func importPopulated(
        _ folder: TemporaryFolder, clock: TestClock = TestClock(), ids: SequentialIDs = SequentialIDs(),
        log: CapturingMacLog = CapturingMacLog()
    ) throws -> LegacyImportLaunchResult {
        try Fixture.install("legacy-populated", in: folder)
        return try LegacyImportCoordinator.forTest(folder, clock: clock, ids: ids, log: log).run()
    }

    private func openList(_ state: GTDState, _ list: OpenList) -> [String] {
        GTDQueries.list(.list(list), options: ListOptions(), in: state, today: CalendarDay(date: TestClock.importTime))
            .sections.flatMap(\.tasks).map(\.title)
    }

    // MARK: - T092: import and verification

    @Test("021-FR-020 021-SC-003 the populated fixture imports with every §3 equality, silently, and the old file becomes the backup")
    func populated() throws {
        let folder = TemporaryFolder()
        let original = try Fixture.data("legacy-populated")
        let result = try importPopulated(folder)

        #expect(result.row == 2)
        #expect(result.notices.isEmpty, "a normal upgrade shows no notice")
        let record = try #require(importRecord(folder))
        #expect(record.state == .completed && record.legacyRenamedAt != nil && record.importedAt == TestClock.importTime)
        #expect(record.backupFileName == "local-gtd.backup-20261006T143400Z.json")
        #expect(folder.bytes("local-gtd.backup-20261006T143400Z.json") == original, "the backup is the file, unchanged")
        #expect(!MacFiles.exists(folder.legacy))
        #expect(!folder.names.contains { $0.hasPrefix("store.import-") }, "no staging file is left")

        let state = try storedState(folder)
        #expect(state.tasks.count == 18)
        #expect(state.projects.count == 6 && state.tags.count == 3, "the deleted tag is not carried")
        let van = try task(state, "Book a van")
        #expect(van.subtasks.map(\.title) == ["Compare prices", "Measure the boxes", "Ask Sam about his van"])
        #expect(van.subtasks.map(\.state) == [.open, .completed, .cancelled])
        #expect(van.comments.map(\.body) == ["Van company said Friday is free", "Budget is 120 EUR, fuel included"])
        #expect(van.comments.allSatisfy { $0.editedAt == nil }, "the edit marker is not carried")
        #expect(van.priority == .medium)
        let deposit = try task(state, "Deposit back from landlord")
        #expect(deposit.state == .waiting && deposit.waitingFor == "Landlord")
        #expect(deposit.createdAt == LegacySnapshot.date("2026-09-25T09:00:00Z"))
        #expect(deposit.waitingSince == LegacySnapshot.date("2026-09-28T16:45:00Z"), "waitingSince ≠ createdAt, to the second")
        let seeds = try task(state, "Buy seeds")
        #expect(seeds.state == .completed && seeds.lastOpenList == .next)
        #expect(seeds.completedAt == LegacySnapshot.date("2026-09-18T17:30:00Z"))
        let landlord = try task(state, "Call the old landlord")
        #expect(landlord.state == .cancelled && landlord.lastOpenList == .waiting && landlord.waitingFor == nil)
        #expect(try task(state, "Call the plumber").tagIDs.count == 1, "the deleted tag reference is dropped quietly")
        #expect(try task(state, "Order soil").dueDate == CalendarDay(isoString: "2026-10-10"))

        // Archived projects keep their tasks; the Russian name takes the kit's form and its active
        // namesake stays apart, archived first (§2 step 2).
        let oldFlat = try project(state, "Old flat", archived: true)
        #expect(oldFlat.desiredOutcome == "Keys returned and the deposit back")
        #expect(state.tasks.values.filter { $0.projectID == oldFlat.id }.count == 3)
        let oldKv = try project(state, "Квартира No5", archived: true)
        let kv = try project(state, "Квартира No5", archived: false)
        #expect(oldKv.id != kv.id)
        #expect(try task(state, "Read the gas meter").projectID == oldKv.id)
        #expect(try project(state, "Garden", archived: false).desiredOutcome == "Vegetables growing by May")
        _ = try project(state, "Tax return 2024", archived: true)

        // One Next list across three projects and no project, in the Mac's order.
        #expect(
            openList(state, .next) == [
                "Order soil", "Book a van", "Renew passport", "Paint the hallway", "Plan the beds", "Return the keys",
                "Pack the kitchen",
            ]
        )
        #expect(openList(state, .waiting) == ["Deposit back from landlord", "Quote from movers", "Spare key from the neighbour"])
        #expect(openList(state, .someday) == ["Read the gas meter", "Sell the old sofa", "Build a greenhouse", "Learn pottery"])
        #expect(openList(state, .inbox) == ["Call the plumber"])
        #expect(record.report?.adjustedCount == 1 && record.report?.notCarriedCount == 0, "only “Квартира №5” changed")
    }

    @Test("021-FR-020 021-SC-003 the awkward fixture verifies against the canonical expectation and the report lists exactly the adjustments")
    func awkward() throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-awkward", in: folder)
        let result = try LegacyImportCoordinator.forTest(folder).run()

        #expect(result.notices.isEmpty, "adjustments alone stay silent apart from the X-02 line")
        let record = try #require(importRecord(folder))
        #expect(record.state == .completed && record.report?.notCarriedCount == 0)
        let reportName = try #require(record.report?.fileName)
        #expect(reportName == "local-gtd.import-report-20261006T143400Z.txt")
        let report = try #require(folder.bytes(reportName).map { String(decoding: $0, as: UTF8.self) })

        let state = try storedState(folder)
        let names = state.projects.values.map(\.name).sorted()
        #expect(names == ["Home Repair", "Home Repair", "Home Repair (2)", "TM Ideas", "Квартира No5"])
        #expect(state.tags.values.map(\.name).sorted() == ["Errands", "home", "home (2)"])
        let emoji = try #require(state.tasks.values.first { $0.title.hasSuffix("…") })
        #expect(emoji.title.unicodeScalars.count <= 500)
        #expect(emoji.details?.hasPrefix("Full title: ") == true)
        #expect(try task(state, "Call  mom").title == "Call  mom", "titles are not collapsed")
        let notes = try task(state, "Long notes")
        #expect((notes.details?.unicodeScalars.count ?? 0) <= 20_000)
        #expect(notes.comments.count == 1 && notes.comments[0].body.hasPrefix("Notes, continued (1 of 1):"))
        let comment = try task(state, "Long comment")
        #expect(comment.comments.count == 2 && comment.comments[1].body.hasPrefix("(continued)"))
        let ideas = try project(state, "TM Ideas", archived: false)
        #expect(ideas.desiredOutcome?.unicodeScalars.count == 1_000 && ideas.color == nil)
        #expect(try task(state, "Lost project").projectID == nil)

        // Exactly one report line per adjusted value, none missing.
        let lines = report.split(separator: "\n").filter { $0.hasPrefix("- ") }
        #expect(lines.count == record.report?.adjustedCount)
        for expected in [
            "- project: “Квартира №5” → “Квартира No5”", "- project: “™ Ideas” → “TM Ideas”",
            "- project: “Home  Repair” → “Home Repair”", "- project: “Home Repair” → “Home Repair (2)”",
            "- tag: “@home” → “home”", "- tag: “home” → “home (2)”", "- tag: “Errands ” → “Errands”",
            "- task project reference: “project_missing” → “”",
        ] {
            #expect(lines.contains { $0.hasPrefix(expected) }, "the report lists \(expected)")
        }
        for kind in ["task title", "task notes", "comment", "project outcome", "project colour"] {
            #expect(lines.contains { $0.hasPrefix("- \(kind): ") }, "the report lists a \(kind)")
        }
        #expect(!lines.contains { $0.contains("Call  mom") })
    }

    @Test("021-FR-003 021-SC-003 the importer turns the populated fixture into the golden artifact, byte for byte")
    func goldenArtifact() throws {
        let folder = TemporaryFolder()
        _ = try importPopulated(folder)
        let produced = try #require(folder.bytes(LegacyFileNames.store))
        if ProcessInfo.processInfo.environment["BRAINBUDDY_RECORD_GOLDEN"] == "1" {
            try produced.write(to: Repository.goldenImport)
        }
        let golden = try Data(contentsOf: Repository.goldenImport)
        #expect(produced == golden, "regenerate with BRAINBUDDY_RECORD_GOLDEN=1 only for a deliberate change")
        // Sorted keys and the same instants make the run reproducible.
        let again = TemporaryFolder()
        _ = try importPopulated(again)
        #expect(again.bytes(LegacyFileNames.store) == produced)
    }

    @Test("021-FR-003 021-FR-020 the archived Old flat is createProject, three createTask and archiveProject, nothing compacted")
    func outboxShape() throws {
        let snapshot = try Fixture.snapshot("legacy-populated")
        let plan = try LegacyStoreImporter.plan(snapshot, importedAt: TestClock.importTime, makeID: SequentialIDs().provider)
        let flat = try #require(plan.expectation.projects.first { $0.name == "Old flat" }).id
        let flatTasks = Set(plan.expectation.tasks.filter { $0.projectID == flat }.map(\.id))
        let shape = plan.document.outbox.compactMap { operation -> String? in
            switch operation.command {
            case .createProject(let create) where create.projectID == flat: "createProject"
            case .createTask(let create) where flatTasks.contains(create.taskID): "createTask"
            case .archiveProject(let id) where id == flat: "archiveProject"
            default: nil
            }
        }
        #expect(shape == ["createProject", "createTask", "createTask", "createTask", "archiveProject"])
        // Every legacy step is its own operation: the Waiting task re-entering Waiting keeps both moves.
        let moves = plan.document.outbox.filter { if case .transitionTask = $0.command { true } else { false } }
        #expect(moves.count == 4, "2 moves for the late Waiting task, 1 complete, 1 cancel")
    }

    @Test("021-FR-022 a corrupt file is left exactly as it was: no staging file, no store.json, the corrupt notice")
    func corrupt() throws {
        let folder = TemporaryFolder()
        let original = try Fixture.install("legacy-corrupt", in: folder)
        let result = try LegacyImportCoordinator.forTest(folder).run()

        #expect(folder.bytes(LegacyFileNames.legacy) == original)
        #expect(!MacFiles.exists(folder.store) && !folder.names.contains { $0.hasPrefix("store.import-") })
        #expect(importRecord(folder)?.state == .unreadable && importRecord(folder)?.unreadableReason == .corrupt)
        let notice = try #require(result.notices.first)
        #expect(notice == .unreadable(.corrupt, file: folder.legacy))
        #expect(notice.title == "Brain Buddy couldn't read your earlier tasks")
        #expect(notice.textBeforePath == "The file from the previous version was left exactly as it was. It's here:")
        #expect(notice.textAfterPath == "Brain Buddy will start with an empty workspace. Keep the file if you'd like help recovering it.")
    }

    @Test("021-FR-022 a file from a newer version is left as it was, with the newer-version notice")
    func newerVersion() throws {
        let folder = TemporaryFolder()
        let original = try Fixture.install("legacy-newer", in: folder)
        let result = try LegacyImportCoordinator.forTest(folder).run()

        #expect(folder.bytes(LegacyFileNames.legacy) == original)
        #expect(!MacFiles.exists(folder.store) && !folder.names.contains { $0.hasPrefix("store.import-") })
        #expect(importRecord(folder)?.unreadableReason == .newerVersion)
        let notice = try #require(result.notices.first)
        #expect(notice.textBeforePath.hasPrefix("They were saved by a newer version of Brain Buddy"))
        #expect(notice.textAfterPath == "Install the newer version to open the file again.")
    }

    @Test("021-FR-020 021-FR-022 a record forced through “not carried” is listed, the rest imports, the notice shows once, the backup is kept")
    func partlyCarried() throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-populated", in: folder)
        let clock = TestClock()
        let coordinator = LegacyImportCoordinator.forTest(
            folder, clock: clock, hooks: LegacyImportTestHooks(notCarried: ["task_pottery"])
        )
        let result = try coordinator.run()

        let record = try #require(importRecord(folder))
        #expect(record.state == .completed && record.report?.notCarriedCount == 1)
        let report = try #require(record.report.flatMap { folder.bytes($0.fileName) }.map { String(decoding: $0, as: UTF8.self) })
        #expect(report.contains("Not carried over") && report.contains("“Learn pottery”"))
        #expect(try storedState(folder).tasks.count == 17)
        let notice = try #require(result.notices.first)
        #expect(notice == .partlyCarried(report: folder.file(record.report!.fileName)))
        #expect(notice.title == "Brain Buddy carried over your earlier tasks, except a few it couldn't read")
        try coordinator.recordNoticeSeen(notice)
        #expect(try coordinator.run().notices.isEmpty, "shown once")

        var due = record
        due.signedOutSinceImport = true
        #expect(!LegacyImportCoordinator.backupIsDue(due, now: clock.now.addingTimeInterval(90 * TestClock.day), atSignOutWithInitialUpload: 0))
    }

    @Test("021-FR-022 an injected verification mismatch records verificationFailed and keeps the file; no store.json")
    func verificationFailure() throws {
        let folder = TemporaryFolder()
        let original = try Fixture.install("legacy-populated", in: folder)
        let hooks = LegacyImportTestHooks(tamperStaging: { document in document.outbox.removeLast() })
        let result = try LegacyImportCoordinator.forTest(folder, hooks: hooks).run()

        #expect(importRecord(folder)?.state == .unreadable && importRecord(folder)?.unreadableReason == .verificationFailed)
        #expect(folder.bytes(LegacyFileNames.legacy) == original)
        #expect(!MacFiles.exists(folder.store) && !folder.names.contains { $0.hasPrefix("store.import-") })
        let notice = try #require(result.notices.first)
        #expect(notice.title == "Brain Buddy couldn't carry over your earlier tasks")
        #expect(notice.textBeforePath == "Your file is fine and was left exactly as it was. It's here:")
        let after = try #require(notice.textAfterPath)
        #expect(after.hasPrefix("This is a problem in Brain Buddy.") && !after.contains("later version"))
    }

    @Test("021-FR-030 the import log holds counts and enum names only: no title, no path, no file name, no digest")
    func logPrivacy() throws {
        let home = "Users/sentinel-home-7f3a/Library/Application Support/BrainBuddyMac"
        let log = CapturingMacLog()
        // Populated, awkward, corrupt, newer, verification failed, partly carried, later file.
        for (fixture, hooks) in [
            ("legacy-populated", LegacyImportTestHooks()), ("legacy-awkward", LegacyImportTestHooks()),
            ("legacy-corrupt", LegacyImportTestHooks()), ("legacy-newer", LegacyImportTestHooks()),
            ("legacy-populated", LegacyImportTestHooks(tamperStaging: { $0.outbox.removeLast() })),
            ("legacy-populated", LegacyImportTestHooks(notCarried: ["task_van"])),
        ] {
            let folder = TemporaryFolder(home)
            try Fixture.install(fixture, in: folder)
            _ = try LegacyImportCoordinator.forTest(folder, log: log, hooks: hooks).run()
        }
        let later = TemporaryFolder(home)
        _ = try importPopulated(later, log: log)
        try Fixture.install("legacy-awkward", in: later)
        _ = try LegacyImportCoordinator.forTest(later, log: log).run()

        let lines = log.messages()
        #expect(!lines.isEmpty)
        let snapshot = try Fixture.snapshot("legacy-populated")
        let sentinels = snapshot.tasks.map(\.title) + snapshot.projects.map(\.name) + ["sentinel-home-7f3a", "/Users/", "local-gtd", ".json", ".txt", "store.import", "backup-", "report-"]
        for line in lines {
            for sentinel in sentinels { #expect(!line.contains(sentinel), "“\(line)” contains \(sentinel)") }
            #expect(line.firstMatch(of: #/[0-9A-Fa-f]{32}/#) == nil, "“\(line)” holds a digest")
        }
        #expect(lines.contains("import unreadable reason=corrupt") && lines.contains("import unreadable reason=newerVersion"))
        #expect(lines.contains("import unreadable reason=verificationFailed") && lines.contains("later file kept"))
        #expect(lines.contains { $0.hasPrefix("import completed tasks=18 ") })
    }

    // MARK: - T093: the state machine

    @Test("021-FR-033 a first launch without a previous-version file records none, durably, before the workspace opens")
    func freshInstallRecordsNone() throws {
        let folder = TemporaryFolder()
        let result = try LegacyImportCoordinator.forTest(folder).run()
        #expect(result.row == 1 && result.notices.isEmpty)
        #expect(importRecord(folder)?.state == LegacyImportRecord.State.none)
        #expect(MacFiles.exists(folder.sidecar))
    }

    @Test("021-FR-021 021-FR-033 inProgress is on disk before the staging file; completed holds the keyed digest, the backup and legacyRenamedAt")
    func importStateIsExplicit() throws {
        let folder = TemporaryFolder()
        let data = try Fixture.install("legacy-populated", in: folder)
        #expect(throws: SimulatedCrash.self) {
            try LegacyImportCoordinator.forTest(folder, hooks: LegacyImportTestHooks(crash: .afterInProgress)).run()
        }
        let inProgress = try #require(importRecord(folder))
        #expect(inProgress.state == .inProgress && inProgress.attemptID != nil)
        #expect(!folder.names.contains { $0.hasPrefix("store.import-") }, "no staging file before inProgress is recorded")

        _ = try LegacyImportCoordinator.forTest(folder).run()
        let completed = try #require(importRecord(folder))
        let salt = try #require(MacLocalStateStore(directory: folder.url).load())
        #expect(completed.state == .completed && completed.importedLegacyDigest == salt.digest(of: data))
        #expect(completed.importedLegacyDigest?.count == 64 && completed.importedLegacyDigest != inProgress.attemptID?.uuidString)
        #expect(completed.backupFileName != nil && completed.legacyRenamedAt != nil)
    }

    @Test("021-FR-033 the first write of store.json records workspaceFirstWrittenAt")
    @MainActor
    func firstWriteIsRecorded() async throws {
        let folder = TemporaryFolder()
        let host = WorkspaceHost(
            configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: SpyTokenStore(),
            transport: CountingTransport(), now: TestClock().provider
        )
        await host.workspace.load()
        #expect(MacLocalStateStore(directory: folder.url).load()?.workspaceFirstWrittenAt == nil)
        try host.workspace.capture(.init(text: "Call the landlord"))
        await host.workspace.flush()
        #expect(MacLocalStateStore(directory: folder.url).load()?.workspaceFirstWrittenAt == TestClock.importTime)
    }

    /// Runs a launch with a previous-version file beside a workspace in use and checks FR-033: no
    /// import, every file's bytes unchanged, and the "later file" notice exactly once.
    private func expectLaterFileKept(_ folder: TemporaryFolder, clock: TestClock = TestClock()) throws {
        let kept = folder.names.filter { !$0.hasPrefix(".") && $0 != MacLocalStateStore.fileName && !LegacyFileNames.isStaging($0) }
        let before = Dictionary(uniqueKeysWithValues: kept.map { ($0, folder.bytes($0)) })
        let coordinator = LegacyImportCoordinator.forTest(folder, clock: clock, ids: SequentialIDs(namespace: 7))
        let first = try coordinator.run()
        #expect(first.notices == [.laterFile(file: folder.legacy)])
        let notice = try #require(first.notices.first)
        #expect(notice.title == "Brain Buddy found tasks from the previous version")
        #expect(notice.textAfterPath == "Your current tasks are unchanged.")
        for (name, bytes) in before { #expect(folder.bytes(name) == bytes, "\(name) is unchanged") }
        #expect(!folder.names.contains { $0.hasPrefix("store.import-") })
        try coordinator.recordNoticeSeen(notice)
        #expect(try coordinator.run().notices.isEmpty, "the notice shows once")
        for (name, bytes) in before { #expect(folder.bytes(name) == bytes, "\(name) is still unchanged") }
    }

    @Test("021-FR-033 a file that appears after a fresh install beside a workspace with records is kept, never imported")
    @MainActor
    func laterFileAfterFreshInstall() async throws {
        let folder = TemporaryFolder()
        _ = try LegacyImportCoordinator.forTest(folder).run()
        let document = StoreDocument(
            outbox: [PendingOperation(command: .createTask(.init(taskID: "t1", title: "Mine", list: .inbox)), issuedAt: TestClock.importTime)],
            account: LinkedAccount(id: "u1", email: "alex@example.com", serverURL: URL(string: "https://api.example.com")!, linkedAt: TestClock.importTime)
        )
        try StoreDocumentCoding.encode(document).write(to: folder.store)
        try Fixture.install("legacy-populated", in: folder)
        try expectLaterFileKept(folder)
        #expect(importRecord(folder)?.state == .laterFileKept)
    }

    @Test("021-FR-033 with mac-local.json removed, a file beside store.json is a later file")
    func laterFileAfterSidecarLoss() throws {
        let folder = TemporaryFolder()
        _ = try importPopulated(folder)
        try FileManager.default.removeItem(at: folder.sidecar)
        try Fixture.install("legacy-awkward", in: folder)
        try expectLaterFileKept(folder)
    }

    @Test("021-FR-033 an old build writing a new file after the rename leaves a later file; the record stays completed")
    func laterFileAfterRename() throws {
        let folder = TemporaryFolder()
        _ = try importPopulated(folder)
        try Fixture.install("legacy-awkward", in: folder)
        try expectLaterFileKept(folder)
        #expect(importRecord(folder)?.state == .completed && importRecord(folder)?.laterFile != nil)
    }

    @Test("021-FR-033 after a sign-out removed store.json, an older copy's new file is a later file, not an import")
    func laterFileAfterSignOut() throws {
        let folder = TemporaryFolder()
        _ = try importPopulated(folder)
        try FileManager.default.removeItem(at: folder.store)
        try LegacyImportCoordinator.forTest(folder).didSignOut(initialUploadRemaining: 0)
        try Fixture.install("legacy-awkward", in: folder)
        try expectLaterFileKept(folder)
        #expect(!MacFiles.exists(folder.store), "nothing was imported into the emptied workspace")
    }

    @Test("021-FR-033 signed out without an import, a file that appears is a later file")
    func laterFileAfterSignOutWithoutImport() throws {
        let folder = TemporaryFolder()
        _ = try LegacyImportCoordinator.forTest(folder).run()
        _ = try MacLocalStateStore(directory: folder.url).update { $0.workspaceFirstWrittenAt = TestClock.importTime }
        try Fixture.install("legacy-populated", in: folder)
        try expectLaterFileKept(folder)
    }

    @Test("021-FR-033 the backup deleted by retention, then the original restored: kept as found, not renamed or deleted")
    func laterFileAfterRetention() throws {
        let folder = TemporaryFolder()
        let clock = TestClock()
        _ = try importPopulated(folder, clock: clock)
        clock.advance(31 * TestClock.day)
        #expect(try LegacyImportCoordinator.forTest(folder, clock: clock).didSignOut(initialUploadRemaining: 0))
        #expect(importRecord(folder)?.backupDeletedAt != nil)
        try Fixture.install("legacy-populated", in: folder)
        try expectLaterFileKept(folder, clock: clock)
        #expect(MacFiles.exists(folder.legacy))
    }

    @Test("021-FR-033 an inProgress record beside a store.json it did not create: store.json untouched, its staging file deleted")
    func inProgressWithForeignStore() throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-populated", in: folder)
        #expect(throws: SimulatedCrash.self) {
            try LegacyImportCoordinator.forTest(folder, hooks: LegacyImportTestHooks(crash: .afterStaging)).run()
        }
        #expect(folder.names.contains { $0.hasPrefix("store.import-") })
        let foreign = try StoreDocumentCoding.encode(StoreDocument())
        try foreign.write(to: folder.store)
        try expectLaterFileKept(folder)
        #expect(folder.bytes(LegacyFileNames.store) == foreign)
        #expect(importRecord(folder)?.state == .laterFileKept)
    }

    @Test("021-FR-033 an older copy that keeps writing shows no second notice")
    func olderCopyKeepsWriting() throws {
        let folder = TemporaryFolder()
        _ = try importPopulated(folder)
        try Fixture.install("legacy-awkward", in: folder)
        let coordinator = LegacyImportCoordinator.forTest(folder)
        let first = try coordinator.run()
        try coordinator.recordNoticeSeen(try #require(first.notices.first))
        try Data("{\"version\": 1, \"changed\": true}".utf8).write(to: folder.legacy)
        #expect(try coordinator.run().notices.isEmpty)
    }

    @Test("021-FR-033 an unwritten fresh workspace still imports a file copied in later (row 2)")
    func unwrittenFreshWorkspaceImports() throws {
        let folder = TemporaryFolder()
        _ = try LegacyImportCoordinator.forTest(folder).run()
        #expect(importRecord(folder)?.state == LegacyImportRecord.State.none)
        let result = try importPopulated(folder)
        #expect(result.row == 2 && importRecord(folder)?.state == .completed && MacFiles.exists(folder.store))
    }

    @Test("021-FR-021 a crash after each step recovers on the next run, with no duplicate record", arguments: [
        LegacyImportTestHooks.CrashPoint.afterInProgress, .afterStaging, .afterVerification, .afterCompleted, .betweenRenames,
    ])
    func crashesRecover(point: LegacyImportTestHooks.CrashPoint) throws {
        let folder = TemporaryFolder()
        let original = try Fixture.install("legacy-populated", in: folder)
        #expect(throws: SimulatedCrash.self) {
            try LegacyImportCoordinator.forTest(folder, hooks: LegacyImportTestHooks(crash: point)).run()
        }
        if point != .betweenRenames { #expect(folder.bytes(LegacyFileNames.legacy) == original, "untouched until the rename") }
        if MacFiles.exists(folder.store) { #expect(try storedState(folder).tasks.count == 18, "store.json is the verified import") }

        let result = try LegacyImportCoordinator.forTest(folder, ids: SequentialIDs(namespace: 3)).run()
        #expect(result.notices.isEmpty)
        #expect(importRecord(folder)?.state == .completed && importRecord(folder)?.legacyRenamedAt != nil)
        #expect(try storedState(folder).tasks.count == 18)
        #expect(!MacFiles.exists(folder.legacy) && !folder.names.contains { $0.hasPrefix("store.import-") })
        #expect(folder.names.filter { $0.hasPrefix("local-gtd.backup-") }.count == 1)
    }

    @Test("021-FR-021 a crash between the record and the rename finishes only the rename (row 9)")
    func crashBetweenRenamesFinishesOnlyTheRename() throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-populated", in: folder)
        #expect(throws: SimulatedCrash.self) {
            try LegacyImportCoordinator.forTest(folder, hooks: LegacyImportTestHooks(crash: .betweenRenames)).run()
        }
        let store = folder.bytes(LegacyFileNames.store)
        #expect(importRecord(folder)?.legacyRenamedAt == nil)
        let result = try LegacyImportCoordinator.forTest(folder).run()
        #expect(result.row == 9)
        #expect(folder.bytes(LegacyFileNames.store) == store, "store.json is not rewritten")
        #expect(importRecord(folder)?.legacyRenamedAt != nil && !MacFiles.exists(folder.legacy))
    }

    @Test("021-FR-033 staging files: one orphaned by a lost sidecar goes at the next launch; a sign-out deletes every one")
    func stagingCleanup() throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-populated", in: folder)
        #expect(throws: SimulatedCrash.self) {
            try LegacyImportCoordinator.forTest(folder, hooks: LegacyImportTestHooks(crash: .afterStaging)).run()
        }
        let orphan = try #require(folder.names.first { $0.hasPrefix("store.import-") })
        try FileManager.default.removeItem(at: folder.sidecar)
        _ = try LegacyImportCoordinator.forTest(folder, ids: SequentialIDs(namespace: 4)).run()
        #expect(!folder.names.contains(orphan) && !folder.names.contains { $0.hasPrefix("store.import-") })

        try Data("{}".utf8).write(to: folder.file("store.import-\(UUID().uuidString.lowercased()).json"))
        try LegacyImportCoordinator.forTest(folder).didSignOut(initialUploadRemaining: 0)
        #expect(!folder.names.contains { $0.hasPrefix("store.import-") })
    }

    @Test("021-FR-021 the backup retention table", arguments: [
        // days, sign-out since import, first upload left at the sign-out, not carried, sidecar lost, deleted
        (29, true, 0, 0, false, false), (31, false, 0, 0, false, false), (31, true, 0, 0, false, true),
        (31, true, 12, 0, false, false), (31, true, 0, 1, false, false), (31, true, 0, 0, true, false),
    ])
    func backupRetention(days: Int, signOut: Bool, firstUpload: Int, notCarried: Int, sidecarLost: Bool, deleted: Bool) throws {
        let folder = TemporaryFolder()
        let clock = TestClock()
        try Fixture.install("legacy-populated", in: folder)
        let hooks = LegacyImportTestHooks(notCarried: notCarried > 0 ? ["task_pottery"] : [])
        _ = try LegacyImportCoordinator.forTest(folder, clock: clock, hooks: hooks).run()
        let backup = try #require(importRecord(folder)?.backupFileName)
        if sidecarLost { try FileManager.default.removeItem(at: folder.sidecar) }
        clock.advance(Double(days) * TestClock.day)
        let coordinator = LegacyImportCoordinator.forTest(folder, clock: clock)
        if signOut {
            // The state right after the sign-out (a sign-out during the first upload keeps the
            // backup until a later qualifying launch or sign-out, data-model E8 condition 4).
            let willRemove = coordinator.backupWillBeRemovedAtSignOut(initialUploadRemaining: firstUpload)
            #expect(willRemove == deleted, "the X-04 text ends with signOutBackupRemoved exactly when it goes")
            try coordinator.didSignOut(initialUploadRemaining: firstUpload)
        } else {
            _ = try coordinator.run()
        }
        #expect(MacFiles.exists(folder.file(backup)) == !deleted)
        if sidecarLost {
            let kept = try #require(coordinator.backup())
            #expect(kept.keptUntil == TestClock.importTime.addingTimeInterval(30 * TestClock.day), "the date from the file name")
        }
    }

    @Test("021-FR-020 an old copy holding the legacy lock blocks the import; after the rename its next write is refused")
    func oldCopyStillRunning() async throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-populated", in: folder)
        let gate = GateLegacyLocking()
        let coordinator = LegacyImportCoordinator.forTest(folder, locking: gate)
        let run = Task.detached { try coordinator.run() }
        try await Task.sleep(nanoseconds: 50_000_000)
        #expect(!gate.acquired && MacFiles.exists(folder.legacy) && importRecord(folder) == nil, "nothing read while the old copy writes")
        gate.open()
        _ = try await run.value
        #expect(importRecord(folder)?.state == .completed)
        // The pre-021 store's guard before each write (`LocalGTDStore.mutate`, deleted by T109): a
        // missing file with a non-zero generation is a 409, and nothing is written.
        let generation = try Fixture.snapshot("legacy-populated").generation
        #expect(!MacFiles.exists(folder.legacy) && generation != 0, "an older copy's next write fails with its 409")
    }

    @Test("021-FR-023 review marks survive the import, and a due mark stays due")
    func reviewMarksSurvive() throws {
        let folder = TemporaryFolder()
        _ = try importPopulated(folder)
        let local = try #require(MacLocalStateStore(directory: folder.url).load())
        let state = try storedState(folder)
        let now = TestClock.importTime
        #expect(!local.waitingReviewDue(try task(state, "Quote from movers"), in: state, now: now), "reviewed 2 days ago")
        #expect(local.waitingReviewDue(try task(state, "Spare key from the neighbour"), in: state, now: now), "a due mark stays due")
        #expect(local.waitingReviewDue(try task(state, "Deposit back from landlord"), in: state, now: now), "a stale receipt is dropped")
        #expect(!local.somedayReviewDue(try task(state, "Build a greenhouse"), in: state, now: now))
        #expect(local.somedayReviewDue(try task(state, "Learn pottery"), in: state, now: now))
        let garden = try project(state, "Garden", archived: false)
        #expect(local.validProjectMark(for: garden, in: state, now: now)?.decision == .keep)
        #expect(local.projectMark(for: try project(state, "Move flat", archived: false)) == nil, "changed since review: dropped")
        #expect(local.waitingReviews.keys.allSatisfy { $0.hasPrefix("c:") })
    }
}

// MARK: - Volume

/// The two heavy cases run one after the other, so the time budget is not measured while the
/// property test competes for the same cores.
@Suite("Legacy store import: volume", .serialized)
struct LegacyStoreImportVolumeTests {
    private func importRecord(_ folder: TemporaryFolder) -> LegacyImportRecord? {
        MacLocalStateStore(directory: folder.url).load()?.legacyImport
    }

    @Test("021-FR-020 for 500 seeds a store the old app accepts imports, verifies and carries every record")
    func propertyEveryAcceptedStoreImports() throws {
        for seed in 0..<500 {
            var generator = LegacyStoreGenerator(seed: UInt64(seed))
            let data = try generator.store()
            let snapshot = try LegacySnapshot.read(data)
            let ids = SequentialIDs(namespace: seed % 9_999)
            let plan = try LegacyStoreImporter.plan(snapshot, importedAt: TestClock.importTime, makeID: ids.provider)
            var document = plan.document
            document.generation = 1
            let problems = LegacyStoreImporter.verify(
                try StoreDocumentCoding.encode(document), against: plan.expectation,
                today: CalendarDay(date: TestClock.importTime)
            )
            #expect(problems.isEmpty, "seed \(seed): \(problems)")
            #expect(plan.notCarried.isEmpty && plan.counts.tasks == snapshot.tasks.count, "seed \(seed) carried everything")
            #expect(plan.counts.projects == snapshot.projects.count)
            if !problems.isEmpty { break }
        }
    }

    @Test("021-FR-020 2,000 tasks with subtasks and comments import and verify within 10 s")
    func timeBudget() throws {
        let folder = TemporaryFolder()
        var generator = LegacyStoreGenerator(seed: 2_000)
        try generator.store(tasks: 2_000, subtasksPerTask: 2, commentsPerTask: 1).write(to: folder.legacy)
        let started = Date()
        _ = try LegacyImportCoordinator.forTest(folder).run()
        let elapsed = Date().timeIntervalSince(started)
        #expect(importRecord(folder)?.state == .completed)
        #expect(try storedState(folder).tasks.count == 2_000)
        #expect(elapsed < 10, "took \(elapsed) s")
    }
}

// MARK: - Stores the old app could write

/// A seeded generator of stores that satisfy `LocalGTDStore`'s own rules (read from
/// `macos/Sources/BrainBuddyMac/LocalGTDStore.swift` before T109 deleted it): names and titles
/// trimmed with Foundation whitespace and 1 – 500 grapheme clusters, outcomes up to 1,000, comments
/// up to 20,000, notes unlimited, project names unique among all projects and active tag names
/// unique among active tags under `localizedCaseInsensitiveCompare`, waiting-for required in
/// Waiting. Names draw on NFKC-sensitive characters, "@" prefixes, runs of spaces and emoji.
struct LegacyStoreGenerator {
    private var state: UInt64

    init(seed: UInt64) { state = seed &+ 0x9E37_79B9_7F4A_7C15 }

    private mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }

    private mutating func int(_ range: ClosedRange<Int>) -> Int {
        range.lowerBound + Int(next() % UInt64(range.count))
    }

    private mutating func pick<T>(_ values: [T]) -> T { values[int(0...(values.count - 1))] }

    private static let pieces = [
        "Home", "repair", "Квартира", "№5", "™", "ﬁle", "Ｆｕｌｌ", "@", "@home", "  ", "   ", "👍🏽", "👩‍👩‍👧", "é", "e\u{301}",
        "Ⅻ", "x²", "Straße", "STRASSE", "garden", "Garden", "tab\tbed", "No", "½", "ｶﾀｶﾅ", "a", "b",
    ]

    private mutating func text(maxGraphemes: Int) -> String {
        var value = ""
        for _ in 0..<int(1...6) { value += pick(Self.pieces) + pick(["", " ", "  "]) }
        if int(0...20) == 0 { value += String(repeating: pick(["x", "👍🏽", "ü"]), count: int(400...600)) }
        value = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty { value = "x" }
        while value.count > maxGraphemes { value.removeLast() }
        return value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "y" : value.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private mutating func unique(_ existing: [String], maxGraphemes: Int) -> String {
        while true {
            let candidate = text(maxGraphemes: maxGraphemes)
            if !existing.contains(where: { $0.localizedCaseInsensitiveCompare(candidate) == .orderedSame }) { return candidate }
        }
    }

    private func date(_ day: Int, _ minute: Int) -> String {
        let date = Date(timeIntervalSince1970: 1_780_000_000 + Double(day) * 86_400 + Double(minute) * 60)
        return ISO8601DateFormatter().string(from: date)
    }

    /// A store; `tasks` fixes the size (the 2,000-task budget uses ordinary text: short notes, no
    /// giant values, as a real store holds).
    mutating func store(tasks taskCount: Int? = nil, subtasksPerTask: Int? = nil, commentsPerTask: Int? = nil) throws -> Data {
        let ordinary = taskCount != nil
        var projects: [[String: Any]] = []
        var names: [String] = []
        for index in 0..<int(0...5) {
            let name = unique(names, maxGraphemes: 500)
            names.append(name)
            var project: [String: Any] = [
                "id": "project_\(index)", "name": name, "state": int(0...3) == 0 ? "archived" : "active", "revision": 1,
            ]
            if int(0...1) == 0 { project["desiredOutcome"] = text(maxGraphemes: 1_000) }
            projects.append(project)
        }
        var tags: [[String: Any]] = []
        var activeTagNames: [String] = []
        for index in 0..<int(0...4) {
            let deleted = int(0...4) == 0
            let name = deleted ? text(maxGraphemes: 500) : unique(activeTagNames, maxGraphemes: 500)
            if !deleted { activeTagNames.append(name) }
            tags.append(["id": "tag_\(index)", "name": name, "state": deleted ? "deleted" : "active", "revision": 1])
        }
        let states = ["inbox", "next", "waiting", "someday", "completed", "cancelled"]
        var tasks: [[String: Any]] = []
        for index in 0..<(taskCount ?? int(0...14)) {
            let state = pick(states)
            let created = date(index % 40, int(0...600))
            var task: [String: Any] = [
                "id": "task_\(index)", "title": text(maxGraphemes: 500), "state": state, "revision": int(1...5),
                "tagIDs": Array(Set((0..<int(0...2)).compactMap { _ in tags.isEmpty ? nil : pick(tags)["id"] as? String })).sorted(),
                "priority": pick(["none", "low", "medium", "high"]), "orderKey": int(1...50), "createdAt": created,
            ]
            if !projects.isEmpty, int(0...1) == 0 { task["projectID"] = pick(projects)["id"] }
            if int(0...3) == 0 {
                task["details"] = String(repeating: pick(["notes ", "👍🏽", "  "]), count: ordinary ? int(1...60) : int(1...12_000))
            }
            if int(0...3) == 0 { task["dueDate"] = "2026-1\(int(0...2))-1\(int(0...9))" }
            let last = pick(["inbox", "next", "waiting", "someday"])
            if state == "waiting" {
                task["waitingFor"] = text(maxGraphemes: 500)
                task["waitingSince"] = int(0...1) == 0 ? created : date(index % 40 + 1, 0)
            }
            if state == "completed" {
                task["lastOpenState"] = last
                task["completedAt"] = date(index % 40 + 2, 0)
            }
            if state == "cancelled" {
                task["lastOpenState"] = last
                task["cancelledAt"] = date(index % 40 + 2, 0)
            }
            task["subtasks"] = (0..<(subtasksPerTask ?? int(0...3))).map { position in
                [
                    "id": "sub_\(index)_\(position)", "title": text(maxGraphemes: 500),
                    "state": pick(["open", "completed", "cancelled"]), "orderKey": position + 1, "revision": 1,
                ] as [String: Any]
            }
            task["comments"] = (0..<(commentsPerTask ?? int(0...2))).map { position in
                var comment: [String: Any] = [
                    "id": "comment_\(index)_\(position)",
                    "body": !ordinary && int(0...10) == 0 ? String(repeating: "c", count: 20_000) : text(maxGraphemes: 20_000),
                    "actorID": "local", "createdAt": created, "revision": 1,
                ]
                if int(0...2) == 0 { comment["editedAt"] = date(index % 40 + 3, 0) }
                return comment
            }
            tasks.append(task)
        }
        let store: [String: Any] = [
            "version": 1, "generation": int(1...99), "tasks": tasks, "projects": projects, "tags": tags, "idempotency": [:] as [String: Any],
        ]
        return try JSONSerialization.data(withJSONObject: store)
    }
}
