# Implementation Plan: Stable Multilingual Voice Brain Dump

**Branch**: `005-multilingual-voice-brain-dump` | **Date**: 2026-07-29 | **Spec**:
`specs/005-multilingual-voice-brain-dump/spec.md`

**Input**: Feature specification from `specs/005-multilingual-voice-brain-dump/spec.md`
plus the live-verification evidence recorded there (reference RU/EN corpus, real
4-minute recording, fail-closed consent probes).

**Note**: This is a retroactive plan. It describes the architecture the delivered
implementation already satisfies (verified live 2026-07-29) as the plan that was
executed, and calls out the single open follow-up lane (FR-016 grounding
tolerance) as remaining work. It does not introduce new architecture; where it
states a decision, the decision is already in `main`.

## Summary

Stabilize the ADR-0002 `voice_brain_dump` operation so a real, multi-minute,
code-switched Russian/English recording becomes individually reviewable,
correctly split, language-faithful task proposals with full transcript
provenance — where the prior pipeline failed closed and produced zero committed
tasks. The work is four cooperating changes inside the existing operation
substrate, adding no new persistence store and no new domain module:

1. **Multilingual transcription** — a Deepgram accurate-STT adapter
   (`nova-3`) that emits per-utterance `TranscriptHypothesis` segments and does
   not force a single language; the OpenAI accurate-STT adapter is hardened to
   the same fail-closed contract (multi-minute timeout, terminal quota
   classification, single-hint pinning with zero/multi-hint auto-detect).
2. **Semantic reconciliation that grounds without over-rejecting** — a
   `gpt-4o` strict-structured-output reconciler (`brain-dump-reconciler-v2`
   prompt: language-lock, segment-boundary, accounting, conciseness) with
   morphology-tolerant grounding and per-operation skip of a single
   unverifiable proposal, preserving every anti-hallucination guarantee.
3. **Multi-vendor consent** — the operation consent record carries an explicit
   named `providers` list; every pipeline stage checks its own vendor against
   that set and fails closed before audio leaves the device; the recording UI
   discovers the real configured vendor names from a new
   `GET /api/brain-dump-providers` endpoint.
4. **Test hermeticity** — the backend test environment scrubs real
   provider credentials so a developer `.env` cannot change deterministic
   test-provider selection.

Everything above is delivered. FR-016 (multi-clause modifier grounding,
self-correction tolerance, garbled-proper-noun tolerance) is the one remaining
lane; until it lands, those proposal shapes fail closed rather than guess.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5 / React 18 (frontend).

**Primary Dependencies**: FastAPI, Pydantic v2, `httpx` (provider clients),
OpenAI Chat Completions (`gpt-4o` reconciler, `gpt-4o-mini-transcribe`
STT fallback), Deepgram `nova-3` (accurate STT); frontend React Query + Zustand.

**Storage**: No new store. The `AsyncOperation` and its append-only
segment/patch/proposal/provider-run records persist through the existing
owner-partitioned SQLite payload used by `voice_brain_dump`
(`backend/app/workflows/voice_brain_dump/repository.py`); canonical Inbox tasks
persist through the Tasks module (`tasks.sqlite3`) via `TaskPort`.

**Testing**: pytest + FastAPI `TestClient` (backend), Vitest + Testing Library
(frontend), plus a real-audio evaluation harness
(`backend/app/workflows/voice_brain_dump/evaluation.py`) reported separately from
unit suites per the ADR-0002 STT/extraction separation.

**Target Platform**: Linux server (Fly.io private backend + proxy frontend);
mobile-first browser capture.

**Project Type**: Web application (FastAPI backend + React frontend) — the
ADR-0001 modular monolith.

**Performance Goals**: End-to-end processing of a 4-minute recording within
2 minutes of sealing (SC-007; measured ~30 s live). Accurate-STT stage tolerates
multi-minute provider latency (180 s adapter timeout) up to the 30-minute
recording cap.

**Constraints**: Consent-gated, fail-closed before any upload; no raw audio,
transcript text, credentials, paths, or content fingerprints in logs / metrics /
events / committed fixtures; idempotent commit under replay; anti-hallucination
grounding never weakened to raise yield.

