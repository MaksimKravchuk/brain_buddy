# Implementation Plan: Stable Multilingual Voice Brain Dump

**Branch**: `005-multilingual-voice-brain-dump` | **Date**: 2026-07-29 | **Spec**:
`specs/005-multilingual-voice-brain-dump/spec.md`

**Input**: Feature specification from `specs/005-multilingual-voice-brain-dump/spec.md`
plus the live-verification evidence recorded there (reference RU/EN corpus, real
4-minute recording, fail-closed consent probes).

**Note**: This is a retroactive plan describing the architecture the delivered
implementation satisfies. The work is **committed on the feature branch
`005-multilingual-voice-brain-dump`** at HEAD `317aca5` — the US1-US3 core
(`000c2f8`, `f6cd066`), the FR-016 grounding lane, the planning-review hardening
lane (`889a956`…`2c3e4ec`), the commit-concurrency/audio-deletion fixes
(`cac5a27`), the live evidence harness + report (`900eeb8`, `0b0d166`), the
commit_batch/committing retention fixes (`c979621`), and the final5feb fix round
(`317aca5`, with the live report re-run committed at `166b9a3`) —
**not yet merged to `main` and not yet deployed**. Live observations (the 4-minute
recording drive) are experimental evidence, kept separate from landed/deployed
acceptance evidence (see the Evidence manifest). It introduces no new
architecture; where it states a decision, that decision is realized in the
branch, pending ASK-class landing (see Release gates).

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
   that set and fails closed before persistence or external-provider egress (first-party boundary); the recording UI
   discovers the real configured vendor names from a new
   `GET /api/brain-dump-providers` endpoint.
4. **Test hermeticity** — the backend test environment scrubs real
   provider credentials so a developer `.env` cannot change deterministic
   test-provider selection.

All four changes are delivered on the branch, FR-016 (multi-clause modifier
grounding, self-correction tolerance, garbled-proper-noun tolerance) landed in
`reconciler.py` with a documented fail-closed residue (pronoun-binding
self-correction, edit-distance-3 proper-noun garbles, one paraphrase class), and
the full planning-review hardening lane (consent egress boundary,
provider-discovery prerequisite, review-screen citations, consent-withdrawal
deletion, frozen-batch phased-saga commit, ADR-0008 rollout flag, operational
evidence report, ADR-0006 copy, title-shape invariant) plus the
commit-concurrency/deletion fixes, the commit_batch/committing retention fixes, and
the live evidence report are delivered at
HEAD `317aca5` (1003 backend / 454 frontend green — see "Hardening lane (delivered)").

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

**Constraints**: Consent-gated, fail-closed before any external-provider egress or
persistence (first-party boundary); no **real** capture audio, transcript text,
credentials, paths, or content fingerprints of real captures in logs / metrics /
events / committed fixtures. (The fictional, founder-authored reference corpus and
hashes derived from it are committable versioned test data — see Data handling.)
Idempotent commit under replay; anti-hallucination grounding never weakened to
raise yield.

**Scale/Scope**: Single dogfooding founder; one operation at a time; reference
corpus ~50 utterances / ~30 actionable cold-start creations.

## Constitution Check

*GATE: met at HEAD `317aca5` (for founder-only INTERNAL exposure). The US1-US3 core, FR-016, and the hardening lane
(Phase 6, T029-T037) that closed the high-risk-review gaps (consent egress
boundary, review-screen provenance, consent-withdrawal deletion, frozen-batch
phased-saga commit, ADR-0008 default-OFF rollout flag, corpus evidence) are all
delivered and verified (1003 backend / 454 frontend green). Final confirmation is
the approved planning-review campaign against `2c3e4ec`.*

- **Spec workflow**: `spec.md` and `checklists/requirements.md` are current and
  reflect the delivered behavior; this plan follows them. The spec has no
  `[NEEDS CLARIFICATION]` markers, and the three planning-review product
  decisions (partial-batch commit semantics, garbled-proper-noun handling,
  code-switched title language) are recorded in the spec's Clarifications section
  (2026-07-29) and in the handoff. FR-016 is delivered; the open scope is the
  planning-review hardening lane (Phase 6, T029-T037), which gates the approved
  handoff and ASK landing.
