# Contract: the A2A operations BrainBuddy uses (outbound)

Binding: **JSON-RPC 2.0 over HTTP(S)** only (A2A v1.0 §9). BrainBuddy is a client, never a
server. Every request below passes `validate_destination` and `pinned_request`
(`backend/app/modules/agents/egress.py`): one pinned address, hostname TLS, no redirects,
body ≤ `connector_max_response_bytes` for card and short-call reads and
≤ `a2a_task_max_response_bytes` (default 256 KB, hard maximum 1 MiB) for `GetTask`/`ListTasks`
reads, HTTPS unless the governed private class applies.

## Discovery

`GET {agent_origin}/.well-known/agent-card.json` — no credential, `Accept: application/json`,
timeout `connector_timeout_seconds`. Parsing is **lenient** (unknown fields ignored) and
accepts both the 1.0 shape and the legacy shape Hermes serves:

| card field | accepted forms | use |
|---|---|---|
| `supportedInterfaces[]` | `{url, protocolBinding, protocolVersion, tenant?}`; legacy `url` + `preferredTransport` + top-level `protocolVersion` | first entry with `protocolBinding == "JSONRPC"` and `protocolVersion` matching `^1\.0(\.\d+)?$` (§8.3.2); its `url` is the interface; `tenant` echoed in every request when set |
| `capabilities.streaming`, `.pushNotifications` | bool | recorded; push registration only when true |
| `capabilities.extensions[]` | `{uri, description?, required?, params?}` | `uri == <single-start URI>` ⇒ guaranteed tier; any `required: true` extension BrainBuddy does not implement ⇒ `a2a_no_supported_interface` |
| `securitySchemes{}` | 1.0 `{httpAuthSecurityScheme:{scheme}}` / `{apiKeySecurityScheme:{location,name}}`; legacy `{type:"http",scheme}` / `{type:"apiKey",in,name}` | supported: `http`+`bearer` → `Authorization: Bearer <cred>`; `apiKey` with `location/in == "header"` → `<name>: <cred>`; anything else ⇒ `a2a_auth_scheme_unsupported` naming the scheme |
| `securityRequirements[]` / legacy `security[]` | list of scheme-name maps | the owner's `auth_scheme` must satisfy at least one requirement, and it is consulted *before* the scheme catalogue: `securitySchemes` says what the agent understands, this says what it will accept. The names within one alternative are conjoined and BrainBuddy holds one credential, so an alternative is satisfiable only when every scheme it names is of the owner's kind; a name the card never declared states nothing checkable and is dropped from the alternative. No alternative satisfiable ⇒ `a2a_auth_scheme_unsupported` naming the first scheme of the first alternative — the one the owner would have to change to. An empty list means the agent needs no credential (credential still sent) |
| `name`, `version`, `description`, `skills[]` | strings | bounded copy into `AgentCardSummary` |

Failure categories (FR-002/SC-009): transport error or timeout → `a2a_unreachable`;
HTTP 404/non-JSON/no `name`+`supportedInterfaces` → `a2a_not_an_agent`; no 1.0.x JSON-RPC
interface → `a2a_no_supported_interface` (also when the interface host fails egress);
protocol version present but outside 1.0.x → `a2a_protocol_version_unsupported`.

## Request envelope (every RPC)

```
POST {interface_url}
Content-Type: application/json        Accept: application/json
A2A-Version: 1.0                      X-Correlation-ID: <server-generated per call: uuid4 hex, or obs_<id> for a scheduled observation>
Authorization: Bearer <cred>  |  <api key header name>: <cred>
A2A-Extensions: <single-start URI>    (guaranteed-tier agents only: on the first SendMessage, every replay of it and every reply, always paired with message.extensions)
{"jsonrpc":"2.0","id":"<uuid4>","method":"<PascalCase>","params":{...camelCase, proto fields only...}}
```

`X-Correlation-ID` is minted by BrainBuddy for each outbound call (`uuid4().hex`; `obs_<id>`
for a scheduled observation) and logged under the same value on BrainBuddy's side; it is never
the inbound `X-Correlation-ID`/`X-Request-ID` a client sent to the API forwarded verbatim
(constitution Principle IV: accepted client-supplied ids are observability labels only). The
`contextId` BrainBuddy sends is always the server-assigned run id and is never derived from
any request header. Extension activation is fixed here, and this file is authoritative: a
guaranteed-tier agent sees `A2A-Extensions` **and** `message.extensions` on the very first
`SendMessage`, not only on replays, because §3–4 of the extension only oblige the agent to
record the dedup key for a request that activated it.

