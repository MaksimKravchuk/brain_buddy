# Brain Dump + TaskTrackerPort v1 acceptance tests

Status: Normative design contract
Decision: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)
Specification: [spec.md](spec.md)

Use deterministic clocks/IDs, owner A and owner B, fake audio chunks, a fake transcript
stage, a fake reconciler, a fake Execution port, and a fake RTM client. The fake RTM client
must separately simulate failure before send, timeout after accept, delayed visibility,
similar title/time candidates, token expiry, and malformed responses.

## Brain Dump lifecycle

| ID | Scenario | Required assertion |
|---|---|---|
| BD-01 | create session | durable operation starts in `recording`; no external route/task exists |
| BD-02 | stable speech | chronological numbered provisional drafts append with stable IDs and segment lineage |
| BD-03 | merge/split/reorder | visible numbers update; confirmations and edits continue to address stable draft IDs |
| BD-04 | pause | stable input drains/checkpoints; recording stops; proposals remain unconfirmed and no RTM call occurs |
| BD-05 | resume | same operation resumes with prior events, edits, lineage, and drafts intact |
| BD-06 | reload while recording/paused | projection and event cursor restore the same user-visible state |
| BD-07 | stop | input seals, reconciliation runs, review appears, and RTM fake has zero calls |
| BD-08 | resume after stop | rejected without changing operation revision or sealed input |
| BD-09 | cancel before confirmation | reaches `cancelled`; no route/outbox/external task exists |
| BD-10 | user edit wins | later model patches do not overwrite edited fields |
| BD-11 | low confidence | draft is marked for clarification and cannot infer destination metadata |
| BD-12 | out-of-order/duplicate event | client converges by sequence or projection refetch and applies each event once |

## Confirmation and no-silent-write

| ID | Scenario | Required assertion |
|---|---|---|
| CF-01 | model proposes tasks | no canonical route/outbox or tracker call before explicit confirmation |
| CF-02 | accept one draft | exactly one route/outbox item is persisted with the exact frozen title/destination |
| CF-03 | select batch subset | only selected accepted drafts get routes; rejected/unselected drafts do not |
| CF-04 | confirm all selected | one durable per-action result exists in batch order |
| CF-05 | edit frozen draft | batch becomes superseded and confirmation is rejected until refrozen |
| CF-06 | stale draft revision | returns conflict with refreshed review; no tracker call |
| CF-07 | repeat same confirmation | original route/result IDs return; writes and tracker calls remain one |
| CF-08 | reuse key with changed body | returns `409 IDEMPOTENCY_CONFLICT`; no extra route/task |
| CF-09 | close during commit | operation continues; reload shows actual per-task states, not blanket success |
| CF-10 | partial batch failure | successful sibling remains; a proven pre-send failure may retry, while an ambiguous sibling is resolution-only |

## TaskTrackerPort contract

Run the same contract suite against the test fake and RTM adapter with a fake RTM client.

| ID | Scenario | Required assertion |
|---|---|---|
| TP-01 | create DTO | adapter receives only Execution DTOs, never RouteRecord/CaptureItem/transcript/audio |
| TP-02 | exact title | created/read-back snapshot preserves the confirmed title |
| TP-03 | default destination | Inbox is used; no generic/default project is invented |
| TP-04 | metadata boundary | create/confirmation DTOs cannot express optional tracker metadata |
| TP-05 | get by ref | complete provider-qualified ref returns a normalized snapshot |
| TP-06 | bounded list | owner/Inbox/window/max are enforced; max over adapter cap is rejected/clamped explicitly |
| TP-07 | stable ref | stored ref includes adapter/account/container/task series/task IDs and never changes after success |
| TP-08 | owner isolation | owner B cannot create/read/list/resolve with owner A binding or refs |
| TP-09 | no generic mutations | port has no edit/complete/delete/list-management/calendar/recurrence API |
| TP-10 | architecture | Execution imports no Organize repository/domain DTO; Organize imports no concrete adapter |
| TP-11 | runtime fake guard | production startup refuses a success-inventing mock/fake adapter |

## RTM mapping with fake client

| ID | Scenario | Required assertion |
|---|---|---|
| RTM-01 | owner credential lookup | call uses only owner A binding; token is absent from logs/events/persistence DTOs |
| RTM-02 | expired/revoked token | maps RTM auth failure to `AUTH_REQUIRED/user_action`; no create retry |
| RTM-03 | create plain Inbox task | `tasks.add` sends exact name plus required RTM protocol fields only, omits `list_id`, and sets `parse=0` |
| RTM-04 | untouched task | call has no `external_id`, tags, notes, URL, `na`, priority, due/start, recurrence, reminder, location, estimate, assignment, or list/project move |
| RTM-05 | fixed destination | Brain Dump cannot request a selected regular list or any destination other than Inbox |
| RTM-06 | create response | returned list/taskseries/task/transaction refs persist before success is reported |
| RTM-07 | local-only provenance | operation/draft/route linkage persists in BrainBuddy and none is sent to RTM |
| RTM-08 | read-back | get verifies normalized title/Inbox/state before final success |
| RTM-09 | remote error map | official auth, permission, service, invalid name, rate-limit if exposed, and protocol failures map to taxonomy |
| RTM-10 | redacted diagnostics | exception/task text, signed URL, API key, shared secret, and auth token are absent from logs |
| RTM-11 | no metadata controls | confirmation and port DTOs cannot express RTM tags, notes, URLs, dates, priority, or list movement |