**Scale/Scope**: Single dogfooding founder; one operation at a time; reference
corpus ~50 utterances / ~30 actionable cold-start creations.

## Constitution Check

*GATE: satisfied by the delivered implementation; re-checked against the shipped
code for this retroactive plan.*

- **Spec workflow**: `spec.md` and `checklists/requirements.md` are current and
  reflect the live-verified behavior; this plan follows them. Clarification is
  not open — the spec has no `[NEEDS CLARIFICATION]` markers. Remaining scope
  (FR-016) is explicitly bounded in the spec's Out of Scope and carried as one
  open lane here.
- **Consent & Safety (Principle I)**: External processing requires current
  consent that names *every* configured vendor (`consent.providers`), and each
  stage re-verifies its own vendor before uploading (fail-closed
  `CONSENT_PROVIDER_NOT_ALLOWED`). No-consent recordings stay on-device
  provisional only. Provisional model output stays in the operation workspace
  until explicit confirmation applies frozen title-only actions through
  `TaskPort` (ADR-0002 contract preserved). Raw audio/transcript/credentials/
  paths/fingerprints stay out of logs, metrics, events, and fixtures; the test
  env scrubs `OPENAI_API_KEY`/`DEEPGRAM_API_KEY` so real keys and the reference
  recording never enter CI.
- **Tests (Principle II)**: Behavior changes shipped with failing-then-passing
  backend pytest (adapter contracts, grounding accept/reject matrix, per-op
  skip, consent-mismatch fail-closed, hermeticity) and frontend Vitest
  (provider discovery, consent payload). Edge cases cover invalid/oversized/
  malformed provider responses, timeouts, quota exhaustion, consent denial,
  idempotent replay, and partial failure. Full suites: 875 backend / 443
  frontend green with the feature active (SC-008).
- **Contracts (Principle III / ADR-0001, ADR-0002)**: The consent
  `providers: list[str]` field and the `GET /api/brain-dump-providers`
  discovery endpoint are additive; the legacy single-vendor `provider` consent
  field remains accepted for backward compatibility during migration. Provider
  selection stays configuration/DI wiring (`container.py`, `config.py`), never a
  stored vendor enum or a branch in domain logic. `TaskPort` remains the only
  path to canonical task creation; the reconciler emits proposal patches only.
  New allowlisted provider error codes extend, not replace, the existing
  envelope.
- **Observability (Principle IV)**: Every response keeps `X-Correlation-ID`;
  provider runs record role, status, coarse cost accounting, stage, and an
  allowlisted `error_code` — never provider payloads or user text. Terminal vs.
  retryable classification is explicit and surfaced as an actionable code.
- **Mobile/resilience/performance (Principle V)**: Capture/seal/resume tolerate
  the multi-minute accurate-STT stage; a crash between transcription and
  reconciliation resumes from the persisted accurate generation without paying
  for transcription twice (checkpoint reuse). Consent withdrawal, chunk hash
  mismatch, stale-revision commands, and duplicate replays keep their
  fail-closed / idempotent semantics. This feature is squarely on the primary
  voice-capture loop and does not touch the CRT canvas.
- **Delivery boundary**: This plan and `tasks.md` are planning input only.
  Hermes Kanban owns implementation ownership, isolated worktrees, TDD, review,
  CI, PR, and Fly release gates. The FR-016 lane is dispatched through Kanban,
  not executed here.

## Project Structure

### Documentation (this feature)

```text
specs/005-multilingual-voice-brain-dump/
├── spec.md                     # what/why + live-verification evidence
├── checklists/requirements.md  # spec quality checklist
├── plan.md                     # this file
├── tasks.md                    # logical tasks by user story + FR-016 lane
└── hermes-handoff.json         # validated Kanban handoff
```

### Source Code (delivered paths)

