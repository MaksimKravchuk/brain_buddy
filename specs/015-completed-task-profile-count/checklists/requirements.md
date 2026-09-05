# Requirements Checklist: Completed Task Profile Count

**Purpose**: Verify the planning package is implementation-ready without claiming implementation.
**Created**: 2026-09-05
**Feature**: [spec.md](../spec.md) · [design.md](../design.md) · [plan.md](../plan.md) · [tasks.md](../tasks.md)

## Scope and user outcome

- [x] CHK001 Exact Web Profile copy and placement are explicit.
- [x] CHK002 Zero, nonzero, complete +1 and reopen -1 states are independently observable.
- [x] CHK003 Current-state, owner-only and top-level-only semantics are unambiguous.
- [x] CHK004 Lifetime, cancelled, subtask, mobile, breakdown, gamification and release non-goals are explicit.

## Contract, privacy and failure behavior

- [x] CHK005 The additive Account response field and existing authenticated boundary are named.
- [x] CHK006 No stored aggregate, migration, provider, consent change or external call is allowed.
- [x] CHK007 Cross-owner tasks and user data in logs/evidence are prohibited.
- [x] CHK008 Loading and authenticated non-401 initial/refetch failure copy is explicit; failures preserve actionable correlation behavior without showing a cached or invented value, while 401 preserves redirect behavior.
- [x] CHK009 Successful profile mutation, authentication, data-rights and Task lifecycle semantics remain compatible; the sole availability change is explicit below.
- [x] CHK014 Tasks retains query ownership through its public service, and a failed task read prevents profile/email mutation before any account write commits.

## Design and evidence

- [x] CHK010 D-01-S01…D-01-S07 cover applicable loading, zero, nonzero, refresh, unavailable and unauthorized states.
- [x] CHK011 Responsive, keyboard, focus and accessibility impact is explicitly bounded.
- [x] CHK012 Backend, frontend and browser RED→GREEN tasks carry concrete paths and `015-FR-nnn`/Allure requirements, including the typed account-hook fixture.
- [x] CHK013 Full verification, independent review/PO, snapshot freshness and no-publication boundaries are retained.

## Result

Planning-quality self-check: **PASS**. Exact human ratification and the mandatory five-lens planning review remain gates before implementation.