Every request also carries an **absolute wall-clock deadline** that `pinned_request` enforces
itself, while waiting for headers and inside its body loop (an httpx read timeout is per
chunk, so a drip-feeding agent never trips it): reply window + 15 s for a start or reply
exchange, `connector_timeout_seconds` (10 s) + 5 s for every other call (`data-model.md` §9). A breach closes the
stream and raises `EgressDeadlineExceeded` — start ⇒ delivery unconfirmed (lookup before any
resend), reply ⇒ command unconfirmed, observe ⇒ contact not refreshed, cancel ⇒
`cancel_outcome=unconfirmed`, test ⇒ `a2a_unreachable`. Start exchanges run on the exchange pool
(at most `max_exchanges_per_connection` per connection). A reply runs on the calling
request's thread while still being recorded as a durable `reply` exchange (state, kind,
deadline), because a reply is issued from a request the user is waiting on and the pool it
would queue for is the one starts saturate — and a reply is often what *resolves* one of
those held exchanges. `CancelTask` and `CreateTaskPushNotificationConfig` run on a dedicated
control pool and never wait behind exchanges; observations run on the observation pool.

Only proto-defined fields are ever sent (the SDK server rejects unknown params). Responses
must be a JSON object with `jsonrpc`, matching `id`, and exactly one of `result`/`error`;
anything else is `a2a_response_invalid` (delivery unconfirmed for `SendMessage`). A response
body over the applicable cap is `a2a_response_over_cap`: for `GetTask` it triggers the
`ListTasks` fallback below instead of failing the observation.

## Operations

| op | method | params | timeout | result handling |
|---|---|---|---|---|
| Connection test | `ListTasks` | `{pageSize:1}` (+`tenant`) | short | 2xx result ⇒ **ready**; `-32601` ⇒ retry with `GetTask {id:"brainbuddy-probe"}` expecting `-32001` ⇒ ready; HTTP 401/403 or `-32050/-32052` ⇒ `a2a_credentials_rejected`; 429/`-32051` ⇒ `a2a_rate_limited` — `status` stays `untested` (never ready) until a later successful test, `last_test_error_detail={retry_after_seconds}`, retry offered after that (FR-002, AC-037; D-01-S25 / M-01-S22) |
| Start | `SendMessage` | `{message:{messageId:"<run>:start", contextId:"<run>", role:"ROLE_USER", parts:[{text:title},{text:details}?,{text:"<label>\n<body>"}…], metadata:{"brainbuddy.task_id":…, "brainbuddy.run_id":…}, extensions:[<uri>] (guaranteed tier)}, configuration:{taskPushNotificationConfig:{url,token}?, historyLength:0}}` | `httpx.Timeout(connect=5 s, read=reply_window + 15 s)` (blocking, `returnImmediately` absent) | `result.task` ⇒ observation (Decision E), `agent_task_id` — adopted only if `task.contextId == "<run>"`, otherwise `a2a_response_invalid` and `context_id_honoured=false` on the connection; `result.message` ⇒ completed with text; `-32602` ⇒ not sent; 429 ⇒ not sent `a2a_rate_limited`; 401/403 ⇒ not sent `a2a_credentials_rejected`; timeout/5xx/transport ⇒ delivery unconfirmed |
| Probe / lookup | `ListTasks` | `{contextId:"<run>", pageSize:5, includeArtifacts:false, historyLength:0}` | short | newest task by `status.timestamp` (Hermes: first item) adopted **only if its `contextId` equals the run id** (a foreign `contextId` is ignored); empty ⇒ nothing by itself — the resend that may follow an empty lookup is a user-triggered dispatch with preconditions (`api-deltas.md`, `check-delivery`): refused unless the connection is ready, unchanged and in the verified scope of the dispatch, the manifest still present, rollout ON and the dispatch reauthentication rule satisfied; serialised per run; never from a background thread; and no resend at all when the connection has `context_id_honoured=false` |
| Observe | `GetTask` | `{id:<agent_task_id>, historyLength:0}` routinely; `historyLength:20` only when the observed state needs text (input-required question, terminal summary) | short | observation; over `a2a_task_max_response_bytes` ⇒ fall back to `ListTasks {contextId:"<run>", includeArtifacts:false, historyLength:0}` so the state is still observed and the run marks `result_availability=too_large` ("unavailable — too large to store", never **Stopped reporting**); `-32001` ⇒ agent no longer reports this run |
| Reply | `SendMessage` | `{message:{messageId:<command_id>, contextId:"<run>", taskId:<agent_task_id>, role:"ROLE_USER", parts:[{text:answer}], referenceTaskIds:[<agent_task_id>], extensions:[<uri>] (guaranteed tier), metadata:{…,"brainbuddy.command_id":…}}, configuration:{historyLength:20, taskPushNotificationConfig:{url,token}? (the same per-run config whenever the card supports push, so a successor task stays push-accelerated)}}` | `httpx.Timeout(connect=5 s, read=reply_window + 15 s)` | returned Task ⇒ command confirmed + observation; a **different** task id in the same `contextId` ⇒ task succession (below); `-32004` (terminal task, no successor) ⇒ command rejected, observation refreshed, the run shows the agent's own reason and the reply control is withdrawn; `-32001` ⇒ agent no longer reports; timeout/5xx/transport/deadline ⇒ command unconfirmed, scheduled observation resumes at the exchange deadline (Task succession, below) |
| Cancel | `CancelTask` | `{id:<agent_task_id>, metadata:{"brainbuddy.command_id":…}}` | short; control pool, never behind exchanges | Task ⇒ confirmed + observation; `-32002` ⇒ `cancel_outcome=not_cancelable`; `-32004`/`-32601` ⇒ `unsupported`; `-32001` ⇒ `task_missing`; `-32603`, HTTP 5xx, timeout or transport loss ⇒ `unconfirmed` — the cancel control stays available and a later attempt reuses the same command id (never a durable "not supported by this agent" claim) |
| Register push (adopted task) | `CreateTaskPushNotificationConfig` | `{taskId, url, token}` | short; control pool | any error ⇒ `push_registration=refused`, silent |

