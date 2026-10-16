# Tasks: Mac agents

**Input**: [spec.md](spec.md), [plan.md](plan.md), [design.md](design.md),
[intake.md](intake.md).

**Status**: draft slice map for owner approval. Implementation starts only after the
design sign-off and a `/speckit-review` verdict of `approved` or `founder-accepted`.
Pending clarifications (a) – (c) carry recommended defaults; a different answer changes
only PR-04 ((a), (c)) or PR-10 ((b)). No slice changes `backend/` (D2). PR-07 and PR-10
also wait, outside this map, for 028 PR-03 (the Settings window, `Settings/AgentsSettingsTab.swift`
and the `agents` glyph). This file is portable planning input, not permission to
implement, merge or deploy.

**Delivery gates** (non-negotiable, regardless of who executes these tasks): isolated
worktree and feature branch per slice; Constitution Principle II; tests name the
feature-qualified id (`030-FR-###` / `030-SC-###`, `030_FR_###` in Swift function names);
acceptance graded by an agent that did not write the code; landing class decided by
`scripts/classify_path_risk.py` — SHIP/SHOW land through verified trunk (ADR-0008,
ADR-0030; `AGENTS.md`). Each slice runs
`python3 scripts/check_slice_budget.py specs/030-mac-agents/tasks.md PR-NN` and checks that
`git diff --stat origin/main -- backend/` is empty before review. `/verify-live` is never
part of a slice.

**Tests (Principle II)**: reused — kit `EndpointRequestTests`, `ErrorMappingTests`,
`ModernAuthTests`; Mac `AccountSettingsModelTests`, `AgentsWebLinkTests`,
`MacSyncFlowTests`, the Carry On snapshot suites; backend relay tests (run unchanged).
Necessary additions are named inside the tasks below. Test-first applies to T002
(secrets redacted), T005 (200-id batching), T007 (cache cleared and expiry), T010
(grouping table) and T015 (no run state changes a step).

**Shared kit and design**: the agent wrappers go in `ios/BrainBuddyKit` as public,
platform-neutral API so the iPhone app can reuse them. `BrainBuddyDesign` is owned by the
iOS thread; no slice edits it.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel with other [P] tasks of the same slice (different files).
- **[USn]**: the user story in spec.md.
- Each task names its requirements and its PR slice.

---

## Phase 1 — Kit: agent connections API (PR-01)

- [ ] T001 [US5] Add `AgentConnectionDTO` (with card, capabilities, controls, tier,
  disclosures, status, staleness, revision; lenient enums), `AgentAuthScheme` and the
  seven connection calls (`agentConnections`, `agentConnection(id:)`,
  `createAgentConnection`, `updateAgentConnection`, `testAgentConnection`,
  `replaceAgentCredential`, `disconnectAgentConnection`) to
  `ios/BrainBuddyKit/Sources/BrainBuddyAPI/AgentConnectionsAPI.swift`, each mutation with
  an `Idempotency-Key` and, where the server takes it, `expected_revision`. 030-FR-029 –
  030-FR-034, 030-FR-042. PR-01.
- [ ] T002 [US5] Test-first: in
  `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AgentConnectionsAPITests.swift` assert that
  request bodies carrying a credential or password never print it (`description`,
  `String(reflecting:)`), that `update` sends `current_password` only when given, the
  paths, methods and keys of every call, and decoding of fixtures copied field for field
  from `backend/app/schemas/agents.py` (ready, stale, unsupported, api key with header
  name). 030-FR-035, 030-FR-034. PR-01.
- [ ] T003 [P] [US5] Add `APIError.agentFailure` (`relayUnavailable` for 404 "External
  agent relay is not available.", `wrongPassword` for 403 on a password-bearing call,
  `staleRevision`, `rateLimited`, `offline`, `other`) in
  `ios/BrainBuddyKit/Sources/BrainBuddyAPI/AgentAPIError.swift`, with mapping tests in
  `AgentConnectionsAPITests.swift`; `APIError.from` unchanged. 030-FR-002, 030-FR-018,
  030-FR-034, 030-FR-042. PR-01.

## Phase 2 — Mac core: availability and memory cache (PR-03), copy (PR-13)

