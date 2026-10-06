# bb command contract

## Configuration/discovery/input

Global --server accepts canonical origin; --api-prefix defaults /api. Explicit flags win over BB_SERVER/BB_API_PREFIX and saved configuration. First login needs explicit server when unconfigured; released docs supply production frontend origin. HTTPS except loopback development. No credentials in flags. BB_SESSION_TOKEN is invocation-only; otherwise configured protected store.

Help/version human text offline. bb commands returns local names/descriptions; bb commands task or task update adds only scoped inputs/options/enums/examples from the same clap model. bb schema METHOD PATH fetches existing api_prefix/openapi.json and returns only that operation/referenced schemas under response bounds.

--json @- reads stdin; @FILE reads regular file; inline JSON allowed for nonsensitive business input. Max1MiB UTF-8, one JSON object for writes. Named payload fields and JSON exclusive. --revision/--key may supplement JSON; conflicts fail locally. Positive explicit revision wherever expected_revision required; explicit reusable key wherever server requires Idempotency-Key. Validate current server key grammar, generate neither implicitly. No name-to-ID or revision lookup.

--dry-run compiles method/path, query keys, body field names/types and safe revision/key metadata; redact all values/content/credentials, including query values. No credential access/HTTP or server-validation claim. No Cookie/Authorization/Set-Cookie preview.

## Named operations

| Command | Existing request |
|---|---|
| task add | POST /tasks; TaskCreateRequest/key |
| task list | GET /tasks; q/state/project_id/tag_id/priority/due filters/sort/cursor/limit |
| task get ID | GET /tasks/{id} |
| task update ID | PATCH /tasks/{id}; TaskUpdateRequest/revision/key |
| task transition ID ACTION | POST /tasks/{id}/transitions; move/complete/reopen/cancel; explicit to_state when needed, revision/key |
| project list/get/add/update/archive | Existing /projects routes and revision/key requirements |
| tag list/get/add/update/delete | Existing /tags routes; delete expected_revision query/key |
| tree list/get | Existing owner-scoped /trees routes |
| tree api METHOD PATH | Generic JSON scoped to existing /crt/ or /trees/; no invented mutation/gate bypass |
| api METHOD PATH | Explicit deployed member JSON, supplied query/body/revision/key |
| auth login/status/logout | Specialized device-auth.md |

Generic api GET/POST/PUT/PATCH/DELETE paths stay under api_prefix. Repeatable --query KEY=VALUE URL-encoded. Reject absolute URLs,//, userinfo, fragments, dot segments/backslashes/encoded separators/traversal/prefix escape. No arbitrary headers/cookies/redirects/binary upload or download. /auth/device/* reserved for specialized auth. Generic semantics remain server-owned; named shortcuts validate syntax. 204→data:null, unsupported media fails. Generic body full bounded JSON unless --fields selected; named-task projection only for task commands.

## Output

Success stdout exactly one compact JSON+newline; no routine stderr/color/spinner. Explicit login waiting/installer progress human stderr. Failure one structured JSON error stderr, no success stdout; help/version exit0 human text, parse errors JSON.

Default task fields id,title,state,revision,priority,due_date,project_id,tag_ids. --fields comma-separated documented dotted fields; preserve id/revision when present and page metadata. Malformed/unknown selectors fail (known named schema validates empty lists). --fields and --full exclusive. --full all bounded task fields. No expression language.

Task list existing items→data, page:{has_more,next_cursor}; counts_by_state only --full. limit default20/max200, server cursor opaque/preserved and never followed. Unpaginated project/tag/tree arrays truncated locally report page:{has_more:false,next_cursor:null,truncated:true}, clearly local with no continuation claim. All list modes honor limit. Body>8MiB fails without partial JSON.

Synthetic example: {"data":[{"id":"fixture-task","title":"Draft outline","state":"inbox","revision":1}],"page":{"has_more":false,"next_cursor":null}}.

## Error/exit contract

{error:{code,message,http_status?,detail?,reference_id?,retry_after_seconds?,delivery_unknown?,idempotency_key?}}. Detail retains safe conflict reason/revisions/validation field/type; removes input/ctx/password/token/cookie/provider-secret fields. Redact exact active credential/known request secrets, no raw HTML/headers/reqwest Debug. Bound error16KiB; correlation from X-Correlation-ID or reference_id. Retry-After numeric seconds or bounded HTTP-date.

| Exit | Meaning |
|---|---|
| 0 | Success/help/version |
| 2 | Invalid input/400/422/other4xx |
| 3 | Authentication required401 |
| 4 | Forbidden403 |
| 5 | Not found404/capability unavailable |
| 6 | Conflict409 |
| 7 | Rate limited429 |
| 8 | Transport/timeout; writes include delivery_unknown |
| 9 | Server5xx/protocol/oversized response |
| 10 | Credential store unavailable/local credential failure |
| 11 | Explicit authorization denied/expired/consumed |
| 130 | Cancellation |

Special device outcomes map by code before status. No business retries; auth polling only explicit repeated protocol. Writes interrupted after dispatch remain uncertain; no invented success.
