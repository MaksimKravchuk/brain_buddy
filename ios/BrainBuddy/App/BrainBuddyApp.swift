import BackgroundTasks
import BrainBuddyCore
import BrainBuddyWorkspace
import CoreFoundation
import Network
import SwiftUI
import WidgetKit

@main
struct BrainBuddyApp: App {
    @State private var workspace: Workspace
    @State private var router = AppRouter()
    @State private var toasts = ToastCenter()
    @Environment(\.scenePhase) private var scenePhase

    init() {
        let usesPreviewData = ProcessInfo.processInfo.arguments.contains(AppConstants.previewDataLaunchArgument)
        let workspace = usesPreviewData
            ? Workspace.preview()
            : Workspace.live(appGroupID: AppConstants.appGroupID)
        // App Intents that run inside the app process reuse this workspace
        // instead of opening a second copy of the store (ios/Shared).
        SharedWorkspace.adopt(workspace)
        _workspace = State(initialValue: workspace)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .modifier(WidgetReloadAfterSync())
                .environment(workspace)
                .environment(router)
                .environment(toasts)
                .tint(BBColor.brand)
                .task { await loadIfNeeded() }
                .task { await observeExternalWrites() }
                .task { await observeNetwork() }
                .onChange(of: scenePhase) { _, phase in
                    scenePhaseChanged(to: phase)
                }
                .onOpenURL { url in
                    router.handle(url)
                }
        }
        .backgroundTask(.appRefresh(AppConstants.backgroundRefreshTaskID)) { [workspace] in
            await BackgroundRefresh.run(workspace)
        }
        .commands {
            CaptureCommands(router: router)
        }
    }

    // MARK: Lifecycle

    private func loadIfNeeded() async {
        guard !workspace.isLoaded else { return }
        await workspace.load()
    }

    private func scenePhaseChanged(to phase: ScenePhase) {
        switch phase {
        case .active:
            Task {
                if workspace.isLoaded {
                    await workspace.reloadIfChangedExternally()
                    // Sync on foreground (docs: "on launch and foreground").
                    if workspace.account != nil { await workspace.syncNow() }
                }
                WidgetCenter.shared.reloadAllTimelines()
            }
        case .background:
            Task {
                await workspace.flush()
                WidgetCenter.shared.reloadAllTimelines()
                BackgroundRefresh.schedule(for: workspace)
            }
        default:
            break
        }
    }

    /// Widgets and App Intents write the shared file from other processes and
    /// post a Darwin notification; pick their changes up at once.
    private func observeExternalWrites() async {
        for await _ in SystemEvents.darwinNotifications(named: AppConstants.storeChangedNotification) {
            guard workspace.isLoaded else { continue }
            await workspace.reloadIfChangedExternally()
        }
    }

    private func observeNetwork() async {
        for await isAvailable in SystemEvents.networkAvailability() {
            workspace.networkAvailabilityChanged(isAvailable: isAvailable)
        }
    }
}

/// Reloads widget timelines when a sync finishes, once the result is on disk
/// (widgets read the shared file, not this process's memory).
private struct WidgetReloadAfterSync: ViewModifier {
    @Environment(Workspace.self) private var workspace

    func body(content: Content) -> some View {
        content.onChange(of: workspace.syncStatus) { previous, current in
            guard previous == .syncing, current != .syncing else { return }
            Task {
                await workspace.flush()
                WidgetCenter.shared.reloadAllTimelines()
            }
        }
    }
}

// MARK: - Background refresh

/// Opportunistic sync via `BGAppRefreshTask`. The identifier must be listed in
/// Info.plist `BGTaskSchedulerPermittedIdentifiers`, with the `fetch`
/// background mode enabled.
@MainActor
enum BackgroundRefresh {
    /// Runs one refresh and asks for the next one.
    static func run(_ workspace: Workspace) async {
        if !workspace.isLoaded { await workspace.load() }
        await workspace.syncNow()
        await workspace.flush()
        WidgetCenter.shared.reloadAllTimelines()
        schedule(for: workspace)
    }

    /// Asks the system for a refresh in about 30 minutes. Only signed-in
    /// devices have anything to sync, so local-only devices never wake up.
    static func schedule(for workspace: Workspace) {
        guard workspace.account != nil else { return }
        let request = BGAppRefreshTaskRequest(identifier: AppConstants.backgroundRefreshTaskID)
        request.earliestBeginDate = Date(timeIntervalSinceNow: 30 * 60)
        do {
            try BGTaskScheduler.shared.submit(request)
        } catch {
            // Unavailable in the Simulator and when Background App Refresh is
            // off; foreground sync still covers everything.
        }
    }
}

// MARK: - Commands

/// Keyboard and menu-bar capture (iPad), which also covers the sidebar layout
/// where the tab view's bottom accessory is not shown.
private struct CaptureCommands: Commands {
    let router: AppRouter

    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button("Capture a task…") {
                router.presentCapture(router.captureContextForSelectedTab)
            }
            .keyboardShortcut("n", modifiers: .command)
        }
    }
}

// MARK: - System event streams

enum SystemEvents {
    /// Yields once per Darwin notification named `name`, until the consuming
    /// task is cancelled.
    static func darwinNotifications(named name: String) -> AsyncStream<Void> {
        AsyncStream(bufferingPolicy: .bufferingNewest(1)) { continuation in
            let box = DarwinObserverBox(continuation: continuation)
            CFNotificationCenterAddObserver(
                CFNotificationCenterGetDarwinNotifyCenter(),
                Unmanaged.passUnretained(box).toOpaque(),
                { _, observer, _, _, _ in
                    guard let observer else { return }
                    Unmanaged<DarwinObserverBox>.fromOpaque(observer).takeUnretainedValue().continuation.yield()
                },
                name as CFString,
                nil,
                .deliverImmediately
            )
            // The termination handler keeps `box` alive until the stream ends,
            // then unregisters it.
            continuation.onTermination = { _ in
                CFNotificationCenterRemoveObserver(
                    CFNotificationCenterGetDarwinNotifyCenter(),
                    Unmanaged.passUnretained(box).toOpaque(),
                    CFNotificationName(name as CFString),
                    nil
                )
            }
        }
    }

    /// Yields whether a network path is available: once at start, then on
    /// every path change, until the consuming task is cancelled.
    static func networkAvailability() -> AsyncStream<Bool> {
        AsyncStream(bufferingPolicy: .bufferingNewest(1)) { continuation in
            let box = PathMonitorBox()
            box.monitor.pathUpdateHandler = { path in
                continuation.yield(path.status == .satisfied)
            }
            continuation.onTermination = { _ in
                box.monitor.cancel()
            }
            box.monitor.start(queue: DispatchQueue(label: "com.brainbuddy.ios.network-path"))
        }
    }
}

private final class DarwinObserverBox: Sendable {
    let continuation: AsyncStream<Void>.Continuation

    init(continuation: AsyncStream<Void>.Continuation) {
        self.continuation = continuation
    }
}

/// `NWPathMonitor` is thread-safe; the box lets the stream's `@Sendable`
/// termination handler reference it whatever the SDK's annotations say.
private final class PathMonitorBox: @unchecked Sendable {
    let monitor = NWPathMonitor()
}
