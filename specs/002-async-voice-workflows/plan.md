# Implementation Plan: Multilingual Voice Brain Dump Reconciliation

**Branch**: `wt/t_58293688` | **Date**: 2026-07-18 | **Spec**: `specs/002-async-voice-workflows/spec.md`

**Input**: ADR-0002 amendment and the feature/acceptance specification in this directory.

## Summary

Replace the shipped fixed-locale browser-transcript/positional-split path with one thin,
resumable end-to-end Brain Dump slice. The browser records and uploads original audio; a
fast STT role plus text extractor shows provisional tasks; Stop runs accurate multilingual
STT from sealed audio and a lineage-aware text reconciliation pass; Review preserves user
locks/conflicts; explicit confirmation creates title-only native Inbox tasks exactly once.

Keep this inside the existing FastAPI/React modular monolith. Persist operation work and
leases in the existing owner-partitioned SQLite deployment, use deterministic provider
fakes in CI, and retain SSE as optional acceleration with GET polling as the correctness
fallback. Do not add a broker, Celery, service extraction, CRDT, external task routing, CRT,
or inferred task metadata.

## Technical Context

**Language/Version**: Python 3.11; TypeScript strict + React

**Primary Dependencies**: Existing FastAPI, Pydantic, sqlite3, React, React Query, Vite; the
first provider adapter may use an approved existing HTTP client after selection, but the
contracts and deterministic fakes do not depend on a vendor SDK.

**Storage**: Existing `backend/data/tasks.sqlite3` deployment, adding schema-v2 operation
payloads/append history and persisted provider-run leases. Raw audio remains under the
configured data root behind opaque owner-scoped media references and retention cleanup.

**Testing**: pytest/FastAPI TestClient, Vitest + Testing Library, Playwright Compose E2E,
deterministic labelled audio/text fixtures, repository restart/lease/idempotency tests,
`python3 scripts/check_spec_kit_specs.py`, and normal backend/frontend CI gates.

**Target Platform**: Responsive web app; mobile browser recording with server-side FastAPI
processing.

**Project Type**: Existing backend/frontend web application.

**Performance Goals**: ADR-0002 p95 budgets: local recording feedback <100 ms, stable fast
segment <700 ms after segment end, first provisional task <1.5 s after a semantic boundary,
visible patch <500 ms after emission, streamed fast drain <2 s, reconciled two-minute dump
<8 s and configured maximum <20 s, local confirmation acknowledgement <1 s.

**Constraints**: Explicit external-processing consent; original audio is required for new
schema-v2 accurate reconciliation; polling must restore full state; no raw content in
telemetry; bounded retries/leases; no canonical task before confirmation; no paid live
provider in ordinary CI.

**Scale/Scope**: One primary-user MVP workflow with bounded recording duration and short
working-artifact retention. Weekly Review receives shared substrate-compatible contracts
only; no Weekly Review UX expansion in this slice.

## Constitution Check

*Gate result: PASS before design and after this plan. No waiver is required.*

- **Spec workflow**: `spec.md`, `acceptance-tests.md`, this plan, requirements checklist,
  and `tasks.md` are current. ADR-0002 is the architecture source of truth.
- **Consent & Safety**: Media leaves the device only under current external-processing
  consent. Audio/transcript/task text, vocabulary, credentials, paths, and content hashes
  stay out of logs, metrics, fixtures, and PR evidence. Test fixtures are synthetic.
- **Tests**: Every behavior task starts with failing deterministic backend/frontend tests.
  Provider failure, timeout, retry, cancellation, owner isolation, idempotency, migration,
  polling, and partial recovery are explicit acceptance groups.
- **Contracts**: Schema-v2 operation, transcript version, proposal patch/conflict, provider
  port, API projection, state machine, and v1 compatibility aliases are defined in ADR-0002
  before implementation.
- **Observability**: Correlation IDs, redacted stage events, real progress labels, retry/error
  codes, lease recovery counts, and fallback quality are required; no fake percentages.
- **Mobile/resilience/performance**: Chunked local recording survives offline windows within
  limits. UI closure does not cancel. Polling and persisted leases/checkpoints recover state.
- **Delivery boundary**: These tasks are planning input. Hermes Kanban ownership, isolated
  worktrees, TDD, independent architecture/product/AI-QA review, CI, PR, merge, Fly deploy,
  and production-safe smoke remain authoritative.

## Architecture and ownership

### Application workflow package

Create `backend/app/workflows/voice_brain_dump/` as the owner of async-operation orchestration
and contracts:

```text
backend/app/workflows/voice_brain_dump/
├── __init__.py       # public workflow types/service
├── domain.py         # schema-v2 operation, runs, segment versions, patches/conflicts
├── providers.py      # FastSttPort, AccurateSttPort, TextReconcilerPort + deterministic fakes
├── repository.py     # owner-scoped payload/history, leases, media refs, v1 import
├── service.py        # commands, projections, patch validation, freeze/confirm coordination
└── runner.py         # in-process due-run scan, leases, deadlines, bounded recovery
```

This is an application-workflow boundary, not a seventh domain module. It may call the
native Task application port to create a confirmed Inbox task; it must not reach directly
into task tables or another module's repository. The existing `TaskService` gains one
idempotent title-only command for this port. The current task-module Brain Dump methods and
documents become compatibility adapters during migration and are removed only after v1
aliases/data no longer need them.

### Existing files changed by the slice

