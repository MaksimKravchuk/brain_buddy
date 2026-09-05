# Contract: push notifications — what BrainBuddy registers and what it accepts

Push is an **accelerator only** (FR-008): a verified notification schedules an immediate
authenticated `GetTask`; nothing in the notification body ever changes run state.

## What BrainBuddy registers

Only when the agent card declares `capabilities.pushNotifications: true`.

1. **Inline with the start message** (preferred; works for the blocking Hermes exchange
   because no task id is needed yet):

```json
"configuration": {
  "taskPushNotificationConfig": {
    "url": "https://<public_base_url>/api/a2a/push/<run_id>/<token>",
    "token": "<token>"
  }
}
```

2. **After adopting a task** found by `ListTasks` (interrupted exchange):
   `CreateTaskPushNotificationConfig {taskId, url, token}`. Any error (including `-32003`)
   sets `push_registration=refused`; the run continues by observation and nothing is shown
   as an error (spec edge case).

3. **With every reply message**: the follow-up `SendMessage` carries the same per-run
   `taskPushNotificationConfig` whenever the card supports push, so a successor task created
   by the reply (`a2a-wire.md`, Task succession) keeps push acceleration; the observation
   schedule stays the fallback.

The hand-off review discloses this registration before confirmation (FR-005, AC-007):
`AgentManifestResponse.push_callback` carries `registered`, a token-masked `url_preview` and
the server-owned disclosure sentence (`api-deltas.md`).

`token`: 32 bytes, urlsafe base64, unique per run, **derived** at dispatch as a keyed HMAC
over the run id under the relay key ring (`derive_push_token`) rather than drawn at random,
because the same token has to go out again with every reply and the run stores only its
fingerprint — a value that must be reproducible cannot also be forgotten. It is
indistinguishable from random without the key and unguessable with it, because the run id it
derives from is itself unguessable. Stored only as `SecretBox.fingerprint(token)` — kept until identifier expiry (90 d), not cleared at
terminal, so a late valid push is still recognised as such (below). `url` is built from
`agent_relay_push_base_url` (`BRAIN_BUDDY_PUBLIC_BASE_URL` + api prefix + `/a2a/push`), which
production validates as a canonical public HTTPS origin (`backend/app/core/config.py`
`_canonical_public_base_url`). That origin is the **backend Fly app's own**
(`fly.backend.toml` sets `BRAIN_BUDDY_PUBLIC_BASE_URL = 'https://brain-buddy-backend.fly.dev'`),
so the agent calls the backend app directly; the frontend image's nginx proxy
(`deploy/nginx/default.conf`, which proxies *outward* to that backend) is not on the path.
The registration call for an adopted task runs on the control pool, never behind exchanges.
`authentication` is omitted (neither reference runtime honours it; the SDK sends the token as
`X-A2A-Notification-Token`, Hermes sends nothing but `X-A2A-Signature`).

Why the token is in the URL: Hermes stores only the URL of a push config and signs with a
secret BrainBuddy cannot know, so a header-only token would leave Hermes pushes unverifiable.
The token authorizes one thing — an extra observation BrainBuddy would perform anyway within
`observation_interval_seconds` — so its exposure in an agent's log is bounded by design.
BrainBuddy's own logs are a different matter and are handled below.

## Redaction (the token never reaches BrainBuddy's logs)

- `backend/app/api/middleware.py` (`CorrelationIdMiddleware`) today logs `request.url.path`
  on both its success line (`api_request …`) and its exception line (`api_request_failed …`).
  It applies a pure sanitising function before **any** log call: any path under
  `{api_prefix}/a2a/push/` is logged as `{api_prefix}/a2a/push/{run_id}/[redacted]`, on both
  lines; the function only rewrites the string and must never raise, so a malformed path can
  neither leak nor break the request.
- `backend/app/core/logging.py` routes `uvicorn.access` to the console handler; it gains a
  logging filter that rewrites or drops access lines whose request path starts with
  `{api_prefix}/a2a/push/`, so the server's own access log cannot repeat the token either.
