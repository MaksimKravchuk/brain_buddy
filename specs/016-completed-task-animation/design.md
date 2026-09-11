# Design: Visible completed tasks

**Feature**: `specs/016-completed-task-animation/`
**Spec**: `spec.md` (Clarifications settled: 2026-09-06; owner narrowed scope to completion presentation)
**Screens**: `design/task-completion.html`
**Human sign-off**: Owner's 2026-09-06 browser screenshots and instructions accept grey struck titles, movement to the bottom and persistent filtering. The HTML records that direction; it has not been separately reviewed by the owner.

## Applicability

This changes the existing web task workspace. Preserve its row anatomy, controls, grouping, detail sheet and explicit reopen destinations. Add one Completed section after all loaded open rows/groups. Completed records are included by default; the existing history toggle becomes Show cancelled. Native-mobile UI is outside scope. Owner explicitly excluded new search and combined-filter functionality; existing project/tag membership and existing query behavior are preserved.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop web | Existing task list, before/after completion | Locate completed work without losing list/filter membership | FR-001–FR-003 |
| M-01 | mobile web, 390×851 | Same list and states with compact header | Complete and recover work at a narrow viewport | FR-001–FR-003 |

## State inventory

Both screens share these stable state suffixes: `D-01-S01` / `M-01-S01`, and so on. The HTML depicts S01/S03 at both widths; the other rows specify changes to existing states rather than new screens.

### D-01 and M-01 — task list

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| S01 default | Initial load or navigation | Open tasks first; any matching completed tasks under one Completed heading; no heading with zero completed rows; no entry animation; open-only subtitle counts | Existing list heading and subtitle; Completed | FR-001, FR-003; SC-003 |
| S02 pending | Completion request in flight | Existing pending/disabled handling; row retains its unsaved position and open styling; no success movement yet | Existing pending feedback | FR-003 |
| S03 completed | Canonical completion succeeds | Checked circle; readable slate-500 title with strikethrough; row moves below all loaded open groups; its tags/date/detail link remain | Completed | FR-001, FR-002; SC-001, SC-002 |
| S04 reopen | Explicit reopen succeeds in detail sheet | Normal title/check control returns in the selected open destination; list eligibility follows that destination | Existing named reopen destination | FR-002, FR-003 |
| S05 loading | Initial fetch | Existing loading presentation and useful filter controls; no false empty state | Existing loading copy | FR-003 |
| S06 empty, first run | No tasks | Existing empty state and Add a task; no empty Completed heading | Existing empty copy | FR-001, FR-003 |
| S07 empty, filtered | No tasks match active filters | Existing filtered-empty guidance and retained filter controls | Existing filtered-empty copy | FR-003; SC-003 |
| S08 completed only | Matching tasks are all completed | Completed heading followed by checked grey struck rows; add/filter controls remain available | Completed | FR-001, FR-002 |
| S09 fetch error | Loading fails | Existing error and Retry; previously loaded data follows existing recovery behavior | Existing specific error and correlation identifier where supplied | FR-003 |
| S10 save failure or interruption | Completion fails or connection is lost | No successful transition for the failed task; existing actionable recovery/retry remains; refresh reconciles canonical state | Existing mutation error/recovery copy | FR-003 |
| S11 partial failure | Several completion requests have mixed outcomes | Each successful row reaches Completed once; failed rows preserve their previous state and existing error handling | Completed and existing error copy | FR-003 |
| S12 cancelled history | Show cancelled selected | Existing cancelled history stays distinct from successful completion; it is not counted as open work | Show cancelled; existing cancelled state | FR-001, FR-003 |
| S13 pagination | Another existing page loads | Newly fetched open rows join the open section above Completed; each fetched task appears once; canonical server order and paging are unchanged | Existing pagination control | FR-001, FR-003; SC-003 |
| S14 filtered or grouped completion | State/project/tag/search/date filter or project grouping is active | Same matching completed records, once, in a single Completed section below every open group; group/tag identity remains visible where already provided | Existing filter/group labels; Completed | FR-001, FR-003; SC-003 |
| S15 reduced motion / keyboard | Reduced motion is set or completion invoked by keyboard | Success styling and final order apply instantly with reduced motion; otherwise movement completes with usable visible focus on the moved task link when the old completion button is removed | Accessible completed state and task title | FR-002, FR-003; SC-002 |

