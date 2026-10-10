import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

@Suite("Canonical Rust query cache fences (026-FR-025, 026-FR-026)")
struct RustWorkspaceTests {
    private let query = Data("{\"kind\":\"list_counts\"}".utf8)

    @Test("026-FR-025: malformed canonical answers report a query error instead of publishing or retrying forever")
    @MainActor
    func malformedAnswer() async {
        let controlled = ControlledRustQuery()
        var published = false
        let cache = RustWorkspaceAdapter(inputs: Data()) { query, inputs, cursor in
            try await controlled.answer(query, inputs: inputs, cursor: cursor)
        } didPublish: { _, _ in published = true }
        let prepared = Task { await cache.prepare(query) }
        await controlled.waitForCalls(1)
        await controlled.complete(0, generation: "invalid")
        await prepared.value
        #expect(!published)
        #expect(cache.readiness(for: query) == .failed("MALFORMED_QUERY_RESULT"))
        #expect(await controlled.callCount() == 1)
    }

    @Test("026-FR-025: a canonical decoding failure remains distinct from an empty ready page")
    @MainActor
    func decodingFailure() async {
        let controlled = ControlledRustQuery()
        let cache = RustWorkspaceAdapter(inputs: Data()) { query, inputs, cursor in
            try await controlled.answer(query, inputs: inputs, cursor: cursor)
        } didPublish: { _, _ in throw RustDomainError.malformedResult }
        let prepared = Task { await cache.prepare(query) }
        await controlled.waitForCalls(1)
        await controlled.complete(0, generation: "1")
        await prepared.value
        #expect(cache.page(for: query) == nil)
        #expect(cache.readiness(for: query) == .failed("MALFORMED_QUERY_RESULT"))
    }

    @Test("026-FR-025: only the requested visible page crosses the bridge, with explicit navigation")
    @MainActor
    func onDemandPages() async {
        let controlled = ControlledRustQuery()
        let cache = RustWorkspaceAdapter(inputs: Data()) { query, inputs, cursor in
            try await controlled.answer(query, inputs: inputs, cursor: cursor)
        } didPublish: { _, _ in }
        let first = Task { await cache.prepare(query) }
        await controlled.waitForCalls(1)
        await controlled.complete(0, generation: "1", nextCursor: "page-two")
        await first.value
        #expect(await controlled.callCount() == 1)
        #expect(cache.page(for: query)?.collectionNextCursor == "page-two")
        let next = Task { await cache.nextPage(query) }
        await controlled.waitForCalls(2)
        #expect(await controlled.lastCursor() == "page-two")
        #expect(cache.page(for: query) == nil)
        await controlled.complete(1, generation: "1")
        await next.value
        #expect(await controlled.callCount() == 2)
        let back = Task { await cache.previousPage(query) }
        await controlled.waitForCalls(3)
        #expect(await controlled.lastCursor() == nil)
        await controlled.complete(2, generation: "1", nextCursor: "page-two")
        await back.value
        #expect(cache.entries.count == 1)
    }

    @Test("026-FR-001: a recovered prepared gesture reuses the committed receipt before any fresh ID can be minted")
    @MainActor
    func committedDraftRecovery() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let date = Date(timeIntervalSince1970: 1_790_000_000)
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let command = try facade.workspaceCommand(.createTask(.init(taskID: TaskID(UUID().uuidString.lowercased()),
            title: "Recovered draft", list: .inbox)), commandID: UUID(), at: date, in: .empty)
        let context = RustWorkspaceContext(now: date, timeZone: "UTC", actorID: "device",
            policy: Data("{\"weekly_review\":false,\"navigator_provider\":null,\"navigator_available\":false,\"consent_text_version\":1}".utf8))
        let intent = Data("authored draft".utf8)
        let prepared = RustWorkspaceGesture(authoredIntent: intent, commands: [command], context: context)
        try await runtime.saveDraft(RustWorkspaceDraft(draftID: "runtime:prepared:window", editorKind: "runtime_gesture",
            recordType: nil, recordKey: nil, baseRevision: nil,
            fields: try StoreDocumentCoding.makeEncoder().encode(prepared), updatedAt: "2026-10-10T09:00:00Z"))
        guard case .saved = try await runtime.execute([command], context: context) else {
            Issue.record("the first execution must commit"); return
        }
        // A new controller represents a relaunch after commit, before cleanup.
        let saver = RustWorkspaceGestureSaver(runtime: runtime)
        var minted = false
        let recovered = try await saver.save(editorID: "window", authoredIntent: intent) {
            minted = true
            return prepared
        }
        guard case .saved(let gesture) = recovered else { Issue.record("known success must survive recovery"); return }
        #expect(!minted)
        #expect(gesture.receipts.first?.commandID == command.commandID)
        #expect(gesture.receipts.first?.replayed == true)
        #expect(gesture.commands == [command])
        #expect(try await runtime.snapshot().pending == "1")
        #expect(try await runtime.loadDraft("runtime:prepared:window") == nil)
        try await runtime.close()
    }

    @Test("026-FR-025: an invalidation during a read survives completion and never publishes the old generation")
    @MainActor
    func invalidationDuringRead() async {
        let controlled = ControlledRustQuery()
        var published: [String] = []
        let cache = RustWorkspaceAdapter(inputs: Data()) { query, inputs, cursor in
            try await controlled.answer(query, inputs: inputs, cursor: cursor)
        } didPublish: { _, page in published.append(page.projectionGeneration) }
        let prepared = Task { await cache.prepare(query) }
        await controlled.waitForCalls(1)
        #expect(cache.readiness(for: query) == .loading)
        cache.invalidate(generation: 2)
        await controlled.complete(0, generation: "1")
        await controlled.waitForCalls(2)
        #expect(published.isEmpty)
        #expect(cache.page(for: query) == nil)
        await controlled.complete(1, generation: "2")
        await prepared.value
        #expect(published == ["2"])
        #expect(cache.readiness(for: query) == .ready)
    }

    @Test("026-FR-026: closing the binding fences a result still in flight")
    @MainActor
    func closeDuringRead() async {
        let controlled = ControlledRustQuery()
        var published = false
        let cache = RustWorkspaceAdapter(inputs: Data()) { query, inputs, cursor in
            try await controlled.answer(query, inputs: inputs, cursor: cursor)
        } didPublish: { _, _ in published = true }
        let prepared = Task { await cache.prepare(query) }
        await controlled.waitForCalls(1)
        cache.close()
        await controlled.complete(0, generation: "1")
        await prepared.value
        #expect(!published)
        #expect(cache.readiness(for: query) == .notRequested)
    }
}

