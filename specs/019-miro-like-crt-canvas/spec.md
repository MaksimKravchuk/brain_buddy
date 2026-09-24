# Feature Specification: Miro-like CRT Canvas

**Feature Branch**: `crt`

**Created**: 2026-09-19

**Status**: Approved for implementation planning — design signed off 2026-09-19

**Input**: User description: "A simple Miro-like Current Reality Tree canvas with cards, curved arrows, Miro-inspired navigation/menu, keyboard-first Enter/Tab creation, and immediate integration into the BrainBuddy web UI."

## Clarifications

### Session 2026-09-19

- Q: What is the canonical causal direction and Enter behavior? → A: Bottom-up CRT; Enter creates a cause below the selected effect and links the new cause to that effect.
- Q: What does Tab create? → A: A same-level sibling cause that inherits the selected card’s effect when one exists.
- Q: Where does the first release open? → A: The existing Thinking Mode navigation opens `/crt`; Task and Project entry points are deferred.
- Q: What happens on first open? → A: Open the last tree; if no tree exists, show a first-run empty state; tree CRUD/import/export lives in the title menu.
- Q: Which hotkeys are required? → A: Enter, Tab, Delete, undo/redo, Space+drag, plus/minus zoom, zero fit-all, and arrow-key traversal between related cards.
- Q: What is the first-release scope? → A: Web desktop tree menu, cards/arrows, drag, inline edit, autosave, undo/redo, pan/zoom/fit and selected-card inspector.
- Q: What is explicitly excluded? → A: Mobile editing, Task/Project links, Brain Dump promotion, collaboration/share, comments, AND/OR, evidence/actions, version UI and AI validation.
- Q: How are save failures handled? → A: Online-first with locally retained unsynchronized changes, visible status, retry and leave warning.
- Q: Who receives the first rollout? → A: The approved internal dogfood account through a dedicated server-owned CRT flag.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enter Thinking Mode and manage trees (Priority: P1)

An authenticated internal user opens Thinking Mode from the existing BrainBuddy navigation and continues in the valid unexpired last-tree preference, otherwise the most recently updated owner-scoped tree. If no tree exists, the user creates the first tree from a clear empty state. The title menu supports switching and basic tree management without leaving the canvas.

**Why this priority**: The canvas has no product value while the existing Thinking Mode remains a disabled placeholder or the user cannot open and persist a tree.

**Independent Test**: Enable the CRT rollout for an account, open Thinking Mode, create and rename a tree, reload, and observe the same tree and content; then switch between two trees and export/import one.

**Acceptance Scenarios**:

1. **Given** the feature is effective and the user has a previously opened tree, **When** the user chooses Thinking Mode, **Then** `/crt` opens that owner-scoped tree and fits its content into view.
2. **Given** the feature is effective and the user has no trees, **When** the user opens Thinking Mode, **Then** a first-run empty state explains how to create the first tree and no demo content is fabricated.
3. **Given** an open tree, **When** the user uses the title menu, **Then** they can create, switch, rename, export, import, or request deletion of an owner-scoped tree.
4. **Given** a deletion request, **When** the user has not confirmed the destructive action, **Then** the tree and any unsynchronized work remain intact.
5. **Given** the feature is not effective, **When** the user navigates directly to a CRT URL, **Then** the canvas is not exposed and the rest of BrainBuddy remains usable.
6. **Given** a deletion request with no unresolved pending-work barrier, **When** the user confirms it, **Then** the owner-scoped tree is deleted, its last-tree preference is invalidated, and the most recently updated remaining tree opens or the truthful first-run state appears.

---

### User Story 2 - Build a causal tree from the keyboard (Priority: P1)

A user selects a card and rapidly grows a bottom-up causal tree. Enter creates a cause below and connects it to the selected effect. Tab creates a sibling cause at the same level, inheriting the selected card’s effect where one exists. Focus moves into inline editing so the new card can be named immediately.

**Why this priority**: Fast, low-friction causal decomposition is the core user outcome and the reason to build a specialized canvas instead of using generic forms.

**Independent Test**: Starting with one selected effect, create a branching 10-card tree using only the keyboard, verify every generated relation is cause → effect, reload, and observe the same graph.

**Acceptance Scenarios**:

1. **Given** a selected card not currently being edited, **When** the user presses Enter, **Then** a new card appears below, a relation points from the new cause to the selected effect, the new card becomes selected, and its label enters edit mode.
2. **Given** a selected card with one unique nearest outgoing effect, **When** the user presses Tab, **Then** a new sibling appears at the same depth and links to that effect without changing the original relation.
3. **Given** a selected card with no effect to inherit, **When** the user presses Tab, **Then** an unlinked same-level card is created and enters edit mode rather than inventing a causal relation.
4. **Given** the user is editing text or another input, **When** Enter, Tab, Delete, arrows, plus, minus, zero or Space are pressed for text/input behavior, **Then** canvas shortcuts do not hijack those keystrokes.
5. **Given** a selected card, **When** the user presses an arrow key, **Then** selection moves predictably to the nearest related card in that spatial direction; no relation or content is changed.

---

### User Story 3 - Edit and navigate like a focused whiteboard (Priority: P2)

The user can drag cards, edit labels inline, draw or remove arrows, select cards or relations, pan the infinite workspace and control zoom through both pointer controls and keyboard shortcuts. Curved arrows remain readable and visibly directed when cards move.

**Why this priority**: Miro-like direct manipulation is necessary to refine a tree after fast keyboard capture and to understand branching causality at a glance.

**Independent Test**: Create several cards, manually connect two valid cards, drag them, edit text, pan/zoom/fit, select a relation and remove it, then verify the graph is persisted and invalid links are rejected without data loss.

**Acceptance Scenarios**:

1. **Given** an open tree, **When** the user creates, moves, edits or connects cards, **Then** the canvas updates immediately and curved arrows remain attached to the correct card edges with clear arrowheads.
2. **Given** an attempted self-link, duplicate relation or cycle, **When** the user completes the connection gesture, **Then** the relation is not created and an inline actionable error is announced, with a support reference when a server request occurred.
3. **Given** a card or relation is selected, **When** Delete is pressed outside text editing, **Then** a relation is removed directly and a card with connected relations requires explicit confirmation before cascade deletion.
4. **Given** any viewport, **When** the user pans, zooms, chooses fit-all or uses the zoom controls, **Then** the tree remains navigable and the current zoom level is visible.
5. **Given** a selected card, **When** the inspector is open, **Then** the user can edit its label and see neutral incoming/outgoing causal context without parent/child terminology.

---

### User Story 4 - Recover from save and network failures (Priority: P2)

The user always knows whether the tree is saved. If synchronization fails or connectivity drops and compatible browser storage is available, pending edits remain recoverable in the current account/browser scope. If storage is unavailable/full, same-page in-memory retry continues with a persistent named-loss warning and destructive-navigation barrier, but reload/crash recovery is not claimed.

**Why this priority**: A thinking canvas invites rapid edits; silent data loss would make the feature unusable even if drawing interactions are polished.

**Independent Test**: Make edits, force save failure, reload and recover the pending draft, retry after connectivity returns, then verify the server copy matches and the local pending state clears.

**Acceptance Scenarios**:

1. **Given** a successful edit, **When** autosave completes, **Then** the UI changes from saving to saved and a reload returns the canonical update.
2. **Given** a failed or timed-out save, **When** the failure is reported, **Then** the UI shows unsaved state, a retry action and a copyable support reference while preserving the local pending changes.
3. **Given** pending local changes, **When** the user reloads the same account and origin, **Then** the app offers or automatically restores the newer compatible local draft without overwriting newer canonical server data silently.
4. **Given** pending local changes, **When** the user attempts to leave, switch account, switch tree, import, delete or sign out, **Then** the app blocks or warns before the pending work can be discarded.
5. **Given** account scope changes, **When** another user signs in on the same browser, **Then** the prior owner’s pending tree content is neither displayed nor applied.

### Edge Cases

