# Feature Specification: Escape closes the Task menu first

**Feature Branch**: `paperclip/bra-1-escape-menu`
**Created**: 2026-08-04
**Status**: Authored after approved bounded planning review; pending independent ratification
**Input**: BRA-2, amended by BRA-6 after independent ratification findings

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Dismiss the nearest Task detail layer (Priority: P1)

A keyboard user viewing Task detail can dismiss the open Task menu without accidentally leaving the selected task. A subsequent Escape, when the menu is closed, retains the existing behavior of closing Task detail.

**Why this priority**: Escape must act on the nearest dismissible layer. Closing both the menu and its parent detail loses context and violates predictable keyboard behavior.

**Independent Test**: Open a known task detail and its Task menu, press Escape once, and verify the menu closes, the selected task route and `Task detail` heading remain, and focus returns to the Task menu button. Press Escape again and verify the existing detail-close navigation occurs.

**Acceptance Scenarios**:

1. **Given** Task detail for a selected task is open and its Task menu is open, **When** the user presses Escape, **Then** only the Task menu closes, the same task detail route and `Task detail` heading remain, and focus is restored to the Task menu button.
2. **Given** Task detail for a selected task is open and its Task menu is closed, **When** the user presses Escape from a target already eligible for the existing detail-close shortcut, **Then** the existing navigation to the current list route occurs unchanged.
3. **Given** Task detail and its Task menu are open, **When** one Escape keydown is handled, **Then** the parent detail-close handler does not also navigate for that same event.

### Negative Scenarios and Edge Cases

- Escape from an input, textarea, or select while the Task menu is closed remains owned by that control; this feature does not broaden the parent detail-close shortcut.
- An open modal dialog continues to own Escape instead of allowing Task detail to close underneath it; this is guarded by the unchanged `TaskListPage` exclusion and existing modal-owner tests.
- Non-Escape keys do not dismiss the Task menu.
- Closing the Task menu with Escape does not cancel, complete, reopen, move, or otherwise mutate the task.
- The behavior applies only while the non-terminal Task menu button and menu are rendered; terminal-task behavior is unchanged.
- Repeated Escape follows layer order: first press closes the open menu; a later press with the menu closed may close detail under the existing eligibility rules.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: When the Task menu is open, its Escape handling MUST close only that menu.
- **FR-002**: The Escape event that closes the Task menu MUST NOT trigger the parent Task detail close navigation.
- **FR-003**: Menu dismissal by Escape MUST preserve the selected task identifier, current Task detail route, and rendered `Task detail` heading.
- **FR-004**: After Escape closes the Task menu, keyboard focus MUST be restored to the `Task menu` button.
- **FR-005**: When the Task menu is closed, the existing eligible Escape-to-close-detail behavior in `TaskListPage` MUST remain unchanged, including its focused-field and modal exclusions.
- **FR-006**: The change MUST introduce no task mutation, persistence, API, authentication, privacy, observability, or routing-contract change beyond suppressing navigation for the menu-owned Escape event.

## Assumptions & Dependencies

- `frontend/src/features/tasks/TaskDetailPanel.tsx` owns Task menu open state and the `Task menu` button.
- `frontend/src/features/tasks/TaskListPage.tsx` owns document-level Escape navigation from selected Task detail to the current list route.
- Existing browser focus semantics and React refs are sufficient; no dependency or shared state is required.
- This localized keyboard behavior has no effect on capture → review → route/CRT, mobile interruption handling, data persistence, remote processing, or the approximately 200-node CRT canvas.

## Out of Scope

- Redesigning the Task menu, adding menu items, or changing Cancel task behavior.
- Changing which focused fields or dialogs own Escape when the menu is closed.
- Changing Task detail routes, list-route calculation, panel toggling, task lifecycle, or backend contracts.
- Adding global keyboard management infrastructure.

## Success Criteria *(mandatory)*

- **SC-001**: One targeted Testing Library regression test proves that a non-Escape key leaves the open Task menu in place and that a first Escape closes it, preserves the same detail route and `Task detail` heading, restores focus to the Task menu button, and does not navigate.
- **SC-002**: The same targeted behavioral test proves that focused-field ownership remains intact with the menu closed and that a later eligible Escape still closes Task detail through the existing route behavior.
- **SC-003**: No production files outside the existing Task detail/menu ownership path are required; a request-log checkpoint proves menu dismissal emits no additional request, including no task write.
- **SC-004**: Existing modal-owner coverage plus unchanged-parent-handler review proves an open modal retains Escape ownership, and the existing terminal-task route test explicitly proves no Task menu is rendered for a terminal task.

## Requirement → Acceptance Evidence

| Requirement | Planned evidence |
|---|---|
| FR-001, FR-002 | Targeted route-level Testing Library test: open menu, dispatch a non-Escape key and assert it remains open; dispatch Escape once, then assert `Cancel task` is absent and the detail route is unchanged. |
| FR-003 | In the same test, assert the selected task route is unchanged and the `Task detail` heading remains rendered after the first Escape. |
| FR-004 | In the same test, assert the accessible `Task menu` button has focus after the first Escape. |
| FR-005 | With the menu closed, focus the existing Title textarea and assert Escape preserves Task detail; then focus an eligible target and assert a later Escape returns to the pre-existing list route. Cite `BrainDumpOverlay.test.tsx` Escape ownership coverage and changed-path review of the unchanged `TaskListPage` modal exclusion. |
| FR-006 | Record the mocked-fetch call count after route/menu setup and assert the first Escape adds no request of any method; changed-path review confirms frontend-only localized scope. |
| Terminal-task negative scenario | Extend the existing `keeps terminal recovery explicit in task detail` route test to assert `Task menu` is absent for the terminal fixture. |
