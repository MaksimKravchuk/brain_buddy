# Specification Quality Checklist: Transcript-first voice brain dump

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-05
**Feature**: [spec.md](../spec.md) · [intake.md](../intake.md)

Produced by the `/speckit-specify` quality validation and re-validated after the
`## Clarifications` session of 2026-09-05. Under the pinned v0.15.0 workflow
`/speckit-checklist` runs only after `plan.md` exists, so this file grades the
specification artifact alone: it claims nothing about design, plan, code or
runtime evidence.

## Content Quality

- [x] CHK001 No implementation details (languages, frameworks, APIs) — no endpoint, module, prompt name, status code or file of product code is named. "Browser preview", "accurate transcript", "task extraction" / "reconciler", "spend ceiling" and "provisional" are ADR-0002 product vocabulary already shown in the UI and used in `intake.md`; the commit ids in `**Status**` are provenance for the retro-spec, not implementation guidance.
- [x] CHK002 Focused on user value and business needs — every user story opens with the owner's situation; the six rows of the intake KPI table (§3) each map to a success criterion.
- [x] CHK003 Written for non-technical stakeholders — the reference utterance and expected tasks are quoted in the founder's words; the only governance terms are "hash-frozen" and "ADR-0002 amendment", both explained in `**Status**`.
- [x] CHK004 All mandatory sections completed — `## User Scenarios & Testing`, `## Requirements`, `## Success Criteria` carry the template headings in template order; `## Clarifications`, `## Out of Scope` and `## Assumptions` are filled, not placeholders.

## Requirement Completeness

- [x] CHK005 No [NEEDS CLARIFICATION] markers remain — zero markers; the seven open points were resolved as recorded, attributed decisions under `### Session 2026-09-05`.
- [x] CHK006 Requirements are testable and unambiguous — each FR names an observable behaviour; FR-004 enumerates its concrete cases (filler title, folded duplicate, affirmation, punctuation-variant revival, reason-only record); FR-008's "captured duration" is pinned by the sixth clarification (audio captured, pauses excluded).
- [x] CHK007 Success criteria are measurable — SC-001…SC-007 are counts or percentages with the intake baselines beside them.
- [x] CHK008 Success criteria are technology-agnostic (no implementation details) — they speak of tasks, cards, confirmations, renders and labels, never of components or services.
- [x] CHK009 All acceptance scenarios are defined — 23 Given/When/Then scenarios across four stories, each executable by a tester without reading code.
- [x] CHK010 Edge cases are identified — 15 edge cases, each tied to the FR it exercises, including the nine the founder's record calls for (filler-only, self-correction, restatement, consent withdrawn, ceiling reached, reload mid-recording, stale discard, browser without preview, mobile resume).
- [x] CHK011 Scope is clearly bounded — `**Status**` states exactly what is narrowed in spec 002; `## Out of Scope` lists six exclusions with their deciding clarification.
- [x] CHK012 Dependencies and assumptions identified — `## Assumptions` (single-user deployment, unchanged ceilings, no mobile preview lane, frozen 002, best-effort preview, consent precondition, unchanged retention) and the inherited cross-cutting constraints.

## Feature Readiness

- [x] CHK013 All functional requirements have clear acceptance criteria — trace: FR-001 → US2 #1, #4 and the browser-without-preview edge case; FR-002 → US2 #1, US3 #1, US4 #5 and the legacy-operation edge case; FR-003 → US1 #1, #4 and the mixed-language edge case; FR-004 → US1 #1, #3, #5 and the self-correction, restatement, affirmation, deleted-not-revived and dropped-item-record edge cases; FR-005 → US1 #2, US2 #3, #5 and the filler-only edge case; FR-006 → US2 #2, #4, US4 #4; FR-007 → US4 #1–#4, #6 and the stale-revision edge case; FR-008 → US4 #5 and the reload edge case; FR-009 → US3 #1–#7 and five edge cases; FR-010 → US3 #1, #2, #6 and the mobile-resume edge case; FR-011 → the legacy-operation edge case only (a stated condition and expected outcome, but no Given/When/Then story scenario — noted, accepted because the behaviour is unchanged from today).
- [x] CHK014 User scenarios cover primary flows — record → review → save (US1); speaking and processing status with the honest empty review (US2); recovery from a terminal failure on web and mobile (US3); the four destructive exits and resume (US4).
- [x] CHK015 Feature meets measurable outcomes defined in Success Criteria — SC-001 → US1; SC-002, SC-003 → US2; SC-006, SC-007 → US3; SC-004, SC-005 → US4; no criterion lacks a story and no story lacks a criterion.
- [x] CHK016 No implementation details leak into specification — scanned for service, status-code, route, module and framework names; none present.

## Notes

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`. None remain.
- Validation record — iteration 1 (after the first write): 15/16 passing; CHK013 failed because the FR-004 clause "dropped items MUST be recorded by reason, never by content" had no acceptance criterion. Fixed by adding the **Dropped-item record** edge case. Iteration 2: 16/16 passing.
- Re-validation after the `## Clarifications` session: 16/16 → 16/16; no item changed state, because the clarifications were written into the spec together with the requirements rather than replacing markers.
- The founder waived the interview and design sign-off gates («просто доделай»); the waiver is recorded in `intake.md` and in the seventh clarification so `/speckit-accept` and `/speckit-report` can see it. This checklist does not stand in for either gate.
- Requirement ids for tests are feature-qualified: `015-FR-001` … `015-FR-011`, `015-SC-001` … `015-SC-007`.
