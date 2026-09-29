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
/// tab view's bottom accessory. Glass comes from the system chrome (tab bar,
/// accessory, navigation bars); the screens themselves stay flat.
private struct MainTabView: View {
    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router

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
        .sheet(item: $router.capture) { context in
            CaptureSheet(context: context)
                .overlay(alignment: .bottom) { ToastHost() }
        }
        .fullScreenCover(isPresented: $router.isProcessingInbox) {
            ProcessInboxScreen()
                .overlay(alignment: .bottom) { ToastHost() }
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
                .navigationDestination(for: AppRoute.self) { route in
                    AppRouteView(route: route)
                }
        }
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
/// it cannot decode, so nothing is lost; the person can retry.
private struct LoadErrorView: View {
    let message: String
    @Environment(Workspace.self) private var workspace
    @State private var isRetrying = false

    var body: some View {
        EmptyStateView(
            title: "We couldn't open your tasks",
            message: "Your tasks are still on this device and nothing was changed. \(message)",
            systemImage: "exclamationmark.triangle",
            actionTitle: isRetrying ? "Trying again…" : "Try again",
            action: retry
        )
        .disabled(isRetrying)
        .bbScreenBackground()
    }

    private func retry() {
        guard !isRetrying else { return }
        isRetrying = true
        Task {
            await workspace.load()
            isRetrying = false
        }
    }
}
