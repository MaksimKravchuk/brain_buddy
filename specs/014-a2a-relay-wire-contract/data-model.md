# Data model: A2A relay wire contract (feature 014)

Storage stays `backend/data/agents.sqlite3` through `backend/app/modules/agents/repository.py`
(SQLite-only, JSON payload per row, owner-scoped primary keys). No new table; the columns
below are added by a ledgered migration (`agent_schema_migrations`, pattern at
`repository.py` 284–331). Pydantic documents live in `backend/app/modules/agents/domain.py`
(`StorageBaseModel`); `schema_version` moves to 2 on every rewritten document.

Content limits are unchanged: `MAX_PROGRESS_CHARS=2000`, `MAX_QUESTION_CHARS=4000`,
`MAX_RESULT_CHARS=20000`, `MAX_REPLY_CHARS=4000`, `MAX_CONTEXT_ITEMS=20`,
`MAX_CONTEXT_ITEM_CHARS=4000` (`domain.py` 68–73). New bounds: `MAX_CARD_BYTES=64000`
(connector max response), `MAX_SKILLS=50`, `MAX_SKILL_TEXT_CHARS=500`,
`MAX_CARD_DESCRIPTION_CHARS=2000`, `MAX_ARTIFACT_SUMMARY_ITEMS=20`, `MAX_EXTENSIONS=20`.

## 1. Agent Connection (`AgentConnectionDocument`) — FR-001, FR-002, FR-003, FR-004, FR-012

| field | type | rule |
|---|---|---|
| `id`, `owner_id`, `name`, `created_at`, `updated_at`, `revision` | unchanged | 007 |
| `wire` | `Literal["a2a"]` | new; a record without it is a pre-existing bespoke record (migration marks it disconnected) |
| `endpoint_url` → `agent_address` | absolute URL, `_reject_endpoint_unsafe_components` | the agent **origin** the user typed; card fetched from `{origin}/.well-known/agent-card.json` (spec §14.3); may also be the full card URL if it ends with `agent-card.json` |
| `auth_scheme` | `Literal["bearer","api_key"]` | chosen by the owner (D-01-S08/S09); default `bearer` |
| `auth_header_name` | HTTP field-name token, not in `RESERVED_AUTH_HEADER_NAMES` | `"Authorization"` for bearer; for api_key copied from `card.security_schemes[…].api_key.name` at test time, never user-typed; `None` until discovery |
| `credential` | `SealedSecret \| None` | unchanged sealing (`AAD_PURPOSE_OUTBOUND_CREDENTIAL`) |
| `card` | `AgentCardSummary \| None` | discovery result of the last successful card fetch (below) |
| `card_fingerprint` | 64-hex sha256 \| None | over canonical JSON of `{interface_url, protocol_version, security_schemes: {name: kind/header}, security_requirements, extension_uris}`; drift detection (AC-012) |
| `card_drift_at` | datetime \| None | set when preview/dispatch sees a fingerprint mismatch; cleared by a successful test |
| `guarantee_tier` | `Literal["guaranteed","best_effort"] \| None` | `guaranteed` iff the extension URI is declared; `None` until tested |
| `best_effort_acknowledged_at` | datetime \| None | FR-003/AC-026: stamped by the first confirmed hand-off on this connection whose request carries `acknowledge_duplicate_risk: true`; while `None` and the tier is `best_effort`, a confirm without the flag is refused (`duplicate_risk_acknowledgement_required`); cleared when the tier becomes `guaranteed` after a re-test (irrelevant then) and never on rename |
| `agent_changed` (derived) | bool | `last_test_error_code == "agent_card_changed"` — the fifth connection condition **Agent changed** (FR-002, D-01-S20 / M-01-S18) |
| `status` | `untested\|ready\|invalid_credentials\|unreachable\|unsupported\|disconnected` | unchanged vocabulary; drift → `untested` |
| `last_test_error_code` | str \| None | `a2a_unreachable`, `a2a_not_an_agent`, `a2a_protocol_version_unsupported`, `a2a_no_supported_interface`, `a2a_auth_scheme_unsupported`, `a2a_credentials_rejected`, `a2a_rate_limited`, `agent_card_changed`, plus every `destination_*` code from `egress.py` |
| `last_contact_at`, `last_tested_at`, `scope_verified_at`, `first_dispatch_at`, `disconnected_at` | unchanged | reauth scope resets on address change, credential rotation **and card drift** |
| `disconnect_reason` | `Literal["owner","superseded_wire_contract"] \| None` | migration writes `superseded_wire_contract` (SC-010) |
| removed | `inbound_secret`, `capabilities.progress`, `auth_header_name` as user input | FR-012 |

