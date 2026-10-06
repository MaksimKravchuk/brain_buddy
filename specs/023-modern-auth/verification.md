# Modern authentication verification

Status: local implementation input29411eb verified; release/feature acceptance incomplete. This file records actual evidence, including failures. It does not certify launch or GDPR compliance.

## Candidate and compatibility

- Implementation branch: `feat/modern-auth`; verified input
  `29411eba1fa0f6f13e54ec55b29635b1169100ff`, integrated base
  `143f1e813a466a7a000cd1f7e39bf4aae06c268d`. Earlier main
  `21f08d26698a434f7b1d16b991b2b43d4e0ea0f2` was integrated in `ce49b38`.
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
  `10923345745dd38e6c176ea79e91bfff6c2a7885` (historically open/unmerged).
  Final recheck: same latest head `1e63e42acb3206980cc66b297eee315f1893dcb7`,
  closed without a PR merge; its spec package is in integrated base143.
  Planning changes remain under `specs/021-mac-sync`. Existing password/me/logout wire contract,
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

## Independent retention finding and bounded repair

Independent review of `deacdb8cedd015bfddfd13f9d772d40bc745bff4` returned
**request_changes**, finding `SEC-FINAL-004`: normal privacy maintenance did not
expire authentication metadata when the delivery worker was disabled by missing
keys. The original review and synthetic reproduction remain at
`/tmp/modern-auth-final-code-review-deacdb8.json`. Two regression cases first
failed against that candidate (`/tmp/modern-auth-retention-red.log`).

Local expiry now runs in the regular privacy sweep independently of delivery,
using the same existing expiry/lease rules. The targeted unlink and maintenance
suite passed **34 tests** in 18.38 seconds
(`/tmp/modern-auth-retention-green.log`); the three final boundary cases passed
in 3.16 seconds (`/tmp/modern-auth-retention-final.log`), covering missing keys,
provider unavailability without network calls, and isolation of a transient
store failure from account deletion. These are focused results, not a full
candidate acceptance verdict.

## OpenAPI inventory correction after the interrupted 056252d run

Full `make verify-all` at `056252da83c790b6c4bcf2a92d29bb5d08285826`
found one precise contract-fixture mismatch: the six compatible account routes
now intentionally document the optional expected-owner mismatch **404**, while
the old exact error-status inventory omitted it. The run was interrupted after
the confirmed failure rather than represented as green. Preserved partial
Allure results: **1,994 passed, 1 failed, 1 skipped** under
`/tmp/modern-auth-v4-partial/backend-allure`; raw log:
`/tmp/modern-auth-023-verify-all-final-frozen-v4.log`. Interrupted pytest teardown
also produced a stash error; no final aggregate or coverage result is claimed.

Only the six expected status sets were corrected, retaining exact inventory and
error-envelope assertions. The actual application contract suite then passed
**5 tests** in 7.98 seconds (`/tmp/modern-auth-contract-final.log`). Application
code, native source and frontend source did not change in this correction.
A fresh complete run remains required.

## Complete 850f782 backend and asynchronous frontend fixture repair

At `850f782f476e8574e98406b39f994bc9d67acd0e`, the complete backend
passed **4,324 tests** in 1,388.83 seconds (1,179 warnings), with unchanged
floors passing at **98.61% lines / 95.86% branches** and Allure taxonomy passing
all 4,324 results. Raw full-chain log:
`/tmp/modern-auth-023-verify-all-final-frozen-v5.log`; preserved coverage:
`/tmp/modern-auth-v5-actual/backend-coverage.xml`.

A separate frontend coverage preflight first failed its existing Allure CLI
canary with sandbox `spawnSync allure EPERM` (**1,725 passed, 1 failed**).
The same unchanged suite with permitted subprocess execution passed **1,726
tests / 74 files** in 444.07 seconds, all unchanged floors and taxonomy:
98.99% statements / 97.83% branches / 98.76% functions / 99.51% lines.
Original failure and green evidence are retained under
`/tmp/modern-auth-frontend-sandbox-failed-850f782/` and
`/tmp/modern-auth-frontend-green-850f782/`; raw retry log:
`/tmp/modern-auth-frontend-coverage-850f782-retry.log`.

