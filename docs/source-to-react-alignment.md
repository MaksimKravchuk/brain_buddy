# Desktop source-to-React alignment specification

## Scope and authority

This is an implementation checklist, not a redesign brief. The sole desktop/web visual
authority is the verified standalone export:

- source: `/home/max/Code/brain_buddy/.hermes/design-imports/authoritative/Brain Buddy Web (Standalone).html`
- SHA-256: `c2a44adfb56ebe3b8c0fff15e24e590fce4a97a80161a7dd2f3e44b98a9a621b`
- verification viewport: 1440 x 814
- source references inside the export:
  - template stylesheet `Brain Buddy task shell — CSS (post-pivot)`
  - template stylesheet `Brain dump — shared styles (web overlay + mobile full screen)`
  - resource `173794dd-c7c0-498f-8e4a-845bfdb435c2`, `tasks-first workspace`
  - resource `606d569f-f8be-4055-95ad-c87ac83bb0cf`, task-shell presentational components
  - resource `c708d106-b94b-4065-a29c-ee871433e380`, Brain Dump shared core

Only the desktop web composition above is in scope. The export contains no mobile
frames, no dedicated workspace loading frame, no dedicated workspace error frame, and
no designed list/project empty composition. Do not fill those absences with an invented
visual treatment during alignment.

## Current React baseline and mapping result

The checked-in React application has no represented GTD workspace screen. Its routes are
`/login`, `/signup`, and a protected `/`, where `/` renders the legacy canvas
`TreeWorkspace` (`frontend/src/App.tsx:27-40`). `TreeWorkspace`
(`frontend/src/pages/TreeWorkspace.tsx:142-234`) renders a tree menu, a full-width React
Flow canvas, floating zoom controls, tree create/rename/delete modals, and tree-specific
empty/error/loading states. It does not render the source top bar, GTD sidebar, task
rows, project/context views, Weekly Review placeholder, or Brain Dump.

Consequently every source workspace screen below is currently **unmapped**. The target
is the protected `/` route currently occupied by `TreeWorkspace`; authentication routes
are not source frames and must not be used as visual substitutes. The legacy
`components/layout/Layout.tsx` is also not mounted by the current route and its 320px
sidebar is not a source-aligned shell.

Implementation should replace the `/` workspace composition with a task-first workspace
and introduce task-specific React components rather than restyling `TreeCanvas`,
`BrainNode`, tree modals, or zoom controls. Until task components exist, the exact
component names in the table are implementation targets, not claims that such components
already exist.

## Global desktop contract (must match before per-screen work)

| Area | Source contract | Current React difference | Precise implementation target |
| --- | --- | --- | --- |
| App frame | Full-height flex column on `#f8fafc`; 56px top bar above a scrolling two-column body. | `TreeWorkspace` has a 56px-ish tree header but no task shell and then a full-width canvas. | Protected `/`: render `TaskWorkspaceShell` in place of `TreeWorkspace`; keep the shell at `height: 100vh` with internal content scrolling. |
| Top bar | `height: 56px`, `padding: 0 20px`, 16px gap, translucent `rgba(255,255,255,.9)` surface, 8px backdrop blur, 1px `#e2e8f0` bottom border, z-index 30. | Tree header is `px-6 py-3`, exposes tree actions/sign-out and lacks source controls. | `TaskTopbar`: Brand, 340 x 34 search, Brain dump button, and 32px human avatar only. |
| Sidebar / main grid | 248px fixed GTD sidebar (`--bb-sidebar-w`); 1px right border; `16px 12px 24px` padding; 20px section gap. Main is flexible and scrolls. | No sidebar is mounted. The unused `Layout` has a non-source 320px sidebar. | `TaskSidebar` at exactly 248px. Do not reuse the 320px layout aside. |
| Content column | Main inner column `max-width: 760px`, centered; `padding: 32px 32px 64px`. | Canvas occupies all available width; no centered task column. | `TaskContent` wrapper around every list/project/context/review pane. |
| Type | Embedded Inter, then `ui-sans-serif, system-ui, "Segoe UI", sans-serif`; feature settings `cv11`, `ss01`, `ss03`. Scale: 10/11/12/14/15/16/20/28px; weights 400/500/600/700. | Tailwind config nominally names Inter, but source screen typography is absent. | Load/use the source stack for the task workspace; title 20px/1.3/-0.015em/600; body rows 14px/500; metadata 11–12px; placeholder display 28px/1.15/-0.02em/600. |
| Core color tokens | Base `#f8fafc`, sunken `#f1f5f9`, raised `#fff`; primary `#0ea5e9`; primary text `#0f172a`; default border `#e2e8f0`; hover border `#cbd5e1`. | Existing palette is close in places, but canvas/node semantics and current controls are a different visual system. | Define/use these values for task UI only; do not inherit canvas node colors as task states. |
| Radii / shadows | Inputs/menu 6px; small controls 8px; task cards 12px; panel/dialog/toast 20px; pills/circles 999px. Soft: `0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03)`; raised: `0 1px 2px rgba(15,23,42,.05), 0 8px 24px -12px rgba(15,23,42,.12)`; floating: `0 1px 2px rgba(15,23,42,.04), 0 12px 32px -16px rgba(15,23,42,.18)`. | Current tree cards/nodes use asymmetric large radii and canvas-specific glow. | Apply source radii and shadows to task surfaces; no asymmetric BrainNode radii in the task UI. |
| Motion / focus | Smooth easing `cubic-bezier(.22,1,.36,1)`; 150/200/250ms quick/base/settle; keyboard focus ring is white 2px plus sky 4px. Source disables pulse animations under `prefers-reduced-motion: reduce`. | Global focus ring is similar, but task-specific focus rules do not exist. | Preserve focus-visible ring on navigation, checkbox, search, task/detail inputs, buttons, and overlay controls; add reduced-motion handling for source pulse, shimmer, caret, waveform, and overlay transitions. |

