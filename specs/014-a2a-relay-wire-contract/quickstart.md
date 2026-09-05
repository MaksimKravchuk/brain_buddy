# Quickstart: validating feature 014 (A2A relay wire contract)

Runnable validation scenarios for the delivered feature. Every scenario is free and
deterministic except §8, which is approval-gated. Backend tests carry `014_FR_###` /
`014_SC_###` in their names and the AC ids they prove in their docstrings, as the 007 tests
do (`test_agent_relay_service.py` 303–306), because the coverage gate checks only FR/SC ids. Paths are repository-relative; commands
assume the toolchain from `.claude/skills/self-verify/SKILL.md`.

## 0. Prerequisites

```bash
make install-backend                      # installs .[dev], which now includes a2a-sdk[http-server]==1.1.2
make install-frontend && make install-mobile
cd frontend && npx playwright install --with-deps chromium && cd ..
```

Environment for local manual runs (never production):

```bash
export BRAIN_BUDDY_ENV=development
export BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS=1     # loopback agents are private-class
export BRAIN_BUDDY_PUBLIC_BASE_URL=http://localhost:8000  # push callback origin
export BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS=5   # shorter than the 60 s default for demos
```

Rollout: `external_agent_relay` is SQLite-managed; turn it ON for your account through the
Admin Portal (`/admin` → Feature flags) or `PUT /api/admin/feature-flags/external_agent_relay`
with an operator session (`docs/external-agent-relay-release.md`).

## 1. The official a2a-sdk helloworld sample (SC-001, SC-002, AC-001, AC-009, AC-016, AC-026)

Terminal A — the unmodified sample, vendored at `backend/vendor/a2a_helloworld/`:

```bash
cd backend/vendor/a2a_helloworld && HOME=$(mktemp -d) python __main__.py   # listens on 127.0.0.1:9999
curl -s http://127.0.0.1:9999/.well-known/agent-card.json | python -m json.tool | head -20
```

Expected: card `name: "Hello World Agent"`, `supportedInterfaces[0].protocolVersion: "1.0"`,
`capabilities.streaming: true`, no `pushNotifications`.

Terminal B — BrainBuddy (`make dev-backend`, `make dev-frontend`), then in the web UI:

1. Settings → Connected agents → Add agent: address `http://127.0.0.1:9999`, scheme
   *Bearer token*, any credential, your password → Save → **Test**.
   Expected (D-01-S11): status *Tested ready*, discovery result with the sample's name,
   version `0.0.1`, skill *Echo Bot*, streaming *yes*, push *no*, tier **Best-effort single
   start** with the duplicate-risk sentence and a link to the published extension
   specification (opens in a new tab only when clicked).
2. Open any Task → Hand to agent → review (D-02-S02): title, details toggle, supporting
   items, Task ID, run ID, correlation ID, destination `http://127.0.0.1:9999`, tier and
   cancellation disclosures, external-copy notice. Expected (AC-026): **Send** stays
   disabled until you tick the one-time acknowledgement that a duplicate task is possible;
   a confirm request without `acknowledge_duplicate_risk: true` (replay it from devtools)
   is refused with `duplicate_risk_acknowledgement_required`. Tick it → Send.
   Expected (D-03): timeline shows **Sent** then **Agent reported complete** within the
   same request (the sample completes inside `SendMessage`); result text
   `Hello, World! I have received your request (...)`; the Task stays open. A second
   hand-off on the same connection shows the disclosure only, with no acknowledgement.
3. Replay: repeat the confirmation request three times with the same `Idempotency-Key`
   (browser devtools "replay XHR", or `curl` with the captured body and headers).
   Expected: identical `AgentRunResponse`; `curl -s -X POST http://127.0.0.1:9999/ -H
   'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"ListTasks",
   "params":{"contextId":"<run id>"}}'` lists exactly one task.
4. Request cancellation on the completed run: control is withdrawn (terminal).

Automated equivalent: `cd backend && pytest tests/test_agent_a2a_reference_helloworld.py -v`
(a pre-bind availability check on `127.0.0.1:9999` fails — never skips — with a clear message
naming the occupant when the port is taken; the sample is started as a subprocess with a
30 s startup wait on the card URL and guaranteed teardown through `request.addfinalizer`, kill
+ wait, even on assertion failure or timeout; the sample's cancel answer is asserted as
`-32004`, with the fallback documented in `contracts/a2a-wire.md`). The AC-026 acknowledgement gate is automated in
`tests/test_agent_relay_service.py` (`test_first_best_effort_confirm_without_acknowledgement_is_refused`,
`test_acknowledgement_flag_is_ignored_once_persisted`,
`test_best_effort_acknowledged_at_is_persisted_and_reset_with_scope`).

