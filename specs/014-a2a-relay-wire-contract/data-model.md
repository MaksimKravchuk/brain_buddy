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
| `endpoint_url` (storage key unchanged; the API exposes it as `agent_address`) | absolute URL, `_reject_endpoint_unsafe_components` | the agent **origin** the user typed; card fetched from `{origin}/.well-known/agent-card.json` (spec §14.3); may also be the full card URL if it ends with `agent-card.json`. The 007 storage key is kept on purpose so the previous image still parses the row on rollback (`plan.md`, Rollback boundary) |
| `auth_scheme` | `Literal["bearer","api_key"]` | chosen by the owner (D-01-S08/S09); default `bearer` |
| `auth_header_name` | HTTP field-name token, not in `RESERVED_AUTH_HEADER_NAMES`; key absent otherwise | stored only for `api_key` connections: copied from `card.security_schemes[…].api_key.name` at test time, never user-typed, and refused with `a2a_auth_scheme_unsupported` when it collides with the reserved set (which keeps every transport-structural name and adds `A2A-Version`, `A2A-Extensions`, `X-Correlation-ID`); a bearer connection stores **no** `auth_header_name` key — never `"Authorization"`, which the 007 model's validator rejects — and derives the `Authorization` header from `auth_scheme` at request time; absent until discovery |
| `credential` | `SealedSecret \| None` | unchanged sealing (`AAD_PURPOSE_OUTBOUND_CREDENTIAL`) |
| `card` | `AgentCardSummary \| None` | discovery result of the last successful card fetch (below); connection configuration retained for the connection's lifetime and erased on disconnect together with the credential — never swept at 90 d (product owner, 2026-09-04; FR-016, AC-024) |
| `card_fingerprint` | 64-hex sha256 \| None | over canonical JSON of `{interface_url, protocol_version, security_schemes: {name: kind/header}, security_requirements, extension_uris}`; drift detection (AC-012); connection lifetime, erased on disconnect (the run's copy in §2 is identifier tier, 90 d) |
| `card_drift_at` | datetime \| None | set when preview/dispatch sees a fingerprint mismatch; cleared by a successful test |
| `guarantee_tier` | `Literal["guaranteed","best_effort"] \| None` | `guaranteed` iff the extension URI is declared; `None` until tested |
| `best_effort_acknowledged_at` | datetime \| None | FR-003/AC-026: stamped by the first confirmed hand-off on this connection whose request carries `acknowledge_duplicate_risk: true` (under the repository's process-wide command lock); while `None` and the tier is `best_effort`, a confirm without the flag is refused (`duplicate_risk_acknowledgement_required`); **cleared whenever `scope_verified_at` is cleared** — agent address change, auth-scheme change, credential rotation, card drift detected — so the first hand-off after a destination change asks again; also cleared when the tier becomes `guaranteed` after a re-test (irrelevant then); never on rename |
| `context_id_honoured` | bool \| None | `None` until the first `SendMessage` answer on this connection; `False` when the task the agent returned does not carry the run id as its conversation identifier. While `False`, BrainBuddy never resends automatically on this connection (an empty lookup keeps **Delivery unconfirmed**) and the best-effort disclosure says so (FR-006); exposed as `correlation_id_honoured` |
| `agent_changed` (derived) | bool | `last_test_error_code == "agent_card_changed"` — the fifth connection condition **Agent changed** (FR-002, D-01-S20 / M-01-S18) |
| `status` | `untested\|ready\|invalid_credentials\|unreachable\|unsupported\|disconnected` | unchanged vocabulary; drift → `untested`; a rate-limited test (`last_test_error_code=a2a_rate_limited`) leaves `untested` — never `ready` — until a later successful test, and the retry is offered after `last_test_error_detail.retry_after_seconds` (FR-002, AC-037; D-01-S25 / M-01-S22) |
| `last_test_error_code` | str \| None | `a2a_unreachable`, `a2a_not_an_agent`, `a2a_protocol_version_unsupported`, `a2a_no_supported_interface`, `a2a_auth_scheme_unsupported`, `a2a_credentials_rejected`, `a2a_rate_limited`, `agent_card_changed`, plus every `destination_*` code from `egress.py` |
| `last_test_error_detail` | JSON object \| None, ≤ 512 bytes | closed per-code shapes, refreshed by every test: `a2a_protocol_version_unsupported` → `{"found_version": str}`; `a2a_auth_scheme_unsupported` → `{"scheme": str}`; `a2a_rate_limited` → `{"retry_after_seconds": int \| null}`; every other code → `null`. Coarse metadata; never card text beyond those values |
| `last_contact_at`, `last_tested_at`, `scope_verified_at`, `first_dispatch_at`, `disconnected_at` | unchanged | reauth scope resets on address change, auth-scheme change, credential rotation **and card drift**. `first_dispatch_at` (the spent first-content trigger read by `requires_dispatch_reauthentication`) is stamped by the exchange **start** — the `queued → open` transition of §2, when the message actually leaves BrainBuddy — never at reservation as 007 does today (`service.py` `dispatch_run` stamps it before any I/O): a `queued` hand-off that never started leaves it unset, so the retry of a hand-off a restart settled as **Not sent** is a first dispatch again and needs recent reauthentication (FR-004) |
| `disconnect_reason` | `Literal["owner","superseded_wire_contract"] \| None` | migration writes `superseded_wire_contract` (SC-010) |
| `controls_offered` (derived) | `{reply: bool, cancel: bool}` | BrainBuddy-side: the controls the product offers on this connection's runs — always `true` for a tested A2A connection, never an agent claim (cards do not advertise cancellation, FR-010); `capabilities` carries only the card's `streaming` and `push_notifications`; the run projection withdraws controls per run. The same name in `contracts/api-deltas.md` |
| removed | `inbound_secret`, `capabilities.progress`, `auth_header_name` as user input | FR-012 |

**AgentCardSummary** (embedded, coarse metadata): `name` (≤200), `version` (≤64), `description`
(≤2000), `protocol_version` (`"1.0"` or `"1.0.<patch>"`), `interface_url` (validated like
`agent_address`; may be a different host — validated separately, HTTPS unless governed private),
`streaming: bool`, `push_notifications: bool`, `skills[]` (≤50 × `{id ≤128, name ≤200,
description ≤500}`), `auth_schemes_offered[]` (`{name, kind: bearer|api_key|oauth2|oidc|mtls|other, header_name?}` — the same name in `contracts/api-deltas.md`),
`security_required: bool`, `extension_uris[]` (≤20 × ≤512 chars), `fetched_at`.
Every one of these strings — and every `last_test_error_detail` value — is untrusted agent text:
both clients render it as inert plain text, never an anchor or `Linking` target, never
HTML/markdown-interpreted, never auto-linkified, exactly as `result_link` is treated (FR-016,
AC-031); the bounds above are the only processing it receives. `interface_url` is the one
field that is not prose: it is the dispatch target, and discovery only ever copies the
interface it *selected*, which has already passed the destination check. A rejected address —
a `javascript:` scheme, a link-local metadata host — is refused at discovery as
`a2a_no_supported_interface`; there is no summary at all, so it is never copied into
`card.interface_url`, into a failure detail, or into any other stored field, and a card that
starts naming one leaves the last successfully tested card exactly as it was.

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
| `context_id` | str | `= id` (FR-006): the wire conversation identifier *is* the run id, which is also part of the push callback path. It is 007 coarse metadata retained with the run row until account purge — no sweep deletes a dispatched run row — and is therefore **not** identifier tier: nulling it at 90 d would erase nothing the agent or BrainBuddy holds, so SC-007 asserts the honest statement instead (research H) |
| `message_id` | str | `= f"{id}:start"`; identifier tier (90 d) |
| `agent_task_id` | str \| None | first known from the SendMessage response or the ListTasks probe; every adopted task must carry the run id as its conversation identifier (FR-006); **task succession** (Resolved 6, FR-010, AC-028): a reply exchange that returns a Task with a different id under the same correlation ID replaces it, the previous id is kept in the succession timeline row, and the reply is never refused; identifier tier |
| `interface_url` | str \| None | copied from the connection at dispatch; observation of this run always uses it (edge case "card changes while a run is active"); identifier tier |
| `card_fingerprint` | str \| None | at dispatch; identifier tier |
| `guarantee_tier` | `guaranteed\|best_effort` | copied at dispatch; shown on every surface (FR-013) |
| `run_version` | int ≥ 0 | **BrainBuddy-assigned observation version**; +1 per accepted observation under compare-and-set (FR-008) |
| `exchange_state` | `none\|queued\|open\|closed\|interrupted` | `queued` from the durable reservation until a worker of the exchange pool starts the exchange (at most `max_exchanges_per_connection` workers per connection, §9); `open` while a SendMessage exchange is held by a worker; `interrupted` after restart recovery of an `open` exchange only — a `queued` exchange (`exchange_started_at is None`) has provably not been sent and is settled instead as `dispatch_state=not_sent`, `dispatch_error_code=restarted_before_send`, `exchange_state=none`, with the hand-off re-offered under the same run and message ids (D-03-S03 / M-03-S02 variant text; AC-032). While `queued` nothing has gone out: `dispatch_run` skips the inline lookup and returns the **Queued** projection (`primary_state_label: "Queued"`, explained as "Waiting for a free connection slot; nothing has been sent yet" — the queued variant of D-03-S04 / M-03-S03); the label becomes **Sent** only once the worker starts the exchange |
| `exchange_kind` | `start\|reply\|None` | which exchange `exchange_state` describes. Restart recovery of a `reply` exchange is lookup-only and confirms the command by succession evidence (§4), never by resending it (AC-033) |
| `exchange_started_at`, `exchange_deadline_at` | datetime \| None | stamped when the worker **starts** the exchange, not at submit — in the same write as the connection's `first_dispatch_at` when that is still unset (§1); deadline = start + reply_window + 15 s, and it is enforced on the open socket by `egress.pinned_request` (`EgressDeadlineExceeded`, §9), not only recorded |
| `last_observed_at`, `next_observation_at` | datetime \| None | schedule; `None` once terminal, missing, or disconnected. After `last_contact_at + reporting_window` the interval backs off (×2 per missed interval, capped at 10 × `observation_interval_seconds`, derived from `last_contact_at` and `now` — no extra column) until `identifiers_expire_at`; a verified push, a reply/cancel acknowledgement or a user read of the run resets it to the base interval (FR-008). Scheduled observation of the predecessor task is suspended while the reply exchange is open and resumes when the exchange is `closed` or `interrupted` or at `exchange_deadline_at`, whichever comes first (succession precedence below) |
| `observation_trigger_pending` | `schedule\|push\|command\|None` | set by verified push / command ack so the next pass runs immediately |
| `agent_task_missing_at` | datetime \| None | TaskNotFound observed (AC-020); stops observation and commands, preserves last contact |
| `push_registration` | `unregistered\|registered\|refused\|unsupported` | `unsupported` when the card lacks push; `refused` on `-32003`/error (silent to the user) |
| `push_token_fingerprint` | str \| None | `SecretBox.fingerprint(token)`; identifier tier — kept until identifier expiry, **not** cleared on terminal, so a valid push arriving after the run closed still passes the fingerprint comparison and is classified `push_after_close`, never `push_token_rejected` (§7, SC-003) |
| `cancel_outcome` | `none\|requested\|unconfirmed\|accepted\|unsupported\|not_cancelable\|task_missing` | AC-018/AC-029; `unsupported` only from `-32004`/`-32601`, `not_cancelable` only from `-32002` — both keep the last observed state and withdraw the control; `unconfirmed` from `-32603`, HTTP 5xx, timeout or transport loss — keeps the last observed state **and** the cancel control, and a later attempt reuses the same command id |
| `blocked_reason` | str \| None | fixed text for `AUTH_REQUIRED` ("Agent needs additional authentication"); content tier |
| `artifacts_summary` | list[`{name ≤200, media_type ≤128, kind: text\|file\|data\|link}`] ≤20 | placeholders for non-text artifacts; content tier |
| `result_availability` | `available\|too_large\|None` | `None` until a terminal observation; `too_large` when the task record exceeded `a2a_task_max_response_bytes` and the state was observed through the `ListTasks` fallback — the surfaces show "unavailable (too large to store)" with a visible marker instead of drifting into **Stopped reporting**; coarse marker, nulled with the content tier |
| `identifiers_expire_at`, `identifiers_expired` | datetime, bool | `dispatched_at + 90 d`; sweep nulls every identifier-tier field |

**Manifest shape** (rollback boundary): the 014 manifest keeps the 007 keys `token`,
`run_id`, `task_id`, `connection_id`, `agent_name`, `title`, `details`, `context_items`
(storage name; the API says `supporting_items`) and `protocol_version` (`"1.0"`), adds
`message_id`, `correlation_id`, the tier and cancellation disclosures,
`acknowledgement_required` and `push_callback`, and **also writes the 007-required
`reporting` and `reporting_instructions` keys with inert placeholder values**
(`reporting = {callback_url: "", connection_id: <connection id>}` plus the 007 defaults;
`reporting_instructions = ""`) that 014 never reads and the API never exposes, so a frozen 007
`AgentRunManifest` validates every 014 run row and the 007 image's sweep, export and reads
keep working after a rollback (`plan.md`, Rollback boundary; research F).

**Dispatch state machine** (FR-006): `not_sent → delivery_unconfirmed` (reservation +
exchange `queued`, before I/O, as today) → `sent` (any of: SendMessage answered with a Task or
Message; ListTasks probe found the task; a later observation found it) or `not_sent`
(definitive: `ConnectError`, destination rejected before send, HTTP 4xx before task creation,
`-32602` invalid params, 429 → `dispatch_error_code=a2a_rate_limited`; or a restart while the
exchange was still `queued` → `dispatch_error_code=restarted_before_send`, hand-off re-offered
with the same ids) or stays `delivery_unconfirmed` (timeout/5xx/transport
loss/`EgressDeadlineExceeded`/`interrupted` with an empty correlation-ID lookup). A replayed
confirmation or the user's **Check again** (`POST /agent-runs/{id}/check-delivery`, D-03-S05 /
M-03-S04) on `delivery_unconfirmed` performs the correlation-ID lookup once; found → adopt →
`sent`; empty → resend the identical message once with the same message id — except on a
connection with `context_id_honoured=false`, where nothing is resent (not by any thread and
not on **Check again**, because an empty lookup there proves nothing) and the run stays
`delivery_unconfirmed`. **Resend preconditions** (AC-030, FR-006 — one reason per condition,
the same list as `contracts/api-deltas.md` `check-delivery`): the lookup is always allowed,
also while rollout is OFF, except on a disconnected connection; the resend branch is refused
and the run left `delivery_unconfirmed` — `connection_not_ready` when the connection is not
`ready`, is stale, or its `scope_verified_at` is `None` or younger than the run's
`dispatched_at` (address, auth-scheme, credential or card-drift reset since dispatch);
`agent_card_changed` when the connection is **Agent changed** or the run's pinned
`card_fingerprint` differs from the connection's; `run_content_expired` when `manifest` is
null; `reauthentication_required` when `requires_dispatch_reauthentication` applies and no
valid `current_password` was sent; `rollout_disabled` while rollout is OFF (AC-036) — returned
after the lookup ran, with the lookup's outcome (an adopted task, refreshed contact, the audit
row) already applied. `connection_disconnected` (no credential exists any more),
`run_terminal` and `agent_task_missing` refuse the whole check before any lookup. When it
runs it passes `requires_dispatch_reauthentication` exactly like a dispatch (the request
carries `current_password` for that case) — because `first_dispatch_at` is stamped by the
`queued → open` transition (§1), a resend of an exchange that had started lies inside the
spent trigger, and the reachable case of the rule is the retry of a hand-off that never left
(`queued` at restart → `not_sent`), which is a dispatch — goes to the run's pinned
`interface_url`, and is serialised: the `interrupted|delivery_unconfirmed → open` transition is a compare-and-set on
`run_version` under the process-wide command lock before any I/O, so a concurrent check, a
replayed confirmation or the observer's restart-recovery lookup re-reads, sees `open` and
returns the winner without network I/O (SC-008). No content-bearing `SendMessage` is ever
initiated without a user action: the exchange pool *executes* one, because a send an agent
holds open for the reply window may not sit on the request thread, but the only things that
start one are a confirmed hand-off, its user-triggered replay and a user reply — the
observer scheduler, the observation pool, the control pool, restart recovery and the
retention sweep emit none. Neither path ever mints a new run or message id.

