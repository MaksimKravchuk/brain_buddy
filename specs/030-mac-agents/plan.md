# Implementation Plan: Mac agents

**Branch**: `030-mac-agents` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/030-mac-agents/spec.md`; agreed requirements
in [intake.md](intake.md) (Max's decisions D1 – D9, 2026-10-16; pending (a) – (c) with
recommended defaults); design in [design.md](design.md) (G-01 – G-08 from board cells
M21 – M24, M29, M30 and DSAgents). Research: `/mnt/project-files/design/mac-feature8-groundwork.md`.

## Summary

Three layers, each consuming the one below, with no backend change:

1. **Shared kit** (`ios/BrainBuddyKit/Sources/BrainBuddyAPI/`): additive, platform-neutral
   Swift wrappers for the relay API of specs 007/014 — agent connections (list, read, add,
   edit, test, replace credential, disconnect) and agent runs (preview, send, per-step
   runs, summaries batched at 200 ids, one run, reply, check again, stop) — plus a typed
   reading of the two relay-specific failures (wrong password, relay unavailable). The
   iPhone can reuse them unchanged.
2. **Mac core** (`macos/Sources/BrainBuddyMacCore/`, Foundation-only, no UI): the flag and
   password availability, an owner-keyed memory-only cache with expiry, the run grouping
   table, the All runs store that assembles runs from summaries and run reads and polls
   them, the hand-off and run-action flows, and the Settings agents model and editors.
3. **Mac app** (`macos/Sources/BrainBuddyMac/`): the sidebar section, All runs canvas and
   Waiting for group (G-01 – G-03), the inspector run section (G-05), the hand-off sheet
   (G-04), and the Settings › Agents tab with its sheets (G-06 – G-08), all with shared
   `BrainBuddyDesign` controls and `CarryOnMacIcons` glyphs.

## Technical Context

**Language/Version**: Swift 6 (language mode 6), macOS 26; shared kit `ios/BrainBuddyKit`
(iOS 26 / macOS 26, Linux-testable `BrainBuddyAPI`).
**Primary Dependencies**: SwiftUI, AppKit; kit products `BrainBuddyAPI`,
`BrainBuddyWorkspace`, `BrainBuddyDesign` (consumed, not changed).
**Storage**: none new. Run content, connection details, drafts, secrets and passwords are
memory-only (030-FR-026). No server schema or migration.
**Testing**: Swift Testing in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests` (CI `ios-kit`,
Linux and macOS) and `macos/Tests/BrainBuddyMacTests` (CI `macos-app`, plus a recorded
macOS-host run); snapshots through `assertMacSnapshot`. The backend relay suites run
unchanged.
**Target Platform**: macOS 26; production backend (Python today, Rust after 027 — both
serve the same relay routes).
**Project Type**: native client feature over an existing server contract.
**Performance Goals**: 030-SC-004 (state change visible within the observation interval
+ 5 s); 030-SC-007 (3 summary requests for 450 open steps).
**Constraints**: no change under `backend/` (D2, 027-FR-022; 030-SC-010); no new endpoint
(D3); no change to `BrainBuddyDesign` (owned by the iOS thread); kit additions additive.
**Scale/Scope**: 8 surfaces, ~3,400 product lines over 12 slices.

## Constitution Check

*Pre-design: pass. Re-checked after design: pass.*

- **Spec workflow**: spec.md is current; Max's decisions D1 – D9 are in spec
  Clarifications and intake.md; pending (a) – (c) carry recommended defaults and name
  the slice each changes. The full path applies (significant new capability on a new
  surface, consuming a cross-surface contract).
- **Consent & Safety (I)**: handing off is an explicit act after the manifest preview
  shows exactly what leaves BrainBuddy (030-FR-015). The Current password is asked where
  the server requires it (D2) and never stored (030-FR-035). Agent text is inert
  (030-FR-028); result links are never opened or fetched. Run content is memory-only,
  owner-keyed and cleared on sign-out, session end and account change (030-FR-026),
  which meets spec 007 FR-018 without a disk cache to encrypt. The 30-day expiry is
  enforced on every render (030-FR-027; spec 007 FR-015).
