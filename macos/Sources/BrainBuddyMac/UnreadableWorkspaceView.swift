import BrainBuddyDesign
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
        MacWorkspaceNoticePanel(
            title: UnreadableWorkspaceCopy.title, message: UnreadableWorkspaceCopy.message,
            detail: host.workspace.loadError
        ) {
            Button(UnreadableWorkspaceCopy.startFresh) { confirmingStartFresh = true }
                .buttonStyle(.carryOnSecondary)
                .disabled(retrying)
            Button(retrying ? UnreadableWorkspaceCopy.tryingAgain : UnreadableWorkspaceCopy.tryAgain) {
                Task {
                    retrying = true
                    await host.retryLoad()
                    retrying = false
                }
            }
            .buttonStyle(.carryOnStrong)
            .keyboardShortcut(.defaultAction)
            .disabled(retrying)
            .focused($tryAgainFocused)
        }
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

/// The launch's stopped state: the runtime could not be opened, so no workspace opens. One calm
/// panel in the X-09 pattern with only "Try again" (default, focused): it runs the launch again.
/// There is no "Start fresh": an empty workspace would fork from the retired file.
struct LegacyImportFailedView: View {
    let launch: MacLaunch
    @FocusState private var tryAgainFocused: Bool

    var body: some View {
        MacWorkspaceNoticePanel(
            title: LegacyImportFailedCopy.title, message: LegacyImportFailedCopy.message,
            detail: LegacyImportFailedCopy.hint
        ) {
            Button(launch.isRunning ? LegacyImportFailedCopy.tryingAgain : LegacyImportFailedCopy.tryAgain) {
                Task { await launch.retryImport() }
            }
            .buttonStyle(.carryOnStrong)
            .keyboardShortcut(.defaultAction)
            .disabled(launch.isRunning)
            .focused($tryAgainFocused)
        }
        .onAppear { tryAgainFocused = true }
    }
}

/// X-09's calm panel on the window's ground: a quiet symbol, the serif title, the 14 message and
/// its secondary detail, centred, then the actions (`actions`, 8 apart).
struct MacWorkspaceNoticePanel<Actions: View>: View {
    let title: String
    let message: String
    let detail: String?
    let actions: Actions

    init(title: String, message: String, detail: String?, @ViewBuilder actions: () -> Actions) {
        self.title = title
        self.message = message
        self.detail = detail
        self.actions = actions()
    }

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 30))
                .foregroundStyle(CarryOnColorStyle.coMarkOpen)
                .accessibilityHidden(true)
            Text(title)
                .carryOnText(CarryOnTypeScale.title)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .accessibilityAddTraits(.isHeader)
            VStack(spacing: 6) {
                Text(message)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                if let detail {
                    Text(detail).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
            }
            .font(MacSheetFont.body)
            .lineSpacing(4)
            .multilineTextAlignment(.center)
            .frame(maxWidth: 440)
            .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) { actions }
                .padding(.top, 4)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .frame(minWidth: 720, minHeight: 480)
        .background(CarryOnColorStyle.coBgGround)
    }
}
