# Quickstart: validating feature 014 (A2A relay wire contract)

Runnable validation scenarios for the delivered feature. Every scenario is free and
deterministic except §7, which is approval-gated. Paths are repository-relative; commands
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

## 1. The official a2a-sdk helloworld sample (SC-001, SC-002, AC-001, AC-009, AC-016)

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
(starts the sample as a subprocess on 9999; fails clearly if the port is taken).

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
2. Hand off a Task. Expected: the confirmation returns within ~5 s showing **Sent** (the
   inline probe found the WORKING task); with `STUB_REPLY_DELAY_SECONDS=90` the run shows
   *Running* with no fabricated failure; within one observation interval after the stub
   replies (≤ 60 s, ≤ 5 s with the demo interval) the run shows **Agent reported complete**
   — and immediately if the stub's push arrived (`push_registration: registered` in the run
   JSON, timeline row `trigger: push`).
3. Hand off a Task whose title contains `ask me` (first hand-off on this best-effort
   connection: tick the one-time acknowledgement). Expected: *Needs you* with the stub's
   question (D-03-S08); answer it. Expected: the answer is shown *sent but not acknowledged*
   (D-03-S09) until the reply exchange returns; because Hermes creates a successor task for
   the follow-up, the timeline shows **Agent continued the run in a new task** with both
   task ids, the reply is never refused, and then the terminal report follows.
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
(starts `run_stub.py` on a free port; `tests/test_vendor_provenance.py` proves the vendored
plugin files are byte-identical to the recorded upstream commit).

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
  tests/test_agent_a2a_client.py tests/test_agent_egress.py -k "014_SC_003 or 014_FR_004 or 014_FR_008" -v
```

Expected: every case asserts zero projection change and zero secret disclosure —
unauthenticated (401 → invalid credentials), cross-owner (404), malformed and oversized card
and task bodies, unknown run, private destination and DNS rebinding (`fake_resolver`),
stale connection, forged / replayed / wrong-token / oversize / post-terminal push, card
drift (`agent_card_changed`), superseded bespoke record (SC-010).

## 5. Barrier tests (SC-008) and observer determinism

```bash
cd backend && pytest tests/test_agent_relay_service.py -k "014_SC_008" -v
cd backend && pytest tests/test_agent_observer.py -v
```

Expected: concurrent duplicate start/reply/cancel converge on one durable winner and at most
one agent-side action (`BlockingA2AAgent` port); observer tests run with the synchronous
executor and the `Clock` fixture — no sleeps — covering schedule, coalescing, restart
recovery (`interrupted` → adopt or `delivery_unconfirmed`), version compare-and-set,
terminal locking and TaskNotFound.

## 6. Retention and purge (SC-007)

```bash
cd backend && pytest tests/test_agent_relay_service.py tests/test_agent_repository.py -k "014_SC_007" -v
```

Expected: content gone at 30 d, identifiers (`agent_task_id`, `correlation_id`,
`message_id`, `push_token_fingerprint`) and event rows gone at 90 d, audit rows gone at
90 d, `delete_all_for_owner` leaves no row for the owner and every row for another owner.

## 7. Full gates and the product E2E

```bash
make verify-all          # check-specs, validate-ci, backend, frontend, mobile, e2e
python3 scripts/check_requirement_coverage.py specs/014-a2a-relay-wire-contract
```

`make test-e2e` brings up the compose stack with the `agents` profile (services
`a2a-helloworld` in the backend's network namespace and `hermes-a2a`), enables the flag
through the operator API, and runs `frontend/tests/e2e/agent-relay.compose.spec.ts`
(stories: hand-off to helloworld, hand-off to the Hermes stub, replay creates one task,
security rejections). Expected: Allure results under epic `External agent relay` alongside
the unchanged native product matrix.

## 8. Attended live run against a real Hermes (release evidence, spends money)

Not part of CI and never run by a subagent or schedule. With explicit human approval:
configure a real Hermes gateway with the A2A platform enabled and a bearer token behind
public HTTPS, add it as a connection in a staging BrainBuddy, hand off one Task, answer one
question, cancel one run, and attach the correlation ids, run ids and redacted card summary
to the release SHA as described in `docs/external-agent-relay-release.md` ("Hermes live
evidence"). Expected: the same labels as §2, with real model output rendered inertly.
