import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

@MainActor
@Suite("Selected Review Workspace journeys (026-FR-001, 026-FR-025, 026-FR-026)")
struct RustWorkspaceReviewJourneyTests {
    private func workspace(at directory: URL, clock: TestClock, reviewEnabled: Bool = true) async throws
        -> (Workspace, RustWorkspaceRuntime, ControlledStore) {
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let retired = ControlledStore()
        let workspace = Workspace(store: retired, sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")), reviewEnabled: reviewEnabled,
                startup: .freshAccountless),
            now: { clock.now })
        workspace.deviceTimeZone = { TimeZone(secondsFromGMT: 0)! }
        await workspace.load()
        return (workspace, runtime, retired)
    }

    @Test("Review decisions clear drafts only after durable success and preserve them on canonical refusal")
    func decisionsPreserveDrafts() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let clock = TestClock()
        let (workspace, runtime, retired) = try await workspace(at: directory, clock: clock)
        try await workspace.acknowledgeExplainer(editorID: "scene:review:explainer")
        let task = try await workspace.capture(CaptureDraft(text: "Call the plumber", list: .next), editorID: "scene:review:capture")
        await workspace.prepareList(.list(.next))
        let record = try #require(workspace.task(task))
        let key = DraftKey.decisionForm(.waitingFor, task: task, formulation: record.formulation?.id)
        try await workspace.saveDraft("Waiting for the quote", for: key, editorID: "scene:review:form")
        do {
            _ = try await workspace.decide(.waiting, on: task, waitingFor: "", formulationID: record.formulation?.id,
                expectedTask: workspace.shownTask(of: record), editorID: "scene:review:decision")
            Issue.record("The owning runtime must refuse the missing waiting note")
        } catch {
            #expect(Workspace.saveMessage(for: error) == GTDValidationError.waitingForRequired.message)
        }
        #expect(try await workspace.draft(for: key, editorID: "scene:review:form") == "Waiting for the quote")
        let decision = try await workspace.decide(.waiting, on: task, waitingFor: "Waiting for the quote",
            formulationID: record.formulation?.id, expectedTask: workspace.shownTask(of: record), editorID: "scene:review:decision")
        #expect(!decision.rawValue.isEmpty)
        #expect(try await workspace.draft(for: key, editorID: "scene:review:form") == nil)
        await workspace.prepareList(.list(.waiting))
        #expect(workspace.task(task)?.state == .waiting)
        #expect(await retired.loadCount == 0)
        #expect(await retired.written.isEmpty)
        #expect(workspace.fullReplayCount == 0)
        #expect(try await runtime.loadDraft("runtime:prepared:scene:review:decision") == nil)
        #expect(try await runtime.snapshot().pending == "0")
        await workspace.closeRuntime()

        // Reopening must read durable local authority and private beforeimages;
        // the previous controller's Swift state has been released.
        clock.advance(by: 60)
        let (reopened, reopenedRuntime, reopenedRetired) = try await self.workspace(at: directory, clock: clock)
        await reopened.prepareList(.list(.waiting))
        try await reopened.undoDecision(decision, editorID: "scene:review:undo")
        await reopened.prepareList(.list(.next))
        #expect(reopened.task(task)?.state == .next)
        #expect(reopened.task(task)?.title == "Call the plumber")
        #expect(try await reopenedRuntime.snapshot().pending == "0")
        #expect(await reopenedRetired.loadCount == 0)
        #expect(await reopenedRetired.written.isEmpty)
        await reopened.closeRuntime()
    }

    @Test("Hidden Review upkeep expires original Undo evidence without changing the completed public task")
    func hiddenUpkeepPreservesCompletedEffects() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let clock = TestClock()
        let (workspace, runtime, _) = try await workspace(at: directory, clock: clock)
        try await workspace.acknowledgeExplainer(editorID: "scene:expiry:explainer")
        let task = try await workspace.capture(CaptureDraft(text: "Original local task", list: .next), editorID: "scene:expiry:capture")
        await workspace.prepareList(.list(.next))
        let record = try #require(workspace.task(task))
        let decision = try await workspace.decide(.waiting, on: task, waitingFor: "Original waiting note",
            formulationID: record.formulation?.id, expectedTask: workspace.shownTask(of: record), editorID: "scene:expiry:decision")
        let generation = try await runtime.snapshot().projectionGeneration
        await workspace.closeRuntime()
        clock.advance(by: ReviewRetention.snapshotWindow + 1)
        let (hidden, hiddenRuntime, retired) = try await self.workspace(at: directory, clock: clock, reviewEnabled: false)
        #expect(hidden.isRustBound)
        #expect(!hidden.reviewExposed)
        #expect(try await hiddenRuntime.snapshot().projectionGeneration == generation)
        await hidden.prepareList(.list(.waiting))
        #expect(hidden.task(task)?.state == .waiting)
        #expect(hidden.task(task)?.waitingFor == "Original waiting note")
        do {
            try await hidden.undoDecision(decision, editorID: "scene:expiry:undo")
            Issue.record("The original seven-day deadline must survive relaunch and hidden upkeep")
        } catch { #expect(Workspace.saveMessage(for: error) == GTDValidationError.undoUnavailable.message) }
        #expect(try await hiddenRuntime.snapshot().pending == "0")
        #expect(await retired.loadCount == 0)
        #expect(await retired.written.isEmpty)
        await hidden.closeRuntime()
    }

    @Test("The importer factory preserves original local Undo and settings before converting never-sent intents")
    func importedAccountlessBootstrap() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let clock = TestClock()
        let legacy = await loadedWorkspace(clock: clock)
        legacy.accountlessReviewEnabled = true
        legacy.deviceTimeZone = { TimeZone(secondsFromGMT: 0)! }
        try legacy.acknowledgeExplainer()
        let task = try legacy.capture(CaptureDraft(text: "Imported local task", list: .next))
        clock.advance(by: 1)
        try legacy.updateReviewSettings(ReviewSettingsChange(thresholdDays: 30))
        let originalSettings = legacy.state.review.settings
        let before = try #require(legacy.task(task))
        let session = try legacy.startReview(mode: .quick, entry: .list)
        let decision = try legacy.decide(.waiting, on: task, waitingFor: "Original private evidence", sessionID: session)
        let extraTask = TaskID("00000000-0000-4000-8000-000000000073")
        let source = StoreDocument(base: legacy.state, outbox: [
            PendingOperation(command: .createTask(.init(taskID: extraTask, title: "Never sent capture", list: .inbox)),
                issuedAt: clock.now, idempotencyKey: UUID(uuidString: "A0000000-0000-4000-8000-000000000001")!),
            PendingOperation(command: .updateTask(.init(taskID: extraTask, changes: TaskChanges(title: .set("Never sent edited")))),
                issuedAt: clock.now, idempotencyKey: UUID(uuidString: "B0000000-0000-4000-8000-000000000002")!)
        ], local: legacy.localReview)
        let json = directory.appendingPathComponent("store.json")
        try StoreDocumentCoding.makeEncoder().encode(source).write(to: json)
        let originalBytes = try Data(contentsOf: json)
        let bridge = try RustBridgeRuntime()
        let facade = RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC"))
        let importer = RustStoreImporter(runtime: bridge, legacyFileURL: json,
            databaseURL: directory.appendingPathComponent("store.sqlite3"), workspaceID: "local", now: { clock.now })
        let selection = try await RustWorkspaceSelection.importAccountless(using: importer, facade: facade, reviewEnabled: true)
        let retired = ControlledStore()
        let workspace = Workspace(store: retired, sync: nil, rust: selection, now: { clock.now })
        workspace.deviceTimeZone = { TimeZone(secondsFromGMT: 0)! }
        await workspace.load()
        #expect(workspace.isRustBound)
        try await workspace.prepareReviewRead(.state)
        #expect(workspace.state.review.settings.thresholdDays == originalSettings.thresholdDays)
        #expect(workspace.state.review.openSession?.id != nil)
        await workspace.prepareList(.list(.inbox))
        #expect(workspace.list(.list(.inbox)).sections.flatMap(\.tasks).map(\.title) == ["Never sent edited"])
        try await workspace.undoDecision(decision, editorID: "scene:import:undo")
        await workspace.prepareList(.list(.next))
        await workspace.refreshTaskDetails(task)
        let restored = try #require(workspace.task(task))
        #expect(restored.state == .next)
        #expect(restored.formulation?.startedAt == before.formulation?.startedAt)
        #expect(try await selection.runtime.snapshot().pending == "0")
        #expect(try Data(contentsOf: json) == originalBytes)
        #expect(await retired.loadCount == 0)
        #expect(await retired.written.isEmpty)
        await workspace.closeRuntime()

        // Completed source manifests permit an importer retry after native
        // public versions have advanced, without repinning the edited task.
        let retried = try await RustWorkspaceSelection.importAccountless(using: importer, facade: facade, reviewEnabled: true)
        let reopened = Workspace(store: ControlledStore(), sync: nil, rust: retried, now: { clock.now })
        await reopened.load()
        await reopened.prepareList(.list(.next))
        await reopened.refreshTaskDetails(task)
        #expect(reopened.task(task)?.state == .next)
        #expect(try await retried.runtime.snapshot().pending == "0")
        await reopened.closeRuntime()
    }

    @Test("Selected Review reads use canonical queues and expose readiness; legacy upkeep never writes the document")
    func canonicalReadsAndRetiredUpkeep() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let clock = TestClock()
        let (workspace, _, retired) = try await workspace(at: directory, clock: clock)
        try await workspace.acknowledgeExplainer(editorID: "scene:review:explainer")
        let session = try await workspace.startReview(mode: .quick, entry: .list, editorID: "scene:review:start")
        try await workspace.prepareReviewRead(.state)
        #expect(workspace.reviewReadiness(.state) == .ready)
        #expect(workspace.state.review.openSession?.id == session)
        try await workspace.prepareReviewRead(.queue(.decisions, session))
        #expect(workspace.reviewReadiness(.queue(.decisions, session)) == .ready)
        try await workspace.prepareReviewRead(.summary(session))
        let open = try #require(workspace.state.review.openSession)
        #expect(workspace.decisionStep(in: open) == .nothingAsks)
        workspace.runReviewUpkeep()
        workspace.runLocalReviewMaintenance()
        #expect(workspace.applyDueAutoParks() == 0)
        #expect(workspace.pendingEdits.isEmpty)
        let syncStart: (ReviewMode, ReviewEntry, [ReviewStep]) throws(GTDValidationError) -> ReviewSessionID = {
            try workspace.startReview(mode: $0, entry: $1, skipping: $2)
        }
        #expect(throws: GTDValidationError.asynchronousSaveRequired) { try syncStart(.quick, .list, []) }
        #expect(await retired.loadCount == 0)
        #expect(await retired.written.isEmpty)
        await workspace.closeRuntime()
    }
}