```text
backend/app/core/config.py                    # voice limits, role selection, deadlines/retention
backend/app/container.py                      # wire ports, workflow service, runner
backend/app/main.py                           # runner startup/shutdown lifecycle
backend/app/api/dependencies.py               # resolve VoiceBrainDumpService
backend/app/api/tasks.py                      # current owner-scoped route family + aliases
backend/app/schemas/tasks.py                  # request/projection contracts
backend/app/modules/tasks/domain.py            # native task source link; v1 compatibility only
backend/app/modules/tasks/repository.py        # native task child-key transaction/compat adapter
backend/app/modules/tasks/service.py           # title-only create port; remove orchestration ownership
frontend/src/api/taskTypes.ts                 # schema-v2 projection/patch/conflict types
frontend/src/api/client.ts                    # audio, poll/events, user patch, freeze/confirm APIs
frontend/src/features/brain-dump/BrainDumpRoute.tsx
frontend/src/features/brain-dump/BrainDumpRoute.test.tsx
backend/tests/test_brain_dump_operations_api.py
backend/tests/test_task_repository.py
frontend/tests/native-tasks-voice-brain-dump.compose.spec.ts
```

Add focused tests rather than growing unrelated task suites:

```text
backend/tests/test_voice_brain_dump_domain.py
backend/tests/test_voice_brain_dump_repository.py
backend/tests/test_voice_brain_dump_runner.py
backend/tests/test_voice_brain_dump_reconciliation.py
backend/tests/fixtures/voice_brain_dump/v1/manifest.json
```

Synthetic labelled audio fixtures belong under `backend/tests/fixtures/voice_brain_dump/`.
They must contain no user recording. Keep binaries minimal and version their manifest,
labels, language/code-switch terms, expected task count/boundaries, and licensing/source.

## Contracts and flow

1. `POST /api/brain-dump-operations` records consent/language hints and returns schema-v2
   `recording` projection.
2. `MediaRecorder` uploads monotonic audio chunks with capture-clock spans and content hash.
   Fast runs process contiguous acknowledged windows; text extraction emits validated
   proposal patches. Browser Web Speech can post preview segments but is labelled preview.
3. Stop posts `seal` with expected count/manifest hash. The persisted runner advances
   `sealing -> fast_processing -> accurate_transcribing -> reconciling`.
4. Accurate STT receives the sealed opaque media reference, not fast text. Accepted segment
   versions explicitly supersede covered fast/preview IDs.
5. Reconciler receives the active accurate projection, stable proposal IDs, full lineage,
   user locks, and conflicts. It returns structured add/update/split/merge/remove/supersede
   drafts. The service allocates IDs and atomically appends validated patches.
6. `awaiting_confirmation` renders Review. Open conflicts block freeze. A frozen batch pins
   one proposal revision.
7. `confirm` calls the native Task port once per selected active proposal with deterministic
   child key and title only. The Task port supplies Inbox/default fields and returns one
   stable task ID.
8. GET projection and optional ordered events expose equivalent state. Reconnect/poll never
   depends on client-held transcript/proposal state.

## Persistence and migration

- Use per-operation append collections plus a derived projection in schema-v2 payloads for
  the first slice; compare-and-set revision/lease updates remain transactional in SQLite.
- Keep raw audio separate from JSON payloads behind `media_ref`; validate owner on every
  operation, chunk, nested artifact, batch, and task source reference.
- Import active schema-v1 payloads once into preview segments, synthetic add/remove patches,
  title locks, and `provisional_only` quality. Preserve proposal IDs.
- Completed/cancelled v1 operations are read-only and never replayed.
- Keep `/transcript`, `/finish`, `/commit`, and direct proposal PATCH as additive v1 aliases
  for one compatibility window. Do not claim accurate output when original audio is absent.
- Recovery scans expired leases at startup/interval, caps attempts and operation recovery,
  and reuses successful `(operation, role, method, input_hash)` results.

## Test and evaluation strategy

- **Domain/unit**: all state transitions, transcript active projection, many-to-many
  supersession, patch preconditions, stable IDs, split/merge positions, tombstone visibility,
  lock/conflict resolution, freeze rules, and semantic fixture outputs.
- **Repository**: owner isolation, v1 import once, lease claim/race/expiry, process-restart
  recovery, timeout-after-accept, append atomicity, and deterministic child idempotency.
- **API**: chunk/seal gaps and conflicts, commands/revisions, polling/event equivalence,
  nested wrong-owner `404`, redacted envelopes, compatibility aliases, confirmation defaults.
- **Frontend**: MediaRecorder plus preview fallback, progressive stable-key list, explicit
  processing labels, polling resume, edit/delete locks, conflict UI, fallback warning, Save
  disabled until conflict-free.
- **Evaluation**: ML-01–ML-06 and versioned corpus metrics. Never use punctuation or a
  conjunction token as the splitting oracle.
- **E2E**: record -> provisional list -> stop -> processing -> accurate correction and
  split/merge -> edit/delete/conflict resolution -> explicit Save -> reload/relogin Inbox;
  use deterministic fake providers and synthetic media.

## Rollout and release

1. Land storage/contracts/provider fakes dark; schema-v1 remains default-compatible.
2. Enable schema-v2 for deterministic tests and local/preview environments.
3. Run exact-head backend/frontend/Compose E2E and labelled evaluation gates.
4. Enable configured real providers only with consent, credentials, deadlines, and budget;
   provider absence is an explicit disabled/fallback state.
5. Independent Product QA and AI-QA review the same immutable head before merge.
6. Merge through normal PR, automatic Fly deploy, main CI, and authenticated production-safe
   smoke without paid provider calls unless explicitly budgeted.

## Complexity Tracking

No constitution violation. New append history and persisted leases are the minimum needed
for restart-safe correction/idempotency. SQLite and one in-process runner are deliberately
simpler than a broker, worker service, CRDT, or distributed transaction.
