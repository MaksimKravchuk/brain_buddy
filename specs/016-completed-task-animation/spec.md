# Feature Specification: Completed task animation

**Feature Branch**: `016-completed-task-animation`
**Created**: 2026-09-06
**Status**: Narrowed to the owner's latest explicit scope.
**Input**: Animate completion. Open tasks appear first; completed tasks remain visible in a separate subdued section below.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See completed work move down (Priority: P1)

The owner checks a task and sees it become completed, then move into the Completed section without disappearing.

**Independent Test**: Complete a middle row, observe grey struck text and movement below open rows, then reload and find it again.

**Acceptance Scenarios**:
1. Given open and completed tasks in a fetched list, render open rows first and one Completed section after all open project groups.
2. Given an open row, when the existing save succeeds, show a check and grey struck title and animate the row to Completed.
3. Given a failed save, retain the open row and existing visible retry/recovery behavior; do not animate false success.
4. Given a completed row, its detail link and existing explicit reopen workflow remain available; reopening restores normal open presentation.
5. Given the same task appears in a project view, a tag view and search results, completing it in one view updates its shared status. Each matching view shows that same task in its Completed section, exactly once within that view.

### Edge Cases

- Empty, completed-only, grouped and paginated lists use the existing queries and controls.
- Newly loaded open rows join the open part above completed rows; each fetched task appears once.
- Detail-sheet completion uses the same canonical acknowledgement and final list presentation.
- Reduced motion suppresses movement. Keyboard completion keeps focus usable. Initial loads and filter navigation need no animation.
- Existing cancelled-history access remains available separately; cancelled work is not labelled Completed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Existing web task views MUST request completed items by default, partition loaded results into open tasks followed by a labelled Completed section, and keep existing sorting within each section and project grouping among open tasks. Completed titles MUST be grey and struck while remaining readable.
- **FR-002**: After canonical completion succeeds, the row MUST remain in the list and animate to its completed position within 600ms. Existing detail completion and reopen behavior MUST agree with the displayed section.
- **FR-003**: The change MUST preserve existing save/revision/idempotency, failure/recovery and query behavior, work at 390px and desktop widths, preserve keyboard focus/accessibility and honor reduced motion. Account switches MUST not paint the previous owner's task rows; late acknowledgements from an old scope MUST not update or animate the current scope.

### Key Entities

Task remains one existing entity with one canonical identity and status. Project and tags remain unchanged. Lists produced by searches and filters are overlapping views of tasks: the same task can appear in several views simultaneously. Open/Completed are presentation sections inside each view over existing state values; no storage or API redesign is introduced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Within each matching view, a completed task appears exactly once below all loaded open tasks with checked status and readable grey struck title. Its appearance in other matching views is allowed.
- **SC-002**: A successful completion visibly moves within 600ms; reduced motion has no movement, and a failed save has no successful transition.
- **SC-003**: The existing filtered project/tag/search views and reload still return/display completed tasks through existing include-completed behavior. Completing or reopening the same task in one view gives it the same canonical status in every other matching view. No new filters are introduced.
- **SC-004**: Named component and browser evidence covers completion, failure, grouping, loaded pages, detail/reopen, keyboard, mobile layout and account-switch/late-acknowledgement isolation; required CI and the standard production release succeed.

## Clarifications

- The owner's screenshots approve grey struck text and completed tasks at the bottom. Their initial request approves movement and keeping completed tasks visible.
- The latest owner instruction explicitly removes new search/filter capabilities from scope: only animation and placement by open/completed status belong in this task.
- The owner clarified that a task can belong to multiple lists produced by searches and filters. Completion changes the shared task status and its section within each matching view; it does not move task ownership to one exclusive list. Existing filters still determine which tasks belong in each result set.
- Project/tag/search logic and server pagination/order remain unchanged. Reuse existing include-completed query support; do not add origin metadata, new status parameters or multi-tag controls.
- The existing Show completed checkbox currently requests both completed and cancelled tasks. It becomes Show cancelled and controls cancelled inclusion alone. Completed work no longer has a hiding opt-out.
- This narrowly supersedes spec 011 FR-029's hidden completed history, FR-030's web/native presentation equivalence and ADR-0006's Show completed UI rule. API defaults, native mobile and open-work counters remain unchanged.
- Every fetched completed task is rendered with no new recency/count cutoff. The existing mixed 50-row page budget remains: unfetched open tasks may require Load more. No new server sorting or history limit belongs to the owner's narrowed scope.
- Completed headings appear only when at least one completed task is loaded. Existing open-work subtitles and counters retain open-only meaning.

## Assumptions

- Scope: existing web task-list presentation and canonical completion callbacks. Native mobile, backend, storage, new filters, search, voice, authentication protocol and deployment infrastructure are untouched. The widened task-list cache is scoped by account so a different owner cannot paint cached completed rows.
- Primary-loop impact: visible completed results. Capture, routing, CRT and provider processing are unchanged.
- Existing correlation IDs, errors, CI/smoke and image rollback are reused. On 2026-09-06 the owner explicitly confirmed no flag for this correction and requested the general rule that flags apply to significant new capabilities (agent harness, Brain dump, Current Reality Tree). This decision is recorded in AGENTS.md, ADR-0022 and the delivery runbook. The release-smoke-only delivery_canary is unchanged. The portable review still must pass before product implementation.

### Delivery prerequisite

The candidate also includes the demonstrated frontend manifest/lock compatibility repair required to execute the existing Node20 and Docker gates on current main. This includes runtime React Query and compiler/linter version changes, with no new advisory compared with HEAD. SC-004 requires the unchanged baseline, full validation, independent repair review and normal image rollback. This prerequisite adds no product feature; a UI-only forward revert must retain the validated dependency repair.

The existing browser report also requires a faithful reporting repair: use explicit named product steps and supported omission of automatic diagnostic detail. All original actions, assertions, attachments and tests remain; validators, thresholds and timing evidence stay unchanged. SC-004 requires independent statement-preservation review and fresh full Linux E2E evidence for this prerequisite.
