import BrainBuddyCore
import SwiftUI

/// The route table shared by every tab's `NavigationStack`.
struct AppRouteView: View {
    let route: AppRoute

    var body: some View {
        switch route {
        case .destination(let destination):
            TaskListScreen(destination: destination)
        case .projects:
            ProjectsScreen()
        case .archivedProjects:
            ProjectsScreen(showsArchived: true)
        case .tags:
            TagsScreen()
        case .settings:
            SettingsScreen()
        case .syncIssues:
            SyncIssuesScreen()
        case .review:
            ReviewEntryScreen()
        case .performance:
            PerformanceScreen()
        case .account:
            AccountScreen()
        case .signInMethods:
            SignInMethodsScreen()
        }
    }
}