- Those two are the only layers, and the only ones on the token's path: the callback URL is
  built from the backend app's own origin (above), so agents call the backend Fly app
  directly, the frontend image's `deploy/nginx/default.conf` never sees the request and needs
  no `location /api/a2a/push/` block, and `backend/Dockerfile` runs uvicorn with no reverse
  proxy of its own.
- The token never appears in responses, error envelopes, audit rows (they carry ids and
  coarse outcome codes only; the run keeps just `push_token_fingerprint`, the keyed
  `SecretBox.fingerprint`, never a plain digest) or timeline events.
- Residual: the real production edge is the Fly proxy in front of the backend app, which may
  log request paths outside BrainBuddy's control; that is disclosed, not argued away. It is
  bounded by the token's nature: wake-up-only (a verified push only schedules an immediate
  observation BrainBuddy would perform anyway; all state comes from `GetTask`), unique per
  run, and not honoured once the run is terminal or the connection is disconnected.
- SC-009 evidence: `test_push_token_never_appears_in_logs` (`test_agent_relay_api.py`)
  captures application logging **and** `uvicorn.access` — exactly the two in-process edges
  above — during a verified push, a rejected push and a failing push (the exception path) and
  asserts the issued token string appears in none of the captured lines.

## What BrainBuddy accepts

`POST {api_prefix}/a2a/push/{run_id}/{token}` — checks run strictly in this order:

| # | check | outcome |
|---|---|---|
| 1 | declared `Content-Length` > 64 000, or streamed body > 64 000 bytes | `413`, no row (before reading / while reading) |
| 2 | process-wide fixed-size limiter for the whole route, consulted **before any database read** | `429`, no row |
| 3 | resolve `run_id`: unknown, not dispatched, or identifiers expired | `403 {"detail":"Notification rejected."}`, **no durable row, no limiter key**; counted only in a process-wide fixed-size rejection counter (for alerting), never per unknown id |
| 4 | token fingerprint mismatch for a known run (constant-time comparison; the fingerprint is kept until identifier expiry, so a late *valid* push passes here) | `403`, one bounded audit row per (owner, connection, `push_token_rejected`, UTC day) |
| 5 | run terminal, `agent_task_missing`, or connection disconnected/missing — including a valid push that arrives after BrainBuddy's own terminal observation, the common Hermes race | `403`, bounded row class `push_after_close`, no observation |
| 6 | per-run limiter exceeded (30/min) — keys exist only for known, dispatched, non-terminal runs, the limiter has a maximum key count, and a run's bucket is evicted when the run goes terminal or is disconnected | `429`, no row |
| 7 | verified | `204`, `observation_trigger_pending="push"`, observer wake, audit `push_verified` |

`InMemoryRateLimiter` (`backend/app/core/rate_limit.py`) never evicts keys (its buckets are
`defaultdict`s and `_prune` only trims timestamps inside a key), so step 6 uses a bounded
variant (a `max_keys` extension of it) rather than the class as-is; step 2 is a plain
fixed-size counter with no per-key state. Because unknown ids never create a key, limiter
memory is bounded by real dispatched runs (`test_unknown_run_flood_leaves_limiter_memory_bounded_and_no_rows`),
and the global limiter trips before the run lookup (`test_global_push_limiter_trips_before_the_run_lookup`).
Steps 3, 4 and 5 are byte-identical to the caller — the same status, the same body, no
distinguishing header and no `Retry-After` — so they differ only in the durable audit row
BrainBuddy writes (`test_push_rejections_are_indistinguishable_to_the_caller`). The `429` of
step 6 is reachable only for known runs; that bounded run-existence oracle is intentional and
protected by unguessable run ids, and because it is the one deviation from the repository's
404-for-wrong-owner convention it is recorded in `docs/auth.md` in one line: the A2A push
callback answers 403 rather than 404, and its per-run 429 is a deliberate, run-id-gated
existence signal accepted because run ids are unguessable and the token authorises only an
observation BrainBuddy would perform anyway. A verified push wakes the observer through the
narrow wake port `api/dependencies.py` exposes to the route.

