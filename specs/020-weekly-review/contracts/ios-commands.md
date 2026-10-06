# Contract: iOS core commands, records and outbox (020)

**Package**: `ios/BrainBuddyKit` (Swift 6.2, no third-party dependencies, every target
Linux-testable via `sh ios/scripts/swift-linux.sh test`). **Rule source**:
`contracts/formulation-clock.md`. **Wire**: `contracts/http.md`.

`GTDReducer` (`ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift`) stays the only
home of GTD rules on Apple platforms. The formulation clock is maintained by the reducer
for every existing command and by the new commands below; screens never compute or
write clock fields themselves.

## 1. Record additions (`BrainBuddyCore/Records.swift`)

`TaskRecord` gains (all optional or defaulted, decoded with `decodeIfPresent` as
`PendingOperation.everSent` already does):

```swift
public var formulation: FormulationClock?      // nil unless in Next with a started clock
public var consecutiveStalledFormulations: Int // default 0
public var parked: ParkMarker?                 // only while .someday

public struct FormulationClock: Hashable, Sendable, Codable {
    public var id: FormulationID          // minted in the command ("form_<lowercased UUID>") and
                                          // sent as `new_formulation_id`; the server adopts it
                                          // (http §1, id shapes in http "Client-supplied ids")
    public var startedAt: Date
    public var extendedAt: Date?
    public var extensionReason: String?
    public var parkFloorAt: Date?
}
public struct ParkMarker: Hashable, Sendable, Codable {   // auto-park only
    public var at: Date
    public var formulationID: FormulationID
    public var clockBefore: FormulationClock?             // local parks; server keeps its own
    public var stalledBefore: Int
}
```

`GTDState` gains `review: ReviewState` (settings, sessions, decisions, receipts, park
acks, bulk releases, navigator consent; data-model E10). `TaskDTO`
(`BrainBuddyAPI/WireModels.swift`) gains `formulation` and `parked`
(`decodeIfPresent`); `StoreDocument+Merge.swift` copies them on pull, so server values
replace local ones exactly as `createdAt`/`waitingSince` do today.

## 2. New `GTDCommand` cases (`BrainBuddyCore/Commands.swift`)

Each case maps to exactly one HTTP request (the existing invariant) and carries every
client id it creates.

