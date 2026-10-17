# Implementation Plan: Mac Account and Settings window (⌘,)

**Branch**: `028-mac-settings-account` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/028-mac-settings-account/spec.md`; agreed
requirements in [intake.md](intake.md) (interview with Max, 2026-10-16); design in
[design.md](design.md) (screens S-01 – S-04 from board cell M25).

## Summary

Add a SwiftUI `Settings` scene to the Mac app (`macos/`) with the board's tab bar —
Account, Agents, Sync. The Account tab is a Foundation-only read model in
`BrainBuddyMacCore` over two additive shared-kit calls (`GET /account` and the
existing `GET /account/auth-methods`), plus a native export through `NSSavePanel` and
an additive kit call for `GET /account/export`. Sign in, sign in again and sign out
reuse the existing `MacSyncController` flows; the Sync tab hosts the existing sync
popover view; the Agents tab opens the web agents page. No backend, web or iPhone
change; no feature flag.

## Technical Context

**Language/Version**: Swift 6 (language mode 6), macOS 26; shared kit
`ios/BrainBuddyKit` (iOS 26 / macOS 26).
**Primary Dependencies**: SwiftUI, AppKit (`NSSavePanel`, `NSWorkspace`), kit products
`BrainBuddyAPI`, `BrainBuddyWorkspace`, `BrainBuddyDesign`.
**Storage**: none new. Account details live in memory; the export is written once to
the person's chosen URL.
**Testing**: Swift Testing in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests` (Linux and
macOS, CI lane `ios-kit`) and `macos/Tests/BrainBuddyMacTests` (CI lane `macos-app`,
plus a recorded macOS-host run); snapshot tests through `BrainBuddyDesignTestSupport`.
**Target Platform**: macOS 26 (Apple silicon and Intel).
**Project Type**: native client feature.
**Performance Goals**: 028-SC-001 (window ≤ 0.5 s, rows ≤ 2 s).
**Constraints**: no backend change; kit additions additive; no new persisted state;
logs carry no personal data (028-FR-018).
**Scale/Scope**: 4 screens, ~1,000 product lines over 4 slices.

## Constitution Check

*Pre-design: pass. Re-checked after design: pass.*

- **Spec workflow**: spec.md is current; the five interview answers (Max, 2026-10-16)
  are in spec Clarifications and intake.md. The credential and deletion actions are
  out of scope and recorded as a backlog follow-up in spec.md.
- **Consent & Safety (I)**: no AI, no remote processing, no new consent. Account
  details are memory-only (028-FR-005); the export is written only where the person
  chooses and not retained (028-FR-013). The session token stays in the login Keychain
  and is never put in a URL (028-SC-006). The agents URL is built by the kit's validated
  destination builder (https, or http on localhost; no user info, query or fragment
  from the server).
- **Tests (II)**: reused checks — the existing kit API tests (`ModernAuthTests` for
  `accountAuthMethods`, `EndpointRequestTests`, `ErrorMappingTests`), the Mac sign-in /
  sign-out flow tests (`MacSyncFlowTests`), the sync popover model tests
  (`SyncStatusPopoverModelTests`) and the Carry On snapshot suites. Necessary additions,
  at the cheapest reliable level: kit request/decoding tests for the two new calls and
  the agents destination (`BrainBuddyAPITests`); Foundation-only model tests for the
  Account tab state machine, owner guard and export flow (`BrainBuddyMacTests`, no UI);
  snapshot tests for S-02/S-03 states in light and dark. Test-first applies to the two
  safety invariants that are new code: the owner guard (a late response for another
  account is discarded, 028-FR-005) and "no partial export file" (028-FR-013). No
  Allure taxonomy applies (Swift tests are outside the pytest/Vitest/Playwright rule);
  test names carry the qualified ids (`028_FR_005` / `"028-FR-005 …"`).
