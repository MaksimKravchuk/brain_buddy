# Specification Quality Checklist: Rust core and sync

**Purpose**: verify specification completeness before implementation approval.
**Created**: 2026-10-08. **Feature**: [spec.md](../spec.md).

## Content

- [x] The problem, user, value, scope, and non-goals are described.
- [x] User stories have independently testable outcomes; Given/When/Then scenarios include failures and recovery.
- [x] Behavior in the spec is separate from implementation in the plan/contract; Rust is an explicit user constraint.
- [x] FR and SC items are testable; proposed numerical budgets are not presented as measured results.
- [x] Consent/local-first, mobile, observability, and data-loss requirements are included.
- [x] Accepted Task/Review/Identity/CRT/A2A contracts are not rewritten without an identified ADR proposal.
- [x] Conflict, lost ACK, reset, retention, compatibility, and migration rules are described.
- [x] Shared Rust code is not used to claim that platform tests are unnecessary.
- [x] Assumptions and unconfirmed decisions are listed explicitly.

## Implementation readiness

- [ ] Human sign-off has been obtained for the new conflict/recovery screens in design.md.
- [ ] The proposed ADR and defaults (limits, retention, compatibility, cohort/platform order) have been accepted in the contract slice.
- [ ] The official planning review has an admissible verdict and current digest.
- [ ] A detailed PR-slice map has been agreed and analyze has run before coding.

These outstanding approvals do not prevent completing the requested specification as a Draft, but the package must not be presented as authorization to implement. Document checks and independent findings are recorded in [verification.md](../verification.md).