| case | payload | request | reducer effect |
|---|---|---|---|
| `decideTask(DecideTask)` | `decisionID, taskID, type, formulationID?, newFormulationID?, stallReason?, title?, waitingFor?, reason?, sessionID?, aiUse, navigatorRequestID?, followUpTaskID?` | `POST /tasks/{id}/decisions` (sends `decision_id`, `new_formulation_id`, `follow_up_task_id`) | applies the decision table (http §3) and records `ReviewDecision` with an undo snapshot (and the follow-up's revision) |
| `undoDecision(DecisionID)` | — | `POST /review/decisions/{id}/undo` | restores the snapshot, removes the decision, deletes a created follow-up only if it is unchanged |
| `autoParkTask(AutoParkTask)` | `taskID, formulationID` | `POST /tasks/{id}/auto-park` | parks iff activated and the local evaluation is `park_due`; stores `clockBefore` |
| `bulkRelease(BulkRelease)` | `bulkID, kind, sessionID?, taskIDs` | `POST /review/bulk-releases` (sends `id`) | moves each eligible task to Someday (no park marker) and keeps its previous list and clock in the local bulk-release record |
| `undoBulkRelease(BulkID)` | — | `POST /review/bulk-releases/{id}/undo` | restores tasks whose state is unchanged, clock included |
| `review(ReviewCommand)` | see below | one request per case | mutates `GTDState.review` only |

Every client id a command carries is `<prefix>_<lowercased UUID>` (`review_`,
`decision_`, `bulk_`, `form_`, `task_`), the shape the server validates (http
"Client-supplied ids").

`ReviewCommand`: `acknowledgeExplainer(timeZone)` → `POST /review/explainer/acknowledge`
with the device zone (FR-051; the command writes only the activation instant in
`review.settings` — `local.activatedAt` when account-less — and nothing on any task; the
task clocks change only through the deterministic post-replay activation step of §3,
which runs because an activation instant is now known, so `review(…)` still mutates
`GTDState.review` only); `updateSettings(ReviewSettingsChange)` → `PUT /review/settings`
(a zone change is queued only when the device's own zone changed: the workspace
compares `TimeZone.current` with `local.lastObservedTimeZone` on load, on foreground
and on the system time-zone-change notification, queues `updateSettings(timeZone:)`
when they differ and then records the new zone; a pulled zone that differs from the
device's is never a reason to send, http §5; `lastObservedTimeZone` is first set to the
zone the device sends with the explainer acknowledgement or at onboarding, or, on a
device that sends neither, to its zone when it first loads the review state);
`acknowledgeParks([ParkAck])` → `POST /review/parks/acknowledge`;
`startSession(StartSession)` (carries the client `sessionID`) → `POST /review/sessions`
with `id` and `replace_open: true`;
`progressSession(SessionProgress)` → `PATCH /review/sessions/{id}`;
`finishSession(FinishSession)` → `POST /review/sessions/{id}/finish` (only Done on the
summary; leaving sends nothing but progress, FR-029);
`grantNavigatorConsent(provider)` / `revokeNavigatorConsent(provider)` →
`POST` / `DELETE /review/navigator/consent`.

New `GTDValidationError` cases (user-facing `message`, as today):
`decisionNotAllowed`, `extensionAlreadyUsed`, `extensionNotDue`,
`formulationChanged`, `undoUnavailable`, `projectArchived`.

**Exhaustive switches to update**: every exhaustive `switch` over `GTDCommand` in
`BrainBuddyCore` (reducer, replay, compaction), `BrainBuddySync` (sync mapping, push
planner, push engine) and the in-memory server in `BrainBuddyFakeServer`; adding the
cases makes the compiler enumerate them, so no line list is kept here.

## 3. Clock maintenance in existing cases

| existing case | added reducer rule |
|---|---|
| `createTask(list: .next)` | start a formulation at the command's `date` |
| `updateTask(changes.title = .set)` while in Next | substantive per `FormulationKey` → close + start; cosmetic → nothing |
| `updateTask(changes.dueDate ≠ .unchanged)` while in Next | `parkFloorAt = max(existing, date + 7 d)` |
| `transitionTask` into Next (move/reopen) | start a formulation; clear `parked` |
| `transitionTask` out of Next | close the formulation (stalled count rule) |
| `transitionTask` out of Someday | clear `parked` |
| `archiveProject` | unchanged (clears `projectID`, as today) |

Every case that starts a formulation mints `form_<UUID>` in the command (not in the
reducer, so replay is deterministic) and sends it as `new_formulation_id`
(http §1). Before local activation (below) the reducer still maintains clocks, but
classification returns `none` and nothing parks (formulation-clock §2).

**Activation step (FR-016, FR-051)**: activation is not an outbox operation of the
task stream. The reducer applies the formulation-clock §3 activation transition as a
deterministic **post-replay step keyed on the activation instant**: after replaying
the outbox onto `base`, if an activation instant is known (`base.review.settings.
activatedAt` pulled from the server when signed in; `local.activatedAt` for
account-less use), every Next task's clock is clamped to it and its floor raised to
`activatedAt + 14 d`. The same inputs therefore always give the same clocks, whatever
order operations were folded in.

**Compaction is clock-aware** (account-less correctness): replay applies each
operation at its `issuedAt`, and today `OutboxCompactor` folds a task edit into the
task's unsent creation and turns a later move into the creation's list. Folding would
move a later title change or move back to the creation instant and over-state the
formulation age, which, without an account, nothing would correct. So once the review
feature is exposed on the device, the compactor **does not fold** an `updateTask` that
changes the title, nor a `transitionTask`, into an unsent `createTask` of a task; other
folds (notes, tags, project, priority, subtasks, comments) stay as they are, because
they do not touch the clock. A Swift test asserts that, for every transition vector,
replaying the compacted outbox and replaying the uncompacted operations give identical
`formulation` fields.

Signed-in devices also receive the server's clock on every pull (`TaskDTO.formulation`
replaces the local value); a task the server has with a `null` clock classifies as
`none` locally until the server's repair arrives, so the device can never park it
early.