- [ ] T006 [P] [US2] Implement `AgentAvailability` in
  `macos/Sources/BrainBuddyMacCore/AgentAvailability.swift` (owner id, `relayEnabled` from
  `me().featureFlags["external_agent_relay"]`, password state from
  `accountAuthMethods().hasPassword` with `unknown` on failure, refresh at sign-in, on
  activation throttled to 5 minutes and on `relayUnavailable()`, the one-shot "show Add new
  agent" request), with tests in `macos/Tests/BrainBuddyMacTests/AgentAvailabilityTests.swift`
  over a fake remote. 030-FR-001, 030-FR-002, 030-FR-036. PR-03.
- [ ] T007 [US2] Test-first: in `macos/Tests/BrainBuddyMacTests/AgentMemoryCacheTests.swift`
  assert that the cache drops everything on `clear()` (sign-out, session end, account
  change), refuses a write for another owner, returns the expired marker and drops the
  content once `now ≥ contentExpiresAt` (also with no network), and that no type in it
  is `Codable`; then implement `macos/Sources/BrainBuddyMacCore/AgentMemoryCache.swift`.
  030-FR-026, 030-FR-027, 030-SC-005. PR-03.
- [ ] T008 [P] [US2] Add every string of design.md § Copy and the web's connection status
  words and sentences (ported from `frontend/src/features/agents/agentCopy.ts`) to
  `macos/Sources/BrainBuddyMacCore/AgentsCopy.swift`, with a parity test for the status
  words in `macos/Tests/BrainBuddyMacTests/AgentsCopyTests.swift`. 030-FR-030, 030-FR-041.
  PR-13 (split out of PR-03 to keep both within budget).
- [ ] T009 [US2] Add the log-content test in `AgentMemoryCacheTests.swift`: drive
  availability and cache with a known title, agent name, address, question, secret and
  password and assert none appears in the captured `MacLogSink` lines. 030-FR-039,
  030-SC-005. PR-03.

## Phase 3 — Kit: agent runs API (PR-02)

- [ ] T004 [US1] Add `AgentManifestDTO`, `AgentRunDTO`, `AgentRunEventDTO`,
  `AgentRunSummaryDTO` and `AgentPrimaryState` (15 labels plus `.unknown(String)`) and the
  run calls (`previewAgentHandoff`, `sendAgentHandoff`, `agentRuns(taskID:)`,
  `agentRunSummaries(taskIDs:)`, `agentRun(id:)`, `replyToAgentRun`,
  `checkAgentRunDelivery`, `cancelAgentRun`) and `APIError.needsManifestReview` (400 with
  `detail.reason` `manifest_not_reserved` or `manifest_token_mismatch`) to
  `ios/BrainBuddyKit/Sources/BrainBuddyAPI/AgentRunsAPI.swift`, with decoding and request
  tests in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AgentRunsAPITests.swift` against
  fixtures copied from the backend schemas (one run per label, a result link, a too-large
  result, a succession event, an expired run). 030-FR-005, 030-FR-017, 030-FR-019,
  030-FR-020, 030-FR-023, 030-FR-042. PR-02.
- [ ] T005 [US2] Test-first: in `AgentRunsAPITests.swift` assert that
  `agentRunSummaries` makes no request for no ids, one for 200, three for 450 (200, 200,
  50, in order, repeated `task_id` query items), merges the sparse maps and surfaces the
  first failing batch's error; then implement the batching. 030-FR-005, 030-SC-007. PR-02.

## Phase 4 — Mac core: Settings agents model and editors (PR-06)

- [ ] T018 [US5] Implement `AgentSettingsModel` in
  `macos/Sources/BrainBuddyMacCore/AgentSettingsModel.swift` (list without disconnected
  agents, selection, G-06.01 detail rows, Test again, loading/offline/failed/password-less
  phases, owner guard), with tests in
  `macos/Tests/BrainBuddyMacTests/AgentSettingsModelTests.swift`. 030-FR-029, 030-FR-030,
  030-FR-036, 030-FR-038. PR-06.
- [ ] T019 [US5] Implement `AgentConnectionEditor` in
  `macos/Sources/BrainBuddyMacCore/AgentConnectionEditor.swift` (Add = create, test,
  select; Replace credential; Edit with the password only when address or scheme changes;
  Delete; one Idempotency-Key per action reused on Try again; `expectedRevision`;
  wrong password, stale revision, 429 and relay-unavailable mapping; secrets cleared after
  each request and on dismiss). 030-FR-031 – 030-FR-035. PR-06.
- [ ] T020 [US5] Tests in `macos/Tests/BrainBuddyMacTests/AgentConnectionEditorTests.swift`:
  each action's request and outcome over a fake remote; name-only Edit sends no password;
  wrong password keeps the other fields and clears the password; a stale revision
  re-reads; a 429 is not retried; secrets are empty after success, failure and dismiss.
  030-FR-031 – 030-FR-035, 030-FR-038. PR-06.

## Phase 5 — Mac core: grouping and All runs store (PR-04)

- [ ] T010 [US2] Test-first: in `macos/Tests/BrainBuddyMacTests/AgentRunGroupTests.swift`
  assert the 030-FR-006 table for all 15 labels (Lost contact holds only Stopped
  reporting; "Agent no longer reports this run" is under To review with its full text),
  the group order, unknown labels, the canvas detail words (030-FR-007) and the compact
  Waiting for words (030-FR-010) at fixed `now` values; then implement
  `macos/Sources/BrainBuddyMacCore/AgentRunGroup.swift`. 030-FR-006, 030-FR-007,
  030-FR-010, 030-SC-003. PR-04.
- [ ] T011 [US2] Confirm that a synced step's server id is readable on both the Swift and
  the Rust-selected workspace; if the Rust path lacks a read accessor, add a read-only one
  in `macos/Sources/BrainBuddyMacCore/AgentRunsStore.swift`'s workspace adapter (no kit
  write path changes). 030-FR-005, 030-FR-013. PR-04.
- [ ] T012 [US2] Implement `AgentRunsStore` in
  `macos/Sources/BrainBuddyMacCore/AgentRunsStore.swift` (open steps with server ids →
  200-id summary batches → one run read per listed run; groups, per-agent counts,
  Waiting for rows; `lastUpdated`; phases; owner guard; cache writes through
  `AgentMemoryCache`). 030-FR-004, 030-FR-005, 030-FR-009, 030-FR-025, 030-FR-026,
  030-SC-007. PR-04.
- [ ] T013 [US3] Add polling to `AgentRunsStore.swift` with an injected clock (per-run at
  `observationIntervalSeconds` while on screen, 60 s summaries tick while visible, Sync now
  and post-action refresh, pause when hidden or offline, ended runs not polled) and tests
  in `macos/Tests/BrainBuddyMacTests/AgentRunsStoreTests.swift`, including 450 open steps
  → 3 summary requests and a stale notice when a batch fails. 030-FR-024, 030-FR-025,
  030-SC-004, 030-SC-007. PR-04.

## Phase 6 — Mac core: hand-off flow and run actions (PR-05)

- [ ] T014 [US1] Implement `HandoffFlow` in
  `macos/Sources/BrainBuddyMacCore/HandoffFlow.swift` (ready agents only; first selected;
  preview with details and "Project: <name>"; `needsPassword` only on
  `reauthenticationRequired`; acknowledgement only when required; one Idempotency-Key per
  Send reused on Try again; re-preview when `needsManifestReview` (400 with reason
  `manifest_not_reserved` / `manifest_token_mismatch`, never 409/410); error mapping;
  `relayUnavailable` → availability; on success insert the run into the store), with
  tests in `macos/Tests/BrainBuddyMacTests/HandoffFlowTests.swift`. 030-FR-013 –
  030-FR-018, 030-SC-001. PR-05.
- [ ] T015 [US4] Test-first: in `macos/Tests/BrainBuddyMacTests/AgentRunActionsTests.swift`
  feed a fake workspace through hand-off, polling, reply, stop, check again and every run
  label, and assert the workspace received no step command; then assert Mark step done
  issues exactly complete (and create in the same project in Next actions when the
  next-step text is non-empty). 030-FR-012, 030-FR-022, 030-SC-002. PR-05.
- [ ] T016 [US3] Implement `AgentRunActions` in
  `macos/Sources/BrainBuddyMacCore/AgentRunActions.swift` (reply ≤ 4,000 characters with
  `expectedRevision`, stop, check again with the password only when required, Mark step
  done and Make the next step through a `StepCommands` protocol over the existing
  workspace commands; disabled offline; nothing queued). 030-FR-020, 030-FR-022,
  030-FR-023, 030-FR-025. PR-05.
- [ ] T017 [P] [US3] Tests in `AgentRunActionsTests.swift` for reply pending, a withdrawn
  control, a stale revision on reply, offline refusal without queueing and check again's
  password path. 030-FR-020, 030-FR-023, 030-FR-025. PR-05.

## Phase 7 — Mac: sidebar, All runs canvas, Waiting for (PR-07)

- [ ] T021 [US2] Add `WorkspaceDestination.agentRuns(AgentRunsFilter)` in
  `macos/Sources/BrainBuddyMacCore/SidebarEntries.swift` (no kit query) and have
  `macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift` own `AgentAvailability`,
  `AgentMemoryCache` and `AgentRunsStore` for the signed-in account and clear them on
  sign-out and account change. 030-FR-001, 030-FR-026. PR-07.
- [ ] T022 [US2] In `macos/Sources/BrainBuddyMac/ContentView.swift` add the Agents sidebar
  section (G-01) between Lists and Dates with "All runs N", agent rows and "Add new
  agent" (opens Settings › Agents with the Add sheet through the availability request),
  and the `allRuns` glyph in `macos/Sources/BrainBuddyMac/CarryOnMacIcons.swift`.
  030-FR-002, 030-FR-004, 030-FR-036, 030-FR-041. PR-07.
- [ ] T023 [US2] Build G-02 in `macos/Sources/BrainBuddyMac/Agents/AgentRunsCanvas.swift`
  and `macos/Sources/BrainBuddyMac/Agents/AgentRunRow.swift` (header, groups, rows, agent
  filter, empty/loading/stale/failed states), and G-03 in `ContentView.swift` (Agents group
  above People, header "<n> people, <m> agents", sidebar count n + m, unchanged without
  runs; run rows select the step and offer no task actions). 030-FR-003, 030-FR-007 –
  030-FR-011, 030-FR-025, 030-FR-041. PR-07.
- [ ] T024 [US2] Scene tests in `macos/Tests/BrainBuddyMacTests/AgentsSceneTests.swift`:
  no Agents section signed out; section and "Add new agent" per flag and password state;
  the Waiting for count and groups; selecting a run row selects the step without moving
  it. 030-FR-001, 030-FR-002, 030-FR-004, 030-FR-009, 030-FR-011, 030-SC-006. PR-07.

## Phase 8 — Mac: run section in the inspector (PR-08)

- [ ] T025 [US3] Build G-05 in `macos/Sources/BrainBuddyMac/Agents/AgentRunSection.swift`
  (timeline, Needs you with Reply / Stop run, running, queued, result with Mark step done /
  Make the next step / Hand off again, failed, stopped reporting, other labels, expired,
  delivery unconfirmed with Check again, offline, earlier runs, succession line; agent
  text as plain text only) and host it in
  `macos/Sources/BrainBuddyMac/TaskInspector.swift` through
  `macos/Sources/BrainBuddyMac/ContentView.swift`. 030-FR-019 – 030-FR-023, 030-FR-025,
  030-FR-027, 030-FR-028, 030-FR-041. PR-08.
- [ ] T026 [US4] Tests in `macos/Tests/BrainBuddyMacTests/AgentRunSectionTests.swift`: each
  label shows its block; withdrawn controls are absent; a result link is not a link;
  Markdown and HTML in agent text show literally; expired content never renders; keyboard
  order and accessible names. 030-FR-020, 030-FR-021, 030-FR-027, 030-FR-028, 030-FR-040.
  PR-08.

## Phase 9 — Mac: hand-off sheet (PR-09)

- [ ] T027 [US1] Build G-04 in `macos/Sources/BrainBuddyMac/Agents/HandoffSheet.swift`
  (agent rows, What it will get, disclosures, conditional password and acknowledgement,
  Send to <agent> / Cancel, sending, wrong password, failed, no ready agent, offline) and
  enable Hand off… and Hand off again in `macos/Sources/BrainBuddyMac/TaskInspector.swift`
  (disabled with "This step hasn't reached your account yet." without a server id; hidden
  with the flag off), presenting the sheet from
  `macos/Sources/BrainBuddyMac/ContentView.swift`. 030-FR-013 – 030-FR-018, 030-FR-040,
  030-FR-041. PR-09.
- [ ] T028 [US1] Tests in `macos/Tests/BrainBuddyMacTests/HandoffSheetTests.swift`: three
  interactions from a selected step to Send without a password; the password field and
  acknowledgement appear only when required; Return sends and Esc cancels; the flag
  turning off closes the sheet. 030-FR-013, 030-FR-016, 030-FR-040, 030-SC-001. PR-09.

## Phase 10 — Mac: Settings › Agents tab (PR-10)

- [ ] T029 [US5] Replace the content of
  `macos/Sources/BrainBuddyMac/Settings/AgentsSettingsTab.swift` (028) with G-06 when the
  flag is on and the account is signed in — list with + and −, details in
  `macos/Sources/BrainBuddyMac/Settings/AgentDetailsView.swift`, Test again, the
  password-less line with "Open account on the web…", offline and failed states — and
  keep 028's content unchanged with the flag off or signed out. 030-FR-025, 030-FR-029,
  030-FR-030, 030-FR-036, 030-FR-037, 030-FR-038. PR-10.
- [ ] T030 [US5] Tests in `macos/Tests/BrainBuddyMacTests/AgentsSettingsTabTests.swift`:
  flag off shows 028's text and link; password-less shows the line and no +; the web
  account URL carries no credential; the sidebar's "Add new agent" request opens the Add
  sheet once. 030-FR-036, 030-FR-037, 030-SC-006. PR-10.

## Phase 11 — Mac: Add, Replace, Edit, Delete sheets (PR-11)

- [ ] T031 [US5] Build G-07 in `macos/Sources/BrainBuddyMac/Settings/AddAgentSheet.swift`
  and G-08 in `macos/Sources/BrainBuddyMac/Settings/AgentConnectionSheets.swift` (secure
  fields, conditional password on Edit, "Delete <name>?" with Cancel as default, error
  lines, Return and Esc). 030-FR-031 – 030-FR-035, 030-FR-040, 030-FR-041. PR-11.
- [ ] T032 [US5] Tests in `macos/Tests/BrainBuddyMacTests/AgentSheetsTests.swift`: Add and
  test is disabled until every field is filled; Edit shows the password only after the
  address or type changes; Delete is never the default button; closing a sheet empties the
  secure fields. 030-FR-031 – 030-FR-035, 030-FR-040. PR-11.

## Phase 12 — Snapshots and host evidence (PR-12)

- [ ] T033 [US2] Snapshot tests in `macos/Tests/BrainBuddyMacTests/AgentsSnapshotTests.swift`
  with `assertMacSnapshot` for G-01.03, G-02.01, G-03.01, G-04.02, G-04.03, G-05.01,
  G-05.06, G-05.08, G-05.09, G-06.01, G-06.04 and G-07.01, light and dark; renders
  committed under `macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-agents-*.png` after
  comparison with board cells M21 – M24, M29 and M30. 030-FR-041, 030-SC-009. PR-12.
- [ ] T034 [US2] Run `swift test` in `macos/` and the kit's `BrainBuddyAPITests` on a macOS
  26 host at the candidate SHA, do the keyboard-only and VoiceOver pass, and record both in
  `specs/030-mac-agents/evidence/macos-host-run.md`. 030-SC-008, 030-SC-009. PR-12.

## Dependencies & Execution Order

- PR-01, PR-03 and PR-13 have no dependencies and disjoint paths: run in parallel.
- PR-02 depends on PR-01. PR-06 depends on PR-01, PR-03 and PR-13; it runs in parallel with
  PR-02, PR-04 and PR-05.
- PR-04 depends on PR-02, PR-03 and PR-13. PR-05 depends on PR-04.
- PR-07 depends on PR-04 and, outside this map, on 028 PR-03.
- PR-08 depends on PR-05 and PR-07. PR-09 depends on PR-08.
- PR-10 depends on PR-06 and PR-07 and, outside this map, on 028 PR-03; it runs in
  parallel with PR-08 and PR-09. PR-11 depends on PR-10.
- PR-12 depends on PR-07, PR-09 and PR-11.
- Manual acceptance after PR-12: SC-001, SC-004 – SC-006, SC-008 against a test agent.

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The shared kit can list, read, add, edit, test, re-credential and disconnect agents, with secrets redacted and the relay's wrong-password and unavailable answers typed",
      "tasks": ["T001", "T002", "T003"],
      "requirements": [
        "030-FR-002", "030-FR-018", "030-FR-029", "030-FR-030", "030-FR-031",
        "030-FR-032", "030-FR-033", "030-FR-034", "030-FR-035", "030-FR-042", "030-SC-010"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/AgentConnectionsAPI.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/AgentAPIError.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AgentConnectionsAPITests.swift"
      ],
      "depends_on": [],
      "tests": [
        "cd ios/BrainBuddyKit && swift test --filter AgentConnectionsAPITests",
        "cd ios/BrainBuddyKit && swift test --filter ErrorMappingTests",
        "sh ios/scripts/swift-linux.sh test --filter AgentConnectionsAPITests"
      ],
      "acceptance": [
        "Every connection call sends the documented method, path, body and Idempotency-Key, and no credential or password appears in any description",
        "404 relay-unavailable and 403 wrong-password map to typed agent failures while APIError.from is unchanged"
      ],
      "budget": {"product_loc": 320, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "Mac core knows the owner, the relay flag and the password state, and keeps agent data only in an owner-keyed memory cache that clears on sign-out and hides expired content",
      "tasks": ["T006", "T007", "T009"],
      "requirements": [
        "030-FR-001", "030-FR-002", "030-FR-026", "030-FR-027",
        "030-FR-036", "030-FR-039", "030-SC-005"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/AgentAvailability.swift",
        "macos/Sources/BrainBuddyMacCore/AgentMemoryCache.swift",
        "macos/Tests/BrainBuddyMacTests/AgentAvailabilityTests.swift",
        "macos/Tests/BrainBuddyMacTests/AgentMemoryCacheTests.swift"
      ],
      "depends_on": [],
      "tests": [
        "cd macos && swift test --filter AgentAvailabilityTests",
        "cd macos && swift test --filter AgentMemoryCacheTests"
      ],
      "acceptance": [
        "The flag and password state refresh on sign-in, activation and a relay-unavailable answer; unknown password state keeps controls",
        "The cache refuses other owners, clears on sign-out and account change, never returns expired content and writes nothing to disk or logs"
      ],
      "budget": {"product_loc": 260, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-13",
      "outcome": "Mac core holds every agent string from design.md and the web's connection status words and sentences, word for word",
      "tasks": ["T008"],
      "requirements": ["030-FR-030", "030-FR-041"],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/AgentsCopy.swift",
        "macos/Tests/BrainBuddyMacTests/AgentsCopyTests.swift"
      ],
      "depends_on": [],
      "tests": [
        "cd macos && swift test --filter AgentsCopyTests"
      ],
      "acceptance": [
        "Every design.md copy string exists once, and the connection status words and sentences match frontend agentCopy.ts"
      ],
      "budget": {"product_loc": 160, "files": 1},
      "implementer": "mechanical-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "The shared kit can preview and send a hand-off, read runs per step, read latest-run summaries in 200-id batches, read one run, reply, check again and stop",
      "tasks": ["T004", "T005"],
      "requirements": [
        "030-FR-005", "030-FR-017", "030-FR-019", "030-FR-020", "030-FR-023",
        "030-FR-042", "030-SC-007"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/AgentRunsAPI.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AgentRunsAPITests.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": [
        "cd ios/BrainBuddyKit && swift test --filter AgentRunsAPITests",
        "sh ios/scripts/swift-linux.sh test --filter AgentRunsAPITests"
      ],
      "acceptance": [
        "Every run label, a result link, a too-large result, a succession event and an expired run decode from backend-shaped fixtures; unknown labels decode leniently",
        "450 task ids produce exactly three summary requests of 200, 200 and 50 ids"
      ],
      "budget": {"product_loc": 380, "files": 1},
      "implementer": "mechanical-implementer"
    },
    {
      "id": "PR-06",
      "outcome": "Mac core lists agents with their M29 details and runs Test again, Add, Replace credential, Edit and Delete with the password exactly where the server needs it",
      "tasks": ["T018", "T019", "T020"],
      "requirements": [
        "030-FR-029", "030-FR-030", "030-FR-031", "030-FR-032", "030-FR-033",
        "030-FR-034", "030-FR-035", "030-FR-036", "030-FR-038"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/AgentSettingsModel.swift",
        "macos/Sources/BrainBuddyMacCore/AgentConnectionEditor.swift",
        "macos/Tests/BrainBuddyMacTests/AgentSettingsModelTests.swift",
        "macos/Tests/BrainBuddyMacTests/AgentConnectionEditorTests.swift"
      ],
      "depends_on": ["PR-01", "PR-03", "PR-13"],
      "tests": [
        "cd macos && swift test --filter AgentSettingsModelTests",
        "cd macos && swift test --filter AgentConnectionEditorTests"
      ],
      "acceptance": [
        "Detail rows match the connection fields and the web's status words; name-only Edit sends no password",
        "Wrong password, stale revision and 429 are handled in words without automatic retry, and secrets are empty after every outcome"
      ],
      "budget": {"product_loc": 380, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "Mac core assembles every open step's latest run from batched summaries and run reads, groups them as M22 with Lost contact meaning only Stopped reporting, and polls them at their interval",
      "tasks": ["T010", "T011", "T012", "T013"],
      "requirements": [
        "030-FR-004", "030-FR-005", "030-FR-006", "030-FR-007", "030-FR-009",
        "030-FR-010", "030-FR-013", "030-FR-024", "030-FR-025", "030-FR-026",
        "030-SC-003", "030-SC-004", "030-SC-007"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/AgentRunGroup.swift",
        "macos/Sources/BrainBuddyMacCore/AgentRunsStore.swift",
        "macos/Tests/BrainBuddyMacTests/AgentRunGroupTests.swift",
        "macos/Tests/BrainBuddyMacTests/AgentRunsStoreTests.swift"
      ],
      "depends_on": ["PR-02", "PR-03", "PR-13"],
      "tests": [
        "cd macos && swift test --filter AgentRunGroupTests",
        "cd macos && swift test --filter AgentRunsStoreTests"
      ],
      "acceptance": [
        "All 15 labels land in the 030-FR-006 groups with the 030-FR-007 and 030-FR-010 words",
        "Polling follows each run's interval with a test clock, pauses hidden or offline, and 450 open steps cost three summary requests"
      ],
      "budget": {"product_loc": 380, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-05",
      "outcome": "Mac core hands a step off with the password and acknowledgement only when required, replies, stops, checks again, and changes a step only through Mark step done and Make the next step",
      "tasks": ["T014", "T015", "T016", "T017"],
      "requirements": [
        "030-FR-012", "030-FR-013", "030-FR-014", "030-FR-015", "030-FR-016",
        "030-FR-017", "030-FR-018", "030-FR-020", "030-FR-022", "030-FR-023",
        "030-FR-025", "030-SC-001", "030-SC-002"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/HandoffFlow.swift",
        "macos/Sources/BrainBuddyMacCore/AgentRunActions.swift",
        "macos/Tests/BrainBuddyMacTests/HandoffFlowTests.swift",
        "macos/Tests/BrainBuddyMacTests/AgentRunActionsTests.swift"
      ],
      "depends_on": ["PR-04"],
      "tests": [
        "cd macos && swift test --filter HandoffFlowTests",
        "cd macos && swift test --filter AgentRunActionsTests"
      ],
      "acceptance": [
        "No hand-off, poll, reply, stop or run label issues a step command; Mark step done issues complete plus an optional create in the same project",
        "One Idempotency-Key per Send reused on Try again; a stale manifest is re-previewed, never sent"
      ],
      "budget": {"product_loc": 360, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-07",
      "outcome": "The Mac sidebar shows Agents with All runs and per-agent rows, the All runs canvas groups runs as M22, and Waiting for shows an Agents group above People without moving any step",
      "tasks": ["T021", "T022", "T023", "T024"],
      "requirements": [
        "030-FR-001", "030-FR-002", "030-FR-003", "030-FR-004", "030-FR-007",
        "030-FR-008", "030-FR-009", "030-FR-010", "030-FR-011", "030-FR-025",
        "030-FR-026", "030-FR-036", "030-FR-041", "030-SC-006"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/SidebarEntries.swift",
        "macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Sources/BrainBuddyMac/CarryOnMacIcons.swift",
        "macos/Sources/BrainBuddyMac/Agents/AgentRunsCanvas.swift",
        "macos/Sources/BrainBuddyMac/Agents/AgentRunRow.swift",
        "macos/Tests/BrainBuddyMacTests/AgentsSceneTests.swift"
      ],
      "depends_on": ["PR-04"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter AgentsSceneTests",
        "cd macos && swift test --filter WeeklyReviewRowTests",
        "cd macos && swift test --filter MacSyncFlowTests"
      ],
      "acceptance": [
        "Signed out there is no Agents section; signed in the section, counts and Add new agent follow the flag and password state",
        "Waiting for shows Agents above People with n + m in the sidebar, and is unchanged when no run is listed"
      ],
      "budget": {"product_loc": 400, "files": 6},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-10",
      "outcome": "With the flag on, Settings › Agents shows the M29 list and details with Test again; password-less accounts see the password line; with the flag off the tab is 028's unchanged",
      "tasks": ["T029", "T030"],
      "requirements": [
        "030-FR-025", "030-FR-029", "030-FR-030", "030-FR-036", "030-FR-037",
        "030-FR-038", "030-SC-006"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/Settings/AgentsSettingsTab.swift",
        "macos/Sources/BrainBuddyMac/Settings/AgentDetailsView.swift",
        "macos/Tests/BrainBuddyMacTests/AgentsSettingsTabTests.swift"
      ],
      "depends_on": ["PR-06", "PR-07"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter AgentsSettingsTabTests",
        "cd macos && swift test --filter AgentsWebLinkTests"
      ],
      "acceptance": [
        "Flag off shows 028's text and link unchanged; flag on shows the list, details and Test again",
        "A password-less account sees the line and Open account on the web… with no credential in the URL, and no +"
      ],
      "budget": {"product_loc": 300, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-08",
      "outcome": "A step's inspector shows its latest run with the timeline, Needs you with Reply and Stop run, the result with Mark step done and Make the next step, and every other state in words",
      "tasks": ["T025", "T026"],
      "requirements": [
        "030-FR-019", "030-FR-020", "030-FR-021", "030-FR-022", "030-FR-023",
        "030-FR-025", "030-FR-027", "030-FR-028", "030-FR-040", "030-FR-041"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/Agents/AgentRunSection.swift",
        "macos/Sources/BrainBuddyMac/TaskInspector.swift",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Tests/BrainBuddyMacTests/AgentRunSectionTests.swift"
      ],
      "depends_on": ["PR-05", "PR-07"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter AgentRunSectionTests",
        "cd macos && swift test --filter CarryOnInspectorSnapshotTests"
      ],
      "acceptance": [
        "Each label shows its block with only the controls the run offers, agent text is inert, and expired content never renders",
        "The step stays in its list until Mark step done; the existing inspector snapshots are unchanged for steps without runs"
      ],
      "budget": {"product_loc": 360, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-11",
      "outcome": "Add new agent, Replace credential, Edit and Delete sheets work from Settings › Agents with secure fields and the password where required",
      "tasks": ["T031", "T032"],
      "requirements": [
        "030-FR-031", "030-FR-032", "030-FR-033", "030-FR-034", "030-FR-035",
        "030-FR-040", "030-FR-041"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/Settings/AddAgentSheet.swift",
        "macos/Sources/BrainBuddyMac/Settings/AgentConnectionSheets.swift",
        "macos/Tests/BrainBuddyMacTests/AgentSheetsTests.swift"
      ],
      "depends_on": ["PR-10"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter AgentSheetsTests"
      ],
      "acceptance": [
        "Add and test creates, tests and selects the agent; Edit asks for the password only after a destination change",
        "Delete is never the default button and closing any sheet empties its secure fields"
      ],
      "budget": {"product_loc": 360, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-09",
      "outcome": "From a step's card the person hands it to a ready agent in three interactions, seeing exactly what the agent gets, with the password and acknowledgement only when the server asks",
      "tasks": ["T027", "T028"],
      "requirements": [
        "030-FR-013", "030-FR-014", "030-FR-015", "030-FR-016", "030-FR-017",
        "030-FR-018", "030-FR-040", "030-FR-041", "030-SC-001"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/Agents/HandoffSheet.swift",
        "macos/Sources/BrainBuddyMac/TaskInspector.swift",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Tests/BrainBuddyMacTests/HandoffSheetTests.swift"
      ],
      "depends_on": ["PR-08"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter HandoffSheetTests"
      ],
      "acceptance": [
        "Hand off…, choose agent, Send reaches the server with no password field unless the preview requires one",
        "Unsynced steps show Hand off… disabled with its reason; with the flag off no hand-off control exists"
      ],
      "budget": {"product_loc": 260, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-12",
      "outcome": "Agent renders are approved against M21 – M24, M29 and M30 in light and dark and the macOS host run is recorded",
      "tasks": ["T033", "T034"],
      "requirements": ["030-FR-041", "030-SC-008", "030-SC-009"],
      "paths": [
        "macos/Tests/BrainBuddyMacTests/AgentsSnapshotTests.swift",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__",
        "specs/030-mac-agents/evidence/macos-host-run.md"
      ],
      "depends_on": ["PR-07", "PR-09", "PR-11"],
      "tests": [
        "cd macos && swift test --filter AgentsSnapshotTests"
      ],
      "acceptance": [
        "Snapshots match the design.md G- states listed in T033 in light and dark",
        "The host run names the SHA, the passing suites and the keyboard and VoiceOver pass"
      ],
      "budget": {"product_loc": 1, "files": 1},
      "implementer": "mechanical-implementer"
    }
  ]
}
```

PR-12 changes only tests, renders and evidence, which do not count as product code; its
budget is the minimum the schema accepts. No slice changes `backend/` (D2) or
`BrainBuddyDesign` (owned by the iOS thread).
