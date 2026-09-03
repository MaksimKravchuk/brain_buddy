# Implementation Plan: A2A Relay Wire Contract

**Branch**: `014-a2a-relay-wire-contract` | **Date**: 2026-09-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/014-a2a-relay-wire-contract/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.
Amend the spec first when implementation intent changes.

## Summary

Feature 007 ships a bring-your-own-agent relay whose connector envelope no agent implements. This feature replaces that wire with the Linux Foundation A2A protocol v1.0.x and removes the bespoke envelope, while every wire-independent 007 guarantee (consent manifest, reauthentication, sealed secrets, pinned HTTPS egress, honest projection, retention, purge, rollout-OFF semantics) is kept in place. Technical approach, decided in `research.md` (Decisions A–K):

- A minimal in-house JSON-RPC 2.0 client (`backend/app/modules/agents/a2a/`) built on the existing DNS-pinned egress; `a2a-sdk` is a dev-only dependency for the reference runtime, never a runtime dependency (Decision A).
- A background `AgentObserver` (thread pool plus one scheduler thread) that holds the blocking `SendMessage` exchange for up to the reply window, observes every non-terminal run on a schedule, is woken by verified push notifications and command acknowledgements, and recovers interrupted exchanges after a restart from durable run state (Decision B).
- Correlation identifiers: the A2A `contextId` is the run id (shown as *Correlation ID*), the start `messageId` derives from the run's idempotency key, and BrainBuddy looks the run up with `ListTasks(contextId)` before any resend; agents declaring the published single-start extension are the guaranteed tier, all others best-effort with a one-time acknowledgement (Decisions C and the sign-off decisions in spec Clarifications).
- A per-run push token route replaces the bespoke inbound event route; a verified push only triggers an observation (Decision D).
- A pure state-mapping function with BrainBuddy-assigned observation versions and terminal locking (Decision E).
- Deletion of the bespoke wire in backend, web and mobile, with a ledgered migration that marks pre-existing records disconnected (Decision F).
- Two vendored, unmodified reference runtimes (a2a-sdk helloworld sample, Hermes A2A plugin driven by a stub handler) in backend integration tests and the compose Playwright stack, plus an attended live Hermes run as release evidence (Decision G).

## Technical Context

**Language/Version**: Python 3.11 (backend); TypeScript strict on React 18 / Vite (web); TypeScript strict on Expo / React Native (iOS)

**Primary Dependencies**: FastAPI 0.119, Pydantic 2.12, httpx (re-locked from 0.27.2 to 0.28.x inside the existing `>=0.25,<0.29` range because the dev-only `a2a-sdk[http-server]==1.1.2` requires `>=0.28.1`), React Query, Zustand; no protobuf or Google client libraries at runtime

**Storage**: SQLite JSON documents under `backend/data/agents.sqlite3` through `backend/app/modules/agents/repository.py`; new columns and one ledgered migration row, no new table (`data-model.md`)

**Testing**: pytest + FastAPI TestClient with `httpx.MockTransport` and loopback fake agents; Vitest + Testing Library; Jest plus the real-backend mobile integration suite; Playwright against the compose stack with two agent fixture services

**Target Platform**: Fly.io, one always-on `1 cpu / 1 GB` machine for the backend; web via the Fly frontend proxy; iOS via Expo

**Project Type**: web service + web client + mobile client (BrainBuddy modular monolith, ADR-0001)

**Performance Goals**: observation interval 60 s (SC-006: true terminal state within one interval), dispatch request returns within `dispatch_wait_seconds` (5 s) while the exchange continues in the background, exchange held up to `reply_window_seconds + 15 s` (315 s), 8 observer workers by default

**Constraints**: HTTPS-only public destinations with DNS pinning on every card fetch, task call and push registration (007 FR-004); no per-owner cap on concurrent runs (bounded by the worker pool and API rate limits); 30-day content and 90-day identifier/audit retention; no secrets, card bodies, task text or artifacts in logs

