# Business Intake: Miro-like CRT Canvas

**Feature**: `specs/019-miro-like-crt-canvas/`
**Interviewed**: 2026-09-19
**Interviewee**: Product owner (internal dogfood user)

## The ask, as given

> Я хочу простой miro like канвас с карточками и стрелочками. Мы можем взять навигацию и меню из миро. мне еще нравиься как у них стрелки выглядят. Хоткеи надо тоже. enter для создания карточки ниже tab для создания соседней карточки (наследуя родителя, если есть) Сразу подключаем его к UI в BB

## 1. Problem

- **Whose problem**: The current internal dogfood user when investigating causes and effects.
- **How it shows up today**: BrainBuddy exposes a disabled Thinking Mode and `/crt/*` only renders a “Coming later” placeholder even though a tree backend survives from the pre-pivot product.
- **What it costs**: Root-cause work has to happen outside BrainBuddy, breaks the tasks-first workspace flow, and cannot reuse BrainBuddy tree persistence.
- **If we build nothing**: Thinking Mode remains non-functional and BrainBuddy cannot support its intended “Think in CRT” step.

## 2. Customer and persona

- **Primary**: A keyboard-oriented internal knowledge worker performing personal root-cause analysis.
- **Secondary**: None in the first release.
- **Deployment shape**: Single-user dogfood inside the existing multi-account owner-scoped application.

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Build a branching causal tree entirely from the keyboard | Impossible in BrainBuddy because the canvas is unavailable | One user creates a 10-card branching tree in under 2 minutes without using the pointer for card creation or navigation | First internal release |
| Canvas interaction at realistic personal scale | No current user-facing canvas | Pan, zoom, selection, movement and keyboard creation remain perceptually responsive on approximately 200 cards | First internal release |

## 4. Scope boundary

**In scope**

- [x] A web-desktop Miro-like CRT canvas opened from the existing Thinking Mode navigation item.
- [x] A tree-title menu for create, switch, rename, delete, JSON import and JSON export.
- [x] Simple cards, curved directional arrows, drag positioning, inline card editing and manual connection editing.
- [x] Bottom-up CRT semantics: cause below, effect above, persisted as `cause → effect`.
- [x] Keyboard-first creation and navigation: Enter, Tab, Delete, undo/redo, pan, zoom, fit-all and related-card traversal.
- [x] Selection and a compact inspector for the selected card.
- [x] Autosave with explicit state, retryable failures, local preservation of unsynchronized changes and leave protection.
- [x] Server-owned staged exposure, initially limited to the approved internal account.

**Out of scope — explicitly confirmed by the human**

- [x] Native mobile canvas editing; the first release is web desktop only.
- [x] Task or Project links and “Think” actions from those records; entry is global Thinking Mode only.
- [x] Brain Dump promotion into a CRT.
- [x] Collaboration, sharing, presence and multi-user concurrent editing.
- [x] Comments, AND/OR gates, evidence records, corrective actions and richer RCA workflow entities.
- [x] AI validation or any external AI processing from this canvas.
- [x] Version/snapshot UI; existing backend version capability is not surfaced in this first release.

**Confirmed by**: Product owner on 2026-09-19

## 5. Constraints

- **Deadline**: None stated; correctness and a usable keyboard path define readiness.
- **Platform**: Authenticated BrainBuddy web desktop. Native mobile is unaffected.
- **Offline behavior**: Online-first. Unsynchronized edits remain locally recoverable, save state is visible, retry is available, and leaving with pending work triggers a warning. No cross-device merge is promised.
- **Must not break**: Tasks-first root route, Brain Dump modal routing, owner isolation, cause-to-effect relation semantics, existing stored trees, account export/purge, and current mobile behavior.
- **Budget / provider cost limits**: No paid provider or AI call is in scope.

## 6. Compliance obligation

`AccountService` already provides self-serve GDPR account management — profile/email/password, ZIP data export, 14-day-grace deletion and purge — and is never feature-flagged.

- **New durable records**: No new product record category is required; the feature exposes owner-scoped tree, node and relation records already present. The browser additionally retains only the current owner/origin’s unsynchronized draft state.
- **Consent**: No external processing occurs, so no new provider consent is required.
- **Retention**: Canonical tree data follows account lifetime. Local unsynchronized state is removed after successful synchronization, explicit discard, account switch/sign-out, or account deletion.
- **Export**: Tree JSON remains directly exportable and tree data remains included in account ZIP export.
- **Purge**: Existing account purge must continue to remove tree, validation and version data; local client state must be cleared on sign-out/account-scope change.
- **Residency / other obligations**: No new external subprocessor or residency boundary.

## 7. Existing-system dependencies

- **Backend surfaces**: Existing tree/node/relation services, repositories, owner-scoped routes and feature-flag service; API contracts may need neutral card terminology and reliable save semantics.
- **Frontend surfaces**: `AppRoutes`, `AppShell` Thinking Mode navigation, typed API client/hooks, canvas/store/components and local draft handling.
- **Mobile**: Unaffected.
- **AI providers**: Not used.
- **Primary loop impact**: Makes the existing “Think in CRT” destination usable as a global Thinking Mode. Routing from captures, Tasks or Projects into CRT candidates remains deferred.

## 8. Definition of done

- [x] With the CRT flag effective, the approved internal user opens Thinking Mode from the existing BrainBuddy navigation and reaches the last opened tree or a truthful first-run empty state.
- [x] The approved internal user creates a 10-card branching bottom-up CRT in under 2 minutes using Enter/Tab and keyboard navigation, with arrows oriented cause → effect.
- [x] The approved internal user can also create, move, edit, connect and delete cards/relations with pointer controls patterned after Miro.
- [x] Tree create/switch/rename/delete/import/export works from the title menu without leaving the canvas.
- [x] Undo/redo, pan, zoom, fit-all, autosave status, retry and local unsynchronized-draft recovery work without losing edits.
- [x] A representative approximately 200-card tree remains perceptually responsive and readable.
- [x] With the feature flag ineffective, the existing product remains usable and CRT routes fail closed without exposing another owner’s data.

## Deferred to /speckit-clarify

- [x] None. The product owner resolved direction, entry point, first-open behavior, hotkeys, scope, non-goals, resilience and rollout during the interview.

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| Historical `requirements/` describe reversed relation direction in some examples | Current ADRs/code and the requested bottom-up interaction use cause → effect | Canonical direction is `source = cause`, `target = effect`; visual causes sit below effects | Product owner + accepted ADR-0001 |
| Pre-pivot design suggests entry from a task/project | First release should be available immediately from BrainBuddy UI | Enable global Thinking Mode at `/crt`; task/project linking is a later slice | Product owner |
