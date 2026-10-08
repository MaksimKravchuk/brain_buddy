import BrainBuddyCore
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation

/// What `SyncTriggerSource` drives: the workspace, and the engine for the one trigger the workspace
/// has no call for (`.foreground` when the window becomes visible again). `WorkspaceHost` is the app's.
@MainActor
package protocol SyncTriggerTarget: AnyObject {
    var isAccountLinked: Bool { get }
    func reloadIfChangedExternally() async
    func setForegroundActive(_ active: Bool) async
    /// `.foreground`: one forced pull.
    func requestForegroundPull() async
    func networkAvailabilityChanged(isAvailable: Bool)
    /// `.manual`, single-flight.
    func syncNow() async
    func flush() async
    func refreshTaskDetails(_ id: TaskID) async
}

/// The network path, as `NWPathMonitor` reports it (`SyncTriggerSource+Live.swift`); tests fake it.
package protocol NetworkPathMonitoring: AnyObject, Sendable {
    /// Starts reporting: `satisfied` once at the start, then on every change.
    func start(_ report: @escaping @Sendable (_ satisfied: Bool) -> Void)
    func stop()
}

/// The `ProcessInfo` activity that keeps App Nap from stretching the 15 s tick while an account is
/// linked (FR-006; review c2, G07, G64).
@MainActor
package protocol SyncActivityHolding: AnyObject {
    func begin()
    func end()
}

/// What the app tells the source: `NSApplication` and main-window notifications.
package enum AppLifecycleEvent: Hashable, Sendable {
    /// `NSApplication.didBecomeActiveNotification`.
    case didBecomeActive
    /// The main window's occlusion state turned visible (`NSWindow.didChangeOcclusionStateNotification`).
    case windowBecameVisible
    /// `NSApplication.willResignActiveNotification`.
    case willResignActive
    /// `NSApplication.willTerminateNotification` (or `applicationShouldTerminate`).
    case willTerminate
}

/// The Mac's sync triggers, the table of contracts/mac-app-host.md §5 (FR-006), with no AppKit:
///
/// | event | call |
/// |---|---|
/// | launch (`start()`) | the path monitor starts; `setForegroundActive(true)`: the kit ticker on for the life of the process, one pull |
/// | activation | `reloadIfChangedExternally()`, then `setForegroundActive(true)`, one forced pull |
/// | the window visible again | `.foreground` |
/// | network back / gone | `networkAvailabilityChanged(true / false)`, on changes only |
/// | File › "Sync now", popover "Sync now", "Retry" | `syncNow()` |
/// | resign, terminate | `flush()` |
///
/// Local changes reach the engine through the kit's own 2 s debounce. While an account is linked
/// the App Nap activity is held; account-less, none. An open task's detail is read again on every
/// 15 s tick (`refreshTaskDetails`), because a subtask or comment written elsewhere reaches this
/// Mac only that way (merged PR-05 rule). Every trigger reaches the engine, which sends nothing
/// without an account except a pending logout (FR-029).
@MainActor
package final class SyncTriggerSource {
    private let target: any SyncTriggerTarget
    private let pathMonitor: any NetworkPathMonitoring
    private let activity: any SyncActivityHolding
    private let log: any MacLogSink
    private var detailTicker: PeriodicSyncTicker?
    private var started = false
    private var foregroundActivated = false
    /// What the engine was last told (the workspace assumes a network at launch).
    private var networkReported = true
    package private(set) var holdsActivity = false
    package private(set) var openTaskID: TaskID?

    package init(
        target: any SyncTriggerTarget, pathMonitor: any NetworkPathMonitoring, activity: any SyncActivityHolding,
        detailScheduler: any SyncScheduler = TaskSyncScheduler(), log: any MacLogSink = SystemMacLog()
    ) {
        self.target = target
        self.pathMonitor = pathMonitor
        self.activity = activity
        self.log = log
        detailTicker = PeriodicSyncTicker(scheduler: detailScheduler) { [weak self] in await self?.detailTick() }
    }

    /// Launch step 6, after `workspace.load()`.
    package func start() async {
        guard !started else { return }
        started = true
        pathMonitor.start { [weak self] satisfied in
            Task { @MainActor in self?.pathChanged(satisfied: satisfied) }
        }
        foregroundActivated = true
        await target.setForegroundActive(true)
        accountLinkChanged()
        log.log(.sync, "triggers started")
    }

    package func handle(_ event: AppLifecycleEvent) async {
        switch event {
        case .didBecomeActive:
            await target.reloadIfChangedExternally()
            if foregroundActivated {
                // The kit's ticker already runs for the life of the process: only the forced pull.
                await target.requestForegroundPull()
            } else {
                foregroundActivated = true
                await target.setForegroundActive(true)
            }
        case .windowBecameVisible:
            await target.requestForegroundPull()
        case .willResignActive, .willTerminate:
            await target.flush()
        }
        accountLinkChanged()
    }

    /// File › "Sync now" ⌘R, X-02 "Sync now" and X-01 "Retry": single-flight in the kit.
    package func syncNowRequested() async {
        await target.syncNow()
    }

    /// The path monitor's report: only a change reaches the engine (a repeated "satisfied" would
    /// otherwise force a pull).
    package func pathChanged(satisfied: Bool) {
        guard satisfied != networkReported else { return }
        networkReported = satisfied
        target.networkAvailabilityChanged(isAvailable: satisfied)
    }

    /// Holds the App Nap activity exactly while an account is linked: called after start, every
    /// event, a sign-in and a sign-out.
    package func accountLinkChanged() {
        let linked = target.isAccountLinked
        guard linked != holdsActivity else {
            updateDetailTicker()
            return
        }
        holdsActivity = linked
        if linked { activity.begin() } else { activity.end() }
        log.log(.sync, "app nap activity held=\(linked)")
        updateDetailTicker()
    }

    /// The task whose detail is open, or nil.
    package func setOpenTask(_ id: TaskID?) {
        openTaskID = id
        updateDetailTicker()
    }

    private func updateDetailTicker() {
        detailTicker?.setActive(openTaskID != nil && holdsActivity)
    }

    private func detailTick() async {
        guard let id = openTaskID, target.isAccountLinked else { return }
        await target.refreshTaskDetails(id)
    }

    /// Process exit: the path monitor stops; the activity ends with the process.
    package func stop() {
        pathMonitor.stop()
        detailTicker?.setActive(false)
        if holdsActivity {
            holdsActivity = false
            activity.end()
        }
    }
}

extension WorkspaceHost: SyncTriggerTarget {
    package var isAccountLinked: Bool { workspace.account != nil }
    package func reloadIfChangedExternally() async { await workspace.reloadIfChangedExternally() }
    package func setForegroundActive(_ active: Bool) async { await workspace.setForegroundActive(active) }
    package func requestForegroundPull() async { await engine.request(.foreground) }
    package func networkAvailabilityChanged(isAvailable: Bool) { workspace.networkAvailabilityChanged(isAvailable: isAvailable) }
    package func syncNow() async { await workspace.syncNow() }
    package func flush() async { await workspace.flush() }
    package func refreshTaskDetails(_ id: TaskID) async { await workspace.refreshTaskDetails(id) }
}