**Observation state machine** (FR-009): `reported_state ∈ {accepted, running, blocked,
completed, failed, cancelled}`; terminal = `{completed, failed, cancelled}`; a differing
observation on a terminal run is rejected; an identical observation only refreshes
`last_contact_at`/`last_observed_at`. Label precedence (`_primary_state_label`, extended):
content expired → connection disconnected → completed/failed/cancelled → **agent no longer
reports this run** → stopped reporting → blocked ("Needs you" / auth reason) → cancellation
requested → running → accepted → delivery unconfirmed → sent → **queued** → not sent, where
`exchange_state = queued` is checked before the dispatch labels: a run whose exchange is still
`queued` renders as **Queued** ("Waiting for a free connection slot; nothing has been sent
yet" — the queued variant of D-03-S04 / M-03-S03) even though its durable `dispatch_state` is
already `delivery_unconfirmed`; a run whose exchange is `open` with no definitive outcome yet
renders as **Sent** (the D-03-S04 pending projection); and **Delivery unconfirmed** applies
only once the exchange has closed or been interrupted without evidence. `cancel_outcome ∈
{unsupported, not_cancelable, unconfirmed}` is a separate line, never the primary label.
`result_link` is rendered as inert text the user can copy on every surface:
`result_link_interactive` is always `false` because the 007 helper
`egress.interactive_result_link` is unchanged (product owner, 2026-09-04).

**Write rule for background threads** (FR-008, purge safety): every write from an observer or
exchange worker is a conditional `UPDATE … WHERE owner_id = ? AND id = ? AND run_version = ?`
issued by `AgentRelayService.apply_observation` after re-reading the run under the
repository's process-wide `command_lock`; there is no *run* insert path from background
threads — event, succession and audit rows are appended only for a run that still exists and
is not purged — the worker aborts when the run is missing, disconnected, terminal or
identifiers-expired, and no event, command or audit row is written for a missing run. Network I/O never happens inside
that lock (the 007 dispatch path in `service.py` is the pattern). A purged run therefore cannot
be resurrected and a disconnected or terminal run cannot be overwritten by a late result.

**Content expiry rule** (007 FR-015, SC-007): an observation — scheduled or push-triggered — on
a run whose content tier has expired (`content_expired` or `now >= content_expires_at`)
advances only `reported_state`, `run_version`, `last_contact_at`/`last_observed_at`, the raw
`agent_state` on the event row, timeline markers (`summary = None`) and terminal locking; it
MUST NOT write `blocked_reason`, `artifacts_summary`, `progress_text`, `question_text`,
`result_text`, `result_link`, `failure_reason` or any other agent text back into the row. The
same fields are nulled at read time by `domain.project_run_for_access` (§8), so a run whose
content is due but not yet swept never returns agent text either.

**Succession precedence** (FR-010, AC-028, AC-033): while the reply exchange is open,
scheduled observation of the predecessor task is suspended — bounded: it resumes once the
exchange is `closed` or `interrupted` or at `exchange_deadline_at`, whichever comes first — and
a terminal observation of the predecessor that arrives while the reply is unconfirmed or its
exchange is open does **not** lock the run — it is recorded as a `kind: observation` timeline
row whose summary reads "The previous task ended: <state>" and whose `type` is the run's
unchanged projected state, and the run stays blocked/reply-pending; when the reply exchange
returns a successor task the `task_succession` row supersedes the predecessor's terminal
outcome; when the reply itself meets a failed/terminal task with no successor, the observation
is applied honestly (the agent's own reason) and the reply control is withdrawn. A reply that
is never acknowledged stays in the timeline with `delivery: unconfirmed`;
`reply_pending_command_id` is kept until the first observation applied after the suspension
ends, which settles the command as unconfirmed, and the reply control then derives from that
observation's state — blocked ⇒ offered again for a new command id — so the run is never left
unobserved until identifier expiry.

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
| `kind` | `observation\|task_succession` | timeline rows only; a rejected push is never an event row — it is the bounded audit action `push_token_rejected` in §6 |
| `previous_agent_task_id`, `new_agent_task_id` | str \| None | only on `task_succession` rows; rendered as **The agent continued this run in a new task** (D-03-S27 / M-03-S26; identifier tier) |

Only differing observations create rows (no 60-second spam); rows are ordered by
`run_version`. A `task_succession` row is appended (and `run_version` incremented) when a
reply exchange returns a different task id under the same correlation ID; a terminal report
about the predecessor that arrives while the reply is pending is a `kind: observation` row
("The previous task ended: <state>") that does not change the run's state (§2, succession
precedence). Retention: summaries redacted at 30 d with the run content; rows purged with the
run's identifier expiry at 90 d.

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
Task/Message (explicit correlation) **or**, after a restart interrupted the reply exchange
(`exchange_kind=reply`), by succession evidence — a task in the run's conversation created
after the command's `created_at`, found by the recovery lookup — because Hermes serves no
history; a reply exchange is never resent. A reply whose exchange ended ambiguously and is
never acknowledged stays `unconfirmed` and is settled in the timeline when the observation
suspension ends (§2); a later reply gets a new command id; cancel → confirmed when `CancelTask` returns a Task,
`rejected` only on an explicit `-32002`/`-32004`/`-32601`/`-32001` answer, and left
`unconfirmed` (with `outcome_code=a2a_internal_error` for `-32603`, otherwise `None`) on
`-32603`, HTTP 5xx, timeout or transport loss — the run's `cancel_outcome` becomes
`unconfirmed` and a later cancel attempt reuses this command id (AC-029).

## 5. Idempotency record (`AgentIdempotencyRecord`) — unchanged

`key_hash`, `command`, `request_hash`, `resource_id`, `command_id`, `delivery_attempted`,
`completed`, `response_body`, `created_at` (24 h). The cancel receipt keeps
`connection_revision`; the dispatch receipt adds `exchange_state` so a replay while the
exchange is still open returns the live projection without a second exchange.

## 6. Audit entry (`AgentAuditEntryDocument`) — unchanged shape, new actions

Actions: `card_fetched`, `connection_tested`, `card_drift_detected`, `run_dispatched`,
`exchange_closed`, `task_adopted`, `delivery_lookup_failed` (one row per delivery check whose
correlation-ID lookup did not come back — outcome is the allowlisted transport code, and the
run is left exactly as it was: an unanswered lookup is not evidence that nothing exists, so it
licenses no resend, FR-006/SC-008), `task_succession_recorded` (one row per `task_succession`
timeline row, §3), `observation_accepted` (written only
when the observation changed the state, bounded per run/state class/UTC day — never one row
per 60-second poll), `observation_rejected` (bounded per owner/connection/class/day),
`push_registered`, `push_refused`, `push_verified`, `push_token_rejected` (one bounded row
per owner/connection/UTC day; the same name in `contracts/push-callback.md`),
`push_after_close` (bounded, same rule; also the classification of a valid push arriving after
the run closed, since the fingerprint is kept until identifier expiry), `run_replied`,
`run_cancel_requested`, `identifiers_expired`, `wire_superseded` (one row per connection the
ledgered migration rewrites; the ledger row records the count). Outcomes are coarse codes; never text, never tokens
(the push token appears in no audit row — the run keeps only `push_token_fingerprint`,
the keyed `SecretBox.fingerprint`). 90-day purge unchanged (`AUDIT_RETENTION`).

## 7. Push token (no document) — FR-008

Derived per run (32 bytes, urlsafe, a keyed HMAC over the run id under the relay key ring —
`derive_push_token`; never stored in plaintext, and recomputable so every reply carries the
same token), sent to the agent inside
`TaskPushNotificationConfig.url` and `.token` with the start message and again with every
reply message when the card supports push (so a successor task keeps push acceleration; the
schedule stays the fallback), stored only as `push_token_fingerprint`. Verification, in the
order fixed by `contracts/push-callback.md`: body cap → process-wide limiter → run lookup
(unknown → `403`, no row, no limiter key) → constant-time fingerprint comparison → run
dispatched + not terminal + not disconnected + connection exists → bounded per-run limiter.
It stops verifying when the run becomes terminal, missing or disconnected — that step refuses
with the `push_after_close` class — while the fingerprint itself is kept until identifier
expiry, so the comparison step still recognises a late valid push (the agent's terminal push
racing BrainBuddy's own terminal observation) and never misclassifies it as
`push_token_rejected`. `CreateTaskPushNotificationConfig` for an adopted task runs on the
control pool (§9). The verified push wakes the observer through the narrow wake port that
`api/dependencies.py` exposes to the route.
The token never appears in a response, error envelope, audit row, timeline event or log line
(`contracts/push-callback.md`, Redaction).

## 8. Retention tiers (SC-007)

| tier | fields | bound | sweep step |
|---|---|---|---|
| content | manifest, progress/question/result/failure texts, `result_link`, `blocked_reason`, `artifacts_summary`, the agent status text, `result_availability`, command bodies, event summaries | 30 d from dispatch | `expire_due_content` (**extended**: today it nulls six 007 fields once and re-detects only event summaries and command bodies — `repository.py` 998–1042; it now also nulls `blocked_reason`, `artifacts_summary` and the status text, and its selection predicate re-detects a non-null value in any content column, so a value written after expiry is re-erased on the next pass and nothing survives a partial expiry; the observation path itself never writes agent text into an expired run, §2. The read-time projection `domain.project_run_for_access` — today nulling manifest, the four texts, `result_link`, `failure_reason` and `reply_pending_command_id` on every read path, `domain.py` 362–378 — is extended to null `blocked_reason`, `artifacts_summary`, `result_availability` and the agent status text as well, so due content is inaccessible before the sweep runs. The sweep skips and logs — correlation id, no content — a row it cannot parse instead of aborting the transaction for every owner) |
| identifiers | `message_id`, `agent_task_id`, `interface_url`, `card_fingerprint`, `push_token_fingerprint`, event rows, `agent_task_id_after` — **not** the run id: `context_id = id` is retained with the run row as 007 coarse metadata until account purge (no sweep deletes a dispatched run row) and `docs/data-retention.md` says so | 90 d from dispatch | new `expire_due_identifiers` |
| audit | all audit rows | 90 d | `purge_expired_audit` (unchanged) |
| idempotency | records | 24 h | unchanged |
| connection card metadata | `card`, `card_fingerprint` | connection lifetime; erased on disconnect together with the credential — never swept; only audit rows that name the card follow the 90-day bound (product owner, 2026-09-04; FR-016, AC-024, SC-007) | `disconnect_connection` |

Account purge (`delete_all_for_owner`) deletes every row of every table; export
(`export_owner_data`) excludes `credential`, `push_token_fingerprint` and `card_fingerprint`.
One thing survives purge by design and is disclosed rather than hidden: the agent-side copy
of the push callback URL cannot be recalled (the credential needed to call
`DeleteTaskPushNotificationConfig` is destroyed first, and Hermes keeps only the URL). After
purge the token verifies against nothing — the route answers the opaque `403` for purged and
unknown runs without a durable row — and the 007 FR-005 external-copy notice already covers
the copy the agent keeps (`contracts/push-callback.md`, Deregistration). The tiers above are
documented for users in `docs/data-retention.md` (retention-schedule rows and the
`relay/relay.json` export member) and `frontend/src/pages/PrivacyPolicyPage.tsx`.

## 9. Configuration (`AgentRelaySettings`, `backend/app/core/config.py`)

| setting | env | default / bounds |
|---|---|---|
| `observation_interval_seconds` | `BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS` | 60, 5–3600 |
| `reply_window_seconds` | `BRAIN_BUDDY_AGENT_REPLY_WINDOW_SECONDS` | 300, 300–3600 (never below 300 s, FR-007) |
| `dispatch_wait_seconds` | `BRAIN_BUDDY_AGENT_DISPATCH_WAIT_SECONDS` | 5, 0–30 |
| `exchange_workers` (exchange pool: SendMessage start/reply only) | `BRAIN_BUDDY_AGENT_EXCHANGE_WORKERS` | 8, 1–64 |
| `max_exchanges_per_connection` (exchange workers one connection may hold at once; excess exchanges stay `queued`, so one hostile or broken agent cannot exhaust the pool for every owner) | `BRAIN_BUDDY_AGENT_MAX_EXCHANGES_PER_CONNECTION` | 2, 1–`exchange_workers` |
| `observer_workers` (observation pool: GetTask/ListTasks; separate from the exchange pool) | `BRAIN_BUDDY_AGENT_OBSERVER_WORKERS` | 4, 1–64 |
| `control_workers` (control pool: CancelTask and CreateTaskPushNotificationConfig, short timeout; never shared with start/reply exchanges, so a cancel never waits behind the exchanges it ends) | `BRAIN_BUDDY_AGENT_CONTROL_WORKERS` | 2, 1–16 |
| `connector_timeout_seconds` (test/short-call timeout; also the exchange connect timeout) | unchanged name | 10, ≤120 (exchanges use `httpx.Timeout(connect=5, read=reply_window + 15)`) |
| absolute request deadline | derived: `egress.pinned_request(deadline_seconds=…)` | exchange: `reply_window_seconds + 15` (315 s at the defaults); observation, control and test calls: `connector_timeout_seconds` (10 s) + 5 s = 15 s at the defaults. Enforced by `pinned_request` itself while waiting for headers and inside the `iter_raw` loop (an httpx read timeout is per chunk, so a drip-feeding agent never trips it); breach closes the stream and raises `EgressDeadlineExceeded` — exchange ⇒ `delivery_unconfirmed` (lookup before any resend), observation ⇒ failed contact, cancel ⇒ `cancel_outcome=unconfirmed`, test ⇒ `a2a_unreachable` |
| `connector_max_response_bytes` (card and short-call reads) | unchanged | 64000 |
| `a2a_task_max_response_bytes` (GetTask/ListTasks reads; over-cap GetTask falls back to ListTasks without artifacts) | `BRAIN_BUDDY_AGENT_A2A_TASK_MAX_RESPONSE_BYTES` | 262144 (256 KB), 1024–1048576 (1 MiB hard max) |
| push limiter bounds | constants beside the route (`PUSH_GLOBAL_MAX_PER_MINUTE`, `PUSH_RUN_MAX_PER_MINUTE`, `PUSH_LIMITER_MAX_KEYS`) | 600/min process-wide before any database read; 30/min per known run; at most 1024 per-run keys, evicted on terminal/disconnect |
| `push_base_path` | constant `AGENT_PUSH_PATH = "/a2a/push"` | replaces `AGENT_EVENTS_PATH` |
| `agent_relay_push_base_url` | derived | `{public_base_url}{api_prefix}/a2a/push` |
| `stale_after_seconds`, `reporting_window_seconds`, `content_retention_seconds`, `retention_sweep_interval_seconds`, `allow_private_destinations` | unchanged | |
