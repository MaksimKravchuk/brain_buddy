# Contract: BrainBuddy REST deltas (feature 014)

Base: `backend/app/api/agents.py` and `backend/app/schemas/agents.py` as ratified by 007.
Session cookie, owner scoping, `Idempotency-Key`, `X-Correlation-ID`, the
`external_agent_relay` gate on *new-work* routes, and 404-for-wrong-owner are unchanged.
Both clients (`frontend/src/api/agentTypes.ts`, `mobile/src/api/types.ts`) mirror these
shapes one-to-one. Vocabulary (spec Clarifications 2026-09-03, ADR-0006): client-facing
names are `supporting_items` and `correlation_id`; the protocol words never appear in any
response, label or error message. Connection condition labels rendered verbatim from
`status`/`last_test_error_code`: `Not tested`, `Tested ready`, `Stale`, `Invalid credentials`,
`Unreachable`, `Unsupported`, **`Agent changed`**, `Disconnected`.

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
  "last_test_error_detail": null | { "found_version": "0.9.4" } | { "scheme": "oauth2" } | { "retry_after_seconds": 30 },   // closed per-code shapes, data-model.md §1
  "correlation_id_honoured": null | true | false,   // false: the agent's first answer did not keep the run's correlation ID; BrainBuddy never auto-resends on this connection (FR-006)
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
  "agent_changed": false,                      // FR-002 fifth condition; true iff last_test_error_code == "agent_card_changed"
  "best_effort_acknowledged_at": null | "…",  // FR-003 one-time acknowledgement (null until the first confirmed best-effort hand-off)
  "disconnect_reason": null | "owner" | "superseded_wire_contract",
  "last_contact_at": "…", "last_tested_at": "…", "created_at": "…", "revision": 3 }
```

`tier_disclosure` and `cancellation_disclosure` are server-owned sentences rendered
verbatim (FR-003, FR-010, FR-014); `tier_disclosure_url` is the published extension
specification the best-effort disclosure links to (FR-003), opened only on explicit user
action with external-destination disclosure. `capabilities.reply`/`.cancel` are always
`true` for a tested A2A connection; the run projection withdraws controls per run.

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
  "tier_disclosure_url": "https://github.com/…/single-start/v1.md",
  "acknowledgement_required": true,          // best-effort tier and best_effort_acknowledged_at is null (AC-026)
  "cancellation_disclosure": "…", "external_copy_notice": "…",
  "push_callback": { "registered": true,     // false, with url_preview null and no disclosure, when the card lacks push support
                     "url_preview": "https://…/api/a2a/push/agentrun_…/…",   // token masked; the callback origin is part of the manifest token
                     "disclosure": "BrainBuddy also gives this agent a private callback address with a per-run token so it can tell BrainBuddy when to check on the run. The agent keeps that address until the run ends." },
  "reauthentication_required": false, "parts_preview": [ "<exact text of part 1>", "…" ] }
```

`push_callback.disclosure` is a server-owned sentence rendered verbatim in the review's
"what will be sent" list (FR-005, AC-007); the token itself never appears in any response.

Preview refetches the card; drift ⇒ `400 {reason: "agent_card_changed"}` and the connection
becomes **Agent changed** (D-02-S09, D-01-S20).

`POST /tasks/{task_id}/agent-runs` (gate, Idempotency-Key) — request:

```json
{ "connection_id": "…", "include_details": true, "supporting_items": [ … ],
  "manifest_token": "<64 hex>", "current_password": null | "…",
  "acknowledge_duplicate_risk": false | true }
```

`acknowledge_duplicate_risk` is part of the canonical request identity for replay. When the
connection is best-effort and `best_effort_acknowledged_at` is null, a confirm without
`acknowledge_duplicate_risk: true` is refused with `400 {reason:
"duplicate_risk_acknowledgement_required"}` before any reservation is consumed; the first
accepted confirm stamps the timestamp under the repository's process-wide command lock (the
flag is ignored otherwise). The timestamp is cleared, and the acknowledgement asked again,
whenever the connection's verified scope resets (address or auth-scheme change, credential
rotation, card drift). The call may take up to `dispatch_wait_seconds` and returns
`AgentRunResponse`; while the exchange is still `queued` (no free exchange worker yet) the
response carries `primary_state_label: "Queued"` — rendered with the explanation "Waiting
for a free connection slot; nothing has been sent yet" (the queued variant of D-03-S04 /
M-03-S03) — and no lookup has run; the label becomes `Sent` only once the exchange starts.
Replay with the same key
returns the same run without a second exchange; replay on a `delivery_unconfirmed` run
performs the correlation-ID lookup (adopt or resend) once.

