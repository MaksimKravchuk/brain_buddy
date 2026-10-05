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
    public var id: FormulationID          // client UUID until the server's id is pulled
    public var startedAt: Date
    public var extendedAt: Date?
    public var extensionReason: String?
    public var parkFloorAt: Date?
}
public struct ParkMarker: Hashable, Sendable, Codable {
    public var at: Date
    public var by: ParkOrigin            // .auto | .person
    public var formulationID: FormulationID
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
| `decideTask(DecideTask)` | `decisionID, taskID, type, formulationID?, stallReason?, title?, waitingFor?, reason?, sessionID?, aiUse, navigatorRequestID?, followUpTaskID?` | `POST /tasks/{id}/decisions` | applies the decision table (http §3) and records `ReviewDecision` with an undo snapshot |
| `undoDecision(DecisionID)` | — | `POST /review/decisions/{id}/undo` | restores the snapshot, removes the decision, deletes a created follow-up |
| `autoParkTask(AutoParkTask)` | `taskID, formulationID` | `POST /tasks/{id}/auto-park` | parks iff the local evaluation is `park_due` |
| `bulkRelease(BulkRelease)` | `bulkID, kind, sessionID?, taskIDs` | `POST /review/bulk-releases` | parks each eligible task with `by: .person` |
| `undoBulkRelease(BulkID)` | — | `POST /review/bulk-releases/{id}/undo` | restores tasks whose state is unchanged |
| `review(ReviewCommand)` | see below | one request per case | mutates `GTDState.review` only |

`ReviewCommand`: `updateSettings(ReviewSettingsChange)` → `PUT /review/settings`;
`acknowledgeParks([ParkAck])` → `POST /review/parks/acknowledge`;
`startSession(StartSession)` → `POST /review/sessions`;
`progressSession(SessionProgress)` → `PATCH /review/sessions/{id}`;
`finishSession(FinishSession)` → `POST /review/sessions/{id}/finish`;
`grantNavigatorConsent(provider)` / `revokeNavigatorConsent(provider)` →
`POST` / `DELETE /review/navigator/consent`.

New `GTDValidationError` cases (user-facing `message`, as today):
`decisionNotAllowed`, `extensionAlreadyUsed`, `extensionNotDue`,
`formulationChanged`, `undoUnavailable`, `projectArchived`.

**Exhaustive switches to update** (from the current code): `Reducer.swift:24`,
`Reducer+Replay.swift:39`, `Compaction.swift` (151, 267, 337), `Replay.swift`
(~185, 229), `BrainBuddySync/GTDCommand+Sync.swift` (18, 39, 68, 84, 116),
`BrainBuddySync/PushPlanner.swift:98` and `PlannedRequest.send` (:35),
`BrainBuddySync/SyncEngine+Push.swift` (353, 434), and the in-memory server in
`BrainBuddyFakeServer`.

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

Because replay re-applies each operation at its `issuedAt`
(`Replay.swift`), the clock is deterministic for account-less use, where the
compacted outbox is the only data.

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
  re-evaluates the decision. If the task's formulation changed, the operation is set
  aside as a `SyncIssue` with the M-03 error copy ("couldn't be saved to your account.
  The task is still in Next.") and its reference id. The server's auto-park yield
  rule (http §3) means a decision made offline before a server park is normally
  accepted rather than stale.
- **`autoParkTask` returns `applied: false`**: acknowledged like a success; the
  pulled server task wins. `LocalReviewState.issuedAutoParks[taskID] = formulationID`
  prevents re-issuing for the same formulation, so a device whose clock runs ahead
  cannot loop (research R9).

## 5. Auto-park on device

`Workspace` (`BrainBuddyWorkspace/Workspace.swift`) gains
`func applyDueAutoParks()`; it is called on load, on foreground
(`scenePhase == .active`), after each pull, and from the existing background refresh
task (`BrainBuddyApp.swift:43`). It queries `GTDQueries.dueAutoParks(in:now:settings:)`
and performs one `autoParkTask` per task via the private `perform(_:)`.

- Account-less: the park is final locally (FR-014).
- Signed in: the park is optimistic; the server decides (`applied`), and pull
  reconciles. Two devices parking the same formulation both get 200 and one server
  park (US2-6).
- Widgets and intents never park (they open the workspace with `enableSync: false`
  and only read); the widget counts `park_due` tasks as "moves to Someday tomorrow"
  until the app applies the park.

## 6. Queries (`BrainBuddyCore/Queries+Review.swift`, new)

`GTDQueries.formulationClass(of:now:settings:timeZone:)`,
`decisionQueue(in:now:settings:)` (oldest `ask_at` first),
`dueAutoParks(in:now:settings:)`, `unseenParks(in:)`,
`restartCandidates(in:now:settings:)`, `wins(in:now:)` (completed in the last
7 days), `capacityMirror(in:now:)` (Next count, 4-week weekly average, implied
weeks), `waitingDue(in:now:)`, `somedayDue(in:now:limit: 7)`,
`projectsNeedingNextAction(in:)` (reuses `ProjectSummary.needsNextAction`,
`Queries.swift:183`), `datesAhead(in:today:days: 14)`,
`lastCountedReview(in:)`, `askCount(in:now:settings:)` (widget).

## 7. Persistence (`StoreDocument` v2)

`StoreDocument.currentVersion` becomes 2. `StoreDocumentCoding.migrationStep(from: 1)`
(`BrainBuddyPersistence/StoreDocumentCoding.swift:117`) adds an empty
`base.review`/`local` and, for account-less documents, sets
`local.activatedAt = nil` (activation happens when the flag/build switch first shows
the feature, not at migration). A v1 build that meets a v2 file reports
`.unsupportedVersion` (existing behaviour); the app and its widget extension ship in
one bundle, so they never disagree.

## 8. Feature exposure on device

Shown when signed in and `MeDTO.featureFlags["weekly_review"] == true`, or when
account-less and the build's Info.plist key `BBWeeklyReviewLocal` (new, in
`ios/project.yml`) is `YES`. Otherwise Lists keeps the existing `DeferredRow`
("coming later", `Screens/Browse/ListsHubScreen.swift:47-53`).
