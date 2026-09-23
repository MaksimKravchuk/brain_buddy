# Design: Miro-like CRT Canvas

**Feature**: `specs/019-miro-like-crt-canvas/`  
**Spec**: `spec.md` (clarifications settled: 2026-09-19)  
**Screens**: `design/*.html`  
**Human sign-off**: approved by product owner on 2026-09-19

<!--
  Produced for the Spec Kit design stage. Screen and state IDs are stable
  references for planning and acceptance review; do not renumber them.
  The design is desktop-only for the first release. Accepted contracts and
  current product behavior outrank the exploratory pre-pivot kit.
-->

## Applicability

This feature has a user-visible desktop web surface. Thinking Mode opens `/crt` for an authenticated account with the server-owned CRT exposure effective. The surface uses the BrainBuddy shell, a light dot-grid workspace, compact floating controls, simple cards, directed curved arrows, and a selected-card inspector. It is intentionally not a collaboration surface and does not introduce AI, comments, sharing, version UI, or task/project linking.

The reference image informed the spatial language only: a quiet infinite board, a compact left tool rail, a title/menu surface, a small bottom zoom cluster, and readable curved directed links. It does not copy Miro branding, text, colors, collaboration controls, or commercial actions.

## Design authority and visual contract

- **Tokens**: BrainBuddy `slate` neutrals, `sky-500` primary, `indigo-500` secondary, `emerald` saved state, `amber` warning/offline, and `rose` destructive/error states.
- **Type**: system-safe Inter-first stack, 14px UI body, 20px pane titles, 28px empty-state display, 10px uppercase section labels. No external font request is used by the static screens.
- **Surfaces**: flat `#f8fafc` base, white raised cards, `#f1f5f9` sunken inspector, hairline `#e2e8f0` borders, soft/floating shadows, 8px controls, 12–20px panels.
- **Canvas**: React Flow-like dot background at low contrast; no photographic imagery, heavy gradients, or decorative noise.
- **Cards**: asymmetric `rounded-l-2xl rounded-r-xl` treatment with a narrow sky accent bar. Root/no-incoming and leaf/no-outgoing semantics use the existing yellow/red node tokens; semantic meaning is also written in labels and inspector copy, never color alone.
- **Relations**: cause is the source and effect is the target. Default layout is bottom-up: causes below effects. Curves terminate at card edges and use visible arrowheads. Selected relation/card uses a sky stroke and glow without removing the neutral relationship label.
- **Voice**: calm, second-person, sentence case, direct. Empty state copy is truthful: no demo content is fabricated.

## Shell and interaction model

1. **Global entry**: existing Thinking Mode navigation opens `/crt`; the top shell identifies Brain Buddy and the current tree. The canvas is not exposed when the feature flag is ineffective.
2. **Title/menu**: the tree title is a button with an explicit menu. Menu actions stay in the canvas: create, switch, rename, import JSON, export JSON, and confirmed delete. Disabled actions are visibly disabled when no tree exists.
3. **Board**: the canvas owns selection, drag, relation handles, pan, zoom, fit-all, and arrow-key traversal. The left rail is compact and keyboard-addressable. The lower-right control cluster exposes fit, zoom out, percentage, and zoom in.
4. **Inspector**: a 320px side panel shows the selected card label plus incoming causes and outgoing effects. It never invents parent/child types or duplicates graph ownership.
5. **Save status**: a persistent shell status distinguishes saved, saving, unsaved/error, and offline-local. Failure states keep the draft and expose retry plus a support reference where a request occurred.
6. **Recovery**: a stale canonical copy and a divergent local draft remain preserved until connectivity returns. The user previews both copies and reviews differences before choosing; discarding local edits requires a second confirmation that names the lost edits. Navigation, account changes, import, tree switching, delete, sign-out, and reload are blocked or warned while pending work could be discarded.
7. **Keyboard-first creation**: Enter creates a cause below the selected card and links it to that effect. Tab creates a same-level sibling and inherits only a unique nearest effect while canvas shortcut mode is active. Escape exits that composite canvas mode so the next Tab/Shift+Tab resumes ordinary browser focus navigation. With no selection, Enter or Tab creates an unlinked card near the viewport center. Text fields, menus, dialogs, and controls retain native key behavior.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| **D-01** | desktop | Default loaded canvas | Show the last owner-scoped tree with bottom-up cards, directed curves, selected card, inspector, shell save status, tool rail, and zoom controls. | 019-FR-002–006, 010, 012, 014–017, 020, 022–024 |
| **D-02** | desktop | First run + open tree menu | Show the truthful no-tree state, the single create CTA, and title-menu tree CRUD/import/export affordances without demo content. | 019-FR-003–004, 013, 018, 020–024 |
| **D-03** | desktop | Offline retention + sync conflict review | Show retained local changes, visible offline/save failure, canonical-versus-local previews, required difference review, retry, backup, defer and support reference. | 019-FR-017–021, 023–024 |
| **D-04** | desktop | Keyboard shortcuts + selected-card inspector | Make the full first-release shortcut set discoverable while preserving a dense selected-card editing and relation-inspection view. | 019-FR-007–016, 023–024 |
| **D-05** | desktop + narrow boundary | System feedback and exposure boundaries | Consolidate loading/error/partial/storage states plus stable unsupported-width (`D-05-UW`), normally disabled (`D-05-FD`) and flag-service unavailable (`D-05-FU`) boundaries. | 019-FR-001–002, 017–024 |
| **D-06** | desktop modal/sheet family | Destructive and recovery confirmations | Cover sync-conflict discard plus tree delete (`D-06-TD`), connected-card cascade (`D-06-CD`), pending-work transition (`D-06-PW`) and expired-draft recovery (`D-06-EX`) with named consequences and safe focus. | 019-FR-004, 010, 018–021, 023–024 |