- **Contracts (III)**: no server contract changes. Consumed contracts are listed in
  spec Dependencies. Kit additions are new public types and methods; no existing
  signature changes, so the iPhone is unaffected (028-FR-024).
- **Observability (IV)**: every kit request already carries `X-Correlation-ID`; the
  model keeps `APIError.referenceID` and shows it as "Reference: …" (028-FR-017). Mac
  logs go through the existing `MacLogSink` with stage, outcome, duration and reference
  only (028-FR-018); a log-content test asserts no email, name or path appears.
- **Mobile/resilience/performance (V)**: offline and session-ended states keep local
  work untouched (028-FR-016, 028-SC-005); export is cancellable and atomic; no change
  to sync, capture or canvas.
- **Delivery boundary**: tasks.md is portable planning input; isolated worktrees,
  Principle II, independent review, ADR-0008 landing, CI and release gates remain
  authoritative. Classification: SHIP/SHOW (Mac app and kit client code; no ASK path —
  the export is the existing server export, unchanged). The mandatory `/speckit-review`
  gate runs before implementation.
- **Design citation**: [design.md](design.md). Slice PR-03 realizes **S-01** (window
  and tab bar), **S-02** (all states), **S-03** and **S-04**; PR-01 provides S-02's
  read model (S-02.01 – S-02.07, S-02.13 – S-02.15) and S-03's destination; PR-02
  provides S-02.08 – S-02.12's export flow; PR-04 records S-02/S-03 renders.

## Architecture

### Shared kit (`ios/BrainBuddyKit/Sources/BrainBuddyAPI/`) — additive

- `AccountAPI.swift` (new): `public struct AccountSummaryDTO: Decodable` (`id`,
  `email`, `displayName`, `completedTaskCount`; other `AccountResponse` fields ignored)
  and `BrainBuddyAPIClient.accountSummary()` → `GET /account` through the existing
  `get(_:)`.
- `AccountExportAPI.swift` (new): `public struct AccountExport` (`suggestedFileName`,
  `data`; `description` redacted) and `BrainBuddyAPIClient.exportAccount()` →
  `GET /account/export` through the existing `exchange(_:)`, reading the file name from
  `Content-Disposition` (fallback `brainbuddy-export.zip`, path components stripped).
  Cancellation follows the transport's task cancellation.
- `NativeAuthCallback.swift`: `NativeAccountDestination.agentsURL(origin:)` — the same
  origin validation as `url(origin:ownerID:deleting:)`, path `/settings/agents`, no
  query. The existing method is not changed.
- The web origin comes from the existing `authMethods()` (`GET /auth/methods`, which
  sends `client=ios`); no new client value.

### Mac core (`macos/Sources/BrainBuddyMacCore/`) — Foundation-only