`POST /agent-runs/{id}/check-delivery` (Idempotency-Key; no reauthentication; the **Check
again** control on D-03-S05 / M-03-S04) — empty body. Performs the same lookup-before-resend
once with the run's own correlation ID and message ID: a found task is adopted and the run
becomes `sent`; when the agent reports no task the identical start message is resent once with
the same message ID — unless the connection has `correlation_id_honoured: false`, in which case
nothing is resent; an ambiguous answer leaves the run `delivery_unconfirmed`. Returns
`AgentRunResponse`; on a run that is already `sent` it returns the run unchanged. Refused with
`400 {reason: "run_terminal"}`, `"agent_task_missing"` or `"connection_disconnected"`. It never
mints a new run or message ID (AC-027).

## Runs

`AgentRunResponse` (fields added to the 007 shape; nothing removed except `capabilities.progress`):

```json
{ "…007 fields…",
  "run_version": 4,                       // BrainBuddy observation version
  "guarantee_tier": "best_effort",
  "message_id": "…", "correlation_id": "…", "agent_task_id": null | "task-…",
  "exchange_open": false,                 // a SendMessage exchange is queued or still held
  "exchange_state": "none|queued|open|closed|interrupted",
  "agent_task_missing": false,            // AC-020 condition
  "cancel_outcome": "none|requested|unconfirmed|accepted|unsupported|not_cancelable|task_missing",
  "push_registration": "unregistered|registered|refused|unsupported",
  "blocked_reason": null | "Agent needs additional authentication",
  "artifacts_summary": [ { "name": "report.pdf", "media_type": "application/pdf", "kind": "file" } ],
  "result_link": null | "https://…",       // 007 field, unchanged: the agent-reported link, shown as inert text the user can copy
  "result_link_interactive": false,       // 007 field, always false: egress.interactive_result_link is unchanged (documented click-time reason), so no client ever renders the link as clickable
  "result_availability": null | "available" | "too_large",   // too_large: the task record exceeded the read cap; state observed through the task list
  "last_observed_at": "…", "observation_interval_seconds": 60,   // the configured base interval; the server may observe less often after the reporting window (FR-008 backoff)
  "identifiers_expired": false,
  "events": [ { "id": "…", "type": "running", "run_version": 2, "received_at": "…",
                "summary": "…", "trigger": "schedule", "kind": "observation",
                "previous_agent_task_id": null, "new_agent_task_id": null },
              { "id": "…", "type": "blocked", "run_version": 3, "received_at": "…",
                "summary": "The previous task ended: failed", "trigger": "schedule", "kind": "observation",
                "previous_agent_task_id": null, "new_agent_task_id": null },
              { "id": "…", "type": "running", "run_version": 4, "received_at": "…",
                "summary": "The agent continued this run in a new task", "trigger": "command",
                "kind": "task_succession", "previous_agent_task_id": "task-a1",
                "new_agent_task_id": "task-b2" } ],
  "commands": [ { "id": "agentcmd_…", "kind": "reply", "body": "…",
                  "delivery": "unconfirmed|confirmed|rejected", "outcome_code": null,
                  "created_at": "…", "confirmed_at": null } ] }
```

