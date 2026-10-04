# Implementation Plan: Compact Task Rows

**Branch**: `codex/compact-task-rows` | **Date**: 2026-09-10 | **Spec**: `specs/017-compact-task-rows/spec.md`

**Input**: Feature specification and approved visual direction from
`specs/017-compact-task-rows/spec.md` and `specs/017-compact-task-rows/design.md`.

## Summary

Replace the desktop Task card stack with exact 44 px hairline rows, insert the
existing route-backed `TaskDetailPanel` below the selected row, and add a compact
agent rail. Before assignment the rail is a split robot/chooser control backed by
the existing eligible-connections query and immutable hand-off review. After a run
exists it becomes a single 184 × 28 px state control with no chooser. The server
contract, relay confirmation boundary, Task lifecycle, and native mobile client do
not change.

## Technical Context

**Language/Version**: TypeScript strict, React 19, Vite

**Primary Dependencies**: React Router, TanStack React Query, Zustand, Tailwind,
Lucide React; all already present. Add `@axe-core/playwright` as the smallest executable
serious/critical accessibility-audit dependency required by SC-004.

**Storage**: Existing server data unchanged; one `localStorage` value keyed by API
origin and owner ID stores JSON `{connectionId, confirmedAt}`. A global feature-key
sweep on startup/focus/interval and auth-transition cleanup bound its eligibility.

**Testing**: Vitest + Testing Library with the repository Allure taxonomy helper;
existing Playwright smoke/product coverage where the Task list journey is affected

**Target Platform**: Desktop responsive web, with a 768 px supported desktop floor
and a 390 × 851 responsive-web check; native mobile is out of scope

**Project Type**: Existing React web client in a backend/frontend/mobile monorepo

**Performance Goals**: Ten 44 px collapsed rows remain visible in the ordinary
1440 × 900 list area; agent summary or connection reads never block Task rendering

**Constraints**: No new endpoint/request shape, provider call, backend persistence,
feature flag, or native-mobile change; preserve existing review/confirmation and
autosave state machines. One test-only accessibility dependency is necessary for the
severity-classified SC-004 gate.

**Scale/Scope**: One desktop Task-list surface, one reused detail surface, one
compact agent-control component, and targeted frontend tests

## Constitution Check

*GATE: Passed before Phase 0 and re-checked after Phase 1.*

| Principle | Assessment |
|---|---|
| Spec workflow | `intake.md`, `spec.md`, checked requirements, and approved `design.md` exist. The plan cites D-01 through D-04. Implementation waits for the ADR-0011 review verdict. |
| Data consent & safety | The row shortcut only preselects the existing immutable hand-off review; no Task content leaves on row activation. The browser preference stores only owner/API-scoped connection ID plus confirmation time and grants no authority; auth and global expiry sweeps remove eligible residue under FR-008. |
| Tested delivery | Targeted Vitest tests fail first for row geometry, inline routing/focus, split selection, no pre-review dispatch, compact truthful labels, rollout OFF, and recovery. Existing Task/relay suites remain gates. |
| Contract-first interfaces | No backend schema, endpoint, event, or shared response changes. The frontend consumes the existing `AgentConnectionResponse`, `AgentRunSummaryResponse`, Task route, and review seed. |
| Observability | Existing API errors and correlation IDs remain owned by the Task/relay detail and review surfaces. No new log or metric contains user content. |
| Responsive/resilient | D-01-S10–S17, D-02-S03–S16, D-03-S07–S26, and D-04-S01–S09 cover loading, partial failure, offline, long content, keyboard/focus, and 390 px responsive web. Native mobile and CRT performance are N/A because their code and surface do not change. |
| Delivery boundary | Work is on isolated branch `codex/compact-task-rows`; TDD, Spec Kit review, CI, exact-SHA landing, and production evidence remain authoritative. Because this introduces persistent browser personal data and changes privacy disclosure, landing is **ASK**, regardless of the current path classifier's lower result: implementation is authorized, but no automatic candidate promotion is permitted without separate explicit recorded landing approval and the ADR-0008 audited temporary-ruleset procedure. |
| Design citation | D-01 implements dense rows; D-02 route-backed inline detail; D-03 split/assigned agent controls; D-04 narrow and resilience behavior. |

No constitution violation or complexity exception is required.

## Project Structure

### Documentation (this feature)

