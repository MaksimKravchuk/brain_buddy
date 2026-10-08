import BrainBuddyMacCore
import SwiftUI

/// Design X-09 (contracts/mac-app-host.md §9): `store.json` cannot be read, or was written by a
/// newer version. One calm panel replaces the lists; nothing syncs, nothing is sent, and the file
/// is never overwritten. "Try again" is the default and has focus; "Start fresh…" only sets the
/// file aside after its own confirmation, whose default and Escape are "Keep trying".
struct UnreadableWorkspaceView: View {
    let host: WorkspaceHost
    @State private var retrying = false
    @State private var confirmingStartFresh = false
    @FocusState private var tryAgainFocused: Bool

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 34))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text(UnreadableWorkspaceCopy.title)
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)
            VStack(spacing: 6) {
                Text(UnreadableWorkspaceCopy.message)
                if let reason = host.workspace.loadError {
                    Text(reason).foregroundStyle(.secondary)
                }
            }
            .multilineTextAlignment(.center)
            .frame(maxWidth: 440)
            .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 12) {
                Button(UnreadableWorkspaceCopy.startFresh) { confirmingStartFresh = true }
                    .disabled(retrying)
                Button(retrying ? UnreadableWorkspaceCopy.tryingAgain : UnreadableWorkspaceCopy.tryAgain) {
                    Task {
                        retrying = true
                        await host.retryLoad()
                        retrying = false
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(retrying)
                .focused($tryAgainFocused)
            }
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .frame(minWidth: 720, minHeight: 480)
        .onAppear { tryAgainFocused = true }
        .alert(UnreadableWorkspaceCopy.confirmTitle, isPresented: $confirmingStartFresh) {
            Button(UnreadableWorkspaceCopy.confirm, role: .destructive) {
                Task { await host.startFresh() }
            }
            Button(UnreadableWorkspaceCopy.keepTrying, role: .cancel) {}
                .keyboardShortcut(.defaultAction)
        } message: {
            Text(UnreadableWorkspaceCopy.confirmMessage)
        }
    }
}

/// The launch's import-failed state (data-model E7.1 invariant 4): the upgrade import could not
/// reach a terminal state, so no workspace opens. One calm panel in the X-09 pattern with only
/// "Try again" (default, focused): it runs the import again, which resumes from what the failed
/// attempt recorded. There is no "Start fresh": an empty workspace would make the previous
/// version's file a "later file" that is never imported.
struct LegacyImportFailedView: View {
    let launch: MacLaunch
    @FocusState private var tryAgainFocused: Bool

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 34))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text(LegacyImportFailedCopy.title)
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)
            VStack(spacing: 6) {
                Text(LegacyImportFailedCopy.message)
                Text(LegacyImportFailedCopy.hint).foregroundStyle(.secondary)
            }
            .multilineTextAlignment(.center)
            .frame(maxWidth: 440)
            .fixedSize(horizontal: false, vertical: true)
            Button(launch.isRunning ? LegacyImportFailedCopy.tryingAgain : LegacyImportFailedCopy.tryAgain) {
                Task { await launch.retryImport() }
            }
            .keyboardShortcut(.defaultAction)
            .disabled(launch.isRunning)
            .focused($tryAgainFocused)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .frame(minWidth: 720, minHeight: 480)
        .onAppear { tryAgainFocused = true }
    }
}
