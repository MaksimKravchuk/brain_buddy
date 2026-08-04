# Implementation Plan: Escape closes the Task menu first

**Branch**: `paperclip/bra-1-escape-menu` | **Date**: 2026-08-04 | **Spec**: `specs/006-escape-task-menu/spec.md`
**Input**: BRA-2 and the repository behavior at `TaskDetailPanel.tsx:89-139` and `TaskListPage.tsx:123-142`

## Summary

Give the Task menu first ownership of Escape while it is open. The menu closes, suppresses the same key event from reaching the document-level detail-close behavior, and restores focus to its trigger. With the menu closed, preserve the existing Task detail Escape navigation and exclusions exactly.

## Technical Context

**Language/Version**: TypeScript strict, React 18
**Primary Dependencies**: Existing React hooks and browser keyboard/focus APIs; no new dependency
**Storage**: N/A
**Testing**: Vitest + Testing Library with the central Allure taxonomy helper
**Target Platform**: Existing responsive web Task detail surface
**Project Type**: Frontend slice in the FastAPI + React modular monolith
**Performance Goals**: Synchronous dismissal with no network request or perceptible delay
**Constraints**: One behavioral change; preserve route, heading, task state, parent Escape exclusions, and existing menu actions
**Scale/Scope**: One menu trigger, one menu surface, and the existing route-level Escape handler

## Constitution Check

*GATE: Passed for planning; independent ratification remains required.*

- **Spec workflow**: This package states the what/why, technical ownership, one testable story, a requirements checklist, and test-first tasks. It must be independently ratified before implementation handoff.
- **Consent & Safety**: No data, remote processing, persistence, credentials, or durable side effects are introduced.
- **Tests**: One targeted route-level Testing Library test is written first and observed failing because Escape currently reaches the document listener and closes Task detail. It then proves both menu-first dismissal and unchanged menu-closed fallback.
- **Contracts**: No API, schema, route shape, lifecycle, or persistence contract changes. This refines keyboard ownership inside the existing Task detail UI.
- **Observability**: No request or operation occurs, so correlation IDs and logs are unaffected.
- **Mobile/resilience/performance**: Keyboard-only behavior adds no mobile flow, offline state, data-loss risk, or CRT performance work; responsive layout remains unchanged.
- **Delivery boundary**: Spec Kit artifacts are planning input only. Hermes Kanban, isolated worktrees, TDD, independent review, CI, landing, and release gates remain authoritative.

## Architecture and Ownership

`TaskDetailPanel` already owns `menuOpen`; it is therefore the narrow owner for menu-level Escape behavior and trigger focus restoration. The implementation should keep a ref to the existing `Task menu` button and handle Escape only while `menuOpen` is true. The handled event must be prevented from producing default behavior and stopped before the document-level listener can execute for that keydown.

`TaskListPage` remains the owner of Escape-to-close-detail navigation. Its current list target calculation and focused-field/modal exclusions remain unchanged. No new global keyboard coordinator, store state, context, route, or backend contract is justified.

## Planned Source Scope

```text
frontend/src/features/tasks/TaskDetailPanel.tsx  # menu-owned Escape and trigger focus restoration
frontend/src/app/AppRoutes.test.tsx               # established route-level behavioral test module
```

The existing `frontend/src/app/AppRoutes.test.tsx` route fixture already renders real Task routes and owns the relevant API/router setup. Extend that module rather than creating a duplicate task fixture module. No other production path is planned.

## Single Targeted Behavioral Test Strategy

Use one route-level Testing Library test with real `TaskListPage`/`TaskDetailPanel` behavior and the smallest existing API/router fixture:

1. Render a selected non-terminal task at a concrete detail route and record the current route/heading.
2. Open `Task menu`; verify `aria-expanded=true` and `Cancel task` is visible.
3. Dispatch Escape and verify the menu is absent, the same task route and `Task detail` heading remain, no mutation client was called, and the `Task menu` button has focus.
4. Dispatch Escape again with the menu closed and verify the existing navigation to the list route.

The test must carry non-empty Allure `epic`, `feature`, `story`, a human-readable title, and at least one named step using `frontend/src/test/allureTaxonomy.ts`. The implementation card must record RED output before production edits and GREEN output afterward.

## Requirement → Evidence Matrix

| Requirement | Evidence assertion | Evidence location |
|---|---|---|
| FR-001 | `Cancel task` disappears after first Escape | targeted Task route test |
| FR-002 | route does not change after first Escape | targeted Task route test |
| FR-003 | same task route and `Task detail` heading remain | targeted Task route test |
| FR-004 | `Task menu` trigger receives focus | targeted Task route test |
| FR-005 | second Escape navigates to existing list target | targeted Task route test |
| FR-006 | no mutation client call; changed source scope stays localized | targeted test plus changed-path review |

## Risks and Mitigations

- **Both handlers observe one Escape**: stop propagation in the menu-owned handler before document-level navigation; prove route stability after one keydown.
- **Focus is lost when menu unmounts**: restore focus to the stable trigger ref after closing; assert focus behavior.
- **Fallback regresses**: exercise a second Escape after dismissal in the same behavioral test.
- **Over-broad keyboard interception**: attach menu handling only while open and assert non-Escape/menu-closed behavior remains delegated.

## Release and Verification Gates

- Focused RED then GREEN Vitest command for the targeted test.
- Focused frontend test file passes with required Allure taxonomy.
- The Architect runs the bounded read-only planning-review campaign, resolves technical findings, authors and validates `hermes-handoff.json`, and records the approved run before independent ratification.
- `python3 scripts/check_spec_kit_specs.py` passes with the Architect-authored handoff present.
- Independent review confirms only planned frontend behavior changes and no production/config/CI/security scope drift.
- Feature is a localized UI fix with no feature flag or migration; normal repository delivery gates still apply.