`primary_state_label` vocabulary (rendered verbatim, `design.md` D-03): `Not sent`, `Queued`,
`Sent`, `Delivery unconfirmed`, `Accepted`, `Running`, `Needs you`, `Cancellation requested`,
`Agent reported complete`, `Failed`, `Cancelled`, `Stopped reporting`,
`Agent no longer reports this run`, `Connection disconnected`,
`Content expired under retention policy`. A run whose exchange is still `queued` renders
`Queued` (the queued variant of D-03-S04 / M-03-S03), for example
`{ "dispatch_state": "delivery_unconfirmed", "exchange_state": "queued", "exchange_open": true,
"reported_state": null, "primary_state_label": "Queued" }`, and the client shows the design
copy "Waiting for a free connection slot; nothing has been sent yet" whenever
`exchange_state == "queued"`; a run whose exchange is `open` with no definitive outcome renders
`Sent` (the D-03-S04 pending projection); `Delivery unconfirmed` applies only once the exchange
has closed or been interrupted without evidence. Secondary
server sentences: `failure_reason` begins with `Rejected by agent` for rejected tasks;
`cancel_outcome` ∈ `{unsupported, not_cancelable}` renders "Cancellation not supported by this
agent."; `cancel_outcome == "unconfirmed"` renders "Cancellation request unconfirmed — you
can try again." and keeps the cancel control; `result_availability == "too_large"` renders
"Result unavailable (too large to store)." in place of the result text; a `kind:
task_succession` row renders **The agent continued this run in a new task** (D-03-S27,
M-03-S26).

`AgentRunSummaryResponse` adds `guarantee_tier`, `cancel_outcome`, `agent_task_missing`.

`POST /agent-runs/{id}/reply` and `POST /agent-runs/{id}/cancel`: unchanged requests;
refused with `400 {reason: "agent_task_missing"}` when the agent no longer reports the
run, and `400 {reason: "run_content_expired"}`/`"run_terminal"` as today. A reply the agent
answers with a different task in the same conversation is never refused: the new task is
adopted and the succession row appended (FR-010). `cancel` on a run with `cancel_outcome ∈
{unsupported, not_cancelable}` replays the recorded outcome (no second CancelTask); on
`unconfirmed` it sends `CancelTask` again with the **same** command id (AC-029). A `GET` of
a run resets its observation backoff to the base interval.

## New inbound route

`POST /a2a/push/{run_id}/{token}` — no session, not flag-gated, see `push-callback.md`.

## Rollout OFF (007 FR-019, FR-016)

Blocked: create/update/test/credential/preview/dispatch. Allowed: reads, disconnect,
reply/cancel and `check-delivery` for existing non-terminal runs (they complete or settle an
already-confirmed hand-off and never create a run), the push route, the observer, retention,
purge.

## Error reasons added to `ValidationFailure.detail.reason`

`agent_card_changed`, `agent_task_missing`, `auth_scheme_unsupported`, `a2a_rate_limited`,
`duplicate_risk_acknowledgement_required`, `connection_disconnected`,
`connection_not_ready` (unchanged), `superseded_wire_contract` (mutations on a migrated
record). Every error carries `X-Correlation-ID`.

## Compatibility (constitution Principle III, `docs/api-compatibility.md`)

The deltas above are breaking for a strict client under the repository's own policy: two
routes removed, `endpoint_url` renamed to `agent_address`, `context_items` renamed to
`supporting_items`, `inbound_signing_secret` and `capabilities.progress` removed,
`auth_header_name` no longer accepted on requests, `auth_scheme` newly required, the create
response type changed, and new `last_test_error_code`, `cancel_outcome` and
`primary_state_label` values. The compatibility strategy is recorded here rather than left
implied: the web client ships lockstep with the backend behind the Fly frontend proxy; the
iOS client is internal distribution (`mobile/eas.json` `development` and `preview` profiles
declare `distribution: internal`, and `docs/api-compatibility.md` records that no separately
versioned mobile client contract exists yet); and the whole relay surface is gated by
`external_agent_relay`, which has been OFF since 007 ratification, so no deployed client
depends on the removed or renamed shapes. Therefore no versioned OpenAPI snapshot and no
migration window are published for this change; the minimum iOS build is refreshed together
with the backend release (the pre-014 build cannot render an A2A connection and must not be
kept in use once the flag turns on); and this document is the migration note Principle III
requires. Backend schemas still change first (`backend/app/schemas/agents.py`), then
`frontend/src/api/agentTypes.ts` and `mobile/src/api/types.ts`.