Static artifacts:

- `design/D-01-default-canvas.html`
- `design/D-02-first-run-tree-menu.html`
- `design/D-03-offline-conflict-confirmation.html`
- `design/D-04-keyboard-inspector.html`
- `design/D-05-system-states.html`
- `design/D-05-UW-unsupported-width.html` (responsive 390×851 boundary companion)
- `design/D-06-destructive-confirmation.html`

## State inventory

Every desktop screen keeps the shell/status language consistent. A state marked “not the primary composition” is still specified here because it must not degrade into a blank surface or claim a successful save.

### Shared loading timing

- Direct input receives immediate optimistic/pressed feedback. For network or comparison work, preserve layout immediately but do not flash a spinner for work completed within 300 ms.
- At 300 ms, show the specified spinner/skeleton/progress copy, set the affected region `aria-busy="true"`, and announce one polite status update. At 10 seconds, change the copy to “Still working…” and expose the safe cancel or retry-later path where cancellation is valid.
- The client timeout remains 15 seconds for reads and 30 seconds for mutations. Timeout clears busy state and enters the screen's actionable error/offline state; it never leaves an indefinite spinner or announces success.
- Reads and comparison-only requests may be cancelled through their `AbortController`; the stable `*-CN` state says “Loading cancelled. Nothing changed,” focuses Retry, and renders no stale result as current. A mutation cannot be truthfully cancelled after dispatch: at 10 seconds it offers “Keep working” (return focus to canvas while the status remains pending) and “Keep waiting,” preserves the immutable keyed request/draft, and reconciles any late response. Timeout is unresolved/retryable, not cancelled; same-key retry or explicit refetch/reconciliation determines the outcome.

### D-01 — Default loaded canvas

| state | trigger | what the user sees | copy / action | FR/SC refs |
|---|---|---|---|---|
| `D-01-DF` default | Last tree loads successfully | Full graph, selected card, inspector, left rail, zoom cluster, saved status | “Saved just now”; “Current Reality Tree · bottom-up” | 019-FR-003, 005–006, 014–017; 019-SC-002 |
| `D-01-LD` loading | Open `/crt` or switch tree before data arrives | Stable shell, skeleton inspector, centered progress treatment; no stale tree presented as current | “Loading your last tree…”; keep route and focus stable | 019-FR-003, 020–021 |
| `D-01-EM` empty (first run) | No owner-scoped tree exists | D-02 composition replaces the graph; one create CTA; no fabricated cards | “Start with your first undesired effect” | 019-FR-003, 021 |
| `D-01-NA` filtered-empty | Not applicable in this release: filtering is out of scope | No filter or no-results UI is implemented | N/A | 019-FR-026 |
| `D-01-ER` error | Canonical load fails | Keep shell; replace graph with retryable error state and support reference | “We couldn't load this tree”; “Retry loading” | 019-FR-020–021; 019-SC-006 |
| `D-01-PF` payload integrity failure | Canonical snapshot has missing endpoint/incomplete relation/layout | Reject the payload as a whole; keep prior accepted graph/draft when present, otherwise no graph; never present partial server data as canonical | “We couldn't verify this tree”; “Retry tree load” + reference | 019-FR-011, 020–021 |
| `D-01-OF` offline / interrupted | Network drops during edit or save | Existing graph remains usable; shell changes to amber offline-local and local draft remains visible | “Offline · changes kept locally”; “Retry save” | 019-FR-017–019; 019-SC-004 |
| `D-01-CN` cancelled read | User cancels a tree read after progress appears | No stale tree is presented; stable shell names cancellation | “Loading cancelled. Nothing changed.”; focus “Retry loading” | 019-FR-020–021, 023 |