## Shared components and literal states

### Top bar and navigation

- `TaskTopbar` must show, in order: sprout icon plus literal **Brain Buddy** brand;
  search icon with placeholder **Search tasks and trees**; right-aligned mic-icon
  **Brain dump** CTA; circular pale-sky human avatar **TS**. Use source icon sizes:
  brand sprout 22px, search/mic 15px, avatar 32px.
- Search is exactly 340 x 34px with 12px horizontal padding, 8px icon/text gap, 8px
  radius, `#f1f5f9` background, and transparent border. On focus-within it becomes
  white with a `#0ea5e9` border; it is not a generic full-width search bar.
- `TaskSidebar` list items are 34px high, 10px horizontal padding, 10px icon/label
  gap, 8px radius, 14px/500, and 2px vertical list gap. Hover uses the sunken surface
  and primary text. Selected list/project is white with the soft shadow. Long project
  names wrap to at most two lines in an auto-height item (7px top/bottom padding);
  ordinary labels ellipsize.
- Source navigation order and copy: **Inbox**, **Next actions**, **Waiting for**,
  **Someday / maybe**, **Weekly review** (with due badge); then **Projects** with
  Onboarding revamp, Pricing, Team offsite, and Migrate billing to the new usage-based
  pricing model; then **Contexts** as @calls, @errands, @deep-work, @laptop.
- Source count treatment: Inbox uses a sky filled 18px-high pill (minimum 20px,
  11px/600 white); other navigation counts are plain 12px muted text with a 20px
  minimum width. The weekly review due pill is 10px/600, amber-50/amber-200/amber-800.
- Context pills are white 12px/500 capsules with a 1px border, 3px by 10px padding,
  six-pixel gaps, and `6px 10px 0` cloud padding. Hover darkens border/text; selected
  context uses `#f0f9ff`, sky border, and `#0369a1` text.

### Pane header, task cards, and density

- Every represented list/project/context pane starts with a flex header aligned to the
  baseline, 12px gap, and 20px bottom margin. Use a 20px title and a 12px metadata line
  4px below it; action controls align right with an 8px gap.
- Normal task list density is a vertical 8px gap. A task is white, 1px `#e2e8f0`,
  12px radius, `12px 16px` padding, and soft shadow. The internal row has a 32px
  minimum height and a 12px gap. Compact mode is only the source edit-mode representation:
  `8px 14px` task padding; do not make it the default or substitute it for mobile.
- Row elements: 18px circular checkbox; 14px/500 one-line ellipsized title; six-pixel
  chip gap; right side with 10px gap; fixed 96px right-aligned 11px muted project column
  when enabled. Normal cards, not grid tiles, are the source density.
- Hover raises only the card shadow. Expanded cards use the raised shadow. Completion
  is 0.45 opacity plus a strikethrough and muted title; checkbox hover changes only its
  border to sky; checked checkbox is sky with white check. Keyboard focus uses the
  two-layer focus ring.
- `working` / `review` / `offer` source task cards use the emerald AI border
  `#a7f3d0`; the agent is a 22px emerald squircle with 8px radius, never a human
  circle. `needs-you` uses amber-50 card background and amber-200 border. Due chips are
  rose-50 / rose-200 / rose-700. Thinking is sky; do not use the emerald AI color for
  thinking.
- Chips are 22px high, 11px/500, 8px horizontal padding, full pill radius, and a 1px
  border. Context is neutral/slate; due, AI, thinking, and needs-you use the semantic
  colors above. Pulsing dots are 6px and pulse at 1.6s unless reduced motion is active.