## 2. The unmodified Hermes A2A plugin with a stub handler (SC-001, SC-006, AC-014, AC-015, AC-018, AC-021)

Terminal A — vendored plugin + stub gateway, no model:

```bash
cd backend/vendor/hermes_a2a && \
HOME=$(mktemp -d) A2A_PORT=9900 A2A_BEARER_TOKEN=devtoken A2A_HOST=127.0.0.1 \
A2A_PUSH_SECRET=unused STUB_REPLY_DELAY_SECONDS=90 python run_stub.py
curl -s http://127.0.0.1:9900/.well-known/agent-card.json | python -m json.tool | head -30
```

Expected: card with `securitySchemes.bearer`, `capabilities.pushNotifications: true`,
`streaming: true`, `protocolVersion "1.0"`. The stub echoes after `STUB_REPLY_DELAY_SECONDS`,
answers `[INPUT_REQUIRED] …` when the text contains `ask me`, and never needs a model.

Terminal B — in BrainBuddy:

1. Add agent `http://127.0.0.1:9900`, *Bearer token* `devtoken` → Test.
   Expected: *Tested ready*, **Best-effort single start**, push *yes*.
   Negative: rotate the credential to `wrong` → Test → *Invalid credentials* (D-01-S12) and
   the secret is never displayed.
2. Hand off a Task. Expected (AC-007): because this card declares push support, the review
   lists the callback disclosure — BrainBuddy registers a private callback address with a
   per-run token, held by the agent until the run ends — with the token masked in
   `push_callback.url_preview`. Confirm. Expected: the confirmation returns within ~5 s
   showing **Sent** (the inline probe found the WORKING task; a hand-off that has to wait for
   a free exchange worker shows **Queued** — "Waiting for a free connection slot; nothing has
   been sent yet" — until the exchange starts); with `STUB_REPLY_DELAY_SECONDS=90` the run shows
   *Running* with no fabricated failure; within one observation interval after the stub
   replies (≤ 60 s, ≤ 5 s with the demo interval) the run shows **Agent reported complete**
   — and immediately if the stub's push arrived (`push_registration: registered` in the run
   JSON, timeline row `trigger: push`).
3. Hand off a Task whose title contains `ask me` (first hand-off on this best-effort
   connection: tick the one-time acknowledgement). Expected: *Needs you* with the stub's
   question (D-03-S08); answer it. Expected (AC-028, D-03-S27): the answer is shown *sent but
   not acknowledged* (D-03-S09) until the reply exchange returns; because Hermes creates a
   successor task for the follow-up, the timeline shows **The agent continued this run in a
   new task** with both task ids, the run keeps its one correlation ID, the reply is never
   refused, and then the terminal report follows. Answer only after Hermes' 300 s watchdog
   has failed the waiting task and the timeline first shows *The previous task ended: failed*
   — the run is **not** marked failed while your answer is pending — followed by the
   succession row.
4. Hand off, then Request cancellation while the stub is delaying. Expected:
   **Cancellation requested** then **Cancelled** (Hermes resolves the blocked exchange with
   `TASK_STATE_CANCELED`).
5. Restart the Hermes stub while a run is *Running*. Expected on the next observation:
   **Agent no longer reports this run** (D-03-S18), last contact preserved, reply/cancel
   withdrawn, no *Failed* claim.
6. Restart the stub **without** `A2A_BEARER_TOKEN` (its card drops the security scheme)
   and open a hand-off review. Expected (D-02-S09, D-01-S20): the review refuses with
   `agent_card_changed`, the connection shows **Agent changed** with the tested and current
   interface side by side, and a new successful test plus your password are required before
   the next hand-off.

Automated equivalent: `cd backend && pytest tests/test_agent_a2a_reference_hermes.py -v`
(starts `run_stub.py` bound to port 0 and reads the bound port back, so it never collides;
`tests/test_vendor_provenance.py` proves the vendored plugin files are byte-identical to the
recorded upstream commit, and `tests/test_agent_a2a_extension_identifier.py` proves the
FR-011 identifier path exists and is what the API serves as `tier_disclosure_url`).