The full-chain frontend then exposed **two asynchronous fixture races**
(**1,724 passed, 2 failed**): checking code-field focus before its mount effect,
and assuming conflict recovery's persistence/refetch/save completed after one
fake-timer advancement. Its aggregate remains **failed**; browser lanes did not
run. Actual failed Allure records are preserved under
`/tmp/modern-auth-v5-actual/frontend-failed/`.

Only those test waits were repaired: wait for focus, and for actual refetch/UI
and second save while recovery timers are real. The local graph and required
revision assertions remain intact; application code, timing contracts and floors
are unchanged. An intermediate two-file run passed 127 tests in 33.18 seconds
(`/tmp/modern-auth-async-fixtures-green.log`); after the final explicit UI-ready
wait, the two affected cases passed in 6.78 seconds
(`/tmp/modern-auth-async-fixtures-final.log`; other 125 cases were filtered).
Typecheck and lint passed. A fresh complete frozen-candidate chain is required.

## Complete local verification at 630e812 and current native integration

The frozen `630e812cfb5713b9e1db026ddcf605ed724c351a` completed the
canonical `make verify-all` with exit **0**. Browser checks ran first, followed
by the two unit suites; all original targets and recipes remained required.
Backend: **4,324 passed**, coverage floors **98.61% lines / 95.86% branches**,
Allure taxonomy 4,324. Frontend: **1,726 passed / 74 files**, unchanged floors
**98.99% statements / 97.83% branches / 98.76% functions / 99.51% lines**,
Allure taxonomy 1,726. Legacy browser: **65 passed**, one optional external
model case skipped. Modern auth: **14 passed**. All executed browser cases
passed on the first attempt, with no flaky cases; combined freshness, taxonomy
and six required native-product stories passed. Raw log:
`/tmp/modern-auth-023-verify-all-final-frozen-v7.log`; actual archive and
aggregate: `/tmp/modern-auth-v7-actual/aggregate-summary.json`.

The modern suite exercised real application, SQLite, session and signature
validation with isolated synthetic Google/Apple upstreams and SMTP capture.
At 1440×1000 and 390×851, ten held-response interactions gave visible pending
feedback within **29.6 ms maximum**, one submission, disabled duplicate
controls, visible keyboard focus and 44 CSS-pixel targets. Fourteen Axe results
had zero violations, with fourteen masked screenshots. Evidence retains the
actual `630e812` input SHA; it is not live provider or physical-iOS evidence.
Legacy CRT kept its original 200 ms thresholds and 120 measurements. Its
generated candidate field is null; outer inventory/hash evidence provides the
local source context, not a release-bound artifact.

Earlier V6 failures remain preserved in
`/tmp/modern-auth-v6-actual/legacy-failed/`: CRT zoom exceeded its unchanged
budget, and completed-task verification failed. Independent reproduction found
an existing autosave race (`BASELINE-TASK-ACK-SYNC-001`, P2): an intervening sync
updates the mutable revision baseline before a valid acknowledgement is
validated. It remains outside this auth change and is unresolved; a passing
repeat does not repair it or prove the original failure's exact wire ordering.

Public `main` advanced to `143f1e813a466a7a000cd1f7e39bf4aae06c268d`.
The full seven-commit advance includes native Weekly Review implementation as
well as the latest commit's 30 Mac-spec documents. It was fetched read-only and
merged locally without conflicts. Mac PR265 remains the other chat's work;
its observed head was `1e63e42acb3206980cc66b297eee315f1893dcb7`.
The modern workspace completion now reuses Weekly Review's existing local
account-linking preparation, and checks cancellation again after that async
step. Three bounded regressions cover server-side preservation of local parks,
storage failure before any credential submission with the outbox preserved,
and cancellation while preparation waits. These new integrated native inputs
require fresh Swift tests and candidate verification; the completed 630 run
is historical evidence for its own SHA only.

## Final integrated local verification at 29411eb

Verified implementation input: `29411eba1fa0f6f13e54ec55b29635b1169100ff`; integrated main/base: `143f1e813a466a7a000cd1f7e39bf4aae06c268d`. The fresh complete `make verify-all` exited **0**. Only target ordering was supplied through `--eval`: browser first, then both unit suites. Every original target, recipe and artifact/coverage gate remained required. The actual explicit candidate field is294. Same-source pinned backend/frontend E2E images were reused after verifying production source equivalence; no fresh image build or image-label SHA is invented.