**AgentCardSummary** (embedded, coarse metadata): `name` (≤200), `version` (≤64), `description`
(≤2000), `protocol_version` (`"1.0"` or `"1.0.<patch>"`), `interface_url` (validated like
`agent_address`; may be a different host — validated separately, HTTPS unless governed private),
`streaming: bool`, `push_notifications: bool`, `skills[]` (≤50 × `{id ≤128, name ≤200,
description ≤500}`), `security_schemes_offered[]` (`{name, kind: bearer|api_key|oauth2|oidc|mtls|other, header_name?}`),
`security_required: bool`, `extension_uris[]` (≤20 × ≤512 chars), `fetched_at`.

**State transitions** (connection): `untested → (test) ready | invalid_credentials |
unreachable | unsupported`; `ready → stale` is derived (`now >= last_contact_at + stale_after`);
`ready|stale → untested` on address change or credential rotation; `ready|stale → untested +
agent_card_changed` (**Agent changed**) on card drift seen by preview, dispatch or test, which
also resets `scope_verified_at` (FR-004); any → `disconnected` on owner disconnect or the wire
migration; `disconnected` is terminal. Hand-off is refused for `untested`, `stale`, changed
and `disconnected`.

**Client-facing vocabulary** (spec Clarifications 2026-09-03): REST responses say
`supporting_items` and `correlation_id`; the internal field names `context_items`/`context_id`
below mirror the protocol and never leave `backend/app` (see `contracts/api-deltas.md`).

## 2. Execution Run (`AgentRunDocument`) — FR-005, FR-006, FR-007, FR-008, FR-013, FR-015

| field | type | rule |
|---|---|---|
| `id`, `owner_id`, `connection_id`, `task_id`, `agent_name`, `manifest`, `dispatched_at`, `dispatch_state`, `dispatch_error_code`, `reported_state`, `progress_text`, `question_text`, `result_text`, `result_link`, `failure_reason`, `last_contact_at`, `cancel_requested_at`, `reply_pending_command_id`, `connection_disconnected_at`, `content_expires_at`, `content_expired`, `created_at`, `updated_at`, `revision` | unchanged | 007 |
| `context_id` | str | `= id` (FR-006); identifier tier (90 d) |
| `message_id` | str | `= f"{id}:start"`; identifier tier |
| `agent_task_id` | str \| None | first known from the SendMessage response or the ListTasks probe; **task succession** (Resolved 6): a reply exchange that returns a Task with a different id in the same correlation context replaces it, the previous id is kept in the succession timeline row, and the reply is never refused; identifier tier |
| `interface_url` | str \| None | copied from the connection at dispatch; observation of this run always uses it (edge case "card changes while a run is active"); identifier tier |
| `card_fingerprint` | str \| None | at dispatch; identifier tier |
| `guarantee_tier` | `guaranteed\|best_effort` | copied at dispatch; shown on every surface (FR-013) |
| `run_version` | int ≥ 0 | **BrainBuddy-assigned observation version**; +1 per accepted observation under compare-and-set (FR-008) |
| `exchange_state` | `none\|open\|closed\|interrupted` | `open` while a SendMessage exchange is held by a worker; `interrupted` after restart recovery |
| `exchange_started_at`, `exchange_deadline_at` | datetime \| None | deadline = start + reply_window + 15 s |
| `last_observed_at`, `next_observation_at` | datetime \| None | schedule; `None` once terminal, missing, or disconnected |
| `observation_trigger_pending` | `schedule\|push\|command\|None` | set by verified push / command ack so the next pass runs immediately |
| `agent_task_missing_at` | datetime \| None | TaskNotFound observed (AC-020); stops observation and commands, preserves last contact |
| `push_registration` | `unregistered\|registered\|refused\|unsupported` | `unsupported` when the card lacks push; `refused` on `-32003`/error (silent to the user) |
| `push_token_fingerprint` | str \| None | `SecretBox.fingerprint(token)`; identifier tier; cleared on terminal |
| `cancel_outcome` | `none\|requested\|accepted\|unsupported\|not_cancelable\|task_missing` | AC-018; `unsupported`/`not_cancelable` keep the last observed state |
| `blocked_reason` | str \| None | fixed text for `AUTH_REQUIRED` ("Agent needs additional authentication"); content tier |
| `artifacts_summary` | list[`{name ≤200, media_type ≤128, kind: text\|file\|data\|link}`] ≤20 | placeholders for non-text artifacts; content tier |
| `identifiers_expire_at`, `identifiers_expired` | datetime, bool | `dispatched_at + 90 d`; sweep nulls every identifier-tier field |

