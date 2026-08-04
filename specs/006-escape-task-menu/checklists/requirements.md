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
- [x] Non-Escape, focused-field, modal-owner, terminal-task, and no-request outcomes map to explicit test or changed-path evidence.
- [x] No unresolved clarification marker or template placeholder remains.

## Ratification Gate

- [x] The Architect completed approved standard-risk bounded planning-review campaign `0b6f2fc1` and resolved its three evidence findings in the authored package.
- [x] The Architect authored and validated `hermes-handoff.json` against approved review `0b6f2fc1`; the read-only ratifier does not edit artifacts.
- [x] `python3 scripts/check_spec_kit_specs.py` passes before the exact authored SHA is handed to the independent ratifier.
- [ ] A separate ratifier reviews the exact authored SHA and records an approve/block receipt without editing the package.

## Result

AUTHORING COMPLETE — approved bounded review `0b6f2fc1` is recorded, its evidence findings are resolved, the handoff is valid, and the package is ready for exact-SHA independent ratification.
