# Contract: BrainBuddy REST deltas (feature 014)

Base: `backend/app/api/agents.py` and `backend/app/schemas/agents.py` as ratified by 007.
Session cookie, owner scoping, `Idempotency-Key`, `X-Correlation-ID`, the
`external_agent_relay` gate on *new-work* routes, and 404-for-wrong-owner are unchanged.
Both clients (`frontend/src/api/agentTypes.ts`, `mobile/src/api/types.ts`) mirror these
shapes one-to-one. Vocabulary per `design.md`: client-facing names use `supporting_items`
and `correlation_id` (see research NEEDS CLARIFICATION 1).

## Removed endpoints (FR-012)

| route | replacement |
|---|---|
| `POST /agent-connections/{id}/signing-secret` | none — no inbound secret exists |
| `POST /agent-events` | `POST /a2a/push/{run_id}/{token}` (see `push-callback.md`) |

Removed schemas: `AgentConnectionSecretResponse`, `AgentConnectionSigningSecretResponse`,
`AgentConnectionRotateSigningSecretRequest`, `AgentReportingContractResponse`,
`AgentEventIngestResponse`; `AgentConnectionCreatedResponse` no longer carries
`inbound_signing_secret` (create now returns a plain `AgentConnectionResponse`, 201).

## Connections

`POST /agent-connections` (gate, reauth, Idempotency-Key) — request:

```json
{ "name": "My Hermes", "agent_address": "https://agent.example.com",
  "auth_scheme": "bearer" | "api_key", "credential": "<secret>", "current_password": "…" }
```

`auth_header_name` is no longer accepted. `PUT /agent-connections/{id}` accepts `name`,
`agent_address`, `auth_scheme`, `expected_revision`, `current_password` (required when
`agent_address` or `auth_scheme` changes). `POST …/credential`, `POST …/test`,
`POST …/disconnect`, `GET /agent-connections[/{id}]` unchanged in shape of the request.

`AgentConnectionResponse` (every connection read):

```json
{ "id": "…", "name": "…", "agent_address": "https://…", "auth_scheme": "bearer",
  "auth_header_name": "Authorization" | "X-API-Key" | null,
  "status": "untested|ready|invalid_credentials|unreachable|unsupported|disconnected",
  "stale": false, "ready_for_handoff": true, "stale_after_seconds": 604800,
  "last_test_error_code": null | "a2a_unreachable" | "a2a_not_an_agent" |
     "a2a_protocol_version_unsupported" | "a2a_no_supported_interface" |
     "a2a_auth_scheme_unsupported" | "a2a_credentials_rejected" | "a2a_rate_limited" |
     "agent_card_changed" | "destination_*",
  "last_test_error_detail": null | { "found_version": "0.9.4" } | { "scheme": "oauth2" },
  "card": null | { "name": "…", "version": "…", "description": "…", "protocol_version": "1.0",
     "interface_url": "https://…", "streaming": true, "push_notifications": false,
     "skills": [ { "id": "…", "name": "…", "description": "…" } ],
     "auth_schemes_offered": [ { "name": "bearer", "kind": "bearer" } ],
     "extension_uris": [ "…" ], "fetched_at": "…" },
  "guarantee_tier": null | "guaranteed" | "best_effort",
  "tier_disclosure": null | "Guaranteed single start. …" | "Best-effort single start. …",
  "tier_disclosure_url": "https://github.com/…/single-start/v1.md",
  "capabilities": { "streaming": true, "push_notifications": false, "reply": true, "cancel": true },
  "cancellation_disclosure": "Cancellation depends on the agent …",
  "card_changed": false, "disconnect_reason": null | "owner" | "superseded_wire_contract",
  "last_contact_at": "…", "last_tested_at": "…", "created_at": "…", "revision": 3 }
```

`tier_disclosure` and `cancellation_disclosure` are server-owned sentences rendered
verbatim (FR-003, FR-010, FR-014). `capabilities.reply`/`.cancel` are always `true` for a
tested A2A connection; the run projection withdraws controls per run.

## Hand-off review and dispatch

`POST /tasks/{task_id}/agent-runs/preview` (gate) — request
`{ "connection_id": "…", "include_details": true, "supporting_items": [ { "label": "…", "body": "…" } ] }`.
Response `AgentManifestResponse`:

```json
{ "token": "<64 hex>", "run_id": "agentrun_…", "task_id": "…", "connection_id": "…",
  "agent_name": "…", "title": "…", "details": null | "…", "supporting_items": [ … ],
  "message_id": "agentrun_…:start", "correlation_id": "agentrun_…",
  "destination_interface": "https://…", "protocol_version": "1.0",
  "guarantee_tier": "best_effort", "tier_disclosure": "…",
  "cancellation_disclosure": "…", "external_copy_notice": "…",
  "reauthentication_required": false, "parts_preview": [ "<exact text of part 1>", "…" ] }
```

Preview refetches the card; drift ⇒ `400 {reason: "agent_card_changed"}` (D-02-S09).
`POST /tasks/{task_id}/agent-runs` (gate, Idempotency-Key) — request unchanged apart from
`supporting_items`; may take up to `dispatch_wait_seconds` and returns `AgentRunResponse`.
Replay with the same key returns the same run without a second exchange; replay on a
`delivery_unconfirmed` run performs the context lookup (adopt or resend) once.

## Runs

`AgentRunResponse` (fields added to the 007 shape; nothing removed except `capabilities.progress`):

```json
{ "…007 fields…",
  "run_version": 4,                       // BrainBuddy observation version
  "guarantee_tier": "best_effort",
  "message_id": "…", "correlation_id": "…", "agent_task_id": null | "task-…",
  "exchange_open": false,                 // a SendMessage exchange is still held
  "agent_task_missing": false,            // AC-020 condition
  "cancel_outcome": "none|requested|accepted|unsupported|not_cancelable|task_missing",
  "push_registration": "unregistered|registered|refused|unsupported",
  "blocked_reason": null | "Agent needs additional authentication",
  "artifacts_summary": [ { "name": "report.pdf", "media_type": "application/pdf", "kind": "file" } ],
  "last_observed_at": "…", "observation_interval_seconds": 60,
  "identifiers_expired": false,
  "events": [ { "id": "…", "type": "running", "run_version": 2, "received_at": "…",
                "summary": "…", "trigger": "schedule", "kind": "observation" } ],
  "commands": [ { "id": "agentcmd_…", "kind": "reply", "body": "…",
                  "delivery": "unconfirmed|confirmed|rejected", "outcome_code": null,
                  "created_at": "…", "confirmed_at": null } ] }
```

`primary_state_label` vocabulary (rendered verbatim, `design.md` D-03): `Not sent`, `Sent`,
`Delivery unconfirmed`, `Accepted`, `Running`, `Needs you`, `Cancellation requested`,
`Agent reported complete`, `Failed`, `Cancelled`, `Stopped reporting`,
`Agent no longer reports this run`, `Connection disconnected`,
`Content expired under retention policy`. Secondary server sentences: `failure_reason`
begins with `Rejected by agent` for rejected tasks; `cancel_outcome` ∈
`{unsupported, not_cancelable}` renders "Cancellation not supported by this agent."

`AgentRunSummaryResponse` adds `guarantee_tier`, `cancel_outcome`, `agent_task_missing`.

`POST /agent-runs/{id}/reply` and `POST /agent-runs/{id}/cancel`: unchanged requests;
refused with `400 {reason: "agent_task_missing"}` when the agent no longer reports the
run, and `400 {reason: "run_content_expired"}`/`"run_terminal"` as today. `cancel` on a run
with `cancel_outcome ∈ {unsupported, not_cancelable}` replays the recorded outcome (no
second CancelTask).

## New inbound route

`POST /a2a/push/{run_id}/{token}` — no session, not flag-gated, see `push-callback.md`.

## Rollout OFF (007 FR-019, FR-016)

Blocked: create/update/test/credential/preview/dispatch. Allowed: reads, disconnect,
reply/cancel for existing non-terminal runs, the push route, the observer, retention, purge.

## Error reasons added to `ValidationFailure.detail.reason`

`agent_card_changed`, `agent_task_missing`, `auth_scheme_unsupported`, `a2a_rate_limited`,
`connection_not_ready` (unchanged), `superseded_wire_contract` (mutations on a migrated
record). Every error carries `X-Correlation-ID`.