- **Tests (II)**: reused — kit `EndpointRequestTests`, `ErrorMappingTests`,
  `ModernAuthTests` (`accountAuthMethods`), the Mac `AccountSettingsModelTests` and
  `AgentsWebLinkTests` (028), `MacSyncFlowTests` (sign-out clears state), the Carry On
  snapshot suites; backend relay tests unchanged. Necessary additions at the cheapest
  reliable level: kit request/decoding tests against fixtures copied from the backend
  schemas (no network); Foundation-only Mac core tests for availability, cache, grouping,
  store, flows and editors over fake remotes and a test clock; thin scene tests for
  wiring; snapshots for the designed states. Test-first applies to five invariants that
  are new code: the grouping table with Lost contact = Stopped reporting only
  (030-FR-006); no run state changes a step (030-FR-012, 030-SC-002); the cache is cleared
  on sign-out/account change and never shows expired content (030-FR-026, 030-FR-027);
  summaries are batched at 200 ids (030-SC-007); secrets and passwords never appear in a
  description or log line (030-FR-035, 030-FR-039). Swift test names carry the qualified
  ids (`030_FR_006` / `"030-FR-006 …"`). No Allure taxonomy applies (Swift tests are
  outside the pytest/Vitest/Playwright rule).
- **Contracts (III)**: no server contract change. Kit additions are new public types and
  methods; `APIError.from` is not changed — the relay-specific readings are an additive
  `APIError` extension used only by the agent wrappers, so iPhone behaviour is unchanged
  (030-FR-042). Unknown future state labels decode leniently and show verbatim.
- **Observability (IV)**: every kit request already carries `X-Correlation-ID`; models
  keep `APIError.referenceID` and show it as "Reference: …" (030-FR-038). Mac logs go
  through `MacLogSink` with stage, outcome, status class, duration and reference only
  (030-FR-039); a log-content test asserts no title, agent name, address, text, secret or
  password appears.
- **Mobile/resilience/performance (V)**: offline keeps last-read runs readable and
  disables every write without queueing (030-FR-025); polling pauses when hidden or
  offline (030-FR-024); local tasks are never touched by agent code (030-FR-012).
- **Feature flag**: the agent harness is a significant capability and stays behind the
  existing `external_agent_relay` flag (AGENTS.md owner decision 2026-09-06); flags are
  never authorization — the server enforces both.
- **Delivery boundary**: tasks.md is portable planning input; isolated worktrees,
  Principle II, independent review, ADR-0008 landing, CI and release gates remain
  authoritative. Classification per slice by `scripts/classify_path_risk.py`: Mac app and
  kit client code are SHIP/SHOW under ADR-0030; no ASK path is touched. The mandatory
  `/speckit-review` gate runs before implementation.
- **027 freeze (D2)**: no file under `backend/` changes; every slice checks
  `git diff --stat origin/main -- backend/` is empty (030-SC-010).
- **Design citation**: [design.md](design.md). PR-03 provides the availability and cache
  behind every G- state; PR-04 provides G-01 – G-03's data; PR-05 provides G-04's and
  G-05's flows; PR-06 provides G-06 – G-08's model; PR-07 renders **G-01**, **G-02**,
  **G-03**; PR-08 renders **G-05**; PR-09 renders **G-04**; PR-10 renders **G-06**; PR-11
  renders **G-07**, **G-08**; PR-12 records the renders.

## Architecture

### Shared kit (`ios/BrainBuddyKit/Sources/BrainBuddyAPI/`) — additive, platform-neutral

- `AgentConnectionsAPI.swift` (new, PR-01): `AgentConnectionDTO` (id, name, agentAddress,
  authScheme, authHeaderName, status, stale, readyForHandoff, capabilities {streaming,
  pushNotifications}, controlsOffered, card {name, version, protocolVersion, skills},
  guaranteeTier, tierDisclosure, cancellationDisclosure, agentChanged, lastTestErrorCode,
  lastContactAt, lastTestedAt, revision); `AgentAuthScheme` (`bearer`, `apiKey`);
  `AgentGuaranteeTier`; lenient enums for status and error codes. Calls through the
  existing `get` / `mutate` / `exchange`: `agentConnections()`, `agentConnection(id:)`,
  `createAgentConnection(name:address:scheme:credential:currentPassword:idempotencyKey:)`,
  `updateAgentConnection(id:name:address:scheme:currentPassword:expectedRevision:idempotencyKey:)`,
  `testAgentConnection(id:idempotencyKey:)`,
  `replaceAgentCredential(id:credential:currentPassword:expectedRevision:idempotencyKey:)`,
  `disconnectAgentConnection(id:currentPassword:expectedRevision:idempotencyKey:)`. Request
  bodies holding a credential or password are `Encodable` only, with a redacted
  `description`.
