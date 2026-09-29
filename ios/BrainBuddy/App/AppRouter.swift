import BrainBuddyCore
import Foundation
import Observation
import SwiftUI

/// The tabs of the root `TabView`. Search uses `Tab(role: .search)`.
enum AppTab: String, Hashable, CaseIterable {
    case inbox, next, today, lists, search
}

private struct AppTabKey: EnvironmentKey {
    static let defaultValue: AppTab? = nil
}

extension EnvironmentValues {
    /// The tab a screen is shown in (nil outside the tab view), so it can
    /// publish its capture context to the router.
    var appTab: AppTab? {
        get { self[AppTabKey.self] }
        set { self[AppTabKey.self] = newValue }
    }
}

/// Every screen that can be pushed onto a tab's navigation stack.
enum AppRoute: Hashable {
    case task(TaskID)
    case destination(Destination)
    case projects
    case archivedProjects
    case tags
    case settings
    case syncIssues
}

/// Where a capture started, so the sheet can preselect the list and due date
/// and apply the project or tag of the screen it was opened from.
struct CaptureContext: Identifiable, Hashable {
    var id = UUID()
    var list: OpenList = .inbox
    var projectID: ProjectID? = nil
    var tagID: TagID? = nil
    var dueDate: CalendarDay? = nil
}

/// Navigation state for one window: the selected tab, one navigation path per
/// tab, and the window's presentations (capture sheet, Process inbox).
@MainActor
@Observable
final class AppRouter {
    var selectedTab: AppTab = .inbox
    var paths: [AppTab: NavigationPath] = AppRouter.emptyPaths()
    /// Non-nil while the capture sheet is shown.
    var capture: CaptureContext?
    /// True while Process inbox is shown full screen.
    var isProcessingInbox = false
    /// A capture asked for while Process inbox was open; shown once the
    /// cover has gone (`presentPendingCapture()`), since a sheet can't be
    /// presented from under a full-screen cover.
    @ObservationIgnored private var pendingCapture: CaptureContext?
    /// The capture context of the list screen on top of each tab, published
    /// by `TaskListScreen`, so the capture bar and ⌘N file into the project,
    /// tag or list you are looking at.
    private var screenCaptures: [AppTab: ScreenCapture] = [:]

    private struct ScreenCapture {
        let destination: Destination
        /// Nil for a screen that files nothing (history, dates, an archived
        /// project): capture uses the tab's default there.
        let context: CaptureContext?
    }

    init() {}

    /// Pushes `route` onto the selected tab's navigation stack.
    func open(_ route: AppRoute) {
        paths[selectedTab, default: NavigationPath()].append(route)
    }

    /// Opens capture. An open capture keeps its draft rather than being
    /// replaced, and Process inbox closes first.
    func presentCapture(_ context: CaptureContext = CaptureContext()) {
        guard capture == nil else { return }
        if isProcessingInbox {
            pendingCapture = context
            isProcessingInbox = false
            return
        }
        capture = context
    }

    /// Shows a capture asked for while Process inbox was open. Call from the
    /// cover's `onDismiss`.
    func presentPendingCapture() {
        guard let pending = pendingCapture else { return }
        pendingCapture = nil
        if capture == nil { capture = pending }
    }

    /// Called by a list screen when it appears on `tab` (and when what it
    /// files into changes).
    func publishCaptureContext(_ context: CaptureContext?, for destination: Destination, on tab: AppTab) {
        screenCaptures[tab] = ScreenCapture(destination: destination, context: context)
    }

    /// Called by a list screen when it leaves `tab`. Ignored when another
    /// screen has published since, whichever order the two events arrive in.
    func withdrawCaptureContext(for destination: Destination, on tab: AppTab) {
        guard screenCaptures[tab]?.destination == destination else { return }
        screenCaptures[tab] = nil
    }

    func popToRoot(_ tab: AppTab) {
        paths[tab] = NavigationPath()
    }

    /// A binding to `tab`'s navigation path, for `NavigationStack(path:)`.
    func path(for tab: AppTab) -> Binding<NavigationPath> {
        Binding(
            get: { self.paths[tab] ?? NavigationPath() },
            set: { self.paths[tab] = $0 }
        )
    }

    /// The capture context the capture bar and ⌘N use on the selected tab:
    /// the list, project or tag screen on top when it files somewhere,
    /// otherwise Next actions on the Next tab and Inbox everywhere else.
    var captureContextForSelectedTab: CaptureContext {
        if var context = screenCaptures[selectedTab]?.context {
            context.id = UUID()
            return context
        }
        return selectedTab == .next ? CaptureContext(list: .next) : CaptureContext()
    }

    /// Handles `brainbuddy://` URLs:
    /// - `capture` (optionally `?list=inbox|next|waiting|someday`) opens capture,
    /// - `task/<id>` opens a task on the selected tab,
    /// - `inbox`, `next`, `today`, `lists`, `search` select that tab.
    /// Returns false for URLs the app does not understand.
    @discardableResult
    func handle(_ url: URL) -> Bool {
        guard let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
            components.scheme?.lowercased() == AppConstants.urlScheme,
            let host = components.host?.lowercased()
        else { return false }

        switch host {
        case "capture":
            var context = CaptureContext()
            if let raw = components.queryItems?.first(where: { $0.name == "list" })?.value,
                let list = OpenList(rawValue: raw.lowercased())
            {
                context.list = list
            }
            // Closes Process inbox first and keeps a capture that is
            // already open rather than replacing its draft.
            presentCapture(context)
            return true
        case "task":
            let rawID = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            guard !rawID.isEmpty else { return false }
            dismissPresentations()
            open(.task(TaskID(rawID)))
            return true
        default:
            guard let tab = AppTab(rawValue: host) else { return false }
            dismissPresentations()
            selectedTab = tab
            return true
        }
    }

    /// Closes Process inbox so the destination shows. An open capture stays
    /// open with its draft; the navigation happens underneath it.
    private func dismissPresentations() {
        isProcessingInbox = false
    }

    nonisolated private static func emptyPaths() -> [AppTab: NavigationPath] {
        var paths: [AppTab: NavigationPath] = [:]
        for tab in AppTab.allCases { paths[tab] = NavigationPath() }
        return paths
    }
}
