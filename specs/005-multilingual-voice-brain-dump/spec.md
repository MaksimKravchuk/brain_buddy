# Feature Specification: Stable Multilingual Voice Brain Dump

**Feature Branch**: `005-multilingual-voice-brain-dump`

**Created**: 2026-07-29

**Status**: Retroactive — documents behavior delivered on branch `005-multilingual-voice-brain-dump` and verified live on 2026-07-29 (FR-016 grounding tolerance has since landed with a documented fail-closed residue; a small set of privacy/UX hardening fixes is landing before an approved handoff — see plan.md "Follow-up hardening in flight")

**Input**: User description: "Stable multilingual voice brain dump: a founder records a stream-of-consciousness voice note in Russian, English, or code-switched speech, and BrainBuddy reliably turns it into individually reviewable, correctly split task proposals with full transcript provenance. The existing voice brain dump failed closed on real multilingual recordings — a real 4-minute Russian recording with English product terms produced zero committed tasks."

## Clarifications

### Session 2026-07-29

- Q: If task creation fails partway through a reviewed batch, must the batch be all-or-nothing, or do already-created tasks remain? → A: **Per-action durable** — already-created tasks remain and a retry idempotently completes only the remaining actions (ADR-0002 per-action commit semantics, not whole-batch rollback). FR-015 and US1 acceptance scenario 4 reflect this.
- Q: Is a correctly transcribed proper noun mandatory, or is dropping a task with a garbled proper noun acceptable? → A: **Fail-closed omission accepted** — proper-noun preservation is best-effort; heavily garbled nouns are not guessed and dependent proposals fail closed (FR-016 tolerance recovers close mishears). FR-001, FR-016, and the proper-noun Edge Case reflect this.
- Q: What is the canonical title-fidelity rule for generated task proposals (given code-switched utterances and multi-language evidence)? → A: **Language-faithful rewrites** — titles preserve the source language, the spoken intent, proper nouns, and embedded foreign terms; grammatical inflection and grounded rewording are allowed (a title need not be a verbatim substring), and omission of non-core details for conciseness is allowed; translation is prohibited. The extractive-subsequence option was declined because it would contradict the delivered FR-008 morphology tolerance. This separates the title-generation rule (FR-006 output, FR-007 conciseness) from the semantic-grounding tolerance (FR-008 verification). FR-006, FR-007, FR-008, US1 scenario 1, and SC-003 reflect this.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Multilingual dump becomes reviewable tasks (Priority: P1)

A founder records a several-minute stream-of-consciousness voice note mixing Russian and English (product names, tech terms) on their phone, stops the recording, and reviews a list of task proposals — one per spoken intent, titled in the language they spoke, each traceable to the exact utterance that produced it — then commits the ones they want into their Inbox.

**Why this priority**: This is the product's core capture ritual. Before this feature, a real multilingual recording produced zero committed tasks, which destroyed the trust loop the whole product depends on.

**Independent Test**: Record (or replay) the reference 4-minute Russian/English corpus recording, drive it through capture → review → commit, and count committed tasks and their languages.

**Acceptance Scenarios**:

1. **Given** a sealed recording of ~50 spoken utterances in Russian with embedded English terms, **When** processing completes, **Then** the review screen shows at least 15 task proposals, every title is language-faithful to its source utterance (source language, proper nouns, and embedded foreign terms preserved, never translated — inflection/grounded rewording permitted), and each proposal cites the utterance(s) it came from.
2. **Given** an utterance joining two nouns with a simple conjunction («Добавь молоко и хлеб в список покупок»), **When** proposals are generated, **Then** it yields exactly one task — never two.
3. **Given** an utterance that is a query or display request («Покажи все задачи на сегодня»), **When** proposals are generated, **Then** it yields no task.
4. **Given** the user commits the reviewed proposals, **When** they open their task list, **Then** every committed proposal appears as a task exactly once, even if commit is retried; **and** if a commit fails partway through the batch, the already-created tasks remain and a retry completes only the remaining actions (per-action durable, not whole-batch rollback).

