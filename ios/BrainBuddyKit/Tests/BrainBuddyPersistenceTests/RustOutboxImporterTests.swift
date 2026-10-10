import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyPersistence

// The legacy outbox after the import (spec 026, T042). The classification itself, with the golden
// fixture, the 24-hour window, aliases and the old issues, is tested in `bb-client` (`cargo test -p
// bb-client legacy_outbox`); these tests are about the Swift end: the sends to look up come from the
// Rust store, the lookup is a port, a receipt is matched by its key alone, and the typed errors reach
// the caller without payload text.

/// A folder with a legacy `store.json` and a place for the Rust store, imported once.
private struct OutboxLane {
    let directory: URL
    let legacy: URL
    let database: URL

    init() throws {
        directory = try makeTemporaryDirectory()
        legacy = directory.appendingPathComponent("store.json")
        database = directory.appendingPathComponent("rust", isDirectory: true)
            .appendingPathComponent("workspace.sqlite3")
    }

    func imported(_ document: StoreDocument, runtime: RustBridgeRuntime) async throws {
        _ = try await FileDocumentStore(fileURL: legacy).update { $0 = document }
        _ = try await RustStoreImporter(
            runtime: runtime, legacyFileURL: legacy, databaseURL: database, workspaceID: "workspace-local",
            busyTimeoutMilliseconds: 2_000, now: { Fixtures.issuedAt }
        ).run()
    }

    func importer(runtime: RustBridgeRuntime) -> RustOutboxImporter {
        RustOutboxImporter(
            runtime: runtime, databaseURL: database, workspaceID: "workspace-local",
            busyTimeoutMilliseconds: 2_000, now: { Fixtures.issuedAt })
    }
}

/// A send a request was made for, first sent four days before the import.
private func sentOperation() -> PendingOperation {
    PendingOperation(
        command: .createTask(.init(taskID: TaskID("task-9"), title: "Sent twice", list: .inbox)),
        issuedAt: Fixtures.createdAt, attempts: 2, firstAttemptAt: Fixtures.createdAt,
        lastAttemptAt: Fixtures.issuedAt, lastError: "timeout", everSent: true)
}

/// Records what was asked, and answers `answer` for every key.
private struct RecordingLookup: LegacyReceiptLookup {
    let asked: Asked
    let reply: RustLegacyAnswer

    func answer(for send: RustLegacySend) async -> RustLegacyAnswer {
        await asked.record(send)
        return reply
    }
}

private actor Asked {
    private(set) var sends: [RustLegacySend] = []

    func record(_ send: RustLegacySend) { sends.append(send) }
}

@Suite("Rust legacy outbox (026-FR-003, 026-FR-005, 026-FR-010, 026-FR-013, 026-SC-002, 026-SC-005)")
struct RustOutboxImporterTests {
    @Test("026-FR-013: never-sent intents are not looked up, are not rebuilt and never look synchronized")
    func neverSentIntentsStayPending() async throws {
        let lane = try OutboxLane()
        defer { removeTemporaryDirectory(lane.directory) }
        let runtime = try RustBridgeRuntime()
        try await lane.imported(
            StoreDocument(outbox: [Fixtures.operation(0), Fixtures.operation(1)]), runtime: runtime)
        let asked = Asked()

        let status = try await lane.importer(runtime: runtime).run(
            lookup: RecordingLookup(asked: asked, reply: .unproven))

        #expect(await asked.sends.isEmpty)
        #expect(status.carried == 2)
        #expect(status.unsent == 2)
        #expect(status.classified)
        #expect(!status.mayRun)
        #expect(!status.fullySynced)
    }

    @Test("026-FR-005: a receipt for the send's own key settles it and proves the alias")
    func aReceiptSettlesTheSend() async throws {
        let lane = try OutboxLane()
        defer { removeTemporaryDirectory(lane.directory) }
        let runtime = try RustBridgeRuntime()
        let operation = sentOperation()
        try await lane.imported(StoreDocument(outbox: [operation]), runtime: runtime)
        let asked = Asked()
        let proof = RustLegacyAnswer.accepted(aliases: [
            RustLegacyAlias(entityType: "task", oldLocalID: "task-9", serverID: "task_0123456789ab")
        ])

        let status = try await lane.importer(runtime: runtime).run(
            lookup: RecordingLookup(asked: asked, reply: proof))

        let sends = await asked.sends
        #expect(sends.count == 1)
        #expect(sends.first?.idempotencyKey.lowercased() == operation.idempotencyKey.uuidString.lowercased())
        #expect(status.accepted == 1)
        #expect(status.aliases == 1)
        #expect(status.openIssues == 0)
        #expect(status.fullySynced)
        // The verdict is final: the next run asks nothing.
        let next = Asked()
        let again = try await lane.importer(runtime: runtime).run(lookup: RecordingLookup(asked: next, reply: .unproven))
        #expect(await next.sends.isEmpty)
        #expect(again == status)
    }