private actor ControlledRustQuery {
    private var calls: [CheckedContinuation<RustWorkspaceAnswer, any Error>] = []
    private var waiters: [(Int, CheckedContinuation<Void, Never>)] = []
    private var cursors: [String?] = []

    func answer(_ query: Data, inputs: Data, cursor: String?) async throws -> RustWorkspaceAnswer {
        try await withCheckedThrowingContinuation { continuation in
            calls.append(continuation)
            cursors.append(cursor)
            let ready = waiters.filter { $0.0 <= calls.count }
            waiters.removeAll { $0.0 <= calls.count }
            for (_, waiter) in ready { waiter.resume() }
        }
    }

    func waitForCalls(_ count: Int) async {
        if calls.count >= count { return }
        await withCheckedContinuation { waiters.append((count, $0)) }
    }

    func callCount() -> Int { calls.count }
    func lastCursor() -> String? { cursors.last ?? nil }

    func complete(_ index: Int, generation: String, nextCursor: String? = nil) {
        calls[index].resume(returning: .answered(RustWorkspacePage(projectionGeneration: generation,
            result: Data("{\"kind\":\"list_counts\",\"value\":{}}".utf8), collectionNextCursor: nextCursor)))
    }
}


extension RustWorkspaceTests {
    @Test("026-FR-026: an old tokenless interactive draft cannot execute an unknown suffix or mint replacement IDs")
    @MainActor
    func tokenlessInteractiveUnknownPreservesDraft() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let instant = Date(timeIntervalSince1970: 1_790_000_000)
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let command = try facade.workspaceCommand(.decideTask(.init(decisionID: .make(UUID()), taskID: TaskID("task_unknown"), type: .keepWaiting)),
            commandID: UUID(), at: instant, in: .empty)
        let context = RustWorkspaceContext(now: instant, timeZone: "UTC", actorID: "device",
            policy: Data(#"{"weekly_review":true,"navigator_provider":null,"navigator_available":false,"consent_text_version":1}"#.utf8))
        let original = RustWorkspaceGesture(authoredIntent: Data("preserved authored input".utf8), commands: [command], context: context)
        var fields = try #require(JSONSerialization.jsonObject(with: StoreDocumentCoding.makeEncoder().encode(original)) as? [String: Any])
        var oldCommands = try #require(fields["commands"] as? [[String: Any]])
        oldCommands[0].removeValue(forKey: "admissionTokens")
        fields["commands"] = oldCommands
        let bytes = try JSONSerialization.data(withJSONObject: fields, options: [.sortedKeys])
        try await runtime.saveDraft(RustWorkspaceDraft(draftID: "runtime:prepared:scene:old", editorKind: "runtime_gesture",
            recordType: nil, recordKey: nil, baseRevision: nil, fields: bytes, updatedAt: "2026-10-10T09:00:00Z"))
        var prepared = false
        do {
            _ = try await RustWorkspaceGestureSaver(runtime: runtime).save(editorID: "scene:old", authoredIntent: original.authoredIntent) {
                prepared = true
                return original
            }
            Issue.record("unknown original interactive completion requires a reload")
        } catch { #expect((error as? RustBridgeError)?.code == "SHOWN_FRAME_RELOAD_REQUIRED") }
        #expect(!prepared)
        #expect(try await runtime.loadDraft("runtime:prepared:scene:old")?.fields == bytes)
        #expect(try await runtime.snapshot().pending == "0")
        try await runtime.close()
    }
}
