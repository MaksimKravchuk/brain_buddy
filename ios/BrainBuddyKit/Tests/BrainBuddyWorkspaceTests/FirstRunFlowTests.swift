import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// The iPhone first run (boards 01–04): decided once per device from what it holds, walked with
/// the existing task commands, and remembered as dates and an outcome only.
@MainActor
@Suite struct FirstRunFlowTests {
    // MARK: Decision

    @Test("032-FR-001 a clean device shows the welcome and remembers it") func aCleanDeviceShowsTheWelcomeAndRemembersIt() {
        let store = MemoryFirstRunStore()
        let flow = FirstRunFlow(store: store, now: { Fixture.epoch })

        flow.decide(FirstRunLaunchFacts())

        #expect(flow.phase == .welcome)
        #expect(flow.coversApp)
        #expect(store.saved == FirstRunRecord(decidedAt: Fixture.epoch, outcome: .inProgress))
    }

    @Test("032-FR-001 032-SC-002 a device that holds anything never shows it", arguments: [
        FirstRunLaunchFacts(hasAccount: true),
        FirstRunLaunchFacts(isRustSelected: true),
        FirstRunLaunchFacts(taskCount: 1),
        FirstRunLaunchFacts(projectCount: 1),
        FirstRunLaunchFacts(tagCount: 1),
    ])
    func aDeviceThatHoldsAnythingNeverShowsIt(_ facts: FirstRunLaunchFacts) {
        let store = MemoryFirstRunStore()
        let flow = FirstRunFlow(store: store, now: { Fixture.epoch })

        flow.decide(facts)

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .notNeeded)
    }

    @Test("032-FR-012 a record that cannot be saved skips the welcome") func aRecordThatCannotBeSavedSkipsTheWelcome() {
        let store = MemoryFirstRunStore()
        store.failsToSave = true
        let flow = FirstRunFlow(store: store)

        flow.decide(FirstRunLaunchFacts())

        #expect(flow.phase == .done)
    }

    @Test("032-FR-001 a finished run never returns") func aFinishedRunNeverReturns() {
        for outcome in [FirstRunRecord.Outcome.notNeeded, .skipped, .notYet, .signedIn] {
            let store = MemoryFirstRunStore(FirstRunRecord(decidedAt: Fixture.epoch, outcome: outcome))
            let flow = FirstRunFlow(store: store)
            flow.decide(FirstRunLaunchFacts())
            #expect(flow.phase == .done, "\(outcome)")
        }
    }

    @Test("032-FR-011 a run left before the capture starts again at the welcome") func aRunLeftBeforeTheCaptureStartsAgainAtTheWelcome() {
        let flow = FirstRunFlow(store: MemoryFirstRunStore(FirstRunRecord(decidedAt: Fixture.epoch, outcome: .inProgress)))

        flow.decide(FirstRunLaunchFacts())

        #expect(flow.phase == .welcome)
    }

    @Test("032-FR-011 a run left after the capture does not resume") func aRunLeftAfterTheCaptureDoesNotResume() {
        let store = MemoryFirstRunStore(FirstRunRecord(decidedAt: Fixture.epoch, outcome: .inProgress))
        let flow = FirstRunFlow(store: store)

        flow.decide(FirstRunLaunchFacts(taskCount: 1, hasInboxItem: true))

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .notYet)
    }

    @Test("032-FR-010 the landing tip shows until it is dismissed") func theLandingTipShowsUntilItIsDismissed() {
        let store = MemoryFirstRunStore(FirstRunRecord(decidedAt: Fixture.epoch, outcome: .firstStep))
        let flow = FirstRunFlow(store: store)

        flow.decide(FirstRunLaunchFacts(taskCount: 1))

        #expect(flow.phase == .landing)
        #expect(flow.showsLandingTip)
        #expect(!flow.coversApp)
    }

    @Test("032-FR-001 deciding twice keeps the first answer") func decidingTwiceKeepsTheFirstAnswer() {
        let flow = FirstRunFlow(store: MemoryFirstRunStore())
        flow.decide(FirstRunLaunchFacts())
        flow.decide(FirstRunLaunchFacts(taskCount: 3))
        #expect(flow.phase == .welcome)
    }

    // MARK: Walk

    @Test("032-FR-005 032-FR-008 032-FR-010 the whole run ends on Next actions with the step and the words in the note") func theWholeRunEndsOnNextActionsWithTheStepAndTheOriginalWordsInTheNote() async throws {
        let workspace = await loadedWorkspace()
        let store = MemoryFirstRunStore()
        let tipDate = Fixture.epoch.addingTimeInterval(60)
        var clock = Fixture.epoch
        let flow = FirstRunFlow(store: store, now: { clock })
        flow.decide(FirstRunLaunchFacts(workspace))
        flow.start()
        #expect(flow.phase == .capture)

        let captured = try await flow.capture("  the garage is a mess and Sam needs the van back \n", in: workspace)
        #expect(captured)
        let item = try #require(workspace.state.tasks.values.first)
        #expect(item.title == "the garage is a mess and Sam needs the van back")
        #expect(item.state == .inbox)
        #expect(flow.phase == .firstStep(item.id))
        #expect(flow.capturedText == "the garage is a mess and Sam needs the van back")

        let moved = try await flow.makeNextStep("Call Sam about the van", in: workspace)
        #expect(moved)
        let step = try #require(workspace.task(item.id))
        #expect(step.title == "Call Sam about the van")
        #expect(step.details == "the garage is a mess and Sam needs the van back")
        #expect(step.state == .next)
        #expect(step.projectID == nil)
        #expect(workspace.state.projects.isEmpty)
        #expect(workspace.state.tasks.count == 1)
        #expect(flow.phase == .landing)
        #expect(store.saved?.outcome == .firstStep)

        clock = tipDate
        flow.dismissTip()
        #expect(flow.phase == .done)
        #expect(store.saved?.tipDismissedAt == tipDate)
    }

    @Test("032-FR-005 the capture is the text as written, without Smart Add") func theCaptureIsTheTextAsWrittenWithoutSmartAdd() async throws {
        let workspace = await loadedWorkspace()
        let flow = startedFlow()

        try await flow.capture("Paint the hall @Home #errands tomorrow", in: workspace)

        let item = try #require(workspace.state.tasks.values.first)
        #expect(item.title == "Paint the hall @Home #errands tomorrow")
        #expect(item.projectID == nil)
        #expect(item.tagIDs.isEmpty)
        #expect(item.dueDate == nil)
    }

    @Test("032-FR-005 empty text adds nothing") func emptyTextAddsNothing() async throws {
        let workspace = await loadedWorkspace()
        let flow = startedFlow()

        let captured = try await flow.capture(" \n ", in: workspace)

        #expect(!captured)
        #expect(workspace.state.tasks.isEmpty)
        #expect(flow.phase == .capture)
    }

    @Test("032-FR-006 Skip leaves an empty Inbox") func skipLeavesAnEmptyInbox() {
        let store = MemoryFirstRunStore()
        let flow = FirstRunFlow(store: store)
        flow.decide(FirstRunLaunchFacts())
        flow.start()

        flow.skip()

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .skipped)
    }

    @Test("032-FR-009 Not yet keeps the item in the Inbox unchanged") func notYetKeepsTheItemInTheInboxUnchanged() async throws {
        let workspace = await loadedWorkspace()
        let store = MemoryFirstRunStore()
        let flow = FirstRunFlow(store: store)
        flow.decide(FirstRunLaunchFacts())
        flow.start()
        try await flow.capture("Sort the garage", in: workspace)
        let before = workspace.state

        flow.notYet()

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .notYet)
        #expect(workspace.state == before)
        #expect(workspace.state.tasks.values.first?.state == .inbox)
    }

    @Test("032-FR-008 an empty step moves nothing") func anEmptyStepMovesNothing() async throws {
        let workspace = await loadedWorkspace()
        let flow = startedFlow()
        try await flow.capture("Sort the garage", in: workspace)
        let before = workspace.state

        let moved = try await flow.makeNextStep("   ", in: workspace)

        #expect(!moved)
        #expect(workspace.state == before)
    }

    @Test("032-FR-008 a step that repeats the capture adds no note") func aStepThatRepeatsTheCaptureAddsNoNote() async throws {
        let workspace = await loadedWorkspace()
        let flow = startedFlow()
        try await flow.capture("Call Sam", in: workspace)

        try await flow.makeNextStep("Call Sam", in: workspace)

        let step = try #require(workspace.state.tasks.values.first)
        #expect(step.details == nil)
        #expect(step.state == .next)
    }

    @Test("032-FR-003 linking an account ends the run at any step") func linkingAnAccountEndsTheRunAtAnyStep() {
        let store = MemoryFirstRunStore()
        let flow = FirstRunFlow(store: store)
        flow.decide(FirstRunLaunchFacts())

        flow.accountLinked()

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .signedIn)
    }

    // MARK: Composition

    @Test("032-FR-008 the step change keeps an existing note after the captured words") func theStepChangeKeepsAnExistingNoteAfterTheOriginalWords() {
        let changes = FirstRunFlow.stepChanges(step: "Call Sam", original: "garage mess", existingDetails: " keys in the drawer ")
        #expect(changes.title == .set("Call Sam"))
        #expect(changes.details == .set("garage mess\n\nkeys in the drawer"))
        #expect(changes.projectID == .unchanged)
        #expect(changes.tagIDs == .unchanged)
        #expect(changes.dueDate == .unchanged)
    }

    // MARK: Helpers

    private func startedFlow() -> FirstRunFlow {
        let flow = FirstRunFlow(store: MemoryFirstRunStore())
        flow.decide(FirstRunLaunchFacts())
        flow.start()
        return flow
    }
}

@Suite struct UserDefaultsFirstRunRecordStoreTests {
    @MainActor
    @Test("032-FR-012 the record round-trips through its own key") func theRecordRoundTripsThroughItsOwnKey() throws {
        let suite = "FirstRunTests-\(UUID().uuidString)"
        let defaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = UserDefaultsFirstRunRecordStore(defaults: defaults)
        #expect(store.load() == nil)

        let record = FirstRunRecord(decidedAt: Fixture.epoch, outcome: .firstStep, tipDismissedAt: Fixture.epoch)
        try store.save(record)

        #expect(UserDefaultsFirstRunRecordStore(defaults: defaults).load() == record)
        #expect(defaults.data(forKey: UserDefaultsFirstRunRecordStore.key) != nil)
    }
}

@MainActor
private final class MemoryFirstRunStore: FirstRunRecordStore {
    private(set) var saved: FirstRunRecord?
    var failsToSave = false

    init(_ record: FirstRunRecord? = nil) {
        saved = record
    }

    func load() -> FirstRunRecord? { saved }

    func save(_ record: FirstRunRecord) throws {
        if failsToSave { throw CocoaError(.fileWriteUnknown) }
        saved = record
    }
}
