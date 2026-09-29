import BrainBuddyCore
import Foundation
import Observation
import SwiftUI

/// The tabs of the root `TabView`. Search uses `Tab(role: .search)`.
enum AppTab: String, Hashable, CaseIterable {
    case inbox, next, today, lists, search
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

/// Where a capture started, so the sheet can preselect the list and apply the
/// project or tag of the screen it was opened from.
struct CaptureContext: Identifiable, Hashable {
    var id = UUID()
    var list: OpenList = .inbox
    var projectID: ProjectID? = nil
    var tagID: TagID? = nil
}

/// Navigation state for the whole app: the selected tab, one navigation path
/// per tab, and the app-level presentations (capture sheet, Process inbox).
@MainActor
@Observable
final class AppRouter {
    var selectedTab: AppTab = .inbox
    var paths: [AppTab: NavigationPath] = AppRouter.emptyPaths()
    /// Non-nil while the capture sheet is shown.
    var capture: CaptureContext?
    /// True while Process inbox is shown full screen.
    var isProcessingInbox = false

    init() {}

    /// Pushes `route` onto the selected tab's navigation stack.
    func open(_ route: AppRoute) {
        paths[selectedTab, default: NavigationPath()].append(route)
    }

    func presentCapture(_ context: CaptureContext = CaptureContext()) {
        capture = context
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

    /// The capture context the capture bar uses on the selected tab: Next
    /// captures into Next actions, every other tab into Inbox.
    var captureContextForSelectedTab: CaptureContext {
        selectedTab == .next ? CaptureContext(list: .next) : CaptureContext()
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
            isProcessingInbox = false
            // Keep a capture that is already open rather than replacing its draft.
            if capture == nil { presentCapture(context) }
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

    private func dismissPresentations() {
        capture = nil
        isProcessingInbox = false
    }

    nonisolated private static func emptyPaths() -> [AppTab: NavigationPath] {
        var paths: [AppTab: NavigationPath] = [:]
        for tab in AppTab.allCases { paths[tab] = NavigationPath() }
        return paths
    }
}
