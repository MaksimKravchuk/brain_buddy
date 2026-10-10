import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyPersistence

// The legacy `StoreDocument` file becomes a verified Rust store, or nothing changes (spec 026,
// T041). The import itself, with the frozen golden fixture, the Mac awkward/corrupt/newer
// fixtures, the crash and full-disk cases, is tested in `bb-client` (`cargo test -p bb-client
// import`); these tests are about the Swift end: the file store's own decoder judges the file
// first, its counts are cross-checked by the core, the bridge's typed errors reach the caller
// without payload text, and no failure touches the legacy file.

/// A folder with a legacy `store.json` and a place for the Rust store.
private struct LegacyLane {
    let directory: URL
    let legacy: URL
    let database: URL

    init() throws {
        directory = try makeTemporaryDirectory()
        legacy = directory.appendingPathComponent("store.json")
        database = directory.appendingPathComponent("rust", isDirectory: true)
            .appendingPathComponent("workspace.sqlite3")
    }

    func importer(
        runtime: RustBridgeRuntime, now: @escaping @Sendable () -> Date = { Fixtures.issuedAt }
    ) -> RustStoreImporter {
        RustStoreImporter(
            runtime: runtime, legacyFileURL: legacy, databaseURL: database, workspaceID: "workspace-local",
            busyTimeoutMilliseconds: 2_000, now: now)
    }

    func write(_ document: StoreDocument) async throws {
        _ = try await FileDocumentStore(fileURL: legacy).update { $0 = document }
    }

    func names() throws -> [String] {
        try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted()
    }

    func backups() throws -> [String] {
        try names().filter { $0.contains(".pre-rust-") }
    }
}

/// The error a run throws, or nil when it did not throw a `RustStoreImportError`.
private func importFailure(of body: () async throws -> Void) async -> RustStoreImportError? {
    do {
        try await body()
        return nil
    } catch {
        return error as? RustStoreImportError
    }
}

@Suite("Rust store import (026-FR-010, 026-FR-013, 026-FR-022, 026-FR-025, 026-SC-005)")
struct RustStoreImporterTests {
    @Test("026-FR-013: a populated document is imported, backed up and counted as the kit's decoder counts it")
    func importsAPopulatedDocument() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        try await workspace.write(Fixtures.richDocument())
        let before = try Data(contentsOf: workspace.legacy)

        let report = try await workspace.importer(runtime: runtime).run()

        #expect(!report.alreadyActive)
        #expect(report.sourceVersion == Int64(StoreDocument.currentVersion))
        #expect(report.sourceGeneration == 1)
        #expect(report.sourceBytes == UInt64(before.count))
        #expect(report.sourceSHA256.count == 64)
        #expect(report.counts.tasks == 1)
        #expect(report.counts.subtasks == 1)
        #expect(report.counts.comments == 1)
        #expect(report.counts.projects == 1)
        #expect(report.counts.tags == 1)
        #expect(report.counts.outboxEntries == 2)
        #expect(report.counts.issues == 1)
        // The Swift reader and the core's reader counted the same bytes the same way.
        let decoded = try StoreDocumentCoding.decode(before)
        #expect(report.counts == RustImportCounts(counting: decoded))
        // The task, its project and its subtask carry a server ID the file proved; the comment and the
        // tag do not.
        #expect(report.aliases == 2)
        #expect(report.localTaskFacts == 1)

