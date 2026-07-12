# BrainBuddy mobile-first UX proposal

Status: Founder review proposal — not an implementation specification
Primary surface: **Operate** (capture and review queues); secondary surface: **Explore / Inspect** (CRT)

## Product hierarchy

BrainBuddy’s mobile wedge is a short loop, not a smaller desktop canvas:

1. **Capture quickly** — start a Brain Dump from anywhere, see that speech is safe, and keep speaking.
2. **Understand proposals** — distinguish live transcript, provisional candidates, reconciled suggestions, and user edits.
3. **Confirm intentionally** — nothing is routed, deleted, or promoted until the user confirms a frozen batch.
4. **Review deliberately** — process a bounded Weekly Review queue one item at a time, with progress and a clear next action.
5. **Think deeply when warranted** — promote a recurring/complex problem to CRT, then use the tree in a focused mobile viewer/editor or the full desktop workspace.

This preserves ADR-0001’s capture → organize → review → optional CRT path and ADR-0002’s shared asynchronous operation/confirmation contract. It does not turn BrainBuddy into a task manager.

## Navigation model

### Phone (below 768px)

A persistent four-item bottom bar provides thumb-reachable destinations:

- **Dump** — primary capture action and resumable operation.
- **Review** — queue, item decisions, and review completion.
- **Trees** — CRT list and focused tree/detail view.
- **More** — operation history, privacy/retention, task-tracker destination, account, and sign-out.

The current section title and operation status sit in a compact top app bar. Contextual back navigation replaces the title on detail/editor screens. A sticky bottom action dock contains the current primary action; it sits above the navigation and safe-area inset.

### Desktop (768px and above)

A persistent left rail holds the same information architecture. The primary workspace becomes a two- or three-pane composition:

- Brain Dump: transcript / candidate list / selected candidate or operation status.
- Weekly Review: queue / selected item / action or history panel.
- CRT: tree canvas / inspector, preserving the existing strong canvas-first layout.

Desktop is not a stretched phone stack: it increases simultaneous context, keeps selection visible, and avoids modal churn.

## Responsive rules

| Concern | Phone | Tablet / desktop |
|---|---|---|
| Navigation | Bottom bar; 4 stable destinations | Left rail; labels always visible |
| Detail | Replaces list; explicit Back | Adjacent pane; selection persists |
| Primary action | Sticky thumb-zone dock | Inline in active pane/header |
| CRT | Focused subtree, pan/zoom, selected-node sheet | Full canvas plus inspector |
| Forms/editor | Full-width page or bottom sheet; keyboard-safe dock | Inspector or centered dialog |
| Confirmation | One card at a time, optional “confirm safe additions” | Batch list with side-by-side diff |
| Long text | Natural height, 2-line previews only in lists, explicit expand | Constrained readable measure in detail pane |
| Transient status | Inline beside affected object; toast only for background completion | Inline plus compact activity area |

Breakpoints are content-driven. The prototype uses 768px for the shell transition and 1120px for a third desktop pane. Support is explicitly checked at 375px and 430px; no horizontal page scroll is allowed.

## Component and layout principles

- **One dominant action per state.** Recording emphasizes Stop; confirmation emphasizes Confirm selected; review detail emphasizes a decision, not navigation.
- **44px minimum touch targets**, 8px spacing rhythm, 16px phone gutters, and safe-area padding via `env(safe-area-inset-*)`.
- **State before decoration.** Status labels use text plus shape/icon, never color alone. Unknown-duration work uses stage text and indeterminate progress, not fake percentages.
- **Proposals are not records.** “Provisional,” “Reconciled,” “Edited by you,” low-confidence, conflict, and pending-route states are visibly distinct.
- **Destructive and external actions remain explicit.** Delete, route, existing-item edits, and CRT promotion stay individually reviewable even when “select safe additions” is available.
- **Keyboard and focus.** Logical DOM order, visible `:focus-visible`, Escape closes sheets/dialogs, Enter submits only single-line fields, and text areas preserve newline entry. Sticky controls move above the on-screen keyboard; content remains scrollable.
- **Resumability.** Closing the app never implies cancellation. Every live operation exposes “Safe to leave” and restores its phase, item, edits, and queue position.
- **Offline honesty.** Recording can continue locally within the configured limit, with a persistent offline banner, local duration/storage status, and reconnection upload state. No server progress is implied while offline.
- **Error locality.** Retry is placed beside the failed stage/action. Correlation/reference details are expandable, not primary copy. Terminal microphone/storage errors offer salvage or deletion where possible.
- **Accessible semantics.** Landmarks, headings, list semantics, `aria-live` for transcript/progress, explicit button labels, form labels/help, reduced-motion support, and contrast suitable for WCAG AA.
- **Visual continuity.** Reuse the current slate surfaces, sky accent, soft borders/shadows, and restrained rounded corners. The proposal removes desktop-only hover dependence and does not lean on glass/gradient effects.

