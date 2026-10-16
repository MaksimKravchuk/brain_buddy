# Implementation Plan: Mac first run and sign-in

**Branch**: `029-mac-first-run-sign-in` | **Date**: 2026-10-16 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/029-mac-first-run-sign-in/spec.md`; agreed
requirements in [intake.md](intake.md) (owner and thread decisions 2026-10-16; (c)
answered by Max on 2026-10-16: Rust only; pending (a), (b)); design in [design.md](design.md) (F-01 – F-04, A-01 – A-05 from board cells
M01–M06). Research: `/mnt/project-files/design/mac-feature7-groundwork.md`.

## Summary

Two independent tracks that meet only in the final snapshot slice:

1. **First run** (groundwork slice A): a Foundation-only `FirstRunModel` in
   `BrainBuddyMacCore` decides once per Mac whether the first run is needed, records the
   outcome in `mac-local.json`, and composes the first step from existing task commands.
   SwiftUI views in the main window render F-01 – F-04. No network, no new command.
2. **Sign-in** (groundwork slice B): the Rust server accepts a `macos` authentication
   client value (a Rust-only conformance case; the Python server is not changed, per Max's
   answer to (c)); the kit sends the device's value; the Mac's `SignInFlow` moves to the
   kit's native attempt API (`Workspace.beginSignIn` / `completeSignIn`) and gains email
   code and Google, shown only when `methods` reports them for `macos`; `SignInSheet`
   follows M05. Against the Python server the Mac stays on password sign-in.

Later slices: the invite step M06 (groundwork slice C, after 027 T055) and Apple on the
Mac (groundwork slice D, gated by pending (a)).

## Technical Context

**Language/Version**: Swift 6 (language mode 6), macOS 26; kit `ios/BrainBuddyKit`;
Rust (conformance suite only). No Python change (answer to (c)).
**Primary Dependencies**: SwiftUI, AppKit, AuthenticationServices
(`ASWebAuthenticationSession`, macOS); kit `BrainBuddyAPI`, `BrainBuddyWorkspace`,
`BrainBuddyDesign`; `rust/crates/bb-conformance`.
**Storage**: `mac-local.json` gains an optional `firstRun` record (dates and enums). No
server schema or migration.
**Testing**: Swift Testing in `macos/Tests/BrainBuddyMacTests` (CI `macos-app`) and
`ios/BrainBuddyKit/Tests/BrainBuddyAPITests` (CI `ios-kit`); Rust conformance
(`rust/crates/bb-conformance`, `live` feature, Rust-only case); snapshots through
`BrainBuddyDesignTestSupport`. The existing backend `test_modern_auth_*` suites run
unchanged.
**Target Platform**: macOS 26; production backend.
**Project Type**: native client feature with a small Rust-server contract addition.
**Performance Goals**: the welcome is visible with the first window (no extra launch
delay); 029-SC-001.
**Constraints**: first run makes no network request (029-FR-014); iPhone requests stay
byte-identical (029-FR-033); `web` and `ios` server behaviour unchanged and no change
under `backend/` (029-SC-006; 027-FR-022 freeze).
**Scale/Scope**: 9 surfaces/states groups; ~1,600 product lines over 8 slices.

## Constitution Check

*Pre-design: pass. Re-checked after design: pass. Re-checked 2026-10-16 after Max's
answer to (c): pass; the Python freeze exception request is withdrawn.*

- **Spec workflow**: spec.md is current; owner and thread decisions are recorded in spec
  Clarifications and intake.md; (c) is answered (Rust only); the two pending
  clarifications (a), (b) carry recommended defaults and name the slices they change. The full path applies (cross-surface contract change).
- **Consent & Safety (I)**: no AI and no remote processing in the first run (029-FR-014).
  The first-run record holds no typed text (029-FR-015). Sign-in keeps the token in the
  login Keychain; the kit's PKCE-style challenge/verifier protects the code and provider
  flows; Google runs in an ephemeral system authentication session; nothing secret goes
  to logs, URLs or `mac-local.json` (029-FR-027). Against the Python server the Mac
  offers only password sign-in and creates no accounts; the Rust invite rule is handled by
  PR-07.
- **Tests (II)**: reused — kit `ModernAuthTests`, `InviteHandoffTests`,
  `EndpointRequestTests`; Mac `MacSyncFlowTests` (sign-in/out), `MacLocalStateTests`,
  `MacLaunchTests`, the Carry On snapshot suites; backend `test_modern_auth_*` (unchanged;
  they already cover the Python server rejecting an unknown client). Necessary additions
  at the cheapest reliable level: Foundation-only `FirstRunModelTests` (clean-Mac decision
  matrix, outcomes, first-step composition, no text in the record); kit request tests for
  the client value (`ios` byte-identical, `macos` on the Mac identity); `SignInFlowTests`
  over a fake workspace (each method, each outcome, the different-account guard, and the
  password-only fallback when `methods` rejects `macos`); one Rust-only conformance case
  for `macos` (Apple refused); snapshots for F-01 – F-03 and A-01, A-02, A-04, A-05 in
  light and dark. No new pytest. Test-first applies to three invariants that are new code: the clean-Mac decision
  (029-FR-001, never shows on a Mac with data), "original text kept in the note"
  (029-FR-009) and the different-account refusal on sign-in again (029-FR-024).
  Swift tests carry the qualified ids in their names (`029_FR_001` / `"029-FR-001 …"`);
  the Rust conformance case names `029-FR-017` in its title.
- **Contracts (III)**: one additive Rust-server contract change — the client value gains
  `macos` (029-FR-017) — recorded as a Rust-only `change` case in the conformance suite
  and a note in the 027 capability inventory. The Python server's contract is unchanged
  (027-FR-022). No response shape changes. Kit changes are additive; the iPhone sends
  `ios` exactly as today.
- **Observability (IV)**: existing `X-Correlation-ID` and `APIError.referenceID` shown as
  "Reference: …" (029-FR-025); the server already parses `X-Client: brainbuddy-macos`
  for logs (CAP-MW-002). Mac logs through `MacLogSink`: stage, method kind, outcome,
  duration, reference only.
- **Mobile/resilience/performance (V)**: the first run is local-only and survives quit at
  any step without loss (spec US2 scenario 7); sign-in failures never touch local tasks
  (029-SC-007).
- **Delivery boundary**: tasks.md is portable planning input; isolated worktrees,
  Principle II, independent review, ADR-0008 landing, CI and release gates remain
  authoritative. Classification per slice by `scripts/classify_path_risk.py`: Mac, kit and
  auth code are SHIP/SHOW under ADR-0030; PR-08's entitlement/signing change is reviewed
  when (a) is answered. The mandatory `/speckit-review` gate runs before implementation.
- **027 freeze ((c), answered by Max 2026-10-16: Rust only)**: the Python server is not
  changed, so 027-FR-022 holds. PR-03 changes only the Rust conformance case and the 027
  inventory. PR-04 – PR-05 keep the Mac on password sign-in against Python and show
  Google and the email code only when `methods` reports them for `macos`, which happens
  once the Rust server is live (a one-line availability check on `methods`, 029-FR-019).
- **Design citation**: [design.md](design.md). PR-01 provides F-01 – F-04's model; PR-02
  renders **F-01**, **F-02**, **F-03**, **F-04**; PR-04 provides A-01 – A-04's flow; PR-05
  renders **A-01**, **A-02**, **A-03**, **A-04** (with A-04.03's interim invite message);
  PR-06 records the renders; PR-07 renders **A-05**; PR-08 adds A-01's Apple button.

## Architecture

### First run — Mac core (`macos/Sources/BrainBuddyMacCore/`, Foundation-only)

- `MacLocalState.swift`: optional `firstRun: FirstRunRecord?` — `decidedAt: Date`,
  `outcome: FirstRunOutcome` (`notNeeded | inProgress | skipped | notYet | firstStep |
  signedIn`), `tipDismissedAt: Date?`. Decoded with `decodeIfPresent` (older files read as
  nil). No strings beyond the enum (029-FR-015).
- `FirstRunModel.swift` (new, `@MainActor @Observable`): inputs are the local-state store,
  the workspace (`account`, legacy-import record, `workspaceFirstWrittenAt` as found at
  launch, open-list counts and project readiness) and two availability booleans (hotkey
  registered, speech available). Phases: `undecided | welcome(typing: Bool) |
  firstStep(TaskID) | landing(TaskID) | done`.
  - **Decision** (029-FR-001): `firstRun == nil` and no account and the workspace was
    first written at this launch (or never), and the legacy import brought nothing, and —
    once the counts and projects are ready — zero open tasks and zero projects →
    `welcome`, record `inProgress`. Any other combination → record `notNeeded`, `done`.
    A record of `inProgress` found at launch (quit mid-run) → `done` with outcome kept as
    `notYet` if an Inbox item exists, otherwise `skipped`; `firstStep` with
    `tipDismissedAt == nil` → `landing` (029-FR-011 relaunch).
  - **Capture** (029-FR-006): calls the existing workspace capture to the Inbox with the
    trimmed text unchanged (no Smart Add parse), then `firstStep(id)`.
  - **First step** (029-FR-009): one `updateTask` with `title = step` and, when the
    original differs, `details = original` (the task's existing details are empty for a
    fresh capture; if not, the original is put first, separated by a blank line), then
    `transitionTask` to Next actions — the same pair the Inbox inspector's "A step I can
    take" path issues today (`TaskInspector.swift:455`). No `createProject`. On failure
    the model stays in `firstStep` and surfaces the existing error.
  - **Skip / Not yet / Got it / signed in** record the outcome and move to `done`;
    `signedIn` is set when `workspace.account` becomes non-nil during any phase
    (029-FR-013).
  - `launchDestination`: `.list(.inbox)` while `welcome`/`firstStep`, `.list(.next)` for
    `landing`, otherwise the model's existing default (029-FR-002).
  - `showsFirstRunSidebar`: true in any phase but `done` (029-FR-012).
- `FirstRunCopy.swift` (new): every F- string in design.md § Copy.
- `BrainBuddyModel.swift`: initial `destination` taken from `FirstRunModel` when the
  decision is `welcome`/`landing`; otherwise unchanged (`.list(.next)`).

### First run — Mac app (`macos/Sources/BrainBuddyMac/`)

- `FirstRun/WelcomeInboxView.swift` (new): F-01 inside the Inbox content when the list is
  empty and the phase is `welcome`; reuses the existing capture field and mic button
  (`CarryOnMacCapture.swift`) and `VoiceCapture`; Return/Esc via `onKeyPress`.
- `FirstRun/FirstStepInspector.swift` (new): F-02 content inside the existing
  `MacInspectorPanel` when the selected task is the first-run item and the phase is
  `firstStep`; the normal `TaskInspector` is untouched outside the first run (029-FR-033).
- `FirstRun/LandingTip.swift` (new): F-03 tip under the next-step card.
- `ContentView.swift`: hosts the three views; the sidebar hides counts and the Projects,
  Archived projects and Tags sections while `showsFirstRunSidebar` (F-04); the list header
  "1 thing to sort" during `firstStep`.
- `QuickCaptureView.swift`: exposes whether ⌃⌥⇧B registered (today it sets
  `registrationError`, `:68`) so the hint and tip are honest (029-FR-004).

### Sign-in — server (Rust only; `backend/` unchanged)

- Python: no change (answer to (c)). `Client = Literal["web", "ios"]`
  (`backend/app/schemas/modern_auth.py:13`) stays, so `GET /auth/methods?client=macos`
  answers its validation error (422) and the Mac falls back to password sign-in.
- Rust: one Rust-only case in `rust/crates/bb-conformance/tests/modern_auth.rs`, written
  with the existing `rust_only_test!` macro (`cap_*_rust_*`, runs only when
  `BB_CONFORMANCE_SERVER=rust`, like the invite-handoff `change` rows): methods, email
  request and Google start with `client=macos` behave as `ios` (native path, the same
  `brainbuddy://auth/callback` return); Apple is reported as not offered and its start is
  refused. The 027 capability inventory's CAP-HTTP-010 row gains a note that `macos` is a
  Rust-only change (029-FR-017). The Rust server's own modern-auth implementation of the
  value belongs to 027's modern-auth slices, which must pass this case.

