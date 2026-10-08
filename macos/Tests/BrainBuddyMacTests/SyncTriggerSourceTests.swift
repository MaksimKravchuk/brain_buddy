import BrainBuddyCore
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// Records every call the trigger source makes, in order.
@MainActor
final class RecordingTriggerTarget: SyncTriggerTarget {
    var isAccountLinked = false
    private(set) var calls: [String] = []

    func clear() { calls.removeAll() }
    func reloadIfChangedExternally() async { calls.append("reloadIfChangedExternally") }
    func setForegroundActive(_ active: Bool) async { calls.append("setForegroundActive(\(active))") }
    func requestForegroundPull() async { calls.append("foreground") }
    func networkAvailabilityChanged(isAvailable: Bool) { calls.append("networkAvailabilityChanged(\(isAvailable))") }
    func syncNow() async { calls.append("syncNow") }
    func flush() async { calls.append("flush") }
    func refreshTaskDetails(_ id: TaskID) async { calls.append("refreshTaskDetails(\(id.rawValue))") }
}

/// The trigger table of contracts/mac-app-host.md §5 (FR-006), with a fake path monitor, a fake App
/// Nap activity and manual timers.
@Suite("Sync triggers")
@MainActor
struct SyncTriggerSourceTests {
    @MainActor
    private struct Rig {
        let target = RecordingTriggerTarget()
        let monitor = FakePathMonitor()
        let activity = FakeActivity()
        let scheduler = ManualSyncScheduler()
        let source: SyncTriggerSource

        init() {
            source = SyncTriggerSource(
                target: target, pathMonitor: monitor, activity: activity, detailScheduler: scheduler, log: CapturingMacLog()
            )
        }
    }

    @Test("021-FR-006 launch starts the path monitor and the kit ticker for the life of the process, with one pull")
    func launchStarts() async {
        let rig = Rig()
        await rig.source.start()
        #expect(rig.monitor.isStarted)
        #expect(rig.target.calls == ["setForegroundActive(true)"], "the kit ticker on, and one forced pull")
        await rig.source.start()
        #expect(rig.target.calls == ["setForegroundActive(true)"], "starting twice changes nothing")
        #expect(!rig.target.calls.contains("setForegroundActive(false)"), "the Mac never stops the ticker")
    }

    @Test("021-FR-006 activation reloads external changes, then asks for one forced pull; a visible window asks for .foreground")
    func activationAndOcclusion() async {
        let rig = Rig()
        await rig.source.handle(.didBecomeActive)
        #expect(rig.target.calls == ["reloadIfChangedExternally", "setForegroundActive(true)"])
        rig.target.clear()
        await rig.source.handle(.didBecomeActive)
        #expect(rig.target.calls == ["reloadIfChangedExternally", "foreground"], "later activations pull again")
        rig.target.clear()
        await rig.source.handle(.windowBecameVisible)
        #expect(rig.target.calls == ["foreground"])
    }

    @Test("021-FR-006 the network coming back or going reaches the engine, each change once")
    func networkChanges() async {
        let rig = Rig()
        await rig.source.start()
        rig.target.clear()
        rig.source.pathChanged(satisfied: true)
        #expect(rig.target.calls.isEmpty, "a network at launch is no change (no extra pull)")
        rig.source.pathChanged(satisfied: false)
        rig.source.pathChanged(satisfied: false)
        rig.source.pathChanged(satisfied: true)
        rig.source.pathChanged(satisfied: true)
        #expect(rig.target.calls == ["networkAvailabilityChanged(false)", "networkAvailabilityChanged(true)"])
    }

    @Test("021-FR-006 Sync now, Retry and the popover's Sync now run syncNow; resign and terminate flush")
    func syncNowAndFlush() async {
        let rig = Rig()
        await rig.source.syncNowRequested()
        await rig.source.handle(.willResignActive)
        await rig.source.handle(.willTerminate)
        #expect(rig.target.calls == ["syncNow", "flush", "flush"])
    }

    @Test("021-FR-006 the App Nap activity is held exactly while an account is linked")
    func appNapActivityFollowsTheAccount() async {
        let rig = Rig()
        await rig.source.start()
        #expect(!rig.activity.held && rig.activity.begins == 0, "account-less, none")

        rig.target.isAccountLinked = true
        rig.source.accountLinkChanged()
        #expect(rig.activity.held && rig.activity.begins == 1)
        rig.source.accountLinkChanged()
        await rig.source.handle(.didBecomeActive)
        #expect(rig.activity.begins == 1, "held once, not again")

        rig.target.isAccountLinked = false
        rig.source.accountLinkChanged()
        #expect(!rig.activity.held && rig.activity.ends == 1, "ended at sign-out")

        rig.target.isAccountLinked = true
        rig.source.accountLinkChanged()
        rig.source.stop()
        #expect(!rig.activity.held && rig.monitor.isStopped)
    }

    @Test("021-FR-006 an open task's detail is read again on every 15 s tick while signed in, and not otherwise")
    func openTaskDetailRefreshesOnTicks() async {
        let rig = Rig()
        await rig.source.start()
        rig.source.setOpenTask("task-1")
        #expect(rig.scheduler.pendingDelays.isEmpty, "account-less: no tick")

        rig.target.isAccountLinked = true
        rig.source.accountLinkChanged()
        #expect(rig.scheduler.pendingDelays == [.seconds(SyncTiming.periodicTick)])
        rig.target.clear()
        await rig.scheduler.runNext()
        await rig.scheduler.runNext()
        #expect(rig.target.calls == ["refreshTaskDetails(task-1)", "refreshTaskDetails(task-1)"])

        rig.source.setOpenTask(nil)
        rig.target.clear()
        await rig.scheduler.runAll()
        #expect(rig.target.calls.isEmpty, "no task open: nothing read")
    }
}