```text
backend/app/workflows/voice_brain_dump/
├── domain.py            # TranscriptHypothesis; consent.providers list; segment build
├── service.py           # multi-segment persistence, full-list reconciler feed,
│                        #   resume-path rebuild, multi-provider consent guards,
│                        #   STT_PROVIDER_INVALID_RESPONSE allowlisting
├── repository.py        # owner-partitioned operation persistence (SQLite payload)
├── providers.py         # provider-role config surface
├── confirmation.py      # frozen title-only batch -> TaskPort commit
├── evaluation.py        # real-audio STT/extraction eval harness (separate report)
├── task_port.py         # ADR-0001 TaskPort boundary into the Tasks module
└── adapters/
    ├── deepgram_stt.py  # multilingual accurate STT (nova-3), per-utterance segments
    ├── openai_stt.py    # hardened accurate STT (180s, quota-429 terminal, auto-detect)
    └── reconciler.py    # gpt-4o strict structured output, v2 prompt,
                         #   morphology-tolerant grounding, per-op skip

backend/app/core/config.py     # deepgram/openai provider defaults (model, api_key_env)
backend/app/container.py       # DI wiring: provider == "deepgram" -> DeepgramAccurateStt
backend/app/api/tasks.py       # GET /api/brain-dump-providers discovery endpoint
backend/tests/conftest.py      # hermetic env scrub of OPENAI_API_KEY/DEEPGRAM_API_KEY

frontend/src/api/taskHooks.ts          # useBrainDumpProviders (consent providers array)
frontend/src/api/client.ts             # typed brain-dump-providers client call
frontend/src/features/brain-dump/BrainDumpRoute.tsx  # consent discovery + display
```

**Structure Decision**: Web-application layout under the ADR-0001 modular
monolith. All work lands inside the existing `voice_brain_dump` workflow package
plus its config/container/api seams and the frontend brain-dump feature; no new
module, store, or top-level package was introduced.

## Module ownership and design decisions

1. **Provider roles stay configuration + DI, never domain state (ADR-0002).**
   `config.py` exposes role-and-schema-based defaults — the accurate provider
   selects `nova-3` + `DEEPGRAM_API_KEY` for Deepgram or
   `gpt-4o-mini-transcribe` + `OPENAI_API_KEY` for OpenAI. `container.py` wires
   `DeepgramAccurateStt` when `provider == "deepgram"`. No vendor enum is stored
   on the operation and no domain branch reads a vendor name, so split-vendor
   deployment (transcription vendor A, reconciliation vendor B) is wiring, not a
   schema migration. Both STT adapters satisfy one `AccurateSttPort` contract and
   the reconciler satisfies `TextReconcilerPort`.

2. **Utterance provenance is first-class.** `deepgram_stt.py` emits one
   `TranscriptHypothesis` per spoken utterance (order, timing, language),
   preserving embedded English proper nouns rather than collapsing to one blob.
   `service.py` persists every segment and feeds the reconciler the *full* list
   so each proposal can cite the exact segment(s) it derives from. This is the
   `TranscriptSegment -> proposal` lineage ADR-0002 requires and the citation
   target for FR-002.

3. **Grounding is morphology-tolerant but not weakened.** `reconciler.py`
   verifies each proposed title against its cited transcript evidence with
   `_tokens_equivalent`, which accepts legitimate source-language inflection
   (Russian imperative ↔ infinitive) and title-fragment ↔ clause equivalence,
   satisfying FR-008. It still rejects concrete-identity swaps, cross-clause
   action/target recombination, restoration of user-deleted proposals, and
   destructive removals lacking explicit destructive language (FR-009). The
   `brain-dump-reconciler-v2` prompt (`template_version =
   "brain-dump-reconciler-v2"`) carries language-lock (titles in the source
   language, never translated — FR-006), segment-boundary (one intent = one
   task; a simple «и»/"and" conjunction never splits — FR-003), accounting
   (no separate utterances merged unless the same action — FR-004), and
   conciseness (core action + object; no inferred deadlines/tags/projects —
   FR-007) rules.

4. **One bad proposal never poisons the batch.** A single proposal that fails
   grounding raises `_SemanticGroundingFailure` and is skipped per-operation,
   leaving every verified sibling intact (FR-010, US3). An entirely unverifiable
   batch still surfaces an explicit validation error rather than an empty
   success, and structural protocol violations (unknown identifiers, malformed
   operations) still fail the whole batch. This is the direct fix for the
   dominant production failure where one unverifiable item aborted a whole
   50-task dump.