- **Consent & Safety (Principle I)**: External processing requires current
  consent naming the configured vendors (`consent.providers`); provisional model
  output stays in the operation workspace until explicit confirmation applies
  frozen title-only actions through `TaskPort` (ADR-0002 contract preserved). Raw
  audio/transcript/credentials/paths/fingerprints stay out of logs, metrics,
  events, and fixtures; the test env scrubs `OPENAI_API_KEY`/`DEEPGRAM_API_KEY`
  so real keys and the reference recording never enter CI. **Consent egress
  boundary (hardened, delivered)**: the pre-persistence guard now requires the
  *complete* configured vendor set (`889a956`), so a consent naming only the
  reconciler vendor fails closed before persistence or external-provider egress (first-party boundary); provider
  discovery is a fail-closed prerequisite for recording with the hardcoded
  fallback removed, and FR-012 vendor names are rendered (`2420c96`). See the
  "Hardening lane (delivered)" section.
- **Tests (Principle II)**: Behavior changes shipped with failing-then-passing
  backend pytest (adapter contracts, grounding accept/reject matrix, per-op
  skip, consent-mismatch fail-closed, hermeticity) and frontend Vitest
  (provider discovery, consent payload). Edge cases cover invalid/oversized/
  malformed provider responses, timeouts, quota exhaustion, consent denial,
  idempotent replay, and partial failure. Full suites: 1003 backend / 452
  frontend green with the feature active at HEAD `2c3e4ec` (SC-008).
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
   "brain-dump-reconciler-v2"`) carries language-lock (titles are language-faithful
   — preserve the source language, intent, required identities, and embedded
   foreign terms; grounded rewording and inflection are allowed, a title need not
   be a verbatim substring; translation and ungrounded additions are prohibited —
   FR-006, enforced as a title-shape invariant distinct from FR-008 grounding),
   segment-boundary (one intent = one
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
   the consented set before persistence or external-provider egress (first-party boundary); a mismatch
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
   as an actionable code rather than an opaque 500. **Provider note (FR-013
   scope)**: terminal-quota classification is per-provider and exists only where
   the provider distinguishes permanent exhaustion. The default primary STT
   (Deepgram `nova-3`) currently maps every HTTP 429 to a *retryable*
   `STT_PROVIDER_UNAVAILABLE`, so a Deepgram-signalled permanent quota condition
   can still consume the retry budget — a known gap to close by detecting a
   terminal Deepgram quota signal (or narrowing FR-013 to providers that
   distinguish it), tracked as a follow-up.

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
- **Commit semantics (product decision, 2026-07-29)** — commit is **per-action
  durable, idempotent under replay**, not whole-batch atomic. A failure partway
  through a reviewed batch keeps the already-created tasks; a retry completes only
  the remaining actions, each exactly once via the deterministic child key
  (ADR-0002 §492–519). FR-015 and US1 acceptance scenario 4 are amended from
  "atomically" to this per-action durable definition; the plan and its tests use
  the same definition (partial-failure resumes, never rolls back siblings).
- **No change** to the `AsyncOperation` state machine, chunk-upload manifest
  identity, freeze/confirm idempotency keys, or the title-only
  `create_native_inbox_task` commit action shape.

## Data handling and privacy

Raw audio is **workflow-private** behind an opaque `media_ref` (see the ownership
exception below); operation records never hold bytes or filesystem paths.
Transcript segments and proposals are working artifacts under a configurable
retention window. **Provenance lifecycle** (product decision, 2026-07-29): exact
cited-utterance text is available during Review and for the retention window;
after it expires, the working text is purged and durable provenance is immutable
IDs + content hashes only (`action receipt -> confirmed_title_sha256`,
`source_segment_ids`, `Task.source_capture_ids`). Provider runs, logs, metrics,
and events carry IDs, roles, enum states, coarse bands, stage names, and
allowlisted error codes only — never audio, transcript/task text, vocabulary,
provider responses, emails, or credentials.

**Committable test data**: real capture audio/transcripts and fingerprints of
real captures are never committed. The reference corpus
(`founder_ru_reading_script.v1.json`) is fictional, founder-authored, self-declared
safe-to-commit versioned test data; it and per-title SHA-256 hashes derived from
it (the T035 report/run artifacts) are committable. This codifies the delivered
posture (the corpus is the sole committed place utterance text lives) rather than
the blanket "never committed" phrasing.

**Retention**: the posture matches the provenance decision and the hard-maximum
decision. (1) Frozen `commit_batch` action titles are reduced to their SHA-256
(= receipts' `confirmed_title_sha256`) by `purge_expired_working_artifacts` for
terminal/withdrawal-finalized operations past the window, so no plaintext
derived-title text outlives the window (`c979621`, T040). (2)
`recover_committing_operations` resumes stranded mid-commit operations through the
standard commit path with recovery idempotency keys (`c979621`, T041). (3) The
retention window is a **hard maximum** (product decision): a `committing` operation
still unfinished at its working-artifact deadline is finalized terminal and its
exact transcript/proposal/title text is purged (completed tasks/receipts preserved
as IDs/hashes). Delivered (`317aca5`, **T048**): a past-deadline `committing` op is
finalized to `cancelled`, preserving `committed_task_ids` and a reduced ledger with
a full exact-text scrub — closing the reviewed gap where a persistently failing
`TaskPort` kept a `committing` op and its plaintext indefinitely. (4) Idempotency
snapshots: the periodic sweep scrub-overwrites operation idempotency snapshots
(SQLite + JSON sidecar) with a redacted post-purge snapshot at the deadline, so
full-operation text does not survive retention (`317aca5`, **T045**). (5) Raw-audio
deletion is fail-closed: a verified-absence outcome with a sweep retry replaces the
former `ignore_errors=True` (`cac5a27`, T039).

**ADR-0001/0002 raw-media ownership — bounded migration exception.** ADR-0001
assigns raw-input media to Capture; here the `voice_brain_dump` workflow's own
`repository.py` persists raw audio chunks
(`save/load/delete_brain_dump_audio_chunks`) rather than a Capture-owned port, so
the workflow is both orchestrator and media owner. This is a **documented
exception, not ADR-0001 compliance** — the store is described as workflow-private,
not Capture-private. **Remediation**: Architect-owned; either route media through a
Capture-owned port/repository or record an accepted ADR amendment naming the
temporary owner. **Owner/milestone**: resolve before Capture module extraction or a
second writer of operation media, whichever comes first; tracked as a follow-up
architecture task, not only a contingent extraction trigger. Until then, no other
module reads or writes this store.

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
  transcription vendor fails closed before persistence or provider egress
  (first-party boundary) — the delivered vendor-B-only no-persistence test is the
  primary SC-006 evidence; no external consent means recording does not start
  (no on-device provisional path). The client-side capture gate (T030) is
  defense-in-depth. A full-stack A+B / consent-only-B browser-egress assertion
  (client sends no audio request) remains a follow-up test.
- **Idempotency** — commit replay creates each reviewed task exactly once.
- **Hermeticity** — deterministic providers hold with `OPENAI_API_KEY`/
  `DEEPGRAM_API_KEY` present in the ambient environment.
- **Frontend** — `useBrainDumpProviders` renders discovered vendor names; consent
  payload carries the providers array; `BrainDumpRoute` shows real names.
- **Evaluation harness** — reference corpus utterance-by-utterance metrics
  (task-count accuracy, boundary precision, zero translations, zero conjunction
  splits), reported separately from the unit suites.

Delivered evidence: 1003 backend (97.23% coverage, incl. 334 reconciliation) + 452
frontend green at HEAD `317aca5`, including the delivered vendor-B-only
no-persistence consent test. The live evidence report ran at `900eeb8`
(`run_key e8cb406f…`): SC-001 (19 committed), SC-003 (0/45 translated), SC-007
(21.1 s) pass; SC-002 74.4% (32/43 strict) and SC-004 2 splits are below the
PUBLIC-ON gates, founder-accepted. See the Evidence manifest for the SC
→ test/report mapping.

## Release gates

Standard BrainBuddy CI gates apply and remain Hermes-owned: backend lint
(`ruff`) / format (`black`) / type (`mypy`) / pytest + coverage, frontend Vitest
+ build, Docker image builds, and the CI spec gate
(`python3 scripts/check_spec_kit_specs.py`). Real providers are enabled only
behind configured credentials and consent; deterministic providers remain the CI
default.

**Delivery class: ASK (ADR-0008), not standard verified-trunk.** This feature
changes external-processing privacy/consent behavior and modifies
`backend/app/api/tasks.py`, both of which ADR-0008 classifies as ASK paths and
explicitly excludes from automatic candidate promotion. Landing therefore
requires the ADR-0008 ASK procedure: a recorded human approval, green CI on the
exact tested SHA, and an audited ASK landing (temporary ruleset intervention with
the deploy key as sole `restrict_updates` bypass). It must not ride the SHIP/SHOW
auto-landing path. Fly production release follows the verified-trunk deploy after
that ASK landing.

**Exposure gate (product decisions, 2026-07-29).** BrainBuddy is currently a
single-user (founder-only) product. Code lands and deploys with the
`voice_brain_dump` flag **OFF**. An explicit **founder-only INTERNAL** experiment
is approved against a **no-regression floor**: SC-002 ≥ 74.4% strict-oracle and
conjunction splits ≤ 2 (the authoritative 900eeb8 baseline; the earlier ~88% was a
superseded loose-oracle figure). Regression below the floor requires a new
decision. **Public ON is blocked** until the ADR-0002 targets (≥95%
task-count/boundary precision-recall, 100% critical-term preservation) pass, or an
accepted ADR supersedes them — the acceptance tiers are explicit: the MUST-level
conjunction-split (FR-003) and required-term (FR-006) rules are public-ON-tier,
the founder-INTERNAL tier is the floor, and consent/anti-hallucination guarantees
are unconditional at both. So "stable/delivered" means stable for founder-only
INTERNAL use, not a public release. (Follow-up: a short ADR-0002 annotation
recording the OFF→INTERNAL→ON ladder — release-closure T054.)

**Flag-OFF privacy controls (product decision, 2026-07-29).** The exposure flag is
exposure control, never authorization. For an owner's *existing* operations,
read/status, consent withdrawal, cancel, and raw-audio deletion **remain reachable
regardless of the flag** — only new-capture surfaces are flag-gated — and the
background runner **pauses advancing provider work** for an OFF owner (so external
egress does not drain past an OFF flag). This corrects the reviewed behavior where
OFF 404'd the withdrawal/deletion routes while the runner kept advancing;
**delivered** (`317aca5`, T046): `{withdraw_consent, cancel, delete_raw_audio}` plus
GET read/status bypass the gate, all new-capture actions and provider discovery stay
gated, and the runner skips OFF owners via a container-wired predicate. Unsetting the
provider configuration (fail-closed Disabled adapters) remains the operator-level
containment for external egress.

## FR-016 grounding-tolerance lane (delivered)

FR-016 extends semantic verification to tolerate, without weakening FR-009:
(a) titles that draw modifier details from multiple clauses of the *same* cited
utterance; (b) mid-utterance self-corrections («в восемь, ой, лучше в восемь
тридцать»), preferring the corrected value; and (c) transcription-garbled proper
nouns («BrainBuddy» → «BrentBuddy»). **Delivered 2026-07-29** in `reconciler.py`
(`_grounding_clauses`, `_correction_clauses`, `_entities_equivalent` /
within-segment adjunct grounding), covered by
`test_openai_reconciler_grounds_within_segment_multi_clause_aggregation`,
`test_openai_reconciler_grounds_self_corrected_utterances`, and
`test_openai_reconciler_tolerates_stt_garbled_proper_noun` (334 reconciliation /
907 backend tests green). A **documented fail-closed residue** remains — the
pronoun-binding self-correction case, edit-distance-3 proper-noun garbles, and
one paraphrase class — which still fails closed rather than guessing, so FR-009 is
preserved. Explicitly rejected alternatives stay out of scope: windowed/batched
reconciliation (tested 2026-07-29: +3 proposals for +21% cost and a reintroduced
translation regression) and inferring structured fields from speech.

## Hardening lane (delivered)

The high-risk planning reviews (`c6003348`, then `rerun0729`) surfaced privacy,
durability, and evidence gaps between the reviewed code and the spec's promises.
The full hardening lane (tasks T029–T037) landed test-first on the ASK-class
paths in commits `889a956`, `2ca19f0`, `2420c96`, `b670856`, `2c3e4ec`:

1. **Consent pre-persistence boundary** — the complete configured vendor set is
   required at the egress boundary (`889a956`), with an authoritative `providers`
   list and `AUDIO_UPLOAD_PROVIDER_CONSENT_CONFLICT` on conflicting dual-field
   precedence plus a no-persistence negative test (`2ca19f0`). SC-006 re-anchors
   to HEAD.
2. **Provider-discovery fail-closed + FR-012** — hardcoded `openai` fallback
   removed; mic/upload gated on discovery with a retry state; real vendor names
   rendered (`2420c96`).
3. **Review-screen citations** — each proposal's cited utterance is rendered with
   stale-id degradation (`2420c96`).
4. **Consent-withdrawal deletion, frozen-batch phased-saga commit, ADR-0008
   rollout flag** — withdrawal sets a deletion deadline and sweeps active ops; the
   commit ledger is a phased saga (status `committing`); a default-OFF
   `voice_brain_dump` flag gates all 8 routes and UI (`2ca19f0`, `2420c96`).
5. **Operational evidence report, ADR-0006 copy, title-shape invariant** —
   hash-addressed SC-001..004/007 report (`b670856`), provisional/confirmation
   copy (`2c3e4ec`), and a script-based language-fidelity title invariant distinct
   from FR-008 grounding (`b670856`).

Integrated verification: full suite 1003 backend (97.22% cov) / 454 frontend green,
build/ruff/mypy clean, plus a live e2e drive yielding 25 committed proposals.
**SHA provenance** (distinct roles, do not conflate): the hardening lane completed
at `2c3e4ec`; commit concurrency/deletion at `cac5a27`; commit_batch/committing
retention at `c979621`; the **final5feb fix round at `317aca5` — the frozen
implementation SHA**; the live evidence report **re-ran ON `317aca5`**
(`run_key bfd2defe…`, committed `166b9a3`); the planning-artifact HEAD is the docs
commit (docs only, no code). **Exact-SHA evidence is now satisfied**: per ADR-0008
the report ran on the exact reviewed implementation SHA, and docs-only commits
after it do not touch code, so `317aca5` is the tested code SHA that governs the
landing evidence. **Known non-gating leftover**: Playwright visual baselines need
regeneration.

## Evidence manifest

Acceptance evidence is anchored to the branch, privacy-safe (no raw recording or
transcript — aggregate metrics and named tests only):

- **Source**: branch `005-multilingual-voice-brain-dump`, HEAD `317aca5`
  (US1-US3 core `000c2f8`/`f6cd066`, FR-016 grounding, hardening lane `889a956`/
  `2ca19f0`/`2420c96`/`b670856`/`2c3e4ec`, concurrency/deletion `cac5a27`, live
  evidence `900eeb8`/`0b0d166`, commit_batch/committing retention `c979621`, and
  the spec package), pending ASK-class landing.
- **Automated suites**: 1003 backend (pytest, 97.23% coverage, incl. 334
  reconciliation) + 454 frontend (Vitest) green with the feature active — this
  supersedes the earlier 875/907 backend figures.
- **SC → evidence**: SC-002/003/004 map to the reconciliation grounding/shaping
  tests in `backend/tests/test_voice_brain_dump_reconciliation.py` and the T035
  corpus report; SC-005 to the per-op skip tests; SC-006 to the split-vendor
  consent tests in `backend/tests/test_brain_dump_operations_api.py`, **including
  the vendor-B-only no-persistence negative test delivered at HEAD** (`2ca19f0`);
  provider hardening to `backend/tests/test_voice_stt_adapters.py`; hermeticity to
  `backend/tests/conftest.py`.
- **SC-001/SC-007 (15 committed tasks, ~30 s)**: recorded operational
  observations from the 2026-07-29 real-recording drive on this branch, labelled
  experimental (not a landed/deployed CI artifact); the real-audio harness
  (`evaluation.py`, `scripts/evaluate_voice_stt.py`) reports STT/extraction
  aggregates only and does not itself drive capture-to-commit. Hardening task
  T035 replaces this with a SHA-keyed capture→review→commit report.
- **ADR-0002 release-gate posture**: this slice does **not** meet ADR-0002's
  public-release targets (>=95% exact task-count accuracy, >=95% boundary
  precision/recall, 100% critical-term preservation). On the live report at
  `900eeb8` the strict 4-signal oracle scores **SC-002 74.4% (32/43)** and
  **SC-004 2 conjunction splits** — below the SC-002 ≥80% and SC-004 zero-split
  **PUBLIC-ON gates**. (Earlier ~82-88% figures used a looser correctness notion;
  the strict oracle is authoritative.) Per the exposure decision this is an
  explicitly **founder-only INTERNAL** increment that accepts the current
  baseline; it does not claim satisfied ADR-0002 public-release acceptance, and
  public ON stays gated on those targets.

## Migration and rollback (version skew)

**Landed design (`cac5a27`, `c979621`)**: within the current backend, a mid-commit
interruption resumes exactly — the frozen `commit_batch` plus owner-serialized,
atomic `create_native_inbox_task` idempotency (CAS ledger recording, child
identity retained by a purge exemption) makes a resumed commit exactly-once. No
new schema beyond the documented `commit_batch`/`consent_withdrawn_at` fields was
added. The remaining risk is purely **version skew on rollback to a pre-saga
backend** (`origin/main`), which drops these fields via `StorageBaseModel`
`extra="ignore"` and has no resume code. The rollback matrix must therefore cover
all four new structures:

1. **`consent.providers`** — on rollback the older backend ignores it and compares
   the single legacy `consent.provider` against the differently-configured
   reconciler; split-vendor operations fail closed (safe direction).
2. **`commit_batch` (frozen per-action ledger)** — an operation resting in status
   `committing` loses its ledger on the first old-backend read-modify-write, and
   `origin/main` has no saga/resume code, so a partially-executed commit becomes
   unresumable with tasks already created and no receipts — breaking the FR-015
   per-action-durable guarantee. Rollback MUST first resume-to-completion or
   cancel every `committing` operation; cancelling a partially committed batch is
   never safe.
3. **`consent_withdrawn_at` + withdrawal-anchored `working_artifacts_expires_at`**
   — `origin/main`'s purge has no withdrawal-eligibility branch, and an old-backend
   rewrite permanently erases the marker, silently defeating the T032
   withdrawal-deletion promise. Rollback MUST let withdrawal-triggered purges
   complete (or purge synchronously) before restoring the older backend.
4. **New-client → old-backend request schema** — a new client sends `providers` to
   the older strict request schema (`StrictBaseModel` rejects unknown fields), so
   the frontend must not be newer than the backend; define backend-first
   deployment order.

Deployment order differs by direction: **forward** deploy is backend-first (so the
new backend accepts `providers` before the new client sends it); **rollback** is
**old-frontend-first**, then the old backend only after preconditions are met —
stop accepting new capture; drain every `committing` operation to completion (do
not cancel a partially committed batch — see the partial-commit finding below);
let withdrawal-triggered purges complete. Completed operations are immutable and
unaffected. Old-backend rewrites permanently erase `commit_batch` and
`consent_withdrawn_at`, so these preconditions are mandatory. This rollback drill
(with executable pre-checks for zero remaining `committing` operations and due
withdrawal cleanup, and a `docs/voice-stt.md` runbook step) is tracked as
release-closure **T053**, not left as prose; code-level mitigation (e.g., a
rollback-safe ledger encoding) remains the Architect's call.

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|------|-----------|--------------------------------------|
| Raw-media owned by the workflow repository rather than a Capture-owned port | Single-owner MVP slice; media exposed only via opaque `media_ref` with owner scoping | A Capture port/repository is the correct target but not required before Capture extraction; tracked as a bounded exception with exit criteria (see Data handling) |

The feature adds no new project, module, persistence store, service, or broker; it
hardens adapters and adds one additive consent field and one read-only discovery
endpoint. It does **not** yet fully satisfy the ADR-0001 media-ownership boundary:
raw media is workflow-owned, a documented exception that requires either a
Capture-owned port or an accepted ADR amendment before the claim of ADR
compliance holds — tracked as release-closure **T050**. This plan does not assert
ADR-0001/0002 compliance while that exception is unresolved.