    @Test("026-FR-010: a send without proof is kept as an issue and is never reissued")
    func anUnprovenSendStaysAnIssue() async throws {
        let lane = try OutboxLane()
        defer { removeTemporaryDirectory(lane.directory) }
        let runtime = try RustBridgeRuntime()
        try await lane.imported(StoreDocument(outbox: [sentOperation()]), runtime: runtime)

        let status = try await lane.importer(runtime: runtime).run()

        #expect(status.uncertain == 1)
        #expect(status.openIssues == 1)
        #expect(status.mayRun)
        #expect(!status.fullySynced)
    }

    @Test("026-FR-013: the old file's own issues are carried over as open issues")
    func oldIssuesBecomeIssues() async throws {
        let lane = try OutboxLane()
        defer { removeTemporaryDirectory(lane.directory) }
        let runtime = try RustBridgeRuntime()
        try await lane.imported(Fixtures.richDocument(), runtime: runtime)

        let status = try await lane.importer(runtime: runtime).run()

        // The rich document has one never-sent entry, one sent entry and one old issue.
        #expect(status.carried == 2)
        #expect(status.unsent == 1)
        #expect(status.uncertain == 1)
        #expect(status.carriedIssues == 1)
        #expect(status.convertedIssues == 1)
        #expect(status.openIssues == 2)
        #expect(!status.mayRun)
    }

    @Test("026-FR-013: nothing is classified before the import")
    func requiresTheImport() async throws {
        let lane = try OutboxLane()
        defer { removeTemporaryDirectory(lane.directory) }
        let runtime = try RustBridgeRuntime()
        var thrown: RustOutboxImportError?
        do {
            _ = try await lane.importer(runtime: runtime).run()
        } catch {
            thrown = error as? RustOutboxImportError
        }
        #expect(thrown == .notImported)
    }

    @Test("026-FR-026: a cancelled task gets CANCELLED and nothing is classified")
    func cancellation() async throws {
        let lane = try OutboxLane()
        defer { removeTemporaryDirectory(lane.directory) }
        let runtime = try RustBridgeRuntime()
        try await lane.imported(StoreDocument(outbox: [sentOperation()]), runtime: runtime)
        let importer = lane.importer(runtime: runtime)
        let (gate, release) = AsyncStream<Void>.makeStream()
        let task = Task { () -> RustOutboxImportError? in
            // Cancelling a task ends its iteration, so the call below always starts cancelled.
            for await _ in gate { break }
            do {
                _ = try await importer.run()
                return nil
            } catch {
                return error as? RustOutboxImportError
            }
        }
        task.cancel()
        release.yield()
        release.finish()

        #expect(await task.value == .failed(.cancelled))
        #expect(try await importer.run().uncertain == 1)
    }

    @Test("026-SC-005: the bridge error codes map onto typed outbox errors")
    func errorMapping() {
        let cases: [(String, String?, RustOutboxImportError)] = [
            ("LEGACY_OUTBOX_NOT_IMPORTED", nil, .notImported),
            ("LEGACY_OUTBOX_UNREADABLE", "outbox", .unreadable(field: "outbox")),
            ("STORE_BUSY", nil, .storeBusy),
            ("STORE_FULL", nil, .storeFull),
            ("STORE_CORRUPT", nil, .storeCorrupt),
            ("STORE_UPGRADE_REQUIRED", nil, .storeNewer),
            ("INTERNAL_ERROR", nil, .failed(RustBridgeError(code: "INTERNAL_ERROR"))),
        ]
        for (code, field, expected) in cases {
            #expect(RustOutboxImportError(RustBridgeError(code: code, field: field)) == expected)
        }
        #expect(RustOutboxImportError.storeBusy.isRetryable)
        #expect(!RustOutboxImportError.storeFull.isRetryable)
        #expect(!RustOutboxImportError.notImported.isRetryable)
    }
}