- `AccountSettingsModel.swift` (new, `@MainActor @Observable`): inputs are the
  workspace's `LinkedAccount?`, the sync line's session-ended state and an
  `AccountSettingsRemote` protocol (`accountSummary()`, `accountAuthMethods()`,
  implemented by `BrainBuddyAPIClient` built like `reviewSuggestionRemote()`: account
  server URL, `WorkspaceHost.systemTokenStore()`, `WorkspaceHost.clientIdentity`).
  Output: `phase` = `notSignedIn | loading | loaded(AccountRows) | offline |
  sessionEnded | failed(message, reference, rateLimited)`; `AccountRows` holds the
  display strings of design S-02.02/S-02.03 (each row's value or "Unavailable").
  `reload()` runs both reads concurrently, keyed by the account id it started with;
  a result is applied only if `workspace.account?.id` and the DTO's id still match
  (owner guard). `clear()` on sign-out, session end or account change. No disk
  writes. Error mapping: `.network` → offline; `.unauthorized` → sessionEnded;
  `.rateLimited` → failed(rateLimited) with no retry; others → failed with
  `referenceID`. A failed methods read with a successful account read → S-02.03.
- `AccountSettingsCopy.swift` (new): every string in design.md § Copy.
- `AccountExportFlow.swift` (new, `@MainActor @Observable`): `idle | exporting |
  choosingLocation(suggestedName) | saved | failed(kind, reference)`; `start()`
  downloads through an `AccountExportRemote` protocol; `save(to:)` writes with
  `Data.write(to:options: .atomic)` (temporary file + rename, so the destination never
  holds a partial file); `cancel()` (Cancel, panel cancelled, window closed) cancels the
  download or drops the bytes and writes nothing; any write error maps to "Couldn't save
  the file there." The flow keeps no copy of the bytes after the write or cancel.
- `AgentsWebLink.swift` (new): reads the origin through `authMethods()` on the account's
  server, or `MacSyncController`'s default server when signed out, and returns
  `NativeAccountDestination.agentsURL(origin:)` or an unavailable state.
- Logging through the existing `MacLogSink` category `.sync` (stage, outcome,
  duration, reference only).

### Mac app (`macos/Sources/BrainBuddyMac/`)

- `BrainBuddyMacApp.swift`: add `Settings { MacSettingsView(launch: launch) }`. SwiftUI's
  `Settings` scene gives ⌘,, the app-menu item, single instance and ⌘W. While the
  workspace is not loaded yet (`launch.sync == nil`), the Account tab shows S-02.01.
- `Settings/MacSettingsView.swift` (new): `TabView` with three `tabItem`s (S-01) and a
  `@State` selection, which keeps the last tab while the app runs (S-01.02).
- `Settings/AccountSettingsTab.swift` (new): lays out `AccountSettingsModel` and
  `AccountExportFlow` per design S-02 using `CarryOnColorStyle` roles only. Reloads on
  appear and on `NSWindow.didBecomeKeyNotification` for its window (028-FR-004), and
  on `workspace.account` changes. Export… starts the download (S-02.09); when it
  completes, `NSSavePanel` opens (allowed type zip, `nameFieldStringValue` = the
  server's suggested name, S-02.08) and the flow writes to the confirmed URL; see the
  note on export order below. Sign out… calls `openWindow(id: "main")` and then `controller.requestSignOut()`,
  so the main window's guard and 021 X-04 run unchanged (S-02.13). Sign in… / Sign in
  again… call `controller.beginSignIn(from: .menu)` after bringing the main window
  forward (the existing entry; no new router case). The footer shows
  `controller.line.description.text`.
- `Settings/AgentsSettingsTab.swift` (new): S-03, `NSWorkspace.shared.open(url)`.
- `Settings/SyncSettingsTab.swift` (new): hosts the existing `SyncStatusPopover(controller:)`
  in a scroll view (S-04). The popover view is not modified; its `onAppear` focus request
  goes through the router, which only moves focus inside a popover that is open, so
  hosting it here moves no focus in the main window (asserted in PR-03's tests).
- `CarryOnMacIcons.swift`: three new cases (`account`, `agents`, `sync`) drawn from the
  M25 SVG paths, same stroke rules as the existing glyphs.

**Note — export order**: the server's file name is known only from the export
response, and 028-FR-012 asks for that name in the save panel. The flow therefore
downloads first (S-02.09, cancellable), then opens the panel prefilled (S-02.08), and
writes atomically to the confirmed URL. The bytes are held in memory only until the
panel closes; cancelling the panel drops them and writes nothing (028-FR-013). The
alternative — panel first with a generic name — was rejected because it would not
show the server's name.

## Delivery phases

Four slices; the slice map with paths, budgets and checks is in
[tasks.md](tasks.md#pr-срезы).

1. **PR-01 — Account read model and kit calls**: kit `accountSummary()`, agents
   destination; Mac core `AccountSettingsModel`, `AccountSettingsCopy`,
   `AgentsWebLink`; tests. Parallel with PR-02.
2. **PR-02 — Export**: kit `exportAccount()`; Mac core `AccountExportFlow`; tests.
   Parallel with PR-01.
3. **PR-03 — Settings scene and tabs**: the scene, the tab bar, the Account, Agents and
   Sync tab views, icons. Depends on PR-01 and PR-02. The window first appears here,
   complete, so no partial Settings ever ships.
4. **PR-04 — Snapshots and host evidence**: S-02 and S-03 snapshot tests in light and
   dark, and `evidence/macos-host-run.md`. Depends on PR-03.

## Project Structure

### Documentation (this feature)

```text
specs/028-mac-settings-account/
├── intake.md
├── spec.md
├── design.md
├── plan.md
├── tasks.md
├── checklists/requirements.md
└── evidence/macos-host-run.md   # PR-04
```

### Source Code (repository root)

```text
ios/BrainBuddyKit/Sources/BrainBuddyAPI/
├── AccountAPI.swift              # PR-01 (new)
├── AccountExportAPI.swift        # PR-02 (new)
└── NativeAuthCallback.swift      # PR-01 (agentsURL, additive)
ios/BrainBuddyKit/Tests/BrainBuddyAPITests/
├── AccountAPITests.swift         # PR-01 (new)
└── AccountExportAPITests.swift   # PR-02 (new)
macos/Sources/BrainBuddyMacCore/
├── AccountSettingsModel.swift    # PR-01 (new)
├── AccountSettingsCopy.swift     # PR-01 (new)
├── AgentsWebLink.swift           # PR-01 (new)
└── AccountExportFlow.swift       # PR-02 (new)
macos/Sources/BrainBuddyMac/
├── BrainBuddyMacApp.swift        # PR-03
├── CarryOnMacIcons.swift         # PR-03
└── Settings/                     # PR-03 (new)
    ├── MacSettingsView.swift
    ├── AccountSettingsTab.swift
    ├── AgentsSettingsTab.swift
    └── SyncSettingsTab.swift
macos/Tests/BrainBuddyMacTests/
├── AccountSettingsModelTests.swift   # PR-01
├── AgentsWebLinkTests.swift          # PR-01
├── AccountExportFlowTests.swift      # PR-02
├── MacSettingsSceneTests.swift       # PR-03
├── SettingsSnapshotTests.swift       # PR-04
└── __Snapshots__/                    # PR-04 (mac-settings-*.png)
```

## Verification

- Kit: `cd ios/BrainBuddyKit && swift test --filter BrainBuddyAPITests` (CI `ios-kit`).
- Mac: `cd macos && swift build && swift test` on macOS 26 (CI `macos-app`), recorded in
  `evidence/macos-host-run.md` with the SHA, because some ids are traceable only under
  `macos/Tests` (see `scripts/check_requirement_coverage.py`).
- Specs: `python3 scripts/check_spec_kit_specs.py`; after the last slice,
  `python3 scripts/check_requirement_coverage.py specs/028-mac-settings-account`.
- Manual acceptance on the reference Mac: SC-001 timing, SC-002 row comparison with the
  web account page, SC-004 export comparison, SC-007 keyboard-only pass.

## Risks

| risk | mitigation |
|---|---|
| The kit client removes the stored token on a 401, as it does for every request | Same behavior as the existing review-suggestion remote; the Account tab shows S-02.05 and the existing sync line reaches "Sign in again" on its own; no local data touched (asserted in PR-01 tests with a fake token store) |
| Hosting `SyncStatusPopover` outside the popover could move focus in the main window | Router only honors `.focusInside` for an open surface; PR-03 test asserts the router's surface and focus requests are unchanged when the Sync tab appears |
| Large export held in memory | Exports are small JSON/ZIP archives today; the bytes live only until the atomic write |
| `GET /account/auth-methods` returns 404/503 when modern auth is off | S-02.03 shows "Unavailable" for the affected rows |

## Complexity Tracking

No constitution violations.
