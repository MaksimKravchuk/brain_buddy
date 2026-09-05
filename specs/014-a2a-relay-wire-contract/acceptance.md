# Acceptance: A2A Relay Wire Contract

**VERDICT**: accept
**Feature**: `specs/014-a2a-relay-wire-contract/`
**Graded**: 2026-09-05  **Implementation SHA**: `c14b32debe778d643d1c9de4a0e5cb8efe2300d5` (`c14b32d`; tree identical to PR #192 head `e5603d7`)
**Re-checked**: 2026-09-05, after three documentation-only fixes to first-pass findings (see "Re-check" below)
**Auditor**: `acceptance-auditor` (did not write the code under grade)

Writer-owned pre-freeze evidence is a separate artifact validated by
`scripts/validate_pre_freeze_receipt.py`; this post-freeze acceptance verdict
must not substitute for it. Review, QA, CI, landing, deploy, and smoke are
post-freeze obligations under ADR-0008.
<!-- BrainBuddy pre-freeze receipt contract: acceptance. Preserve this section. -->

## Where the browser evidence comes from

**The Playwright layer of this audit is CI's evidence, not local.** The Compose
stack cannot start in this sandbox (no Docker daemon) and the artifact host is
blocked by the egress proxy, so the local `frontend/allure-results/playwright`
store holds 40 **skipped** results and proves nothing —
`validate_ci_artifacts.py product-e2e-results` fails against it here, by design.

What is accepted instead is workflow run 875 (`33971103803`) on head
`e5603d7`, whose tree is identical to the audited worktree. During this audit
the GitHub API was queried directly and independently confirmed:

- job **`Compose Playwright E2E`** `101320597656` — **success**; step 9
  "Run Compose smoke and Playwright E2E" (14:22:20Z–14:24:18Z) and step 10
  "Validate Playwright Allure results" both success. Step 10 is the workflow's
  own anti-fake gate: it runs `validate_ci_artifacts.py results … --since-file
  frontend/allure-results/playwright/.run-started-at`,
  `validate_ci_artifacts.py product-e2e-results` and
  (inside `make test-e2e`) `validate_allure_taxonomy.py --label playwright-e2e`.
  The job would have failed had any of the three failed — the previous head
  `e753439` failed exactly there.
- job **`Allure Report`** `101321369840` — success, including
  `allure quality-gate` at `maxFailures: 0`.
- the only red jobs in run 875 are `Spec Kit artifacts` (missing
  `acceptance.md` / `traceability.md` / `report.md` — this file and its
  companion answer two of the three) and `Full CI`, which fans in from it.
- Playwright: 40 tests, 39 passed, 1 pre-existing skip. All four relay stories
  in `frontend/tests/e2e/agent-relay.compose.spec.ts` passed on the first
  attempt. Artifact `playwright-allure-results` id `9971110271`, sha256
  `06148d7b2e6181065e6f7176e523fce06c64affd647801a02a80a931b250e21d`.

Per `docs/e2e-acceptance-charter.md` the relay stories are graded against the
**External agent relay product matrix** (Allure epic `External agent relay`),
not against the native `BrainBuddy MVP loop` story list that
`product-e2e-results` enforces; CI ran and passed both.

## Re-check

Three findings from the first pass were addressed in the worktree and re-graded.
`git diff` shows the change set is **documentation only** — one table in
`docs/e2e-acceptance-charter.md` and four docstrings across two test files. No
assertion, fixture, product line or configuration value changed, so the local
Allure stores remain valid evidence for every assertion they record. The eight
affected tests were nonetheless re-run from `backend/.venv` at re-check time:

- the three `AC-011` refusal tests plus the replay test — **8 passed in 1.56 s**;
- `test_014_SC_006_a_delayed_agent_is_sent_then_observed_complete` — **1 passed
  in 10.83 s** against the real unmodified Hermes process.

1. **Charter rows corrected** — the `A2A hand-off to the helloworld sample` and
   `A2A hand-off to the Hermes stub` rows now claim only what their stories
   assert and name the tests that carry the rest. Both stories remain required
   evidence gates under epic `External agent relay`; nothing was deleted from
   the matrix. **014-SC-004, 014-SC-005 and 014-SC-006 move from `weak` to
   `covered`** — my `weak` finding was precisely "the clause is proved at a
   lower layer than the charter requires", and the charter now requires the
   layer where the proof lives, naming the specific test for each clause. Each
   of those named tests was read in full during the first pass, so this is a
   re-grade against a corrected authority, not a concession: had any clause
   lacked a test, the row would have read `missing` and no document edit could
   have changed it.
2. **`AC-011` now traced** — the three refusal tests in
   `test_agent_relay_service.py` cite `AC-011`; the id appears at three sites
   where it previously appeared at none. `AC-010` remains covered by the replay
   tests (`test_replaying_the_dispatch_returns_the_same_run_without_restarting`,
   `test_014_SC_002_three_replays_create_one_task_and_one_exchange`, the two
   loopback tier tests and the two conformance replays).
3. **SC-006 docstring corrected** — it now states that a token-secured Hermes
   refuses to push to a private callback, so the scheduled observation is what
   settles the run. That is what the test's `{event.trigger} == {"schedule"}`
   assertion has always checked; prose and assertion now agree.

Two things this re-check did **not** soften, and one error of my own:

- the three unasserted loading states (D-01-S02, M-01-S02, M-03-S20) stay on the
  record for a human waiver, unchanged;
- the caveats behind the three re-graded rows stay in `traceability.md`: the
  SC-004 component `it.each` renders a fixture-supplied label rather than
  proving derivation, the iPhone-width review surface has no device journey at
  any layer in this repository, and SC-006's settle is measured at a scaled 5 s
  interval;
- **my own citation error**: the first pass cited
  `TestHandOffReview::test_a_replayed_confirmation_returns_the_same_run` for
  AC-010, and no such test exists. It is corrected. I then re-verified all 152
  Python test names cited in `traceability.md` against `def <name>(` in
  `backend/tests` — 152/152 present — and all 24 Vitest/Jest titles against
  their source files — 24/24 present. One residual mislabel that is not mine:
  `test_agent_relay_api.py::TestHandOffRoutes::test_an_untested_connection_refuses_the_hand_off`
  still reads `AC-010 over HTTP` while asserting AC-011 behaviour.

## Tally

| | count |
|---|---|
| criteria total | 64 (17 FR + 10 SC + 37 AC) |
| covered | 64 |
| weak (test exists but does not exercise it) | 0 (3 at first pass: SC-004, SC-005, SC-006) |
| missing | 0 |
| hollow tests found | 0 |

Full matrix: `traceability.md`

## Blockers

None. No criterion is `missing`, no result predates the implementation commit,
and none of the eight tests read in full is hollow.

Three design states remain unasserted and are recorded below for a human
waiver. No criterion is weak after the re-check; the caveats behind the three
re-graded criteria are kept in the `traceability.md` evidence column rather than
dropped.

## Evidence

| check | command | result |
|---|---|---|
| product-e2e stories | `validate_ci_artifacts.py product-e2e-results --path frontend/allure-results/playwright` | **fail locally** (`expected active native product scenarios, found 0 active result(s)` — all 40 local results are `skipped`, no Docker); **pass in CI** run 875 job 101320597656: `native-product-e2e: found 39 meaningful passing result(s) covering 6 required stories` |
| relay product matrix | `docs/e2e-acceptance-charter.md` → External agent relay; 4 stories under epic `External agent relay` | pass (CI run 875; all four passed first attempt) |
| result freshness | `validate_ci_artifacts.py results --path <store> --label <label> --since-file <marker at 2026-09-05T14:08:51Z = commit c14b32d>` | pass — backend 2800 executed, frontend-vitest 918 executed, mobile-jest 1534 executed, every result file written 14:33–14:38 UTC, after the implementation commit at 14:08:51 UTC |
| allure taxonomy | `validate_allure_taxonomy.py --path backend/allure-results --label backend-pytest` (and vitest / mobile-jest) | pass — 2935 / 930 / 1534 files, taxonomy OK on all three; `--label playwright-e2e` passed in CI on the 39 executed results |
| result statuses | direct read of every `*-result.json` | backend 2935 passed / 0 failed / 0 broken; vitest 930 passed; mobile 1534 passed |
| requirement coverage | `check_requirement_coverage.py specs/014-a2a-relay-wire-contract` | pass — 27/27 traced |
| backend coverage | `validate_coverage_floor.py --stack backend` → line 98.57% / branch 95.62% (floor 98.47 / 95.61) | pass |
| frontend coverage | line 99.12 / stmt 98.93 / branch 97.84 / func 98.71 (floor 98.84 / 98.76 / 97.77 / 98.64) | pass |
| mobile coverage | line 95.71 / stmt 95.68 / branch 90.88 / func 96.40 (floor 94 / 94 / 88 / 95) | pass |
| review gate | `.specify/workflows/runs/014-campaign-2/planning-review-summary.json` | `founder-accepted`, recorded in `review.md` |
| task ledger | `specs/014-a2a-relay-wire-contract/tasks.md` | 131 ticked, 0 open |
| bespoke-wire residue | auditor's own `grep -rn "signing_secret\|agent-events" backend/app frontend/src mobile/src` | one prose comment and one unrelated `idx_agent_events_run` index name; no code path, no fixture |
| cited-test existence | auditor's own sweep of every name in `traceability.md` against `def <name>(` and against the Vitest/Jest sources | pass — 152/152 Python names, 24/24 component titles (one bad citation in the first pass was the auditor's and is corrected) |
| re-check re-runs | `pytest` on the 4 edited-docstring tests from `backend/.venv` | pass — 8 passed (1.56 s) and 1 passed (10.83 s, real Hermes process) |

