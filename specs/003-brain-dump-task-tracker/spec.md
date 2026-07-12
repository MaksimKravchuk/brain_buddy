# Brain Dump + TaskTrackerPort v1 specification

Status: Design contract
Decision: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)

## Goal

A user can speak a Brain Dump, see a growing chronological numbered list of provisional
task drafts, pause and resume, stop and review, explicitly accept selected tasks, and see
durable per-task RTM outcomes without silent writes or silent duplicates.

## Release boundary

The release contains one product workflow: Brain Dump to the user's configured task
tracker. The concrete MVP tracker is RTM. Weekly Review and CRT are not navigable product
flows and must not enlarge the port. A future native tracker may implement the same port.

## User contract

1. Starting creates a durable operation before recording begins.
2. Stable speech appends provisional drafts numbered in chronological display order.
3. Draft IDs are stable; display numbers may change after merge, split, or reorder.
4. Pause settles the current checkpoint and preserves the session. Resume continues it.
5. Stop seals input and enters reconciliation/review. It creates no RTM task.
6. The review shows exact titles and the fixed RTM Inbox destination. The user may
   edit/reject drafts and
   confirm one, several selected drafts, or all currently selected drafts.
7. Editing a frozen batch invalidates it. Confirmation always targets exact draft revisions.
8. Each accepted task gets an independent durable result: queued, creating, succeeded,
   failed, ambiguous, or cancelled.
9. Success shows the tracker, destination, exact title, immutable external reference, and
   read-back status. Failure and uncertainty remain visible after reload.
10. The UI never says "created" for a fake, queued, timed-out, or ambiguous result.

## Default RTM mapping

- destination: RTM Inbox by omitting `list_id`;
- `parse=0`;
- title: exact confirmed draft title;
- no other RTM fields: no `external_id`, tags, notes, URLs, `na`, priority, due/start date,
  recurrence, reminder, location, estimate, assignment, or list/project move.

The adapter persists the returned RTM `list_id`, `taskseries_id`, and `task_id`. BrainBuddy
keeps operation/draft/route linkage only in its own storage.

## API slices

Exact route naming may follow existing `/api` conventions, but the behavior must expose:

```text
POST /brain-dumps
GET  /brain-dumps/{operation_id}
GET  /brain-dumps/{operation_id}/events?after=<sequence>
PUT  /brain-dumps/{operation_id}/audio/{chunk_number}
POST /brain-dumps/{operation_id}/pause
POST /brain-dumps/{operation_id}/resume
POST /brain-dumps/{operation_id}/stop
POST /brain-dumps/{operation_id}/commands       # edit/reject/reorder/retry/cancel
POST /brain-dumps/{operation_id}/batches        # freeze selected draft revisions
POST /brain-dumps/{operation_id}/confirm        # explicit idempotent confirmation
GET  /brain-dumps/{operation_id}/results
POST /task-tracker/rtm/connect
GET  /task-tracker/status
GET  /task-routes/{route_id}/candidates          # read-only manual resolution aid
POST /task-routes/{route_id}/resolve             # link verified ref or cancel ambiguity
```

All routes are authenticated and owner-scoped. Mutations use `Idempotency-Key`, an expected
operation/route revision where applicable, and the existing correlation ID contract.
Wrong-owner references return `404`.

## Confirmation request

```text
ConfirmBrainDumpBatch:
  operation_id
  batch_id
  based_on_proposal_revision
  actions[]:
    action_id
    draft_id
    expected_draft_revision
    decision: accept | reject
    exact_title
```

The server derives one stable route ID and child idempotency key per accepted action. The
same request/key returns the same action and route results. The same key with changed
content returns `409 IDEMPOTENCY_CONFLICT`.

## Execution boundary

Organize/application code submits confirmed Execution DTOs; it never invokes RTM or writes
Execution repositories. Execution owns task routes, outbox items, dispatch attempts,
external refs, normalized snapshots, and tracker errors. The adapter accepts only the DTOs
specified by ADR-0003.

An outbox worker leases `prepared` items, writes an attempt, marks `sending`, and then calls
the adapter. If process state cannot prove the request was never sent, the next state is
`ambiguous`, with no path to another create for that route.

## Ambiguous-outcome UX

For a potentially accepted RTM create:

- query only the owner binding, Inbox, and a bounded attempt-time window to show possible
  candidates;
- use title/time only as a visual hint, never as identity or an auto-link signal;
- explain that zero candidates does not prove the task was not created;
- allow the user to link a verified complete RTM ref or cancel the unresolved local route;
- never expose retry-create for that route;
- preserve the attempt and any manually linked external reference in audit history.

## Security and privacy

RTM API key/shared secret are deployment secrets. Per-user auth tokens are referenced by
an owner-scoped binding and encrypted or secret-stored. Secrets never enter client DTOs,
operation events, logs, route/outbox records, or external references. Logs contain IDs,
state, timings, allowlisted remote codes, and retry disposition only.

RTM receives only the confirmed title. It receives no BrainBuddy provenance, notes, URLs,
raw audio, transcript, discarded drafts, source spans, confidence, model/prompt metadata,
email, or other BrainBuddy content.

## Migration contract

`BrainBuddyTaskTrackerAdapter` may later become the configured binding for new routes. It
implements the same create/get/list interface and normalized DTOs. Historical RTM refs
remain provider-qualified immutable evidence and continue to render as RTM links. No
migration rewrites or imports them by default.

## Implementation graph

1. Salvage the narrow owner-scoped Capture/Organize foundation from PR #60; remove runtime
   fake success and out-of-scope Thinking/CRT product work.
2. Implement durable Brain Dump operations, event projection, live drafts,
   pause/resume/stop, freeze, and explicit confirmation.
3. Implement Execution DTOs, route/outbox/attempt/result persistence, leases, error
   taxonomy, and a test-only fake adapter.
4. Implement RTM owner binding and signed client wrapper, then plain Inbox create/get/list.
5. Add durable ambiguous-outcome and manual-resolution UI.
6. Run deterministic suites and one controlled credentialed sandbox smoke test before
   claiming functional completion.

## Definition of done

- every scenario in `acceptance-tests.md` is automated at its specified layer;
- architecture tests prohibit Execution imports of Organize repositories/domain DTOs;
- runtime configuration cannot select a success-inventing mock in production;
- the credentialed smoke creates exactly one uniquely titled plain Inbox task, reads it
  back, verifies no metadata, and records cleanup without uncontrolled leftovers;
- result reload demonstrates durable success and external refs;
- a forced timeout-after-send demonstrates durable ambiguity without any second create;
- PR #60 is described as foundation-only until these gates pass.
