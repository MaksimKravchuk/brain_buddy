import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// The app's root: a quiet loading state, a recovery screen when the stored
/// file cannot be read, and otherwise the tab view.
struct RootView: View {
    @Environment(Workspace.self) private var workspace

    var body: some View {
        if let message = workspace.loadError {
            LoadErrorView(message: message)
        } else if workspace.isLoaded {
            MainTabView()
        } else {
            LoadingView()
        }
    }
}

// MARK: - Tabs

/// Inbox, Next actions, Today, Lists and Search, with the capture bar in the
/// tab view's bottom accessory (and at the bottom of the iPad sidebar, where
/// the accessory is not shown). Glass comes from the system chrome (tab bar,
/// accessory, sidebar, navigation bars); the screens themselves stay flat.
///
/// The capture sheet and Process inbox host their own toasts, next to their
/// bottom buttons, so an Undo never covers the controls.
private struct MainTabView: View {
    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router
    @Environment(ToastCenter.self) private var toasts

    var body: some View {
        @Bindable var router = router
        TabView(selection: $router.selectedTab) {
            Tab(AppTab.inbox.title, systemImage: AppTab.inbox.symbolName, value: AppTab.inbox) {
                TabRootView(tab: .inbox)
            }
            .badge(workspace.counts().inbox)

            Tab(AppTab.next.title, systemImage: AppTab.next.symbolName, value: AppTab.next) {
                TabRootView(tab: .next)
            }

            Tab(AppTab.today.title, systemImage: AppTab.today.symbolName, value: AppTab.today) {
                TabRootView(tab: .today)
            }

            Tab(AppTab.lists.title, systemImage: AppTab.lists.symbolName, value: AppTab.lists) {
                TabRootView(tab: .lists)
            }

            Tab(value: AppTab.search, role: .search) {
                TabRootView(tab: .search)
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .tabBarMinimizeBehavior(.onScrollDown)
        .tabViewBottomAccessory {
            CaptureAccessory()
        }
        .tabViewSidebarBottomBar {
            CaptureAccessory(drawsGlass: true)
        }
        .sheet(item: $router.capture) { context in
            CaptureSheet(context: context)
        }
        // A capture asked for while Process inbox was open (⌘N, a deep link)
        // shows once the cover has gone.
        .fullScreenCover(isPresented: $router.isProcessingInbox, onDismiss: { router.presentPendingCapture() }) {
            ProcessInboxScreen()
        }
        // Changes stay on screen and are retried with the next save; say so
        // when a save fails instead of pretending it worked.
        .onChange(of: workspace.storageError) { _, problem in
            if let problem { toasts.showError(problem) }
        }
    }
}

/// One tab: its navigation stack, the shared route table, and the toast host.
/// The toast overlay sits inside the tab so the tab bar and the capture
/// accessory are part of its safe area and toasts float just above them.
private struct TabRootView: View {
    let tab: AppTab
    @Environment(AppRouter.self) private var router

    var body: some View {
        NavigationStack(path: router.path(for: tab)) {
            TabRootScreen(tab: tab)
                .toastMagicTap()
                .navigationDestination(for: AppRoute.self) { route in
                    AppRouteView(route: route)
                        .toastMagicTap()
                }
        }
        .environment(\.appTab, tab)
        .overlay(alignment: .bottom) {
            ToastHost()
        }
    }
}

private struct TabRootScreen: View {
    let tab: AppTab

    var body: some View {
        switch tab {
        case .inbox: TaskListScreen(destination: .list(.inbox))
        case .next: TaskListScreen(destination: .list(.next))
        case .today: TodayScreen()
        case .lists: ListsHubScreen()
        case .search: SearchScreen()
        }
    }
}

// MARK: - Loading and recovery

/// Shown until the store is read. The spinner only appears if loading takes
/// long enough to notice, so a normal launch shows nothing but the page colour.
private struct LoadingView: View {
    @State private var showsIndicator = false

    var body: some View {
        ZStack {
            BBColor.surfaceBase.ignoresSafeArea()
            if showsIndicator {
                ProgressView()
                    .accessibilityLabel("Loading your tasks")
            }
        }
        .task {
            try? await Task.sleep(for: .milliseconds(400))
            showsIndicator = true
        }
    }
}

/// The stored file could not be read. The workspace never overwrites a file
/// it cannot decode, so nothing is lost; the person can retry, or deliberately
/// set the file aside and start with empty lists.
private struct LoadErrorView: View {
    let message: String
    @Environment(Workspace.self) private var workspace
    @State private var isRetrying = false
    @State private var confirmsStartFresh = false

    var body: some View {
        VStack(spacing: BBSpacing.sm) {
            EmptyStateView(
                title: "We couldn't open your tasks",
                message: "Your tasks are still on this device and nothing was changed. \(message)",
                systemImage: "exclamationmark.triangle",
                actionTitle: isRetrying ? "Trying again…" : "Try again",
                action: retry
            )
            Button("Start fresh", role: .destructive) { confirmsStartFresh = true }
                .frame(minHeight: 44)
        }
        .disabled(isRetrying)
        .bbScreenBackground()
        .confirmationDialog("Start fresh?", isPresented: $confirmsStartFresh, titleVisibility: .visible) {
            Button("Set the file aside and start fresh", role: .destructive, action: startFresh)
            Button("Keep trying", role: .cancel) {}
        } message: {
            Text("The unreadable file stays on this device, set aside where Brain Buddy won't use it. You start with empty lists; tasks you synced come back when you sign in.")
        }
    }

    private func retry() {
        guard !isRetrying else { return }
        isRetrying = true
        Task {
            await workspace.load()
            isRetrying = false
        }
    }

    private func startFresh() {
        guard !isRetrying else { return }
        isRetrying = true
        Task {
            await workspace.resetUnreadableStore()
            isRetrying = false
        }
    }
}