### D-02 — First run + open tree menu

| state | trigger | what the user sees | copy / action | FR/SC refs |
|---|---|---|---|---|
| `D-02-DF` default | No tree exists and title menu is opened | Truthful empty canvas plus open menu; create/import are enabled, tree-dependent actions disabled | “Choose a tree to continue”; “Create a new tree” | 019-FR-003–004, 021 |
| `D-02-LD` create/import/loading | Create, import, or last-tree lookup is pending | CTA/menu action shows progress and preserves shell; no duplicate submit | At 300 ms “Creating tree…” / “Importing…”; timeout keeps current graph/draft and exposes same-key Retry + reference | 019-FR-004, 017, 021 |
| `D-02-RN` rename pending | User submits a valid new name | Menu stays open, field and duplicate submit disabled; current graph/draft remain visible | At 300 ms “Renaming tree…”; success returns focus to title button with new name | 019-FR-004, 017, 021, 023 |
| `D-02-RER` rename error/interrupted | Rename HTTP/network/timeout failure | Original canonical title remains; typed value stays in field; Retry/cancel and support reference when sent | “We couldn't rename this tree”; Retry focuses field on failure, title button on cancel/menu close | 019-FR-004, 017, 020–021, 023 |
| `D-02-EX` export pending | User requests canonical export | Label action “Export saved server copy.” If local/conflicting edits exist, inline warning says “Unsynced edits are not included” and offers “Download local backup”; menu/current graph/draft stay unchanged; only export action disabled | At 300 ms “Preparing saved server copy…”; success returns focus to Export and announces “Saved server copy downloaded” | 019-FR-004, 018–021, 023 |
| `D-02-XER` export error/interrupted | Export HTTP/network/timeout/cancel | No graph/draft mutation; Retry and support reference when sent | “We couldn't export this tree”; focus Retry; cancel/menu close restores title button | 019-FR-004, 020–021, 023 |
| `D-02-EM` empty (first run) | First authenticated open has no trees | Centered empty state, no sample graph, inspector placeholder | “No demo content is added for you.” | 019-FR-003, 021; 019-SC-006 |
| `D-02-ALT` no alternate tree | Tree switch list has no other entries | Menu section stays present with a bordered empty message | “No other trees yet” | 019-FR-004, 023 |
| `D-02-ER` create/import/load error | Create/import/load fails | Menu stays safe to close; actionable error announced; current graph/draft unchanged | “We couldn't create this tree”; “Retry” + support reference | 019-FR-004, 011, 020–021 |
| `D-02-PF` import partial failure | Import validation finds malformed JSON, unknown schema, missing endpoints, duplicates, or cycles | Current empty/current tree and draft stay intact; validation detail beside import | “Import rejected: relation endpoints are missing”; “Choose another file” | 019-FR-011, 020–021 |
| `D-02-OF` offline / interrupted | Create/import attempted without network/storage | Do not imply canonical creation; explain whether local recovery is available | “You're offline. Reconnect before creating a canonical tree.” | 019-FR-017–019, 021 |
| `D-02-CN` cancelled lookup/export | User cancels a cancellable read/export | Menu/current graph remain; no file or stale tree claimed | “Request cancelled. Nothing changed.”; focus Retry/action | 019-FR-004, 020–021, 023 |

### D-03 — Offline conflict + destructive confirmation

