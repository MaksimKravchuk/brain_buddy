import Foundation
import Observation

// The one presenter of the main window (contracts/mac-app-host.md §6, review c1 F22): the only
// type that decides which sheet, alert or popover the window shows and where keyboard focus goes.
// Its only input is `UserIntent`: a click, a menu item, a shortcut, or one of the launch notices.
// It has no `SyncSnapshot` input, so no sync state can ever present a surface or move focus
// (FR-017, SC-004). `MacPresentationGuardTests` keeps every other presentation call out of the
// app's sources; the SwiftUI side that binds this state is `MacPresentationRouter+SwiftUI.swift`.

/// Where the sign-in sheet was opened from, for the focus rule when it closes (design "Keyboard and
/// focus": back to the opener when it still exists, else to the status words).
package enum SignInEntry: Hashable, Sendable {
    /// X-01's trailing "Sign in to sync".
    case statusLineAction
    /// X-02's "Sign in…" or "Sign in again".
    case popover
    /// X-07's app menu.
    case menu
}

/// What X-02 hangs from.
package enum PopoverAnchor: Hashable, Sendable {
    /// X-01's words in the sidebar footer.
    case statusWords
    /// X-01's toolbar item while the sidebar is hidden.
    case toolbarItem
}

/// The launch notices: X-05 (the upgrade notice), X-08 (a second copy) and X-09 (the workspace
/// file can't be read).
package enum LaunchNotice: Hashable, Sendable {
    case upgrade, alreadyOpen, unreadableWorkspace
}

/// How the sign-in sheet closed, as the sheet knows it.
package struct SignInClose: Hashable, Sendable {
    package enum Outcome: Hashable, Sendable {
        /// Cancel or Esc.
        case cancelled
        /// Signed in (after the "account deletion cancelled" note, when there was one).
        case signedIn
    }

    package var outcome: Outcome
    /// The X-01 trailing action ("Sign in to sync") is still on screen.
    package var trailingActionShown: Bool

    package init(outcome: Outcome, trailingActionShown: Bool) {
        self.outcome = outcome
        self.trailingActionShown = trailingActionShown
    }
}

/// Every control a routed focus request can name.
package enum FocusTarget: Hashable, Sendable {
    /// X-01's words (in the sidebar footer).
    case statusWords
    /// X-01's trailing action ("Sign in to sync" or "Retry").
    case statusTrailingAction
    /// X-01's toolbar item while the sidebar is hidden.
    case toolbarStatusItem
    case inPopover(SyncPopoverControl)
    case signInEmail, signInPassword, signInNote
}

/// A focus move the window applies once; `serial` makes two requests for the same control distinct.
package struct FocusRequest: Equatable, Sendable {
    package var target: FocusTarget
    package var serial: Int
}

/// What a person did that may present something or move focus.
package enum UserIntent: Hashable, Sendable {
    /// A click, Space or Return on X-01's words (or its toolbar item): X-02.
    case openSyncDetails(from: PopoverAnchor)
    /// Esc or a click outside X-02.
    case closeSyncDetails
    /// "Sign in to sync", "Sign in…": X-03.
    case signIn(from: SignInEntry)
    /// "Sign in again", "Sign in again…": X-03 with the email locked.
    case signInAgain(from: SignInEntry)
    case closeSignIn(SignInClose)
    /// "Sign out…", once the unsaved-edit guard has passed: X-04.
    case signOut
    /// X-04's Cancel, or X-04 closed after a confirmation.
    case closeSignOut
    /// One of the launch notices.
    case launchNotice(LaunchNotice)
    case closeLaunchNotice
    /// A focus move that follows the person's own action inside a surface already open: X-02's
    /// focus on open and after Dismiss, an error in X-03.
    case focusInside(FocusTarget)
}

