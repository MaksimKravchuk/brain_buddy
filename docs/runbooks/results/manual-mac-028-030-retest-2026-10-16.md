# Mac 028–030 retest — 2026-10-16–17

## Accepted outcome and scope

Retest S-13, S-14, A-17, A-26, A-35, actual VoiceOver Settings tab names (#494), and main-window foregrounding after menu sign-out from Settings (#498). The owner additionally authorized fixing the repeated Keychain prompts that blocked sign-in.

The correction must make routine session reads and cleanup noninteractive, preserve the existing rebuild/re-sign-in generation behavior, and allow manual QA to continue. It does not change storage format, credentials, access lists, account ownership, iOS behavior, or agent readiness semantics. The original matrix used synthetic local accounts, tasks and agents. A subsequent owner-operated sign-in to the production server is recorded separately below.

## Owner-operated sign-in follow-up — 2026-10-17

The owner reported another blocked system Keychain prompt. At inspection no BrainBuddyMac process was running, so that report could not be attributed to the fixed binary. The owner cancelled the remaining system dialogs manually; the UI tool cannot access SecurityAgent.

Launched the verified app at `macos/.build/BrainBuddyMac.app` with its normal local workspace. The running executable path matched this artifact, with SHA-256 `9f6b3d8d925e439be6ee0f1b0cd00d4ffbb89f7d594fc320b1df94be14dcb1fb`. Startup reached the main window without a Keychain prompt. The sign-in form pointed to `https://brain-buddy-frontend.fly.dev/api`. The owner entered their own credentials directly in the app and confirmed that sign-in completed; credentials were not requested in chat or entered by the agent.

Post-login accessibility observations independently confirmed **Synced just now** in the main window and Account settings, with Sign out available and Account/Agents/Sync controls exposed. The session was left signed in. No further sign-out or agent mutation was performed on this account. A later UI-tool timeout while returning from Settings limits the window-close check; a process sample showed an idle main event loop rather than the earlier Keychain wait. Sample: `/tmp/bb-retest-20261016/owner-login-after-settings-sample.txt`.

This verifies owner sign-in and synchronization on the local fixed client. It does not resolve the separate delivery blocker or establish that the client fix has landed in main.

## Exact build and checks

- Initial main baseline: `2ffbba47b97270078178d3898f8f8016794525c4`. Main advanced concurrently to `ffdea1ca7a618b9035f3689947d48faa70704205` (PR #490; only three iPhone capture UI files).
- Initial fixed source and detailed manual matrix: `02eaa2ef2ce322e11074c6c98424aa57376ada75`.
- Current rebased fixed source: `19976520a5ae73bf8338b0d26bc23c5601f8628f`, parent `ffdea1ca7a618b9035f3689947d48faa70704205`. The patch is unchanged; `git diff 02eaa2ef 19976520 -- macos ios/BrainBuddyKit rust` is empty.
- App: `macos/.build/BrainBuddyMac.app`, locally built and ad hoc signed; no TeamIdentifier.
- Initial fixed executable SHA-256: `f1e3987541eed66818611ca3bd82d9a56a7045a52d454b4d9c42c9116005db0e`.
- Current rebuilt executable SHA-256: `9f6b3d8d925e439be6ee0f1b0cd00d4ffbb89f7d594fc320b1df94be14dcb1fb`; the file changed on rebuild, so a fresh manual login/menu-sign-out/foreground smoke was performed on it.
- Build: PASS, `RUSTUP_TOOLCHAIN=1.99.0 BB_APPLE_TARGETS=aarch64-apple-darwin sh build_app.sh`.
- Full Mac suite: PASS on both fixed revisions, 493 Swift Testing tests in 50 suites plus 8 XCTest tests; repeated after rebase.
- Keychain subset: PASS, 7 tests; includes refused-item recovery, earlier-build generation preservation, and interaction-state restoration on successful and failed reads.
- Linux API package: PASS on both fixed revisions, 197 tests in 22 suites through `sh ios/scripts/swift-linux.sh test --filter BrainBuddyAPITests`.
- Independent code review: APPROVED at each exact fixed SHA by a separate `gpt-6.1-sol` reviewer; the review was repeated for `19976520` after rebase, with no actionable findings. Review covered Security call paths, recursive locking, state restoration, generation recovery and unchanged iOS branches.
- Full repository verification: NOT GREEN locally. After correcting TMPDIR and PATH, backend completed with 6222 passed and 3 failed; the chain stopped there. The same three tests passed in a separate serial diagnostic run in 4.02 seconds. Exact-SHA CI remains the authoritative full required gate; isolated success does not turn the original run into a pass.
- Delivery: owner explicitly approved CI → main → production on 2026-10-17 after the automatic permission review initially rejected submission. The standard submit script accepted the receipt and classified both paths non-ASK. The first candidate [CI](https://github.com/maxk-lab/brain_buddy/actions/runs/38973229145) was cancelled as stale after main advanced. The identical fix was rebased, rebuilt, retested and independently reviewed at `19976520`, then submitted through the same standard path. [Current exact-SHA CI](https://github.com/maxk-lab/brain_buddy/actions/runs/38974389013) completed SUCCESS, including Full CI, all native lanes, Backend, Frontend, E2E, mutation gate, Docker and Allure. The macOS package step in the iOS lane passed 1488 tests in 151 suites. The [release](https://github.com/maxk-lab/brain_buddy/actions/runs/38977046868) FAILED at the landing push, before any main update or deployment: `Permission to maxk-lab/brain_buddy.git denied to deploy key`. Deploy was skipped; production smoke did not run for this candidate. At the failed landing, `main` was `ffdea1ca7a618b9035f3689947d48faa70704205`. It subsequently advanced to `eb74d27fd7acb7407719246749ea190594913ece` through PR #499 (shared Apple Rust bridge cache; workflow/spec changes only). It does not contain this fix. Candidate `19976520` remains available but is now stale; a fresh rebase, independent exact-SHA review and CI are required before retrying delivery, in addition to resolving the access blocker.

## Keychain defect and correction

Before the fix, the local API accepted sign-in but the Mac remained on “Signing in…”. The operator repeatedly entered the macOS password and chose Allow, with the system dialog returning; they subsequently chose Deny. The initial sample waited in `SignInFlow.submit → Workspace.signIn → SyncEngine.linkAccount → KeychainSessionTokenStore.storeOnMac → isRefused → readData → SecItemCopyMatching`. Another sample showed concurrent task-list/agent-availability requests blocked in Keychain reads and locks.

The store relied on `kSecUseAuthenticationUIFail`. The file-based Mac keychain does not honor the per-query suppression used here; Chromium documents the same issue and uses the legacy process-level interaction switch ([upstream implementation](https://chromium.googlesource.com/chromium/src/crypto/+/refs/heads/main/apple/scoped_keychain_user_interaction_allowed.cc)). Existing tests additionally disabled interaction around entire scenarios, masking the missing production protection.

A regression now starts with interaction enabled and reads an inaccessible item in a temporary test keychain through the production store. Before the product fix it blocked in `readData → SecItemCopyMatching → SecurityServer::decrypt`; an external 35-second watchdog stopped only the test process group. After the fix the same test passed in 0.017 seconds, and all seven Keychain tests passed in 0.309 seconds.

The Mac store now serializes its operations with one recursive lock, suppresses interaction while routine operations run, and restores the exact previous setting on success/error. Explicit sign-in writes share the lock and respect a previously disabled setting. Existing generation recovery remains unchanged. No real Keychain entry or access list was manually inspected, deleted or changed to work around the defect.

Manual verification of the rebuilt app: an earlier session produced “Sign in again to sync” without blocking; explicit re-sign-in completed immediately, loaded both tasks and showed “Synced just now”. Menu sign-out and a further sign-in also completed. No additional operator password entry was required during these fixed-app journeys.

## Manual results

The detailed matrix below was exercised on `02eaa2ef`. The current rebased revision has identical Mac/shared-kit/Rust source trees and retains these observations with explicit provenance. The rebuilt `19976520` app additionally passed a fresh local operator-account sign-in (under one second, Synced just now, no operator Keychain intervention), menu Sign out from focused Account, Cancel → main-window foreground, confirmed menu sign-out, and Account → Not signed in without another confirmation. No claim is made that the agent matrix or human speech check was repeated on the rebuilt binary.

| Check | Result | Observed evidence |
|---|---|---|
| S-13 | PASS | Menu Sign out is present with Settings focused. One confirmation completes sign-out; reopening Settings → Account shows “Not signed in”. No second confirmation. |
| S-14 | PARTIAL — NEEDS HUMAN for spoken rows | All Account labels and values, including Your data, are exposed in the accessibility tree and visible without the former export clipping. Export opens the native Save panel; it was cancelled. VoiceOver was enabled for the spoken-row check, but the operator could not verify that audio. Tab speech is separately confirmed below. |
| A-17 | PARTIAL for literal plan; routing fix PASS | Stopping both agent processes alone leaves their last tested-ready status cached, so Hand off still lists them. After Test again marks both Unreachable, Hand off says “No agent is ready to receive a hand-off.” Open Settings brings the existing Settings window from Account to **Agents**. Restarting and testing each restores Tested ready. The literal stop-only precondition still differs from the plan; no automatic readiness probe was added. |
| A-26 | PASS | With Hermes Needs you and an unsent answer, stopping the backend and refreshing with Sync now shows “This may be out of date.” and “Needs a connection.”; Reply and Stop run are disabled. Selecting another task and reopening preserves the cached run, timeline and question. Restarting the backend and Sync now clears stale state; Stop run and a populated Reply become enabled again. No answer was sent. |
| A-35 | PASS | Typed a synthetic credential and current password in Add agent without submitting. Menu Sign out remains available, closes the form and presents the main-window confirmation. After sign-out/sign-in, a newly opened Add form has empty Name, Address, Credential and Current password. No draft connection was created. |
| #494 actual tab names | PASS — operator confirmed | Account, Agents and Sync have distinct accessibility names/identifiers and correct selected traits. With VoiceOver enabled, the operator confirmed “Названия вкладок читаются правильно”. |
| #498 main window foreground | PASS | From focused Settings, menu Sign out presents the confirmation. Cancelling returns to the main Brain Buddy window (`main`) with its task list, rather than Settings. Repeated from Add agent and completed sign-out; the main window remains foreground. |

A restored same-account session initially retained the unavailable agent view; clicking Sync now refreshed availability and restored the agent section. Fresh sign-in after sign-out showed it immediately. This observation is not a claim that the Keychain correction changes the existing five-minute availability cache.

VoiceOver was OFF before testing and observed OFF after the final check. Its caption-panel preference was already enabled and was not changed. Screenshots and accessibility observations of the changed surfaces are recorded in the QA chat; no recording of spoken audio is claimed.

## Local evidence

- `/tmp/bb-retest-20261016/keychain-before.log`
- `/tmp/bb-retest-20261016/keychain-regression-before-sample.txt`
- `/tmp/bb-retest-20261016/keychain-after.log`
- `/tmp/bb-retest-20261016/signin-sample.txt`
- `/tmp/bb-retest-20261016/repeated-keychain-sample.txt`
- `/tmp/bb-retest-20261016/build-fixed.log`
- `/tmp/bb-retest-20261016/swift-test-fixed.log`
- `/tmp/bb-retest-20261016/linux-api-tests.log`

The first full-repository verification attempt hit the macOS `/var` versus `/private/var` temporary-path alias in planning-review tests. A canonical `TMPDIR=/private/tmp` cleared that stage. The next attempt lacked `ruff` on PATH. The corrected run using the installed backend tools ended with 6222 passed and these three failures:

- `tests/test_agent_relay_api.py::TestPushCallbackRoute::test_global_push_limiter_trips_before_the_run_lookup`: limiter budget/read-count assertion.
- `tests/test_cli_auth.py::test_024_FR_013_independent_processes_commit_exactly_one_session`: child-process readiness wait followed by cleanup of an unstarted child.
- `tests/test_cli_auth.py::test_024_FR_013_process_termination_rolls_back_consumption_and_mint`: child-process readiness queue timeout.

All three passed together in a separate serial run (`--no-cov`, because this diagnostic subset is not a full coverage measurement), exit 0, 4.02 seconds. Their Python implementation and tests are unchanged by this Mac-only patch. This does not establish the underlying cause of the loaded-run failures or claim that local `make verify-all` passed. Evidence: `/tmp/bb-retest-20261016/verify-all-final.log` and `/tmp/bb-retest-20261016/backend-isolated-retry.log`. The first subset attempt passed its tests but failed the whole-suite coverage floor; it was rerun with coverage disabled only for the subset, never for the full-suite gate.

## Cleanup

Signed out through the app, confirmed the local signed-out state, stopped the QA app/backend/two agents, and removed their disposable fixture state and credential-bearing files under `/tmp/bb-retest-20261016`. Retained the compiled app, non-secret results, build/test logs and call-stack diagnostics. No production data or real Keychain access controls were changed.

Rebased verification logs: `/tmp/bb-retest-20261016/build-rebased.log`, `/tmp/bb-retest-20261016/swift-test-rebased.log`, `/tmp/bb-retest-20261016/linux-api-rebased.log`. Fresh smoke fixtures under `/tmp/bb-final-qa-20261017` were signed out, stopped and removed after verification.

## Delivery blocker and maintainer decision

Read-only inspection after the failed release established:

- Organization `maxk-lab`: `deploy_keys_enabled_for_repositories=false`. GitHub documents that disabling this setting also disables existing deploy keys: https://docs.github.com/en/enterprise-cloud@latest/organizations/managing-organization-settings/restricting-deploy-keys-in-your-organization.
- The organization currently contains one accessible repository and one existing deploy key; there were no inaccessible key lists. The key `verified-trunk-landing` (ID `158071892`) is verified and already has write permission (`read_only=false`). No key rotation or secret-value access was performed.
- Active main ruleset `Tests` (ID `11196382`) requires Full CI, Docker Images, a pull request and merge queue. Its bypass list contains OrganizationAdmin and two User actors; it does not contain the landing deploy key and has no update-restriction rule.
- `landing` and `production` environments already restrict deployment branches to `main` only.
- The landing secret metadata exists; its value was never read.

The repository runbook (Required main protection, maintainer ASK) explicitly says these are “GitHub settings changes performed manually by the maintainer — never automated”. No GitHub access or protection setting has been changed in this task.

A concrete proposal to restore the already documented ADR-0008 path is prepared for maintainer review, not executed:

| Setting | Current | Proposed canonical state |
|---|---|---|
| Organization deploy keys | Disabled | Enabled; this affects deploy-key use/creation organization-wide, currently one repository/key |
| main update restriction | Absent | Enabled |
| main bypass actors | OrganizationAdmin and two Users | Only existing `verified-trunk-landing` deploy key, ID `158071892` |
| Required Full CI and Docker Images | Enabled | Retained |
| Existing PR / merge queue rules | Enabled | Retained; the trusted landing identity is the sole bypass, as the runbook requires |
| landing / production branch policy | main only | Retained |

Before/proposed non-secret metadata is retained at `/tmp/bb-retest-20261016/main-ruleset-before.json`, `main-ruleset-proposed.json`, and `org-policy-proposed.json`. The proposed files have not been submitted to GitHub. This is a separate security-sensitive configuration decision; approval to ship the code did not itself change these controls. After an authorized maintainer repair, re-read current main and the protection settings, then retry the standard release only if the tested candidate is still fresh. Do not push main directly or deploy ad hoc.
