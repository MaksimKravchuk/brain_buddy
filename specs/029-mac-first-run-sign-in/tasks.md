# Tasks: Mac first run and sign-in

**Input**: [spec.md](spec.md), [plan.md](plan.md), [design.md](design.md),
[intake.md](intake.md).

**Status**: draft slice map for owner approval. Implementation starts only after the
design sign-off and a `/speckit-review` verdict of `approved` or `founder-accepted`.
Clarification (c) is answered (Max, 2026-10-16: Rust only, no Python exception), so no
slice changes `backend/`. PR-07 waits for 027 PR-55 (task T055) on the Rust server; PR-08
waits for pending clarification (a) and a team-signed Mac build. This file is portable planning input, not permission to implement, merge or deploy.

**Delivery gates** (non-negotiable, regardless of who executes these tasks): isolated
worktree and feature branch per slice; Constitution Principle II; tests name the
feature-qualified id (`029-FR-###` / `029-SC-###`, `029_FR_###` in Swift and Rust
function names); acceptance graded by an agent that did not write the code; landing class
decided by `scripts/classify_path_risk.py` — SHIP/SHOW land PR-less through verified
trunk (ADR-0008, ADR-0030; `AGENTS.md`). Each slice runs
`python3 scripts/check_slice_budget.py specs/029-mac-first-run-sign-in/tasks.md PR-NN`
before review.

**Tests (Principle II)**: reused — kit `ModernAuthTests`, `InviteHandoffTests`,
`EndpointRequestTests`; Mac `MacSyncFlowTests`, `MacLocalStateTests`, `MacLaunchTests`, the
Carry On snapshot suites; backend `test_modern_auth_*` (run unchanged; no backend file
changes). Necessary additions are named inside the tasks below. Test-first applies to T002 (clean-Mac decision), T004 (original
text kept in the note) and T014 (different account refused on sign-in again).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel with other [P] tasks of the same slice (different files).
- **[USn]**: the user story in spec.md.
- Each task names its requirements and its PR slice.

---

## Phase 1 — First-run model (PR-01)

- [ ] T001 [P] [US1] Add `FirstRunRecord` (`decidedAt`, `outcome`, `tipDismissedAt`) as an
  optional `firstRun` field of `MacLocalState` in
  `macos/Sources/BrainBuddyMacCore/MacLocalState.swift` (decodeIfPresent; enums and dates
  only), with round-trip and old-file tests in
  `macos/Tests/BrainBuddyMacTests/MacLocalStateTests.swift`. 029-FR-001, 029-FR-015. PR-01.
- [ ] T002 [US1] Test-first: in `macos/Tests/BrainBuddyMacTests/FirstRunModelTests.swift`
  write the clean-Mac decision matrix (fresh; store written earlier; legacy import with
  tasks; account linked; record present; record `inProgress` with and without an Inbox
  item; record `firstStep` with the tip pending) and assert the phase, the recorded
  outcome and that nothing but the record is written. 029-FR-001, 029-FR-002,
  029-FR-011, 029-SC-002. PR-01.
- [ ] T003 [US1] Implement `FirstRunModel` in
  `macos/Sources/BrainBuddyMacCore/FirstRunModel.swift` (decision, phases, capture as
  written, skip, not yet, got it, signed-in end, launch destination, first-run sidebar
  flag, availability inputs for the hotkey and speech) and wire its launch destination
  into `macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift`. 029-FR-001 – 029-FR-007,
  029-FR-010 – 029-FR-014. PR-01.
- [ ] T004 [US2] Test-first: in `FirstRunModelTests.swift` assert that the first step sets
  the title to the step, keeps the original capture text in the details (not duplicated
  when equal), moves the task to Next actions, issues no `createProject`, and leaves the
  task unchanged in the Inbox when the save fails; then implement the composition in
  `FirstRunModel.swift`. 029-FR-009, 029-SC-004, 029-SC-007. PR-01.
