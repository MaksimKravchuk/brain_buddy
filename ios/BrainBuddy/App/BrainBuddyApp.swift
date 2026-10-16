import BackgroundTasks
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import Combine
import CoreFoundation
import Network
import SwiftUI
import UIKit
import WidgetKit

@main
struct BrainBuddyApp: App {
    /// One workspace for the process; navigation and toasts are per window
    /// (`SceneRoot`), so two iPad windows don't drive each other.
    @State private var workspace: Workspace
    /// Beta performance diagnostics; nil when the build turns them off.
    @State private var diagnostics: PerformanceDiagnostics?
    /// The one-time first run (boards 01 to 04), decided by `RootView` once the store is read.
    @State private var firstRun: PhoneFirstRunFlow
    /// Whether this launch resolves the runtime (spec 026, T044): the install has a persisted
    /// selection, or the local pilot switch is on. Otherwise nothing below runs and the app is
    /// exactly the legacy app.
    private let resolvesRuntime: Bool
    @Environment(\.scenePhase) private var scenePhase

    init() {
        // Registers the bundled Instrument faces before the first view asks for one.
        CarryOnFonts.register()
        BBNavigationBarAppearance.apply()
        let usesPreviewData = ProcessInfo.processInfo.arguments.contains(AppConstants.previewDataLaunchArgument)
        let location = RustRuntimeLocation.appGroup(AppConstants.appGroupID)
        // An unreadable selection counts: the install must not fall back to the retired file.
        let selection: Bool
        do {
            selection = try RustRuntimeSelectionStore(location: location).load() != nil
        } catch {
            selection = true
        }
        let resolves = !usesPreviewData && (selection || RustRuntimePilotSwitch().isEnabled)
        resolvesRuntime = resolves
        let workspace = usesPreviewData
            ? Workspace.preview()
            : selection && resolves ? Workspace.pending() : Workspace.live(appGroupID: AppConstants.appGroupID)
        // The weekly review's account-less release switch (spec 020), set
        // before the first load so load-time upkeep sees it.
        workspace.accountlessReviewEnabled = ReviewExposure.accountlessReleaseSwitch
        // App Intents that run inside the app process reuse this workspace
        // instead of opening a second copy of the store (ios/Shared).
        SharedWorkspace.adopt(workspace)
        // Widgets show the store, so every saved change refreshes them.
        workspace.didPersist = { WidgetCenter.shared.reloadAllTimelines() }
        _workspace = State(initialValue: workspace)
        _diagnostics = State(initialValue: PerformanceDiagnostics.live())
        _firstRun = State(initialValue: PhoneFirstRunFlow(store: UserDefaultsPhoneFirstRunRecordStore()))
    }

    var body: some Scene {
        WindowGroup {
            SceneRoot()
                .modifier(WidgetReloadAfterSync())
                .environment(workspace)
                .environment(diagnostics)
                .environment(firstRun)
                .task { await diagnostics?.start() }
                .task { await start() }
                .task { await observeExternalWrites() }
                .task { await observeNetwork() }
                .onChange(of: scenePhase) { _, phase in
                    scenePhaseChanged(to: phase)
                }
        }
        .backgroundTask(.appRefresh(AppConstants.backgroundRefreshTaskID)) { [workspace] in
            await BackgroundRefresh.run(workspace)
        }
        .commands {
            CaptureCommands()
        }
    }

    // MARK: Lifecycle

    /// The runtime is resolved before the first load, so the legacy store is never read once the
    /// install has moved and the import never races a running legacy workspace.
    private func start() async {
        if resolvesRuntime { await resolveRuntime() }
        await loadIfNeeded()
    }

    private func resolveRuntime() async {
        guard !workspace.isLoaded else { return }
        let environment: RustRuntimeEnvironment
        do {
            environment = try RustRuntimeEnvironment.appGroup(
                AppConstants.appGroupID, reviewEnabled: ReviewExposure.accountlessReleaseSwitch)
        } catch {
            // The install is the Rust runtime's: never the retired file instead.
            let location = RustRuntimeLocation.appGroup(AppConstants.appGroupID)
            let hasSelection: Bool
            do {
                hasSelection = try RustRuntimeSelectionStore(location: location).load() != nil
            } catch {
                hasSelection = true
            }
            if hasSelection { replaceWorkspace(Workspace.unavailable(code: "BRIDGE_UNAVAILABLE")) }
            return
        }
        switch await RustRuntimeLauncher(environment: environment).resolve() {
        case .legacy:
            break
        case .unavailable(let code):
            replaceWorkspace(Workspace.unavailable(code: code))
        case .rust(let selection, let lifecycle):
            replaceWorkspace(Workspace.selected(selection, lifecycle: lifecycle))
        }
    }