## 3. Replay and the guaranteed tier (SC-002)

```bash
cd backend && pytest tests/test_agent_relay_service.py -k "014_SC_002" -v
```

Expected: three cases pass — helloworld replays (one task), Hermes-stub replays (one task),
and the fake extension-declaring agent from `tests/a2a_fakes.py` whose `ListTasks` is empty,
where BrainBuddy resends the identical message and the agent dedups it (one task, tier shown
as **Guaranteed single start**). The card-level conformance steps are in
`contracts/brainbuddy-single-start-extension.md` §6 and can be replayed with `curl`.

## 4. The security suite on the new wire (SC-003)

```bash
cd backend && pytest tests/test_agent_relay_service.py tests/test_agent_relay_api.py \
  tests/test_agent_a2a_client.py tests/test_agent_egress.py -k "014_SC_003 or 014_SC_009 or 014_FR_004 or 014_FR_008" -v
```

Expected: every case asserts zero projection change and zero secret disclosure —
unauthenticated (401 → invalid credentials), cross-owner (404), malformed and oversized card
and task bodies, unknown run, private destination and DNS rebinding (`fake_resolver`),
stale connection, forged / replayed / wrong-token / oversize / post-terminal push, card
drift (`agent_card_changed`), superseded bespoke record (SC-010, §9). The SC-009 log-scan
case `test_push_token_never_appears_in_logs` captures application and `uvicorn.access`
logging during a verified, a rejected and a failing (exception-path) push and asserts the
issued token string appears in none of them — those two in-process edges are the ones the
scan covers, since the callback lands on the backend app's own origin and the Fly edge is the
disclosed residual; `test_valid_push_after_terminal_is_classified_push_after_close` proves a
late valid push is recorded as a late push, never as a forged token, and
`test_push_rejections_are_indistinguishable_to_the_caller` proves the unknown-run,
wrong-token and closed-run rejections carry the same status, body and headers;
`test_unknown_run_flood_leaves_limiter_memory_bounded_and_no_rows`
and `test_global_push_limiter_trips_before_the_run_lookup` prove the push route's limiter
order; `test_agent_a2a_client.py` proves an oversized or adversarial inbound
`X-Correlation-ID` never reaches an outbound request, and
`test_drip_feeding_agent_trips_the_absolute_deadline` proves a one-byte-per-interval agent is
cut off at the deadline (`EgressDeadlineExceeded`) instead of holding a worker. Card text
(AC-031): `test_card_text_is_returned_verbatim_and_bounded` on the API side, and the
frontend / mobile AC-031 cases (`AgentSettingsPage.test.tsx`, `ConnectionCard.test.tsx`)
render a card whose description carries markup and whose interface address is `javascript:…`
or a metadata address as plain text with no anchor and no `Linking` target.

## 5. Barrier tests (SC-008) and observer determinism

```bash
cd backend && pytest tests/test_agent_relay_service.py -k "014_SC_008" -v
cd backend && pytest tests/test_agent_observer.py -v
```