| state | trigger | what the user sees | copy / action | FR/SC refs |
|---|---|---|---|---|
| `D-03-DF` default | Connectivity returns and sync detects a divergent server copy | D-03 review-first conflict dialog over a readable dimmed canvas; both copies remain preserved | “Review the sync conflict”; “Review differences” | 019-FR-018–019, 021 |
| `D-03-LD` loading | Retry save or conflict comparison is in progress | Dialog keeps both version labels but disables choices until comparison completes | “Comparing local draft with server copy…” | 019-FR-018–019, 021 |
| `D-03-EM` local-create recovery | No canonical tree exists but a local create draft exists | Local draft recovery sheet offers “Keep local draft” or discard with explicit warning; no fake saved tree | “A local tree is ready to recover” | 019-FR-003, 018–019, 021 |
| `D-03-NA` filtered-empty | Not applicable in this release: conflict filtering is out of scope | No conflict-filter UI is implemented | N/A | 019-FR-026 |
| `D-03-ER` error | Comparison/retry fails | Keep dialog open, preserve local draft, expose retry and correlation reference | “We couldn't compare these versions”; “Retry comparison” | 019-FR-018–021 |
| `D-03-PF` comparison integrity failure | Server comparison copy fails graph integrity | Do not show a partial server preview; preserve the complete local draft and last accepted canonical copy, block replacement, offer retry/local backup | “We couldn't verify the server copy”; “Download local backup” | 019-FR-011, 019, 021 |
| `D-03-OF` offline / interrupted | Connection drops while dialog is open or tab is reloaded | Draft remains origin/account/tree scoped when storage is available; leave action warns | “Changes are safe in this browser”; “Stay & retry” | 019-FR-017–019; 019-SC-004 |
| `D-03-CN` comparison cancelled/deferred | User cancels comparison or chooses Resolve later | Both copies remain; conflict status stays visible and resumable | “Conflict deferred · Review differences”; focus returns per automatic-open fallback | 019-FR-019, 021, 023 |

### D-04 — Keyboard shortcuts + selected-card inspector

| state | trigger | what the user sees | copy / action | FR/SC refs |
|---|---|---|---|---|
| `D-04-DF` default | Card selected and shortcut disclosure opened | Selected card has focus ring/handles; inspector exposes label and causal links; nonmodal shortcut groups are readable while focus remains on the Shortcuts trigger | “Keyboard shortcuts”; “Nonmodal · inputs keep their native keys” | 019-FR-007–016, 023 |
| `D-04-LD` loading | Inspector or relation details are fetching | Card remains selected; field skeletons do not steal focus | “Loading card details…” | 019-FR-015, 021 |
| `D-04-EM` empty (first run) | No card selected on an empty tree | Inspector placeholder and D-02 empty state; shortcuts remain available but do not create until user invokes them | “Select a card”; “Enter or Tab creates the first card” | 019-FR-003, 009, 012–013 |
| `D-04-NR` no relations | Selected card has no incoming causes or outgoing effects | Empty relation sections stay labelled | “No incoming causes”; “No outgoing effects” | 019-FR-015, 023 |
| `D-04-ER` error | Label save or inspector fetch fails | Keep edited value locally visible, mark unsaved/error, retry; never revert silently | “We couldn't save this label”; “Retry save” | 019-FR-015–018, 021 |
| `D-04-PF` integrity failure | Inspector projection detects a missing relation endpoint | Do not render a partial causal list; retain selected card/draft, block destructive operations and enter the whole-tree integrity error path | “Card links couldn't be verified”; “Retry tree load” | 019-FR-011, 015, 021 |
| `D-04-OF` offline / interrupted | Card edit occurs offline | Inline value remains; shell and inspector say local-only and leave warning is armed | “Saved locally · waiting to sync” | 019-FR-017–019 |
| `D-04-CN` inspector read cancelled | User cancels inspector-only fetch | Selected card remains; no stale details shown | “Loading cancelled. Nothing changed.”; focus Retry details | 019-FR-015, 020–021, 023 |

### D-05 — System feedback state board

| state | trigger | what the user sees | copy / action | FR/SC refs |
|---|---|---|---|---|
| `D-05-DF` default | Design review of feedback contract | Four bounded state cards, each with semantic badge and safe action | “System feedback states” | 019-FR-017–021, 023 |
| `D-05-LD` loading | Initial tree request | Spinner/skeleton without a false empty state | “Loading your last tree…” | 019-FR-003, 021 |
| `D-05-EM` empty (first run) | No tree result | D-02’s truthful empty state is the canonical composition | “Start with your first undesired effect” | 019-FR-003, 021 |
| `D-05-NA` filtered-empty | Not applicable in this release: filtering is out of scope | No filter or no-results UI is implemented | N/A | 019-FR-026 |
| `D-05-ER` error | Request fails | Rose error block, Retry, support reference | “We couldn't load this tree” | 019-FR-020–021 |
| `D-05-PF` payload integrity failure | Cards/relations/layout fail complete snapshot validation | Amber integrity block; no partial server graph is installed; prior accepted graph/draft remains unchanged | “Tree payload failed integrity checks”; “Retry tree load” | 019-FR-011, 021 |
| `D-05-OF` offline / interrupted | Browser storage unavailable or network interrupted | Honest online-only/local-only distinction; no false recovery promise | “Saved online only” or “Changes are safe in this browser” | 019-FR-017–019, 021; 019-SC-004 |
| `D-05-CN` cancelled read | Cancellable request cancelled | Stable shell, no false result | “Loading cancelled. Nothing changed.”; Retry focused | 019-FR-020–021, 023 |