### Feature-qualified id sweep

Every `014-FR-001…017` and `014-SC-001…010` appears in at least one test name or
Allure label; `014-FR-015` appears exactly once
(`test_agent_relay_service.py::test_014_FR_015_last_contact_is_the_latest_of_every_kind_of_contact`)
and `014-SC-004` only in the dashed form used by Vitest/Jest/Playwright titles.
Bare `FR-001`-style ids were not accepted as evidence anywhere.

Acceptance scenarios: **AC-001 … AC-037 all appear except `AC-011`**, which is
cited in zero test files. Its three covering tests exist and are named in
`traceability.md`; each carries `AC-010` in its docstring instead. That is a
citation defect, not a coverage hole — the behaviour (untested, stale and
cross-owner connections refused before any content leaves) is asserted three
ways, with `sends(a2a_client) == []` each time.

## Measured criteria

| criterion | target | measured | source | tier |
|---|---|---|---|---|
| SC-001 | complete through **Agent reported complete** against 2 unmodified runtimes | 2/2: a2a-sdk `helloworld` (`result_text` contains the sample's own answer, `primary_state_label == "Agent reported complete"`) and Hermes (`test_014_SC_006_a_delayed_agent_is_sent_then_observed_complete`) | `backend/allure-results`, SHA `c14b32d`; plus CI run 875 story `014-SC-005 A2A hand-off to the helloworld sample` | INTERNAL floor |
| SC-002 | exactly 1 task at the agent after 3 replays | 3 replays → `len(tasks) == 1` asked of the **agent** via `ListTasks(contextId)`, on both runtimes and again in the browser story; a guaranteed-tier loopback agent returns 1 of 3 distinct ids while a best-effort one returns 3 | `backend/allure-results`; CI run 875 story `014-SC-002 A2A replay creates one task` | INTERNAL floor |
| SC-003 | 0 accepted state changes, 0 secret disclosure, rejections indistinguishable | 4 rejection classes → identical status (403) and identical bodies modulo `reference_id`, no `Retry-After`, no `WWW-Authenticate`; 50 unknown-run probes → `push_run_limiter.key_count == 0` and 0 new audit rows; 200-probe flood → same; 5 forged tokens → exactly 1 audit row | `backend/allure-results`; CI run 875 story `014-SC-003 A2A security rejections` | INTERNAL floor |
| SC-006 | ≤ 60 s (one observation interval) to the true terminal state; reply window ≥ 300 s | interval default `60` and reply-window floor `300` pinned by `test_014_FR_008_agent_relay_settings_expose_observer_pools_and_bounds` (`reply_window_seconds=299` raises); the settle itself measured against the real Hermes process at a scaled 5 s interval, agent delay 3 s | `backend/tests/test_config.py`, `backend/tests/test_agent_a2a_reference_hermes.py` | INTERNAL floor |
| SC-007 | content ≤ 30 days, identifiers ≤ 90 days, run id to purge | clock +31 d → `content_expired` and every text field `None` **before** the sweep; clock +91 d → `message_id`, `agent_task_id`, `interface_url`, `card_fingerprint`, `push_token_fingerprint` all `None`, events `[]`, `run.id`/`context_id` retained; clock +200 d → live connection card and fingerprint intact | `backend/allure-results` | INTERNAL floor |
| SC-008 | at most 1 agent-side action per command family under a barrier | 2 threads through a blocking client → `len(sends) == 1`; reply and cancel parametrised with and without the operation lock | `backend/allure-results` | INTERNAL floor |
| SC-010 | 0 bespoke code paths, tests or fixtures | `/api/agent-events` and `…/signing-secret` → 404; `import app.modules.agents.connector` → `ModuleNotFoundError`; auditor grep finds none in `backend/app`, `frontend/src`, `mobile/src` | `backend/allure-results` + auditor grep | INTERNAL floor |

No criterion in this feature is voice-related, so no
`scripts/voice_evidence_report.py` run is required or cited.

## Design state coverage

`design.md` declares 129 state ids. 50 are cited by id in a test; the rest were
checked by matching their surface and copy against the component suites. Summary
plus every state that does not come out clean:

| design state id | tested by | status |
|---|---|---|
| D-01-S01, S08–S12, S14, S16, S18–S23, S25 | `AgentSettingsPage.test.tsx`, `agentCopy.test.ts`, `test_agent_relay_service.py::TestConnectByAgentCard`, `test_agent_a2a_card.py` | covered |
| D-01-S03 empty, S05 error, S07 offline | `AgentSettingsPage.test.tsx::shows an empty state once the list loads with no connections`; `::reports a failed connection load instead of showing an empty agent list`; `::never queues an offline connection create for automatic replay` | covered (implemented copy differs from the design draft copy; the states themselves are asserted) |
| D-01-S13, S15, S17, S24 | `test_agent_relay_service.py::test_014_FR_002_the_four_unsupported_categories_keep_their_own_detail`, `::test_014_FR_002_transport_failure_and_deadline_breach_read_as_unreachable`, `AgentSettingsPage.test.tsx::rotates the credential against the revision the user is looking at` | covered |
| D-02-S01–S15 (review) | `AgentHandoffOverlay.test.tsx` (33 cases) + `test_agent_relay_api.py::TestHandOffContractOverHttp` + CI story `014-SC-005 …helloworld sample` | covered |
| D-03-S01, S03–S19, S21–S27 (run panel) | `AgentRunSection.test.tsx` (`014-SC-004 every run state reads as itself`, the D-03-S07/S10/S11/S16/S18/S26/S27 cases), `TaskDetailPanel.test.tsx`, `TaskListPage.test.tsx` | covered |
| D-03-S02 loading | `AgentRunSection.test.tsx` asserts `Loading runs…` | covered |
| M-01, M-02, M-03 (iOS) | `ConnectionCard.test.tsx`, `AddConnectionSheet.test.tsx`, `DisconnectSheet.test.tsx`, `RotateCredentialSheet.test.tsx`, `HandoffSheet.test.tsx`, `AgentRunSection.test.tsx`, `TaskAgentSection.test.tsx`, `agentGuards.test.ts`, `mobile/src/app/__tests__/agents.test.tsx` | covered |
| D-02-S03 loading | `AgentHandoffOverlay.test.tsx` asserts `Building the hand-off preview…` | covered |
| **D-01-S02 loading** | none — `AgentSettingsPage.tsx:77` renders `Loading connections…`; the line is executed (file at 100% line coverage) but no test asserts the skeleton | **unasserted** |
| **M-01-S02 loading** | none — `mobile/src/app/agents/index.tsx:69` renders a bare `ActivityIndicator` (the design's `Loading connections…` copy was not implemented on iOS). The branch is executed, so coverage says nothing; no test asserts the state | **unasserted** |
| **M-03-S20 loading** | none — `mobile/src/features/agents/AgentRunSection.tsx:124` renders `Checking for a newer report…`; every test passes `loading: false` | **unasserted** |
| M-01-S05 connection-test error banner | `mobile/src/app/agents/index.tsx:67` (`test.isError`) is the one uncovered branch in that file per `mobile/coverage/lcov.info`; the *list* error banner beside it is asserted by `mobile/src/app/__tests__/agents.test.tsx::reports a server rejection as an error the user can retry, not as stale data` | **weak** — the state has a test for its sibling path, not for itself |

The three unasserted loading states are one shared treatment (`design.md` §State
inventory: "Every loading row below … shows its skeleton only after about
250 ms … carries no correlation ID, because nothing has failed"), and three of
its six instances *are* asserted. No FR, SC or AC depends on them. An auditor
cannot waive its own finding, so they are recorded here for a human decision
rather than silently absorbed.

## Spot-checked for hollowness

Eight load-bearing tests were read in full — the five the audit brief named plus
three chosen because they make the strongest negative claims.

| test | would it still pass with the feature deleted? |
|---|---|
| `test_agent_a2a_reference_helloworld.py::TestHelloWorldConformance::test_014_SC_002_three_replays_create_one_task_at_the_unmodified_sample` | no — it starts the vendored sample as its own process and asks **the agent**, over its JSON-RPC endpoint, how many tasks the conversation holds. A duplicate at the agent fails it, and a BrainBuddy-side fake could not satisfy it |
| `test_agent_relay_api.py::TestPushCallbackRoute::test_push_rejections_are_indistinguishable_to_the_caller` | no — it compares four real HTTP responses against **each other**, not against a literal, so any distinguishing status, body key or header fails it. Paired with `test_014_SC_003_an_unknown_run_leaves_no_row_and_no_limiter_key`, which drives 50 probes and asserts `key_count == 0` |
| `test_agent_repository_migration.py::TestTheBespokeWireIsGone::*` | no — `/api/agent-events` must 404 through the real app and `app.modules.agents.connector` must raise `ModuleNotFoundError`. Restoring either half fails it. The auditor's own grep agrees |
| `test_agent_relay_service.py::TestDisconnectAndBoundedEvidence` (retention set) | no — the clock is advanced 31 / 91 / 200 days against a real repository, the sweep runs, and rows are re-read; `test_expired_but_unswept_run_reads_with_no_agent_text` deliberately does **not** run the sweep, so a read-time projection that stopped erasing would fail |
| `test_agent_a2a_client.py::TestRequestEnvelope::test_014_FR_004_a_private_destination_is_refused_before_the_credential_moves` | no — it asserts `seen == []`, i.e. no request object was ever constructed. Paired with `test_014_FR_004_every_call_goes_through_the_pinned_egress_path`, which asserts the socket host is the pinned literal IP while the `Host` header and SNI stay the original name |
| `test_agent_observer.py::test_no_background_thread_ever_sends_content` | no, but it is the weakest of the eight: the assertion is an absence (`calls_to("SendMessage") == []`). It earns its keep by driving four real background entry points — `run_once`, `recover_interrupted_exchanges`, `drain_queued_exchanges`, `run_retention_sweep` — and the positive half (that those threads *do* observe) is asserted by the surrounding suite |
| `frontend/…/AgentRunSection.test.tsx::014-SC-004 every run state reads as itself` | not hollow, but narrower than its name: the fixture supplies `primary_state_label` and the test asserts it renders. That is exactly FR-013's claim for the client ("derive labels from the same server projection"); the state→label **derivation** is proved server-side in `test_agent_a2a_mapping.py` and the service suite. Read as a pair, honest |
| `frontend/…/AgentHandoffOverlay.test.tsx::014-FR-016 renders adversarial agent and destination text as inert plain text` | no — it asserts `destination.tagName === "P"`, no descendant `<a>`, `queryAllByRole("link")` empty and `document.querySelector("img") === null` against a `javascript:` URL and an `onerror` payload |

Verdict on hollowness: **0 hollow tests**. The two entries with caveats are
recorded so the caveat is on the record, not to imply they are fake.

## Re-graded criteria (was weak, with the caveat kept)

1. **014-SC-004** — journey carries input-required → answer → **Agent reported
   complete** with one correlation ID across the succession; working, failed,
   canceled and both compact rows are carried by the `014-SC-004` component
   blocks on web and iOS; derivation by
   `test_014_FR_009_every_task_state_projects_to_one_reported_state`. Caveat:
   the component `it.each` asserts that a fixture-supplied
   `primary_state_label` renders, which is the client's half of FR-013 — the
   server suite is what proves the label follows the agent's state.
2. **014-SC-005** — journey carries the reviewed title, the destination
   interface and the acknowledgement gate; tier, cancellation disclosure and
   supporting-item removal by the named `AgentHandoffOverlay.test.tsx` cases.
   Caveat: the iPhone-width surface is proved by Jest component render, because
   no device or simulator journey exists for the Expo app in this repository.
3. **014-SC-006** — proved by
   `test_014_SC_006_a_delayed_agent_is_sent_then_observed_complete`, a
   full-stack run against the real unmodified Hermes with a real observer, not
   a unit test. Caveat: measured at a scaled 5 s interval; the 60 s default and
   the 300 s floor are pinned by the config test.

## Waivers

An auditor cannot waive its own finding. These need a human.

| criterion | why it is not tested | approved by |
|---|---|---|
| D-01-S02 / M-01-S02 / M-03-S20 (shared loading skeleton) | Purely presentational anti-flicker treatment; three of the six instances of the same treatment are asserted, and no FR, SC or AC depends on it | — (open) |
| M-01-S05 iOS connection-test error banner | One uncovered branch (`app/agents/index.tsx:67`); the same screen's list-error banner is asserted, and the underlying error copy is covered by `mobile/src/agents/__tests__/machine.test.ts` | — (open) |
| Playwright layer verified from CI rather than locally | No Docker daemon in the audit sandbox and the artifact host is blocked by the egress proxy; CI ran the identical tree and executed all three anti-fake validators itself | — (open) |
| 014-FR-017 attended Hermes live run | Spends provider money and requires explicit human approval; the spec makes it a pre-**rollout** obligation, not a pre-acceptance one. The runbook that governs it is itself test-asserted (`test_014_FR_017_the_release_runbook_carries_the_three_steps_it_owes`), and `external_agent_relay` stays OFF until the evidence exists | — (open, pre-rollout) |

## Notes for the record

- The implementation deviations in `review.md` were read before grading. Each
  keeps its requirement satisfied rather than narrowing it: the derived push
  token still satisfies the manifest's mask-and-never-store rule
  (`push_token_fingerprint` only, asserted); the reply on the calling thread is
  still recorded as a durable `reply` exchange, so restart recovery, the
  observation suspension and the succession rules are tested against the same
  object the plan described; the helloworld sample's `-32002` refusal is
  asserted **as observed** and mapped to the same withdrawn control; and the
  token-secured Hermes' refusal to POST to a private callback is why
  `test_014_SC_006_a_delayed_agent_is_sent_then_observed_complete` asserts
  `{event.trigger} == {"schedule"}` — the schedule is the guarantee, push is the
  optimisation. That docstring was corrected during the re-check and now states
  the SSRF refusal explicitly, so prose and assertion agree.
- The `revision` correction in `c3d0cb5` is covered and honest: three tests in
  `TestReplyAcrossTheObservationSchedule` prove a quiet observation no longer
  invalidates an answer being typed, that `run_version` and `revision` move for
  different reasons, and — the half that matters — that an answer to a question
  the agent has since replaced is **still** refused with "changed elsewhere".
  Loosening the token did not loosen the guard.
- `tasks.md` T128's per-clause record was used as the map for the bundled
  FR-006, FR-010 and FR-016. Every test it names exists and asserts what the
  clause says. The one thing it promised that had not landed — `AC-011` in the
  T051 docstrings — landed during the re-check.