- The add-task affordance is a full-width 14px row with plus icon, `12px 16px` padding,
  12px radius, 1.5px dashed slate-300 border, and 8px top margin. Its default copy is
  **Add a task**; on Next actions it is exactly **Add a next action — or dump everything
  on your mind with the mic above**. Hover changes border to sky and text to slate-600.

### Expanded task detail state

Map the source expanded row to `TaskRow` plus `TaskDetail`, not a separate page or a
side inspector. It is inside the same 12px task card and begins after `12px` top margin,
`14px` top padding, and a 1px divider. Sections use 18px vertical gap; their items use
8px gap. Preserve all represented source content/states:

- checked/unchecked 14px subtasks and the dashed 13px add-subtask input (maximum 380px),
- run log (maximum 480px): six-pixel done/current/upcoming dots, current pulse,
  13px text plus 11px time,
- amber needs-user prompt/action block (`10px 12px`, 8px radius),
- small bordered artifact link,
- emerald agent handoff/offer block (`10px 12px`, 10px radius),
- human comment avatar (24px circle), comment metadata/text, and add-comment affordance.

The source provides a 250ms detail entrance from `translateY(-4px)`. Retain it and
respect reduced motion. Do not replace this with the existing node/relation inspector.

## Screen-by-screen route/component checklist

`/` is the single represented source route. Navigation changes selected view inside that
workspace; the source does not define separate URL paths. All rows below are currently
unmapped and therefore fail alignment until their named target exists and the literal
checks pass.

| Source screen / trigger | Source composition and represented content | React status / implementation target | Required acceptance checks |
| --- | --- | --- | --- |
| Next actions (default) | Title **Next actions**; 6 source rows; project column visible; task and AI metadata; Think control; Next-specific add affordance. | Unmapped. Create `TaskWorkspace` selected-list state and `TaskListPane` default branch under protected `/`. | Default selected nav item, exact title/copy, six represented rows, 760px column, comfortable card density, group toggle, and source task states all render. |
| Next actions grouped | Same list, grouped by project with group header: colored 8px dot, project label, muted count; group blocks separated by 24px. | Unmapped. `TaskListPane` needs source group-by-project state. | Group control changes only grouping; grouped rows suppress per-row project column; preserve card/list geometry and count treatment. |
| Inbox | Title **Inbox**; 4 raw/unprocessed source tasks and source processing hint; source Inbox count badge. | Unmapped. `TaskListPane` Inbox branch. | Show raw task copy and processing hint, source count badge, task cards and add affordance. Do not use the existing tree empty state. |
| Waiting for | Title **Waiting for**; 2 rows including waiting metadata and a Ready for review AI state. | Unmapped. `TaskListPane` Waiting branch. | Render waiting note, review/AI treatment, correct list count, card geometry, and selected navigation. |
| Someday / maybe | Title **Someday / maybe**; 3 represented rows. | Unmapped. `TaskListPane` Someday branch. | Three source rows with normal task card density; selected navigation and source copy. |
| Weekly review | Deliberate source placeholder: rotate icon, **Weekly review**, guided-pass hint ending **Due Sunday**, and placeholder tag. | Unmapped. `WeeklyReviewPlaceholder` branch. | Render the source placeholder only: 1.5px dashed slate-300, 20px radius, `56px 32px` padding, 56px sky circle icon, 28px title, maximum 400px hint. Do not invent a review workflow. |
| Project: Onboarding revamp | Selected project nav; source metadata says **6 tasks · 1 running on AI** while only 2 task rows are represented. | Unmapped. `ProjectTaskPane` selected-project branch. | Preserve the literal fixture discrepancy instead of generating hidden rows; show two rows, source metadata, no project column, source project dot and selected sidebar state. |
| Project: Pricing | Selected project; source metadata **4 tasks** and 2 represented rows. | Unmapped. `ProjectTaskPane`. | Two rows only; retain source metadata and project selection. |
| Project: Team offsite | Selected project; source metadata **3 tasks · 1 needs you** and 2 represented rows. | Unmapped. `ProjectTaskPane`. | Two rows only; one needs-you amber state; retain source metadata. |
| Project: Migrate billing to the new usage-based pricing model | Long two-line/clipped project label; metadata **2 tasks** but zero represented rows. The source shows an empty row area, not an empty-state composition. | Unmapped. `ProjectTaskPane`. | Keep selected long-label wrapping/clipping and source metadata. Render no invented illustration, CTA, or message in its empty task area. |
| Context: @calls | Title **@calls**; 1 source row and **1 task across your lists** metadata. | Unmapped. `ContextTaskPane`. | Selected sidebar pill; one row; source context header/metadata and task layout. |
| Context: @errands | Title **@errands**; 1 source row. | Unmapped. `ContextTaskPane`. | Same geometry, exact context selection and one source row. |
| Context: @deep-work | Title **@deep-work**; 2 source rows. | Unmapped. `ContextTaskPane`. | Two source rows; selected pill; project column is present per source context rendering. |
| Context: @laptop | Title **@laptop**; 1 source row. | Unmapped. `ContextTaskPane`. | One source row and context selection. |
| Expanded task | Any task clicked/expanded in place; subtasks, log, needs-user, artifact, agent offer, comments. | Unmapped. `TaskRow` / `TaskDetail`. | Follow the expanded-task contract above; retain parent row in the list and no route change. |
| Completion / count update | Checkbox changes task to completed styling and updates the relevant visible count. | Unmapped. Task state reducer/query projection. | Checkbox hover/focus/checked visuals and resulting count update work without changing layout. |
| Placeholder action toast | Source interactions for Sort, Search, Think, New project, Account, and task details produce a centered fixed toast: bottom 24px, white 95%/8px blur, 12px radius, floating shadow, `10px 16px`, 13px muted text. | Unmapped. Workspace toast presenter. | Preserve source geometry/copy per action; do not surface canvas-specific toast copy. |

