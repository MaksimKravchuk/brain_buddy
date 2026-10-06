# Specification Quality Checklist: Mac ↔ backend sync

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-10-06
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

- "macOS Keychain" (FR-005) is named on purpose: it states where a credential may and may not live, which is a security requirement, not a mechanism choice. How the Mac reuses the iPhone's sync behaviour (shared package or not) is left to `/speckit-plan`.
- "ADR-0020" is cited as the accepted decision this feature implements, not as an implementation detail.
- No [NEEDS CLARIFICATION] markers. Defaults taken instead (recorded in Assumptions or the requirement itself):
  - periodic fetch at least every 60 s while active (FR-006);
  - surface a failure after 60 s of continuous failure (FR-014);
  - keep the pre-upgrade store as a backup for ≥ 30 days (FR-021);
  - Mac review marks stay device-local (FR-023, owner-confirmed scope).
- Validation: iteration 1 (2026-10-06), all items pass.
- Validation: iteration 2 (2026-10-06, after planning review campaign `021-mac-sync-c1`; dispositions in `../review-c1-disposition.md`), all items still pass. The spec changed minimally, with FR and SC numbering kept and no owner decision (intake, Clarifications, design Sign-off) altered:
  - new **FR-033**: the upgrade runs at most once into an unwritten workspace; a previous-version store that appears later is kept untouched and the person is told once (review blocking finding F02). Testable by `LegacyStoreImporterTests`; observable as the X-05 "later file" notice;
  - one sentence each in FR-003 (both outcomes: the account's kept, the Mac's shown in full), FR-017 (the "Couldn't sign out" error and the FR-033 notice are allowed dialogs), FR-018 (sign-out names open sync issues) and FR-021 (without a sign-out the backup is kept);
  - two edge cases ("Same-named archived projects", "The previous Mac store appears again after the update"); US1's independent test no longer says "delete"; US2-5's example no longer assumes a project delete route; a cross-reference corrected (FR-001, FR-018);
  - Assumptions: the backup wording corrected, and what the upgrade does not carry (deleted tags, retry receipts, a comment's edited time) stated;
  - no [NEEDS CLARIFICATION] marker was added. Two product choices raised by the review (OQ-1, OQ-2) have recommended defaults recorded in plan.md and do not block.