- [ ] T005 [P] [US1] Add every F- string of design.md § Copy to
  `macos/Sources/BrainBuddyMacCore/FirstRunCopy.swift`, and a test that the record never
  contains captured text (encode a run with a known sentence and search the JSON).
  029-FR-015, 029-FR-031. PR-01.

## Phase 2 — Rust `macos` client conformance (PR-03; no `backend/` change)

- [ ] T006 [US3] Add a Rust-only `macos` case to
  `rust/crates/bb-conformance/tests/modern_auth.rs` with the existing `rust_only_test!`
  macro (named `cap_*_rust_*`, skipped unless `BB_CONFORMANCE_SERVER=rust`): `methods`,
  email request/resend and Google start with `client=macos` behave as `ios` (native path,
  `brainbuddy://auth/callback` return); Apple is reported as not offered and an Apple
  start is refused. The Python server is not changed and keeps rejecting `macos` (answer
  to (c)). 029-FR-017, 029-SC-006. PR-03.
- [ ] T007 [P] [US3] Note on the CAP-HTTP-010 row of
  `specs/027-rust-server/contracts/capability-inventory.md` that `client=macos` is a
  Rust-only change (029-FR-017; the Python server is frozen and rejects it). 029-FR-017,
  029-SC-006. PR-03.

## Phase 3 — First-run views (PR-02)

- [ ] T008 [US1] Build F-01 in `macos/Sources/BrainBuddyMac/FirstRun/WelcomeInboxView.swift`
  (welcome block, focused capture field with the existing mic button, typed-state lines,
  Return/Esc, hint rows honest to hotkey and speech availability). 029-FR-003 – 029-FR-007,
  029-FR-031. PR-02.
- [ ] T009 [US2] Build F-02 in `macos/Sources/BrainBuddyMac/FirstRun/FirstStepInspector.swift`
  inside the existing inspector panel ("Inbox · 1 of 1", question, step field, helper,
  "Make it my next step", "Not yet", Return/Esc). 029-FR-008 – 029-FR-010, 029-FR-031.
  PR-02.
- [ ] T010 [US2] Build F-03 in `macos/Sources/BrainBuddyMac/FirstRun/LandingTip.swift`
  (tip text with the ⌃⌥⇧B clause only when available, "Got it"); show the next-step card's
  "Now" label without a project. 029-FR-011. PR-02.
- [ ] T011 [US1] In `macos/Sources/BrainBuddyMac/ContentView.swift` host F-01 – F-03 and the
  F-04 sidebar (Lists and Dates only, no counts, footer) while the first run shows; in
  `macos/Sources/BrainBuddyMac/QuickCaptureView.swift` expose whether ⌃⌥⇧B registered.
  029-FR-004, 029-FR-008, 029-FR-012, 029-FR-033. PR-02.
- [ ] T012 [US1] Scene tests in `macos/Tests/BrainBuddyMacTests/FirstRunSceneTests.swift`:
  the window opens on the Inbox when the model says welcome; Esc skips; the normal
  `TaskInspector` and sidebar return after the first run; no network client is created
  during the first run. 029-FR-002, 029-FR-007, 029-FR-012, 029-FR-014, 029-SC-001,
  029-SC-003. PR-02.

## Phase 4 — Kit client value and Mac sign-in flow (PR-04)

- [ ] T013 [P] [US3] Read the client value from `ClientIdentity` (`.macOS` → `macos`,
  otherwise `ios`) in `ios/BrainBuddyKit/Sources/BrainBuddyAPI/NativeAuthentication.swift`,
  with request tests in `ios/BrainBuddyKit/Tests/BrainBuddyAPITests/NativeAuthClientTests.swift`
  (the iPhone's methods, email request and provider start bodies byte-identical; the Mac
  identity sends `macos`). 029-FR-016, 029-FR-033. PR-04.
