import BrainBuddyWorkspace
import SwiftUI

/// Keeps a bounded Rust answer's loading and failed states distinct from an
/// empty ready page. Legacy-selected workspaces report ready immediately.
struct WorkspaceQueryContent<Content: View>: View {
    let readiness: WorkspaceQueryReadiness
    let retry: () -> Void
    let content: Content

    init(readiness: WorkspaceQueryReadiness, retry: @escaping () -> Void, @ViewBuilder content: () -> Content) {
        self.readiness = readiness
        self.retry = retry
        self.content = content()
    }

    var body: some View {
        switch readiness {
        case .ready:
            content
        case .notRequested, .loading:
            ZStack {
                Color(uiColor: .systemBackground).ignoresSafeArea()
                ProgressView("Loading…")
            }
        case .failed:
            ZStack {
                Color(uiColor: .systemBackground).ignoresSafeArea()
                ContentUnavailableView {
                    Label("Couldn't load", systemImage: "exclamationmark.triangle")
                } description: {
                    Text("Your data is still here. Try again.")
                } actions: {
                    Button("Retry", action: retry)
                }
            }
        }
    }
}

struct WorkspaceQueryPageControls: View {
    let page: WorkspaceQueryPageState
    let previous: () async -> Void
    let next: () async -> Void

    var body: some View {
        if page.hasPrevious || page.hasNext {
            HStack {
                Button("Previous") { Task { await previous() } }
                    .disabled(!page.hasPrevious)
                Spacer()
                Button("Next") { Task { await next() } }
                    .disabled(!page.hasNext)
            }
            .font(.footnote)
            .padding(.horizontal)
            .padding(.vertical, 8)
        }
    }
}
