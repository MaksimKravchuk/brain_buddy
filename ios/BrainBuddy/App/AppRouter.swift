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

/// Every screen that can be pushed onto a tab's navigation stack. A task is
/// not one of them: it opens in the task sheet (`AppRouter.presentTask`).
enum AppRoute: Hashable {
    case destination(Destination)
    case projects
    case archivedProjects
    case tags
    case settings
    case syncIssues
    /// The weekly review's entry (M-11).
    case review
    /// Beta performance diagnostics (`PerformanceDiagnostics`).
    case performance
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

/// The task shown in the task sheet (boards 13 to 20).
struct PresentedTask: Identifiable, Hashable {
    let id: TaskID
}

/// Navigation state for one window: the selected tab, one navigation path per
/// tab, and the window's presentations (capture sheet, Process inbox, the
/// task sheet).
///
/// Every place that opens a task (list, Today and Search rows, the Next
/// actions card, the `brainbuddy://task/<id>` link) presents it as one half
/// sheet over the window instead of pushing it, so a task opens the same way
/// on every tab. UIKit shows one modal at a time, so a task asked for while
/// capture or Process inbox is up waits until it has gone, and a capture asked
/// for while a task is open closes the task first.
@MainActor
@Observable
final class AppRouter {
    var selectedTab: AppTab = .inbox
    var paths: [AppTab: NavigationPath] = AppRouter.emptyPaths()
    /// Non-nil while the capture sheet is shown.
    var capture: CaptureContext?
    /// True while Process inbox is shown full screen.
    var isProcessingInbox = false
    /// Non-nil while the task sheet is shown.
    var presentedTask: PresentedTask?
    /// A capture asked for while Process inbox or the task sheet was open;
    /// shown once that has gone (`presentPending()`), since UIKit presents one
    /// modal at a time.
    @ObservationIgnored private var pendingCapture: CaptureContext?
    /// A task asked for while capture or Process inbox was open; shown once
    /// that has gone (`presentPending()`).
    @ObservationIgnored private var pendingTask: PresentedTask?
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
    /// replaced, and Process inbox or the task sheet closes first.
    func presentCapture(_ context: CaptureContext = CaptureContext()) {
        guard capture == nil else { return }
        if isProcessingInbox {
            pendingCapture = context
            isProcessingInbox = false
            return
        }
        if presentedTask != nil {
            pendingCapture = context
            presentedTask = nil
            return
        }
        capture = context
    }

    /// Opens `id` in the task sheet, replacing a task already shown. While
    /// capture is open it waits for capture to close (the draft is kept);
    /// Process inbox closes first.
    func presentTask(_ id: TaskID) {
        let task = PresentedTask(id: id)
        if isProcessingInbox {
            pendingTask = task
            isProcessingInbox = false
            return
        }
        if capture != nil {
            pendingTask = task
            return
        }
        presentedTask = task
    }

    /// Closes the task sheet.
    func closeTask() {
        presentedTask = nil
    }

    /// Shows what was asked for while another modal was up: a capture first,
    /// otherwise a task. Call from the `onDismiss` of the capture sheet, the
    /// task sheet and the Process inbox cover.
    func presentPending() {
        if let pending = pendingCapture {
            guard capture == nil, presentedTask == nil, !isProcessingInbox else { return }
            pendingCapture = nil
            capture = pending
            return
        }
        if let pending = pendingTask {
            guard capture == nil, presentedTask == nil, !isProcessingInbox else { return }
            pendingTask = nil
            presentedTask = pending
        }
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
    /// - `task/<id>` opens a task in the task sheet over the selected tab,
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
            // Closes Process inbox first (the task shows once the cover has
            // gone) and waits for an open capture rather than replacing it.
            presentTask(TaskID(rawID))
            return true
        default:
            guard let tab = AppTab(rawValue: host) else { return false }
            dismissPresentations()
            selectedTab = tab
            return true
        }
    }

    /// Closes Process inbox and the task sheet so the destination shows. An
    /// open capture stays open with its draft; the navigation happens
    /// underneath it.
    private func dismissPresentations() {
        isProcessingInbox = false
        presentedTask = nil
    }

    nonisolated private static func emptyPaths() -> [AppTab: NavigationPath] {
        var paths: [AppTab: NavigationPath] = [:]
        for tab in AppTab.allCases { paths[tab] = NavigationPath() }
        return paths
    }
}