### Sign-in — kit (`ios/BrainBuddyKit/Sources/BrainBuddyAPI/`)

- `NativeAuthentication.swift`: the three hard-coded `"ios"` values (`:139,149,163`) read
  the client's `ClientIdentity`: `.macOS` → `"macos"`, every other identity → `"ios"`.
  The iPhone's requests are byte-identical (asserted).

### Sign-in — Mac core and app

- `BrainBuddyMacCore/SignInFlow.swift`: keeps its copy and password logic, and moves the
  password call from `Workspace.signIn(serverURL:email:password:)` to `beginSignIn` +
  `completeSignIn(.password)`. New steps: `choice(methods)`, `code(challenge)`,
  `password`, `collision`, `inviteRequired(InviteHandoff)` (rendered by PR-05's interim
  view, PR-07's step later). Methods come from `authMethods()` on the chosen server
  (Advanced address respected). Availability check (029-FR-019): a 422 validation error
  on `methods` (the Python server does not know `macos`) maps to "password only" with no
  error; any other failure is the methods-failed state. The flow never retries with `ios`
  (029-FR-016). Email code: `requestEmailCode` → `completeSignIn(.emailCode)`,
  resend timer from the challenge. Google: the flow asks a `ProviderSignInPresenting`
  protocol (implemented in the app) for the callback URL, then `completeSignIn(.provider)`.
  Sign in again: after a `.signedIn` outcome whose account id differs from the linked one,
  the flow refuses (029-FR-024). The kit already refuses an account change while one is in
  progress (`Workspace.swift` FR-018 guard); the plan verifies whether the native path
  refuses a different account on sign-in again and, if it does not, adds the guard in the
  kit's `completeSignIn` before the link is recorded, test-first.
- `BrainBuddyMac/SignInSheet.swift`: M05 layout (A-01 – A-04) with design-system roles;
  shows only the methods the flow reports (A-01.08, password only against Python).
- `BrainBuddyMac/MacProviderSignIn.swift` (new): `ASWebAuthenticationSession`
  (`callbackURLScheme: "brainbuddy"`, `prefersEphemeralWebBrowserSession = true`, the main
  window as presentation anchor). The Mac needs no URL-scheme registration for this.
- `BrainBuddyMac/SignInInviteStep.swift` (new in PR-05): A-04.03 interim message;
  PR-07 replaces its body with A-05.

### Later slices

- **PR-07 invite step** (after 027 PR-55 lands on the Rust server): `InviteStepFlow`
  (core) resubmits the handoff through the kit's existing `complete(.invite)` /
  `signupComplete` and maps `INVITE_INVALID`, `SIGNUP_EXPIRED`, 429 + Retry-After;
  `SignInInviteStep.swift` renders A-05 with one field (pending (b)). Amends
  `specs/027-rust-server/contracts/invite-handoff.md:8` ("The Mac app offers only password
  sign-in and never creates accounts").
- **PR-08 Apple on the Mac** (pending (a)): a team-signed build with the
  `com.apple.developer.applesignin` entitlement (`macos/build_app.sh`, a new entitlements
  file), the Rust server's acceptance of the Mac bundle id as a native Apple audience
  (a Rust-only conformance case; the Python server stays unchanged per (c)), and the Apple
  button in `SignInSheet.swift` through `ASAuthorizationAppleIDProvider`.

## Delivery phases

Eight slices; the slice map with paths, budgets and checks is in
[tasks.md](tasks.md#pr-срезы).

1. **PR-01 — First-run model** (Mac core). No dependencies.
2. **PR-03 — Rust `macos` client conformance** (contract first; Rust conformance case and
   027 inventory only, no `backend/` change). No dependencies. Runs in parallel with PR-01.
3. **PR-02 — First-run views**. Depends on PR-01.
4. **PR-04 — Kit client value and Mac sign-in flow**. Depends on PR-03.
5. **PR-05 — Mac sign-in sheet**. Depends on PR-04.
6. **PR-06 — Snapshots and host evidence**. Depends on PR-02 and PR-05.
7. **PR-07 — Invite step**. Depends on PR-06 (and, outside this map, 027 PR-55).
8. **PR-08 — Apple on the Mac**. Depends on PR-06; starts only if (a) is answered "now"
   and a team-signed build exists.

PR-02 and PR-04 are independent and may run at the same time once their bases land.

## Project Structure

### Documentation (this feature)

```text
specs/029-mac-first-run-sign-in/
├── intake.md
├── spec.md
├── design.md
├── plan.md
├── tasks.md
├── checklists/requirements.md
└── evidence/macos-host-run.md   # PR-06
```

### Source Code (repository root)

```text
rust/crates/bb-conformance/tests/modern_auth.rs        # PR-03, PR-08
specs/027-rust-server/contracts/capability-inventory.md  # PR-03
ios/BrainBuddyKit/Sources/BrainBuddyAPI/NativeAuthentication.swift  # PR-04
ios/BrainBuddyKit/Tests/BrainBuddyAPITests/NativeAuthClientTests.swift  # PR-04 (new)
macos/Sources/BrainBuddyMacCore/
├── MacLocalState.swift        # PR-01
├── FirstRunModel.swift        # PR-01 (new)
├── FirstRunCopy.swift         # PR-01 (new)
├── BrainBuddyModel.swift      # PR-01
├── SignInFlow.swift           # PR-04
├── MacSyncController.swift    # PR-04 (sign-in entry, if needed)
└── InviteStepFlow.swift       # PR-07 (new)
macos/Sources/BrainBuddyMac/
├── ContentView.swift          # PR-02
├── QuickCaptureView.swift     # PR-02
├── FirstRun/                  # PR-02 (new)
├── SignInSheet.swift          # PR-05, PR-08
├── MacProviderSignIn.swift    # PR-05 (new)
├── SignInInviteStep.swift     # PR-05 (new), PR-07
└── MacAppleSignIn.swift       # PR-08 (new)
macos/Tests/BrainBuddyMacTests/
├── FirstRunModelTests.swift   # PR-01 (new)
├── MacLocalStateTests.swift   # PR-01
├── FirstRunSceneTests.swift   # PR-02 (new)
├── SignInFlowTests.swift      # PR-04 (new)
├── FirstRunSnapshotTests.swift, SignInSnapshotTests.swift  # PR-06 (new)
├── InviteStepFlowTests.swift  # PR-07 (new)
└── __Snapshots__/             # PR-06 (mac-first-run-*.png, mac-signin-*.png)
```

## Verification

- Mac: `cd macos && swift build && swift test` on macOS 26 (CI `macos-app`), recorded in
  `evidence/macos-host-run.md` with the SHA.
- Kit: `cd ios/BrainBuddyKit && swift test --filter BrainBuddyAPITests` (CI `ios-kit`;
  on Linux `sh ios/scripts/swift-linux.sh test --filter BrainBuddyAPITests`).
- Backend: no change; `git diff --stat origin/main -- backend/` is empty for every slice
  (029-SC-006).
- Rust conformance: the `live` conformance run per 027 quickstart; the Rust-only `macos`
  case runs with `BB_CONFORMANCE_SERVER=rust` once the Rust server serves modern auth, and
  is skipped against the Python server.
- Specs: `python3 scripts/check_spec_kit_specs.py`; after the last slice,
  `python3 scripts/check_requirement_coverage.py specs/029-mac-first-run-sign-in`.
- Manual acceptance on the reference Mac: SC-001 keyboard path, SC-002 launch matrix,
  SC-003 network/permission observation (Little Snitch or `nettop`), SC-005 password only
  against the Python server and three methods against a Rust server with production-like
  configuration, SC-009 keyboard-only and VoiceOver pass.

## Risks

| risk | mitigation |
|---|---|
| Counts and projects arrive asynchronously on a Rust-selected workspace, delaying the decision | The primary signal is synchronous (`workspaceFirstWrittenAt` and the import record at launch); counts only confirm. The window shows the normal empty Inbox until decided, so nothing flashes wrongly |
| An upgrading user with an empty Mac sees no first run | Acceptable by T1 (clean Mac only); recorded `notNeeded` |
| Google and email code on the Mac wait for the Rust cutover | Accepted by Max ((c), 2026-10-16); password works against Python meanwhile; the methods check turns them on without a Mac release |
| The Mac misreads the Python 422 as a load failure, or a real 422 from the Rust server hides methods | 029-FR-019 maps only the unknown-client validation error to password-only; `SignInFlowTests` cover 422, other 4xx/5xx and offline separately |
| New identities without invites | Not reachable on Python from the Mac (password only); Rust enforces; PR-07 handles `INVITE_REQUIRED` |
| Sign in again with a different provider identity | Refusal before link, test-first (029-FR-024) |
| `ASWebAuthenticationSession` anchor when the main window is closed | Sign-in sheet exists only on the main window; the presenter takes that window |
| Esc in the welcome skips by accident | Low cost: nothing is lost (typed text is the only thing dropped, as the board's "Esc to skip" states); the empty Inbox and ⌘N remain |

## Complexity Tracking

| item | why | simpler alternative rejected because |
|---|---|---|
| Mac shows methods only when `methods` reports them for `macos` | Max chose Rust only ((c)); the Python server keeps rejecting `macos` | Sending `ios` from the Mac would mislabel the client in attempts and logs and block the Mac's Apple audience later; a Python exception was declined |
