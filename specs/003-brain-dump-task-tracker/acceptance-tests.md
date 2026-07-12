# Brain Dump flat session + RTM Inbox export acceptance tests

Status: Normative design contract
Decision: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)
Specification: [spec.md](spec.md)

Use deterministic clocks and IDs, owner A and owner B, fake voice/text processors, a fake
Execution port, and a fake RTM client. The RTM fake must distinguish failure before send,
timeout after accept, crash during send, malformed success, and normal success.

## Session and capture

| ID | Scenario | Required assertion |
|---|---|---|
| SS-01 | open with no session | exactly one owner-scoped `open` session is created |
| SS-02 | open again | the same open session and projection return; no second session is created |
| SS-03 | owner isolation | owner B cannot read or mutate owner A's session/drafts; IDs return `404` |
| SS-04 | text capture | input belongs to the open session and zero or more new drafts append |
| SS-05 | voice capture | idempotent chunks feed the same session and new drafts append |
| SS-06 | mixed capture | voice and text drafts share one flat chronological order |
| SS-07 | reload | session revision, stable draft IDs, order, names, and states survive reload |
| SS-08 | capture after viewing/editing | more voice/text input appends without a stop/resume/review transition |
| SS-09 | duplicate capture command | the original capture result returns and no duplicate draft appends |
| SS-10 | stale capture revision | command conflicts without partial input/draft mutation |
| SS-11 | open after terminal save | a new open session is created; saved history is not resumed |

## Flat draft rules and manual controls

| ID | Scenario | Required assertion |
|---|---|---|
| DR-01 | generated drafts | every item has only a task name and stable ID in one flat ordered list |
| DR-02 | later processing | existing names/order/states are unchanged; only new drafts may append |
| DR-03 | no hierarchy/type | schema and response contain no parent, child, group, subtask, task type, or class |
| DR-04 | manual wording edit | exact user wording replaces the name and increments the draft/session revision |
| DR-05 | stale edit | conflict returns current state and does not overwrite the newer name |
| DR-06 | manual delete | draft becomes a tombstone, disappears from active list, and cannot be exported |
| DR-07 | delete replay | original deletion returns with no additional mutation |
| DR-08 | processing cannot mutate | fake processor attempts to revise/merge/split/reorder/delete are rejected/ignored |
| DR-09 | no enrichment | draft DTO has no tags, notes, URL, dates, priority, destination, recommendation, or metadata controls |
| DR-10 | edit/delete after save starts | command is rejected; frozen name and export snapshot remain unchanged |

## Save session and exact transitions

| ID | Scenario | Required assertion |
|---|---|---|
| SV-01 | save non-empty session | one save atomically freezes every non-deleted draft in stable order |
| SV-02 | save excludes deletions | deleted tombstones produce no export and no RTM call |
| SV-03 | save empty session | session becomes `saved`, zero exports exist, and RTM call count is zero |
| SV-04 | one bulk action | no selection, per-draft acceptance, confirmation, review, or destination decision is required |
| SV-05 | records before I/O | save and every ordered export exist durably before first adapter call |
| SV-06 | replay identical save | original save/export IDs and states return; no additional export or RTM call occurs |
| SV-07 | changed idempotency body | `409 IDEMPOTENCY_CONFLICT`; frozen snapshot and call counts are unchanged |
| SV-08 | capture during saving | rejected without changing session, drafts, save, or exports |
| SV-09 | all successful | every draft becomes `exported` and session/save become `saved` |
| SV-10 | sibling issue | failed/ambiguous draft does not stop later siblings; session ends `saved_with_issues` |
| SV-11 | order | status projection follows frozen list order even if workers finish out of order |
| SV-12 | restart with pending exports | only pending exports resume; terminal exports return from storage |
| SV-13 | invalid transition | any state edge not listed in spec is rejected without side effects |

## Create-only TaskTrackerPort

Run the contract suite against the test fake and RTM adapter with a fake RTM client.

| ID | Scenario | Required assertion |
|---|---|---|
| TP-01 | request DTO | adapter receives only owner ID, export ID, and frozen name |
| TP-02 | response DTO | complete provider-qualified external reference persists locally |
| TP-03 | no broad capabilities | port has no get/list/update/complete/delete/move/project/calendar/recurrence API |
| TP-04 | no destination/metadata | request cannot express list, tags, notes, URL, priority, dates, type, hierarchy, or provenance |
| TP-05 | boundary ownership | product code imports the port, not concrete RTM DTOs/client or credential storage |
| TP-06 | owner binding | owner B cannot use owner A's adapter binding or export ID |
| TP-07 | runtime fake guard | production startup cannot select a success-inventing fake adapter |
| TP-08 | replacement | a second create-only adapter can be substituted without changing Brain Dump records/API |

