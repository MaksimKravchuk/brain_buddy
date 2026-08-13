# Implementation Plan: Escape closes the Task menu first

**Branch**: `paperclip/bra-1-escape-menu` | **Date**: 2026-08-04 | **Spec**: `specs/009-escape-task-menu/spec.md`
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

*GATE: Passed after approved bounded review `0b6f2fc1`; independent ratification remains required.*

- **Spec workflow**: This package states the what/why, technical ownership, one testable story, a requirements checklist, and test-first tasks. It must be independently ratified before implementation handoff.
- **Consent & Safety**: No data, remote processing, persistence, credentials, or durable side effects are introduced.
- **Tests**: First extend the existing terminal-task route test with a characterization assertion that the menu is absent. Then write one targeted route-level Testing Library test and observe it failing because Escape currently reaches the document listener and closes Task detail. It proves menu-first dismissal, non-Escape delegation, focused-field ownership, no request side effect, and unchanged eligible menu-closed fallback. Existing modal-owner coverage plus unchanged-parent-handler review guards the modal exclusion.
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

## Targeted Behavioral Test Strategy

Use the established route-level Testing Library module with real `TaskListPage`/`TaskDetailPanel` behavior and its existing mocked-fetch request log:

1. Before the RED test, extend `keeps terminal recovery explicit in task detail` to assert the terminal fixture has no `Task menu`; observe that characterization guard pass before production edits.
2. Render a selected non-terminal task at a concrete detail route and record the current route/heading.
3. Open `Task menu`; verify `aria-expanded=true` and `Cancel task` is visible, then record the mocked-fetch call count after all route/menu setup requests settle.
4. Dispatch a representative non-Escape key and verify the menu remains open and the request count is unchanged.
5. Dispatch Escape and verify the menu is absent, the same task route and `Task detail` heading remain, the mocked-fetch call count is still unchanged (therefore no GET or write request occurred), and the `Task menu` button has focus.
6. Focus the existing Title textarea, dispatch Escape with the menu closed, and verify Task detail remains; then focus the menu button, dispatch a later Escape, and verify the existing navigation to the list route.
7. Retain the unchanged `TaskListPage` modal exclusion and cite the existing `BrainDumpOverlay.test.tsx` test `closes on Escape and on a click outside the panel when the overlay is dismissible` as evidence that the modal itself owns Escape.

The test must carry non-empty Allure `epic`, `feature`, `story`, a human-readable title, and at least one named step using `frontend/src/test/allureTaxonomy.ts`. The implementation card must record RED output before production edits and GREEN output afterward.

## Requirement → Evidence Matrix

| Requirement | Evidence assertion | Evidence location |
|---|---|---|
| FR-001 | menu remains for a non-Escape key; `Cancel task` disappears after first Escape | targeted Task route test |
| FR-002 | route does not change after first Escape | targeted Task route test |
| FR-003 | same task route and `Task detail` heading remain | targeted Task route test |
| FR-004 | `Task menu` trigger receives focus | targeted Task route test |
| FR-005 | focused Title Escape preserves detail; later eligible Escape navigates; modal owner coverage stays green while the parent handler remains unchanged | targeted Task route test, existing `BrainDumpOverlay.test.tsx` Escape test, changed-path review |
| FR-006 | mocked-fetch count is unchanged from the settled setup checkpoint through non-Escape and first-Escape handling; changed source scope stays localized | targeted Task route test plus changed-path review |
| Terminal negative | terminal fixture renders no `Task menu` | existing terminal recovery route test with one characterization assertion |

## Risks and Mitigations

- **Both handlers observe one Escape**: stop propagation in the menu-owned handler before document-level navigation; prove route stability after one keydown.
- **Focus is lost when menu unmounts**: restore focus to the stable trigger ref after closing; assert focus behavior.
- **Fallback regresses**: exercise focused-field exclusion and then an eligible later Escape after dismissal in the same behavioral test; retain the unchanged modal exclusion and its modal-owner test evidence.
- **Over-broad keyboard interception**: attach menu handling only while open; assert a non-Escape leaves the menu open, a focused Title owns Escape when the menu is closed, and terminal detail renders no menu.

## Release and Verification Gates

- Baseline-green terminal characterization, then focused RED and GREEN Vitest commands for the targeted behavior test.
- Focused frontend test file passes with required Allure taxonomy.
- Approved standard-risk bounded read-only planning review `0b6f2fc1` is recorded; the Architect resolves its evidence findings, authors and validates `hermes-handoff.json`, and hands the exact commit to independent ratification.
- `python3 scripts/check_spec_kit_specs.py` passes with the Architect-authored handoff present.
- Independent review confirms only planned frontend behavior changes and no production/config/CI/security scope drift.
- Feature is a localized UI fix with no feature flag or migration; normal repository delivery gates still apply.
