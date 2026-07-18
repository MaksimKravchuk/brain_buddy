# Feature specification: asynchronous voice workflows

Status: Proposed design; product implementation is out of scope for this specification.
Architecture: [ADR-0002](../../docs/decisions/0002-async-voice-operation-substrate.md)
Acceptance tests: [acceptance-tests.md](acceptance-tests.md)

## Goal

Let a user speak a brain dump or conduct a Weekly Review without blocking on one request.
Persist the original audio, show fast provisional understanding while speech continues,
retranscribe sealed audio with an accurate multilingual lane, reconcile versioned text and
proposal lineage, and persist only an explicitly confirmed, idempotent batch with full
provenance.

## User stories

### US1 — See useful provisional tasks while speaking (P1)

As a user giving a long natural brain dump, I see a growing numbered list of provisional
tasks without pausing between thoughts. A mixed Russian/English sentence preserves product
and technical terms. Independent acceptance: the ML-01 fixture shows three provisional
tasks while recording and no native task exists yet.

### US2 — Review accurate corrections without losing my edits (P1)

As a user who stops recording, I see explicit processing before Review while the original
audio is retranscribed accurately and task boundaries are reconciled. Corrections can
update, split, merge, remove, or supersede proposals with visible lineage. If I edited or
deleted a proposal while speaking, the model cannot silently reverse me. Independent
acceptance: ML-02 corrects `brain body` to `BrainBuddy` from audio, ML-03 splits a run-on,
ML-04 keeps one conjunction task, and ML-06 exposes rather than applies a lock conflict.

### US3 — Resume safely and save exactly once (P1)

As a user, I can leave/reopen, retry a bounded failure, inspect whether output is accurate
or provisional-only, and explicitly Save the active Review list. Independent acceptance:
polling alone restores the operation, and repeated Save creates exactly one title-only
native Inbox task per selected proposal with no inferred metadata.

## Required user outcomes

1. The user can start, stop, cancel, leave, resume, retry, and understand current progress.
2. Stable partial transcript and numbered provisional captures appear while recording
   continues; fast, accurate, and text-reconciler roles remain replaceable.
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
11. Mixed RU/EN speech preserves product/technical terms, accurate STT can correct fast
    words from original audio, and semantic task boundaries do not split on conjunctions
    alone.
12. Native Brain Dump confirmation creates only title-only Inbox tasks, exactly once, with
    no inferred tags, project, priority, details, or dates.

## Scope

In scope: operation state/projection, original-audio chunk upload, replaceable fast/accurate
STT and text-reconciler ports, versioned time-aligned transcript supersession, ordered events
with polling fallback, stable proposal IDs and lineage patches, user field locks/conflicts,
snapshot-scoped target resolution, confirmation batches, idempotent commit, persisted
bounded recovery, migration, privacy/retention, and Weekly Review substrate compatibility.

Out of scope: live product implementation in this change, external tracker task editing,
automatic approval/routing/deletion/promotion, a broker, a separate Weekly Review voice
engine, arbitrary tool execution, and automatic compensation of completed external writes.

## Functional requirements

- **FR-001** The operation MUST persist the original recording as chunked, owner-scoped
  working media before accurate reconciliation can start.
- **FR-002** Fast STT, accurate STT, and text reconciliation MUST be replaceable logical
  roles; ordinary tests MUST use deterministic fakes.
- **FR-003** Transcript history MUST be ordered, time-aligned, append-only, versioned, and
  explicitly superseded; no mutable text blob may be authoritative.
- **FR-004** Proposals MUST have stable IDs and append-only add/update/split/merge/remove/
  supersede/reorder patches with source spans and auditable hidden predecessors.
- **FR-005** User changes MUST lock only changed fields. A conflicting model suggestion
  MUST remain visible and unresolved until an explicit user decision.
- **FR-006** Stop MUST run seal, accurate transcription from original audio, and text
  reconciliation before successful Review; fallback quality MUST be visible.
- **FR-007** Operation state, progress, retries, leases/checkpoints, and results MUST survive
  UI closure and process restart, with polling sufficient for correctness.
- **FR-008** Every operation/artifact lookup MUST be owner-isolated; telemetry/events MUST
  be redacted; processing and retention MUST honor consent.
- **FR-009** Only explicit confirmation of a frozen conflict-free revision may create native
  Inbox tasks. Confirmation MUST be exactly-once and MUST infer no metadata.
- **FR-010** Schema-v1 terminal operations MUST remain read-only; active operations without
  source audio MUST be visibly provisional-only and MUST NOT claim accurate correction.

## Edge cases and failure behavior

- Missing chunks block seal with exact resumable gaps; duplicate chunks/results are
  idempotent and conflicting chunk hashes fail visibly.
- Fast failure does not stop recording; accurate failure preserves audio and proposals for
  bounded retry; reconciler failure preserves accurate text and user work.
- A user edit racing model output either rebases disjoint changes or creates a conflict—no
  last-write-wins overwrite.
- A process dying under a lease resumes after lease expiry without duplicate versions,
  patches, or tasks; exhausted recovery cannot hot-loop.
- Consent withdrawal stops future upload/provider calls and schedules unconfirmed working
  artifacts for deletion.

## Privacy and observability impact

External processing remains opt-in by provider category. Logs, metrics, analytics, and
operation events contain only pseudonymous IDs, stage names, timings, counts, coarse bands,
and error codes—not audio, transcripts, task text, vocabulary, paths, hashes usable as
content fingerprints, emails, or credentials. UI progress names real stages and uses
indeterminate progress when totals are unknown.

## Success criteria

- **SC-001** ML-01 through ML-06 pass against a versioned labelled corpus, including exact
  three-task and one-task founder examples.
- **SC-002** Evaluation reports task-boundary precision/recall, exact-count accuracy, title
  cleanliness, code-switched-term accuracy, and conjunction false-split rate by language
  and provider/model version.
- **SC-003** Automated tests show zero silent user-edit loss, zero canonical writes before
  confirmation, zero inferred task metadata, and zero duplicate tasks after retries.
- **SC-004** The browser journey records, shows provisional tasks, processes accurate audio,
  reconciles, resolves edits/deletions/conflicts, saves, and shows persisted Inbox tasks
  after reload/relogin without a paid-provider dependency in CI.
- **SC-005** p95 stage telemetry meets the budgets in ADR-0002 or visibly reports a labelled
  fallback without weakening safety invariants.

## Release gate

Implementation is releasable only when every safety/idempotency/privacy scenario in the
[acceptance test specification](acceptance-tests.md) passes, latency telemetry is produced
for all stated SLOs, and the configured confidence thresholds are backed by a versioned
labelled evaluation report.