### D-06 — Destructive conflict confirmation

| state | trigger | what the user sees | copy / action | FR/SC refs |
|---|---|---|---|---|
| `D-06-DF` default | Difference review complete and user selected server copy | Blocking alert names local edits that will be lost; focus safe back action | “Discard 3 local edits?”; “Back to comparison” | 019-FR-018–019, 021, 023 |
| `D-06-LD` loading | Local-backup download or final server-copy load pending | Initiating action shows progress and destructive confirmation remains disabled | “Preparing local backup…” or “Opening server copy…” | 019-FR-018–021 |
| `D-06-NA` empty/not applicable | No canonical tree exists | No server/local conflict; D-02 remains canonical | No destructive dialog rendered | 019-FR-003, 021 |
| `D-06-ND` no differences | Comparison finds no local edits | Close destructive path and return resolved | “No local edits need to be discarded” | 019-FR-019, 021 |
| `D-06-ER` error | Backup download or final choice fails | Keep both copies/dialog; expose retry/reference | “Nothing was discarded”; “Retry” | 019-FR-018–021 |
| `D-06-PF` partial failure | Diff can name only some local edits | Block discard and require complete comparison or successful backup | “We couldn't verify every local edit” | 019-FR-019, 021 |
| `D-06-OF` offline / interrupted | Connectivity drops before completion | Keep local draft, disable server-copy action, return D-03 | “Reconnect before using the server copy” | 019-FR-017–019, 021; 019-SC-004 |
| `D-06-CN` cancelled/deferred | User closes/defer before mutation dispatch | Preserve both copies and conflict status | “Conflict deferred”; focus restoration fallback applies | 019-FR-019, 021, 023 |

### D-05 boundary state IDs

| id | trigger | exact content/actions | focus and responsive contract | FR refs |
|---|---|---|---|---|
| `D-05-UW` | Authenticated exposed web viewport is below 1024 CSS px | Heading “Thinking Mode needs a wider window”; body “Use a window at least 1024 px wide to edit this tree.”; action “Back to workspace”. No graph content is requested/rendered. | Programmatic focus moves to the heading; 390×851 has no horizontal scroll; the Back action is the next tab stop. | 019-FR-002, 021–024 |
| `D-05-FD` | Normal OFF/not-selected flag result or missing member flag | Heading “Thinking Mode isn't available for this account”; body explains that existing BrainBuddy work is unchanged; action “Back to Tasks”. No support reference because no failed service request is implied. | Focus heading; route remains safe; no canvas request/mutation. | 019-FR-001–002, 021; 019-SC-006 |
| `D-05-FU` | Runtime flag storage is degraded/unreadable | Heading “Thinking Mode is temporarily unavailable”; body “We couldn't check access safely.”; actions “Retry” and “Back to Tasks”; copyable support reference from the failed request. | Focus heading, then Retry; status is announced once; no canvas content/mutation. | 019-FR-001–002, 020–021 |

### D-06 confirmation/recovery state IDs

All four are modal (`role="dialog"`, `aria-modal="true"`) with labelled heading, trapped focus, Escape/cancel without mutation, and trigger-focus restoration. Safe action receives initial focus; destructive action follows explanatory copy and is never the default.

