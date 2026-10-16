# Tasks: Mac Account and Settings window (⌘,)

**Input**: [spec.md](spec.md), [plan.md](plan.md), [design.md](design.md),
[intake.md](intake.md).

**Status**: draft slice map for owner approval. Implementation starts only after the
design sign-off and a `/speckit-review` verdict of `approved` or `founder-accepted`.
This file is portable planning input, not permission to implement, merge or deploy.

**Delivery gates** (non-negotiable, regardless of who executes these tasks): isolated
worktree and feature branch per slice; Constitution Principle II; tests name the
feature-qualified id (`028-FR-###` / `028-SC-###`, `028_FR_###` in Swift function
names); acceptance graded by an agent that did not write the code; landing class
decided by `scripts/classify_path_risk.py` — SHIP/SHOW land PR-less through verified
trunk (ADR-0008, ADR-0030; `AGENTS.md`). Each slice runs
`python3 scripts/check_slice_budget.py specs/028-mac-settings-account/tasks.md PR-NN`
before review.

**Tests (Principle II)**: reused — kit `ModernAuthTests`, `EndpointRequestTests`,
`ErrorMappingTests`; Mac `MacSyncFlowTests`, `SyncStatusPopoverModelTests`, the Carry On
snapshot suites. Necessary additions are named inside the tasks below. Test-first
applies to T005 (owner guard) and T010 (no partial export file); no other task carries
a dedicated test task.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel with other [P] tasks of the same slice (different files).
- **[USn]**: the user story in spec.md.
- Each task names its requirements and its PR slice.

---

## Phase 1 — Account read model and kit calls (PR-01)

- [ ] T001 [P] [US1] Add `AccountSummaryDTO` and `BrainBuddyAPIClient.accountSummary()`
  (`GET /account`) in `ios/BrainBuddyKit/Sources/BrainBuddyAPI/AccountAPI.swift`, with
  request-path and decoding tests (unknown fields ignored, null `display_name`) in
  `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AccountAPITests.swift`. 028-FR-006,
  028-FR-007, 028-FR-024. PR-01.
- [ ] T002 [P] [US4] Add `NativeAccountDestination.agentsURL(origin:)` in
  `ios/BrainBuddyKit/Sources/BrainBuddyAPI/NativeAuthCallback.swift` (same origin
  validation as `url(origin:ownerID:deleting:)`, path `/settings/agents`, no query),
  with accept/reject tests (https, localhost http, user info, path, query, fragment) in
  `AccountAPITests.swift`. 028-FR-019, 028-SC-006. PR-01.
- [ ] T003 [P] [US1] Add every design.md § Copy string as constants in
  `macos/Sources/BrainBuddyMacCore/AccountSettingsCopy.swift`. 028-FR-022. PR-01.
- [ ] T004 [US1] Implement `AccountSettingsModel` in
  `macos/Sources/BrainBuddyMacCore/AccountSettingsModel.swift`: phases notSignedIn /
  loading / loaded / offline / sessionEnded / failed, row strings for S-02.02 and
  S-02.03, concurrent reads, error mapping (no automatic retry on 429), `clear()`,
  memory-only state and redacted logging through `MacLogSink`. 028-FR-003, 028-FR-004,
  028-FR-006 – 028-FR-010, 028-FR-015 – 028-FR-018. PR-01.
- [ ] T005 [US5] Test-first: in `macos/Tests/BrainBuddyMacTests/AccountSettingsModelTests.swift`
  write the owner-guard tests (a late response for the previous account, or a DTO whose
  id differs from `workspace.account`, is discarded; `clear()` on sign-out and account
  change), then the row-mapping tests for every S-02 row value, the offline /
  session-ended / 429 / server-error states with reference, "Unavailable" when the
  methods read fails, a 401 leaving local tasks and unsent changes untouched, and a
  log-content test (no name, email or path). 028-FR-005 – 028-FR-010, 028-FR-016 –
  028-FR-018, 028-SC-005, 028-SC-006. PR-01.
- [ ] T006 [US4] Implement `AgentsWebLink` in
  `macos/Sources/BrainBuddyMacCore/AgentsWebLink.swift` (origin from `authMethods()` on
  the account server or the default server; ready / loading / unavailable) with tests
  in `macos/Tests/BrainBuddyMacTests/AgentsWebLinkTests.swift`. 028-FR-019. PR-01.

## Phase 2 — Export (PR-02)

- [ ] T007 [P] [US2] Add `AccountExport` and `BrainBuddyAPIClient.exportAccount()`
  (`GET /account/export`) in `ios/BrainBuddyKit/Sources/BrainBuddyAPI/AccountExportAPI.swift`,
  parsing the `Content-Disposition` file name (fallback `brainbuddy-export.zip`, path
  components stripped) with a redacted `description`. 028-FR-012, 028-FR-024. PR-02.
