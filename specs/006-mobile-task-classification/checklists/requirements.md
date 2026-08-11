# Specification Quality Checklist: Assign project and tags from the mobile task screen

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-08-10
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

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`

### What the first validation pass found and changed

**Scope was not bounded in the artifact that gets graded.** The non-goals were
confirmed by the human in the interview and written to `intake.md`, but the
spec carried only FR-014 ("no backend or web change"). The other three — bulk
assignment, project/tag management, and smart-add tokens — existed nowhere a
reviewer or the acceptance auditor reads. An "Out of scope" subsection was
added to the spec. The interview skill calls non-goals the highest-value
answers of the whole stage; losing them at the handoff to spec would have
wasted them.

### What the clarify session changed

Three items, two of them found by the repository's automated reviewer on the
pull request before the five-lens review had run at all.

**The spec was unimplementable as written.** AGENTS.md requires new production
behavior behind a server-owned flag defaulting to OFF; the spec forbade every
backend change. Nothing could satisfy both. `KNOWN_FEATURE_FLAGS` lives in
`backend/app/core/config.py`, which is *not* an ASK-classified path, so the
minimal flag wiring costs nothing against the path constraint — the conflict
was with a boundary the interview drew before that rule was checked. FR-015
added, FR-014 and the out-of-scope bullet narrowed to match.

**"Single-user deployment" was false.** The spec reasoned it from invite-gated
signup. `docs/auth.md` describes reusable invites, ordinary accounts and
per-owner isolation, and the mobile client persists a switchable server URL.
The consequence is not cosmetic: FR-011 had bounded the device queue by
sign-out alone, so pending content could survive an account or server change
and be displayed or replayed under the wrong identity. FR-011 now binds every
entry to its account and server, with SC-007 and two acceptance scenarios.

**Offline creation was an open assumption and is now a confirmed limit.**
FR-016 states it: creating a project or tag requires connectivity, and the
affordance is unavailable offline rather than failing after the person types a
name.

### Two judgements a reader should check rather than trust

**No numeric success criterion is claimed.** SC-001 through SC-006 are
observable but not numeric. The intake records an objective — complete inbox
triage from the phone — with an un-instrumented baseline. Rather than invent a
number the acceptance auditor cannot honestly grade, the spec states plainly
that none is claimed and carries the question to `/speckit-clarify`. If the
review panel considers a numeric target mandatory at this risk class, this is
the item to reject on.

**Three assumptions were derived rather than asked**, and each is labelled as
such in the spec: that queued changes survive an app restart (derived from
Principle V), that "connectivity returned" means the next successful request
while the app is in use, and that creating a project or tag requires
connectivity. The third is the consequential one — it narrows User Story 3
against User Story 2, so a person offline can attach existing classifications
but cannot invent new ones. That is a real limit on what the human asked for
and needs their confirmation in `/speckit-clarify`, not a reviewer's.