Parts are `text/plain`; `mediaType` omitted. The manifest lists each part verbatim; the
agent's own joining of parts is agent-defined and not asserted.

**Task succession** (product-owner decision 2026-09-03; spec FR-010, AC-028; design
D-03-S27 / M-03-S26): Hermes mints a new task for every `SendMessage` and its watchdog fails
any non-terminal task — `INPUT_REQUIRED` included — 300 s after creation, so a reply may come
back as a Task whose `id` differs from the run's `agent_task_id`. When the returned Task's
`contextId` equals the run's correlation id, BrainBuddy adopts it as the run's current agent
task, appends the timeline event **The agent continued this run in a new task** carrying the
previous and new task ids, keeps the run's single correlation id, confirms the reply command,
and continues observing the new task. A reply is **never refused** because of succession; a
returned Task with a foreign `contextId` is `a2a_response_invalid` (command unconfirmed).
Precedence against the terminal lock, because the reply exchange itself may block for the
same 300 s the watchdog counts: (a) while the reply exchange is open, scheduled observation
of the predecessor task is suspended, and a terminal observation of the predecessor that
arrives while the reply is unconfirmed or its exchange is open does not lock the run — it is
recorded as the timeline row "The previous task ended: <state>" and the run stays
blocked/reply-pending; (b) when the reply exchange returns a successor task, the succession
row supersedes the predecessor's terminal outcome; (c) when the reply itself meets a
failed/terminal task with no successor (`-32004`, or a returned Task that is the same terminal
predecessor), the run shows the agent's own reason honestly and the reply control is
withdrawn; (d) the suspension has an exit: scheduled observation resumes once the reply
exchange is `closed` or `interrupted`, or at the exchange deadline, whichever comes first —
a reply exchange that ends ambiguously (timeout, 5xx, transport loss, deadline) therefore
never leaves the run unobserved; the reply stays in the timeline as unconfirmed and the reply
control returns, for a new command id, only after a later observation shows the run blocked
again (AC-033).

**Restart recovery** (no thread survives a restart; spec FR-006, FR-010, AC-032, AC-033): a
start exchange that was still queued — never started — settles as **Not sent**
(`restarted_before_send`) and the hand-off is re-offered with the same ids; nothing is
resent. A start exchange that had started is marked interrupted and resolved by the
Probe / lookup above: adopt the task if found, else the run stays **Delivery unconfirmed**
for the user's **Check again**. A reply exchange that had started keeps its
`dispatch_state` — the *start* was delivered, and calling that delivery unconfirmed would
offer a **Check again** whose resend puts the hand-off at the agent twice — and is resolved by
lookup only: the task it finds confirms the reply when the task's `history[]` names the reply's
`messageId`, which is the agent's own record of having received it; otherwise the reply stays
unconfirmed, the run says so, and a fresh reply is still offered. No BrainBuddy `SendMessage` is ever initiated
without a user action: an exchange worker executes the send, and recovery only looks a run
up.

## Error mapping (JSON-RPC `error.code`, A2A §5.4)