## RTM task-name-only mapping

| ID | Scenario | Required assertion |
|---|---|---|
| RTM-01 | credential lookup | only the export owner's server-side binding is used; secrets never enter DTOs/logs |
| RTM-02 | plain Inbox add | `tasks.add` sends exact frozen name, `parse=0`, no `list_id`, and required protocol fields only |
| RTM-03 | no optional fields | no tags, notes, URL, `external_id`, priority, dates, recurrence, reminder, estimate, location, assignee, or list/project move is sent |
| RTM-04 | local-only linkage | session/draft/capture/export IDs remain in BrainBuddy and none is copied into RTM |
| RTM-05 | complete success ref | returned list/task-series/task IDs persist before export becomes `exported` |
| RTM-06 | exact wording | exported task name equals the frozen draft byte-for-byte after normal API encoding |
| RTM-07 | input resembles metadata | dates, tags, URLs, or priority-like text are still sent only as literal name text with `parse=0` |
| RTM-08 | redaction | token, shared secret, signed URL, raw input, transcript, and task name are absent from diagnostics |

## Failure, crash, and ambiguity

| ID | Scenario | Required assertion |
|---|---|---|
| FA-01 | proven pre-send transient | bounded retry stays within the same export and eventually makes at most one sent request |
| FA-02 | terminal/exhausted pre-send | only that draft becomes `failed`; siblings continue |
| FA-03 | timeout after RTM accepts | only that draft becomes `ambiguous`; create call count remains exactly one |
| FA-04 | connection loss after send begins | affected export becomes `ambiguous`; no automatic resend exists |
| FA-05 | process crash while exporting | recovery marks unknown send ambiguous and does not call create again |
| FA-06 | malformed success | without a complete durable reference, export becomes ambiguous rather than success/retry |
| FA-07 | repeated save after ambiguity | stored ambiguity returns; ambiguous draft call count remains one; pending siblings continue |
| FA-08 | worker concurrency | leases/unique constraints allow at most one send per export |
| FA-09 | no inference | no title/time search, automatic adoption, or existing-task link/mutation occurs |
| FA-10 | honest UI | affected draft says RTM may have created it and BrainBuddy will not create it again automatically |
| FA-11 | mixed terminal states | exported, failed, and ambiguous siblings stay independent and reload accurately |
| FA-12 | local persistence conflict after response | returned complete ref is preserved/repaired without another RTM create |

## Explicit non-goal regression checks

| ID | Scenario | Required assertion |
|---|---|---|
| NG-01 | product navigation/API | no CRT, candidate, recommendation, advice, Weekly Review, or destination flow is added |
| NG-02 | draft behavior | no decomposition, subtasks, classification, AI revision, merge, split, or reorder behavior exists |
| NG-03 | planner/review | no stop, reconcile, select, accept/reject, per-task confirm, or planner outcome is required |
| NG-04 | external tasks | no existing RTM task is queried, edited, completed, deleted, linked, or treated as evidence/result |
| NG-05 | PR #60 mock | runtime mock cannot claim successful external creation |
| NG-06 | PR #60 broad scope | only conforming owner persistence, source/draft separation, revisions/idempotency, seams, and test fakes are retained |

## Credentialed RTM sandbox smoke

This opt-in release check uses a dedicated sandbox/dogfood account or an explicitly approved
account, never customer credentials. It creates at most one task per run.

1. Record a fresh run ID and one local export before any RTM call.
2. Verify the owner binding and write permission without logging secrets.
3. Send exactly one uniquely named task with `parse=0`, no `list_id`, and no optional field.
4. Persist the complete returned reference and inspect that exact task in RTM to verify Inbox,
   exact name, and absent optional metadata.
5. Replay the save/recovery path and prove the create call count remains one.
6. Record the exact reference and manual cleanup disposition. Do not bulk-delete or search-
   delete by title.
7. If the send is ambiguous, stop. Do not retry creation; report the one possible artifact
   for manual inspection.

## Release gate

The feature may be called functional only when all deterministic scenarios pass, the
credentialed smoke passes (or stops honestly on one reviewed ambiguous artifact), no
uncontrolled RTM tasks or credentials remain, and the implementation diff contains none of
the explicit non-goal behavior.