## Completion motion

- Begin only after the successful canonical response, including completion from the detail sheet. Never communicate success before it is saved.
- Apply the checked circle and grey strikethrough, then move the row to its final Completed position over **380ms** using the existing `cubic-bezier(0.22, 1, 0.36, 1)` easing. A 300–450ms implementation is equivalent; the acceptance ceiling is 600ms. This longer movement is the bounded exception to the skill's usual 150–250ms small-control transitions.
- Animate displaced rows coherently; preserve one real row per task and its reachable details. No bounce, looping animation, separate success modal or forced scrolling.
- Displaced controls remain tappable at their visual transformed position. A per-task pending guard disables the completing task's button until its save settles, preventing duplicate saves. A later acknowledgement starts from current visual rectangles and replaces only the previous visual animation, never a save.
- Do not animate initial loading, refresh-only layout changes or filter navigation. With `prefers-reduced-motion: reduce`, apply the final position immediately.

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01, M-01 | Existing complete button | Saves completion and starts the successful transition | FR-002, FR-003 |
| D-01, M-01 | Existing title/detail link and explicit reopen action | Opens the task and preserves destination-aware recovery | FR-002, FR-003 |
| D-01, M-01 | Existing list/project/tag/search/date/sort/group controls | Filter and order both open and completed work | FR-001, FR-003 |
| D-01, M-01 | Show cancelled | Keeps cancellation history accessible without opting into completed work | FR-001, FR-003 |
| D-01, M-01 | Existing retry and pagination | Recovers failures and loads remaining results without duplicates | FR-003 |

### Requirements with no affordance

None missing. FR-003 preserves existing safe-save/query behavior and accessibility without adding controls.

### Affordances with no requirement

None. Existing shell, Brain dump and Add a task appear only to preserve the accepted screenshot baseline; they are unchanged.

## Primary loop impact

This improves visibility of evidence/results when the owner reviews finished tasks. Capture → atomic items → clarify/approve → route or CRT candidate is unchanged. Weekly Review remains deferred; this feature adds no Weekly Review surface or automation.

## Mobile viability

- Target viewport: **390×851**. The HTML includes two 390px frames and uses the same compact header and wrapping toolbar. Runtime verification is an implementation acceptance gate, not evidence supplied by this static mock.
- Keep existing 44px completion targets and usable title links. Long titles truncate with the full accessible task name retained; metadata may wrap. No horizontal scrolling or clipped controls is acceptable.
- Completion remains at the left of each row; no new filter toolbar or gesture is required. The completed task remains discoverable below open tasks without a forced scroll.
- No destructive action is added; existing detail actions retain their current behavior.

## Keyboard and focus

- Preserve shell/filter tab order, then row completion control and title link. The completed check indicator is semantic status, not an implicit reopen toggle.
- If the focused completion button disappears, transfer focus to the same task's existing title link without scrolling. Do not replace the link solely to animate it.
- Detail opening, closing and Escape retain current focus restoration behavior; a completed task's title remains a valid restoration target.
- Keep explicit names such as `Complete <task title>` and a non-color-only completed status. The check, strikethrough and Completed heading supplement grey text.
- Use the skill's visible double focus ring. Grey title uses slate-500 on white without whole-row opacity, preserving readable metadata and controls.

## Design authority

- Existing production task rows and the owner's annotated screenshots take precedence for layout; `brain-buddy-design` supplies slate/sky colors, typography, radii and easing. The mock embeds the unchanged logo asset as data, uses the local/system Inter font stack, and loads no external resources.
- Vocabulary: Tag; exactly four open GTD primary lists remain unchanged.
- Existing design-skill validation: **pass**, 6 tests, 2026-09-06. The unchanged validator is evidence tooling, not an implementation surface; its command is recorded with local validation logs.

## Open decisions for the human

None required to implement the accepted direction. New HTML is a reference of the supplied direction, not a fabricated separate approval.