**Scale/Scope**: single-user accounts on a multi-tenant service; tens of concurrent non-terminal runs per deployment; two reference runtimes; six designed screens with 125 states

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Spec workflow**: `spec.md` is final: the 2026-09-03 clarify session and the design sign-off decisions are encoded (zero clarification markers, `checklists/requirements.md` fully checked). `design.md` exists with human sign-off recorded; its open decisions were answered by the product owner and are reflected in FR-002, FR-003, FR-014 and AC-026. Re-check after Phase 1: `research.md` §Resolved and `data-model.md` carry the same answers. PASS.
- **Consent & Safety**: the 007 manifest review, the 15-minute reauthentication triggers (now also on card drift), the sealed-secret box and the pinned egress are reused unchanged (`service.py` `_build_manifest`, `requires_dispatch_reauthentication`; `secrets.py`; `egress.py`). The best-effort tier adds an explicit one-time acknowledgement before the first content-bearing dispatch on such a connection (FR-003, AC-026). Fixtures are synthetic agents only; no real data, credentials or card bodies are committed or logged (Decision K). PASS.
- **Tests**: failing-first suites per surface are enumerated in `research.md` Decision J: backend `test_agent_a2a_card.py`, `test_agent_a2a_client.py`, `test_agent_a2a_mapping.py`, `test_agent_observer.py`, rewritten `test_agent_relay_service.py` / `test_agent_relay_api.py`, reference-runtime tests; frontend and mobile suites per screen state; Playwright stories under the `External agent relay` epic. Edge cases required by Principle II (invalid payloads, timeouts, consent denial, idempotency, retries, cancellation, partial failure) map to SC-002, SC-003, SC-006 and SC-008. Coverage floors ratchet upward only; the backend mutation gate is unaffected because `app/modules/agents` is outside both enforced and observed tiers (ADR-0016), with a follow-up calibration proposed for `a2a/mapping.py` and `a2a/card.py`. PASS.
- **Contracts**: backend schemas change first (`backend/app/schemas/agents.py`), then `frontend/src/api/agentTypes.ts` and `mobile/src/api/types.ts` (Principle III). Contract documents: `contracts/api-deltas.md` (REST deltas and removed routes), `contracts/a2a-wire.md` (outbound A2A operations), `contracts/push-callback.md` (inbound push receipt), `contracts/brainbuddy-single-start-extension.md` (the public extension, published at `docs/a2a-extensions/single-start/v1.md`). Client-facing responses never carry the retired vocabulary (`supporting_items`, `correlation_id`). The removed routes return 404 and the migration marks pre-existing records disconnected; no compatibility path for the bespoke wire is kept because it has zero consumers (FR-012). PASS.
- **Observability**: every outbound A2A call and every observation runs under a correlation id (`X-Correlation-ID`, `obs_<id>` for scheduled observations) recorded on audit rows; structured logs carry method, HTTP status class, allowlisted A2A error codes, protocol version, duration and ids only; user-visible failures carry the SC-009 categories and the correlation id (Decision K). Progress, retry, cancellation and partial-failure state surface through the single server projection (FR-013). PASS.
- **Mobile/resilience/performance**: 007 FR-018 semantics are unchanged (`mobile/src/lifecycle/agentGuards.ts`, `mobile/src/agents/machine.ts`): reopening loads the server projection, offline state is labelled stale, reply and cancel are disabled offline. No canvas impact; the relay has no effect on the ~200-node canvas. PASS.
- **Delivery boundary**: Spec Kit tasks stay portable planning input; implementation runs in an isolated worktree by the `feature-implementer`, verification by `delivery-verifier`, acceptance by `acceptance-auditor`; landing class is ASK (the plan names `backend/app/api/dependencies.py`, `backend/app/modules/agents/secrets.py`, `compose.yaml`, `scripts/run_playwright_e2e.sh` and `.github/workflows/ci.yml`), risk class `high` under ADR-0012 with a recorded human sign-off, exact-SHA dual review and ASK merge authority as for 007; rollout stays OFF until the attended Hermes live run is recorded. PASS.
- **Design citation**: this feature has user-visible surfaces. `design.md` (human sign-off: Max, 2026-09-03) assigns D-01 Connected agents (desktop), D-02 Hand-off review (desktop), D-03 Task agent panel and compact rows (desktop), M-01, M-02, M-03 (iOS, 390×851). Each implementation section below names the state ids it realizes; the acceptance auditor traces criteria through those ids. PASS.

## Project Structure

### Documentation (this feature)