- [ ] T014 [US4] Test-first: in `macos/Tests/BrainBuddyMacTests/SignInFlowTests.swift` write
  the sign-in-again test (a completion for another account is refused with "Sign out first
  to use another account.", nothing linked, unsent changes kept) for each method; then add
  the guard where the plan places it. 029-FR-024, 029-SC-007. PR-04.
- [ ] T015 [US3] Move `macos/Sources/BrainBuddyMacCore/SignInFlow.swift` to the native
  attempt API and add the choice, code, password, collision and invite-required steps:
  methods from `authMethods()` on the chosen server with the `macos` client, a 422 on
  `methods` (the Python server does not know `macos`) mapped to the password-only state
  with no error and no retry as `ios`, email code request/resend/verify,
  provider completion through a `ProviderSignInPresenting` protocol, outcomes and errors
  in words with reference, offline words, no automatic retry on 429, redacted logging;
  adjust `macos/Sources/BrainBuddyMacCore/MacSyncController.swift` only if the sign-in
  entry needs it. Tests in `SignInFlowTests.swift` for each method and outcome over a fake
  workspace, including password-only on a 422 from `methods` and the methods-failed state
  on any other failure. 029-FR-016, 029-FR-018 – 029-FR-025, 029-FR-027, 029-SC-005,
  029-SC-008. PR-04.

## Phase 5 — Mac sign-in sheet (PR-05)

- [ ] T016 [US3] Lay out A-01 – A-04 in `macos/Sources/BrainBuddyMac/SignInSheet.swift`
  per design.md (M05; only the methods `methods` reports for `macos`; A-01.08 password
  only against the Python server; no Apple button unless 029-FR-026 holds; ink "Send me a
  code"; keyboard and VoiceOver). 029-FR-018 – 029-FR-026, 029-FR-031. PR-05.
- [ ] T017 [P] [US3] Implement `ProviderSignInPresenting` with `ASWebAuthenticationSession`
  in `macos/Sources/BrainBuddyMac/MacProviderSignIn.swift` (callback scheme `brainbuddy`,
  ephemeral, main window anchor, cancel → nothing changed). 029-FR-021, 029-FR-027. PR-05.
- [ ] T018 [P] [US5] Add the interim invite-required view (A-04.03) in
  `macos/Sources/BrainBuddyMac/SignInInviteStep.swift`. 029-FR-023. PR-05.

## Phase 6 — Snapshots and host evidence (PR-06)

- [ ] T019 [US1] Snapshot tests in `macos/Tests/BrainBuddyMacTests/FirstRunSnapshotTests.swift`
  for F-01.01, F-01.02, F-01.04 (unavailable), F-02.01, F-02.02, F-03.01 and F-04.01, and in
  `macos/Tests/BrainBuddyMacTests/SignInSnapshotTests.swift` for A-01.02, A-01.03, A-01.08,
  A-02.01, A-04.02 and A-04.03, light and dark; renders committed under
  `macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-first-run-*.png` and `mac-signin-*.png`
  after comparison with the board. 029-FR-031, 029-SC-009. PR-06.
- [ ] T020 [US1] Run `swift test` in `macos/` and the kit's `BrainBuddyAPITests` on a macOS 26
  host at the candidate SHA and record the result in
  `specs/029-mac-first-run-sign-in/evidence/macos-host-run.md`. 029-SC-001, 029-SC-009.
  PR-06.

## Phase 7 — Invite step (PR-07, after 027 PR-55)

- [ ] T021 [US5] Implement `InviteStepFlow` in
  `macos/Sources/BrainBuddyMacCore/InviteStepFlow.swift` (submit the handoff with the code
  through the kit's existing `signupComplete`; map invalid, expired, 429 with Retry-After;
  Back creates nothing), with tests in
  `macos/Tests/BrainBuddyMacTests/InviteStepFlowTests.swift`. 029-FR-028 – 029-FR-030,
  029-FR-027, 029-SC-007. PR-07.
- [ ] T022 [US5] Replace the interim body of
  `macos/Sources/BrainBuddyMac/SignInInviteStep.swift` with A-05 (one code field per pending
  (b), "Create account" ink, "Back"), record its snapshots
  `macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-invite-step-light.png` and
  `mac-invite-step-dark.png`, and amend line 8 of
  `specs/027-rust-server/contracts/invite-handoff.md` (the Mac now creates accounts
  through the invite step). 029-FR-028, 029-FR-029, 029-FR-031. PR-07.

## Phase 8 — Apple on the Mac (PR-08, pending (a))

- [ ] T023 [US3] Add a Rust-only conformance case to
  `rust/crates/bb-conformance/tests/modern_auth.rs` (`rust_only_test!`): `methods` offers
  Apple for `macos` only when the Mac bundle id is configured as a native Apple audience on
  the Rust server, and native Apple completion accepts it. The Rust server's audience
  setting is 027's configuration; the Python server is not changed (answer to (c)).
  029-FR-017, 029-FR-026. PR-08.
- [ ] T024 [US3] Team-sign the Mac build with the Sign in with Apple entitlement
  (`macos/build_app.sh`, `macos/BrainBuddyMac.entitlements`) and add "Continue with Apple"
  through `ASAuthorizationAppleIDProvider` in
  `macos/Sources/BrainBuddyMac/MacAppleSignIn.swift` and
  `macos/Sources/BrainBuddyMac/SignInSheet.swift`, shown only under 029-FR-026; snapshots
  `macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-signin-apple-light.png` and
  `mac-signin-apple-dark.png`. 029-FR-026, 029-FR-031. PR-08.

## Dependencies & Execution Order

- PR-01 and PR-03 have no dependencies and disjoint paths: run in parallel. PR-03 touches
  only the Rust conformance suite and the 027 inventory, never `backend/`.
- Google and the email code on the Mac become visible only when the Rust server serves
  modern authentication and passes PR-03's case; until then the Mac is password-only
  against the Python server, with no further release needed when the server changes.
- PR-02 depends on PR-01; PR-04 depends on PR-03. PR-02 and PR-04 are independent: run in
  parallel.
- PR-05 depends on PR-04. PR-06 depends on PR-02 and PR-05.
- PR-07 depends on PR-06 and, outside this map, on 027 PR-55 (T055) on the Rust server.
- PR-08 depends on PR-06 and on pending (a) answered "now" with a team-signed build.
  Under the recommended default it moves to the backlog when 029 is otherwise accepted.
- Manual acceptance after PR-06: SC-001 – SC-005, SC-007 – SC-009; after PR-07: US5.

## PR-срезы

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "The first-run decision, record, phases and first-step composition work in Mac core with no UI",
      "tasks": ["T001", "T002", "T003", "T004", "T005"],
      "requirements": [
        "029-FR-001", "029-FR-002", "029-FR-006", "029-FR-007", "029-FR-009",
        "029-FR-010", "029-FR-011", "029-FR-013", "029-FR-014", "029-FR-015",
        "029-SC-002", "029-SC-004"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/MacLocalState.swift",
        "macos/Sources/BrainBuddyMacCore/FirstRunModel.swift",
        "macos/Sources/BrainBuddyMacCore/FirstRunCopy.swift",
        "macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift",
        "macos/Tests/BrainBuddyMacTests/MacLocalStateTests.swift",
        "macos/Tests/BrainBuddyMacTests/FirstRunModelTests.swift"
      ],
      "depends_on": [],
      "tests": [
        "cd macos && swift test --filter FirstRunModelTests",
        "cd macos && swift test --filter MacLocalStateTests",
        "cd macos && swift test --filter MacLaunchTests"
      ],
      "acceptance": [
        "The decision matrix shows the first run only on a clean Mac and records the outcome without text",
        "The first step keeps the original text in the note, moves to Next actions and creates no project"
      ],
      "budget": {"product_loc": 300, "files": 4},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "A Rust-only conformance case and the 027 inventory note fix the macos authentication client as a Rust-server change, treated like ios with Apple refused; the Python server is unchanged",
      "tasks": ["T006", "T007"],
      "requirements": ["029-FR-017", "029-SC-006"],
      "paths": [
        "rust/crates/bb-conformance/tests/modern_auth.rs",
        "specs/027-rust-server/contracts/capability-inventory.md"
      ],
      "depends_on": [],
      "tests": [
        "cd rust && cargo test -p bb-conformance --test modern_auth --no-run",
        "cd rust && BB_CONFORMANCE_BASE_URL=http://localhost:8000 cargo test -p bb-conformance --test modern_auth"
      ],
      "acceptance": [
        "The macos case is Rust-only: skipped against the Python server, and on the Rust server methods, email code and Google start accept client=macos while Apple is not offered and its start is refused",
        "No file under backend/ changes and every existing web and ios modern-auth test passes unchanged"
      ],
      "budget": {"product_loc": 1, "files": 1},
      "implementer": "mechanical-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "A clean Mac shows the welcome, first step, landing tip and first-run sidebar as on the board",
      "tasks": ["T008", "T009", "T010", "T011", "T012"],
      "requirements": [
        "029-FR-003", "029-FR-004", "029-FR-005", "029-FR-008", "029-FR-012",
        "029-FR-031", "029-FR-032", "029-FR-033", "029-SC-001", "029-SC-003"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/FirstRun",
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Sources/BrainBuddyMac/QuickCaptureView.swift",
        "macos/Tests/BrainBuddyMacTests/FirstRunSceneTests.swift"
      ],
      "depends_on": ["PR-01"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter FirstRunSceneTests",
        "cd macos && swift test --filter MacSyncFlowTests"
      ],
      "acceptance": [
        "Launching a clean Mac opens the Inbox welcome with the field focused; Return, Esc, Make it my next step, Not yet and Got it behave as F-01 to F-03",
        "Outside the first run the inspector and sidebar are unchanged"
      ],
      "budget": {"product_loc": 380, "files": 5},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "The kit sends the device's client value and the Mac sign-in flow supports Google, email code and password through the native attempt, offering only what methods reports (password only against the Python server)",
      "tasks": ["T013", "T014", "T015"],
      "requirements": [
        "029-FR-016", "029-FR-018", "029-FR-019", "029-FR-020", "029-FR-021",
        "029-FR-022", "029-FR-023", "029-FR-024", "029-FR-025", "029-FR-027",
        "029-SC-005", "029-SC-007", "029-SC-008"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyAPI/NativeAuthentication.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyAPITests/NativeAuthClientTests.swift",
        "macos/Sources/BrainBuddyMacCore/SignInFlow.swift",
        "macos/Sources/BrainBuddyMacCore/MacSyncController.swift",
        "macos/Tests/BrainBuddyMacTests/SignInFlowTests.swift"
      ],
      "depends_on": ["PR-03"],
      "tests": [
        "cd ios/BrainBuddyKit && swift test --filter NativeAuthClientTests",
        "cd ios/BrainBuddyKit && swift test --filter ModernAuthTests",
        "cd macos && swift test --filter SignInFlowTests",
        "cd macos && swift test --filter MacSyncFlowTests"
      ],
      "acceptance": [
        "The iPhone's auth request bodies are byte-identical; the Mac sends macos and never falls back to ios",
        "A 422 from methods yields password only with no error; each method and outcome is handled over a fake workspace, and another account on sign-in again is refused before linking"
      ],
      "budget": {"product_loc": 380, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-05",
      "outcome": "The Mac sign-in sheet follows M05, shows Google and email code only when methods reports them (password only against the Python server), and handles every outcome in words",
      "tasks": ["T016", "T017", "T018"],
      "requirements": ["029-FR-018", "029-FR-019", "029-FR-021", "029-FR-023", "029-FR-026", "029-FR-031"],
      "paths": [
        "macos/Sources/BrainBuddyMac/SignInSheet.swift",
        "macos/Sources/BrainBuddyMac/MacProviderSignIn.swift",
        "macos/Sources/BrainBuddyMac/SignInInviteStep.swift"
      ],
      "depends_on": ["PR-04"],
      "tests": [
        "cd macos && swift build",
        "cd macos && swift test --filter SignInFlowTests"
      ],
      "acceptance": [
        "Only offered methods appear, the Python server yields the password-only sheet, and no Apple button appears in an ad-hoc signed build",
        "Cancelling Google returns to the first step with nothing changed"
      ],
      "budget": {"product_loc": 360, "files": 3},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-06",
      "outcome": "First-run and sign-in renders are approved in light and dark and the macOS host run is recorded",
      "tasks": ["T019", "T020"],
      "requirements": ["029-FR-031", "029-SC-001", "029-SC-009"],
      "paths": [
        "macos/Tests/BrainBuddyMacTests/FirstRunSnapshotTests.swift",
        "macos/Tests/BrainBuddyMacTests/SignInSnapshotTests.swift",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__",
        "specs/029-mac-first-run-sign-in/evidence/macos-host-run.md"
      ],
      "depends_on": ["PR-02", "PR-05"],
      "tests": [
        "cd macos && swift test --filter FirstRunSnapshotTests",
        "cd macos && swift test --filter SignInSnapshotTests"
      ],
      "acceptance": [
        "Snapshots match design.md F- and A- states in light and dark",
        "The host run names the SHA and the passing suites"
      ],
      "budget": {"product_loc": 1, "files": 1},
      "implementer": "mechanical-implementer"
    },
    {
      "id": "PR-07",
      "outcome": "After 027 PR-55, a new identity on the Mac meets the invite step and can create an account or keep working locally",
      "tasks": ["T021", "T022"],
      "requirements": ["029-FR-027", "029-FR-028", "029-FR-029", "029-FR-030", "029-FR-031", "029-SC-007"],
      "paths": [
        "macos/Sources/BrainBuddyMacCore/InviteStepFlow.swift",
        "macos/Sources/BrainBuddyMac/SignInInviteStep.swift",
        "macos/Tests/BrainBuddyMacTests/InviteStepFlowTests.swift",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-invite-step-light.png",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-invite-step-dark.png",
        "specs/027-rust-server/contracts/invite-handoff.md"
      ],
      "depends_on": ["PR-06"],
      "tests": [
        "cd macos && swift test --filter InviteStepFlowTests",
        "cd ios/BrainBuddyKit && swift test --filter InviteHandoffTests"
      ],
      "acceptance": [
        "A valid pasted code creates the account and signs in; invalid, expired and throttled are shown in words",
        "Back or closing creates nothing and local tasks are untouched"
      ],
      "budget": {"product_loc": 220, "files": 2},
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-08",
      "outcome": "With a team-signed build, the Mac offers Continue with Apple and the Rust server accepts the Mac audience",
      "tasks": ["T023", "T024"],
      "requirements": ["029-FR-017", "029-FR-026", "029-FR-031"],
      "paths": [
        "rust/crates/bb-conformance/tests/modern_auth.rs",
        "macos/build_app.sh",
        "macos/BrainBuddyMac.entitlements",
        "macos/Sources/BrainBuddyMac/MacAppleSignIn.swift",
        "macos/Sources/BrainBuddyMac/SignInSheet.swift",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-signin-apple-light.png",
        "macos/Tests/BrainBuddyMacTests/__Snapshots__/mac-signin-apple-dark.png"
      ],
      "depends_on": ["PR-06"],
      "tests": [
        "cd rust && cargo test -p bb-conformance --test modern_auth --no-run",
        "cd macos && swift build"
      ],
      "acceptance": [
        "Apple is offered for macos only when the Rust server has the Mac audience configured, and the button appears only in an entitled build",
        "An Apple sign-in on the Mac lands in the same account as on the iPhone; the Python server is unchanged"
      ],
      "budget": {"product_loc": 200, "files": 4},
      "implementer": "feature-implementer"
    }
  ]
}
```

PR-03 and PR-06 change only tests, specs, renders and evidence, which do not count as
product code; their budget is the minimum the schema accepts. No slice changes
`backend/` (answer to (c)).