## 4. Replay, compaction and conflicts

- **Replay goal checks** (`.replay` mode, `ApplyOutcome.alreadySatisfied`):
  `autoParkTask` is satisfied when the task is not in Next or already parked for that
  formulation; `decideTask` is satisfied when a decision with its `decisionID` is
  already in `review.decisions`; `undoDecision` when the decision is absent;
  `acknowledgeParks` when every ack exists.
- **Compaction** (`OutboxCompactor`): an unsent `decideTask` followed by its
  `undoDecision` cancels both (and the created follow-up task); an unsent
  `bulkRelease` followed by its `undoBulkRelease` cancels both. Sent operations are
  never modified (existing rule).
- **409 stale on `decideTask`**: the existing refetch path (`SyncEngine+Push.swift`
  `handleFailure`/`refetch`) runs; after the refetched task is upserted, replay
  re-evaluates the decision. When the refetched task is parked for the decision's
  `formulationID` and the decision was made before `parked.at`, the decision is resent
  as is: the server's yield rule (http §3) accepts any `expected_revision` from
  `parked.from_revision` up to the current revision, so earlier queued plain edits
  replayed onto the parked task do not defeat it (a `ReviewSyncTests` case: offline
  notes edit, then offline card decision, server park between them → notes kept,
  decision applied with `yielded_auto_park: true`, zero sync issues). Only if the
  formulation itself changed is the operation set aside as a `SyncIssue` with its
  reference id and copy that names the task's **current** list from the refetched
  task, never an assumed one: "Your decision "<decision>" on "<title>" couldn't be
  saved to your account. It's in <current list> now." When that list is
  Someday because of an auto-park, the copy says "It moved to Someday / maybe
  automatically before your decision synced" and the task is listed on "While you
  were away" (design M-03 error rows).
- **`autoParkTask` returns `applied: false`**: acknowledged like a success; the
  pulled server task wins. `LocalReviewState.issuedAutoParks[taskID] = formulationID`
  prevents re-issuing for the same formulation, so a device whose clock runs ahead
  cannot loop (research R9).
- **Review commands never fall into the generic set-aside path** (today a
  `.staleRevision` whose `conflictTarget` is `nil` and every other 4xx are set aside,
  `SyncEngine+Push.swift`). `GTDCommand+Sync.swift` gains a `.review` conflict target
  whose refetch re-pulls `GET /review/state`, and each `ReviewCommand` has a stated rule:

  | command | server behaviour | device rule |
  |---|---|---|
  | `acknowledgeExplainer` | idempotent, first wins | always succeeds; pulled `activatedAt` replaces the local one |
  | `updateSettings` | 409 on `expected_revision` mismatch | refetch state, re-apply only the fields this change set (field-level last writer wins), resend with the new revision |
  | `acknowledgeParks` | idempotent, unknown ids ignored | always succeeds |
  | `startSession` | client `id`, `replace_open: true`; replay only by the same Idempotency-Key (the id is a label, http "Client-supplied ids"); the device keeps the key until success | never 409; if another device's open session was replaced, that device shows "review ended elsewhere" |
  | `progressSession` | merged, never 409 (http §6) | adopt the merged session; if its `current_step` differs, show "review moved on elsewhere" |
  | `finishSession` | idempotent | adopt the returned session |
  | `grant/revokeNavigatorConsent` | idempotent | revoke blocks locally at once |

  `decideTask` naming a session the server does not know is recorded without a session
  (http §3), so no decision is lost (SC-007).