Expected: concurrent duplicate start/reply/cancel converge on one durable winner and at most
one agent-side action (`BlockingA2AAgent` port; the start barrier follows
`test_concurrent_same_key_dispatches_contend_and_converge_only_with_lock`, the reply/cancel
barrier `test_concurrent_same_key_commands_contend_and_converge_only_with_lock`), and so do
concurrent delivery checks — `test_concurrent_check_delivery_requests_converge_on_one_resend`,
`test_check_delivery_racing_a_replayed_confirmation_resends_once`,
`test_check_delivery_racing_restart_recovery_resends_once` (one `open` winner, at most one
resend); observer tests run with the synchronous exchange, observation and control executors
and the `Clock` fixture — no sleeps — covering schedule, coalescing per run and per
unreachable connection, backoff after the reporting window and its reset, restart recovery in
both branches (`test_restart_recovery_settles_a_queued_exchange_as_not_sent_restarted_before_send`:
a never-started exchange becomes **Not sent**, never **Delivery unconfirmed**, and the hand-off
is re-offered; `test_restart_recovery_resolves_an_open_exchange_by_lookup_only`: adopt or stay
`delivery_unconfirmed` with zero `SendMessage`; `test_restart_during_open_reply_exchange_recovers_by_succession_evidence`),
the bounded reply suspension (`test_ambiguous_reply_exchange_resumes_observation_at_the_deadline`:
an ambiguous reply exchange followed by N scheduler passes observes the run again at the
deadline, keeps the reply unconfirmed in the timeline and restores the reply control only after
a blocked observation), the absolute deadline (`test_drip_feeding_agent_releases_the_worker_at_the_deadline`),
the control pool (`test_cancel_reaches_the_agent_while_all_exchange_workers_are_held` — eight
held exchanges, the cancel still lands within its short timeout —,
`test_owner_cancels_a_run_whose_own_exchange_holds_a_worker`), the per-connection bound
(`test_one_connection_holds_at_most_max_exchanges_per_connection`), the no-background-send
rule (`test_no_background_thread_ever_sends_content`), version compare-and-set, terminal
locking, TaskNotFound, the content-expiry rule
(`test_observation_after_content_expiry_writes_no_agent_text`), the succession interleaving
(`test_predecessor_failure_during_open_reply_exchange_does_not_lock_the_run`), purge during an
observation (`test_purge_during_observation_writes_no_row`) and the two-owner starvation case
(`test_one_owners_saturated_exchanges_never_delay_another_owners_observation`).
`tests/test_agent_relay_service.py -k "014_FR_004 or 014_FR_006 or 014_FR_008 or 014_FR_010"`
adds purge and disconnect during an open exchange (zero owner rows, no overwrite), the
queued-exchange projection, `context_id_honoured=false` never resending — not even on
**Check again** —, the resend preconditions (`test_check_delivery_refuses_resend_when_connection_not_ready`,
`…_when_agent_card_changed`, `…_when_scope_reset_since_dispatch`, `…_when_run_content_expired`,
each with zero outbound `SendMessage`), `test_check_delivery_resend_requires_dispatch_reauthentication`
beside `test_check_delivery_lookup_needs_no_reauthentication`, and
`test_cancel_transient_error_then_success_reuses_the_command_id`;
`tests/test_agent_relay_api.py -k "014_FR_016"` adds the rollout-OFF matrix with
`test_rollout_off_check_delivery_looks_up_but_never_resends` (AC-036).

## 6. Retention and purge (SC-007)

```bash
cd backend && pytest tests/test_agent_relay_service.py tests/test_agent_repository.py -k "014_SC_007" -v
```

Expected: content gone at 30 d — the six 007 fields plus `blocked_reason`,
`artifacts_summary`, `result_availability` and the status text, re-erased on the next pass if
anything wrote them after expiry — and an observation accepted after content expiry leaves
every content field null; a run whose content is due but not yet swept already reads with no
agent text on every read path, the sweep deliberately not run
(`test_expired_but_unswept_run_reads_with_no_agent_text`, `project_run_for_access`); one
unparseable run row is skipped and logged with a correlation id and no content while every
other owner's content still expires (`test_expire_due_content_skips_and_logs_an_unparseable_row`);
identifiers (`agent_task_id`, `message_id`, `push_token_fingerprint`) and event rows gone at
90 d, while the run id — which is the run's correlation ID and part of the push callback path
— stays with the run row as coarse metadata until purge and the test asserts exactly that
(`test_run_id_is_retained_with_the_run_row_until_purge_and_identifiers_expire_at_90_days`);
audit rows gone at 90 d, `observation_accepted` audit rows bounded per run/state class/UTC
day, `delete_all_for_owner` leaves no row for the owner and every row for another owner. The live connection's card summary and `card_fingerprint`
survive every sweep while the connection is live and are erased by `disconnect_connection`
together with the credential (product owner, 2026-09-04; FR-016, AC-024, SC-007).

## 7. Full gates and the product E2E

```bash
make verify-all          # check-specs, validate-ci, backend, frontend, mobile, e2e
python3 scripts/check_requirement_coverage.py specs/014-a2a-relay-wire-contract
```

