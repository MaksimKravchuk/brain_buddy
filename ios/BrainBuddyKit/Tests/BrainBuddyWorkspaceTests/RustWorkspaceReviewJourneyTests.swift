import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyWorkspace

@MainActor
@Suite("Selected Review Workspace journeys (026-FR-001, 026-FR-025, 026-FR-026)")
struct RustWorkspaceReviewJourneyTests {
    private func workspace(at directory: URL, clock: TestClock) async throws -> (Workspace, RustWorkspaceRuntime, ControlledStore) {
        let bridge = try RustBridgeRuntime()
        let runtime = try await bridge.openStore(workspaceID: "local", databaseURL: directory.appendingPathComponent("store.sqlite3"))
        let retired = ControlledStore()
        let workspace = Workspace(store: retired, sync: nil,
            rust: RustWorkspaceSelection(runtime: runtime,
                facade: RustDomainFacade(runtime: bridge, context: RustDomainContext(deviceTimeZone: "UTC")), reviewEnabled: true),
            now: { clock.now })
        workspace.accountlessReviewEnabled = true
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
        await workspace.closeRuntime()
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