- **Retry after the server's 24 h idempotency retention** (a lost response followed by
  a long offline window): the device keeps the operation and its Idempotency-Key as
  today and resends it. The server recognises a stored record that matches the retry
  and answers as for a first delivery (http "Retry after the idempotency retention"),
  so the device treats it as success; it is never set aside. Only a non-matching
  record answers `id_conflict`, which is set aside with its Ref as before.
  `ReviewSyncTests` and the golden trace "decision retried after the retention" cover
  it (0 sync issues, the decision applied once).

- **Feature turned off on the server** (rollback, cohort removal): every write a
  review command or `decideTask` / `undoDecision` / `autoParkTask` / `bulkRelease` /
  `undoBulkRelease` sends is accepted with the flag off (http "Gate"), so the outbox
  drains normally and nothing is set aside or reverted; `autoParkTask` gets
  `applied: false`. Defence in depth for the gated reads: a `404` whose
  `detail.reason` is `weekly_review_disabled` maps to a new `APIError.Kind`
  `.featureDisabled`, which `handleFailure` treats like `.rateLimited` (keep the
  operation and its key, back off, never set aside), and the workspace then hides the
  review UI (`MeDTO.featureFlags`) while keeping local review state. `ReviewSyncTests`:
  flag turned off with 3 queued review commands → 0 set-asides, 0 reverted decisions;
  flag back on → everything already applied. `ReviewSyncTests` cover: two devices start
  a review offline, both sync, 0 decisions lost; a settings edit queued while another
  device changed settings; a queued edit survives activation (activation does not bump
  `revision`, formulation-clock §2).

## 5. Auto-park on device

`Workspace` (`BrainBuddyWorkspace/Workspace.swift`) gains
`func applyDueAutoParks()`; it is called on load, on foreground
(`scenePhase == .active`), after each pull, and from the existing background refresh
task (`BrainBuddyApp.swift:43`). It queries `GTDQueries.dueAutoParks(in:now:settings:)`
and performs one `autoParkTask` per task via the private `perform(_:)`.

- Nothing parks before activation (FR-051): `dueAutoParks` is empty while no
  activation instant is known.
- Account-less: the park is final locally (FR-014).
- Signed in: `dueAutoParks` evaluates with `now + local.serverClockOffset` (the last
  observed `server_now − device time`, http §5), so a device clock that runs ahead or
  behind sees the server's due instant. **Online**, the device sends `autoParkTask`
  and applies the park locally only after `applied: true` (no M-09, no "Return to
  Next" on a task the server still holds in Next). **Offline**, the park stays
  optimistic, as designed, and pull reconciles. Two devices parking the same
  formulation both get 200 and one server park (US2-6). `ReviewSyncTests`: device
  clock 2 days ahead, online → no local park, no M-09 entry, no Return on a Next task.
- **Device-side safety valve** (no remote kill switch exists for account-less parks):
  one call applies at most 10 parks; when more are due, the rest wait until M-09 for
  the applied ones has been continued or closed, then the next call applies the next
  batch. Parks can only be later than due, never earlier, so FR-012 still holds in
  substance and a clock defect degrades to a visible prompt instead of mass parking.

`Workspace.runLocalReviewMaintenance()` runs at the same moments (load, foreground,
after pull, background refresh) and keeps the device copy within the server's
retention bounds, signed in or not: it closes local sessions idle ≥ 7 days (partial
or abandoned, data-model E3), nulls local decision undo snapshots and bulk-release
clock snapshots older than 7 days, and deletes form drafts (FR-052) older than 7 days.
- Widgets and intents never park (they open the workspace with `enableSync: false`
  and only read); the widget counts `park_due` tasks as "moves to Someday tomorrow"
  until the app applies the park.

## 6. Queries (`BrainBuddyCore/Queries+Review.swift`, new)

`GTDQueries.formulationClass(of:now:settings:timeZone:)`,
`decisionQueue(in:now:settings:)` (the `asks_for_decision` aggregate in the order of
formulation-clock §5), `dueAutoParks(in:now:settings:)`, `unseenParks(in:)`,
`restartCandidates(in:now:settings:)`, `wins(in:now:)` (completed in the last
7 days), `capacityMirror(in:now:)` (Next count; 4-week weekly average and implied
weeks only with ≥ 4 full weeks of history and ≥ 1 completion, else `nil`, FR-031),
`waitingDue(in:now:)`, `somedayDue(in:now:limit: 7)` (eligibility and order of
http §6), `projectsNeedingNextAction(in:)` (reuses `ProjectSummary.needsNextAction`,
`Queries.swift:183`), `datesAhead(in:today:days: 14)`,
`lastCountedReview(in:)` (completed and partial only), `askCount(in:now:settings:)`
(widget; the same aggregate as `decisionQueue`), `explainerNeeded(in:)` (FR-051).
The `timeZone` that classification uses is the owner's stored `time_zone` (the
formulation-clock owner input) when signed in, so a device sitting in another zone
classifies due-dated tasks exactly as the server parks them; account-less, it is the
device zone. Times shown to the person use the device zone.

