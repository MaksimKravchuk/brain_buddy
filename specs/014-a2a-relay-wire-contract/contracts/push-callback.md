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

`token`: 32 random bytes, urlsafe base64, unique per run, generated at dispatch, stored only
as `SecretBox.fingerprint(token)`. `url` is built from `agent_relay_push_base_url`
(`BRAIN_BUDDY_PUBLIC_BASE_URL` + api prefix + `/a2a/push`), which production validates as a
canonical public HTTPS origin (`backend/app/core/config.py` `_canonical_public_base_url`).
`authentication` is omitted (neither reference runtime honours it; the SDK sends the token as
`X-A2A-Notification-Token`, Hermes sends nothing but `X-A2A-Signature`).

Why the token is in the URL: Hermes stores only the URL of a push config and signs with a
secret BrainBuddy cannot know, so a header-only token would leave Hermes pushes unverifiable.
The token authorizes one thing — an extra observation BrainBuddy would perform anyway within
`observation_interval_seconds` — so its exposure in an agent's log is bounded by design.

## What BrainBuddy accepts

`POST {api_prefix}/a2a/push/{run_id}/{token}`

| check | order | outcome |
|---|---|---|
| declared `Content-Length` > 64 000 | before reading | `413`, no row |
| streamed body > 64 000 bytes | while reading | `413`, no row |
| `run_id` unknown, or run not dispatched, or identifiers expired | after reading | `403 {"detail":"Notification rejected."}`, **no durable row** |
| token fingerprint mismatch for a known run | | `403`, one bounded audit row per (owner, connection, `push_token_rejected`, UTC day) |
| run terminal, `agent_task_missing`, or connection disconnected/missing | | `403`, bounded row class `push_after_close`, no observation |
| per-run rate limit exceeded (`InMemoryRateLimiter`, 30/min) | | `429`, no row |
| verified | | `204`, `observation_trigger_pending="push"`, observer wake, audit `push_verified` |

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

The observer performs `GetTask {id: agent_task_id}` (or the `ListTasks` lookup if the task
id is still unknown because the start exchange is open) under the connection's recorded
`interface_url` and credential, applies the projection under the owner lock with the
compare-and-set version rule, and records `trigger="push"` on any resulting timeline row.

## Reference-runtime behavior

| runtime | when it pushes | payload | header | BrainBuddy result |
|---|---|---|---|---|
| Hermes plugin | once, on terminal or input-required transition (`_finalize_task`) | `{"statusUpdate": {taskId, contextId, status}}`, `application/json` | `X-A2A-Signature` | path token verifies ⇒ immediate observation (AC-021) |
| a2a-sdk server with a push store | every event when configured | `MessageToDict(StreamResponse)` | `X-A2A-Notification-Token` | path token verifies ⇒ immediate observation |
| helloworld sample | never (no push capability) | — | — | `push_registration=unsupported`; schedule only |

## Deregistration

Nothing is deleted at the agent: the token stops verifying when the run becomes terminal,
missing or disconnected, and the fingerprint is nulled at identifier expiry (90 d).
`DeleteTaskPushNotificationConfig` is not used (Hermes drops its single config after the
first push; the SDK config store is the agent's concern).

## Security tests (SC-003, 014-SC-003)

forged token · replayed valid push · wrong-run token · unknown run · oversize declared ·
oversize streamed · malformed body · push after terminal · push after disconnect · push for
another owner's run id · flood (rate limit) — each asserts zero projection change, zero
secret disclosure, and the bounded-cardinality audit rule.
