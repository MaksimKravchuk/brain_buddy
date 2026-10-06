# Contract: shared sync status presentation (021)

This is the single source for the status line on Mac (design **X-01**, **X-02**, **X-07** enablement) and iPhone (design **M-01**). It is pure value code in `ios/BrainBuddyKit/Sources/BrainBuddyCore/SyncPresentation.swift` and `SyncActivityIndicator.swift` (slice PR-05), tested on Linux with Swift Testing and an injected `now`. The apps only render the description. Wording follows FR-012 and design.md "The status line, one table for both platforms".

## 1. `SyncTiming` (one place, FR-013, FR-014, design decision 1)

| constant | value | used for |
|---|---|---|
| `indicatorDelay` | 1 s | the indicator appears only for a sync running longer than this |
| `indicatorMinimum` | 0.5 s | once shown, it stays at least this long |
| `waitingSuffixAfter` | 10 s | " · N changes waiting" while online only after the oldest change waited this long |
| `failureSurfacesAfter` | 60 s | "Couldn't sync · Retry" only once an attempt that started at least this long after `failingSince` has failed (kit-commands §4 "Failing clock") |
| `relativeRefresh` | 30 s | the apps re-describe at least this often (FR-012 "at least once a minute") |
| `periodicTick` | 15 s | Mac (always while running) and iPhone (scene active) `.periodic` trigger, through the kit's `PeriodicSyncTicker` |
| `pullAge` | 30 s | `SyncConfiguration.pullInterval` passed by both apps; with the 15 s tick the gap between pulls stays under 45 s plus one pull (research R8; review c1 F07, F17) |
| `webRefetch` | 45 s | not used by the kit; recorded here so the three clients' cadences sit in one table: the web's visible-tab refetch (research R8) |

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
    public var lastTriedText: String?         // "Last tried 14:35" in the failing state (review c1 F53)
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
| 4 | `failing` | `isOnline && failingSince != nil && lastFailedAttemptAt − failingSince ≥ 60 s` (offline errors never start the clock, §4 of kit-commands) | "Couldn't sync · Retry" (`trailingActionTitle` = "Retry") | attention / warning | `retry` |
| 5 | `offline` | `!isOnline` | "Offline · 1 change waiting" / "Offline · N changes waiting" / "Offline" (N = 0) | calm / none | none (words open the popover on Mac) |
| 6 | `notSyncedYet` | `lastSyncedAt == nil`, or `initialUploadRemaining > 0` (the first upload after linking an account with local data is still draining) | "Not synced yet" | calm / none | none |
| 7 | `synced` (+ waiting) | otherwise | `<synced>` + (" · 1 change waiting" / " · N changes waiting" when `pendingCount ≥ 1 && now − oldestPendingAt > 10 s`, where `oldestPendingAt` is the sendable time of data-model E6) | calm / none | none |

**Failing while offline** (review c1, F13): row 4 holds only while online, so going offline after a minute of server failure shows "Offline …" (row 5), not a "Retry" that cannot act. `failingSince` is kept, not cleared, so the 60 s clock does not restart when the network returns: the first failed attempt back online shows row 4 at once. In that offline state X-02 shows `popoverOffline`, and its details keep the last failure's time and reference id ("Last failed 14:35 · Reference ID …", with Copy).

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
| `failing` | "Couldn't reach Brain Buddy since 14:02. Last tried 14:35. It keeps trying. Reference ID <id>" ("Last tried" updates after every attempt, automatic or Retry; review c1 F53) |
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
| `popoverFailing` | "Couldn't sync since 14:02" + "Brain Buddy didn't answer. Your changes are safe on this <device>, and it keeps trying." + "Last tried 14:35" |
| `popoverFirstUpload` | "Adding your tasks to your account · 1,284 left" (shown instead of `popoverWaiting` while `initialUploadRemaining > 0`; review c1 F33) |
| `popoverSessionEnded` | "Your session ended" + "Sign in again to keep syncing. Your changes stay on this <device> until then." |
| `popoverAccountLess` | "Your tasks are stored on this <device>" + "Nothing is sent anywhere until you sign in. Sign in to use the same tasks on your iPhone and the web." (Mac) |
| `popoverBackup(until)` | Mac only, while the pre-upgrade backup exists: "Backup from before the update · kept until 5 Nov" + "Show in Finder" (review c1 F27, F62) |
| `popoverLaterFile` | Mac only, while a previous-version file is kept (FR-033): "A file from the previous version is on this Mac. It was not added." + "Show in Finder" |
| `signOutUnsent(n, offline, sessionEnded)` | design X-04 rows, verbatim |
| `signOutNothingUnsent` | "Sign out?" + "Your tasks are removed from this <device>. They stay in your account." |
| `signOutIssues(n)` | appended to either sign-out text when sync issues are open (FR-018; review c1 F06, F54): "1 change that couldn't sync will also be removed from this <device>." / "N changes that couldn't sync will also be removed from this <device>." |
| `signOutBackup(until)` | Mac only, appended while the pre-upgrade backup exists and `until` (`importedAt + 30 days`) is still in the future (FR-021; review c1 F27): "A copy of your tasks from before the update stays on this Mac until 5 Nov." Once that date has passed, this sign-out deletes the backup (data-model E8), so no sentence is added and the base text is true |
| `outcomeKeptIssue` | see kit-commands §5: the account's outcome is kept and the full local outcome is shown, with "Copy outcome" |