    private func replaceWorkspace(_ next: Workspace) {
        next.accountlessReviewEnabled = ReviewExposure.accountlessReleaseSwitch
        SharedWorkspace.adopt(next)
        next.didPersist = { WidgetCenter.shared.reloadAllTimelines() }
        workspace = next
    }

    private func loadIfNeeded() async {
        guard !workspace.isLoaded else { return }
        await workspace.load()
        // Weekly review upkeep on load (spec 020, ios-commands §5): local
        // retention (`runLocalReviewMaintenance()`) and, while the review is
        // exposed, the due auto-parks (`applyDueAutoParks()`). Idempotent.
        workspace.runReviewUpkeep()
    }

    private func scenePhaseChanged(to phase: ScenePhase) {
        switch phase {
        case .active:
            diagnostics?.sceneBecameActive()
            Task {
                if workspace.isLoaded {
                    await workspace.reloadIfChangedExternally()
                    // Sync on foreground (docs: "on launch and foreground").
                    if workspace.account != nil { await workspace.syncNow() }
                    // Weekly review upkeep on foreground (spec 020).
                    workspace.runReviewUpkeep()
                }
                WidgetCenter.shared.reloadAllTimelines()
            }
        case .background:
            diagnostics?.sceneEnteredBackground()
            Task {
                await workspace.flush()
                // A selected runtime stops polling and closes its hint stream until the next
                // foreground; the legacy engine ignores it.
                await workspace.enterBackground()
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

/// One window's root: its own navigation state and toasts, so on iPad each
/// window keeps its tab, stack, capture sheet and Undo to itself. Deep links
/// and ⌘N act on the window they reach.
private struct SceneRoot: View {
    @State private var router = AppRouter()
    @State private var toasts = ToastCenter()
    @State private var accounts = AccountModels()

    var body: some View {
        let router = router
        RootView()
            .environment(router)
            .environment(toasts)
            .environment(accounts)
            .tint(BBColor.brandText)
            .modifier(DayChangeObserver())
            .focusedSceneValue(
                \.captureAction,
                CaptureAction {
                    router.presentCapture(router.captureContextForSelectedTab)
                }
            )
            .onOpenURL { url in
                router.handle(url)
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
        // Weekly review upkeep on background refresh (spec 020): retention
        // and due auto-parks, written with the flush below.
        workspace.runReviewUpkeep()
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

/// Keyboard and menu-bar capture (iPad). It captures in the window that has
/// focus, through the action that window publishes (`SceneRoot`).
private struct CaptureCommands: Commands {
    @FocusedValue(\.captureAction) private var captureAction

    var body: some Commands {
        CommandGroup(after: .newItem) {
            Button("Capture a task…") {
                captureAction?.run()
            }
            .keyboardShortcut("n", modifiers: .command)
            .disabled(captureAction == nil)
        }
    }
}

/// Opens capture in the window that publishes it.
struct CaptureAction {
    let run: @MainActor () -> Void

    init(_ run: @escaping @MainActor () -> Void) {
        self.run = run
    }
}

private struct CaptureActionKey: FocusedValueKey {
    typealias Value = CaptureAction
}

extension FocusedValues {
    /// The focused window's capture action, for ⌘N.
    var captureAction: CaptureAction? {
        get { self[CaptureActionKey.self] }
        set { self[CaptureActionKey.self] = newValue }
    }
}

// MARK: - Day changes

/// Bumps `dayChangeCount` at midnight and whenever the clock or time zone
/// changes, so date views (Today, Overdue, due chips) show the new day
/// without waiting for another change to redraw them.
private struct DayChangeObserver: ViewModifier {
    @State private var count = 0

    func body(content: Content) -> some View {
        content
            .environment(\.dayChangeCount, count)
            .onReceive(Self.dayChanges) { _ in
                count &+= 1
            }
    }

    private static var dayChanges: AnyPublisher<Notification, Never> {
        NotificationCenter.default.publisher(for: UIApplication.significantTimeChangeNotification)
            .merge(with: NotificationCenter.default.publisher(for: .NSCalendarDayChanged))
            .receive(on: DispatchQueue.main)
            .eraseToAnyPublisher()
    }
}

private struct DayChangeCountKey: EnvironmentKey {
    static let defaultValue = 0
}

extension EnvironmentValues {
    /// Changes when the calendar day (or the clock) changes. Views that show
    /// dates relative to today read it so they redraw on a new day.
    var dayChangeCount: Int {
        get { self[DayChangeCountKey.self] }
        set { self[DayChangeCountKey.self] = newValue }
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
            box.monitor.start(queue: DispatchQueue(label: "brainbuddy.ios.network-path"))
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