```text
specs/017-compact-task-rows/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
frontend/src/features/tasks/
├── TaskListPage.tsx                         # D-01/D-02 composition and route/focus behavior
├── TaskDetailPanel.tsx                     # D-02 inline layout variant
├── TaskAgentControl.tsx                    # D-03 split and assigned controls
├── taskAgentPreference.ts                  # owner/API-scoped connection-ID preference
└── __tests__/
    ├── TaskListPage.test.tsx               # row, inline route/focus, review-entry tests
    ├── TaskAgentControl.test.tsx           # geometry, menu, compact-state tests
    └── taskAgentPreference.test.ts         # isolation and eligible fallback tests

frontend/src/queryClient.ts                 # production auth/session preference binding
frontend/src/__tests__/queryClient.test.ts  # logout/401/A→B production wiring

frontend/src/features/agents/
├── AgentHandoffOverlay.tsx                 # existing review seed and dispatch callback reused
├── agentCopy.ts                            # compact visible-state projection, full disclosure retained
└── __tests__/agentCopy.test.ts             # truthful `Reported`/fallback copy

frontend/tests/
├── e2e/compact-task-rows.spec.ts           # discovered real-browser geometry/a11y evidence
└── claude-design-shell.spec.ts             # retire sheet/modal assertions and refresh responsive baseline

frontend/src/pages/PrivacyPolicyPage.tsx        # bounded browser preference disclosure
frontend/src/pages/__tests__/PrivacyPolicyPage.test.tsx # pin browser-record disclosure
frontend/package.json / package-lock.json       # test-only Axe Playwright dependency
docs/data-retention.md                          # storage lifecycle and export disposition
specs/014-a2a-relay-wire-contract/              # narrow desktop-web compact-copy supersession

specs/017-compact-task-rows/                    # planning, design, acceptance, report evidence
```

**Structure Decision**: Keep the change inside the existing frontend feature
boundaries. `TaskListPage` owns list composition and route selection;
`TaskDetailPanel` receives an additive inline-layout variant; one small dedicated
control isolates agent menu/focus/geometry; one preference module plus the process-
global query-client bootstrap owns startup/focus/auth cleanup. `TaskSideSheet` and
`AppShell` panel props lose their final production consumer but are intentionally left
as dead compatibility surface in this bounded diff; their later deletion is explicit
technical-debt cleanup, not a hidden fallback. Backend and mobile paths are absent.

### Accepted compatibility changes

- 017-FR-010/FR-012 narrowly supersede the desktop-web collapsed-row clause of
  014-FR-013 and the old web compact-row evidence for 014-SC-004. The full disclosure
  moves to the button's accessible name and inline detail; iOS remains visibly fuller.
- The old `TaskSideSheet` modal/inert assertions and 402 × 874 slide-over snapshot are
  intentionally retired for Task lists. Autosave, recovery, immutable relay review,
  run monitoring, and rollout-OFF behavior are not retired.
- The old two-way Cmd/Ctrl+\\ local panel toggle assertion is intentionally replaced:
  with the route as sole authority, the shortcut collapses an open inline detail and
  cannot reopen a hidden copy that no longer exists.
- Existing `waiting_for` row metadata remains as compact, low-priority text and yields
  with Tags/due/subtask metadata rather than disappearing accidentally.

## Implementation slices

1. **D-01 / D-04 — hairline list**: make the list container gapless; give each
   collapsed header an exact `h-11`; keep completion, title, short Tags and compact
   Waiting-for/due/subtask indicators on one line; progressively hide low-priority metadata; remove card
   radius/background and never render Project/List/Delete.
2. **D-02 — inline detail**: bind non-control row activation to the 44 px header and
   render `TaskDetailPanel` as its non-clickable sibling inside the list item; plain
   detail content/text selection cannot bubble into row activation. Preserve the
   selected URL, adjacent navigation, autosave controller, completion animation,
   Escape/collapse, and deterministic focus restore.
   Do not render `TaskSideSheet`, scrim, modal role, or inert list state. Remove
   `panelOpen`/`sheetPresent` as selection authorities: Close, unhandled Escape and
   Cmd/Ctrl+\\ navigate to the parent route. `TaskDetailPanel` owns the sheet's existing
   target exclusions, and the page retains the document-wide modal guard for both keys
   so one Escape closes a portaled hand-off review without also closing detail. Every
   collapse first calls the keyed detail controller's
   `flush()`; its existing journal and controller map finish the save or preserve
   recovery after unmount, with no outgoing duplicate panel. When detail resolves
   outside the loaded projection, clear excluding filters and keep a matching current
   route; otherwise replace at most once to resolvable Project, open state, or Next
   actions for terminal/no-Project (`showCancelled=1` for cancelled). Walk at most ten
   pages, cancel on route/filter change, and expose Retry/Load more on failure/bound
   exhaustion. A non-existent/another-owner 404 gets one non-leaking list-level error
   and no redirect. Completion uses the existing autosave barrier,
   collapses detail, moves the 44 px header to Completed, and restores focus to that
   row or the documented survivor/heading fallback; FLIP measures only the header.
