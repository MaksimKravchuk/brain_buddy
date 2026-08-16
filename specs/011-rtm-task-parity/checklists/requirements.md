# Requirements checklist: RTM task-management parity

**Feature**: `specs/011-rtm-task-parity/` | **Generated**: 2026-08-15
**Purpose**: gate the repaired package before campaign 2. Every item is checked
because it was verified against the artifacts, not because it was assumed.

## Requirement quality

- [x] Every functional requirement is stated as observable behavior, not implementation.
- [x] Requirement ids are unique and zero-padded (FR-001…FR-039, SC-001…SC-015).
- [x] No unresolved clarification markers remain in `spec.md`.
- [x] No placeholder text remains in `spec.md`, `design.md`, `plan.md` or `tasks.md`.
- [x] Every FR traces to at least one user story or to a named cross-cutting constraint.
- [x] Every FR traces forward to at least one task in `tasks.md`.
- [x] Success criteria are measurable and outcome-focused (SC-001…SC-015); operational
      and rendered-evidence criteria name the evidence needed to authorize their gates.
- [x] Each success criterion names a countable outcome rather than "works correctly".

## Scope discipline

- [x] The P0 scope matches the frozen scope in `intake.md` with nothing added.
- [x] Every P0 gap in `capability-matrix.md` is covered by an FR; none is marked out of
      scope to avoid work.
- [x] P1 items are specified only as backlog, with dependencies and acceptance criteria, and
      are not implemented in this tranche.
- [x] P2 items are product decisions in `p2-decisions.md`, each with value, size/risk,
      dependencies and a recommendation.
- [x] Non-goals are stated explicitly, including that RTM is a reference model and not an
      integration target.

## Current-behavior evidence

- [x] Every "PASS current" row in `capability-matrix.md` is backed by an executed test or an
      executed behavior probe, not by reading source alone.
- [x] The executed evidence is named and reproducible (the 41-passed pytest selection and
      the recorded probe observations).
- [x] Divergences between current behavior and the target contract are labelled DIVERGENT
      rather than folded into ABSENT.
- [x] Behavior that already matches the target (tag global delete, cursor filter binding,
      Inbox as a virtual projection) is recorded as PASS and not re-specified as new work.

## Consistency and authority

- [x] One fact has one authoritative home; current behavior lives only in
      `capability-matrix.md` and other artifacts cite row ids.
- [x] `plan.md` cites `design.md`, as the constitution requires for a user-visible surface.
- [x] Conflicts with ADR-0006 are named, resolved by Max on 2026-08-15, and narrowly
      superseded by accepted ADR-0020 without rewriting ADR-0006 history.
- [x] Max accepted numbered design states for planning (HD-09); SC-015/T-039 require
      screenshots and keyboard/screen-reader video before acceptance.
- [x] The interview stage's provenance limit (projected from a written brief, not elicited)
      is stated; portable brief/reference provenance is embedded in `research.md` and no
      artifact depends on an absolute local path.
- [x] Every campaign-1 finding is carried into digest-visible `research.md`: all 15 blocking
      findings resolved, all 18 important findings explicitly dispositioned, and all 6
      advisory findings recorded.

## Constitution and cross-cutting

- [x] Consent and privacy impact assessed: no new remote processing/egress; FR-035…FR-038
      define Trash retention, immediate name/content erasure, IDs/action/time-only audit,
      export, compatibility mirrors and account purge.
- [x] Owner scoping and 404-not-403 semantics are required for every new surface (FR-031).
- [x] Correlation ids and actionable sanitized errors are required on every success/replay/
      failure surface and are never authorization or idempotency inputs (FR-016, SC-013).
- [x] Mobile-first resilience states are specified for every new surface (`design.md`).
- [x] Every P0 mutation is enumerated under one 24-hour retry/key-conflict contract;
      destructive replay remains a durable no-op without resurrection (FR-015).
- [x] The agent Execution/Run separation is stated as an invariant with its own requirement
      and success criterion (FR-032, SC-010).
- [x] The existing Voice Brain Dump / Smart Add / idempotency-recovery behavior is protected
      by a requirement and a per-slice regression gate (FR-033, SC-011).

## Delivery readiness

- [x] Risk class is derived and stated as high, with the reason (data migration).
- [x] Ship/Show/Ask classification is stated: every implementation slice is ASK-class.
- [x] Rollout/rollback model SQLite JSON payloads plus write-through mirrors, crash recovery,
      safe stale-client fallback, installed-build evidence ownership and inverse rewrite
      before old-image eligibility.
- [x] Test strategy names the runner, the location and the feature-qualified requirement id
      convention for each tier.
- [x] Evidence classes (local tests, independent review, CI, merge, deploy) are required to
      stay distinct in the final report.
- [x] The readiness claim is truthful: package is ready for campaign 2, not implementation;
      high risk has no HD-10 run/digest sign-off, so a technically clean campaign remains
      `escalated` until a named human signs that exact digest.