5. **Consent names every vendor and is enforced per stage (Principle I,
   ADR-0002).** The consent record gains `providers: list[str]` (bounded,
   `max_length=5`) alongside the legacy single `provider` for migration.
   `service.py` guards each stage: the stage's own configured vendor must be in
   the consented set before audio or derived text leaves the device; a mismatch
   fails closed with an explicit consent-mismatch error and no upload. The
   recording UI must show the *real* configured vendor names, so
   `GET /api/brain-dump-providers` returns them from deployment config and
   `useBrainDumpProviders` consumes them into the consent providers array —
   no hardcoded label.

6. **Hardened OpenAI STT for real recordings.** `openai_stt.py` sizes the
   client timeout for multi-minute audio (180 s), classifies an
   `insufficient_quota` 429 as terminal (`STT_PROVIDER_REJECTED_REQUEST`) so a
   permanently exhausted quota does not burn the retry budget while transient
   429/408/409/5xx stay retryable, and pins the decode language only when
   exactly one hint is present — zero or multiple hints leave the field off so a
   code-switched recording auto-detects (FR-001, FR-013). Malformed provider
   output is caught and re-raised as the allowlisted
   `STT_PROVIDER_INVALID_RESPONSE`, which `service.py` allowlists so it surfaces
   as an actionable code rather than an opaque 500.

7. **Test hermeticity against developer machines (FR-014).**
   `backend/tests/conftest.py` scrubs `OPENAI_API_KEY` and `DEEPGRAM_API_KEY`
   from the environment before tests run, so a local `.env` enabling real
   vendors cannot flip deterministic test providers or leak a real credential /
   the reference recording into CI evidence.

## Contract changes

- **`Consent.providers: list[str]`** (additive) — the named vendor set enforced
  per stage. Legacy single-vendor `provider` remains accepted; readers treat
  `providers` as authoritative when present. No breaking change for existing
  stored operations.
- **`GET /api/brain-dump-providers`** (new, session-scoped, correlation-ID
  bearing) — returns the deployment's configured external voice vendor names for
  consent display. Read-only; no owner data.
- **Provider error-code allowlist** (additive) — `STT_PROVIDER_INVALID_RESPONSE`,
  `STT_PROVIDER_REJECTED_REQUEST`, `STT_PROVIDER_AUTHENTICATION_FAILED`,
  `STT_AUDIO_TOO_LARGE`, `STT_AUDIO_FORMAT_UNSUPPORTED`, `STT_AUDIO_MISSING`,
  `STT_COST_LIMIT_EXCEEDED` extend the existing error envelope with explicit
  terminal/retryable classification.
- **Reconciler `template_version = "brain-dump-reconciler-v2"`** — audit
  provenance for the prompt generation (ADR-0002); the prompt text itself is not
  persisted.
- **No change** to the `AsyncOperation` state machine, chunk-upload manifest
  identity, freeze/confirm idempotency keys, or the title-only
  `create_native_inbox_task` commit action.

## Data handling and privacy

Raw audio stays Capture-private behind an opaque `media_ref`; operation records
never hold bytes or filesystem paths. Transcript segments and proposals are
working artifacts under the existing short retention; confirmed provenance
(`TranscriptSegment -> proposal -> action receipt -> Task.source_capture_ids`)
follows ADR-0001/0002 retention. Consent withdrawal mid-operation schedules
uncommitted audio and working transcripts for deletion. Provider runs, logs,
metrics, and events carry IDs, roles, enum states, coarse cost/confidence bands,
stage names, and allowlisted error codes only — never audio, transcript/task
text, language vocabulary, provider responses, emails, or credentials. The
reference recording and its transcript are treated as real user data and are
never committed; the eval harness reports aggregate metrics, not content.

## Observability

Each provider invocation is an append-only `ProviderRun` with role
(`accurate_stt` / `text_reconciler`), status, attempt, cost accounting, stage,
and allowlisted `error_code`. Correlation IDs thread the operation end-to-end and
appear on the discovery endpoint and every command response. Fail-closed consent
mismatches, terminal quota, and grounding skips are all distinguishable by code
for retry/report flows. Counters follow the ADR-0001 contract (sessions
started/ready/failed, proposals proposed/committed, per-stage latency) without
user content.