`make test-e2e` brings up the compose stack with the `agents` profile (services
`a2a-helloworld` in the backend's network namespace and `hermes-a2a`), enables the flag
through the operator API, and runs `frontend/tests/e2e/agent-relay.compose.spec.ts`
(stories: hand-off to helloworld, hand-off to the Hermes stub, replay creates one task,
security rejections). Expected: Allure results under epic `External agent relay`, recorded in
the charter's new per-epic section **External agent relay product matrix**
(`docs/e2e-acceptance-charter.md`) alongside the unchanged native product matrix table.

SC-004 and SC-005 are discharged by named suites inside those gates (research Decision J):

```bash
cd frontend && npx vitest run src/features/agents -t "014-SC-004"   # AgentRunSection / agentCopy: every primary_state_label, compact rows, the Queued, restarted-before-send and too-large variants
cd frontend && npx vitest run src/features/agents -t "014-SC-005"   # AgentHandoffOverlay: every manifest value, both disclosures, each supporting item removable
cd mobile && npx jest src/features/agents src/agents -t "014-SC-004"   # TaskAgentSection + machine: label for label from the same projection
cd mobile && npx jest src/features/agents -t "014-SC-005"              # HandoffSheet: header, scrolling body, pinned Send/Cancel footer, named Remove controls
```

The Playwright stories `A2A hand-off to the Hermes stub` (SC-004 end to end: working,
input-required, completed, failed and canceled through the product surfaces) and `A2A hand-off
to the helloworld sample` (the desktop-width review, SC-005) close the loop. The 390×851
geometry of the review sheet itself — no horizontal scroll, the actions footer never scrolled
off — is verified at design-authoring time (`design.md`, Mobile viability) and re-checked
manually before any release that touches `mobile/src/features/agents/HandoffSheet.tsx` layout;
the RNTL suite asserts the structure, not the pixels.

## 8. Attended live run against a real Hermes (release evidence, spends money)

Not part of CI and never run by a subagent or schedule. With explicit human approval:
configure a real Hermes gateway with the A2A platform enabled and a bearer token behind
public HTTPS, add it as a connection in a staging BrainBuddy, hand off one Task, answer one
question, cancel one run, and attach the evidence to the release SHA as described in
`docs/external-agent-relay-release.md` ("Hermes live evidence"). The evidence is that
section's closed field list — agent name, version, protocol version, declared capabilities,
guarantee tier, correlation ids, run id and the resulting `primary_state_label` sequence — and
never the agent address or interface address, the credential, the push token or its
fingerprint, the card description or skill text, the handed-off Task title, details or
supporting items, artifacts or the agent's model output. Expected: the same labels as §2,
with real model output rendered inertly on the screen and kept out of the evidence. Rollout
stays OFF for every user until, in addition, the refreshed iOS build is the only distributed
build (the runbook's rollout gate).

## 9. SC-010 — bespoke wire removal and migration

```bash
cd backend && pytest tests/test_agent_repository_migration.py -v
grep -rn "agent-events\|inbound_signing_secret\|AGENT_EVENT_ENVELOPE_ADAPTER\|modules.agents.connector" \
  backend/app frontend/src mobile/src; test $? -eq 1
```

Expected: a seeded pre-014 bespoke connection row (no `wire` key) is rewritten by the
ledgered migration `a2a_wire_contract_v1` to `status: "disconnected"`,
`disconnect_reason: "superseded_wire_contract"`, `credential: null`; the rewrite is counted
and audited (one `wire_superseded` audit row per rewritten connection, the count on the
ledger row), a second startup rewrites nothing, and a wire-less row inserted between two
startups is rewritten on the next one (`test_wire_less_rows_are_rewritten_on_every_startup`);
its runs keep their bounded history and are stamped `connection_disconnected_at`; a hand-off
preview on it is refused with `superseded_wire_contract`; `POST /api/agent-events` and
`POST /api/agent-connections/{id}/signing-secret` answer 404; importing
`app.modules.agents.connector` raises `ModuleNotFoundError` (the import-absence assertion);
the grep finds no bespoke symbol in product code. In the UI the record shows D-01-S21 /
M-01-S19 (**Superseded wire contract**). Before the production deploy the runbook's
pre-deploy step counts bespoke rows in production (connection payloads without a `wire`
key) so the "no production records" assumption is evidence. The rollback boundary is proved
alongside: `tests/test_agent_relay_service.py -k "frozen_007"` validates a 014 connection
row **and** 014 run, event and command rows — the run's manifest carrying the inert
`reporting` / `reporting_instructions` keys — against frozen copies of the 007 documents, so
the 007 image's reads, export and `expire_due_content` keep working on 014 rows after a
rollback.