---

### User Story 2 - Consent names every vendor that touches the data (Priority: P2)

Before any audio or derived text leaves the device, the user sees and approves the actual named vendors that will process it — including when transcription and semantic reconciliation are handled by different vendors.

**Why this priority**: Consent integrity is a constitutional requirement (Principle I). Split-vendor processing is now the default configuration, so single-vendor consent would silently misrepresent where data goes.

**Independent Test**: Configure different transcription and reconciliation vendors, start a recording, and inspect the consent payload and the fail-closed behavior when consent names the wrong vendor.

**Acceptance Scenarios**:

1. **Given** the deployment has vendor A for transcription and vendor B for reconciliation, **When** the user grants consent, **Then** the consent names both vendors explicitly and the recording screen displayed the real configured vendor names (not a hardcoded label).
2. **Given** consent that names only vendor B, **When** the pipeline reaches the transcription step for vendor A, **Then** processing fails closed with an explicit consent-mismatch error and no audio leaves the device.
3. **Given** no external-processing consent, **When** the user attempts to record, **Then** recording does not start, nothing is captured or uploaded, and the user is told consent is required. (A no-consent on-device preview mode is not offered; see Out of Scope.)

---

### User Story 3 - One bad proposal never destroys the batch (Priority: P2)

When one extracted proposal cannot be verified against the transcript, the user still receives every other verified proposal; the unverifiable one is silently dropped rather than poisoning the batch.

**Why this priority**: This was the dominant production failure: a single unverifiable proposal aborted the entire result, so a realistic 50-task dump almost always yielded zero tasks.

**Independent Test**: Process a transcript where at least one extracted proposal fails verification and count surviving proposals.

**Acceptance Scenarios**:

1. **Given** a transcript producing 30 extracted proposals of which 5 fail grounding verification, **When** processing completes, **Then** the 25 verified proposals reach review and the 5 rejected ones do not.
2. **Given** a transcript where every extracted proposal fails verification, **When** processing completes, **Then** the operation surfaces an explicit validation error (not an empty success).
3. **Given** a proposal whose meaning is not present in the cited transcript, **When** verification runs, **Then** it is rejected — anti-hallucination guarantees are never weakened to raise yield.

---

### Edge Cases

