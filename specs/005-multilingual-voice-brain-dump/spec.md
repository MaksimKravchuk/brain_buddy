# Feature Specification: Stable Multilingual Voice Brain Dump

**Feature Branch**: `005-multilingual-voice-brain-dump`

**Created**: 2026-07-29

**Status**: Retroactive — documents behavior delivered and verified live on 2026-07-29; one follow-up scope item remains open (see FR-016 and Out of Scope)

**Input**: User description: "Stable multilingual voice brain dump: a founder records a stream-of-consciousness voice note in Russian, English, or code-switched speech, and BrainBuddy reliably turns it into individually reviewable, correctly split task proposals with full transcript provenance. The existing voice brain dump failed closed on real multilingual recordings — a real 4-minute Russian recording with English product terms produced zero committed tasks."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Multilingual dump becomes reviewable tasks (Priority: P1)

A founder records a several-minute stream-of-consciousness voice note mixing Russian and English (product names, tech terms) on their phone, stops the recording, and reviews a list of task proposals — one per spoken intent, titled in the language they spoke, each traceable to the exact utterance that produced it — then commits the ones they want into their Inbox.

**Why this priority**: This is the product's core capture ritual. Before this feature, a real multilingual recording produced zero committed tasks, which destroyed the trust loop the whole product depends on.

**Independent Test**: Record (or replay) the reference 4-minute Russian/English corpus recording, drive it through capture → review → commit, and count committed tasks and their languages.

**Acceptance Scenarios**:

1. **Given** a sealed recording of ~50 spoken utterances in Russian with embedded English terms, **When** processing completes, **Then** the review screen shows at least 15 task proposals, every title is in the language of its source utterance (never translated), and each proposal cites the utterance(s) it came from.
2. **Given** an utterance joining two nouns with a simple conjunction («Добавь молоко и хлеб в список покупок»), **When** proposals are generated, **Then** it yields exactly one task — never two.
3. **Given** an utterance that is a query or display request («Покажи все задачи на сегодня»), **When** proposals are generated, **Then** it yields no task.
4. **Given** the user commits the reviewed proposals, **When** they open their task list, **Then** every committed proposal appears as a task exactly once, even if commit is retried.

---

### User Story 2 - Consent names every vendor that touches the data (Priority: P2)

Before any audio or derived text leaves the device, the user sees and approves the actual named vendors that will process it — including when transcription and semantic reconciliation are handled by different vendors.

**Why this priority**: Consent integrity is a constitutional requirement (Principle I). Split-vendor processing is now the default configuration, so single-vendor consent would silently misrepresent where data goes.

**Independent Test**: Configure different transcription and reconciliation vendors, start a recording, and inspect the consent payload and the fail-closed behavior when consent names the wrong vendor.

**Acceptance Scenarios**:

1. **Given** the deployment has vendor A for transcription and vendor B for reconciliation, **When** the user grants consent, **Then** the consent names both vendors explicitly and the recording screen displayed the real configured vendor names (not a hardcoded label).
2. **Given** consent that names only vendor B, **When** the pipeline reaches the transcription step for vendor A, **Then** processing fails closed with an explicit consent-mismatch error and no audio leaves the device.
3. **Given** no external-processing consent at all, **When** the user records, **Then** only on-device provisional previews are produced and nothing is uploaded.

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
- Speech-to-text mishears proper nouns («BrainBuddy» → «BrentBuddy»): proposals ground against what was actually transcribed; garbled-noun tolerance is follow-up scope (FR-016) and until then such proposals fail closed rather than guessing.
- Self-corrections and disfluencies («в восемь, ой, лучше в восемь тридцать», «хотя нет, назначь её Максиму») currently fail closed; tolerance is follow-up scope (FR-016). Queries, fillers, and «не добавляй…» instructions correctly produce no task today.
- Transcription vendor quota exhaustion, auth failure, oversized audio, and malformed responses each surface as distinct allowlisted error codes; permanent conditions must not burn retry budgets.
- A long recording (30-minute cap) must survive provider latency: transcription timeouts are sized for multi-minute audio, and a crash between transcription and reconciliation resumes without paying for transcription twice.
- Consent withdrawal mid-operation, upload hash mismatch, stale-revision commands, and duplicate command replays keep their existing fail-closed / idempotent-replay semantics.
- Developer-machine configuration (a local `.env` enabling real vendors) must never leak into the automated test environment's deterministic providers.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST transcribe mixed-language (Russian/English code-switched) recordings without forcing a single language, preserving spoken proper nouns and embedded foreign terms.
- **FR-002**: The system MUST preserve utterance boundaries from transcription and record per-utterance provenance such that every task proposal cites the utterance(s) it derives from.
- **FR-003**: Task extraction MUST yield exactly one task per single-intent utterance by default; a simple conjunction («и», "and") within one intent MUST NOT split it.
- **FR-004**: Task extraction MUST NOT merge separately spoken utterances into one proposal unless they explicitly describe the same single action.
- **FR-005**: Queries, display requests, fillers, and explicit "don't add" instructions MUST NOT produce task proposals.
- **FR-006**: Proposal titles MUST be in the language of their cited source utterance; translation of titles is prohibited.
- **FR-007**: Titles MUST stay concise (core action + object); appended deadlines, contexts, tags, labels, and project names are excluded from titles (they remain future structured-field scope, which the system already refuses to infer).
- **FR-008**: Semantic verification MUST accept legitimate morphological variation of the source language (e.g., Russian imperative ↔ infinitive inflection) when judging whether a title is grounded in cited transcript evidence.
- **FR-009**: Semantic verification MUST continue to reject any proposal whose meaning is not traceable to its cited transcript evidence, including concrete-identity swaps, cross-clause action/target recombination, restoration of user-deleted proposals, and destructive removals without explicit destructive language. These guarantees MUST NOT be weakened to increase yield.
- **FR-010**: A single unverifiable proposal MUST be rejected individually without discarding verified sibling proposals; an entirely unverifiable batch MUST fail with an explicit validation error. Structural protocol violations (unknown identifiers, malformed operations) MUST still fail the whole batch.
- **FR-011**: External-processing consent MUST name every configured vendor that will process the recording or its derived text; each pipeline stage MUST verify its own vendor is within the consented set and fail closed on mismatch before data leaves the device.
- **FR-012**: The recording interface MUST display the actual configured vendor names for consent, discovered from the deployment configuration, not hardcoded.
- **FR-013**: Provider failures MUST surface as allowlisted, actionable error codes; permanent conditions (quota exhaustion, invalid credentials, unsupported audio) MUST be classified terminal without burning retry budgets, and transient conditions MUST retry within bounded budgets.
- **FR-014**: The automated test environment MUST be hermetic against developer-machine provider configuration: local environment files MUST NOT alter test-environment provider selection.
- **FR-015**: Committing reviewed proposals MUST atomically create exactly the reviewed tasks, idempotent under command replay, consistent with the existing operation contract.
- **FR-016** *(open follow-up)*: Semantic verification SHOULD additionally tolerate (a) titles drawing modifier details from multiple clauses of the same cited utterance, (b) mid-utterance self-corrections, preferring the corrected value, and (c) transcription-garbled proper nouns, without weakening FR-009. Until delivered, these classes fail closed (measured cost: roughly one third of real-dump proposals).

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
- **SC-003**: Zero proposal titles are translated out of the source utterance's language on the reference corpus. (Verified: 0 across all shapes; prior: 9 of 50.)
- **SC-004**: Zero utterances are split on a simple conjunction within one intent on the reference corpus. (Verified: 0.)
- **SC-005**: A batch containing at least one unverifiable proposal still delivers every verified sibling. (Verified: skip semantics live in production shape.)
- **SC-006**: A consent set that omits the configured transcription vendor produces a fail-closed consent-mismatch error and no audio upload. (Verified live.)
- **SC-007**: End-to-end processing of a 4-minute recording completes within 2 minutes of sealing. (Verified: ~30 seconds.)
- **SC-008**: Full automated backend and frontend suites pass with the feature active. (Verified: 875 backend / 443 frontend.)

## Assumptions

- The reference corpus (a founder-read 50-utterance Russian script with English terms, and its 4-minute m4a recording) is representative of real capture behavior; per-utterance ground truth follows the script's own rule: one numbered utterance = one task.
- Roughly 30 of the 50 corpus utterances are actionable cold-start task creations; the rest are queries, modifications of existing tasks, or fillers, and correctly produce no new task in a cold-start dump.
- Split-vendor processing (one vendor for transcription, another for reconciliation) is an expected deployment configuration, not an edge case.
- Consent UX copy and structured task fields (deadlines, contexts, tags as first-class fields) remain out of scope; titles deliberately exclude those details.
- The legacy single-vendor consent field remains accepted for backward compatibility during migration.

## Out of Scope

- FR-016 implementation (multi-clause modifier grounding, self-correction tolerance, garbled-proper-noun tolerance) — tracked as the follow-up lane; everything else in this spec is delivered.
- Windowed/batched reconciliation calls (tested live 2026-07-29: +3 proposals for +21% cost and a reintroduced translation regression — explicitly rejected).
- Inferring structured fields (due dates, tags, projects, priority) from speech.
- Live streaming transcription vendor changes for the provisional preview track.
