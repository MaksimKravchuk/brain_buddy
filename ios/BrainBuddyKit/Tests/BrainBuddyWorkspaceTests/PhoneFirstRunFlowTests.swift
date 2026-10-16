import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// The iPhone first run (boards 01–04): decided once per device from what it holds, walked with
/// the existing task commands, and remembered as dates and an outcome only.
@MainActor
@Suite struct PhoneFirstRunFlowTests {
    // MARK: Decision

    @Test("032-FR-001 a clean device shows the welcome and remembers it") func aCleanDeviceShowsTheWelcomeAndRemembersIt() {
        let store = MemoryFirstRunStore()
        let flow = PhoneFirstRunFlow(store: store, now: { Fixture.epoch })

        flow.decide(PhoneFirstRunLaunchFacts())

        #expect(flow.phase == .welcome)
        #expect(flow.coversApp)
        #expect(store.saved == PhoneFirstRunRecord(decidedAt: Fixture.epoch, outcome: .inProgress))
    }

    @Test("032-FR-001 032-SC-002 a device that holds anything never shows it", arguments: [
        PhoneFirstRunLaunchFacts(hasAccount: true),
        PhoneFirstRunLaunchFacts(isRustSelected: true),
        PhoneFirstRunLaunchFacts(taskCount: 1),
        PhoneFirstRunLaunchFacts(projectCount: 1),
        PhoneFirstRunLaunchFacts(tagCount: 1),
    ])
    func aDeviceThatHoldsAnythingNeverShowsIt(_ facts: PhoneFirstRunLaunchFacts) {
        let store = MemoryFirstRunStore()
        let flow = PhoneFirstRunFlow(store: store, now: { Fixture.epoch })

        flow.decide(facts)

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .notNeeded)
    }

    @Test("032-FR-012 a record that cannot be saved skips the welcome") func aRecordThatCannotBeSavedSkipsTheWelcome() {
        let store = MemoryFirstRunStore()
        store.failsToSave = true
        let flow = PhoneFirstRunFlow(store: store)

        flow.decide(PhoneFirstRunLaunchFacts())

        #expect(flow.phase == .done)
    }

    @Test("032-FR-001 a finished run never returns") func aFinishedRunNeverReturns() {
        for outcome in [PhoneFirstRunRecord.Outcome.notNeeded, .skipped, .notYet, .signedIn] {
            let store = MemoryFirstRunStore(PhoneFirstRunRecord(decidedAt: Fixture.epoch, outcome: outcome))
            let flow = PhoneFirstRunFlow(store: store)
            flow.decide(PhoneFirstRunLaunchFacts())
            #expect(flow.phase == .done, "\(outcome)")
        }
    }

    @Test("032-FR-011 a run left before the capture starts again at the welcome") func aRunLeftBeforeTheCaptureStartsAgainAtTheWelcome() {
        let flow = PhoneFirstRunFlow(store: MemoryFirstRunStore(PhoneFirstRunRecord(decidedAt: Fixture.epoch, outcome: .inProgress)))

        flow.decide(PhoneFirstRunLaunchFacts())

        #expect(flow.phase == .welcome)
    }

    @Test("032-FR-011 a run left after the capture does not resume") func aRunLeftAfterTheCaptureDoesNotResume() {
        let store = MemoryFirstRunStore(PhoneFirstRunRecord(decidedAt: Fixture.epoch, outcome: .inProgress))
        let flow = PhoneFirstRunFlow(store: store)

        flow.decide(PhoneFirstRunLaunchFacts(taskCount: 1, hasInboxItem: true))

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .notYet)
    }

    @Test("032-FR-010 the landing tip shows until it is dismissed") func theLandingTipShowsUntilItIsDismissed() {
        let store = MemoryFirstRunStore(PhoneFirstRunRecord(decidedAt: Fixture.epoch, outcome: .firstStep))
        let flow = PhoneFirstRunFlow(store: store)

        flow.decide(PhoneFirstRunLaunchFacts(taskCount: 1))

        #expect(flow.phase == .landing)
        #expect(flow.showsLandingTip)
        #expect(!flow.coversApp)
    }

    @Test("032-FR-001 deciding twice keeps the first answer") func decidingTwiceKeepsTheFirstAnswer() {
        let flow = PhoneFirstRunFlow(store: MemoryFirstRunStore())
        flow.decide(PhoneFirstRunLaunchFacts())
        flow.decide(PhoneFirstRunLaunchFacts(taskCount: 3))
        #expect(flow.phase == .welcome)
    }

    // MARK: Walk

    @Test("032-FR-005 032-FR-008 032-FR-010 the whole run ends on Next actions with the step and the words in the note") func theWholeRunEndsOnNextActionsWithTheStepAndTheOriginalWordsInTheNote() async throws {
        let workspace = await loadedWorkspace()
        let store = MemoryFirstRunStore()
        let tipDate = Fixture.epoch.addingTimeInterval(60)
        var clock = Fixture.epoch
        let flow = PhoneFirstRunFlow(store: store, now: { clock })
        flow.decide(PhoneFirstRunLaunchFacts(workspace))
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
        let flow = PhoneFirstRunFlow(store: store)
        flow.decide(PhoneFirstRunLaunchFacts())
        flow.start()

        flow.skip()

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .skipped)
    }

    @Test("032-FR-009 Not yet keeps the item in the Inbox unchanged") func notYetKeepsTheItemInTheInboxUnchanged() async throws {
        let workspace = await loadedWorkspace()
        let store = MemoryFirstRunStore()
        let flow = PhoneFirstRunFlow(store: store)
        flow.decide(PhoneFirstRunLaunchFacts())
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
        let flow = PhoneFirstRunFlow(store: store)
        flow.decide(PhoneFirstRunLaunchFacts())

        flow.accountLinked()

        #expect(flow.phase == .done)
        #expect(store.saved?.outcome == .signedIn)
    }

    // MARK: Composition

    @Test("032-FR-008 the step change keeps an existing note after the captured words") func theStepChangeKeepsAnExistingNoteAfterTheOriginalWords() {
        let changes = PhoneFirstRunFlow.stepChanges(step: "Call Sam", original: "garage mess", existingDetails: " keys in the drawer ")
        #expect(changes.title == .set("Call Sam"))
        #expect(changes.details == .set("garage mess\n\nkeys in the drawer"))
        #expect(changes.projectID == .unchanged)
        #expect(changes.tagIDs == .unchanged)
        #expect(changes.dueDate == .unchanged)
    }

    // MARK: Helpers

    private func startedFlow() -> PhoneFirstRunFlow {
        let flow = PhoneFirstRunFlow(store: MemoryFirstRunStore())
        flow.decide(PhoneFirstRunLaunchFacts())
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
        let store = UserDefaultsPhoneFirstRunRecordStore(defaults: defaults)
        #expect(store.load() == nil)

        let record = PhoneFirstRunRecord(decidedAt: Fixture.epoch, outcome: .firstStep, tipDismissedAt: Fixture.epoch)
        try store.save(record)

        #expect(UserDefaultsPhoneFirstRunRecordStore(defaults: defaults).load() == record)
        #expect(defaults.data(forKey: UserDefaultsPhoneFirstRunRecordStore.key) != nil)
    }
}

@MainActor
private final class MemoryFirstRunStore: PhoneFirstRunRecordStore {
    private(set) var saved: PhoneFirstRunRecord?
    var failsToSave = false

    init(_ record: PhoneFirstRunRecord? = nil) {
        saved = record
    }

    func load() -> PhoneFirstRunRecord? { saved }

    func save(_ record: PhoneFirstRunRecord) throws {
        if failsToSave { throw CocoaError(.fileWriteUnknown) }
        saved = record
    }
}