| id | trigger | named consequence and actions | loading/error/interrupted behavior | undo |
|---|---|---|---|---|
| `D-06-TD` | User requests deletion after pending-work barrier resolves | “Delete ‘{tree name}’?”; “Deletes {card count} cards and {relation count} relations from BrainBuddy.”; `Cancel` (initial focus), `Delete tree`. | At 300 ms “Deleting tree…” and disable repeat submit; on error keep tree/dialog, show Retry + support reference; offline disables Delete. | Server tree deletion is not session undoable; cancel is the safe path. |
| `D-06-CD` | Delete selected card with connected relations | “Delete this card and {relation count} relations?”; show inert card label preview; `Keep card` (initial), `Delete card and relations`. | At 300 ms “Saving deletion…”; on save error restore/retain local command in draft and expose Retry; Escape keeps card. | The confirmed local graph command participates in current-session undo after it is applied. |
| `D-06-PW` | Leave, tree switch, import, sign-out or account switch with pending work | “Resolve unsynced changes before continuing”; list affected tree names and edit counts; `Stay and retry` (initial), `Download backup`, `Discard and continue`. Account transition resolves every departing-owner record. | Save/backup shows 300 ms progress; partial failure names unresolved trees and blocks transition; offline keeps all records; cleanup failure cancels transition. | Discard/identity transition is not undoable; backup is offered before explicit discard. |
| `D-06-EX` | A local draft is stale after 30 days inactivity | “A local draft is over 30 days old”; it stays outside canvas; `Recover draft` (initial; resets 30 days), `Download backup`, `Discard draft`. | Backup/recovery shows progress; error keeps stale bytes and offers retry; storage read failure makes no cleanup claim. | Discard is not undoable; recovery starts a new editing session/history. |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 | BrainBuddy shell / Thinking Mode title | Opens the dedicated CRT surface only for an effectively exposed authenticated account | 019-FR-001–002 |
| D-01 | Tree title button | Opens create, switch, rename, import, export, and delete actions without leaving canvas | 019-FR-004 |
| D-01 | Bottom-up card graph | Renders editable cards and source=cause → target=effect curves with causes below effects | 019-FR-005–006 |
| D-01 | Selectable card + handles | Selects a card, supports drag/connection gestures, and exposes a clear target for keyboard actions | 019-FR-010, 014–015, 023 |
| D-01 | Enter / Tab hint and behavior | Creates a cause below or a same-level sibling, with the specified inheritance rule | 019-FR-007–009, 012–013 |
| D-01 | Left tool rail | Selects, adds, connects, and pans without hiding keyboard access | 019-FR-010, 012–014 |
| D-01 | Bottom zoom cluster | Fit-all, zoom out/in, and visible zoom percentage | 019-FR-014 |
| D-01 | Inspector label field | Edits the selected card label without duplicating graph ownership | 019-FR-015 |
| D-01 | Incoming/outgoing relation list | Shows neutral causal links and their direction without parent/child terminology | 019-FR-006, 015 |
| D-01 | Delete card action | Starts confirmed cascade deletion when connected relations exist | 019-FR-010, 021 |
| D-01 / D-04 | Save status pill | Distinguishes saved, saving, unsaved/error, and offline-local | 019-FR-017–018, 021 |
| D-02 | First-run empty state CTA | Creates an empty tree without fabricated content; Enter, Tab, or Add card creates and names the first effect afterward | 019-FR-003, 009, 021 |
| D-02 | Tree menu disabled states | Prevents rename/export/delete when no tree exists and communicates why | 019-FR-004, 021, 023 |
| D-02 | Import tree JSON | Validates before replacing current data and surfaces malformed/cyclic/duplicate reasons | 019-FR-004, 011, 020–021 |
| D-03 | Offline-local status + Retry save | Preserves unsynchronized edits and offers a direct recovery attempt | 019-FR-017–018 |
| D-03 | Server-copy / local-draft previews and Review differences | Preserves both revisions and requires review before an explicit conflict choice | 019-FR-018–019, 021 |
| D-03 | Download local backup / discard confirmation | Provides a backup path and makes the exact three-edit loss explicit before replacement | 019-FR-018–019, 021 |
| D-03 | Support reference | Gives a copyable correlation reference for failed server requests | 019-FR-011, 018, 021 |
| D-03 | Resolve later / defer | Closes an automatically or manually opened comparison without mutating either copy; leaves a visible conflict status that resumes Review differences | 019-FR-019, 021, 023 |
| D-04 | Nonmodal keyboard shortcut disclosure | Exposes all required keys, the Escape/close path, and that controls/inputs keep native behavior while focus remains on its trigger | 019-FR-012–013, 023 |
| D-04 | Arrow-key traversal | Moves focus/selection to the nearest related card in the requested direction | 019-FR-012 |
| D-05 / `D-05-UW` / `D-05-FD` / `D-05-FU` | Loading/error/partial/storage and exposure boundary states | Defines timed progress, retry, integrity, unsupported width, normal disabled and degraded-service behavior | 019-FR-001–002, 017–023 |
| D-06 / `D-06-TD` / `D-06-CD` / `D-06-PW` / `D-06-EX` | Named-loss dialogs, local backup and stale recovery | Makes each destructive consequence concrete, defaults focus to safety and covers all required transition/recovery confirmations | 019-FR-004, 010, 018–021, 023 |
| D-06 | Back to comparison / discard-and-use-server actions | Keeps initial focus on the safe path and separates final destructive confirmation from conflict review | 019-FR-018–019, 021, 023 |

