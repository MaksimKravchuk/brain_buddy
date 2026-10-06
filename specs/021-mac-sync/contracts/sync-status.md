# Contract: shared sync status presentation (021)

This is the single source for the status line on Mac (design **X-01**, **X-02**, **X-07** enablement) and iPhone (design **M-01**). It is pure value code in `ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncPresentation.swift` and `SyncActivityIndicator.swift` (slice PR-05), tested on Linux with Swift Testing and an injected `now`. The apps only render the description. Wording follows FR-012 and design.md "The status line, one table for both platforms".

## 1. `SyncTiming` (one place, FR-013, FR-014, design decision 1)

| constant | value | used for |
|---|---|---|
| `indicatorDelay` | 1 s | the indicator appears only for a sync running longer than this |
| `indicatorMinimum` | 0.5 s | once shown, it stays at least this long |
| `waitingSuffixAfter` | 10 s | " · N changes waiting" while online only after the oldest change waited this long |
| `failureSurfacesAfter` | 60 s | "Couldn't sync · Retry" only after `failingSince` is this old |
| `relativeRefresh` | 30 s | the apps re-describe at least this often (FR-012 "at least once a minute") |
| `periodicTick` | 15 s | Mac (always while running) and iPhone (scene active) `.periodic` trigger |
| `pullAge` | 45 s | `SyncConfiguration.pullInterval` passed by both apps (research R8) |

## 2. Input and output

```swift
// shapes only
public enum DeviceKind: Sendable { case mac, iPhone }        // "Mac" / "iPhone"
public struct SyncSnapshot: Equatable, Sendable { /* data-model E6 */ }

public struct SyncStatusDescription: Equatable, Sendable {
    public enum Tone { case calm, attention }                 // slate vs amber + glyph (design)
    public enum Glyph { case none, sessionEnded, warning }    // person-badge / triangle
    public enum Action { case none, signIn, signInAgain, retry, showIssues }
    public var state: SyncLineState      // §3 rows, for tests and the popover
    public var text: String              // the whole line, e.g. "Synced 3 min ago · 2 changes waiting"
    public var leading: String           // part before " · ", for the X-01 split rendering
    public var trailingActionTitle: String?   // "Sign in to sync" | "Retry" | nil
    public var tone: Tone
    public var glyph: Glyph
    public var action: Action
    public var accessibilityLabel: String     // "Sync status: <text>. Show details"
    public var tooltip: String                // X-01 hover
    public var announceOnEntry: Bool          // attention states only (design "Announcements")
    public var syncNowEnabled: Bool           // false only for accountLess, sessionEnded, offline;
                                              // never false because a sync is running (single-flight, FR-019)
}

public enum SyncStatusDescriber {
    public static func describe(_ s: SyncSnapshot, now: Date, device: DeviceKind,
                                calendar: Calendar) -> SyncStatusDescription
}
```

## 3. States, precedence and wording

Evaluate top to bottom. The first row that holds wins. This is design.md's precedence ("session ended → rejected changes → failing → offline → changes waiting → synced"), with the account-less and first-load rows placed where they can occur.

| # | `state` | holds when | text (Mac; iPhone replaces "Mac" with "iPhone") | tone / glyph | action |
|---|---|---|---|---|---|
| 1 | `accountLess` | `account == none` | "On this Mac · Sign in to sync" (`trailingActionTitle` = "Sign in to sync") | calm / none | `signIn` |
| 2 | `sessionEnded` | `sessionEnded` | "Sign in again to sync" | attention / sessionEnded | `signInAgain` |
| 3 | `rejected` | `issueCount ≥ 1` | "1 change couldn't sync" / "N changes couldn't sync" | attention / warning | `showIssues` |
| 4 | `failing` | `failingSince != nil && now − failingSince ≥ 60 s` (design precedence puts it above offline; offline errors never start the clock, §4 of kit-commands) | "Couldn't sync · Retry" (`trailingActionTitle` = "Retry") | attention / warning | `retry` |
| 5 | `offline` | `!isOnline` | "Offline · 1 change waiting" / "Offline · N changes waiting" / "Offline" (N = 0) | calm / none | none (words open the popover on Mac) |
| 6 | `notSyncedYet` | `lastSyncedAt == nil` | "Not synced yet" | calm / none | none |
| 7 | `synced` (+ waiting) | otherwise | `<synced>` + (" · 1 change waiting" / " · N changes waiting" when `pendingCount ≥ 1 && now − oldestPendingAt > 10 s`) | calm / none | none |

**`<synced>` relative-time ladder** (FR-012, G-2). Let `Δ = max(0, now − lastSyncedAt)`; a future time counts as 0, the "clock" edge case:

| condition | text |
|---|---|
| Δ < 60 s | "Synced just now" |
| Δ < 60 min | "Synced N min ago" (N = ⌊Δ / 60 s⌋, 1 … 59) |
| same calendar day as `now` | "Synced N h ago" (N = ⌊Δ / 3600 s⌋, ≥ 1) |
| previous calendar day | "Synced yesterday" |
| 2 – 6 calendar days before | "Synced N days ago" |
| otherwise | "Synced on <d MMM>" (e.g. "Synced on 28 Sep"); "<d MMM yyyy>" when the year differs |

Numbers use the locale's grouping ("1,284 changes waiting", design X-01 long text). Copy is English only (FR-012 copy as given).

**Tooltip** (X-01 hover; the reference id appears only here and in X-02, and is copied in X-02):

| state | tooltip |
|---|---|
| `synced`, `notSyncedYet`, `offline` | "Last synced today at 14:31. Click for details." (today / yesterday / "on 28 Sep" at HH:mm), or "Not synced yet. Click for details." |
| `failing` | "Couldn't reach Brain Buddy since 14:02. It keeps trying. Reference ID <id>" |
| `sessionEnded` | "Your session ended. Sign in again to keep syncing." |
| `rejected` | "N changes couldn't sync. Click for details." |
| `accountLess` | "Your tasks are stored on this Mac. Click for details." |

**Copy catalogue in the same file** (shared by X-02, X-03, X-04, M-01 and the iPhone Settings):

| key | text |
|---|---|
| `accountSwitchRefused` | "Sign out first to use another account." + "Changes from the other account are still waiting on this <device>." |
| `popoverLastSynced` | "Last synced · Today at 14:31" |
| `popoverWaitingNothing` | "Waiting to sync · Nothing" |
| `popoverWaiting` | "Waiting to sync · 2 changes · oldest 40 s" |
| `popoverOffline` | "You're offline. Changes are saved on this <device> and sync when you're back online." |
| `popoverFailing` | "Couldn't sync since 14:02" + "Brain Buddy didn't answer. Your changes are safe on this <device>, and it keeps trying." |
| `popoverSessionEnded` | "Your session ended" + "Sign in again to keep syncing. Your changes stay on this <device> until then." |
| `popoverAccountLess` | "Your tasks are stored on this <device>" + "Nothing is sent anywhere until you sign in. Sign in to use the same tasks on your iPhone and the web." (Mac) |
| `signOutUnsent(n, offline, sessionEnded)` | design X-04 rows, verbatim |
| `signOutNothingUnsent` | "Sign out?" + "Your tasks are removed from this <device>. They stay in your account." |

The age format of `oldest` is "N s" under a minute, "N min" under an hour, "N h" under a day, and "N days" otherwise ("oldest 3 days", X-02 "unreachable for days").

## 4. Activity indicator (`SyncActivityIndicator`)

A value-type state machine with no timers inside:

```swift
public struct SyncActivityIndicator: Equatable, Sendable {
    public mutating func started(at: Date)
    public mutating func finished(at: Date)
    public func isVisible(at: Date) -> Bool
    public func nextChange(after: Date) -> Date?   // when the app should re-evaluate
}
```

Rules:

- A cycle visible on screen requires `now − startedAt > 1 s`.
- Once it becomes visible at time `v`, it stays visible until `max(finishedAt, v + 0.5 s)`.
- A new cycle that starts while it is still visible keeps it visible, with no flicker.
- The line's words never change because a sync started or stopped (design "No flicker"). The indicator has a reserved slot.
- Under Reduce Motion the apps render a static glyph instead (`arrow.triangle.2.circlepath`).
- Accessibility name "Syncing", not announced on appearance.

## 5. Tests (Linux, Swift Testing; `BrainBuddyCoreTests/SyncPresentationTests.swift`, `SyncActivityIndicatorTests.swift`)

Each test names its requirement id (`@Test("021-FR-012 …")`):

- every row of §3 for both device kinds;
- every precedence pair: a snapshot satisfying rows *i* and *j* gives *min(i, j)*;
- ladder boundaries at 59 s / 60 s, 59 min / 60 min, 23:59 / 00:00 across midnight, 6 / 7 days, the year change, and a future `lastSyncedAt` giving "just now";
- waiting suffix at 10 s and 10.001 s;
- failing at 59.999 s and 60 s, with `failingSince` surviving a relaunch (decoded snapshot);
- offline with N = 0, 1 and 2;
- singular and plural forms;
- the indicator: 0.9 s sync gives nothing, 1.1 s sync gives visible ≥ 0.5 s, back-to-back cycles give one continuous span;
- `syncNowEnabled` is false exactly for `accountLess`, `sessionEnded` and `offline`, and is true while `isSyncing` in every other state (`021-FR-019`, `021-FR-006`);
- no string contains "—" (the em-dash form is retired, M-01 "before").