- Code-switched audio must not be forced into a single language: with zero or multiple language hints, transcription operates in multilingual mode; with exactly one hint, that language is pinned.
- Speech-to-text mishears proper nouns («BrainBuddy» → «BrentBuddy»): proposals ground against what was actually transcribed; bounded garbled-noun tolerance (FR-016) recovers close mishears, while heavily garbled nouns (beyond the tolerated edit distance) still fail closed rather than guessing.
- Self-corrections and disfluencies («в восемь, ой, лучше в восемь тридцать», «хотя нет, назначь её Максиму»): FR-016 self-correction tolerance prefers the corrected value, with a documented residue (e.g. pronoun-binding self-correction) that still fails closed. Queries, fillers, and «не добавляй…» instructions correctly produce no task.
- Transcription vendor quota exhaustion, auth failure, oversized audio, and malformed responses each surface as distinct allowlisted error codes; permanent conditions must not burn retry budgets.
- A long recording (30-minute cap) must survive provider latency: transcription timeouts are sized for multi-minute audio, and a crash between transcription and reconciliation resumes without paying for transcription twice.
- Consent withdrawal mid-operation, upload hash mismatch, stale-revision commands, and duplicate command replays keep their existing fail-closed / idempotent-replay semantics.
- Developer-machine configuration (a local `.env` enabling real vendors) must never leak into the automated test environment's deterministic providers.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST transcribe mixed-language (Russian/English code-switched) recordings without forcing a single language. Spoken proper nouns and embedded foreign terms are preserved on a best-effort basis; heavily garbled proper nouns MUST NOT be guessed — proposals that depend on them fail closed (see FR-016 and Edge Cases) rather than inventing a term.
- **FR-002**: The system MUST preserve utterance boundaries from transcription and record per-utterance provenance such that every task proposal cites the utterance(s) it derives from.
- **FR-003**: Task extraction MUST yield exactly one task per single-intent utterance by default; a simple conjunction («и», "and") within one intent MUST NOT split it.
- **FR-004**: Task extraction MUST NOT merge separately spoken utterances into one proposal unless they explicitly describe the same single action.
- **FR-005**: Queries, display requests, fillers, and explicit "don't add" instructions MUST NOT produce task proposals.
- **FR-006**: Proposal titles MUST be language-faithful to their cited source utterance: they preserve the source language, the spoken intent, proper nouns, and embedded foreign terms, and are never translated. Grammatical inflection and grounded rewording are permitted — a title need not be a verbatim substring of the utterance — and a code-switched utterance yields a code-switched title rather than one normalized to a single language. (Conciseness is governed by FR-007; grounding tolerance for verification by FR-008; anti-hallucination by FR-009.)
- **FR-007**: Title conciseness (core action + object) is enforced as generation guidance: the extraction step is instructed to exclude appended deadlines, contexts, tags, labels, and project names from titles unless the title would be meaningless without them. Grounding remains the hard guarantee — residual detail may appear in a title only when it is grounded in the cited utterance; inferring such details remains prohibited.
- **FR-008**: Semantic *verification* (distinct from the FR-006 title-generation rule) MUST accept legitimate morphological variation of the source language (e.g., Russian imperative ↔ infinitive inflection) when judging whether a title is grounded in cited transcript evidence. This tolerance proves meaning; it does not license translation or ungrounded rewording of the emitted title, which remain governed by FR-006 and FR-009.
- **FR-009**: Semantic verification MUST continue to reject any proposal whose meaning is not traceable to its cited transcript evidence, including concrete-identity swaps, cross-clause action/target recombination, restoration of user-deleted proposals, and destructive removals without explicit destructive language. These guarantees MUST NOT be weakened to increase yield.
- **FR-010**: A single unverifiable proposal MUST be rejected individually without discarding verified sibling proposals; an entirely unverifiable batch MUST fail with an explicit validation error. Structural protocol violations (unknown identifiers, malformed operations) MUST still fail the whole batch.
- **FR-011**: External-processing consent MUST name every configured vendor that will process the recording or its derived text; each pipeline stage MUST verify its own vendor is within the consented set and fail closed on mismatch before data leaves the device.
- **FR-012**: The recording interface MUST display the actual configured vendor names for consent, discovered from the deployment configuration, not hardcoded.
- **FR-013**: Provider failures MUST surface as allowlisted, actionable error codes; permanent conditions (quota exhaustion, invalid credentials, unsupported audio) MUST be classified terminal without burning retry budgets, and transient conditions MUST retry within bounded budgets.
- **FR-014**: The automated test environment MUST be hermetic against developer-machine provider configuration: local environment files MUST NOT alter test-environment provider selection.
- **FR-015**: Committing reviewed proposals MUST create the reviewed tasks through per-action durable writes that are idempotent under command replay: a failure partway through a batch keeps the already-created tasks, and a retry completes only the remaining actions exactly once (ADR-0002 per-action commit semantics — not whole-batch rollback). Each committed proposal appears as a task exactly once under replay.
- **FR-016** *(delivered 2026-07-29)*: Semantic verification tolerates (a) titles drawing modifier details from multiple clauses of the same cited utterance, (b) mid-utterance self-corrections, preferring the corrected value, and (c) transcription-garbled proper nouns, without weakening FR-009. A documented fail-closed residue remains (the pronoun-binding self-correction case, edit-distance-3 proper-noun garbles, and one paraphrase class): these still fail closed rather than guessing.

### Key Entities