### Requirements → designed affordance/state

| requirement | designed affordance or state | coverage |
|---|---|---|
| 019-FR-001 | Server-owned exposure is represented by the global-entry boundary and fail-closed behavior; no user-facing flag toggle is designed | D-01 shell; D-02 unavailable boundary |
| 019-FR-002 | Thinking Mode shell/title opens `/crt`; disabled exposure does not render the canvas | D-01, D-02 shell |
| 019-FR-003 | Last-tree default; truthful first-run empty state; local-draft first-run recovery | D-01 default; D-02 empty; D-03 recovery |
| 019-FR-004 | Title menu with create/switch/rename/import/export/confirmed delete | D-01 title button; D-02 open menu |
| 019-FR-005 | Card graph and curved arrow SVG treatment | D-01, D-04 |
| 019-FR-006 | Neutral “incoming causes” / “outgoing effects” labels and no typed node control | D-01, D-04 inspector |
| 019-FR-007 | Enter shortcut and “add a cause below” hint | D-01, D-04 shortcut sheet |
| 019-FR-008 | Tab shortcut and sibling-inheritance rule | D-01, D-04 shortcut sheet |
| 019-FR-009 | Empty canvas Enter/Tab hint and first-card placement | D-02 empty state |
| 019-FR-010 | Card handles, connect tool, drag-ready card, relation selection/deletion, confirmed card deletion | D-01, D-04 |
| 019-FR-011 | Inline validation/error rows, retry, support reference, incomplete-relation state | D-03, D-05 |
| 019-FR-012 | Shortcut sheet covers Delete, undo/redo, Space+drag, +/−, 0, arrows and Escape | D-04 |
| 019-FR-013 | Shortcut sheet scopes shortcuts to composite canvas mode, preserves native controls and documents Escape → normal Tab navigation | D-02, D-04 |
| 019-FR-014 | Left pan tool and lower-right fit/zoom cluster with percentage | D-01, D-04 |
| 019-FR-015 | Selected-card inspector with editable label and causal links | D-01, D-04 |
| 019-FR-016 | Saved status remains synchronized with visible graph after history changes | D-01, D-04 shell status |
| 019-FR-017 | Saved pill, offline pill, saving/error state cards | D-01, D-03, D-05 |
| 019-FR-018 | Offline-local banner, Retry save, required review, backup and separate discard confirmation | D-03, D-06 |
| 019-FR-019 | Two-column server/local previews, required difference review, local backup, named lost edits and owner/origin/tree scope | D-03, D-06 |
| 019-FR-020 | Owner-scoped shell, safe import/error behavior, stale-draft and account-transition cleanup disclosure | D-01–D-03, D-06-PW, D-06-EX |
| 019-FR-021 | Timed loading, first-run empty, error, partial, offline, exposure boundaries, conflict and destructive confirmation states | D-02, D-03, D-05 family, D-06 family |
| 019-FR-022 | Sparse controls and no layout-heavy chrome over the board; responsiveness is an implementation acceptance concern | D-01, D-04 |
| 019-FR-023 | Named controls, focus rings, dialog semantics, status text, and non-color labels | All screens |
| 019-FR-024 | BrainBuddy shell/tokens plus whiteboard navigation and directed curves without copied branding | All screens |
| 019-FR-025 | No AI affordance or external processing language appears | All screens by omission |
| 019-FR-026 | No mobile editor, links, sharing, comments, logic gates, evidence/actions, or version controls appear | All screens by omission |

### Requirements with no direct user affordance

- **019-FR-001**: exposure is a server-owned rollout boundary, not a settings control.
- **019-FR-020**: authentication, owner isolation, wrong-owner behavior, correlation IDs, export, and purge remain service contracts; the design only shows safe state/status surfaces.
- **019-FR-022**: responsiveness is verified in implementation and acceptance testing rather than by a new control.
- **019-FR-025**: “no external AI processing” is a scope constraint; adding an affordance would violate it.
- **019-FR-026**: excluded capabilities are intentionally absent; no placeholder controls are designed.

### Affordances with no requirement

None. The title menu, tool rail, inspector actions, zoom controls, save/status surfaces, recovery choices, and shortcut sheet each trace to one or more listed functional, accessibility, or success requirements.

## Primary loop impact

This surface changes the thinking part of the loop only. It does not alter capture, atomic-item creation, clarify/approve, routing, Tasks, Tags, or the deferred Weekly Review. The first-release path is:

