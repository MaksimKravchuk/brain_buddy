import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Whether the weekly review is shown (spec 020, contracts/ios-commands.md
/// §8). Signed in, the workspace answers it from the account's
/// `weekly_review` flag: `GET /review/state` answers only while the flag is
/// effective (`Workspace.reviewExposed`). Account-less, it is the build's
/// release switch, the Info.plist key `BBWeeklyReviewLocal` from
/// `ios/project.yml`: YES in Debug, NO in Release until the owner turns it on
/// (account-less parks have no server and no remote kill switch). While the
/// review is not exposed nothing of it shows and Lists keeps its "coming
/// later" row.
enum ReviewExposure {
    static let accountlessInfoKey = "BBWeeklyReviewLocal"

    /// The account-less release switch; NO when the key is missing.
    static var accountlessReleaseSwitch: Bool {
        let value = Bundle.main.object(forInfoDictionaryKey: accountlessInfoKey)
        if let flag = value as? Bool { return flag }
        // A `$(SETTING)` in the plist arrives as the string "YES" or "NO".
        if let text = value as? String {
            return ["yes", "true", "1"].contains(text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
        }
        return false
    }
}

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
///
/// Weekly review (spec 020): at app open, before anything else, the auto-park
/// explainer (M-26) while it is needed, then "While you were away" (M-09)
/// when unseen parks exist and it was not shown today. A capture asked for
/// meanwhile (a deep link, ⌘N) waits until they close.
private struct MainTabView: View {
    @Environment(Workspace.self) private var workspace
    @Environment(AppRouter.self) private var router
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.scenePhase) private var scenePhase
    @State private var startupSheet: ReviewStartupSheet?

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
        // A capture waits while a review startup sheet is up, then shows.
        .sheet(
            item: Binding(
                get: { startupSheet == nil ? self.router.capture : nil },
                set: { self.router.capture = $0 }
            )
        ) { context in
            CaptureSheet(context: context)
        }
        .sheet(item: $startupSheet, onDismiss: startupSheetDismissed) { sheet in
            switch sheet {
            case .explainer: AutoParkExplainerSheet()
            case .whileAway: WhileYouWereAwaySheet()
            }
        }
        .task { presentStartupSheetIfDue() }
        .onChange(of: workspace.reviewExposed) { _, _ in presentStartupSheetIfDue() }
        .onChange(of: workspace.explainerNeeded) { _, _ in presentStartupSheetIfDue() }
        .onChange(of: workspace.unseenParks().count) { _, _ in presentStartupSheetIfDue() }
        .onChange(of: router.capture == nil) { _, _ in presentStartupSheetIfDue() }
        .onChange(of: router.isProcessingInbox) { _, _ in presentStartupSheetIfDue() }
        .onChange(of: scenePhase) { _, phase in
            if phase == .active { presentStartupSheetIfDue() }
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

    // MARK: Review startup sheets (M-26, M-09)

    /// Presents the explainer while it is needed (FR-051), otherwise "While
    /// you were away" once a calendar day while parks are unseen (FR-015),
    /// never over a capture or Process inbox.
    private func presentStartupSheetIfDue() {
        guard startupSheet == nil, router.capture == nil, !router.isProcessingInbox, workspace.isLoaded,
            workspace.reviewExposed
        else { return }
        if workspace.explainerNeeded {
            startupSheet = .explainer
        } else if workspace.whileAwayShouldShowAtAppOpen() {
            // Shown today, whether it is continued or swiped away.
            workspace.markWhileAwayShown()
            startupSheet = .whileAway
        }
    }

    private func startupSheetDismissed() {
        // The sheet appeared without a tap: VoiceOver goes back to the
        // screen, starting at its navigation title (design "Keyboard and focus").
        UIAccessibility.post(notification: .screenChanged, argument: nil)
        presentStartupSheetIfDue()
    }
}

/// A sheet the weekly review shows at app open, in this order.
private enum ReviewStartupSheet: String, Identifiable {
    /// M-26.
    case explainer
    /// M-09.
    case whileAway

    var id: String { rawValue }
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
