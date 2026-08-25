# Requirements Checklist: Web Task Title Autocomplete

**Purpose**: Verify the planning package is implementation-ready without claiming product implementation.
**Created**: 2026-08-25
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [design.md](../design.md) · [contract](../contracts/title-completions.md) · [tasks.md](../tasks.md)

Every checked item grades artifacts on disk, not code or runtime evidence. Implementation tasks remain unchecked.

## Scope and UX

- [x] CHK001 The existing title input is the only composer; exactly three below-input full-title candidates and no ghost text are explicit.
- [x] CHK002 Unscoped three-word and Project-scoped one-word thresholds are testable and use a defined word boundary.
- [x] CHK003 ArrowUp/Down, Enter draft-only acceptance, Escape dismissal, mouse parity, focus, Tab, and separate subsequent submit are specified.
- [x] CHK004 Smart Add/autocomplete arbitration has one deterministic keyboard owner and forbids stacked menus/generated completed Smart Add tokens.
- [x] CHK005 Web new-task-only scope and mobile, voice, title-edit, CRT, lifecycle, and durable-memory non-goals are explicit.
- [x] CHK006 Design states A-01…A-12 cover OFF, consent, threshold, debounce, loading, success, accept, dismiss, failure, and both keyboard owners.

## Contract and data boundaries

- [x] CHK007 Provider discovery, generation, and content-free acceptance observation have strict request/response/status contracts.
- [x] CHK008 Candidate validation is all-or-none and defines prefix preservation, uniqueness, length, line, count, and Smart Add safety.
- [x] CHK009 Context is limited to draft, same-owner active Project, and at most 50 ordered/deduplicated same-owner prior titles.
- [x] CHK010 No Task/detail/tag/comment/subtask/account/tree/other-owner data or suggestion/consent/history persistence is permitted.
- [x] CHK011 Existing Task create, Smart Add, title-edit, and storage contracts remain unchanged until normal submit.
- [x] CHK012 ADR-0021 resolves ADR-0019's fixed managed-set boundary and defines fresh/existing-volume OFF initialization.

## Privacy, threat, and observability

- [x] CHK013 Authentication, effective flag, current named-provider consent, configured capability, owner Project, threshold, and rate checks precede egress.
- [x] CHK014 False/mismatched consent, missing credentials, degraded/OFF flag, other-owner Project/history, and invalid provider output fail closed.
- [x] CHK015 Prohibited log/metric/evidence content and the narrow allowed observation vocabulary are explicit.
- [x] CHK016 Error bodies avoid provider exception/body reflection while retaining correlation IDs and actionable reason bands.
- [x] CHK017 Acceptance observation carries only random request ID/rank, is best effort, and cannot block input or touch Task persistence.

## Timing, failure, rollout, and evidence

- [x] CHK018 Debounce is 350 ms; cancellation triggers, sequence/snapshot stale suppression, old-result clearing, and residual upstream-cancel risk are defined.
- [x] CHK019 Rate is 20 generation requests per owner per rolling 60 seconds; provider timeout is 3 seconds with no retry.
- [x] CHK020 Safe unavailable preserves the draft and ordinary submission for timeout, 429, transport, provider, and invalid-output failures.
- [x] CHK021 Success, internal-only continuation band, hard stop triggers, and minimum pilot sample are measurable without Task text.
- [x] CHK022 Rollback is flag OFF first and explicitly leaves Tasks, Projects, submitted titles, and current unsaved draft untouched.
- [x] CHK023 Implementation is classified ASK/high with exact-SHA, independent review/QA, CI, explicit approval, and non-automatic landing preserved.
- [x] CHK024 Tasks name concrete source/test paths, RED→GREEN order, Allure/requirement qualifiers, relevant validators, and one focused candidate commit.

## Result

Planning quality gate: **PASS**. No product implementation, provider call, deployment, runtime flag mutation, or production data mutation is claimed.
