# Modern authentication verification

Status: implemented candidate under verification. This file records actual
evidence, including failures. It does not certify launch or GDPR compliance.

## Candidate and compatibility

- Implementation branch: `feat/modern-auth`; current main
  `21f08d26698a434f7b1d16b991b2b43d4e0ea0f2` integrated in `ce49b38`.
  Concurrent main introduced `022-task-mcp`; this feature moved to
  `023-modern-auth` after checking all 113 local refs. Only its authored paths
  and qualified test labels changed; original reviewer outputs/digests remain
  verbatim historical evidence, with a separate renumbering disposition.
- Review PR: [#270](https://github.com/MaksimKravchuk/brain_buddy/pull/270), draft.
  Smart-HTTP push returned 401; publishing uses authenticated Git Data API with
  remote/local tree equality checked. Original local history is retained in
  `backup/modern-auth-local-7dfc962`; no main or production ref was modified.
- Mac PR [#265](https://github.com/MaksimKravchuk/brain_buddy/pull/265)
  inspected before implementation and rechecked at head
  `10923345745dd38e6c176ea79e91bfff6c2a7885`: open, unmerged, planning changes
  under `specs/021-mac-sync`. Existing password/me/logout wire contract,
  default shared client identity and Mac Keychain namespace are preserved.
  Future remembered-email/outbox handling still belongs to 021.
- The CI native lane now also builds/tests the Mac app with the same shared
  package. A green job title alone will not count: inspect RUN=true, checkout
  SHA and executed commands.

## Executed checks

| Check | Actual result | Scope / limitation |
|---|---|---|
| First complete backend run | 3,639 passed, 2 failed, 1,255.13 s | 3,641 cases on pre-main-merge backend. Failures: old public API inventory; rollback shell fixture missing new capture/environment. Both repaired; 50 focused regression cases passed. |
| First backend coverage | lines 97.21%, branches 92.35% | Below immutable floors 98.47% / 95.61%; verification remains red. Pytest's separate 95% aggregate check is insufficient. |
| First complete web run | 1,658 tests / 71 files passed, 390.46 s | All existing and new unit tests passed. |
| First web coverage | statements 97.38%, branches 96.14%, functions 97.30%, lines 98.83% | Below repository floors; verification remains red. Additional failure/recovery coverage in progress. |
| Complete web run after coverage repair | 1,710 tests / 73 files passed, 417.53 s | Actual full lint, typecheck, Vitest, taxonomy and build passed before the latest main MCP merge; candidate-bound rerun follows. |
| Repaired web coverage | statements 99.01%, branches 97.83%, functions 98.80%, lines 99.51% | All immutable repository floors passed; no suppression or floor decrease. |
| Independent security review | initial changes requested; repaired Apple changes approved | Actual review files below. Three reproduced defects: relay delivery disable, revoked-state wire/reconnection, associated notice receipt erasure. Red tests reproduced all three; 44 focused tests and independent equal/newer-consent checks passed after repair. Whole-feature acceptance was not granted. |
| Provider return hydration regression | 1 failing regression / 3 old passing; then 4 passed | Actual browser found callback racing account hydration. Repair waits for settled hydration before owner assertion; timeout invalidates continuation. |
| Disabled-provider reconnection | 1 failing regression / 6 old passing; then 7 passed | Inactive connected methods offer Reconnect and fresh consent rather than ineffective Remove. |
| Worker real-app browser run | 9/9 passed, 59.4 s | Product base `5e5b01d`; synthetic Google/SMTP boundaries, actual signed RSA assertions, SQLite, app and UI. Three masked screenshots and sanitized Axe summaries retained. |
| Integrated real-app browser runner | 9/9 passed, 40.3 s | TLS runner against root candidate with current main. First failed attempt lacked Playwright's FFmpeg; installed recording dependency, then passed. |
| Worker keyboard timing | 22.4 ms, busy+disabled, 1 dispatch, retained focus | Chromium 151 headless, 1280×720. Headed candidate run is in progress; this is not physical iOS evidence. |
| Actual headed browser run | 9/9 passed, 1.3 min | Candidate product `9451af0`; Chromium 151 with Xvfb display, 1280×720 and 390×851 checks. Three masked screen images retained. |
| Headed keyboard timing | 28.1 ms, busy+disabled, 1 dispatch, retained focus | Measurement attachment confirms `headless:false`. Response held at real API boundary, completed by actual mail proof. |
| Headed accessibility | zero Axe violations on all three scanned surfaces | Login's moderate landmark findings were repaired by using the existing layout's semantic main landmark. This is web evidence, not native device evidence. |
| Repository meta gates | check-specs passed; validate-ci passed with local socket access | Default sandbox first blocked socket fixtures; rerun with approved local execution passed. |
| Previous native package run | 614 tests in 65 suites passed | Implementation worker's Linux Swift 6.2 run before final aggregate. Candidate-bound native/CI evidence still required. |
| Aggregate Linux native package | 614 tests / 65 suites passed, 59.213 s | Actual Swift 6.2 run on the integrated foundation/auth tree. Device/Xcode acceptance is separate. |
| Native Apple corrupt/retired-key regression | 79 cases passed / 2 reproduced failures; after repair 81 passed | Decryption moved into the claimed attempt's terminal exception boundary. No upstream call or authority on either failure; unchanged tests passed after repair. |
| Final aggregate start after main merge | meta gates and backend static checks passed; runner blocked before pytest | Workspace filled during local Docker rebuild; removed only enumerated disposable task build caches, preserving images/data. Fresh full chain follows. |
| PR CI at e4e4eab | actual native kit passed; frontend, iOS host and secret scan failed | Node22 Blob realm assertion, inaccessible native error initializer, and two public-value scanner false positives repaired at 4439c00; rerun pending. Claude review runtime returned is_error:true without an assessment. |
| Final independent code review at e4e4eab | changes requested | Reproduced removed-provider public sign-in/restoration and retention defect; native cancellation/compile findings also recorded. Scoped native fixes are at 4439; unlink repair and separate exact-SHA re-review follow. Obsolete local aggregate was stopped before product mutation; it is not a pass. |
| Signed Apple browser continuation | 10/10 full browser journeys passed | Includes actual cross-site form POST/binder, valid ES256 client secret and RS256 Apple assertions, relay signup, stable-subject return without email, and collision rejection. Synthetic boundary evidence only. |
| PR CI at 4439c00 | native and frontend passed; backend coverage failed | Run 37476125539 actually executed RUN=true. iOS simulator host/widgets build, 614 shared Swift tests, 71 Mac tests and 1,710 web tests passed. Backend: 4,270 tests passed, but lines 98.36% / branches 95.25% failed unchanged 98.47% / 95.61% floors. Dependent Docker/E2E/mutation lanes were skipped; the aggregate is not green. |
| Explicit Remove regression and repair | initial 11 failed / 1 passed; repaired focused suites green | Storage repair 8151d74 integrated at 4594804. Google mappings are erased immediately; explicit Apple unlink retains only bounded cleanup linkage, erased after terminal/expired work. Public sign-in cannot reactivate removed ownership. Actual focused executions: 41 Apple/unlink, 150 authority, 140 storage/broker/regression; static and Allure checks passed. Final integrated rerun follows. |
| Additional HTTP/storage/legacy boundaries | 74 tests passed, 37.14 s; Allure taxonomy and formatting/lint passed | Real SQLite payload/index disagreement rejection, invalid-JSON transaction rollback, Apple cross-site form and one-use handoff, Google malformed callback rejection, competing legacy email/invite writes and seed credential recheck. These preserve security behavior and immutable coverage floors. |
| Frozen df94 native package | 614 tests / 65 suites passed, 46.211 s | Exact candidate package sources archived into the already owned Swift6.2 container. The canonical script first failed during a new VFS container copy (ENOSPC); the equivalent complete Swift test command actually ran and passed. No Xcode/device claim. |
| Frozen df94 independent code review | approve bounded code, zero remaining findings | 249 independent domain/SQLite/Apple tests and a separate removed-Google-authority reproduction; all three original findings resolved. Actual execution/input SHAs and scoped source equivalence retained. Full acceptance not granted. |
| Final headed browser repair | 14/14 passed; ten pending measurements 7.6–38.2 ms | Actual worker SHA bae4571; all five actions at 1440×1000 and390×851, visible busy/disabled state, one dispatch, keyboard focus, 44px controls, no overflow;14 Axe scans/zero violations. Auth/browser source equals df94; privacy disclosure text differs, so no whole-tree equality is claimed. |
| Frozen df94 complete backend attempt | 4,312 passed / 1 failed, 1,247.98 s; coverage floors passed | Lines98.60% / branches95.84% exceed unchanged98.47% /95.61% floors. A pre-existing voice sweep shutdown fixture omitted the wake signal used by actual app shutdown; corrected to signal stop+wake and always join, with6 focused maintenance tests passing. A fresh full chain is required after that test repair. |
| Final publication | blocked by automatic approval review | Creating the next Git tree for the existing public PR was rejected for absent explicit permission to publish the prepared new files to public GitHub. No bypass or alternative upload attempted. Remote remains4439c00; final exact public CI cannot run yet. |

Independent reviews:
[initial](reviews/implementation-security-5fc4a6a.json),
[repair review](reviews/implementation-security-8f3adb83.json),
[final candidate changes requested](reviews/implementation-security-e4e4eab3.json),
[merge and renumbering disposition](renumbering-review.json).
The bounded disposition checks immutable `ce49b38`; historical six-lens
review bytes and original planning digest are preserved, without restamping.

Log files remain in this execution workspace under `/tmp/modern-auth-*`.
Generated Allure and browser artifacts are ignored build evidence; fresh final
CI artifacts must bind to the frozen implementation SHA.

## Implementation locations and justified deviations

- The explicit migration orchestrator is `backend/app/services/auth_migration.py`;
  repositories own SQLite state. This keeps orchestration out of persistence.
- Apple grant cleanup has its own bounded service,
  `backend/app/services/auth_apple_lifecycle.py`; orchestration calls it from
  `modern_auth_service.py` and the existing account lifecycle.
- Privacy/cleanup tests use `test_auth_apple_lifecycle.py`,
  `test_auth_migration_integration.py`, `test_modern_auth_authority_edges.py`
  and `test_modern_auth_apple_integration.py` rather than duplicate test files
  suggested by T034. Assertions cover actual durable state and archive content.
- Web security controls live in `features/auth/AccountSecurity.tsx`, callback
  routing in `app/AppRoutes.tsx`; existing account/task behavior is reused.
- Provider/email operations are documented in
  [modern-auth-operations.md](../../docs/modern-auth-operations.md), rather than
  a second overlapping auth-setup guide.
- A separate TLS browser fixture is necessary because optional modern auth is
  intentionally disabled in the existing legacy Compose acceptance stack.
  Both suites remain required; the new runner does not replace legacy E2E.
- Gate integrity changed only for strengthened Makefile checks: migration guard
  tests and modern browser journeys. Coverage floors and validators unchanged.

## Remaining evidence

1. Execute the integrated unlink authority/retention repair and complete required suite on the final
   SHA, and verify native CI really executes against that same candidate.
2. Retain final-candidate synthetic Apple browser and headed web reference artifacts.
   The implemented ten-journey suite already passed; final aggregate rerun follows.
3. Physical iOS: ASWebAuthenticationSession/Apple cancellation and return,
   autofill, Dynamic Type, 44-pt controls, pending feedback and preserved outbox.
4. Real configured Google, Apple and SMTP smoke. Provider accounts existing
   does not supply OAuth IDs/private keys/sender configuration to this workspace;
   current runtime reports no configured secret bindings.
5. Actual controller/processor agreements and disclosures, stopped-writer
   migration, approved exact-SHA release and production smoke. No production
   mutation or claimed live success has occurred.

The full acceptance gate is not ready while T033/T041–T044 remain incomplete.
Do not turn missing device/live/production evidence into passing mock results.


## Full local run at 1f4e7c4 and follow-up browser repairs

Frozen SHA `1f4e7c4b12cf016010ccd366a348b8e7ca2bbc49`: actual
`make -j2 verify-all` ran the complete prerequisite graph. Backend **4,313
passed** in 1,603.90 seconds; unchanged floors passed at **98.60% lines /
95.86% branches**, and Allure taxonomy passed for all 4,313 results. Frontend
**1,710 passed** in 412.56 seconds; unchanged floors passed at 99.01%
statements / 97.83% branches / 98.80% functions / 99.51% lines. Raw log:
`/tmp/modern-auth-023-verify-all-final-frozen-v3.log`; preserved coverage reports:
`/tmp/modern-auth-v3-actual/`. The aggregate is **failed**, because old browser
helpers did not select the newly explicit password/invite flow; only that lane
was terminated (143) while the complete backend lane continued to completion.

An isolated real Compose browser preflight of the prepared helper patch ran
all 66 legacy journeys: **56 passed, 9 failed, 1 skipped**. Actual failures
exposed unconfigured password-account actions requiring new origin/proof keys,
nginx injecting noncanonical X-Request-ID values into UUID-validated routes,
Hermes card discovery through the managed container proxy, a 236.3 ms CRT
selection p95 under concurrent server load, and a voice failure-journey timeout.
The optional model-backed vNext journey was skipped; it is not a pass. Raw
results and diagnostics are retained under
`/tmp/modern-auth-legacy-e2e-preflight/`. They do not certify the final candidate.

Follow-up repairs restore existing password-account controls only after explicit
successful unconfigured discovery, preserve connected metadata, refuse a
passwordless/network-failure downgrade, and bind compatible account requests to
the displayed owner. A late account switch prevents export download. Existing
native requests without the optional owner header remain compatible. nginx no
longer injects its 32-hex request identifier into the UUID-validated API header.
The final browser execution uses a task-local Docker proxy configuration with
only the known private Compose hosts/IPs added to NO_PROXY; the external proxy
and original Docker configuration remain unchanged. No vendored Hermes or A2A
security policy was modified to obtain a pass.

Focused real HTTP regressions: **35 passed** in 45.93 seconds, Allure taxonomy
passed (`/tmp/modern-auth-unconfigured-backend-green.log`). Sandboxed HTTP
attempts stalled or used the wrong working directory and are not passes.
Focused frontend: **75 passed**, typecheck and lint passed
(`/tmp/modern-auth-unconfigured-frontend-final2.log`); earlier test fixture/name
errors were corrected without removing outcome assertions. A fresh final full
chain and independently reviewed candidate are still required.