| code | name | BrainBuddy effect |
|---|---|---|
| `-32001` | TaskNotFound | observe: agent no longer reports; reply/cancel: `task_missing` |
| `-32002` | TaskNotCancelable | `cancel_outcome=not_cancelable`, keep last state |
| `-32003` | PushNotificationNotSupported | `push_registration=refused` |
| `-32004` | UnsupportedOperation | reply on terminal ⇒ rejected; cancel ⇒ `unsupported` |
| `-32005` | ContentTypeNotSupported | start ⇒ not sent `a2a_content_unsupported` |
| `-32006`…`-32009` | InvalidAgentResponse, ExtendedCardNotConfigured, ExtensionSupportRequired, VersionNotSupported | start ⇒ not sent with the code; test ⇒ unsupported |
| `-32600/-32602/-32700` | invalid request/params/parse | not sent `a2a_request_rejected` |
| `-32601` | MethodNotFound | test fallback; cancel ⇒ `cancel_outcome=unsupported`; elsewhere `a2a_unsupported_operation` |
| `-32603` | Internal | ambiguous, never a capability claim: start ⇒ delivery unconfirmed; cancel ⇒ `cancel_outcome=unconfirmed` (control kept, same command id on retry); observe ⇒ contact not refreshed |
| HTTP 401/403, `-32050`, `-32052` | auth | `a2a_credentials_rejected` (test: invalid credentials) |
| HTTP 429, `-32051` | rate limit — HTTP 429, or an agent-specific code admitted through this allowlist (`-32051` is Hermes' code; A2A 1.0 defines no rate-limit error) | `a2a_rate_limited`; start ⇒ **not sent** (retryable with the same ids); test ⇒ status stays untested, `last_test_error_detail={retry_after_seconds}`, retry after that (D-01-S25 / M-01-S22) |
| HTTP 5xx, timeout, transport, deadline (`EgressDeadlineExceeded`) | — | start ⇒ delivery unconfirmed; reply ⇒ command unconfirmed (observation resumes at the deadline); cancel ⇒ `cancel_outcome=unconfirmed`; others ⇒ unreachable / contact not refreshed |
| body over cap | `a2a_response_over_cap` | `GetTask` ⇒ `ListTasks` fallback + `result_availability=too_large`; card ⇒ `a2a_not_an_agent`; other calls ⇒ `a2a_response_invalid` |

Codes are logged only from this allowlist; any other integer is logged as `other`. Only an
explicit agent answer (`-32002`, `-32004`, `-32601`) may ever produce `cancel_outcome ∈
{not_cancelable, unsupported}`.

## Observation projection summary (Decision E)

`TASK_STATE_SUBMITTED→accepted`, `WORKING→running(+status text)`, `INPUT_REQUIRED→blocked(question)`,
`AUTH_REQUIRED→blocked(fixed reason, no reply)`, `COMPLETED→completed(artifact texts + status text,
first url part as inert text the user can copy — never clickable, `result_link_interactive` stays false — other parts as placeholders)`, `FAILED→failed(status text)`,
`REJECTED→failed("Rejected by agent")`, `CANCELED→cancelled`, `UNSPECIFIED→ignored (contact only)`;
direct `Message` ⇒ `completed(text)`. Texts truncated at the 007 limits with a visible marker;
a task whose record exceeded the task read cap is observed through `ListTasks` and rendered
with the "unavailable — too large to store" marker in place of the result. On a run whose
content tier has expired the projection writes state, version and contact only, never text.

## Reference-runtime notes (verified from source)

- Hermes (`plugins/platforms/a2a/adapter.py`, commit `6327930…`): blocks `SendMessage` up to
  300 s then answers `FAILED`; creates a new task per `SendMessage` (replies create a
  successor task); `ListTasks` `contextId` filter, offset `pageToken`; `CancelTask` resolves
  the blocked exchange with `CANCELED`; status text in `status.message`, artifact only when
  completed; legacy card security shape; `A2A-Version` `1.0`/`1.0.0`/absent.
- a2a-sdk 1.1.2 server (helloworld): strict params, no `messageId` dedup, `ListTasks` with
  `contextId`, `SendMessage` returns the completed task within the request, cancel raises
  ⇒ `-32004` UnsupportedOperation, asserted by `test_agent_a2a_reference_helloworld.py`
  (T118) after a 30 s startup wait; documented fallback should the pinned sample answer
  `-32603` instead: BrainBuddy shows `cancel_outcome=unconfirmed` with the control kept
  (never a capability claim), and the assertion is corrected to the observed code with this
  note amended — never widened to accept both; no push capability.
