# Feature specification: asynchronous voice workflows

Status: Proposed design; product implementation is out of scope for this specification.
Architecture: [ADR-0002](../../docs/decisions/0002-async-voice-operation-substrate.md)

Release scope: [ADR-0003](../../docs/decisions/0003-brain-dump-task-tracker-port.md)
ships only the Brain Dump specialization in the next tranche. Weekly Review scenarios in
this shared-substrate specification are future compatibility requirements, not current
implementation scope.

Acceptance tests: [acceptance-tests.md](acceptance-tests.md)

## Goal

Let a user speak a brain dump or conduct a Weekly Review without blocking on one request.
Show fast provisional understanding while speech continues, reconcile it with a smarter
stage, and persist only an explicitly confirmed, idempotent batch with full provenance.

## Required user outcomes

1. The user can start, stop, cancel, leave, resume, retry, and understand current progress.
2. Stable partial transcript and provisional captures appear while recording continues.
3. The user can edit/reorder provisional work without a later model overwriting it.
4. The reconciler can propose merge, split, edit, target, route, review, or CRT actions with
   source cues, confidence, and before/after diffs.
5. Ambiguous or stale targets require resolution; title similarity never silently edits an
   existing item.
6. No canonical capture, existing-item edit, review outcome, route, or promotion is written
   before confirmation.
7. Duplicate delivery, retry, reconnect, and timeout-after-accept create no duplicate write.
8. Undo communicates and enforces its bounded scope; it never claims to reverse an already
   completed external side effect.
9. Voice-led Weekly Review uses the same operation/events/patch/confirmation substrate and
   remains resumable when its voice operation fails or is cancelled.
10. The user controls microphone permission, external processing consent, raw-audio
    deletion, and can inspect retention/provenance without sensitive text entering logs.

## Scope

In scope: operation state/projection, chunk upload, ordered events with polling fallback,
fast transcript/candidate patches, smart reconciliation, user patches, snapshot-scoped
target resolution, confirmation batches, idempotent commit, partial failure, bounded undo,
privacy/retention, and Weekly Review specialization.

Out of scope: live product implementation in this change, external tracker task editing,
automatic approval/routing/deletion/promotion, a broker, a separate Weekly Review voice
engine, arbitrary tool execution, and automatic compensation of completed external writes.

## Release gate

Implementation is releasable only when every safety/idempotency/privacy scenario in the
[acceptance test specification](acceptance-tests.md) passes, latency telemetry is produced
for all stated SLOs, and the configured confidence thresholds are backed by a versioned
labelled evaluation report.