- `AgentAPIError.swift` (new, PR-01): `extension APIError { public var agentFailure:
  AgentFailure }` — `.relayUnavailable` (404 whose detail is "External agent relay is not
  available."), `.wrongPassword` (403 on a password-bearing call), `.staleRevision`,
  `.rateLimited`, `.offline`, `.other`. `APIError.from` is unchanged.
- `AgentRunsAPI.swift` (new, PR-02): `extension APIError { public var needsManifestReview: Bool }` (400 with `detail.reason` `manifest_not_reserved` or `manifest_token_mismatch`, as the web's `needsReReview`), `AgentManifestDTO` (token, runID, taskID,
  connectionID, agentName, title, details, supportingItems, guaranteeTier,
  tierDisclosure, cancellationDisclosure, externalCopyNotice, acknowledgementRequired,
  reauthenticationRequired), `AgentRunDTO` (the fields listed in spec Key Entities plus
  events, commands, controls {reply, cancel}, cancelOutcome, exchangeState,
  resultAvailability, observationIntervalSeconds, contentExpiresAt, createdAt, revision),
  `AgentRunEventDTO`, `AgentRunSummaryDTO`, `AgentPrimaryState` (the 15 labels plus
  `.unknown(String)`). Calls: `previewAgentHandoff(taskID:connectionID:includeDetails:
  supportingItems:)`, `sendAgentHandoff(taskID:…:manifestToken:currentPassword:
  acknowledgeDuplicateRisk:idempotencyKey:)`, `agentRuns(taskID:)`,
  `agentRunSummaries(taskIDs:)` (splits into chunks of at most 200 ids, requests them in
  order, merges the sparse maps; an empty input makes no request), `agentRun(id:)`,
  `replyToAgentRun(id:message:expectedRevision:idempotencyKey:)`,
  `checkAgentRunDelivery(id:currentPassword:expectedRevision:idempotencyKey:)`,
  `cancelAgentRun(id:idempotencyKey:)`.
- The kit's `me()` (`feature_flags`), `accountAuthMethods()` (`has_password`),
  `authMethods()` (web origin) and `NativeAccountDestination` (`url(origin:ownerID:
  deleting:)`, `agentsURL(origin:)`) are reused unchanged.
- `BrainBuddyDesign` is not changed by this feature; it is owned by the iOS thread. If a
  needed control is missing, the slice asks the iOS thread rather than editing it.

### Mac core (`macos/Sources/BrainBuddyMacCore/`) — Foundation-only

- `AgentAvailability.swift` (new, PR-03, `@MainActor @Observable`): inputs the
  workspace's `LinkedAccount?` and a remote (`me()`, `accountAuthMethods()`). Outputs
  `ownerID`, `relayEnabled: Bool`, `passwordState: has | none | unknown`, `isOnline`.
  Refresh at sign-in, on main-window activation (throttled to 5 minutes) and on
  `relayUnavailable()` (called by any flow that sees `.relayUnavailable`). Holds the
  one-shot request "show Add new agent" set by the sidebar row and consumed by the
  Settings tab (030-FR-004).
- `AgentMemoryCache.swift` (new, PR-03): a value store keyed by owner id holding runs,
  summaries, connections and reply drafts; `clear()` on sign-out, session end and account
  change; `run(_:now:)` returns content only when `now < contentExpiresAt`, otherwise an
  expired marker, and drops the content (030-FR-026, 030-FR-027). Nothing is `Codable`.
- `AgentsCopy.swift` (new, PR-13, split out of PR-03 for budget): every string in design.md § Copy, plus the web's
  connection status words and sentences ported from `frontend/src/features/agents/
  agentCopy.ts` (`connectionStatusLabel`, `connectionStatusDetail`, tier wording, the
  queued line).
- `AgentRunGroup.swift` (new, PR-04): `AgentRunGroup` (`needsYou`, `running`, `queued`,
  `toReview`, `lostContact`) from `AgentPrimaryState` by the 030-FR-006 table; the canvas
  detail (030-FR-007) and the compact Waiting for state (030-FR-010) as pure functions of
  a run and `now`.
- `AgentRunsStore.swift` (new, PR-04, `@MainActor @Observable`): inputs the open steps
  with server ids from the workspace (`TaskRecord.serverID` in the store; the plan's
  first task in PR-04 confirms the same id is exposed on the Rust-selected workspace and
  adds a read-only accessor in Mac core if it is not), an `AgentRunsRemote` protocol
  (implemented by `BrainBuddyAPIClient`, built like 028's `AccountSettingsModel` remote),
  `AgentAvailability`, the cache and an injected clock. `refresh()` reads summaries in
  200-id batches, then each listed run; publishes `groups`, `perAgentCounts`,
  `waitingForRows`, `lastUpdated`, `phase` (`loading | loaded | stale | failed(reference)`).
  Polling: one task per on-screen non-ended run at its `observationIntervalSeconds`, a
  60 s summaries tick while the main window is visible, an immediate refresh on Sync now
  and after a hand-off, reply or stop; all paused when hidden or offline. Owner guard: a
  result whose owner differs from `availability.ownerID` is dropped.
- `HandoffFlow.swift` (new, PR-05): phases `loadingAgents | noReadyAgent | previewing |
  ready(manifest) | sending | failed(kind, reference) | sent(run)`. Builds supporting
  items (`Project: <name>`), requests the preview per chosen agent, exposes
  `needsPassword` / `needsAcknowledgement` from the manifest, generates one
  Idempotency-Key per Send and reuses it on Try again, re-previews on a stale or
  expired manifest, maps `.wrongPassword` to the field error and `.relayUnavailable` to
  `availability.relayUnavailable()`. On `sent` it inserts the run into the store.
- `AgentRunActions.swift` (new, PR-05): reply (≤ 4,000 characters, `expectedRevision`,
  one key per Reply), stop, check again (password only when required), and Mark step done
  through a `StepCommands` protocol implemented by the workspace's existing complete and
  create commands: complete the step, then, if the next-step text is non-empty, create a
  step with that title in the same project in Next actions. No other code path in the
  feature calls a step command (030-FR-012).
- `AgentSettingsModel.swift` (new, PR-06, `@MainActor @Observable`): connection list
  (disconnected omitted), selection, detail rows (design G-06.01), Test again, phases
  for loading, offline, failed and password-less.
- `AgentConnectionEditor.swift` (new, PR-06): Add (create then test, then select), Replace
  credential, Edit (password shown only when address or scheme differs), Delete; one
  Idempotency-Key per action; `expectedRevision`; error mapping (030-FR-034); secrets held
  only for the request and zeroed after it.
- Logging through the existing `MacLogSink` (stage, outcome, status class, duration,
  reference).

### Mac app (`macos/Sources/BrainBuddyMac/`) and its core wiring

- `BrainBuddyMacCore/SidebarEntries.swift` (PR-07): `WorkspaceDestination.agentRuns(AgentRunsFilter)` with
  `AgentRunsFilter` = `.all | .agent(connectionID)`; this destination has no kit query —
  `query` becomes optional for it, and `BrainBuddyModel`'s list loading skips it.
- `BrainBuddyMacCore/BrainBuddyModel.swift` (PR-07): owns `AgentAvailability`, `AgentMemoryCache` and
  `AgentRunsStore` for the signed-in account; clears them through the existing sign-out
  and account-change paths.
- `ContentView.swift` (PR-07): the Agents sidebar section (G-01) between Lists and Dates;
  the canvas switch to `Agents/AgentRunsCanvas.swift` (G-02); Waiting for's Agents and
  People groups and header, and the sidebar count n + m (G-03). (PR-08, PR-09): pass the
  run section and the hand-off sheet to the inspector.
- `CarryOnMacIcons.swift` (PR-07): an `allRuns` case drawn from the board's SVG; the
  section reuses 028's `agents` glyph.
- `Agents/AgentRunsCanvas.swift`, `Agents/AgentRunRow.swift` (new, PR-07).
- `Agents/AgentRunSection.swift` (new, PR-08) and `TaskInspector.swift` (PR-08): G-05,
  Hand off… in the action row (PR-09 enables it).
- `Agents/HandoffSheet.swift` (new, PR-09): G-04.
- `Settings/AgentsSettingsTab.swift` (028's file, PR-10): flag on → the list/details split
  (G-06); flag off or signed out → 028's content unchanged. `Settings/AgentDetailsView.swift`
  (new, PR-10).
- `Settings/AddAgentSheet.swift`, `Settings/AgentConnectionSheets.swift` (new, PR-11):
  G-07, G-08.

## Delivery phases

Twelve slices; the slice map with paths, budgets and checks is in
[tasks.md](tasks.md#pr-срезы).

1. **PR-01 — Kit: agent connections API** (contract first). No dependencies.
2. **PR-03 — Mac core: availability and memory cache** (copy moved to PR-13, parallel). No dependencies; parallel with
   PR-01.
3. **PR-02 — Kit: agent runs API**. Depends on PR-01.
4. **PR-06 — Mac core: Settings agents model and editors**. Depends on PR-01 and PR-03;
   parallel with PR-02, PR-04 and PR-05.
5. **PR-04 — Mac core: grouping and All runs store**. Depends on PR-02 and PR-03.
6. **PR-05 — Mac core: hand-off flow and run actions**. Depends on PR-04.
7. **PR-07 — Mac: sidebar, All runs canvas, Waiting for**. Depends on PR-04 (and, outside
   this map, 028 PR-03 for the `agents` glyph in `CarryOnMacIcons.swift`).
8. **PR-08 — Mac: run section in the inspector**. Depends on PR-05 and PR-07.
9. **PR-09 — Mac: hand-off sheet**. Depends on PR-08.
10. **PR-10 — Mac: Settings › Agents tab**. Depends on PR-06 and PR-07 (and 028 PR-03,
    which creates `Settings/AgentsSettingsTab.swift`). Parallel with PR-08 and PR-09.
11. **PR-11 — Mac: Add, Replace, Edit, Delete sheets**. Depends on PR-10.
12. **PR-12 — Snapshots and host evidence**. Depends on PR-07, PR-09 and PR-11.

## Project Structure

### Documentation (this feature)

```text
specs/030-mac-agents/
├── intake.md
├── spec.md
├── design.md
├── plan.md
├── tasks.md
├── checklists/requirements.md
└── evidence/macos-host-run.md   # PR-12
```

### Source Code (repository root)

```text
ios/BrainBuddyKit/Sources/BrainBuddyAPI/
├── AgentConnectionsAPI.swift     # PR-01 (new)
├── AgentAPIError.swift           # PR-01 (new)
└── AgentRunsAPI.swift            # PR-02 (new)
ios/BrainBuddyKit/Tests/BrainBuddyAPITests/
├── AgentConnectionsAPITests.swift  # PR-01 (new)
└── AgentRunsAPITests.swift         # PR-02 (new)
macos/Sources/BrainBuddyMacCore/
├── AgentAvailability.swift       # PR-03 (new)
├── AgentMemoryCache.swift        # PR-03 (new)
├── AgentsCopy.swift              # PR-03 (new)
├── AgentRunGroup.swift           # PR-04 (new)
├── AgentRunsStore.swift          # PR-04 (new)
├── HandoffFlow.swift             # PR-05 (new)
├── AgentRunActions.swift         # PR-05 (new)
├── AgentSettingsModel.swift      # PR-06 (new)
├── AgentConnectionEditor.swift   # PR-06 (new)
├── SidebarEntries.swift          # PR-07
└── BrainBuddyModel.swift         # PR-07
macos/Sources/BrainBuddyMac/
├── ContentView.swift             # PR-07, PR-08, PR-09
├── CarryOnMacIcons.swift         # PR-07
├── TaskInspector.swift           # PR-08, PR-09
├── Agents/                       # PR-07, PR-08, PR-09 (new files)
│   ├── AgentRunsCanvas.swift
│   ├── AgentRunRow.swift
│   ├── AgentRunSection.swift
│   └── HandoffSheet.swift
└── Settings/                     # PR-10, PR-11
    ├── AgentsSettingsTab.swift
    ├── AgentDetailsView.swift
    ├── AddAgentSheet.swift
    └── AgentConnectionSheets.swift
macos/Tests/BrainBuddyMacTests/
├── AgentAvailabilityTests.swift, AgentMemoryCacheTests.swift      # PR-03
├── AgentRunGroupTests.swift, AgentRunsStoreTests.swift            # PR-04
├── HandoffFlowTests.swift, AgentRunActionsTests.swift             # PR-05
├── AgentSettingsModelTests.swift, AgentConnectionEditorTests.swift  # PR-06
├── AgentsSceneTests.swift                                          # PR-07
├── AgentRunSectionTests.swift                                      # PR-08
├── HandoffSheetTests.swift                                         # PR-09
├── AgentsSettingsTabTests.swift                                    # PR-10
├── AgentSheetsTests.swift                                          # PR-11
├── AgentsSnapshotTests.swift                                       # PR-12
└── __Snapshots__/mac-agents-*.png                                  # PR-12
```

## Verification

- Kit: `cd ios/BrainBuddyKit && swift test --filter AgentConnectionsAPITests` and
  `--filter AgentRunsAPITests` (CI `ios-kit`; on Linux
  `sh ios/scripts/swift-linux.sh test --filter AgentRunsAPITests`).
- Mac: `cd macos && swift build && swift test` on macOS 26 (CI `macos-app`), recorded in
  `evidence/macos-host-run.md` with the SHA.
- Backend: no change; `git diff --stat origin/main -- backend/` is empty for every slice
  (030-SC-010). The relay's backend tests run unchanged in CI.
- Specs: `python3 scripts/check_spec_kit_specs.py`; each slice runs
  `python3 scripts/check_slice_budget.py specs/030-mac-agents/tasks.md PR-NN`; after the
  last slice, `python3 scripts/check_requirement_coverage.py specs/030-mac-agents`.
- Manual acceptance on the reference Mac against a test agent: SC-001 hand-off path,
  SC-004 timing, SC-005 disk/log/URL search after sign-out, SC-006 with the flag off,
  SC-008 keyboard-only and VoiceOver pass. `/verify-live` is not used.

## Risks

| risk | mitigation |
|---|---|
| Many open steps make the summaries scan slow | 200-id batches, sequential, at most every 60 s while visible; only listed runs get a run read; follow-up Rust list endpoint (D3) |
| A step's server id is not exposed on the Rust-selected workspace | PR-04's first task checks it and adds a read-only accessor in Mac core; no kit write path changes |
| Polling load | Server-chosen interval per run; paused when hidden or offline; ended runs not polled |
| A stale preview is sent | The manifest token is single-use on the server; the server answers a stale or used manifest with HTTP 400 and `detail.reason` `manifest_not_reserved` or `manifest_token_mismatch` (`modules/agents/service.py` ~2028-2045); PR-02's `APIError.needsManifestReview` detects that, and the flow re-previews and never resends a stale token (409 stays `staleRevision`) |
| Password fields not drawn on the board | Accepted deviation (D2); shown only where the server requires them |
| 028 PR-03 not landed when PR-07/PR-10 start | Both list it as an outside dependency; they start after it lands |
| Labels change on the server | Lenient decoding; unknown labels show verbatim and fall into To review only if ended flags say so, otherwise Running |
| Run content lingers after sign-out | Memory-only cache cleared through the existing sign-out path; test-first in PR-03 |

## Complexity Tracking

| item | why | simpler alternative rejected because |
|---|---|---|
| All runs assembled from summaries + run reads | No list endpoint and the Python server is frozen (D2, D3) | A new endpoint needs a backend change Max declined |
| An additive `APIError` extension for relay failures | The relay's 403/404 meanings differ from the rest of the API | Changing `APIError.from` could alter iPhone behaviour (030-FR-042) |