3. **D-03 / D-04 — agent rail**: load existing connections only when the relay flag
   is on, resolve the browser-local last eligible connection by ID, and open the
   existing `AgentHandoffOverlay` with a seed. Every successful `onDispatched`, from
   both the row and existing detail entry, records the bounded preference. Existing
   runs render a single fixed control and remain visible when the flag is off. A
   failed batch summary refresh uses trustworthy cache when present and otherwise
   omits controls without blocking Tasks. The split remains usable offline to open the
   existing review with disabled confirmation/nothing-queued copy. After dispatch,
   focus moves from the replaced split trigger to the assigned control. Bind a global
   preference sweep and auth subscriber from `queryClient.ts`; cover startup, focus,
   logout, 401, deletion, A→B, malformed, expired, and unavailable-storage paths.
4. **Evidence**: targeted RED→GREEN Vitest assertions, existing affected frontend
   suites, a discovered `frontend/tests/e2e/compact-task-rows.spec.ts` product spec at
   1440 × 900, 768 × 900 and 390 × 851, an `@axe-core/playwright` scan that fails on
   serious/critical violations, production build, Spec Kit validation, full
   repository verification, and bounded screenshots before any Done claim. All visual
   evidence MUST use a purpose-created account with synthetic Task, Tag, Project and
   agent data. A purpose-created synthetic hostname may appear only in the duplicate-
   name chooser proof; no real address, credential, token, fingerprint, or Task content
   may appear.

### Evidence matrix

| requirements | evidence owner |
|---|---|
| FR-001–FR-003, SC-001–SC-003 | `frontend/tests/e2e/compact-task-rows.spec.ts`: exact row/control boxes, aligned columns, no wrap/scroll at 1440, 768 and 390; `TaskListPage.test.tsx`: permitted content only |
| FR-004–FR-006, SC-005 | `TaskListPage.test.tsx`: header-bounded activation and inert detail text, route-only open state, same-row/Close/Escape/collapse-only shortcut, sibling-modal guard, pre-unmount autosave flush/recovery, exact one-redirect/ten-page canonical precedence including cancelled/404/failure/abort, completion-barrier collapse/re-parenting, focus completed-row/origin/next-row/heading; `frontend/tests/e2e/compact-task-rows.spec.ts`: no dialog/scrim/inert and inline placement |
| FR-007–FR-009, SC-006 | `TaskAgentControl.test.tsx`, `taskAgentPreference.test.ts`, and `TaskListPage.test.tsx`: eligible ID resolution, duplicate-name host copy, chooser focus, both review seeds, offline-readable review with zero queued/confirm calls, focus on replacement, update only after confirmed dispatch from both entry points |
| FR-010–FR-014 | `TaskAgentControl.test.tsx` and `agentCopy.test.ts`: complete compact state map, exact 184 × 28 classes, no arrow, Task-disambiguated full accessible disclosure, `Reported` not `Done`, Task remains open, rollout OFF existing runs |
| FR-015 | contract/spec diff plus unchanged backend/mobile suites; no product path in those trees |
| FR-016, SC-004 | component/browser tests inducing loading, first/filtered empty, Task error, batch-summary error with/without in-memory cache, offline, unavailable storage, terminal/long/narrow states; discovered Playwright spec plus `@axe-core/playwright` serious/critical scan and screenshot evidence |
| FR-008, FR-017, SC-008 | `taskAgentPreference.test.ts`, `queryClient.test.ts`, and `PrivacyPolicyPage.test.tsx`: `{connectionId, confirmedAt}`, thirty-day startup/focus sweep across identities, logout/401/deletion/A→B wiring, malformed/ineligible cleanup, export exclusion and exact honest policy copy |
| SC-007 | affected Task, autosave, completion-animation, relay-review, run-monitoring and rollout-OFF suites plus explicitly replaced modal/disclosure/two-way-shortcut assertions |

### Production acceptance boundary

Local and candidate checks are not Done evidence. After verified landing, record the
exact deployed SHA, Full CI and release runs, production smoke, `external_agent_relay`
flag read-back, and synthetic/redacted production screenshots for D-01/D-02/D-03/D-04.
The synthetic smoke identity must execute the changed journey on that deployed SHA:
scan ten rows, edit/open/close inline detail, exercise canonical recovery, verify focus,
and inspect the rollout-appropriate agent control. Existing generic smoke alone is not
evidence for this feature.
Relay-ON production evidence requires a separately authorized existing rollout and
bounded synthetic account/connection; without it, report that criterion as not yet
accepted rather than claiming overall Done.

## Rollback

Rolling back the frontend image changes no server record or API. The prior UI resumes
its side sheet and ignores the versioned preference key. Because old code cannot sweep
that key, rollback evidence must disclose that residual local bytes may remain until
the owner clears BrainBuddy site data or a later 017-capable build runs its global
sweep; the record grants no authority and is never sent to the server. An ASK landing
must record this residual and the site-data removal instruction before rollback.

## Complexity Tracking

The one new dev dependency is required to make SC-004's severity threshold executable.
No production dependency, compatibility layer, or parallel implementation is added.
