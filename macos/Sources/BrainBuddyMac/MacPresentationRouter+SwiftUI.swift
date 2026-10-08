import BrainBuddyMacCore
import SwiftUI

// The SwiftUI side of `MacPresentationRouter` (contracts/mac-app-host.md §6): the one place the
// window attaches X-02's popover, X-03's sheet and X-04's alert, each bound to the router's state,
// and where a routed focus request reaches a `@FocusState`. Everything here is driven by what the
// person did (`UserIntent`); nothing reads the sync state (`MacPresentationGuardTests`).

extension View {
    /// X-02, non-modal, hanging from `anchor`: Esc or a click outside closes it.
    func routedSyncDetailsPopover<Content: View>(
        _ router: MacPresentationRouter, anchor: PopoverAnchor, onClose: @escaping () -> Void,
        @ViewBuilder content: @escaping () -> Content
    ) -> some View {
        popover(
            isPresented: Binding(
                get: { router.syncDetailsAnchor == anchor },
                set: { shown in
                    if !shown, router.syncDetailsAnchor == anchor { onClose() }
                }
            )
        ) {
            content()
        }
    }

    /// X-03, a window sheet. It closes through its own buttons (and Esc, its Cancel); `onDismiss`
    /// covers any other way the system closes it.
    func routedSignInSheet<Content: View>(
        _ router: MacPresentationRouter, onDismiss: @escaping () -> Void,
        @ViewBuilder content: @escaping (SignInRequest) -> Content
    ) -> some View {
        sheet(
            item: Binding(
                get: { router.signInRequest },
                set: { request in
                    if request == nil, router.signInRequest != nil { onDismiss() }
                }
            ),
            content: content
        )
    }

    /// X-04 and "Couldn't sign out" (`SignOutConfirmation`), shown each time the router presents X-04.
    func routedSignOutConfirmation(_ router: MacPresentationRouter, controller: MacSyncController) -> some View {
        modifier(SignOutConfirmation(router: router, controller: controller))
    }

    /// Applies the router's focus requests to `binding` (`map` picks the requests for this view).
    func routedFocus<Value: Hashable>(
        _ binding: FocusState<Value?>.Binding, router: MacPresentationRouter, map: @escaping (FocusTarget) -> Value?
    ) -> some View {
        onChange(of: router.focus, initial: true) { _, request in
            guard let request, let value = map(request.target) else { return }
            binding.wrappedValue = value
        }
    }
}