**Dispatch state machine** (FR-006): `not_sent → delivery_unconfirmed` (reservation +
exchange opened, before I/O, as today) → `sent` (any of: SendMessage answered with a Task or
Message; ListTasks probe found the task; a later observation found it) or `not_sent`
(definitive: `ConnectError`, destination rejected before send, HTTP 4xx before task creation,
`-32602` invalid params, 429 → `dispatch_error_code=a2a_rate_limited`) or stays
`delivery_unconfirmed` (timeout/5xx/transport loss/`interrupted` with an empty context lookup).
A replayed confirmation on `delivery_unconfirmed` performs the context lookup; found → adopt →
`sent`; empty → resend the identical message once.

**Observation state machine** (FR-009): `reported_state ∈ {accepted, running, blocked,
completed, failed, cancelled}`; terminal = `{completed, failed, cancelled}`; a differing
observation on a terminal run is rejected; an identical observation only refreshes
`last_contact_at`/`last_observed_at`. Label precedence (`_primary_state_label`, extended):
content expired → connection disconnected → completed/failed/cancelled → **agent no longer
reports this run** → stopped reporting → blocked ("Needs you" / auth reason) → cancellation
requested → running → accepted → delivery unconfirmed → sent → not sent.
`cancel_outcome ∈ {unsupported, not_cancelable}` is a separate line, never the primary label.

**Last contact** (FR-015): max of accepted dispatch (`sent`), successful observation (including
unchanged), acknowledged reply/cancel. **Stopped reporting**: non-terminal, not disconnected,
not missing, `now >= last_contact_at + reporting_window`.

## 3. Observation (`AgentRunEventDocument`, extended) — FR-008, FR-009

| field | type | rule |
|---|---|---|
| `id`, `owner_id`, `run_id`, `connection_id`, `type` (mapped state), `run_version`, `received_at`, `summary` | unchanged | `summary` is content tier |
| `trigger` | `dispatch\|schedule\|push\|command` | why the observation ran |
| `agent_state` | raw `TASK_STATE_*` string ≤64 | coarse, 90 d with the row |
| `agent_status_at` | datetime \| None | agent's `status.timestamp`, informational only |
| `kind` | `observation\|task_succession\|push_rejected` | timeline vs. coarse markers |
| `previous_agent_task_id`, `new_agent_task_id` | str \| None | only on `task_succession` rows; rendered as "Agent continued the run in a new task" (identifier tier) |

Only differing observations create rows (no 60-second spam); rows are ordered by
`run_version`. A `task_succession` row is appended (and `run_version` incremented) when a
reply exchange returns a different task id in the same correlation context. Retention:
summaries redacted at 30 d with the run content; rows purged with the run's identifier
expiry at 90 d.

## 4. Run Command (`AgentRunCommandDocument`, extended) — FR-006, FR-010

| field | type | rule |
|---|---|---|
| `id` | `agentcmd_…` | doubles as the A2A `messageId` (reply) or `metadata["brainbuddy.command_id"]` (cancel) |
| `kind`, `body`, `created_at`, `confirmed_at` | unchanged | body content tier |
| `delivery` | `unconfirmed\|confirmed\|rejected` | `rejected` only from an explicit A2A error correlated to this command |
| `outcome_code` | str \| None | `a2a_task_not_cancelable`, `a2a_unsupported_operation`, `a2a_task_not_found`, `a2a_internal_error`, `a2a_rate_limited` |
| `agent_task_id_after` | str \| None | task returned by the reply exchange (identifier tier) |