Pure Core functions for behaviour that otherwise lives only in app or widget targets
(so it is Linux-testable, testability finding campaign 1):

- `ReviewReminderPlanner.nextFireDate(settings:lastCountedReview:now:timeZone:) -> Date?`
  — the FR-036 rule (one per week, skipped after a counted review in the preceding
  6 days, follows time-zone changes); the app's `ReviewReminderScheduler` only
  registers what it returns.
- `ReviewRoute.parse(_ url: URL) -> ReviewRoute?` and
  `ReviewEntryPlanner.start(for: .widgetDecisions, state:) -> [ReviewScreen]` — the
  deep link and the entry order of design.md (explainer, onboarding, While you were
  away, restart, then resume or a quick review at the decision step with Wins and Inbox
  skipped).
- `ModelDownloadMachine` (PR-09) — the download state machine (request-only start,
  progress, interruption and resume, insufficient storage, delete, never required for
  non-AI parts) behind injected `ModelDownloader` and `StorageProbe` protocols.
- `MarkerStyle.for(_ class:)` — the marker's text, icon and colour role, with a test
  that no age class maps to an error role (FR-004, FR-038).
- `ReviewCopy` — the catalog of every review-surface string the app and widget show
  (restart, summary, notification title and body, widget chip text and its VoiceOver
  label, M-02 "This wording" lines, While you were away, explainer). Views read their
  copy from it, and a Linux test checks every entry against the same banned-term list
  as the web string guard ("overdue" and streak wording, US5-6 / FR-004 / FR-038).
- `StallReasonRecommendation.decision(for:)` — the reason → recommended decision table
  of design M-03 (unclear → reformulate; too big, missing information, unpleasant / no
  energy → find a first step; waiting on someone → Waiting for; no longer matters →
  cancel), checked against the `stall_recommendation` section of
  `review_flow_vectors.json` (FR-007, US1-6); the web constant is checked against the
  same section.
- `ActiveTimeAccumulator` — the SC-004 active-time rule of data-model E3 with an
  injected clock (gap > 2 min counts 0, background never counts, per-step attribution,
  resume after leaving), checked against the `active_time` vectors.
- `UndoWindowPolicy.duration(voiceOver:switchControl:)` — about 5 s, at least 10 s when
  VoiceOver or Switch Control runs (FR-048, design "Undo (iOS)").
- `WhileAwayPresentation.shouldShowAtAppOpen(lastShownDay:today:hasUnseen:)` — the
  once-per-calendar-day rule of FR-015 (always shown as the first review screen
  regardless), with `local.wywaLastShownDay`.