- [ ] T008 [P] [US2] Tests for T007 in
  `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AccountExportAPITests.swift`: path, file
  name parsing (quoted, RFC 5987 `filename*`, missing, `../` stripped), error mapping
  with reference id, cancellation. 028-FR-012, 028-FR-017. PR-02.
- [ ] T009 [US2] Implement `AccountExportFlow` in
  `macos/Sources/BrainBuddyMacCore/AccountExportFlow.swift`: exporting →
  choosingLocation(suggestedName) → saved / failed / idle, atomic write, `cancel()` that
  drops the bytes, failure kinds of design S-02.11, redacted logging. 028-FR-012,
  028-FR-013, 028-FR-017, 028-FR-018. PR-02.
- [ ] T010 [US2] Test-first: in `macos/Tests/BrainBuddyMacTests/AccountExportFlowTests.swift`
  write the no-partial-file tests (cancel during download, cancel at the panel, write
  failure into a read-only directory, failure after part of a write) before T009's
  write path, then the state and message tests. 028-FR-013, 028-SC-005. PR-02.

## Phase 3 — Settings scene and tabs (PR-03)

- [ ] T011 [US1] Add the `Settings` scene in
  `macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift` and
  `macos/Sources/BrainBuddyMac/Settings/MacSettingsView.swift` (tab bar Account, Agents,
  Sync; selection kept while the app runs; window title = tab name). Design S-01.
  028-FR-001, 028-FR-002, 028-FR-021. PR-03.
- [ ] T012 [P] [US1] Add the `account`, `agents` and `sync` glyphs from the M25 SVG
  paths to `macos/Sources/BrainBuddyMac/CarryOnMacIcons.swift`. 028-FR-002, 028-FR-022.
  PR-03.
- [ ] T013 [US1] Build the Account tab in
  `macos/Sources/BrainBuddyMac/Settings/AccountSettingsTab.swift` per design S-02 (all
  states, rows, footer, reload on window activation and account change, Export… with
  `NSSavePanel`, Sign out… and Sign in… / Sign in again… through the main window and
  the existing controller entries), design-system colors only, VoiceOver labels and
  values, keyboard order. 028-FR-003 – 028-FR-016, 028-FR-022, 028-FR-023. PR-03.
- [ ] T014 [P] [US4] Build the Agents tab in
  `macos/Sources/BrainBuddyMac/Settings/AgentsSettingsTab.swift` (design S-03, opening
  the URL with `NSWorkspace`). 028-FR-019. PR-03.
- [ ] T015 [P] [US4] Build the Sync tab in
  `macos/Sources/BrainBuddyMac/Settings/SyncSettingsTab.swift`, hosting the unchanged
  `SyncStatusPopover` (design S-04). 028-FR-020. PR-03.
- [ ] T016 [US1] Scene tests in `macos/Tests/BrainBuddyMacTests/MacSettingsSceneTests.swift`:
  three tabs in order; no Change…/Connect…/Remove…/Delete account… control or deletion
  row in any S-02 state; Sign out… from Settings increments the controller's sign-out
  request exactly as the menu does; hosting the Sync tab leaves the router's surface and
  focus requests unchanged. 028-FR-002, 028-FR-011, 028-FR-014, 028-FR-020, 028-SC-008.
  PR-03.

## Phase 4 — Snapshots and host evidence (PR-04)

- [ ] T017 [US1] Snapshot tests in `macos/Tests/BrainBuddyMacTests/SettingsSnapshotTests.swift`
  (pattern of `CarryOnSheetsSnapshotTests.swift`) for S-02.01, S-02.02 (M25 sample:
  Max, 214, verified, Apple connected, Google not, password set), S-02.03, S-02.05,
  S-02.06, S-02.09, S-02.11 and S-03.01, S-03.03, light and dark; renders committed
  under `macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-settings-*.png`. 028-FR-022,
  028-SC-007. PR-04.
- [ ] T018 [US1] Run `swift test` in `macos/` and the kit's `BrainBuddyAPITests` on a
  macOS 26 host at the candidate SHA and record the result in
  `specs/028-mac-settings-account/evidence/macos-host-run.md`. 028-SC-001, 028-SC-007.
  PR-04.

## Dependencies & Execution Order

