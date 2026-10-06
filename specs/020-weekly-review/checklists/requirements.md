# Specification Quality Checklist: Weekly Review

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-05
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

- "Apple's on-device model" (FR-022, US3, Assumptions) is named on purpose. The owner chose it as a product requirement during the interview (privacy and offline), not as an implementation choice. Framework, API and storage details are left to `/speckit-plan`.
- FR-011 refers to "existing idempotent, owner-serialized task operations" as a must-not-break constraint from `CLAUDE.md`. It is not a design choice.
- No [NEEDS CLARIFICATION] markers. Every open point from the intake was either resolved with a documented default or recorded as an Assumption:
  - substantive title change → FR-002;
  - threshold-change retroactivity → FR-039;
  - post-release grace → FR-016 (anchored on the explainer since 2026-10-06);
  - receipts → FR-032;
  - Russian on-device support → Assumption plus fallback (FR-023).
- **Items for `/speckit-clarify`**, which are worth a human answer even though defaults exist:
  - Russian on-device support risk: if unverified at planning, is a server fallback for every Russian task acceptable?
  - Whether to adopt iOS 27 Foundation Models features or stay on the iOS 26 baseline.
  - The 30-day Someday receipt, versus 7 days in the macOS POC.
- Validation: iteration 1, all items pass.
- Validation: iteration 2 (2026-10-06, after planning-review campaign 1), all items pass. Re-checked against the amended spec:
  - The three owner answers (Clarifications "Session 2026-10-06") are reflected in FR-014, FR-016, FR-029, FR-033, FR-035, FR-036, FR-038, FR-051, US2-8, US4-8b and US4-9; FR-029 now defines completed, completed without activity, partial and abandoned, so "counts toward regularity" is testable.
  - The new requirements are plain-numbered (FR-051 explainer, FR-052 unsaved text), unique and gate-enforceable; no lettered FR ids exist.
  - New or amended requirements state observable behaviour (what the person sees, what is or is not recorded) and leave mechanisms to the plan; the few named mechanisms (browser leave warning, sheet dismissal) describe user-visible behaviour on each platform.
  - SC-001 and SC-004 now say how they are counted (counted reviews; active time), so they are measurable without implementation detail.
  - Edge cases added: review continued on two devices; the "Huge backlog on first use" and "Offline for a long time" cases now say exactly what is prevented and which actions win.
- Validation: iteration 3 (2026-10-06, after planning-review campaign 2), all items pass. Re-checked against the amended spec:
  - No new requirement was needed; every campaign-2 spec change sharpens an existing one (FR-002 cosmetic save is a decision, FR-005 "reached asks" incl. extension, FR-015 once-a-day rule, FR-017 restart anchor from onboarding, FR-021 project questions, FR-022 / US3 Mac wording, FR-024 revocable while the feature is off, FR-025 and Assumptions on cost caps, FR-029 leaving pauses, FR-030 interruption, FR-032 person-released tasks, FR-042 staged exposure, SC-002 counting rule, US2 independent test, US4-3 / US4-8 / US4-8a, the account-less edge case, Out of Scope for the web project entry). Ids stay FR-001 … FR-052 and SC-001 … SC-007, plain-numbered and unique; no lettered FR ids exist.
  - "Requirements are testable and unambiguous" was re-checked for the points campaign 2 found ambiguous: when a left review becomes partial or abandoned, what "reached asks for a decision" means after an extension, the restart anchor without any review, and whether a cosmetic save counts for SC-002 — each now has one observable answer.
  - "No implementation details" still holds: the amended text names what the person sees and what is recorded; mechanisms (keys, routes, stores) stay in the plan and contracts. The account-less release switch is stated as staged exposure, not as a build setting.
  - No owner decision was reversed (Clarifications 2026-10-05 and 2026-10-06, research "Owner decisions", design Sign-off 1–6).
