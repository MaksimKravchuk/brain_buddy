import AppKit
import BrainBuddyMacCore
import Foundation
import Network
import Synchronization

/// `NWPathMonitor` for `SyncTriggerSource` (contracts/mac-app-host.md §5): satisfied or not, once at
/// the start and on every change, on a queue of its own.
final class LivePathMonitor: NetworkPathMonitoring {
    private let monitor = Mutex(NWPathMonitor())
    private let queue = DispatchQueue(label: "com.brainbuddy.mac.path-monitor")

    func start(_ report: @escaping @Sendable (Bool) -> Void) {
        let queue = queue
        monitor.withLock { monitor in
            monitor.pathUpdateHandler = { path in report(path.status == .satisfied) }
            monitor.start(queue: queue)
        }
    }

    func stop() { monitor.withLock { $0.cancel() } }
}

/// The App Nap activity held while an account is linked (FR-006; review c2, G07, G64): it keeps
/// macOS from stretching the 15 s tick while the window is hidden or covered. Idle ticks send
/// nothing, and a full pull runs at most every 30 s.
@MainActor
final class ProcessSyncActivity: SyncActivityHolding {
    static let reason = "Keeping Brain Buddy in sync"
    private var token: (any NSObjectProtocol)?

    func begin() {
        guard token == nil else { return }
        token = ProcessInfo.processInfo.beginActivity(options: .userInitiatedAllowingIdleSystemSleep, reason: Self.reason)
    }

    func end() {
        guard let token else { return }
        ProcessInfo.processInfo.endActivity(token)
        self.token = nil
    }
}

/// Launch step 6 and the app's notifications (contracts/mac-app-host.md §1, §5): builds the trigger
/// source over the host, starts it once the workspace is loaded and readable, and forwards
/// `NSApplication` activation, resignation and termination and the main window's occlusion turning
/// visible.
@MainActor
final class MacSyncRuntime {
    let triggers: SyncTriggerSource
    private var observers: [any NSObjectProtocol] = []
    private var started = false

    init(host: WorkspaceHost, controller: MacSyncController) {
        triggers = SyncTriggerSource(target: host, pathMonitor: LivePathMonitor(), activity: ProcessSyncActivity())
        controller.triggers = triggers
    }

    func start() async {
        guard !started else { return }
        started = true
        let center = NotificationCenter.default
        let triggers = triggers
        observers = [
            center.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
                Task { @MainActor in await triggers.handle(.didBecomeActive) }
            },
            center.addObserver(forName: NSApplication.willResignActiveNotification, object: nil, queue: .main) { _ in
                Task { @MainActor in await triggers.handle(.willResignActive) }
            },
            center.addObserver(forName: NSWindow.didChangeOcclusionStateNotification, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in await self?.occlusionChanged() }
            },
        ]
        await triggers.start()
    }

    /// Whether a window of ours (not the quick-capture panel or a popover) is visible on screen.
    private var windowVisible = true

    /// `.foreground` once the window turns visible again after being hidden or fully covered.
    private func occlusionChanged() async {
        let visible = NSApp.windows.contains { !($0 is NSPanel) && $0.isVisible && $0.occlusionState.contains(.visible) }
        let becameVisible = visible && !windowVisible
        windowVisible = visible
        if becameVisible { await triggers.handle(.windowBecameVisible) }
    }

    /// `applicationShouldTerminate`: what was typed is on disk, and a confirmed sign-out's data is
    /// removed, before the process ends.
    func terminate() async {
        await triggers.handle(.willTerminate)
        triggers.stop()
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers = []
    }

    /// The one runtime of the process, for the application delegate.
    static var current: MacSyncRuntime?
}

/// Termination waits for the workspace's last write (`flush()`) and a confirmed sign-out's local
/// removal (`SyncTriggerSource`, `.willTerminate`), then quits.
final class MacAppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let runtime = MacSyncRuntime.current else { return .terminateNow }
        Task { @MainActor in
            await runtime.terminate()
            sender.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
}
