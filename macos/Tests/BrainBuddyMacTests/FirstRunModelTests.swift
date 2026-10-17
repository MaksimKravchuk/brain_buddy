import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The Mac's one-time first run (spec 029, PR-01): the clean-Mac decision, the phases, the first
/// step's composition and the record that holds dates and an outcome, never text.
@MainActor
final class FakeFirstRunWriter: FirstRunTaskWriting {
    var captured: [String] = []
    var steps: [(id: TaskID, step: String, original: String)] = []
    var failCapture = false
    var failStep = false
    /// Runs while a save is in flight, standing in for a person acting during the await.
    var duringSave: (() -> Void)?
    let itemID: TaskID = "first-item"

    func captureFirstItem(_ text: String) async -> TaskID? {
        guard !failCapture else { return nil }
        captured.append(text)
        duringSave?()
        return itemID
    }

    func saveFirstStep(_ id: TaskID, step: String, original: String) async -> Bool {
        guard !failStep else { return false }
        steps.append((id, step, original))
        duringSave?()
        return true
    }
}

@Suite("Mac first run")
@MainActor
struct FirstRunModelTests {
    private let clock = TestClock()

    private func make(in folder: TemporaryFolder, seed: ((inout MacLocalState) -> Void)? = nil) throws -> FirstRunModel {
        let store = MacLocalStateStore(directory: folder.url)
        if let seed { try store.update(seed) }
        return FirstRunModel(store: store, now: clock.provider)
    }

    private func recorded(_ folder: TemporaryFolder) -> FirstRunRecord? {
        MacLocalStateStore(directory: folder.url).load()?.firstRun
    }

    // MARK: Decision (T002)