The age format of `oldest` is "N s" under a minute, "N min" under an hour, "N h" under a day, and "1 day" / "N days" otherwise ("oldest 3 days", X-02 "unreachable for days"). The age is measured from the sendable time (data-model E6), so the first sign-in with months-old local data does not read as days of failure.

**Order of the sign-out sentences**: the base text (`signOutUnsent` or `signOutNothingUnsent`), then `signOutIssues`, then `signOutBackup`. The iPhone uses the same catalogue for its sign-out confirmation (PR-07), so both devices name open issues the same way.

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
- every precedence pair: a snapshot satisfying rows *i* and *j* gives *min(i, j)*, except the pair `failing` + offline, which gives `offline` (row 4 requires `isOnline`); that pair has its own case, and so does the return online with `failingSince` kept (`021-FR-014`);
- ladder boundaries at 59 s / 60 s, 59 min / 60 min, 23:59 / 00:00 across midnight, 6 / 7 days, the year change, and a future `lastSyncedAt` giving "just now";
- waiting suffix at 10 s and 10.001 s, measured from the sendable time: an operation issued 213 days ago and linked 5 s ago shows no suffix; `initialUploadRemaining > 0` gives `notSyncedYet` and `popoverFirstUpload` (`021-FR-012`, `021-FR-016`);
- failing when `lastFailedAttemptAt − failingSince` is 59.999 s (not failing) and 60 s (failing), with both surviving a relaunch (decoded snapshot);
- offline with N = 0, 1 and 2;
- singular and plural forms;
- the indicator: 0.9 s sync gives nothing, 1.1 s sync gives visible ≥ 0.5 s, back-to-back cycles give one continuous span;
- `syncNowEnabled` is false exactly for `accountLess`, `sessionEnded` and `offline`, and is true while `isSyncing` in every other state (`021-FR-019`, `021-FR-006`);
- **copy catalogue, verbatim, for both device kinds** (review c1, F46): every key above, including `accountSwitchRefused`, each `popover*`, each `signOutUnsent` variant, `signOutNothingUnsent`, `signOutIssues` (1 and N), `signOutBackup`, and the sentence order (`021-FR-016`, `021-FR-018`, `021-FR-004`);
- **tooltip table, verbatim**, for every state, including "Last tried" in `failing` (`021-FR-015`);
- **oldest-age formatter boundaries**: 59 s / 60 s ("59 s" / "1 min"), 59 min / 60 min ("59 min" / "1 h"), 23 h / 24 h ("23 h" / "1 day"), and "2 days";
- **reference ids**: the `failing` tooltip and `popoverFailing` details contain the non-empty `lastFailureReferenceID`, and every `SyncIssueDescriber` output carries its issue's non-empty reference id (`021-FR-015`, `021-SC-004`);
- no string contains "—" (the em-dash form is retired, M-01 "before").