- PR-01 and PR-02 have no dependencies and disjoint paths: run in parallel.
- PR-03 depends on both; the Settings window first appears complete in PR-03.
- PR-04 depends on PR-03.
- Manual acceptance after PR-04: SC-001 timing, SC-002 row comparison with the web
  account page, SC-003, SC-004 export comparison, SC-006 URL and log check, SC-007
  keyboard-only pass.

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The Account tab's read model and the agents destination work against the existing endpoints, with no UI yet",
      "tasks": ["T001", "T002", "T003", "T004", "T005", "T006"],
      "requirements": [
        "028-FR-003", "028-FR-004", "028-FR-005", "028-FR-006", "028-FR-007",
        "028-FR-008", "028-FR-009", "028-FR-010", "028-FR-015", "028-FR-016",
        "028-FR-017", "028-FR-018", "028-FR-019", "028-SC-005", "028-SC-006"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/AccountAPI.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/NativeAuthCallback.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AccountAPITests.swift",
        "macos/Sources/BrainBuddyMacCore/AccountSettingsCopy.swift",
        "macos/Sources/BrainBuddyMacCore/AccountSettingsModel.swift",
        "macos/Sources/BrainBuddyMacCore/AgentsWebLink.swift",
        "macos/Tests/BrainBuddyMacTests/AccountSettingsModelTests.swift",
        "macos/Tests/BrainBuddyMacTests/AgentsWebLinkTests.swift"
      ],
      "depends_on": [],
      "tests": [
        "cd ios/BrainBuddyKit && swift test --filter AccountAPITests",
        "cd macos && swift test --filter AccountSettingsModelTests",
        "cd macos && swift test --filter AgentsWebLinkTests"
      ],
      "acceptance": [
        "Every S-02 row value and state in design.md is produced by the model from fake remotes",
        "A response for another account is discarded and nothing is written to disk"
      ],
      "budget": {"product_loc": 350, "files": 5},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "The account export downloads and saves atomically, cancellable, with no partial file",
      "tasks": ["T007", "T008", "T009", "T010"],
      "requirements": ["028-FR-012", "028-FR-013", "028-FR-017", "028-FR-018", "028-SC-004", "028-SC-005"],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/AccountExportAPI.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/AccountExportAPITests.swift",
        "macos/Sources/BrainBuddyMacCore/AccountExportFlow.swift",
        "macos/Tests/BrainBuddyMacTests/AccountExportFlowTests.swift"
      ],
      "depends_on": [],
      "tests": [
        "cd ios/BrainBuddyKit && swift test --filter AccountExportAPITests",
        "cd macos && swift test --filter AccountExportFlowTests"
      ],
      "acceptance": [
        "Cancel during download, cancel at the panel and a failed write all leave no file",
        "The suggested file name comes from Content-Disposition with path components stripped"
      ],
      "budget": {"product_loc": 220, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "Cmd+, opens the Settings window with the Account, Agents and Sync tabs, complete",
      "tasks": ["T011", "T012", "T013", "T014", "T015", "T016"],
      "requirements": [
        "028-FR-001", "028-FR-002", "028-FR-011", "028-FR-014", "028-FR-020",
        "028-FR-021", "028-FR-022", "028-FR-023", "028-FR-024", "028-SC-003", "028-SC-008"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/BrainBuddyMacApp.swift",
        "macos/Sources/BrainBuddyMac/CarryOnMacIcons.swift",
        "macos/Sources/BrainBuddyMac/Settings",
        "macos/Tests/BrainBuddyMacTests/MacSettingsSceneTests.swift"
      ],
      "depends_on": ["PR-01", "PR-02"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter MacSettingsSceneTests",
        "cd macos && swift test --filter MacSyncFlowTests"
      ],
      "acceptance": [
        "Cmd+, opens one Settings window with Account, Agents, Sync; no follow-up control appears in any Account state",
        "Sign out from Settings runs the existing guard and confirmation on the main window"
      ],
      "budget": {"product_loc": 390, "files": 6},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "Settings renders are approved in light and dark and the macOS host run is recorded",
      "tasks": ["T017", "T018"],
      "requirements": ["028-FR-022", "028-SC-001", "028-SC-007"],
      "paths": [
        "macos/Tests/BrainBuddyMacTests/SettingsSnapshotTests.swift",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__",
        "specs/028-mac-settings-account/evidence/macos-host-run.md"
      ],
      "depends_on": ["PR-03"],
      "tests": [
        "cd macos && swift test --filter SettingsSnapshotTests"
      ],
      "acceptance": [
        "Snapshots match design.md S-02 and S-03 states in light and dark",
        "The host run names the SHA and the passing suites"
      ],
      "budget": {"product_loc": 1, "files": 1},
      "implementer": "mechanical-implementer"
    }
  ]
}
```

PR-04 changes only tests, renders and evidence, which do not count as product code;
its budget is the minimum the schema accepts.