- A tree has one card, no relations, or multiple disconnected branches.
- Enter/Tab is pressed with no selected card: create a neutral unlinked card near the viewport center and enter edit mode.
- Tab is pressed on a card with multiple outgoing effect relations: use the visually nearest effect in the upward direction; if no unique nearest relation exists, create an unlinked sibling and do not guess.
- A generated placement would overlap an existing card: offset to the nearest free grid position while retaining the intended level.
- A card label is empty or only whitespace: keep editing active and prevent an empty canonical card from being saved.
- A label is long: wrap within the card and preserve access to the full text without growing controls off screen.
- Import contains malformed JSON, unknown schema, missing endpoints, duplicates or cycles: reject it before replacing current data and surface an actionable reason.
- Import succeeds while the current tree has pending changes: require save, retry or explicit discard first.
- A stale canonical tree conflicts with a pending draft: preserve both, explain the conflict and require an explicit choice; never silently overwrite either copy.
- Browser storage is unavailable or full: continue online-only, show that local recovery is unavailable, and do not claim the edit is protected locally.
- The tree contains approximately 200 cards and relations: interaction and shortcuts remain responsive; long operations expose progress rather than freezing.
- A card or relation is behind a floating panel: fit-all and selection scrolling keep it reachable.
- The feature flag changes while the user is editing: preserve unsynchronized work locally and fail closed for further server mutations until exposure returns.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST expose a dedicated server-owned Current Reality Tree feature flag, initially unavailable by default and effective only for the selected internal account during the first rollout; the flag MUST control exposure rather than authorization. A content-free authenticated CRT exposure probe MUST distinguish normal ineffective exposure from degraded/unreadable flag storage for direct-route and already-open-canvas states without returning tree content.
- **FR-002**: An authenticated user with effective exposure MUST be able to open Thinking Mode from the existing BrainBuddy navigation at `/crt`; direct CRT navigation without effective exposure MUST fail closed without affecting other product routes.
- **FR-003**: Thinking Mode MUST open the valid unexpired owner/origin-scoped last-tree preference when it occurs in the owner-scoped list; otherwise it MUST open the most recently updated owner-scoped tree, and when no tree exists show a truthful first-run empty state with an action to create the first tree.
- **FR-004**: The tree-title menu MUST support create, switch, rename, confirmed delete, JSON import and JSON export without navigating away from Thinking Mode.
- **FR-005**: The canvas MUST render simple editable cards and directed curved relations whose canonical semantics are `source = cause` and `target = effect`; causes are placed below effects by the default bottom-up layout.
- **FR-006**: The UI MUST use neutral card, cause and effect language and MUST NOT require parent/child node types for user interaction or derive relation direction from a node type.
- **FR-007**: Enter outside text editing MUST create a card below the selected card, create a cause → selected-effect relation, select the new card and begin inline editing.
- **FR-008**: Tab outside text editing MUST create a same-level sibling that inherits the selected card’s unique nearest effect; when no unique effect can be inherited it MUST create an unlinked sibling rather than guess.
- **FR-009**: With no card selected, Enter or Tab MUST create one unlinked card near the viewport center and begin inline editing.
- **FR-010**: The canvas MUST support card drag positioning, inline label editing, manual relation creation, relation selection/deletion and confirmed cascade card deletion.
- **FR-011**: Self-links, duplicate cause → effect relations, missing endpoints and cycles MUST be prevented with human-readable inline feedback, retry/correction guidance, focus/announcement, and a copyable correlation reference where a server request occurred.
- **FR-012**: The first release MUST support Delete; Cmd/Ctrl+Z; Shift+Cmd/Ctrl+Z (and Ctrl+Y where conventional); Space+drag; plus/minus zoom; zero fit-all; directional arrow navigation among related cards; and Escape to leave canvas shortcut mode.
- **FR-013**: Canvas shortcuts MUST NOT fire while focus is in text editing, form controls, menus, dialogs, or another interaction where the same key has a native meaning. The canvas MUST behave as one composite focus region: Tab creates a sibling only while canvas shortcut mode is active, and Escape exits that mode so subsequent Tab/Shift+Tab resumes ordinary browser focus navigation without trapping the keyboard user.
- **FR-014**: Pointer and keyboard controls MUST support pan, zoom, fit-all, center/retain selection and a visible zoom percentage.
- **FR-015**: Selecting a card MUST reveal a compact inspector that supports label editing and displays its incoming causes and outgoing effects without duplicating graph ownership.
- **FR-016**: The canvas MUST provide undo and redo for user graph/layout changes made during the current editing session and MUST keep the visible graph and pending save state consistent after each history operation.
- **FR-017**: User edits MUST update the canvas immediately and autosave to the existing owner-scoped canonical tree; the interface MUST distinguish saving, saved, unsaved/error and offline-local states.
- **FR-018**: When a save cannot complete and compatible browser storage is available, the system MUST retain the unsynchronized owner/origin-scoped draft locally in that same browser, offer retry, and warn or block before navigation, tree switching, import, deletion, sign-out or account-scope change can discard it. If storage is unavailable/full, the exact request/key and newer edits MUST remain retryable in memory for the current page, with a persistent named-loss warning and the same destructive-navigation barrier; the system MUST NOT claim reload/crash recovery.
- **FR-019**: Draft recovery MUST compare local and canonical revisions/timestamps and MUST NOT silently overwrite a newer canonical tree or expose one owner’s content to another owner.
- **FR-020**: Tree creation, loading, editing, import, export and deletion MUST preserve existing session authentication, owner isolation, wrong-owner 404 behavior, correlation IDs and canonical account export/purge coverage. Browser-local recovery drafts and last-tree preferences MUST be excluded from server account export, expire after 30 days without edit/use, and be cleared for the departing owner on the active origin during same-browser sign-out, account-switch, and account-deletion flows. On the next app run after draft expiry, the stale draft MUST remain outside the canvas and offer one explicit backup/recover-or-discard decision before physical cleanup; recovering resets the inactivity window. No cross-device/browser-storage purge is claimed, and residual bytes may require clearing site data if the app is never run again.
- **FR-021**: Loading, empty, malformed import, save failure, stale conflict, local-storage unavailable, feature-disabled and destructive-confirmation states MUST be visible and actionable; failures MUST not be represented as successful saves.
- **FR-022**: The desktop canvas MUST remain perceptually responsive for approximately 200 cards and their relations, including selection, drag, keyboard creation, pan and zoom.
- **FR-023**: Interactive controls MUST have keyboard access, visible focus and accessible names; graph semantics and selection/error states MUST not be communicated by color alone.
- **FR-024**: The canvas MUST use BrainBuddy’s existing visual tokens and shell while adopting the reference’s whiteboard layout, floating compact controls, light grid, card simplicity and readable curved arrows; it MUST not copy Miro branding, collaboration controls or commercial actions.
- **FR-025**: The feature MUST perform no external AI processing and MUST not surface AI validation controls in this release.
- **FR-026**: Native mobile editing, Task/Project linking, Brain Dump promotion, collaboration/share, comments, AND/OR logic, evidence/actions and version history UI MUST remain outside this release.

