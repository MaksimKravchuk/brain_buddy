# Brain Dump + TaskTrackerPort v1 acceptance tests

Status: Normative design contract
Decision: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)
Specification: [spec.md](spec.md)

Use deterministic clocks/IDs, owner A and owner B, fake audio chunks, a fake transcript
stage, a fake reconciler, a fake Execution port, and a fake RTM client. The fake RTM client
must separately simulate failure before send, timeout after accept, delayed visibility,
multiple marker matches, note failure, token expiry, and malformed responses.

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
| CF-10 | partial batch failure | successful sibling remains; failed/ambiguous sibling is explicit and independently retryable/resolvable |

## TaskTrackerPort contract

Run the same contract suite against the test fake and RTM adapter with a fake RTM client.

| ID | Scenario | Required assertion |
|---|---|---|
| TP-01 | create DTO | adapter receives only Execution DTOs, never RouteRecord/CaptureItem/transcript/audio |
| TP-02 | exact title | created/read-back snapshot preserves the confirmed title |
| TP-03 | default destination | Inbox is used; no generic/default project is invented |
| TP-04 | unsupported explicit field | fails locally and visibly; field is not silently dropped |
| TP-05 | get by ref | complete provider-qualified ref returns a normalized snapshot |
| TP-06 | bounded list | owner/destination/window/max are enforced; max over adapter cap is rejected/clamped explicitly |
| TP-07 | stable ref | stored ref includes adapter/account/container/task series/task IDs and never changes after success |
| TP-08 | owner isolation | owner B cannot create/read/list/reconcile with owner A binding or refs |
| TP-09 | no generic mutations | port has no edit/complete/delete/list-management/calendar/recurrence API |
| TP-10 | architecture | Execution imports no Organize repository/domain DTO; Organize imports no concrete adapter |
| TP-11 | runtime fake guard | production startup refuses a success-inventing mock/fake adapter |

## RTM mapping with fake client

| ID | Scenario | Required assertion |
|---|---|---|
| RTM-01 | owner credential lookup | call uses only owner A binding; token is absent from logs/events/persistence DTOs |
| RTM-02 | expired/revoked token | maps RTM auth failure to `AUTH_REQUIRED/user_action`; no create retry |
| RTM-03 | create Inbox task | `tasks.add` omits `list_id`, sets `parse=0`, exact title, and `external_id=bb:v1:<route_id>` |
| RTM-04 | safe defaults | add/note calls contain no `na`, tags, priority, due/start, recurrence, reminder, location, estimate, assignment, or invented list |
| RTM-05 | explicitly selected regular list | validated list ref is passed; stale/smart/read-only destination maps to typed error |
| RTM-06 | create response | returned list/taskseries/task/transaction refs persist before note call |
| RTM-07 | provenance note | fixed note has operation/draft/route/marker and no transcript/audio/model/email/credentials |
| RTM-08 | note timeout/failure | task remains succeeded with stored ref and visible note-pending warning; task create is not repeated |
| RTM-09 | read-back | get verifies normalized title/destination/state before final success |
| RTM-10 | remote error map | official auth, permission, service, invalid list/name, rate-limit if exposed, and protocol failures map to taxonomy |
| RTM-11 | redacted diagnostics | exception/task text, signed URL, API key, shared secret, auth token, and note body are absent from logs |
| RTM-12 | optional fields disabled in v1 UI | no confirmation generated by the UI includes tags, dates, or priority |

## Outbox, crash, retry, and reconciliation

| ID | Scenario | Required assertion |
|---|---|---|
| OB-01 | persisted before I/O | route, outbox, and started attempt exist before first fake-client call |
| OB-02 | worker concurrency | lease/unique constraints allow one create call for concurrent workers |
| OB-03 | crash before send | attempt is safely retryable and one eventual task is created |
| OB-04 | timeout after accept | state becomes `reconciliation_required`; automatic create call count remains one |
| OB-05 | exact one marker match | reconciliation adopts/read-backs it and records `resolution=reconciled` |
| OB-06 | delayed visibility | bounded reconciliation retries reads only; it never issues another create |
| OB-07 | no marker match | after bounded reads outcome is `ambiguous`, not `failed` or safe-retry |
| OB-08 | multiple marker matches | outcome is `ambiguous`; no task is silently selected or deleted |
| OB-09 | title/time candidate only | candidate may display but cannot auto-link without exact marker/user choice |
| OB-10 | manual link | user-selected provider-qualified ref is verified, stored, and audited as `user_linked` |
| OB-11 | checked-absent retry | explicit attestation creates a new attempt on same route; audit preserves uncertainty |
| OB-12 | repeated worker after success | stored result returns and no adapter call occurs |
| OB-13 | changed request hash | retry is refused and returns to confirmation; old route/ref remains immutable |
| OB-14 | local completion conflict | external success stays visible; reconciliation advances local state instead of swallowing conflict |
| OB-15 | restart recovery | scanning prepared/sending items yields safe retry or reconcile-first based on durable send state |

## Durable result UX

| ID | Scenario | Required assertion |
|---|---|---|
| UX-01 | queued/creating | UI does not use created/success language and shows per-task progress |
| UX-02 | success | exact title, RTM Inbox/list, external link/ref, and verified state survive reload |
| UX-03 | typed failure | actionable message distinguishes reconnect, retry-later, edit destination, and terminal rejection |
| UX-04 | ambiguous | UI says RTM may have created it and offers inspect/link/cancel/checked-absent retry |
| UX-05 | mixed batch | each draft keeps its own result; no aggregate banner hides uncertainty |
| UX-06 | historical ref after adapter switch | old RTM result still renders as immutable RTM evidence |

## Credentialed RTM sandbox/dogfood smoke

This test is opt-in, excluded from normal CI, and guarded by a dedicated sandbox/dogfood
account or explicitly approved account. It must not use production customer credentials.
It creates at most one task per run.

1. Generate a unique title such as `BrainBuddy smoke <run-id>` and one deterministic route
   marker. Record the intended run in a local smoke manifest before calling RTM.
2. Confirm the account binding with `auth.checkToken` and write permission.
3. Create exactly one task with no `list_id`, `parse=0`, no optional metadata, and the
   marker. If a prior task with that marker is found, adopt it instead of creating another.
4. Read it back by the complete external ref and verify title, Inbox destination, no
   priority/due/tags, and the fixed provenance note.
5. Run bounded reconciliation and verify it resolves to that same single ref without a
   second create.
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
| P60-06 | conflict handling | successful external create plus local conflict remains a visible partial result and reconciles |

## Release gate

The feature may be called functional only when:

- lifecycle, confirmation, port, RTM fake-client, outbox/reconciliation, owner/privacy, and
  durable-result suites pass;
- architecture/import and runtime fake guards pass;
- the controlled credentialed smoke passes or produces a reviewed, resolved ambiguous
  outcome without duplicates;
- no uncontrolled RTM tasks or credentials remain from testing;
- PR documentation states exactly which PR #60 foundation was retained and which mock or
  broad-scope behavior was removed.
