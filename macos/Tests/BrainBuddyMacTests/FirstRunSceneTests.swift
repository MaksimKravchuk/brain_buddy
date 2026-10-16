import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// What the main window shows while the first run runs (spec 029, PR-02), asserted on the model the
/// window renders: the views read `destination`, `firstRun.phase` and `firstRun.showsFirstRunSidebar`
/// and nothing else, so these are the scene's decisions. Pixels are PR-06's snapshots.
@Suite("Mac first run scene")
@MainActor
struct FirstRunSceneTests {
    private let clock = TestClock()

    private func clean(_ folder: TemporaryFolder) async -> BrainBuddyModel {
        let workspace = Workspace(store: InMemoryDocumentStore(), sync: nil, now: clock.provider)
        await workspace.load()
        return BrainBuddyModel(workspace: workspace, localStateStore: MacLocalStateStore(directory: folder.url), now: clock.provider)
    }

    @Test("029-FR-002 029-SC-001 a clean Mac opens on the Inbox welcome with the first-run sidebar")
    func opensOnTheWelcome() async {
        let model = await clean(TemporaryFolder())
        #expect(model.destination == .list(.next), "before the decision the window is today's")
        model.decideFirstRun()
        #expect(model.firstRun.phase == .welcome)
        #expect(model.destination == .list(.inbox))
        #expect(model.selectedList == .inbox)
        #expect(model.firstRun.showsFirstRunSidebar)
    }

    @Test("029-FR-007 Esc skips: no item, the normal sidebar and the empty Inbox")
    func escapeSkips() async {
        let folder = TemporaryFolder()
        let model = await clean(folder)
        model.decideFirstRun()
        model.firstRun.skip()
        #expect(model.firstRun.phase == .done)
        #expect(!model.firstRun.showsFirstRunSidebar)
        #expect(model.destination == .list(.inbox))
        #expect(model.workspace.state.tasks.isEmpty)
        #expect(MacLocalStateStore(directory: folder.url).load()?.firstRun?.outcome == .skipped)
    }

    @Test("029-FR-012 the normal sidebar returns when the first run ends, however it ends")
    func sidebarReturns() async {
        let folder = TemporaryFolder()
        let model = await clean(folder)
        model.decideFirstRun()
        #expect(model.firstRun.showsFirstRunSidebar)
        let okCaptureModel = await model.firstRun.capture("the garage is a mess", using: model)
        #expect(okCaptureModel)
        #expect(model.firstRun.showsFirstRunSidebar, "the question keeps the first-run sidebar")
        model.firstRun.notYet()
        #expect(!model.firstRun.showsFirstRunSidebar)
        #expect(model.firstRun.launchDestination == nil)

        let other = await clean(TemporaryFolder())
        other.decideFirstRun()
        let okCaptureOther = await other.firstRun.capture("call Sam", using: other)
        #expect(okCaptureOther)
        let okMakenextstepOther = await other.firstRun.makeNextStep("Call Sam about the van", using: other)
        #expect(okMakenextstepOther)
        #expect(other.firstRun.phase == .landing)
        #expect(other.firstRun.showsFirstRunSidebar, "the tip keeps the first-run sidebar")
        other.firstRun.dismissTip()
        #expect(!other.firstRun.showsFirstRunSidebar)
    }

    @Test("029-FR-012 the first-run sidebar is the Lists and Dates sections of the normal one")
    func sidebarSectionsExist() {
        let headers = SidebarEntries.standard.sections.compactMap(\.header)
        #expect(headers.contains("Lists") && headers.contains("Dates"))
        let lists = SidebarEntries.standard.sections.first { $0.header == "Lists" }?.rows.map(\.title)
        #expect(lists == ["Inbox", "Next actions", "Waiting for", "Someday"])
        let dates = SidebarEntries.standard.sections.first { $0.header == "Dates" }?.rows.map(\.title)
        #expect(dates == ["Overdue", "Today", "Upcoming"])
    }

    @Test("029-SC-001 type, Return, type, Return reaches Next actions with the step and no project")
    func fourKeyboardActions() async throws {
        let model = await clean(TemporaryFolder())
        model.decideFirstRun()
        let okCaptureModel = await model.firstRun.capture("the garage is a mess", using: model)
        #expect(okCaptureModel)
        let okMakenextstepModel = await model.firstRun.makeNextStep("Call Sam about the van", using: model)
        #expect(okMakenextstepModel)
        #expect(model.firstRun.phase == .landing)
        #expect(model.firstRun.launchDestination == .list(.next))
        let next = model.workspace.state.tasks.values.filter { $0.state == .next }
        #expect(next.map(\.title) == ["Call Sam about the van"])
        #expect(next.first?.projectID == nil)
    }

    @Test("029-FR-014 029-SC-003 the first run from launch to Got it makes no network request")
    func noNetworkDuringTheFirstRun() async {
        let folder = TemporaryFolder()
        let transport = CountingTransport()
        let host = WorkspaceHost(
            configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: SpyTokenStore(),
            transport: transport, now: clock.provider)
        await host.workspace.load()
        let model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState, now: clock.provider)
        model.decideFirstRun()
        #expect(model.firstRun.phase == .welcome)
        _ = await model.firstRun.capture("the garage is a mess", using: model)
        _ = await model.firstRun.makeNextStep("Call Sam about the van", using: model)
        model.firstRun.dismissTip()
        await host.workspace.flush()
        #expect(model.firstRun.phase == .done)
        #expect(transport.requests.isEmpty)
    }

    @Test("029-FR-013 an account linked on the welcome ends the first run and keeps the Inbox")
    func accountLinkedEndsIt() async {
        let model = await clean(TemporaryFolder())
        model.decideFirstRun()
        model.firstRun.accountLinked()
        #expect(model.firstRun.phase == .done)
        #expect(!model.firstRun.showsFirstRunSidebar)
    }

    @Test("029-FR-004 029-FR-011 the tip follows the shortcut's availability set by the window")
    func tipFollowsTheShortcut() async {
        let model = await clean(TemporaryFolder())
        model.firstRun.hotkeyAvailable = false
        #expect(!model.firstRun.landingTip.contains("⌃⌥⇧B"))
        model.firstRun.hotkeyAvailable = true
        #expect(model.firstRun.landingTip.contains("⌃⌥⇧B"))
    }
}