extension RustWorkspaceReviewJourneyTests {
    @Test("The async legacy draft path waits for disk and preserves the original storage error and text")
    func legacyDraftDurability() async throws {
        let store = ControlledStore()
        let workspace = await loadedWorkspace(store: store)
        let key = DraftKey.reviewStep(session: "review-local", step: .mindSweep, item: "text")
        await store.holdWrites()
        var finished = false
        let saving = Task {
            try await workspace.saveDraft("Keep this text", for: key, editorID: "scene:legacy:form")
            finished = true
        }
        await store.waitForHeldWrite()
        #expect(!finished, "The caller cannot clear its field before the disk commit")
        await store.releaseWrites()
        try await saving.value
        #expect(finished)
        #expect(try await store.base.load()?.local.formDrafts[key]?.text == "Keep this text")

        await store.failWrites(with: .io("No space left on device"))
        do {
            try await workspace.saveDraft("Still authored", for: key, editorID: "scene:legacy:form")
            Issue.record("A failed local write cannot be reported as saved")
        } catch {
            #expect(Workspace.saveMessage(for: error).contains("No space left on device"))
        }
        #expect(workspace.draft(for: key) == "Keep this text")
        #expect(try await store.base.load()?.local.formDrafts[key]?.text == "Keep this text")
        await store.failWrites(with: nil)
        await workspace.flush()
        #expect(try await store.base.load()?.local.formDrafts[key]?.text == "Keep this text")
        try await workspace.saveDraft("Still authored", for: key, editorID: "scene:legacy:form")
        #expect(try await store.base.load()?.local.formDrafts[key]?.text == "Still authored")
    }
}