- `NavigatorProposalFilter.dropDuplicates(_:projectOpenTitles:)` — drops a proposal
  whose `FormulationKey` equals that of any open task of the project in the local
  store, not only the 20 titles sent (FR-019; contracts/navigator.md §2 rule 5).

## 7. Persistence (`StoreDocument` v2)

`StoreDocument.currentVersion` becomes 2. `StoreDocumentCoding.migrationStep(from: 1)`
(`BrainBuddyPersistence/StoreDocumentCoding.swift:117`) adds an empty
`base.review`/`local` and sets `local.activatedAt = nil`, `local.formDrafts = [:]` and
`local.lastObservedTimeZone = nil` (§2 `updateSettings`).
Activation happens when the person first dismisses the auto-park explainer (M-26,
FR-051), never at migration: account-less, that instant is `local.activatedAt`;
signed in, the device queues `acknowledgeExplainer` and uses the server's
`activated_at` once pulled (an offline device that shows the explainer before learning
it was already seen elsewhere sends a harmless duplicate acknowledgement). Linking an
account-less install to an account sends `acknowledgeExplainer` if the device had
seen it and the account has no activation yet.

**Account linking and local auto-parks** (owner decision 2026-10-06, offline-sync
checklist CHK006; FR-014): the server re-evaluates a device park with its own clocks,
which for tasks it is only now receiving start at upload, so it would answer
`applied: false` and the pulled server task would move every account-less park back to
Next. So `Workspace.signIn`, before the store is uploaded, runs the pure Core step
`ReviewAccountLinking.convertLocalAutoParks(_:)` (`BrainBuddyCore/ReviewAccountLinking.swift`)
over the unsent outbox:

- every unsent `autoParkTask` becomes an ordinary `transitionTask` move to Someday at
  the same position and `issuedAt` (no park marker, no `clockBefore`; the formulation
  closes as for any move out of Next), so the server keeps the task in Someday;
- the converted parks count as seen: the device drops their local park markers and any
  unsent `acknowledgeParks` entries for them, so M-09 / "While you were away" does not
  offer them again on this or any device;
- every other queued operation — `decideTask`, `undoDecision`, sessions, bulk
  releases, settings, consent, park acknowledgements of other tasks — is kept as queued
  and pushed as usual under the ordinary rules of §4 (a decision the server rejects
  becomes a visible Sync issue with its Ref).

The step is deterministic and runs once per linking; a Swift test asserts that, after
linking and one sync against `BrainBuddyFakeServer`, every account-less park is in
Someday on the server with `parked` null, nothing is back in Next, and there are
0 sync issues.

`local.formDrafts: [DraftKey: String]` holds unsaved form text (FR-052), keyed by
form kind + task id + formulation id (or session id + step item, or project id for a
project's first next action, M-08 / M-19). It is never sent,
never part of an outbox operation and never logged; it is removed on save, discard,
formulation change, sign-out, or after 7 days. A v1 build that meets a v2 file reports
`.unsupportedVersion` (existing behaviour); the app and its widget extension ship in
one bundle, so they never disagree.

## 8. Feature exposure on device

Shown when signed in and `MeDTO.featureFlags["weekly_review"] == true`, or when
account-less and the build's Info.plist key `BBWeeklyReviewLocal` (new, in
`ios/project.yml`) is `YES`. Otherwise Lists keeps the existing `DeferredRow`
("coming later", `Screens/Browse/ListsHubScreen.swift:47-53`).

Because account-less parks have no server and no remote kill switch,
`BBWeeklyReviewLocal` is `NO` in the Release configuration (TestFlight and App Store)
until the synced path has run clean for at least one full threshold cycle (T + 7 days)
for the owner; it is `YES` only in Debug until then. Turning it on for Release is a
recorded owner decision at PR-14. The spec records this staged exposure (edge case
"Account-less iOS use", FR-042): until then account-less acceptance runs in Debug
builds and package tests, and Release account-less builds keep the `DeferredRow`.
