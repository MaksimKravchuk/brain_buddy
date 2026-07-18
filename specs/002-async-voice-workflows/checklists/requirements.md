# Requirements Checklist: Multilingual Voice Brain Dump Reconciliation

**Purpose**: Verify that the materially amended async-voice specification is complete,
consistent with ADR-0002/constitution, and implementation-ready.

**Created**: 2026-07-18

**Feature**: `../spec.md`

## Product outcome and scope

- [x] CHK001 US1–US3 describe independently testable user value and all are P1 for the thin
  native Brain Dump loop.
- [x] CHK002 Required founder examples explicitly cover RU/EN code switching, original-audio
  correction, an unpunctuated run-on, and a one-task conjunction phrase.
- [x] CHK003 Progressive proposals, explicit processing, Review, and Save states are distinct.
- [x] CHK004 Weekly Review substrate compatibility is preserved without adding Weekly Review
  UX or a second engine.
- [x] CHK005 CRT, routing, external trackers, autonomous execution, inferred metadata,
  text-to-speech, brokers, and microservices are explicit non-goals.

## Contract completeness

- [x] CHK006 Fast STT, accurate STT, and text reconciliation are replaceable logical roles;
  one vendor may implement several roles without entering domain contracts.
- [x] CHK007 Accurate STT is required to process sealed original audio, not fast transcript
  text.
- [x] CHK008 Transcript versions define ordering, audio spans, generation/lane, append-only
  history, and explicit many-to-many supersession.
- [x] CHK009 Proposal patches define stable IDs, add/update/split/merge/remove/supersede/
  reorder semantics, source lineage, hidden tombstones, and structural successors.
- [x] CHK010 User changes define field-level locks, visible conflicts, explicit resolution,
  and conflict-gated freeze.
- [x] CHK011 State transitions include recording, pause, seal/drain, accurate transcription,
  reconciliation, Review, commit, error/retry, cancellation, and completion.
- [x] CHK012 API contracts define owner-scoped audio, projection, optional events, user
  patches/conflicts, freeze, confirm, and polling fallback.
- [x] CHK013 Confirmation defines deterministic child idempotency and title-only Inbox
  defaults with no canonical write before explicit Save.

## Persistence, migration, and failure behavior

- [x] CHK014 Provider runs, input hashes, leases, deadlines, retry limits, checkpoints, and
  operation recovery budgets are persisted and bounded.
- [x] CHK015 Process death, timeout-after-accept, duplicate output, and competing runner
  claims have deterministic recovery assertions.
- [x] CHK016 Chunk gaps, duplicate/conflicting chunks, offline windows, microphone loss, and
  local storage limits have visible outcomes.
- [x] CHK017 Schema-v1 terminal operations remain immutable; active v1 user edits/deletes and
  IDs import once and remain visibly provisional-only without fabricated audio accuracy.
- [x] CHK018 Compatibility aliases have a bounded migration window and additive responses.
- [x] CHK019 SQLite plus one in-process runner is justified as the minimum; no unnecessary
  infrastructure is prescribed.

## Consent, privacy, owner isolation, and observability

- [x] CHK020 Microphone permission and external-processing consent are separate and current.
- [x] CHK021 Every operation and nested reference is owner-scoped with wrong-owner `404`.
- [x] CHK022 Logs/events/analytics exclude audio, transcript/task text, vocabulary, paths,
  emails, credentials, and content fingerprints.
- [x] CHK023 Retention, consent withdrawal, immediate audio deletion, and cleanup are
  configuration-backed and retry-safe.
- [x] CHK024 UI/telemetry expose real stages, retries, fallback quality, and indeterminate
  work without fake percentages.

## Acceptance and measurable success

- [x] CHK025 Acceptance IDs are unique and cover state, upload, providers, multilingual
  semantics, events, patches, targets, confirmation, UI, undo, review, privacy, recovery,
  migration, latency, and evaluation.
- [x] CHK026 ML-01 requires exactly three tasks and preserves `BrainBuddy`/`production smoke`.
- [x] CHK027 ML-02 proves correction from original audio and retained fast history.
- [x] CHK028 ML-03 and ML-04 distinguish semantic run-on splitting from naive conjunction
  splitting.
- [x] CHK029 Safety gates require zero silent edit loss, zero pre-confirm canonical writes,
  zero inferred task metadata, and zero retry duplicates.
- [x] CHK030 Evaluation metrics include task-boundary precision/recall, exact-count accuracy,
  title cleanliness, code-switched-term accuracy, and conjunction false-split rate.
- [x] CHK031 The browser journey proves reload/relogin persistence and uses deterministic
  fakes rather than paid live providers in ordinary CI.

## Planning and delivery readiness

- [x] CHK032 `plan.md` names real current files, proposed package boundaries, ownership,
  migration, tests, rollout, and constitution checks.
- [x] CHK033 `tasks.md` is grouped by US1–US3, uses exact paths, and places failing tests before
  implementation.
- [x] CHK034 ADR-0001 modular-monolith boundaries and amended ADR-0002 operation safety
  principles remain binding.
- [x] CHK035 Spec Kit artifacts remain planning input; Hermes Kanban, independent review,
  CI, PR, deploy, and smoke gates are not bypassed.

## Notes

All requirement checks are satisfied for independent architecture review. Any implementation
change to role boundaries, state transitions, persistence ownership, confirmation payload,
or migration behavior must amend the spec/ADR/plan before code proceeds.