```text
specs/014-a2a-relay-wire-contract/
├── intake.md            # business interview record (2026-09-03)
├── spec.md              # final specification, FR-001..FR-017, SC-001..SC-010, AC-001..AC-026
├── checklists/requirements.md
├── design.md            # screens D-01..D-03, M-01..M-03 and their state ids; human sign-off recorded
├── design/*.html        # six self-contained static screens
├── plan.md              # this file
├── research.md          # Phase 0: facts F1..F12 and Decisions A..K
├── data-model.md        # Phase 1: documents, state machines, retention tiers, configuration
├── contracts/
│   ├── a2a-wire.md                          # outbound A2A operations BrainBuddy uses
│   ├── brainbuddy-single-start-extension.md # the public extension draft
│   ├── api-deltas.md                        # BrainBuddy REST changes and removed routes
│   └── push-callback.md                     # what BrainBuddy registers and accepts
├── quickstart.md        # runnable validation scenarios
└── tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── api/agents.py                       # routes: connections, test, preview, dispatch, runs, reply, cancel; NEW POST /a2a/push/{run_id}/{token}; REMOVED signing-secret and /agent-events routes
│   ├── api/dependencies.py                 # get_agent_relay_service / require_external_agent_relay_enabled (unchanged semantics; observer wiring)
│   ├── schemas/agents.py                   # request/response deltas per contracts/api-deltas.md
│   ├── core/config.py                      # AgentRelaySettings: observation_interval_seconds, reply_window_seconds, dispatch_wait_seconds, observer_workers, AGENT_PUSH_PATH; AGENT_EVENTS_PATH removed
│   ├── main.py                             # start/stop AgentObserver next to the maintenance thread
│   ├── container.py                        # wire A2AClient, AgentObserver, AgentRelayService
│   └── modules/agents/
│       ├── a2a/__init__.py                 # NEW package
│       ├── a2a/types.py                    # strict Pydantic models for the A2A subset (card, task, message, parts, errors)
│       ├── a2a/card.py                     # card fetch/parse/fingerprint, scheme selection, tier detection
│       ├── a2a/client.py                   # JSON-RPC client over egress.pinned_request: SendMessage, GetTask, ListTasks, CancelTask, push config
│       ├── a2a/mapping.py                  # project_observation(): A2A task/message -> BrainBuddy projection
│       ├── observer.py                     # NEW AgentObserver: exchange pool, scheduler, wake queue, restart recovery
│       ├── domain.py                       # connection/run/event/command deltas; event envelope models removed
│       ├── repository.py                   # new columns, migration a2a_wire_contract_v1, identifier expiry, observation queries
│       ├── service.py                      # discovery/test, tier, drift, dispatch with exchange, reply/cancel via A2A, push verification; bespoke ingest path removed
│       ├── egress.py                       # unchanged pinning; reused by a2a/client.py
│       ├── headers.py                      # rewritten reserved list (A2A-Version, A2A-Extensions, X-Correlation-ID)
│       ├── secrets.py                      # inbound-signing purposes removed; push token fingerprint helper
│       └── connector.py                    # DELETED (bespoke envelope)
├── vendor/
│   ├── a2a_helloworld/                     # unmodified official sample + LICENSE + PROVENANCE.md
│   └── hermes_a2a/                         # unmodified plugins/platforms/a2a + LICENSE + PROVENANCE.md, gateway/ stub, run_stub.py
├── tests/
│   ├── test_agent_a2a_card.py, test_agent_a2a_client.py, test_agent_a2a_mapping.py, test_agent_observer.py   # NEW
│   ├── test_agent_relay_service.py, test_agent_relay_api.py, test_agent_schemas.py, test_agent_repository.py  # rewritten
│   ├── test_agent_a2a_reference_helloworld.py, test_agent_a2a_reference_hermes.py                             # NEW reference runtimes
│   ├── a2a_fakes.py                        # loopback fake agents incl. the extension-declaring one
│   └── allure_taxonomy.py                  # new module stems
└── pyproject.toml, uv.lock                 # dev extra a2a-sdk[http-server]==1.1.2; httpx re-lock

frontend/
├── src/api/agentTypes.ts, agentHooks.ts, client.ts          # contract deltas, removed signing-secret calls
├── src/features/agents/AgentSettingsPage.tsx                # D-01 states S08..S24 (auth scheme, discovery, tier, drift, disconnect reason)
├── src/features/agents/AgentHandoffOverlay.tsx              # D-02 states S01..S15 (acknowledgement S13..S15)
├── src/features/agents/AgentRunSection.tsx, agentCopy.ts    # D-03 states S03..S26; compact rows
├── src/features/tasks/TaskDetailPanel.tsx, TaskListPage.tsx # compact summary fields
└── tests/e2e/agent-relay.compose.spec.ts                    # NEW Playwright stories

mobile/
├── src/api/types.ts, client.ts, hooks.ts                    # contract deltas
├── src/agents/machine.ts, src/lifecycle/agentGuards.ts      # new conditions, withdrawn controls
├── src/features/agents/AddConnectionSheet.tsx, ConnectionCard.tsx   # M-01 states S08..S21
├── src/features/agents/HandoffSheet.tsx                     # M-02 states S01..S14 (acknowledgement S12..S14)
├── src/features/agents/TaskAgentSection.tsx, DisconnectSheet.tsx    # M-03 states S02..S25
├── src/features/agents/SigningSecretSheet.tsx, ReplaceSigningSecretSheet.tsx  # DELETED
└── integration/                                             # connection-test contract against the disposable backend

scripts/fixtures/a2a-helloworld/Dockerfile, scripts/fixtures/hermes-a2a/Dockerfile   # compose fixture images
compose.yaml, scripts/run_playwright_e2e.sh, .github/workflows/ci.yml              # `agents` profile, fixture builds
docs/a2a-extensions/single-start/v1.md                                             # the published extension
docs/external-agent-relay-release.md, docs/e2e-acceptance-charter.md, .env.example # release evidence, E2E matrix, variables
```

