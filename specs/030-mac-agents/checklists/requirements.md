# Specification Quality Checklist: Mac agents

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-16
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs) — requirements are
      behavioural; the Dependencies table and 030-FR-005/016/017 name existing endpoints
      and fields deliberately, because the feature may only show behaviour backed by the
      existing relay contract (030-FR-003) and Max fixed the data source (D3).
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain — the three open questions are recorded as
      pending clarifications (a) – (c) with recommended defaults, each naming the
      requirement and slice it changes
- [ ] Owner answered every question — D1 – D9 answered by Max on 2026-10-16; pending
      (a) groups for undrawn states, (b) Remove with the flag off, (c) open steps only
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded — out-of-scope list in intake.md § 4; follow-ups (Rust
      password rule, Rust list endpoint, native set-password, iPhone screens) recorded in
      spec.md § Follow-ups
- [x] Dependencies and assumptions identified (existing relay routes, 027 keeps them,
      028 PR-03 before the Settings and sidebar slices, the Python backend freeze)

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Constitution gates

- [x] Consent and safety: hand-off previews exactly what leaves BrainBuddy; agent text is
      inert; run content is memory-only and owner-keyed; 30-day expiry enforced
- [x] Principle II: reused checks named; new tests at the cheapest reliable level;
      test-first invariants named in plan.md
- [x] No backend change (D2); no new endpoint (D3); flag `external_agent_relay` kept
- [x] design.md is cited by plan.md and every UI slice

## Notes

- design.md, plan.md and tasks.md exist. Pending human gates: Max's answers to (a) – (c);
  design sign-off (design.md); the `/speckit-review` gate before implementation.
