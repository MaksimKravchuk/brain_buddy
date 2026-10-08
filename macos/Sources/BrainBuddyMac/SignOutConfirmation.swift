import BrainBuddyMacCore
import SwiftUI

/// Design X-04, the sign-out confirmation (contracts/mac-app-host.md §7): an alert sheet on the
/// window, opened only by the person's "Sign out…" after the window's unsaved-edit guard. Its words
/// are `SignOutFlow.Prompt` (the unsent-changes or nothing-unsent variant, the open issues, the
/// backup sentence); "Cancel" is the default (Return) and Esc; "Sign out and remove" is the
/// destructive button when changes would be removed, else "Sign out". When the count changed, or
/// the kit refused a plain sign-out, the router presents it again with the new count. A failed
/// removal shows "Couldn't sign out": nothing was removed and the person is still signed in.
struct SignOutConfirmation: ViewModifier {
    let router: MacPresentationRouter
    let controller: MacSyncController
    @State private var shown = false
    @State private var failureShown = false

    func body(content: Content) -> some View {
        let flow = controller.signOut
        content
            .onChange(of: router.presentationSerial) { _, _ in
                guard router.isConfirmingSignOut, flow.prompt != nil else { return }
                // A hop, so a confirmation shown again follows the one just closed.
                Task { @MainActor in shown = true }
            }
            .alert(flow.prompt?.text.title ?? SignOutCopy.signOut, isPresented: $shown, presenting: flow.prompt) { prompt in
                Button(SignOutCopy.cancel, role: .cancel) { controller.cancelSignOut() }
                    .keyboardShortcut(.defaultAction)
                Button(prompt.confirmTitle, role: prompt.removesUnsent ? .destructive : nil) {
                    Task { @MainActor in
                        if await controller.confirmSignOut() == .failed { failureShown = true }
                    }
                }
            } message: { prompt in
                Text(prompt.text.detail ?? "")
            }
            .alert(SignOutCopy.failedTitle, isPresented: $failureShown) {
                Button(SignOutCopy.ok, role: .cancel) { flow.dismissFailure() }
                    .keyboardShortcut(.defaultAction)
            } message: {
                Text(flow.failure?.detail ?? SignOutCopy.failedDetail)
            }
    }
}