## Resilience and mobile

The accurate-STT stage is sized for multi-minute audio (180 s timeout) up to the
30-minute cap; a process death between accurate transcription and reconciliation
resumes from the persisted accurate generation and reuses the successful
`(operation_id, role, method, input_hash)` run rather than re-transcribing paid
audio. `service.py`'s resume-path rebuild reconstructs the multi-segment
projection and re-feeds the reconciler the full segment list. Chunk-hash
mismatch (`409 CHUNK_CONFLICT`), stale-revision commands, duplicate command
replays, and consent withdrawal keep their existing fail-closed / idempotent
behavior. Closing the UI never cancels; reopening resumes by operation ID.

## Test strategy

- **Adapter contracts** — Deepgram multilingual segmentation; OpenAI timeout,
  terminal-vs-retryable 429 (insufficient_quota vs. rate limit), single-hint
  pinning vs. zero/multi-hint auto-detect, malformed-response allowlisting.
- **Grounding matrix** — accept legitimate morphological variation and
  title-fragment ↔ clause grounding; reject identity swaps, cross-clause
  recombination, deleted-proposal restoration, and undeclared destructive
  removals; assert grounding is never weakened for yield.
- **Batch resilience** — mixed batch delivers verified siblings while skipping
  the unverifiable one; all-unverifiable batch raises explicit validation error;
  structural violations fail the whole batch.
- **Consent** — split-vendor consent names both vendors; consent omitting the
  transcription vendor fails closed with no upload; no-consent yields on-device
  provisional only.
- **Idempotency** — commit replay creates each reviewed task exactly once.
- **Hermeticity** — deterministic providers hold with `OPENAI_API_KEY`/
  `DEEPGRAM_API_KEY` present in the ambient environment.
- **Frontend** — `useBrainDumpProviders` renders discovered vendor names; consent
  payload carries the providers array; `BrainDumpRoute` shows real names.
- **Evaluation harness** — reference corpus utterance-by-utterance metrics
  (task-count accuracy, boundary precision, zero translations, zero conjunction
  splits), reported separately from the unit suites.

Delivered evidence: 875 backend + 443 frontend green; live e2e 2026-07-29 drove a
real 4-minute m4a → 62 utterance segments → 15 committed tasks; SC-001..SC-008
verified in `spec.md`.

## Release gates

Standard BrainBuddy gates apply and remain Hermes-owned: backend lint
(`ruff`) / format (`black`) / type (`mypy`) / pytest + coverage, frontend Vitest
+ build, Docker image builds, and the CI spec gate
(`python3 scripts/check_spec_kit_specs.py`). Real providers are enabled only
behind configured credentials and consent; deterministic providers remain the CI
default. Fly release follows the verified-trunk path (ADR-0008).

## Remaining work — FR-016 grounding-tolerance lane (open)

FR-016 is the only unbuilt scope. It extends semantic verification to tolerate,
without weakening FR-009: (a) titles that draw modifier details from multiple
clauses of the *same* cited utterance; (b) mid-utterance self-corrections
(«в восемь, ой, лучше в восемь тридцать»), preferring the corrected value; and
(c) transcription-garbled proper nouns («BrainBuddy» → «BrentBuddy»). Until it
lands, these shapes fail closed rather than guess — a measured cost of roughly
one third of real-dump proposals. Explicitly rejected alternatives stay out of
scope: windowed/batched reconciliation (tested 2026-07-29: +3 proposals for +21%
cost and a reintroduced translation regression) and inferring structured fields
from speech. The lane touches only `reconciler.py` grounding internals plus its
tests and is dispatched through Hermes Kanban with the same anti-hallucination
gates.

## Complexity Tracking

No constitution violations require justification. The feature adds no new
project, module, persistence store, service, or broker; it hardens adapters and
adds one additive consent field and one read-only discovery endpoint inside the
existing ADR-0001/0002 contracts.
