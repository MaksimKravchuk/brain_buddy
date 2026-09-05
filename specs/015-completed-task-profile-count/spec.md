# Feature Specification: Completed Task Profile Count

**Feature Branch**: `015-completed-task-profile-count`

**Created**: 2026-09-05

**Status**: Awaiting owner ratification

**Input**: User description: "Add a completed-task counter to the user profile as a simple line of text and a number."

## User Scenarios & Testing

### User Story 1 - See current completed work in Profile (Priority: P1)

As a signed-in user, I can open Account settings and read how many of my current top-level tasks are completed without inspecting task lists.

**Why this priority**: this is the complete requested outcome; no secondary feature is needed to make it useful.

**Independent Test**: create a user with known task states, open that user's Web Profile, and compare the exact displayed number before completion, after completing one task, and after reopening it.

**Acceptance Scenarios**:

1. **Given** the signed-in user has no completed top-level tasks, **When** the Profile card loads, **Then** it shows `Completed tasks: 0`.
2. **Given** the user has two completed top-level tasks plus open, cancelled and subtask records, **When** the Profile card loads, **Then** it shows `Completed tasks: 2`.
3. **Given** another account owns completed tasks, **When** the signed-in user opens Profile, **Then** those tasks do not affect the number.
4. **Given** the user completes one open top-level task, **When** Profile is next observed, **Then** the number increases by one.
5. **Given** the user reopens one completed top-level task, **When** Profile is next observed, **Then** the number decreases by one.

### Edge Cases

- A new account and an account containing only open or cancelled tasks show zero.
- Completed subtasks do not affect the count because they are not top-level tasks.
- Deleting or purging owned tasks naturally changes the next derived count; no separate counter reconciliation exists.
- While the account request is pending, the Profile card shows `Completed tasks: …` immediately instead of inventing a number.
- If an authenticated account request fails with a non-401 error, the Profile card replaces the counter with `Completed tasks unavailable. Refresh the page to try again.` plus `(ref: <correlation-id>)` when present; it must not retain or fabricate a number. A 401 preserves the existing session-clear and `/login` redirect instead of retaining the Profile card.
- Concurrent task transitions are reflected by the next authoritative account read; the UI must not accumulate local deltas.
- Account profile and email mutations read the count before committing their write, so a task-store failure cannot report the account mutation as failed after it actually succeeded. Their returned count is the point-in-time value at that pre-mutation read; the next `GET /api/account` remains authoritative after concurrent task transitions.

## Requirements

### Functional Requirements

- **FR-001**: After a successful authoritative account response, the signed-in Web Profile MUST show one textual line with the exact format `Completed tasks: N`.
- **FR-002**: `N` MUST be a non-negative integer derived from tasks owned by the authenticated user.
- **FR-003**: The count MUST include only top-level tasks whose current state is `completed`.
- **FR-004**: Open, waiting, someday, inbox and cancelled tasks MUST NOT be counted.
- **FR-005**: Subtasks MUST NOT be counted, whether open, completed or cancelled.
- **FR-006**: Tasks owned by another user MUST NOT affect the response or displayed number.
- **FR-007**: Completing a top-level task MUST increase the next authoritative profile count by one, and reopening it MUST decrease the next authoritative profile count by one.
- **FR-008**: The value MUST be derived from existing task records; the feature MUST NOT introduce a stored aggregate, migration, background reconciliation or external provider.
- **FR-009**: Successful profile editing, authentication, account export/deletion and task lifecycle semantics MUST remain unchanged. The sole planned availability change is FR-012's fail-before-write behavior when the Tasks count query is unavailable.
- **FR-010**: While the account request is pending, the Profile card MUST expose an immediate polite status `Completed tasks: …`. On an authenticated non-401 account-response failure it MUST expose an alert `Completed tasks unavailable. Refresh the page to try again.` plus `(ref: <correlation-id>)` when present, and MUST NOT show a guessed or stale number. The existing profile form remains available and unchanged in both states. A 401 MUST preserve the existing session-clear and `/login` redirect.
- **FR-011**: New backend, frontend and browser product tests MUST carry `015-FR-nnn` references and the repository Allure epic/feature/story/title/named-step taxonomy.
- **FR-012**: The completed-task query MUST remain owned by the Tasks module and exposed through its public service boundary. Account mutations that return the additive field MUST obtain it before committing the account write; if that query fails, no profile or email mutation may be applied.

### Key Entities

- **Account profile projection**: the authenticated user's existing profile fields plus the derived completed-task count.
- **Top-level task**: an existing owner-scoped Task record; subtasks are separately owned records and are excluded.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Automated and browser evidence passes all four observable states: zero, exact nonzero, completion +1 and reopening -1.
- **SC-002**: A fixture containing completed tasks for two owners reports exactly the signed-in owner's total, with zero cross-owner records included.
- **SC-003**: Fixtures containing completed subtasks and cancelled top-level tasks contribute zero to the displayed total.
- **SC-004**: A representative user can locate and read the line in the existing Profile card without a new navigation step or interaction, and can distinguish its loading, unavailable and recovered states without a stale number.
- **SC-005**: Focused backend and frontend suites plus `make verify-all` pass on the exact candidate snapshot used for review.

## Assumptions

- The existing authenticated Account settings screen remains the intended meaning of “profile”.
- “Completed” means current task state, not the presence of a historical completion timestamp.
- Top-level tasks are the native Task records; separately stored task subtasks are excluded.
- The feature remains unpublished in the isolated acceptance worktree unless the owner separately authorizes release actions.