### Key Entities

- **Tree**: An owner-scoped named Current Reality Tree containing cards, directed causal relations, layout metadata and revision/timestamp information.
- **Card**: A short user-authored statement positioned on the canvas; it participates in zero or more incoming cause relations and outgoing effect relations but has no required parent/child type.
- **Relation**: A directed link from a cause card to an effect card, rendered as a curved arrow and protected from self-links, duplicates and cycles.
- **Last-tree preference**: The owner/origin-scoped identity of the last opened tree; it is convenience state validated against an owner-scoped list before use.
- **Viewport state**: Accepted per-tree center/zoom stored with canonical layout and pending drafts for recovery/diagnostics; normal entry still fits all content and does not restore it as a browser preference.
- **Pending draft**: Owner/origin/tree-scoped unsynchronized tree and layout changes retained locally until synchronization, explicit discard or account-scope cleanup.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A representative internal user can open Thinking Mode and create a branching 10-card causal tree using only keyboard creation/navigation in under 2 minutes.
- **SC-002**: In acceptance tests, 100% of Enter-created relations persist as new cause → selected effect and 100% of unambiguous Tab-created siblings inherit the same effect after save and reload.
- **SC-003**: On a representative approximately 200-card tree, at least 95% of sampled selection, drag, Enter/Tab creation, pan and zoom interactions present visible feedback within 200 ms on the supported test desktop.
- **SC-004**: With compatible browser storage available, save-failure acceptance tests demonstrate zero silent data loss: pending edits survive reload in the same account/browser scope, remain isolated from another account, and synchronize or resolve explicitly after recovery. Storage-unavailable tests separately prove same-page retry, persistent named-loss warning/barrier, and no false reload/crash-recovery claim.
- **SC-005**: Invalid self, duplicate and cyclic links are rejected in 100% of automated acceptance cases with actionable feedback and no graph mutation.
- **SC-006**: With the CRT flag ineffective, direct and navigation-based attempts expose no canvas, issue no tree mutation, and leave all existing task and Brain Dump journeys operational.
- **SC-007**: The changed web surface has no blocked controls, clipping, unintended overlap or horizontal page scrolling at supported desktop widths and introduces no serious or critical automated accessibility violation.

## Assumptions

- The initial audience is one approved internal dogfood account; broader rollout is a later product decision.
- The first supported editing surface is desktop web at 1024 CSS pixels or wider. Narrower web shows a truthful unavailable boundary rather than an editor. The native mobile app remains unchanged and exposes no CRT/Thinking Mode entry in v1.
- Existing owner-scoped tree persistence is the canonical graph store and will be evolved rather than duplicated.
- Existing stored trees must remain readable; any compatibility translation is explicit and preserves cause → effect direction.
- The app is online-first. Local recovery protects pending work on the same browser/account but does not promise cross-device offline merge.
- No external AI, collaboration service or new subprocessor is introduced.
