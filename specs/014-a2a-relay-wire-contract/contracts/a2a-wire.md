# Contract: the A2A operations BrainBuddy uses (outbound)

Binding: **JSON-RPC 2.0 over HTTP(S)** only (A2A v1.0 §9). BrainBuddy is a client, never a
server. Every request below passes `validate_destination` and `pinned_request`
(`backend/app/modules/agents/egress.py`): one pinned address, hostname TLS, no redirects,
body ≤ `connector_max_response_bytes`, HTTPS unless the governed private class applies.

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
| `securityRequirements[]` / legacy `security[]` | list of scheme-name maps | the owner's `auth_scheme` must satisfy at least one requirement; an empty list means the agent needs no credential (credential still sent) |
| `name`, `version`, `description`, `skills[]` | strings | bounded copy into `AgentCardSummary` |

Failure categories (FR-002/SC-009): transport error or timeout → `a2a_unreachable`;
HTTP 404/non-JSON/no `name`+`supportedInterfaces` → `a2a_not_an_agent`; no 1.0.x JSON-RPC
interface → `a2a_no_supported_interface` (also when the interface host fails egress);
protocol version present but outside 1.0.x → `a2a_protocol_version_unsupported`.

## Request envelope (every RPC)

```
POST {interface_url}
Content-Type: application/json        Accept: application/json
A2A-Version: 1.0                      X-Correlation-ID: <BrainBuddy correlation id>
Authorization: Bearer <cred>  |  <api key header name>: <cred>
A2A-Extensions: <single-start URI>    (only for guaranteed-tier agents)
{"jsonrpc":"2.0","id":"<uuid4>","method":"<PascalCase>","params":{...camelCase, proto fields only...}}
```

Only proto-defined fields are ever sent (the SDK server rejects unknown params). Responses
must be a JSON object with `jsonrpc`, matching `id`, and exactly one of `result`/`error`;
anything else is `a2a_response_invalid` (delivery unconfirmed for `SendMessage`).

## Operations

| op | method | params | timeout | result handling |
|---|---|---|---|---|
| Connection test | `ListTasks` | `{pageSize:1}` (+`tenant`) | short | 2xx result ⇒ **ready**; `-32601` ⇒ retry with `GetTask {id:"brainbuddy-probe"}` expecting `-32001` ⇒ ready; HTTP 401/403 or `-32050/-32052` ⇒ `a2a_credentials_rejected`; 429/`-32051` ⇒ `a2a_rate_limited` (not ready) |
| Start | `SendMessage` | `{message:{messageId:"<run>:start", contextId:"<run>", role:"ROLE_USER", parts:[{text:title},{text:details}?,{text:"<label>\n<body>"}…], metadata:{"brainbuddy.task_id":…, "brainbuddy.run_id":…}, extensions:[<uri>]?}, configuration:{taskPushNotificationConfig:{url,token}?, historyLength:0}}` | `reply_window + 15 s` (blocking, `returnImmediately` absent) | `result.task` ⇒ observation (Decision E), `agent_task_id`; `result.message` ⇒ completed with text; `-32602` ⇒ not sent; 429 ⇒ not sent `a2a_rate_limited`; 401/403 ⇒ not sent `a2a_credentials_rejected`; timeout/5xx/transport ⇒ delivery unconfirmed |
| Probe / lookup | `ListTasks` | `{contextId:"<run>", pageSize:5, includeArtifacts:false}` | short | newest task by `status.timestamp` (Hermes: first item) adopted; empty ⇒ nothing |
| Observe | `GetTask` | `{id:<agent_task_id>, historyLength:20}` | short | observation; `-32001` ⇒ agent no longer reports this run |
| Reply | `SendMessage` | `{message:{messageId:<command_id>, contextId:"<run>", taskId:<agent_task_id>, role:"ROLE_USER", parts:[{text:answer}], referenceTaskIds:[<agent_task_id>], metadata:{…,"brainbuddy.command_id":…}}, configuration:{historyLength:20}}` | `reply_window + 15 s` | returned Task ⇒ command confirmed + observation; a **different** task id in the same `contextId` ⇒ task succession (below); `-32004` (terminal task) ⇒ command rejected, observation refreshed; `-32001` ⇒ agent no longer reports |
| Cancel | `CancelTask` | `{id:<agent_task_id>, metadata:{"brainbuddy.command_id":…}}` | short | Task ⇒ confirmed + observation; `-32002` ⇒ `cancel_outcome=not_cancelable`; `-32004`/`-32603` ⇒ `unsupported`; `-32001` ⇒ `task_missing` |
| Register push (adopted task) | `CreateTaskPushNotificationConfig` | `{taskId, url, token}` | short | any error ⇒ `push_registration=refused`, silent |

Parts are `text/plain`; `mediaType` omitted. The manifest lists each part verbatim; the
agent's own joining of parts is agent-defined and not asserted.

**Task succession** (product-owner decision 2026-09-03): Hermes mints a new task for every
`SendMessage` and its watchdog fails an unanswered `INPUT_REQUIRED` task after 300 s, so a
reply may come back as a Task whose `id` differs from the run's `agent_task_id`. When the
returned Task's `contextId` equals the run's correlation id, BrainBuddy adopts it as the
run's current agent task, appends the timeline event "Agent continued the run in a new
task" carrying the previous and new task ids, confirms the reply command, and continues
observing the new task. A reply is **never refused** because of succession; a returned
Task with a foreign `contextId` is `a2a_response_invalid` (command unconfirmed).

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
| `-32601` | MethodNotFound | test fallback; elsewhere `a2a_unsupported_operation` |
| `-32603` | Internal | ambiguous: start ⇒ delivery unconfirmed; cancel ⇒ `unsupported` |
| HTTP 401/403, `-32050`, `-32052` | auth | `a2a_credentials_rejected` (test: invalid credentials) |
| HTTP 429, `-32051` | rate limit | `a2a_rate_limited`; start ⇒ **not sent** (retryable with the same ids) |
| HTTP 5xx, timeout, transport | — | start ⇒ delivery unconfirmed; others ⇒ unreachable |

Codes are logged only from this allowlist; any other integer is logged as `other`.

## Observation projection summary (Decision E)

`TASK_STATE_SUBMITTED→accepted`, `WORKING→running(+status text)`, `INPUT_REQUIRED→blocked(question)`,
`AUTH_REQUIRED→blocked(fixed reason, no reply)`, `COMPLETED→completed(artifact texts + status text,
first url part as inert link, other parts as placeholders)`, `FAILED→failed(status text)`,
`REJECTED→failed("Rejected by agent")`, `CANCELED→cancelled`, `UNSPECIFIED→ignored (contact only)`;
direct `Message` ⇒ `completed(text)`. Texts truncated at the 007 limits with a visible marker.

## Reference-runtime notes (verified from source)

- Hermes (`plugins/platforms/a2a/adapter.py`, commit `6327930…`): blocks `SendMessage` up to
  300 s then answers `FAILED`; creates a new task per `SendMessage` (replies create a
  successor task); `ListTasks` `contextId` filter, offset `pageToken`; `CancelTask` resolves
  the blocked exchange with `CANCELED`; status text in `status.message`, artifact only when
  completed; legacy card security shape; `A2A-Version` `1.0`/`1.0.0`/absent.
- a2a-sdk 1.1.2 server (helloworld): strict params, no `messageId` dedup, `ListTasks` with
  `contextId`, `SendMessage` returns the completed task within the request, cancel raises
  ⇒ `-32603`/`-32004` (assert in test), no push capability.