Confirmation rules: start → confirmed by `sent`; reply → confirmed only when a Task whose
`history[]` contains our `messageId` is observed **or** the reply exchange itself returns a
Task/Message (explicit correlation); cancel → confirmed when `CancelTask` returns a Task.

## 5. Idempotency record (`AgentIdempotencyRecord`) — unchanged

`key_hash`, `command`, `request_hash`, `resource_id`, `command_id`, `delivery_attempted`,
`completed`, `response_body`, `created_at` (24 h). The cancel receipt keeps
`connection_revision`; the dispatch receipt adds `exchange_state` so a replay while the
exchange is still open returns the live projection without a second exchange.

## 6. Audit entry (`AgentAuditEntryDocument`) — unchanged shape, new actions

Actions: `card_fetched`, `connection_tested`, `card_drift_detected`, `run_dispatched`,
`exchange_closed`, `task_adopted`, `task_succeeded`, `observation_accepted`,
`observation_rejected` (bounded per owner/connection/class/day), `push_registered`,
`push_refused`, `push_verified`, `push_rejected` (bounded), `run_replied`,
`run_cancel_requested`, `identifiers_expired`, `wire_superseded`. Outcomes are coarse codes;
never text, never tokens. 90-day purge unchanged (`AUDIT_RETENTION`).

## 7. Push token (no document) — FR-008

Generated per run (32 random bytes, urlsafe), sent to the agent inside
`TaskPushNotificationConfig.url` and `.token`, stored only as `push_token_fingerprint`.
Verification: fingerprint match + run dispatched + not terminal + not disconnected +
connection exists + rate limit. Invalidated when the run becomes terminal, missing or
disconnected, and on identifier expiry.

## 8. Retention tiers (SC-007)

| tier | fields | bound | sweep step |
|---|---|---|---|
| content | manifest, progress/question/result/failure texts, `result_link`, `blocked_reason`, `artifacts_summary`, command bodies, event summaries | 30 d from dispatch | `expire_due_content` (unchanged) |
| identifiers | `context_id`, `message_id`, `agent_task_id`, `interface_url`, `card_fingerprint`, `push_token_fingerprint`, event rows, `agent_task_id_after` | 90 d from dispatch | new `expire_due_identifiers` |
| audit | all audit rows | 90 d | `purge_expired_audit` (unchanged) |
| idempotency | records | 24 h | unchanged |
| connection card metadata | `card`, `card_fingerprint` | connection lifetime; erased on disconnect together with the credential | `disconnect_connection` |

Account purge (`delete_all_for_owner`) deletes every row of every table; export
(`export_owner_data`) excludes `credential`, `push_token_fingerprint` and `card_fingerprint`.

## 9. Configuration (`AgentRelaySettings`, `backend/app/core/config.py`)

| setting | env | default / bounds |
|---|---|---|
| `observation_interval_seconds` | `BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS` | 60, 5–3600 |
| `reply_window_seconds` | `BRAIN_BUDDY_AGENT_REPLY_WINDOW_SECONDS` | 300, 30–3600 |
| `dispatch_wait_seconds` | `BRAIN_BUDDY_AGENT_DISPATCH_WAIT_SECONDS` | 5, 0–30 |
| `observer_workers` | `BRAIN_BUDDY_AGENT_OBSERVER_WORKERS` | 8, 1–64 |
| `connector_timeout_seconds` (test/short-call timeout) | unchanged name | 10, ≤120 |
| `connector_max_response_bytes` | unchanged | 64000 |
| `push_base_path` | constant `AGENT_PUSH_PATH = "/a2a/push"` | replaces `AGENT_EVENTS_PATH` |
| `agent_relay_push_base_url` | derived | `{public_base_url}{api_prefix}/a2a/push` |
| `stale_after_seconds`, `reporting_window_seconds`, `content_retention_seconds`, `retention_sweep_interval_seconds`, `allow_private_destinations` | unchanged | |