**Structure Decision**: the relay stays one module under `backend/app/modules/agents/` (ADR-0001 ownership unchanged); the A2A protocol surface is isolated in the new `a2a/` sub-package so the service keeps orchestrating through a port (`A2AClientPort`) the same way it used `ConnectorPort`; the observer is a sibling module because it owns threads and scheduling, not business rules. Vendored third-party runtimes live under `backend/vendor/` so ruff, black, mypy and coverage never touch them, and their provenance is asserted by a test. Web and iOS keep the existing feature folders; only the signing-secret surfaces disappear.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Vendored third-party code under `backend/vendor/` (helloworld sample, Hermes A2A plugin, MIT/Apache-2.0) | FR-017 and SC-001 require the *unmodified* reference runtimes to be exercised in CI without network access or a model | pip-installing `hermes-agent` pulls the full runtime and is not packaged; cloning at CI time breaks the offline `make test-backend`; a Docker image of real Hermes needs a model provider |
| A thread-pool observer with a scheduler thread inside the API process | Hermes creates the agent task only inside a blocked `SendMessage` (up to 300 s) and every run needs periodic authenticated observation; services are synchronous and ADR-0002 forbids correctness that depends on untracked async tasks | per-run threads are unbounded on a 1-CPU machine; an asyncio task inside uvicorn cannot drive the synchronous services; polling alone never creates the Hermes task |
| A dev-only third-party dependency (`a2a-sdk[http-server]`) and an httpx re-lock | the official sample agent is the second reference runtime and runs in the test interpreter | vendoring the SDK itself duplicates 117 modules; skipping the sample leaves only one reference runtime, below the definition of done |

## Implementation sections (design citations)

Each section names the spec requirements it realizes and the `design.md` state ids the acceptance auditor traces.

