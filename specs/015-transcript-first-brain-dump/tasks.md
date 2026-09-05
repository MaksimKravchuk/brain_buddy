# Tasks: Transcript-first voice brain dump

**Feature**: `specs/015-transcript-first-brain-dump/` · **Branch**: `claude/brain-dump-mechanics-t35ab7` (PR #194) · **Plan**: [plan.md](plan.md) · **Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md)

Retro task list: the implementation already landed on this branch. A task is ticked only where it names the landed commit and the test that proves it; tests carry `015-FR-…` / `015-SC-…` ids (`python3 scripts/check_requirement_coverage.py specs/015-transcript-first-brain-dump` → 18/18). Delivery gates (isolated worktree, tests first, independent acceptance, ADR-0008 landing, CI) are not bypassed by this file.

## Phase 1 — Foundations

- [x] T001 ADR-0002 amendments (preview is a transcript readout; `reconcile_preview`) — `12814a7`, `9f9ae3b`; `docs/decisions/0002-async-voice-operation-substrate.md`.
- [x] T002 Persist preview segments only in `append_brain_dump_transcript` — `12814a7`; `test_brain_dump_operations_api.py::test_transcript_append_records_segments_without_deriving_draft_tasks`, `…interim_and_final_segments_persist_without_draft_tasks` (FR-002, SC-002).
- [x] T003 Keep lineage, lock and conflict rules for pre-existing proposals — `12814a7`, `252fa01`; `test_brain_dump_operations_api.py` seeded-proposal tests, `test_commit_rejects_an_untouched_fast_proposal_after_a_successful_reconcile` (FR-011).

## Phase 2 — US1 Clean next actions

- [x] T004 Prompt `brain-dump-reconciler-v3` (verb-first, language kept, fillers dropped) — `12814a7`; `test_voice_brain_dump_reconciliation.py::test_openai_reconciler_v3_prompt_locks_language_gtd_phrasing_and_template`, GTD grounding parametrized test (FR-003).
- [x] T005 Filler-only titles dropped; all-filler envelope fails closed — `12814a7`, `252fa01`; `…filler_only_titles_are_dropped…`, `…envelope_made_only_of_fillers_fails_closed…` (FR-004, SC-003).
- [x] T006 Duplicates folded with provenance; add restating an active proposal becomes an affirmation — `252fa01`; `…duplicate_titles_within_one_reconciliation_collapse…`, `…folds_its_provenance…`, `…affirms_it_instead_of_minting_a_twin` (FR-004).
- [x] T007 Deleted task not revived under a punctuation variant — `252fa01`; `…cannot_be_restored_under_a_punctuation_variant` (FR-004).
- [x] T008 Structural duplicate folds its predecessors (Codex finding) — `9f9ae3b`; `…structural_duplicate_folds_its_predecessors…`, `…two_structural_duplicates_merge_every_predecessor…` (FR-004).
- [x] T009 Reference utterance → exactly three tasks, committable, saved to Inbox — `12814a7`; `test_brain_dump_operations_api.py::test_seal_reconciles_a_filler_prefixed_dump_into_clean_next_actions` (FR-005, SC-001).

## Phase 3 — US2 Raw text is a status

- [x] T010 Web transcript readout and live tail; no draft cards — `12814a7`, `252fa01`; `BrainDumpRoute.test.tsx` "records through browser microphone and shows the running transcript…", "replaces an interim speech result…"; Compose e2e voice happy path (FR-001, SC-002).
- [x] T011 Processing surface names the stage and shows the transcript — `12814a7`, `252fa01`; `BrainDumpRoute.test.tsx` "shows schema-v2 processing stages…", "falls back to the browser preview transcript…" (FR-006).
- [x] T012 Empty review is not committable (server) — `252fa01`; `test_brain_dump_operations_api.py::test_review_with_no_surviving_proposals_is_not_committable` (FR-005, SC-003).
- [x] T013 Web empty review and loading state — `252fa01`, `fc6d13b`; `BrainDumpRoute.test.tsx` "keeps empty review commands as no-ops…", "tells an empty review that discarding is the way back…" (FR-005).
- [x] T014 Mobile empty review (no Confirm, "What was heard") — `43ae843`; `review.test.tsx` "says nothing was proposed, shows what was heard, and offers no confirm…" (FR-005).
- [x] T015 Compose e2e rewritten for the transcript-first flow — `12814a7`, `50369bc`; `native-tasks-voice-brain-dump.compose.spec.ts` (FR-001, FR-003, FR-005).

## Phase 4 — US3 Recovery from the browser transcript

- [x] T016 Domain: `browser_preview_recovery_hypotheses`, checkpoint literals — `9f9ae3b`; `test_voice_brain_dump_reconciliation.py::test_browser_preview_recovery_hypotheses_keep_only_stable_unsuperseded_preview_text` (FR-009).
- [x] T017 Predicate `can_reconcile_brain_dump_preview` (state, consent, cost, one shot) — `9f9ae3b`; `test_voice_brain_dump_recovery.py::test_015_FR_009_preview_recovery_predicate_requires_every_clause`, mutual exclusion with `review_provisional` (FR-009).
- [x] T018 Command `reconcile_brain_dump_preview` (idempotent, revision-checked, refusals) — `9f9ae3b`; `…queues_one_provisional_reconciler_run`, refusal tests for consent, provider mismatch and cost cap (FR-009).
- [x] T019 Runner feeds exactly the stable preview text; result `provisional_only` + `manual_review`; canonical gate unsatisfiable — `9f9ae3b`; `…runner_reconciles_exactly_the_stable_unsuperseded_preview_text`, `…never_satisfies_the_canonical_accurate_gate` (FR-009, FR-010).
- [x] T020 Retry over preview text; terminal failure leaves cancel only — `9f9ae3b`; `…retryable_failure_retries_over_preview_text_not_audio`, `…terminal_failure_leaves_only_cancel` (FR-009).
- [x] T021 Commit creates Inbox tasks with provisional receipts — `9f9ae3b`; `…commit_creates_inbox_tasks_with_provisional_receipts` (FR-009, SC-006).
- [x] T022 API dispatch, projection, flag gating — `9f9ae3b`; `test_brain_dump_operations_api.py::test_015_FR_009_reconcile_preview_recovers_provisional_tasks_from_browser_preview_text`, `…is_flag_gated…`, `…rejects_a_stale_expected_revision` (FR-009, SC-006).
- [x] T023 Web recovery button and provisional banner regardless of committability — `9f9ae3b`; `BrainDumpRoute.test.tsx` "extracts tasks from the browser transcript when the server offers reconcile_preview", "enables Save for an explicitly reviewed provisional operation" (FR-009, FR-010, SC-007).
- [x] T024 Mobile recovery button and badge — `a1f0d2e`; `review.test.tsx` "offers to extract tasks from the browser transcript…", "posts reconcile_preview with the current revision…" (FR-009, FR-010, SC-006, SC-007).
- [x] T025 Refusal shows the server reason and reference id — `fc6d13b`; `BrainDumpRoute.test.tsx` "shows the server's refusal and its reference, not the HTTP status…" (FR-009).

## Phase 5 — US4 Safe exits and resume

- [x] T026 Web inline confirmations for Discard, Discard all, Delete recording — `051cec1`; `BrainDumpRoute.test.tsx` "asks before discarding a recording…", "closes the discard question on Escape…", "asks before discarding all reviewed tasks…", "asks before deleting a failed recording…" (FR-007, SC-004).
- [x] T027 Cancel processing with confirmation — `051cec1`; "lets the user cancel processing after confirming…", "keeps processing when the cancel question is declined" (FR-006, FR-007, SC-004).
- [x] T028 Resume seeds the tail and the timer — `051cec1`; "seeds the live tail and the timer from a resumed recording", "starts the capture timer at zero for a recording begun in this session" (FR-008, SC-005).
- [x] T029 Mobile platform-dialog confirmations, header rename, "Delete retained audio" — `43ae843`; `review.test.tsx` "asks before discarding a failed recording…", "asks before discarding all from the review sheet…", "names the header control as a discard…" (FR-007, SC-004).
- [x] T030 Conflict count explains a disabled Send — `fc6d13b`; "counts the conflicts blocking Send beside the button…" (FR-011).
- [x] T031 Compose e2e confirmation steps — `051cec1`; `native-tasks-voice-brain-dump.compose.spec.ts` "discarding the review is confirmed inline…" (FR-007).

## Phase 6 — Verification and closure

- [x] T032 Requirement markers on all suites — `9f9ae3b`, `43ae843`, `fc6d13b`; `check_requirement_coverage.py` 18/18.
- [x] T033 CI green on `5ffff85` (all lanes incl. Compose e2e, mutation gate) and on `0a06a5b`.
- [x] T034 Review campaign 1 run; findings recorded in [spec.md](spec.md) Open items.
- [ ] T035 Founder decisions on the five Open items and, if wanted, the high-risk sign-off record for a second campaign.
- [ ] T036 `/speckit-accept` and `/speckit-report` — not run (founder, 2026-09-05); run them if the spec is to be marked delivered.