/// The surface the window shows: at most one at a time.
package enum MacSurface: Hashable, Sendable {
    /// X-02, non-modal.
    case syncDetails(PopoverAnchor)
    /// X-03.
    case signIn(SignInRequest)
    /// X-04.
    case signOutConfirmation
    /// X-05.
    case upgradeNotice
    /// X-08.
    case alreadyOpen
    /// X-09.
    case unreadableWorkspace
}

/// One presentation of X-03.
package struct SignInRequest: Hashable, Sendable, Identifiable {
    package var id: Int
    package var entry: SignInEntry
    /// "Sign in again": the email and server are locked.
    package var locked: Bool
}

@MainActor
@Observable
package final class MacPresentationRouter {
    package private(set) var surface: MacSurface?
    package private(set) var focus: FocusRequest?
    /// Changes with every presentation, also of the surface already shown (X-04 shown again with a
    /// new count), so the window can present it again.
    package private(set) var presentationSerial = 0
    /// Every surface presented, oldest first (the positive control's evidence).
    @ObservationIgnored package private(set) var presented: [MacSurface] = []
    @ObservationIgnored private var serial = 0

    package init() {}

    package func handle(_ intent: UserIntent) {
        switch intent {
        case .openSyncDetails(let anchor):
            present(.syncDetails(anchor))
        case .closeSyncDetails:
            guard case .syncDetails(let anchor) = surface else { return }
            surface = nil
            request(anchor == .toolbarItem ? .toolbarStatusItem : .statusWords)
        case .signIn(let entry):
            present(.signIn(SignInRequest(id: nextSerial(), entry: entry, locked: false)))
            request(.signInEmail)
        case .signInAgain(let entry):
            present(.signIn(SignInRequest(id: nextSerial(), entry: entry, locked: true)))
            request(.signInPassword)
        case .closeSignIn(let close):
            guard case .signIn(let sheet) = surface else { return }
            surface = nil
            request(Self.focusAfterSignIn(entry: sheet.entry, close: close))
        case .signOut:
            present(.signOutConfirmation)
        case .closeSignOut:
            guard surface == .signOutConfirmation else { return }
            surface = nil
            request(.statusWords)
        case .launchNotice(let notice):
            switch notice {
            case .upgrade: present(.upgradeNotice)
            case .alreadyOpen: present(.alreadyOpen)
            case .unreadableWorkspace: present(.unreadableWorkspace)
            }
        case .closeLaunchNotice:
            guard let surface, [.upgradeNotice, .alreadyOpen, .unreadableWorkspace].contains(surface) else { return }
            self.surface = nil
        case .focusInside(let target):
            request(target)
        }
    }

    /// Design "Focus restored on close": on Cancel, the X-01 trailing action when it still exists;
    /// otherwise the control that opened the sheet when it still exists (only the trailing action
    /// can still be there: the popover has closed, a menu item is not a focus target); otherwise
    /// the X-01 words.
    package static func focusAfterSignIn(entry: SignInEntry, close: SignInClose) -> FocusTarget {
        switch close.outcome {
        case .cancelled:
            return close.trailingActionShown ? .statusTrailingAction : .statusWords
        case .signedIn:
            return entry == .statusLineAction && close.trailingActionShown ? .statusTrailingAction : .statusWords
        }
    }

    private func present(_ next: MacSurface) {
        surface = next
        presented.append(next)
        presentationSerial += 1
    }

    private func request(_ target: FocusTarget) {
        focus = FocusRequest(target: target, serial: nextSerial())
    }

    private func nextSerial() -> Int {
        serial += 1
        return serial
    }

    // MARK: Bindings for the SwiftUI side

    /// The X-03 sheet's item.
    package var signInRequest: SignInRequest? {
        if case .signIn(let request) = surface { return request }
        return nil
    }

    package var syncDetailsAnchor: PopoverAnchor? {
        if case .syncDetails(let anchor) = surface { return anchor }
        return nil
    }

    package var isConfirmingSignOut: Bool { surface == .signOutConfirmation }
}