1. **Discovery, test and tier** (FR-001, FR-002, FR-003, FR-004; D-01-S08..S24, M-01-S08..S21). `a2a/card.py` fetches `{origin}/.well-known/agent-card.json` through `pinned_request`, parses both the v1.0 card and the legacy Hermes shape, selects the first JSON-RPC interface with protocol version 1.0.x, validates its host separately under 007 FR-004, maps offered security schemes to `bearer`/`api_key`/unsupported, detects the extension URI for the tier, and computes the drift fingerprint. `service.test_connection` returns the six categories (ready, invalid credentials, unreachable, unsupported ×4, private destination) by an authenticated `ListTasks(pageSize=1)`; the disclosure copy and the `tier_disclosure_url` come from the projection; `agent_card_changed` puts the connection back to untested (D-01-S20 / M-01-S18) and resets `scope_verified_at`.
2. **Hand-off review and dispatch** (FR-005, FR-006, FR-007; D-02-S01..S15 including the acknowledgement states D-02-S13..S15 and the extension link on D-02-S02, M-02-S01..S14 including M-02-S12..S14). The manifest keeps the 007 token discipline and adds `message_id`, `correlation_id`, the tier and cancellation disclosures and `acknowledgement_required`; a best-effort connection's first confirmation must carry `acknowledge_duplicate_risk: true` (AC-026). `dispatch_run` reserves ids, opens the exchange, submits `SendMessage` (context id = run id, message id = `{run_id}:start`, metadata with Task and run ids, inline push config when the card supports push), waits `dispatch_wait_seconds`, probes `ListTasks(contextId)` when still open, and returns the honest dispatch state. Replays never resend without the context lookup; guaranteed-tier resends carry the extension header and message extension.
3. **Observation and run surfaces** (FR-008, FR-009, FR-010, FR-013, FR-014, FR-015; D-03-S03..S26, M-03-S02..S25). `observer.py` schedules `GetTask` per non-terminal run every `observation_interval_seconds`, coalesces in-flight runs, applies `mapping.project_observation` under the owner command lock with compare-and-set on `run_version`, appends timeline events only on change, locks terminal states, sets `agent_task_missing_at` on `TaskNotFound`, and recovers interrupted exchanges at startup. Reply sends a follow-up message with the command id as message id and adopts a succeeding task when Hermes returns a new one (timeline `task_succeeded`); cancel maps `TaskNotCancelable`/`UnsupportedOperation` to `cancel_outcome` without inventing a state. The single projection feeds web and iOS labels verbatim.
4. **Push receipt** (FR-008, FR-016; D-03-S24, M-03-S23 for the timeline "push verified" marker). `POST /api/a2a/push/{run_id}/{token}`: fingerprint verification against a dispatched, non-terminal, non-disconnected run; verified → enqueue an immediate observation, `204`; unverified → opaque `403`/`413` with bounded audit only for a known run; body never parsed for state; per-run rate limit.
5. **Removal and migration** (FR-012, SC-010; D-01-S21, M-01-S19). Delete the bespoke connector, event envelope models, signing-secret rotation, the `/agent-events` route and the web/mobile secret sheets; ledgered migration `a2a_wire_contract_v1` marks pre-existing records disconnected with reason `superseded_wire_contract` and stamps their runs; `.gitleaks.toml` allowlist entries for synthetic signing secrets are removed.
6. **Reference runtimes and tests** (FR-017, SC-001..SC-010). Vendored helloworld and Hermes plugin with provenance checks; `run_stub.py` drives the unmodified Hermes adapter with a scripted reply handler; loopback fake agents for the guaranteed tier and the empty-`ListTasks` resend path; compose fixture services behind the `agents` profile; Playwright stories `A2A hand-off to the helloworld sample`, `A2A hand-off to the Hermes stub`, `A2A replay creates one task`, `A2A security rejections`; the attended Hermes live run documented as approval-gated release evidence, never run in CI or by a subagent.
7. **Rollout, flag and operations** (FR-016, FR-019 of 007). `external_agent_relay` keeps its two axes; while OFF, observation of dispatched runs and verified push handling continue; new settings and the removed callback variable are documented in `.env.example`; `docs/external-agent-relay-release.md` step 5 is rewritten for the A2A smoke and the live evidence section.

## Risks and rollback

- **Duplicate tasks on best-effort agents** are disclosed and acknowledged, never hidden; the resend path is exercised against a fake agent that answers `ListTasks` empty (SC-002).
- **Restart during an exchange**: the run row records `exchange_state=open`; recovery marks it interrupted and the next observation adopts or resends by context lookup; nothing is lost because reservation and dispatch state are durable before I/O.
- **Third-party churn**: the client accepts protocol versions `1.0.x` only and tolerates unknown card fields; Hermes' legacy card shape is covered by a fixture pinned to a commit.
- **Rollback**: redeploy the previous image with the flag OFF; the migration is one-way (bespoke records stay disconnected), which is acceptable because no production records exist and the bespoke wire has no consumers; encryption keys for stored credentials must be kept as in 007.
- **Landing**: ASK class, risk `high`; the review campaign records the human sign-off; dual review on the exact SHA; `make verify-all` green; rollout stays OFF until the live Hermes evidence is attached.