## Outbox, crash, retry, and ambiguity resolution

| ID | Scenario | Required assertion |
|---|---|---|
| OB-01 | persisted before I/O | route, outbox, and started attempt exist before first fake-client call |
| OB-02 | worker concurrency | lease/unique constraints allow one create call for concurrent workers |
| OB-03 | crash before send | attempt is safely retryable and one eventual task is created |
| OB-04 | timeout after accept | state becomes `ambiguous`; all automatic and user-triggered create call counts remain one |
| OB-05 | delayed visibility | bounded Inbox reads may refresh candidates; they never issue another create or auto-adopt |
| OB-06 | zero candidates | outcome remains `ambiguous`; absence is not inferred and retry-create is unavailable |
| OB-07 | one title/time candidate | candidate may display but cannot auto-link without explicit verified user choice |
| OB-08 | multiple title/time candidates | outcome remains `ambiguous`; no task is silently selected or deleted |
| OB-09 | manual link | user-selected provider-qualified ref is read back, stored, and audited as `user_linked` |
| OB-10 | cancel ambiguity | local route records cancellation while preserving the unknown attempt; no RTM mutation occurs |
| OB-11 | repeated worker after success | stored result returns and no adapter call occurs |
| OB-12 | changed request hash | reuse is refused and old route/ref remains immutable |
| OB-13 | local completion conflict | external success stays visible; local state repair does not issue another create |
| OB-14 | restart recovery | prepared items may safely send; any item that reached sending becomes durable ambiguity with no create retry |

## Durable result UX

| ID | Scenario | Required assertion |
|---|---|---|
| UX-01 | queued/creating | UI does not use created/success language and shows per-task progress |
| UX-02 | success | exact title, RTM Inbox/list, external link/ref, and verified state survive reload |
| UX-03 | typed failure | actionable message distinguishes reconnect, safe retry-before-send, and terminal rejection |
| UX-04 | ambiguous | UI says RTM may have created it and offers inspect/link/cancel, never retry-create |
| UX-05 | mixed batch | each draft keeps its own result; no aggregate banner hides uncertainty |
| UX-06 | historical ref after adapter switch | old RTM result still renders as immutable RTM evidence |

## Credentialed RTM sandbox/dogfood smoke

This test is opt-in, excluded from normal CI, and guarded by a dedicated sandbox/dogfood
account or explicitly approved account. It must not use production customer credentials.
It creates at most one task per run.

1. Generate a unique title such as `BrainBuddy smoke <run-id>` and record the intended run
   and local route in a local smoke manifest before calling RTM.
2. Confirm the account binding with `auth.checkToken` and write permission.
3. Before creating, require a fresh run ID whose manifest has no started attempt. Create
   exactly one task with no `list_id`, `parse=0`, and no optional metadata. Once the attempt
   is marked started, the harness must never call create again for that run.
4. Read it back by the complete external ref and verify title, Inbox destination, no
   external ID/note/URL/tags/priority/due/start date or other metadata.
5. Verify the local route links to that ref and that a second invocation returns the stored
   outcome without another create.
6. Record the task permalink/ref and smoke outcome. Cleanup is controlled: if the test
   binding has delete permission and an explicit cleanup flag, delete/undo only that exact
   ref and verify it; otherwise mark/complete it manually in the sandbox and record the
   remaining artifact. Never bulk-delete or search-delete by title.
7. On timeout or ambiguity, stop creation immediately and report the one possible artifact
   for human inspection. A failed smoke must not retry task creation automatically.

Release evidence must include the smoke run ID, local route ID, exactly one external ref
(or an explicit ambiguous possible ref), read-back assertions, cleanup disposition, and
redacted logs. It must not include credentials or signed request URLs.

## PR #60 regression gates

| ID | Scenario | Required assertion |
|---|---|---|
| P60-01 | mock route endpoint | cannot report invented `succeeded`/external refs in a production configuration |
| P60-02 | one-shot voice request | functional MVP uses durable operation/projection; synchronous mock path is test-only or removed |
| P60-03 | broad scope | Weekly Review/Thinking/CRT implementation is absent from this tranche's merge diff |
| P60-04 | boundary | TaskTrackerPort no longer consumes Organize RouteRecord or returns internal DispatchAttempt |
| P60-05 | error handling | generic exception does not become blindly retryable `ADAPTER_ERROR` after possible remote accept |
| P60-06 | conflict handling | successful external create plus local conflict remains visible while local state is repaired without another create |

## Release gate

The feature may be called functional only when:

- lifecycle, confirmation, port, RTM fake-client, outbox/ambiguity-resolution, owner/privacy, and
  durable-result suites pass;
- architecture/import and runtime fake guards pass;
- the controlled credentialed smoke passes or produces a reviewed, resolved ambiguous
  outcome without duplicates;
- no uncontrolled RTM tasks or credentials remain from testing;
- PR documentation states exactly which PR #60 foundation was retained and which mock or
  broad-scope behavior was removed.