## Brain Dump overlay checklist

Brain Dump is a source overlay on top of any task workspace screen, not a new route,
side panel, browser prompt, or canvas modal. It must use `BrainDumpOverlay` mounted at
the protected task workspace root.

| State | Source composition | Required React target and checks |
| --- | --- | --- |
| Recording / initial | Fixed scrim (`rgba(248,250,252,.8)`, 4px blur, z-index 100) centers an 880px panel, capped at viewport minus 48px, white, 1px border, 20px radius, floating shadow. Header is `20px 24px 12px`: 40px mic, 20px title, 12px subtitle, 32px close. Body is `320px 1fr`, minimum 480px high. The task side initially uses the dashed hint. | `BrainDumpOverlay` + `BrainDumpRecording`. Match panel/scrim dimensions, header, close/Discard behavior, initial no-task hint, pulsing rose 7px recording dot/timer, transcript caret, blue waveform, and Stop / Stop & send controls. |
| Recording / captured and forming | Right stack fills the panel, `18px 24px 16px`, 8px row gap. Captured cards are white, 1px border, 12px radius, `11px 14px`, soft shadow; newly captured card enters from `translateY(6px) scale(.98)`. Forming card is dashed with a 2.2s shimmer. | `BrainDumpRecording` state: append captured cards, retain transcript/timer/wave, and render forming shimmer separately from a captured card. Honor reduced motion. |
| Review | Same panel enters review; review list has two columns (`1fr 1fr`, `8px 10px` gap) and capped stack (`max-height: 480px`, min 200px). A review row is white, 1px border, 12px radius, `10px 10px 12px 14px`; editable 14px/500 title; add-date pill; 32px remove. Input hover gets default border; focus gets sky border and white fill. | `BrainDumpReview`. Preserve editable title, add-date affordance, remove, Send to inbox, Discard all, and close. Do not replace it with a generic dialog/form. |
| Send success | Source sends tasks to Inbox, increments visible Inbox count, and emits **1 task sent to inbox** for one sent task. | Overlay callback updates Inbox projection, closes the overlay, selects Inbox, and uses the source toast. |

The source has source-only recording, pulse, shimmer, caret, and waveform animations; all
must be suppressed under reduced motion. Its mobile modifiers are not implementation
authority for this desktop outcome.

## Explicitly non-authoritative states

Do not treat the following existing React states as source acceptance targets and do not
invent source replacements for them in this task:

- `TreeWorkspace` canvas loading, error card, empty canvas, relation errors, floating
  zoom controls, tree menus, tree import/export, and tree CRUD modals.
- Generic source design-system spinner, modal, menu-empty, auth, or canvas-empty CSS
  that is not instantiated by the authoritative workspace app.
- Dedicated workspace loading/error screens and designed list/project empty screens;
  the source has none. Billing's empty task area is the only represented zero-row case.
- Login/signup pages and mobile layouts.

## Completion checklist for an implementing worker

1. At a 1440 x 814 desktop viewport, compare `/` against the source after each listed
   navigation target and Brain Dump state; check the global geometry before card details.
2. Verify literal source copy, counts, project metadata discrepancies, represented row
   counts, long-label wrapping/ellipsis, icons, semantic colors, and the absence of
   invented frames.
3. Exercise hover, keyboard focus-visible, selected navigation/context, normal/compact,
   expanded, checked, due, working/review/offer, needs-you, grouped, placeholder toast,
   and every Brain Dump state listed here.
4. Verify `prefers-reduced-motion: reduce` stops pulsing, recording, shimmer, caret,
   waveform, and entrance animations without removing the corresponding state.
5. Keep the source's intentionally unfinished Weekly Review and zero-row billing
   project as written. Alignment is literal, not an opportunity to replace them.