        // The legacy file is as it was, and its backup is the same bytes.
        #expect(try Data(contentsOf: workspace.legacy) == before)
        #expect(try Data(contentsOf: workspace.directory.appendingPathComponent(report.backupFile)) == before)
        #expect(try workspace.backups() == [report.backupFile, report.manifestFile].sorted())
        #expect(FileManager.default.fileExists(atPath: workspace.database.path))
    }

    @Test("026-FR-010: importing the same file again does nothing")
    func importingTwiceIsIdempotent() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        try await workspace.write(Fixtures.richDocument())

        let first = try await workspace.importer(runtime: runtime).run()
        let second = try await workspace.importer(runtime: runtime).run()

        #expect(!first.alreadyActive)
        #expect(second.alreadyActive)
        #expect(second.sourceSHA256 == first.sourceSHA256)
        #expect(second.counts == first.counts)
        #expect(try workspace.backups().count == 2)
    }

    @Test("026-FR-013: a different file after an import is refused and never merged")
    func aLaterFileIsNeverMerged() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        try await workspace.write(Fixtures.richDocument())
        _ = try await workspace.importer(runtime: runtime).run()

        // An older copy of the app wrote to the file afterwards.
        try await workspace.write(
            StoreDocument(base: .empty, outbox: [Fixtures.operation(7)], issues: [], account: nil))
        let later = try Data(contentsOf: workspace.legacy)

        let failure = await importFailure { _ = try await workspace.importer(runtime: runtime).run() }
        #expect(failure == .alreadyImportedOther)
        #expect(try Data(contentsOf: workspace.legacy) == later)
    }

    @Test("026-FR-022: a damaged file is reported as unreadable, left untouched and nothing is created")
    func aDamagedFileFailsBeforeAnything() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        let damaged = Data(#"{"version": 2, "generation": 3, "base": {"tasks": {"#.utf8)
        try damaged.write(to: workspace.legacy)

        let failure = await importFailure { _ = try await workspace.importer(runtime: runtime).run() }

        #expect(failure == .sourceUnreadable)
        #expect(try Data(contentsOf: workspace.legacy) == damaged)
        #expect(try workspace.names() == ["store.json"])
    }

    @Test("026-FR-022: a file a newer app wrote is reported with its version and left untouched")
    func aNewerFileFailsBeforeAnything() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        let newer = Data(#"{"version": 9, "generation": 1, "future": {"tasks": []}}"#.utf8)
        try newer.write(to: workspace.legacy)

        let failure = await importFailure { _ = try await workspace.importer(runtime: runtime).run() }

        #expect(failure == .sourceNewer(version: 9))
        #expect(try Data(contentsOf: workspace.legacy) == newer)
        #expect(try workspace.names() == ["store.json"])
    }

    @Test("026-FR-022: a missing file is reported and nothing is created")
    func aMissingFileIsReported() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()

        let failure = await importFailure { _ = try await workspace.importer(runtime: runtime).run() }

        #expect(failure == .sourceMissing)
        #expect(try workspace.names().isEmpty)
    }

    @Test("026-FR-022: failures carry a code and a static name, never the user's text")
    func failuresCarryNoUserText() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        var document = Fixtures.richDocument()
        document.base.tasks[TaskID("task-1")]?.projectID = "project-that-does-not-exist"
        document.base.tasks[TaskID("task-1")]?.title = "Call the plumber about the secret door"
        try await workspace.write(document)

        let failure = try #require(
            await importFailure { _ = try await workspace.importer(runtime: runtime).run() })

        #expect(failure == .sourceInconsistent(field: "task_project"))
        #expect(!failure.isRetryable)
        let rendered = "\(failure) \(String(reflecting: failure))"
        #expect(!rendered.contains("plumber"))
        #expect(!rendered.contains("secret"))
        #expect(try workspace.backups().isEmpty)
        #expect(!FileManager.default.fileExists(atPath: workspace.database.path))
    }

    @Test("026-SC-005: a writer holding the document lock makes the import wait, then report storeBusy")
    func aWriterHoldingTheDocumentLockBlocksTheImport() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        try await workspace.write(Fixtures.richDocument())
        let before = try Data(contentsOf: workspace.legacy)
        let importer = RustStoreImporter(
            runtime: runtime, legacyFileURL: workspace.legacy, databaseURL: workspace.database,
            workspaceID: "workspace-local", busyTimeoutMilliseconds: 150)

        // What `FileDocumentStore.update` holds while it reads, transforms and replaces the file.
        let held = try DocumentFile(url: workspace.legacy).lock()
        let failure = await importFailure { _ = try await importer.run() }
        held.release()

        #expect(failure == .storeBusy)
        #expect(failure?.isRetryable == true)
        #expect(try Data(contentsOf: workspace.legacy) == before)
        #expect(try workspace.backups().isEmpty)
        #expect(!FileManager.default.fileExists(atPath: workspace.database.path))
        // The writer is done: the same importer now imports.
        #expect(try await importer.run().alreadyActive == false)
    }

    @Test("026-FR-026: a cancelled task gets CANCELLED and nothing is imported")
    func cancellation() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        try await workspace.write(Fixtures.richDocument())
        let importer = workspace.importer(runtime: runtime)
        let (gate, release) = AsyncStream<Void>.makeStream()
        let task = Task { () -> RustStoreImportError? in
            // Cancelling a task ends its iteration, so the call below always starts cancelled.
            for await _ in gate { break }
            return await importFailure { _ = try await importer.run() }
        }
        task.cancel()
        release.yield()
        release.finish()

        let failure = await task.value

        #expect(failure == .failed(.cancelled))
        #expect(try workspace.backups().isEmpty)
        #expect(!FileManager.default.fileExists(atPath: workspace.database.path))
        // The same importer imports when it is not cancelled.
        #expect(try await importer.run().alreadyActive == false)
    }

    @Test("026-FR-025: a closed runtime reports WORKSPACE_CLOSED and imports nothing")
    func closedRuntime() async throws {
        let workspace = try LegacyLane()
        defer { removeTemporaryDirectory(workspace.directory) }
        let runtime = try RustBridgeRuntime()
        try await workspace.write(Fixtures.richDocument())
        runtime.close()

        let failure = await importFailure { _ = try await workspace.importer(runtime: runtime).run() }

        #expect(failure == .failed(RustBridgeError(code: "WORKSPACE_CLOSED")))
        #expect(try workspace.backups().isEmpty)
    }

    @Test("026-SC-005: the bridge error codes map onto typed import errors")
    func errorMapping() {
        let cases: [(String, String?, RustStoreImportError)] = [
            ("IMPORT_SOURCE_MISSING", nil, .sourceMissing),
            ("IMPORT_SOURCE_UNREADABLE", "json", .sourceUnreadable),
            ("IMPORT_SOURCE_UNSUPPORTED", "task", .sourceNotCarried(field: "task")),
            ("IMPORT_SOURCE_INCONSISTENT", "task_tag", .sourceInconsistent(field: "task_tag")),
            ("IMPORT_SOURCE_CHANGED", nil, .sourceChanged),
            ("IMPORT_TARGET_IN_USE", nil, .storeInUse),
            ("IMPORT_ALREADY_IMPORTED", nil, .alreadyImportedOther),
            ("IMPORT_VERIFICATION_FAILED", "records", .verificationFailed(check: "records")),
            ("STORE_BUSY", nil, .storeBusy),
            ("STORE_FULL", nil, .storeFull),
            ("STORE_CORRUPT", nil, .storeCorrupt),
            ("STORE_UPGRADE_REQUIRED", nil, .storeNewer),
            ("INTERNAL_ERROR", nil, .failed(RustBridgeError(code: "INTERNAL_ERROR"))),
        ]
        for (code, field, expected) in cases {
            #expect(RustStoreImportError(RustBridgeError(code: code, field: field)) == expected)
        }
        // Only a busy store and a file that changed under the import are worth running again as is.
        #expect(RustStoreImportError.storeBusy.isRetryable)
        #expect(RustStoreImportError.sourceChanged.isRetryable)
        #expect(!RustStoreImportError.storeFull.isRetryable)
        #expect(!RustStoreImportError.sourceUnreadable.isRetryable)
    }
}