The body is **never parsed** for state. It may optionally be inspected for a JSON object
carrying `statusUpdate.taskId` / `task.id` to log a coarse `task_id_matches` boolean; a
mismatch still triggers the observation (the observation is authoritative). Rejections are
one opaque sentence; the class is in the owner's bounded audit only (007 post-ratification
clarification, `specs/007-external-agent-relay/spec.md` 111–128).

Headers BrainBuddy ignores: `X-A2A-Signature` (Hermes HMAC over sorted JSON keyed by
`A2A_PUSH_SECRET` or the bearer token — not per-run, not verifiable), `X-A2A-Notification-Token`
(redundant with the path token), `Authorization`.

Replay: a replayed valid push is idempotent — at most one in-flight observation per run and
the rate limit bound the cost; it changes nothing by itself (SC-003 "replayed push").

## Observation triggered by push

The observer performs `GetTask {id: agent_task_id, historyLength: 0}` (or the `ListTasks`
lookup if the task id is still unknown because the start exchange is still open) under
the connection's recorded `interface_url` and credential, hands the result to
`AgentRelayService.apply_observation`, which re-reads the run under the repository's
process-wide command lock and applies the projection with the compare-and-set version rule
(no network I/O inside the lock; no write when the run is missing, disconnected, terminal or
identifiers-expired), and records `trigger="push"` on any resulting timeline row. A push adds
no distinct user-visible state: the user sees the ordinary observation row arrive sooner
(design D-03-S05/S06, M-03-S04/S05) with `trigger: "push"` in the row's detail. A verified
push also resets the run's observation backoff to the base interval (FR-008).

## Reference-runtime behavior

| runtime | when it pushes | payload | header | BrainBuddy result |
|---|---|---|---|---|
| Hermes plugin | once, on terminal or input-required transition (`_finalize_task`) | `{"statusUpdate": {taskId, contextId, status}}`, `application/json` | `X-A2A-Signature` | path token verifies ⇒ immediate observation (AC-021) |
| a2a-sdk server with a push store | every event when configured | `MessageToDict(StreamResponse)` | `X-A2A-Notification-Token` | path token verifies ⇒ immediate observation |
| helloworld sample | never (no push capability) | — | — | `push_registration=unsupported`; schedule only |

## Deregistration

Nothing is deleted at the agent: the token stops verifying when the run becomes terminal,
missing or disconnected (step 5), while the fingerprint is deliberately kept — not cleared at
terminal — and nulled only at identifier expiry (90 d), so a late valid push is classified
`push_after_close` rather than `push_token_rejected`.
`DeleteTaskPushNotificationConfig` is not used (Hermes drops its single config after the
first push; the SDK config store is the agent's concern).

Account purge and disconnect: the agent-side copy of the callback URL cannot be recalled —
disconnect destroys the credential that `DeleteTaskPushNotificationConfig` would need, and
purge removes the run the config names — so it survives both by design and is disclosed
rather than hidden. After purge or disconnect the token verifies against nothing: the route
answers the opaque `403` of step 3 (unknown run, no durable row) or step 5 (disconnected,
bounded row), and the 007 FR-005 external-copy notice shown at every hand-off already covers
the copy the agent keeps (`data-model.md` §8).

## Security tests (SC-003, 014-SC-003; SC-009, 014-SC-009)

forged token · replayed valid push · wrong-run token · unknown run · oversize declared ·
oversize streamed · malformed body · push after terminal · push after disconnect · push for
another owner's run id · flood (rate limit) — each asserts zero projection change, zero
secret disclosure, and the bounded-cardinality audit rule. Plus:
`test_valid_push_after_terminal_is_classified_push_after_close` (a valid token arriving after
the observer's terminal observation is recorded as `push_after_close`, never
`push_token_rejected`), `test_push_rejections_are_indistinguishable_to_the_caller` (steps 3,
4 and 5: same status, same body, no distinguishing header or `Retry-After`),
`test_push_token_never_appears_in_logs` (SC-009 log scan over application and
`uvicorn.access` logging for a verified, a rejected and a failing push),
`test_unknown_run_flood_leaves_limiter_memory_bounded_and_no_rows` (N posts with random run
ids leave limiter memory bounded and create no row) and
`test_global_push_limiter_trips_before_the_run_lookup`.