`Thinking Mode → open last tree / truthful empty state → create or edit cards → inspect cause/effect links → autosave or recover local draft → return to the existing BrainBuddy workspace`

Task/Project entry points, Brain Dump promotion, evidence/results, and any AI processing remain out of scope. No new task lifecycle or list is introduced.

## Mobile viability

- **Viewport**: editor not supported below 1024 CSS px; `D-05-UW` is the truthful narrow-web boundary. Its 390×851 acceptance has no horizontal scroll or clipped control. Native mobile remains unchanged and exposes no CRT/Thinking Mode entry in v1.
- **Tap targets**: desktop controls use at least 32px visual targets; the narrow-web unavailable boundary has no editing actions.
- **One-handed reach**: not applicable to the desktop editor; no mobile editing claim is made.
- **Destructive actions**: connected-card deletion, tree deletion, discard-local-draft, leave-without-sync, import-over-pending-work, and account-scope changes require explicit confirmation. Copy names what is lost: “Leave without syncing” and “Delete tree” are never silent.

## Keyboard and focus

- **Canvas composite**: the canvas is a labelled `role=group`; cards are native buttons using roving `tabindex` and `aria-pressed` for selection, so no listbox/option ownership is implied. Arrow navigation moves both focus and selection. Visible semantic badge text and each button's accessible name include Effect, Root cause, Intermediate or Disconnected plus selected state. Connection handles are separate sibling overlay buttons (never interactive descendants of a card button), exposed only for the selected card in connection mode and named “Connect from {side} of {card label}”; decorative SVG paths and visual-only handle dots are hidden.
- **Tab order**: shell entry and tree title → save/status and Shortcuts trigger → canvas toolbar → the one roving selected-card stop/active handles → zoom controls → inspector fields/actions. DOM order follows visual/interaction order.
- **Focus on open**: D-01 focuses the selected card (or the canvas composite when no selection); inspector label receives focus only after explicit edit activation. D-02 focuses “Create a new tree”; D-03 focuses “Review differences”; D-04 is nonmodal and retains focus on the Shortcuts trigger; D-05 boundaries focus their heading; each D-06 state focuses its named safe action.
- **Focus restored on close**: tree menu returns to the title button; Shortcuts close/Escape leaves or restores focus on its trigger; inspector close returns to selected card. A manually opened dialog returns to its initiating action. If D-03 opens automatically on reconnect, Escape, Resolve later, or retry failure returns to the element focused immediately before open when it is still connected/enabled; otherwise focus moves to the persistent conflict-status “Review differences” control, falling back to the canvas composite if that control unmounts.
- **Escape**: closes menu, nonmodal shortcut disclosure, inspector, conflict dialog, and confirmation without mutation. A pending draft remains intact.
- **Canvas keys**: Enter, Tab, Delete, Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z (and Ctrl+Y), Space+drag, +/−, 0, and arrows operate only while the composite canvas shortcut mode is active, not while editing text or another native control. Escape exits canvas shortcut mode and returns the selected card to an ordinary focus stop; the next Tab/Shift+Tab leaves the canvas normally.
- **Accessible names**: every icon-only control uses a visible tooltip/title plus an accessible name; tool buttons identify Select, Add card, Connect cards, Pan canvas, Fit all, Zoom out, Zoom in, Close inspector, and Dismiss/close actions.
- **Announcements**: selection, save status, retry result, import validation, relation rejection, conflict choice, and destructive confirmation use status/live-region announcements in implementation.
- **Color independence**: selected, root, leaf, warning, offline, error, and partial states pair color with text, iconography, borders, labels, or status copy.
- **Dialog behavior**: modal D-03/D-06 states use `role="dialog"`, `aria-modal="true"`, labelled headings, trapped focus, and explicit cancel/escape paths. D-04 Shortcuts is a labelled nonmodal region with a close action. Destructive buttons are not adjacent without explanatory copy.

## Accepted design decisions

1. Enable the existing global Thinking Mode entry and route it to `/crt`; keep the save/status pill in the canvas top bar beside the active tree context.
2. Use semantic card treatments in the first release: top effects are red, current root causes are yellow, and intermediate cards are white, always with non-color labels/affordances.
3. Keep a manual Connector tool in the left rail alongside automatic Enter/Tab relation creation.

Conflict handling uses the safer fixed default: preview both copies, review differences, offer a local backup, and require a second explicit confirmation before discarding named local edits.

**Human sign-off was granted by the product owner on 2026-09-19.**