## Critical journeys

### Brain Dump

1. Idle: concise consent/retention context and one large “Start recording” control.
2. Recording: duration, upload/network state, waveform feedback, stable partial transcript, and provisional candidates arriving without stealing focus.
3. Stop: seal upload → drain fast stage → reconcile; stage text is resumable and indeterminate where total work is unknown.
4. Draft review: inspect/edit/reorder/defer candidates; reconciled changes show source cues and warnings.
5. Freeze/confirm: safe additions may be grouped; destructive, routing, existing-item, or CRT actions remain individual.
6. Commit: per-action results remain visible; local completion may coexist with asynchronous routing/promotion.
7. Failure: retry from checkpoint, review stable unreconciled candidates, use transcript-only fallback, or delete audio as applicable.

### Weekly Review

1. Queue: bounded snapshot, due/reason context, resume position, and explicit empty/error states.
2. Item detail: full text/provenance, route status/results, and actions: keep, edit, delete, defer, route, promote to CRT.
3. Confirmation: spoken or tapped choices remain proposals until confirmed; stale targets return a refreshed diff.
4. Progress: decided/total is real; deferred counts as an explicit outcome.
5. Completion: blocked while any item is uncovered; summary shows kept, deleted/avoided, deferred, routed, promoted, and completed counts.
6. Leave/resume or voice failure: the Weekly Review remains open and restores the exact item.

## Whole-product screen inventory

### Authentication

- Sign in: default, submitting, invalid credentials, rate-limited.
- Invite signup: default, validation errors, submitting, success.
- Session restoration/expired-session redirect.

### Home / activity

- Resumable operation banner.
- Brain Dump launch and recent completed/failed operations.
- Weekly Review due/resume card.
- Recent routed results/evidence.

### Brain Dump

- Permission/consent request and denied/disabled states.
- Idle/start; recording online; recording offline/local-limit warning.
- Live partial transcript and provisional candidates.
- Uploading, fast processing, reconciling.
- Candidate list/detail/editor, low confidence, conflict, merge/split lineage.
- Frozen confirmation batch and committing results.
- Completed, retryable error, terminal error, cancelled, partial commit, bounded undo.

### Weekly Review

- Start/resume; queue; item detail.
- Keep/edit/delete/defer/route/CRT-promotion confirmation.
- Voice review active and new-thought capture.
- Progress, uncovered-item block, completion summary.
- Empty, list-load error, item stale/conflict, partial commit/retry.

### CRT / trees

- Tree list: populated, empty, loading, error.
- Focused mobile tree/subtree with search, pan/zoom, selected-node sheet.
- Node form: label, type, highlight, relation counts, validation, consent-gated AI feedback, delete.
- Relation inspector; versions/history; create/rename/import/export/delete tree.
- Full desktop canvas with inspector and keyboard shortcuts.

### Results / routing

- Pending/dispatching/succeeded/failed route.
- Evidence/result detail linked to originating capture, review, and CRT.
- Retry/cancel where allowed; explicit external follow-up where automatic undo is unavailable.

### More / settings

- Task-tracker connection/destination and health.
- Microphone and external-processing consent.
- Raw-audio/working-artifact retention and immediate audio deletion.
- Operation history, account/session, sign out, privacy deletion request.
- Loading, save success, validation failure, offline/read-only state.

## Prototype notes

The static prototype demonstrates representative states rather than simulating the backend. Use its built-in “Scenario” control or the product navigation to jump between states. Query parameters (`?screen=recording`, `?screen=confirm`, etc.) make screenshot states stable.