    @Test("029-FR-001 029-SC-002 a fresh Mac shows the welcome, opens on the Inbox and records inProgress")
    func decisionFreshMac() throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts(openTaskCount: 0, projectCount: 0))
        #expect(model.phase == .welcome)
        #expect(model.launchDestination == .list(.inbox))
        #expect(model.showsFirstRunSidebar)
        #expect(recorded(folder)?.outcome == .inProgress)
        #expect(recorded(folder)?.decidedAt == clock.now)
    }

    @Test("029-FR-001 029-SC-002 a Mac with data, an account or tasks records notNeeded and shows nothing",
        arguments: [
            FirstRunLaunchFacts(workspaceWrittenBefore: true),
            FirstRunLaunchFacts(hasAccount: true),
            FirstRunLaunchFacts(openTaskCount: 1, projectCount: 0),
            FirstRunLaunchFacts(openTaskCount: 0, projectCount: 1),
        ])
    func decisionNotClean(_ facts: FirstRunLaunchFacts) throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(facts)
        #expect(model.phase == .done)
        #expect(model.launchDestination == nil)
        #expect(!model.showsFirstRunSidebar)
        #expect(recorded(folder)?.outcome == .notNeeded)
    }

    @Test("029-FR-001 029-SC-002 a recorded first run is never decided again")
    func decisionRecordPresent() throws {
        let folder = TemporaryFolder()
        let earlier = clock.now.addingTimeInterval(-60)
        let model = try make(in: folder) { $0.firstRun = FirstRunRecord(decidedAt: earlier, outcome: .skipped) }
        model.decide(FirstRunLaunchFacts())
        #expect(model.phase == .done)
        #expect(recorded(folder) == FirstRunRecord(decidedAt: earlier, outcome: .skipped))
    }

    @Test("029-FR-001 029-SC-002 a run quit before the question ends as notYet with an Inbox item, skipped without")
    func decisionInProgressRelaunch() throws {
        for (hasItem, outcome) in [(true, FirstRunRecord.Outcome.notYet), (false, .skipped)] {
            let folder = TemporaryFolder()
            let model = try make(in: folder) { $0.firstRun = FirstRunRecord(decidedAt: clock.now, outcome: .inProgress) }
            model.decide(FirstRunLaunchFacts(hasInboxItem: hasItem))
            #expect(model.phase == .done)
            #expect(model.launchDestination == nil)
            #expect(recorded(folder)?.outcome == outcome)
        }
    }

    @Test("029-FR-011 029-SC-002 a run quit at the tip reopens on Next actions with the tip until Got it")
    func decisionTipPending() throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder) { $0.firstRun = FirstRunRecord(decidedAt: clock.now, outcome: .firstStep) }
        model.decide(FirstRunLaunchFacts(workspaceWrittenBefore: true, openTaskCount: 1, projectCount: 0, hasInboxItem: false))
        #expect(model.phase == .landing)
        #expect(model.launchDestination == .list(.next))
        #expect(model.showsFirstRunSidebar)
        model.dismissTip()
        #expect(model.phase == .done)
        let reopened = try make(in: folder)
        reopened.decide(FirstRunLaunchFacts())
        #expect(reopened.phase == .done, "never after Got it")
    }

    @Test("029-FR-001 029-SC-002 deciding writes nothing but the first-run record")
    func decisionWritesOnlyTheRecord() throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder) { $0.sidebar = .init(archivedProjectsExpanded: true) }
        let before = try #require(MacLocalStateStore(directory: folder.url).load())
        model.decide(FirstRunLaunchFacts())
        var after = try #require(MacLocalStateStore(directory: folder.url).load())
        #expect(after.firstRun?.outcome == .inProgress)
        after.firstRun = nil
        #expect(after == before)
        #expect(!folder.names.contains(MacFileNames.store), "no workspace write")
    }

    // MARK: Steps

    @Test("029-FR-006 Return adds one Inbox item with exactly the typed text, trimmed; empty text does nothing")
    func captureAsWritten() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        let blank = await model.capture("  \n ", using: writer)
        #expect(!blank)
        #expect(writer.captured.isEmpty)
        #expect(model.phase == .welcome)
        let added = await model.capture("  buy milk #home tomorrow \n", using: writer)
        #expect(added)
        #expect(writer.captured == ["buy milk #home tomorrow"])
        #expect(model.phase == .firstStep("first-item"))
        #expect(model.launchDestination == .list(.inbox))
    }

    @Test("029-FR-006 a failed capture keeps the welcome")
    func captureFailureStays() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        writer.failCapture = true
        let added = await model.capture("anything", using: writer)
        #expect(!added)
        #expect(model.phase == .welcome)
    }

    @Test("029-FR-007 Esc in the welcome ends the run without adding anything")
    func skipEndsRun() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        model.skip()
        #expect(model.phase == .done)
        #expect(!model.showsFirstRunSidebar)
        #expect(recorded(folder)?.outcome == .skipped)
    }

    @Test("029-FR-010 Not yet leaves the item and ends the run without a tip")
    func notYetEndsRun() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        await model.capture("something", using: writer)
        model.notYet()
        #expect(model.phase == .done)
        #expect(writer.steps.isEmpty)
        #expect(recorded(folder)?.outcome == .notYet)
        #expect(recorded(folder)?.tipDismissedAt == nil)
    }

    @Test("029-FR-013 linking an account at any step ends the run as signedIn")
    func accountEndsRun() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        await model.capture("something", using: writer)
        model.accountLinked()
        #expect(model.phase == .done)
        #expect(recorded(folder)?.outcome == .signedIn)
    }

    @Test("029-FR-007 029-FR-013 a skip or sign-in during the capture save is not undone when the save returns")
    func endDuringCaptureStays() async throws {
        let ends: [(end: (FirstRunModel) -> Void, outcome: FirstRunRecord.Outcome)] = [
            ({ $0.skip() }, .skipped),
            ({ $0.accountLinked() }, .signedIn),
        ]
        for (end, outcome) in ends {
            let folder = TemporaryFolder()
            let model = try make(in: folder)
            model.decide(FirstRunLaunchFacts())
            let writer = FakeFirstRunWriter()
            writer.duringSave = { end(model) }
            let saved = await model.capture("something", using: writer)
            #expect(saved, "the item was saved, so the field clears")
            #expect(model.phase == .done)
            #expect(recorded(folder)?.outcome == outcome)
        }
    }

    @Test("029-FR-010 029-FR-013 Not yet or a sign-in during the step save keeps that outcome")
    func endDuringStepStays() async throws {
        let ends: [(end: (FirstRunModel) -> Void, outcome: FirstRunRecord.Outcome)] = [
            ({ $0.notYet() }, .notYet),
            ({ $0.accountLinked() }, .signedIn),
        ]
        for (end, outcome) in ends {
            let folder = TemporaryFolder()
            let model = try make(in: folder)
            model.decide(FirstRunLaunchFacts())
            let writer = FakeFirstRunWriter()
            await model.capture("something", using: writer)
            writer.duringSave = { end(model) }
            let saved = await model.makeNextStep("A step", using: writer)
            #expect(saved)
            #expect(model.phase == .done)
            #expect(recorded(folder)?.outcome == outcome)
        }
    }

    // MARK: First step (T004)

    @Test("029-FR-009 029-SC-004 the step is saved with the captured text as its original, then the tip shows")
    func firstStepSaves() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        await model.capture("the garage is a mess and Sam needs the van back", using: writer)
        let empty = await model.makeNextStep("   ", using: writer)
        #expect(!empty, "unavailable while the field is empty")
        let saved = await model.makeNextStep(" Call Sam about the van ", using: writer)
        #expect(saved)
        let call = try #require(writer.steps.first)
        #expect(call.id == "first-item")
        #expect(call.step == "Call Sam about the van")
        #expect(call.original == "the garage is a mess and Sam needs the van back")
        #expect(model.phase == .landing)
        #expect(model.launchDestination == .list(.next))
        #expect(recorded(folder)?.outcome == .firstStep)
    }

    @Test("029-FR-009 029-SC-007 a failed save leaves the question and the record as they were")
    func firstStepFailureStays() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        await model.capture("original words", using: writer)
        writer.failStep = true
        let saved = await model.makeNextStep("A step", using: writer)
        #expect(!saved)
        #expect(model.phase == .firstStep("first-item"))
        #expect(recorded(folder)?.outcome == .inProgress)
    }

    @Test("029-FR-009 the step becomes the title and the original goes first in the note, once")
    func stepChangesKeepOriginal() {
        let plain = FirstRunModel.stepChanges(step: "Call Sam", original: "van problem", existingDetails: nil)
        #expect(plain.title == .set("Call Sam"))
        #expect(plain.details == .set("van problem"))
        let withNote = FirstRunModel.stepChanges(step: "Call Sam", original: "van problem", existingDetails: "  earlier note ")
        #expect(withNote.details == .set("van problem\n\nearlier note"))
        let same = FirstRunModel.stepChanges(step: "Call Sam", original: "Call Sam", existingDetails: nil)
        #expect(same.title == .set("Call Sam"))
        #expect(same.details == .unchanged, "not written twice")
        #expect(plain.projectID == .unchanged && plain.tagIDs == .unchanged && plain.dueDate == .unchanged)
    }

    @Test("029-FR-009 029-SC-004 on the real workspace the first step lands in Next actions with the note and no project")
    func firstStepOnTheWorkspace() async throws {
        let folder = TemporaryFolder()
        let workspace = Workspace(store: InMemoryDocumentStore(), sync: nil, now: clock.provider)
        await workspace.load()
        let model = BrainBuddyModel(workspace: workspace, localStateStore: MacLocalStateStore(directory: folder.url), now: clock.provider)
        model.decideFirstRun()
        #expect(model.firstRun.phase == .welcome)
        #expect(model.destination == .list(.inbox))
        let sentence = "the garage is a mess and Sam needs the van back"
        let added = await model.firstRun.capture(sentence, using: model)
        #expect(added)
        guard case .firstStep(let id) = model.firstRun.phase else {
            Issue.record("expected the first-step phase")
            return
        }
        let captured = try #require(workspace.task(id))
        #expect(captured.title == sentence)
        #expect(captured.state == .inbox)
        let saved = await model.firstRun.makeNextStep("Call Sam about the van", using: model)
        #expect(saved)
        let moved = try #require(workspace.task(id))
        #expect(moved.title == "Call Sam about the van")
        #expect(moved.details == sentence)
        #expect(moved.state == .next)
        #expect(moved.projectID == nil)
        #expect(workspace.state.projects.isEmpty, "no createProject")
        #expect(model.firstRun.phase == .landing)
    }

    @Test("029-FR-001 029-FR-002 a model that does not decide keeps today's launch on Next actions")
    func undecidedKeepsDefault() throws {
        let folder = TemporaryFolder()
        let model = BrainBuddyModel(
            workspace: Workspace(store: InMemoryDocumentStore(), sync: nil, now: clock.provider),
            localStateStore: MacLocalStateStore(directory: folder.url), now: clock.provider)
        #expect(model.destination == .list(.next))
        #expect(model.firstRun.phase == .undecided)
        #expect(model.firstRun.launchDestination == nil)
    }

    // MARK: Record and copy (T005)

    @Test("029-FR-015 029-FR-031 the record never contains captured text")
    func recordHoldsNoText() async throws {
        let folder = TemporaryFolder()
        let model = try make(in: folder)
        model.decide(FirstRunLaunchFacts())
        let writer = FakeFirstRunWriter()
        let sentence = "Sentinel-Capture-7f3a the garage is a mess"
        let step = "Sentinel-Step-2c9e call Sam"
        await model.capture(sentence, using: writer)
        await model.makeNextStep(step, using: writer)
        model.dismissTip()
        let data = try #require(folder.bytes(MacLocalStateStore.fileName))
        let text = String(decoding: data, as: UTF8.self)
        #expect(!text.contains("Sentinel-"))
        #expect(!text.contains("garage") && !text.contains("Sam"))
        #expect(text.contains("\"firstRun\""))
    }

    @Test("029-FR-004 029-FR-011 the tip omits the shortcut clause when it is unavailable")
    func landingTipWords() {
        let both = FirstRunCopy.landingTip(hotkeyAvailable: true)
        #expect(both == "This is your next step. When it is done, press Done. Anything else on your mind: ⌘N here, or ⌃⌥⇧B from any app. ⌘O finds any step.")
        let without = FirstRunCopy.landingTip(hotkeyAvailable: false)
        #expect(without == "This is your next step. When it is done, press Done. Anything else on your mind: ⌘N here. ⌘O finds any step.")
    }
}