- **Brain-dump operation**: The long-running capture→review→commit unit; owns consent, audio chunk manifest, transcript segments, proposals, provider runs, and status history.
- **Consent record**: Microphone permission, external-processing permission, the named vendor set, language hints, and vocabulary; captured before recording, enforced per pipeline stage.
- **Transcript segment (utterance)**: One spoken utterance with order, timing, language, and provenance role (preview vs. accurate); the citation target for proposals.
- **Task proposal**: A candidate task with title, cited source segments, verification status, and lineage; only verified proposals reach review, only reviewed proposals commit.
- **Provider run**: One vendor invocation (transcription or reconciliation) with role, status, cost accounting, and allowlisted error code; checkpointed so recovery never repeats paid work.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The reference real 4-minute Russian/English recording (~50 utterances, ~30 actionable cold-start creations) yields at least 15 committed tasks end-to-end. (Verified 2026-07-29: 15 committed; prior behavior: 0.)
- **SC-002**: On the 50-utterance reference corpus processed utterance-by-utterance, at least 80% of task-yielding utterances yield exactly one correct task proposal. A task-yielding utterance is one expected to produce a task when processed in isolation (~39 of 50; the rest are queries, display requests, fillers, or "don't add" instructions). This is a larger set than the ~30 cold-start creations of SC-001, because in isolation an existing-task modification («перенеси…», «отметь…») grounds as its own task, while in a full-recording cold start it correctly does not. (Verified: 32 of ~39 ≈ 82%; prior: ~33%.)
- **SC-003**: Zero proposal titles are translated out of their source utterance's language: every title is language-faithful (source language preserved, mixed-language titles never normalized to one language; inflection/grounded rewording is allowed and is not counted as a violation), measured on the reference corpus. (Verified: 0 translated across all shapes; prior: 9 of 50.)
- **SC-004**: Zero utterances are split on a simple conjunction within one intent on the reference corpus. (Verified: 0.)
- **SC-005**: A batch containing at least one unverifiable proposal still delivers every verified sibling. (Verified: skip semantics live in production shape.)
- **SC-006**: A consent set that omits the configured transcription vendor produces a fail-closed consent-mismatch error and no audio upload. (Partially verified: the stage-level vendor guard is live, but the *complete-set pre-upload* boundary that guarantees "no audio upload" for a vendor-B-only consent is completed by hardening task T029 and re-anchored to that SHA — not verified at HEAD 9bd3ab9.)
- **SC-007**: End-to-end processing of a 4-minute recording completes within 2 minutes of sealing. (Verified: ~30 seconds.)
- **SC-008**: Full automated backend and frontend suites pass with the feature active. (Verified: 907 backend, incl. 334 reconciliation, / 443 frontend — the 875 figure predates the FR-016 grounding lane.)

## Assumptions

- The reference corpus (a founder-read 50-utterance Russian script with English terms, and its 4-minute m4a recording) is representative of real capture behavior; per-utterance ground truth follows the script's own rule: one numbered utterance = one task.
- Roughly 30 of the 50 corpus utterances are actionable cold-start task creations; the rest are queries, modifications of existing tasks, or fillers, and correctly produce no new task in a cold-start dump.
- Split-vendor processing (one vendor for transcription, another for reconciliation) is an expected deployment configuration, not an edge case.
- Consent UX copy and structured task fields (deadlines, contexts, tags as first-class fields) remain out of scope; titles deliberately exclude those details.
- The legacy single-vendor consent field remains accepted for backward compatibility during migration.

## Out of Scope

- FR-016 residue only: the pronoun-binding self-correction case, edit-distance-3 proper-noun garbles, and one paraphrase class remain fail-closed (never guessed). The FR-016 tolerance itself is delivered; broadening this residue is future scope.
- Windowed/batched reconciliation calls (tested live 2026-07-29: +3 proposals for +21% cost and a reintroduced translation regression — explicitly rejected).
- Inferring structured fields (due dates, tags, projects, priority) from speech.
- Live streaming transcription vendor changes for the provisional preview track.
- A no-consent, on-device-only preview mode: today recording requires external-processing consent up front; offering a local-only capture mode without consent is future scope.
