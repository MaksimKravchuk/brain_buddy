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
  "capabilities": { "streaming": true, "push_notifications": false },   // the card's own declarations only
  "controls_offered": { "reply": true, "cancel": true },                // BrainBuddy-side: the controls the product offers on this connection's runs, never an agent claim
  "cancellation_disclosure": "Cancellation depends on the agent …",
  "agent_changed": false,                      // FR-002 fifth condition; true iff last_test_error_code == "agent_card_changed"
  "best_effort_acknowledged_at": null | "…",  // FR-003 one-time acknowledgement (null until the first confirmed best-effort hand-off)
  "disconnect_reason": null | "owner" | "superseded_wire_contract",
  "last_contact_at": "…", "last_tested_at": "…", "created_at": "…", "revision": 3 }
```

`tier_disclosure` and `cancellation_disclosure` are server-owned sentences rendered
verbatim (FR-003, FR-010, FR-014); `tier_disclosure_url` is the published extension
specification the best-effort disclosure links to (FR-003), opened only on explicit user
action with external-destination disclosure. `capabilities` carries only what the card
declares (`streaming`, `push_notifications`); `controls_offered.reply`/`.cancel` are
BrainBuddy-side statements of the controls the product offers on this connection's runs —
always `true` for a tested A2A connection, because agent cards do not advertise cancellation
(FR-010) — never an agent claim; the run projection withdraws controls per run.

Every card-sourced string — `card.name`, `version`, `description`, `skills[].name`,
`skills[].description`, `auth_schemes_offered[].name`, `interface_url` — and every
`last_test_error_detail` value is untrusted agent text returned verbatim within the
`data-model.md` §1 bounds; both clients render it as inert plain text — never an anchor or
`Linking` target, never HTML/markdown-interpreted, never auto-linkified — exactly as
`result_link` is treated (FR-016, AC-031). `last_test_error_code: "a2a_rate_limited"` comes
with `status: "untested"` (never `ready`) until a later successful test; the client offers
the retry after `last_test_error_detail.retry_after_seconds` (D-01-S25 / M-01-S22, AC-037).

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
performs the correlation-ID lookup once and resends only under the `check-delivery`
preconditions below. A run that BrainBuddy restarted before its exchange ever started
returns `dispatch_state: "not_sent"`, `dispatch_error_code: "restarted_before_send"` — nothing
left BrainBuddy — and a later confirmation retries with the same run ID and message ID
(AC-032). That retry is the same request identity as the original confirmation —
`connection_id`, `include_details`, `supporting_items`, `manifest_token` and
`acknowledge_duplicate_risk` unchanged, under the `Idempotency-Key` both clients derive from
the manifest token (`agent-handoff-<token>`, as they do today) — so it replays through the
reserved run; the review reopened by **Try this hand-off again** is seeded from the run's
frozen manifest, and a rebuilt manifest whose token differs is a new preview that reserves a
new run while the earlier one stays `not_sent` (FR-005). Because `first_dispatch_at` is
stamped only when an exchange starts, such a retry is a first dispatch under
`requires_dispatch_reauthentication` and needs `current_password` once the 15-minute window
has passed (FR-004).

`POST /agent-runs/{id}/check-delivery` (Idempotency-Key; the **Check again** control on
D-03-S05 / M-03-S04) — body `{ "current_password": null | "…" }`, needed only when the resend
branch runs and the dispatch reauthentication rule (`requires_dispatch_reauthentication`,
FR-004) applies to the connection; the lookup never needs it. Performs the same
lookup-before-resend once with the run's own correlation ID and message ID: a found task is
adopted and the run becomes `sent`; when the agent *answers* and reports no task the identical
start message is resent once with the same message ID to the interface recorded at dispatch —
unless the connection has `correlation_id_honoured: false`, in which case nothing is resent.
A lookup that never came back — a timeout, a JSON-RPC error, an unusable payload, or a
deployment with no wire to look with — establishes nothing and therefore licenses nothing: the
run is returned unchanged as `delivery_unconfirmed` (200, and no refusal `reason` — the eight
below are all conditions on the *send*, and this is the absence of evidence for one), the
**Check again** control stays offered, and one `delivery_lookup_failed` audit row records the
allowlisted transport code. The resend branch — never the
lookup — is refused, leaving the run `delivery_unconfirmed`, with `400 {reason:
"connection_not_ready"}` when the connection is not `ready`, is stale, or its verified scope
was reset since the run was dispatched (an agent-address, authentication-scheme, credential or
card-drift reset), `"agent_card_changed"` when the connection is **Agent changed** or the
run's pinned card fingerprint no longer matches, `"run_content_expired"` when the frozen
manifest has been nulled by the content tier, `"reauthentication_required"` when the dispatch
reauthentication rule applies and no valid `current_password` was sent (with
`first_dispatch_at` stamped at exchange start, a resend of an exchange that had started lies
inside the spent trigger — the rule is applied all the same), and `"rollout_disabled"` while
rollout is OFF — returned after the lookup ran, with the lookup's outcome already applied: a
found task is adopted and the response is then the `sent` run, not a refusal (§Rollout OFF,
AC-036). Concurrent checks are
serialised per run: the `interrupted|delivery_unconfirmed → open` transition is a
compare-and-set on `run_version` under the process-wide command lock, so a second check, a
replayed confirmation or the observer's restart-recovery lookup returns the winner without a
second send (SC-008). Returns `AgentRunResponse`; on a run that is already `sent` it returns
the run unchanged. Refused outright — before any lookup — with `400 {reason: "run_terminal"}`,
`"agent_task_missing"` or `"connection_disconnected"` (a disconnected connection has no
credential left to look up with). That is the complete list, one reason per condition —
`connection_not_ready`, `agent_card_changed`, `run_content_expired`, `reauthentication_required`,
`rollout_disabled`, `run_terminal`, `agent_task_missing`, `connection_disconnected` — and
spec FR-006, `data-model.md` §2 and tasks T055/T068 carry the same eight. It never mints a
new run or message ID (AC-027, AC-030).

## Runs

`AgentRunResponse` (fields added to the 007 shape; nothing removed except `capabilities.progress`):

```json
{ "…007 fields…",
  "run_version": 4,                       // BrainBuddy observation version
  "guarantee_tier": "best_effort",
  "message_id": "…", "correlation_id": "…", "agent_task_id": null | "task-…",
  "exchange_open": false,                 // a SendMessage exchange is queued or still held
  "exchange_state": "none|queued|open|closed|interrupted",
  "exchange_kind": null | "start" | "reply",   // which exchange exchange_state describes
  "dispatch_error_code": null | "a2a_rate_limited" | "restarted_before_send" | "…",   // 007 field; restarted_before_send: the exchange never started before a restart — Not sent, nothing left BrainBuddy, hand-off re-offered with the same ids
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
has closed or been interrupted without evidence; `Not sent` with `dispatch_error_code ==
"restarted_before_send"` renders the D-03-S03 / M-03-S02 variant "BrainBuddy restarted before
this hand-off was sent. Nothing left BrainBuddy." beside the same-IDs retry. Secondary
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
`unconfirmed` it sends `CancelTask` again with the **same** command id (AC-029); `cancel` is
served from the dedicated control pool and never waits behind hand-off exchanges (AC-035). A
reply whose exchange ended ambiguously stays `delivery: "unconfirmed"` in `commands[]`;
scheduled observation resumes at the exchange deadline and the reply control returns, for a
new command id, only after a later observation shows the run blocked again (AC-033). A `GET` of
a run resets its observation backoff to the base interval.

## New inbound route

`POST /a2a/push/{run_id}/{token}` — no session, not flag-gated, see `push-callback.md`.

## Rollout OFF (007 FR-019, FR-016)

Blocked: create/update/test/credential/preview/dispatch, and the **resend branch** of
`check-delivery` and of a replayed confirmation — the property the flag protects is "no task
content leaves BrainBuddy", not "no run is created". Allowed: reads, disconnect, reply/cancel
for existing non-terminal runs (they complete or settle an already-confirmed hand-off and
never create a run), the **lookup** of `check-delivery` and of a replayed confirmation (an
authenticated observation that adopts a found task; on an empty answer the resend is refused
with `400 {reason: "rollout_disabled"}` — after the lookup ran, its outcome applied — and
the run stays `delivery_unconfirmed` until rollout is ON — AC-036), the push route, the
observer, retention, purge. Covered by the `test_agent_relay_api.py` rollout-OFF matrix.

## Error reasons added to `ValidationFailure.detail.reason`

`agent_card_changed`, `agent_task_missing`, `a2a_auth_scheme_unsupported` (the same code as
`last_test_error_code`), `a2a_rate_limited`, `duplicate_risk_acknowledgement_required`,
`connection_disconnected`, `rollout_disabled` (the resend refusal of `check-delivery` and of
a replayed confirmation while rollout is OFF, returned after the lookup ran),
`connection_not_ready` (unchanged; now also the resend refusal of `check-delivery`),
`run_content_expired`, `run_terminal` and `reauthentication_required` (unchanged; now also on
`check-delivery`), `superseded_wire_contract` (mutations on a migrated record). Every error
carries `X-Correlation-ID`.

## Compatibility (constitution Principle III, `docs/api-compatibility.md`)

The deltas above are breaking for a strict client under the repository's own policy: two
routes removed, `endpoint_url` renamed to `agent_address`, `context_items` renamed to
`supporting_items`, `inbound_signing_secret` and `capabilities.progress` removed,
`auth_header_name` no longer accepted on requests, `auth_scheme` newly required, the create
response type changed, new `last_test_error_code`, `cancel_outcome`, `dispatch_error_code`
and `primary_state_label` values, and — on `AgentManifestResponse` —
`destination_endpoint` renamed to `destination_interface`, `reporting_instructions` and
`instructions_version` removed (both clients render them today:
`frontend/src/features/agents/AgentHandoffOverlay.tsx`,
`mobile/src/features/agents/HandoffSheet.tsx`), and `protocol_version` re-defined from the
bespoke wire version `"2026-08-09"` (`domain.PROTOCOL_VERSION`) to the A2A protocol version
`"1.0"`.

The compatibility strategy — the migration note Principle III requires — is recorded here
rather than left implied. The web client ships lockstep with the backend behind the Fly
frontend proxy. The iOS client is **store-distributed**: `mobile/eas.json` has a `production`
profile (store distribution by default — only `development` and `preview` declare
`distribution: internal`), `docs/external-agent-relay-release.md` carries the TestFlight and
App Store path that builds and submits it, installed App Store binaries cannot be rolled back
remotely, and `docs/api-compatibility.md` records that no separately versioned mobile client
contract exists yet. The whole relay surface is gated by `external_agent_relay`, OFF since
007 ratification and rolled out per user, so no deployed client depends on the removed or
renamed shapes today; the enforceable mechanism that keeps it that way is a
**release-runbook gate**: `external_agent_relay` MUST NOT be turned ON for any user until the
refreshed iOS build is the only distributed build (TestFlight and App Store phased release
complete). While the flag is OFF a pre-014 build that meets the new API sees exactly the OFF
surface it sees today — the gated routes answer the same fail-closed 404 and the ungated
reads return empty collections, because no relay record exists for any user (spec
Assumptions). The mobile client sends no client-build header today
(`mobile/src/api/client.ts` sets only `Content-Type`, `Idempotency-Key` and
`X-Content-SHA256`), so no minimum-build check is introduced: the gate is the mechanism, and
no versioned OpenAPI snapshot or migration window is published for this change. Backend
schemas still change first (`backend/app/schemas/agents.py`), then
`frontend/src/api/agentTypes.ts` and `mobile/src/api/types.ts`.
