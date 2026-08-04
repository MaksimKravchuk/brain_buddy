# Requirements quality checklist: Escape closes the Task menu first

**Purpose**: Verify that the single keyboard behavior is unambiguous and independently testable before ratification.
**Created**: 2026-08-04
**Feature**: `specs/006-escape-task-menu/spec.md`

## Observable behavior

- [x] The positive initial state names both open Task detail and open Task menu.
- [x] The first Escape outcome closes only the Task menu.
- [x] Route, selected task, and `Task detail` heading preservation are explicit.
- [x] Focus restoration names the accessible `Task menu` trigger.
- [x] The menu-closed Escape fallback is explicit and preserves current exclusions.
- [x] A single event cannot close both menu and detail.

## Negative scope

- [x] Non-Escape keys, terminal tasks, menu actions, and task mutations are unchanged.
- [x] Focused input/select/textarea and modal ownership are not broadened.
- [x] No backend, API, persistence, authentication, privacy, observability, route-contract, configuration, or CI change is implied.
- [x] Capture/review/route-to-CRT, mobile interruption, offline, data-loss, and CRT performance impacts are explicitly absent.

## Testability and traceability

- [x] One targeted behavioral test covers the complete first-Escape and second-Escape sequence.
- [x] Every FR maps to a named assertion in the requirement → evidence matrix.
- [x] The plan identifies concrete current source ownership and a bounded changed-path scope.
- [x] Tasks preserve RED → GREEN → verification order and required Allure taxonomy.
- [x] No unresolved clarification marker or template placeholder remains.

## Ratification Gate

- [ ] Independent planning review approves the package.
- [ ] A ratifier adds a validated `hermes-handoff.json`; the author must not self-ratify.
- [ ] `python3 scripts/check_spec_kit_specs.py` passes on the ratified package.

## Result

AUTHOR COMPLETE — observable intent and implementation evidence are specified; independent ratification and the validated handoff remain intentionally separate.
