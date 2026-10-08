import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The positive control of contracts/mac-app-host.md §8: each `UserIntent` presents exactly its own
/// surface, and no sync state moves the router. On its own this cannot fail by construction (the
/// router has no snapshot input), so `MacPresentationGuardTests` carries the evidence (review c2, G16).
@Suite("Presentation router")
@MainActor
struct MacPresentationRouterTests {
    @Test("021-SC-004 021-FR-017 each intent presents exactly its own surface")
    func eachIntentPresentsItsOwnSurface() {
        let cases: [(UserIntent, MacSurface)] = [
            (.openSyncDetails(from: .statusWords), .syncDetails(.statusWords)),
            (.openSyncDetails(from: .toolbarItem), .syncDetails(.toolbarItem)),
            (.signOut, .signOutConfirmation),
            (.launchNotice(.upgrade), .upgradeNotice),
            (.launchNotice(.alreadyOpen), .alreadyOpen),
            (.launchNotice(.unreadableWorkspace), .unreadableWorkspace),
        ]
        for (intent, surface) in cases {
            let router = MacPresentationRouter()
            router.handle(intent)
            #expect(router.surface == surface)
            #expect(router.presented == [surface], "one intent, one surface")
        }

        for entry in [SignInEntry.statusLineAction, .popover, .menu] {
            let router = MacPresentationRouter()
            router.handle(.signIn(from: entry))
            #expect(router.signInRequest?.entry == entry && router.signInRequest?.locked == false)
            #expect(router.focus?.target == .signInEmail)
            router.handle(.closeSignIn(SignInClose(outcome: .cancelled, trailingActionShown: false)))
            router.handle(.signInAgain(from: entry))
            #expect(router.signInRequest?.locked == true, "Sign in again locks the email")
            #expect(router.focus?.target == .signInPassword)
            #expect(router.presented.count == 2)
        }
    }

    @Test("021-FR-017 closing a surface puts focus back where the design says")
    func focusReturnsOnClose() {
        let router = MacPresentationRouter()
        router.handle(.openSyncDetails(from: .statusWords))
        router.handle(.closeSyncDetails)
        #expect(router.surface == nil && router.focus?.target == .statusWords)

        router.handle(.openSyncDetails(from: .toolbarItem))
        router.handle(.closeSyncDetails)
        #expect(router.focus?.target == .toolbarStatusItem)

        router.handle(.signOut)
        router.handle(.closeSignOut)
        #expect(router.surface == nil && router.focus?.target == .statusWords, "X-04 returns to the status words")

        // X-03: on Cancel to the trailing action when it is still there; after signing in, to the
        // opener when it still exists, else to the words.
        let table: [(SignInEntry, SignInClose, FocusTarget)] = [
            (.statusLineAction, SignInClose(outcome: .cancelled, trailingActionShown: true), .statusTrailingAction),
            (.menu, SignInClose(outcome: .cancelled, trailingActionShown: true), .statusTrailingAction),
            (.popover, SignInClose(outcome: .cancelled, trailingActionShown: false), .statusWords),
            (.statusLineAction, SignInClose(outcome: .signedIn, trailingActionShown: false), .statusWords),
            (.statusLineAction, SignInClose(outcome: .signedIn, trailingActionShown: true), .statusTrailingAction),
            (.popover, SignInClose(outcome: .signedIn, trailingActionShown: false), .statusWords),
            (.menu, SignInClose(outcome: .signedIn, trailingActionShown: true), .statusWords),
        ]
        for (entry, close, focus) in table {
            router.handle(.signIn(from: entry))
            router.handle(.closeSignIn(close))
            #expect(router.surface == nil)
            #expect(router.focus?.target == focus, "\(entry) \(close)")
        }
    }

    @Test("021-SC-004 021-FR-017 every sync state and transition through the status line leaves the router untouched")
    func syncStatesNeverMoveTheRouter() {
        let router = MacPresentationRouter()
        let start = TestClock.importTime
        let email = SyncSnapshot.Account.linked(email: "alex@example.com")
        let states: [SyncSnapshot] = [
            SyncSnapshot(account: .none),
            SyncSnapshot(account: email),
            SyncSnapshot(account: email, isSyncing: true),
            SyncSnapshot(account: email, lastSyncedAt: start),
            SyncSnapshot(account: email, lastSyncedAt: start, pendingCount: 2, oldestPendingAt: start),
            SyncSnapshot(account: email, lastSyncedAt: start, pendingCount: 5, oldestPendingAt: start, initialUploadRemaining: 5),
            SyncSnapshot(account: email, isOnline: false, lastSyncedAt: start, pendingCount: 3, oldestPendingAt: start),
            SyncSnapshot(account: email, sessionEnded: true, lastSyncedAt: start),
            SyncSnapshot(account: email, lastSyncedAt: start, issueCount: 2),
            SyncSnapshot(
                account: email, lastSyncedAt: start, failingSince: start, lastFailedAttemptAt: start.addingTimeInterval(60),
                lastFailureReferenceID: "4e5d9a20-0000-4000-8000-000000000001"),
            SyncSnapshot(
                account: email, isOnline: false, lastSyncedAt: start, failingSince: start,
                lastFailedAttemptAt: start.addingTimeInterval(60)),
        ]
        var line = SyncStatusLineModel(snapshot: states[0], now: start)
        var seen: Set<SyncLineState> = []
        var time = start
        // Every ordered pair: from each state to each other one.
        for from in states {
            for to in states {
                time = time.addingTimeInterval(31)
                line.update(from, at: time)
                line.update(to, at: time.addingTimeInterval(1))
                line.refresh(at: time.addingTimeInterval(30))
                _ = line.takeAnnouncement()
                _ = line.toolbarItem(sidebarHidden: true)
                seen.insert(line.description.state)
            }
        }
        #expect(seen == [.accountLess, .sessionEnded, .rejected, .failing, .offline, .notSyncedYet, .synced])
        #expect(line.announcementCount > 0, "attention states were entered")
        #expect(router.surface == nil, "no sync state presents anything")
        #expect(router.focus == nil, "or moves focus")
        #expect(router.presented.isEmpty)
    }
}