- Backend: **4,324 passed**,1,179 warnings,1,325.76s; coverage **98.61% lines/95.86% branches** against unchanged98.47%/95.61%; taxonomy4,324.
- Frontend: **1,726 passed/74 files**,425.30s; coverage **98.99% statements/97.83% branches/98.76% functions/99.51% lines**, above unchanged98.76%/97.77%/98.64%/98.84%; taxonomy1,726.
- Browser: **65 legacy +14 modern passed**, one optional external-model skip, zero failures/flaky/retries. Freshness79 executed results, taxonomy80 and six required product stories passed.
- Headed modern Chromium151 at1440×1000/390×851: ten real held-response interactions, **16.2ms maximum** pending feedback, single dispatch, disabled duplicate controls, visible keyboard focus,44 CSS-pixel controls, no horizontal overflow. Fourteen masked PNGs and14 Axe scans, zero reported violations; three account-surface scans each retain an incomplete rule. Actual two-screen visual inspection is bounded to these web viewports.
- Legacy CRT: current294 identifier,120 samples,104.5ms aggregate p95,119/120 within200ms against unchanged required114; each operation p95≤134.6ms. This pass does not erase the earlier219.1ms failure or repair the independently reproduced baseline autosave P2.
- Complete Swift package: framework summary **776 tests/74 suites passed in56.959s**, including all five modern workspace cases. One opt-in live-backend endpoint test/suite skipped. Actual older source:2pass/3fail/fourissues; actual final repair:all three regressions pass. All160 source/script hashes and11,984 official runtime regular-file hashes were verified after execution.

The canonical native script is unchanged. Default official Swift-image container creation failed ENOSPC before execution. The green run used the script's supported `SWIFT_IMAGE` override: preserved official Swift6.2.4 compiler/runtime in the package bind mount and a compact original Ubuntu runtime image. The failed default/chroot-loader attempts and actual runtime/source provenance remain retained. This is local full-package proof, not Xcode, current public `ios-kit`/`ios-app`, Mac-device or physical-iOS evidence.

[Actual aggregate](evidence/local-29411eb/aggregate-summary.json), [167-path source manifest](evidence/local-29411eb/source-manifest.json), [browser observation snapshot](evidence/local-29411eb/browser-observation.json), [native summary](evidence/local-29411eb/native-summary.json), [native source/input](evidence/local-29411eb/native-input.json). The browser snapshot honestly says aggregate was running at its earlier observation; the separate actual aggregate records the later completed result. Raw full log: `/tmp/modern-auth-023-verify-all-final-integrated-v8.log`, SHA256 `037c29cadf6ac486390664ace0e137daa399130508d2c378328e1967e5af5f81`. Native raw log SHA256 `9aed719e0f72c58170f1407959fdc17171e4ed0cfb6e0b65beecf1f4772377bc`. Archives remain `/tmp/modern-auth-v8-actual/` and `/tmp/modern-auth-native-weekly-review-*`.

Mac PR265 was rechecked near19:39UTC: same head `1e63e42acb3206980cc66b297eee315f1893dcb7`, closed at2026-10-06T17:57:59Z, GitHub `merged=false`; the30-file spec package is already in integrated main143. Earlier open/unmerged observations remain historical. Mac implementation stays owned by the other chat; existing password/me/logout/default-client/Keychain contracts are preserved. PR270 remains open draft at4439c00.

The validated [writer receipt](pre-freeze-writer-receipt.json) proves four local writer obligations for294. Correct path classification is **ASK** (process exit1 correctly refuses automatic promotion), not release authorization. Independent bounded static/native/browser reviews approve the inspected code/evidence with zero new findings; actual reviewer runtime-model identity remains unverifiable. Readiness/traceability is separate from formal grading.

Required current public iOS lanes, physical-native interaction/provider flows, live configured OAuth/SMTP/private relay/notices, production disclosure inputs and release evidence remain unverified. Formal [acceptance](acceptance.md) is **not_run** under the skill's explicit unmet precondition; [report](report.md) records all remaining tasks. Final evidence-only documentation does not relabel tests or reviews as its later commit SHA, exact public CI or a deployed build.

Current independent readiness: **19 covered/13 weak/1 missing**,not_ready/not_graded. [Byte-preserved audit](reviews/final-implementation/modern-auth-acceptance-readiness-29411eb.json) independently matched50 representative test references,4,324 backend/1,726 frontend/79 browser passes plus optional skip, current coverage and the local typed receipt. [Traceability](traceability.md) retains the reviewer's exact statements, statuses and limitations.
