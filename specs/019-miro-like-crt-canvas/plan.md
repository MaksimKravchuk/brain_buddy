# Implementation Plan: Miro-like CRT Canvas

**Branch**: `crt` | **Date**: 2026-09-19 | **Spec**: [spec.md](spec.md)
**Design authority**: [design.md](design.md), screens/states D-01 through D-06
**Risk**: **High / ASK** for delivery classification. The feature is a significant new capability with destructive tree actions and must change the explicit ASK privacy-enforcement API path `backend/app/api/routes.py` (and likely its dependency wiring). Rollout remains server-owned and initially internal, but the flag does not lower the path-risk class under ADR-0008.

## Summary

Implement the first usable Thinking Mode CRT surface at `/crt` by reusing the existing owner-scoped tree/node/relation aggregate and adding a tested React canvas layer. Add the managed `crt_canvas` flag and a gated `/api/crt/trees` facade that leaves legacy `/api/trees` consumers unchanged. Extend the canonical tree and API response with top-level `revision` and `schema_version` fields for conflict-safe full-snapshot saves, and retain failed edits in an owner/origin/tree-scoped local draft. Use the maintained `@xyflow/react` successor to the historical `reactflow` dependency, isolated behind a CRT feature module. Build in vertical slices with failing backend/frontend tests before each implementation slice; do not create a second persistence model, mobile editor, AI path, task/project link, collaboration surface, or version UI.

## Technical Context

**Language/Version**: Backend Python 3.11, FastAPI, Pydantic; frontend strict TypeScript, React 19, Vite; Node version/toolchain from repository CI.

**Primary Dependencies**: Existing React Query 5, Zustand 5, Tailwind, Lucide, Vitest + Testing Library, Playwright, pytest/FastAPI TestClient. Add only `@xyflow/react` at a lockfile-pinned version after the dependency check in `research.md`; do not re-add historical `reactflow`.

**Storage**: Existing owner-scoped JSON tree files/index under `backend/data`, per-tree file lock and LRU cache; existing SQLite runtime feature-flag store; new ADR-0026 `crt_commands.sqlite3` for 30-day Thinking/CRT command receipts/reconciliation metadata (not graph ownership); browser localStorage for owner/origin-scoped unsynchronized drafts and the separate last-tree convenience preference.

**Testing**: Backend pytest + FastAPI TestClient; frontend Vitest + Testing Library; Playwright compose/e2e for keyboard creation, menu/recovery, flag-off boundary, and accessibility smoke; targeted 200-card performance test. Every product test names a feature-qualified requirement (`019-FR-*`/`019-SC-*`) and emits Allure taxonomy.

**Target Platform**: Authenticated desktop web at 1024 CSS px or wider. Native mobile is unaffected with no CRT entry; narrower web shows a truthful unavailable boundary, not a clipped editor.

**Project Type**: React/FastAPI web application in a modular monolith.

**Performance Goals**: On a representative 200-card tree, at least 95% of sampled selection, drag, Enter/Tab creation, pan, and zoom interactions show visible feedback within 200 ms; the graph must remain usable without long main-thread freezes. Initial load and conflict comparison may expose progress states rather than blocking the shell.

**Constraints**: Online-first, local recovery only on the same browser/origin/account; no cross-device merge promise. No external AI processing. Preserve session auth, owner isolation, account export/purge, existing stored trees, root task route, Brain Dump modal routing, and mobile behavior. No raw user content or credentials in logs, metrics, fixtures, or evidence.

**Scale/Scope**: One internal account at first rollout, approximately 200 cards/relations per tree, multiple owner-scoped trees, one desktop route. No collaboration or multi-user merge.

## Constitution Check — pre-design

- **Spec workflow**: PASS for this planning input. `intake.md`, `spec.md`, `checklists/requirements.md`, and the product-owner-approved `design.md` exist; `spec.md` has no unresolved clarification marker.
- **Consent & safety**: PASS with local-storage caveat. No provider/AI call or new consent is required. Canonical tree data stays in the existing owner store. Active-origin flows clear owner/origin/tree-scoped drafts only after sync, confirmed discard, sign-out, confirmed account change, or same-browser account deletion; server purge cannot erase another browser's storage. Browser-storage unavailable/full is visible and never represented as protected recovery.
- **Tests/TDD**: PASS when the vertical order below is followed. Backend contract, flag, revision/conflict, and owner-isolation tests precede service/route changes; frontend client/store/shortcut/component tests precede implementation; Playwright verifies the integrated high-risk paths.
- **Contracts**: PASS after the planned additions. `contracts/http.md` is the source for the revision/error/flag/client shape. `data-model.md` defines Card/Relation/Tree/Draft state. Existing APIs remain the baseline and compatibility rules are explicit.
- **Observability**: PASS. Existing correlation middleware/error envelope remains authoritative. Save conflicts, retries, imports, deletes, flag-disabled mutations, and local-recovery decisions expose request correlation where a request occurred and log IDs/enums/timings only.
- **Mobile/resilience/performance**: PASS. No mobile code changes. Local save/recovery, leave protection, conflict review, storage-unavailable state, and the 200-card benchmark are release criteria.
- **Delivery boundary**: PASS with escalation. Artifacts are portable planning input; implementation still needs isolated worktree, TDD, exact-SHA CI, independent evidence, the ADR-0008 ASK approval/landing path, production smoke, and rollback.
- **Design citation**: PASS. D-01 is the loaded canvas/shell, D-02 first run/tree menu, D-03 local/server conflict review, D-04 shortcuts/inspector, D-05 system feedback, and D-06 destructive confirmation. Each implementation slice below cites the states it realizes.

## Current repository trace

### Backend baseline (existing files)

| Current file | Current responsibility | Planned use |
|---|---|---|
| `backend/app/api/routes.py` | Tree, node, relation, import/export, version, validation, and AI feedback routes | Add a CRT-specific `/crt/trees` facade with the flag dependency; preserve every legacy `/trees` route unchanged. This is an explicit ASK path. |
| `backend/app/api/dependencies.py` | FastAPI `Depends()` auth/service wiring | Reuse `get_current_user`, service dependencies, and add/reuse a narrowly scoped CRT exposure dependency if needed. Do not instantiate services in handlers. Explicit ASK path if changed. |
| `backend/app/api/errors.py` and `backend/app/api/contracts.py` | Error translation/envelopes and documented error responses | Preserve 401/404/409/422/503 shape, correlation reference, and actionable error messages. |
| `backend/app/container.py` | Wires repositories/services | Reuse existing tree and feature-flag services; no duplicate CRT repository. |
| `backend/app/schemas/api.py` | `Node*`, `Relation*`, `Tree*` request/response contracts | Add top-level revision/schema-version compatibility and neutral-card wire handling without breaking old stored payloads. |
| `backend/app/schemas/domain.py` | `TreeDocument`, `NodeDocument`, `RelationDocument` storage models | Add top-level canonical tree revision/schema fields with safe defaults for legacy files. |
| `backend/app/services/tree_service.py` | Tree CRUD, import/export, cache/index, timestamp conflict guard, relation integrity on full replacement | Add revision increment/expected-revision guard and preserve layout/legacy fields. |
| `backend/app/services/node_service.py` | Node create/update/delete and cascade guard | Preserve its public legacy behavior while incrementing the owning aggregate revision on each successful mutation; the canvas itself does not call these routes. |
| `backend/app/services/relation_service.py` | Relation create/update/delete; endpoint, duplicate, cycle validation | Preserve its public legacy behavior and validation while incrementing the owning aggregate revision; reuse the same validation rules in snapshot saves. |
| `backend/app/repositories/tree.py` | File-backed tree persistence, exclusive lock, `update_if_current` | Preserve atomic per-tree writes; adapt the concurrency token without changing storage ownership. |
| `backend/app/repositories/feature_flag.py` | SQLite managed flag rows, migration, degraded fail-closed read, cohort scrub | Under ADR-0025, add `crt_canvas` to the managed row set and post-marker OFF initialization invariants. |
| `backend/app/core/config.py` | Feature flag allow-list and configuration/migration seed | Under ADR-0025, add `crt_canvas` to `KNOWN_FEATURE_FLAGS`; retired inputs never seed it. |
| `backend/app/services/feature_flag_service.py` | Effective member flag resolution and generic admin view/mutations | Add one service-layer CRT resolution that preserves store health plus effective membership from one repository read; the FastAPI dependency maps degraded to `503` and normal OFF/not-selected to `404` without reaching into the repository. |
| `backend/app/api/auth.py` / `backend/app/schemas/auth.py` | `/auth/me`, login, signup and effective flag payload | Existing behavior automatically includes the new effective boolean once the allow-list/service knows it; add regression coverage. |
| `backend/tests/test_api_trees.py`, `backend/tests/api/test_tree_import_export.py`, `backend/tests/test_tree_service.py` | Current tree CRUD, relation integrity, import/export, owner/auth and service tests | Extend with revision conflicts, neutral legacy compatibility, invalid import atomicity, and 019-qualified test names. |
| `backend/tests/test_feature_flags.py`, `test_feature_flag_repository.py`, `test_feature_flag_service.py`, `test_admin_feature_flags_api.py` | Existing flag model/store/service/admin coverage | Extend for `crt_canvas` default-off, selected-user/on resolution, migration, degraded fail-closed, and admin read-back. |

### Frontend baseline (existing files)

| Current file | Current responsibility | Planned use |
|---|---|---|
| `frontend/src/app/AppRoutes.tsx` | Protected route table; `/crt/*` currently renders `ComingLater` | Replace only the CRT placeholder with a flag-aware `CrtRoute`; keep protected route and safe unavailable boundary. |
| `frontend/src/components/shell/AppShell.tsx` | BrainBuddy top bar, sidebar, mobile drawer, account menu, shell toast | Add a flag-effective Thinking Mode navigation affordance and keep the shell layout/accessibility behavior. CRT may use a dedicated canvas shell rather than forcing task list props into the canvas. |
| `frontend/src/api/auth.ts` | `AuthUser`, `hasFeatureFlag`, auth calls | Reuse fail-closed `hasFeatureFlag(user, "crt_canvas")`. |
| `frontend/src/stores/authStore.ts` | Auth scope, refresh, login/logout/clear session | Notify CRT draft scope cleanup on logout/account change; preserve generation guards and 15-second flag refresh. |
| `frontend/src/api/client.ts` | Shared same-origin JSON transport, `ApiError`, correlation ID extraction | Add typed tree operations; do not add ad hoc fetch calls. |
| `frontend/src/api/taskHooks.ts` and `frontend/src/queryClient.ts` | Existing React Query patterns/cache | Follow the existing query/mutation conventions; CRT query keys include account/origin scope. |
| `frontend/src/styles/tokens.css`, Tailwind config, existing UI primitives | BrainBuddy visual tokens and accessible control styles | Use shell tokens: slate neutrals, sky/indigo selection, emerald saved, amber warning/offline, rose error/destructive. Semantic CRT red/yellow/white treatments also have text/icon/border labels. |
| `frontend/src/api/__tests__/client.test.ts`, `auth.test.ts`, `frontend/src/app/AppRoutes.test.tsx`, `frontend/src/components/shell/__tests__/AppShell.test.tsx` | Transport, auth flag, route and shell regression tests | Extend before changing route/nav/flag behavior. |
| `frontend/tests/e2e/` and `frontend/tests/allure.fixtures.ts` | Playwright product tests and taxonomy defaults | Add gated CRT end-to-end coverage after unit/integration slices. |

### Historical evidence (not current source)

Commit `bf120b8` introduced `frontend/src/components/canvas/TreeCanvas.tsx`, `BrainNode.tsx`, `treeStore.ts`, and `reactflow ^11.10.0`. Commit `b186aaa` removed them and the dependency. The old code may inform migration pitfalls but is not an implementation dependency and must not be copied without new tests.

## Dependency strategy

1. Add `@xyflow/react` to `frontend/package.json` only during implementation, using the repository's package manager and lockfile; pin the resolved version in `frontend/package-lock.json`.
2. Keep graph-library types inside new CRT adapters/components. Store canonical domain `Card`/`Relation` values in a feature store; map to library nodes/edges at the render boundary.
3. Use library pan/zoom, fit-view, handles, selection, viewport change, and edge rendering; retain BrainBuddy-owned keyboard commands, local draft, history, semantics, and error announcements.
4. Do not add a second state-management or graph-persistence package. Zustand remains the feature store; React Query remains server cache.
5. Validate a 200-card/relations fixture and build/typecheck before proceeding. If the package is incompatible with current Vite/React/TypeScript, stop, record the failed check, and amend the dependency decision rather than inventing a replacement.

## Proposed feature structure

These are planned files; they do not exist in the current checkout and are not created by this planning task.

```text
backend/
├── app/api/routes.py                         # existing tree routes: gate + contract evolution
├── app/api/dependencies.py                   # existing auth/service dependency boundary, if needed
├── app/api/middleware.py                     # canonical UUID correlation validation
├── app/core/config.py                        # existing flag allow-list
├── app/main.py                               # existing maintenance sweep gains receipt expiry/reconcile
├── app/repositories/feature_flag.py          # existing managed flag rows/migration
├── app/repositories/crt_command.py            # new Thinking/CRT receipt + reconciliation metadata store
├── app/schemas/api.py                        # existing tree/card/relation API shapes
├── app/schemas/domain.py                     # existing canonical tree/card/relation shapes
├── app/services/crt_command_service.py        # idempotent command/reconciliation boundary
├── app/services/tree_service.py              # existing revision/conflict logic
├── app/services/node_service.py              # existing card mutation invariants
├── app/services/relation_service.py          # existing relation invariants
├── app/services/account_service.py           # receipt purge integration
├── app/container.py                          # wire the Thinking/CRT receipt owner
└── tests/                                     # existing tests extended with 019 IDs

frontend/src/
├── api/client.ts                             # existing transport + tree methods
├── api/crtTypes.ts                            # new typed tree/card/relation/error contracts
├── api/crtHooks.ts                            # new React Query tree queries/mutations
├── app/AppRoutes.tsx                          # existing /crt gate replacement
├── components/shell/AppShell.tsx              # existing Thinking Mode navigation
└── features/crt/                              # new feature boundary
    ├── CrtRoute.tsx
    ├── CrtWorkspace.tsx
    ├── CrtCanvas.tsx
    ├── CrtCard.tsx
    ├── CrtInspector.tsx
    ├── CrtTitleMenu.tsx
    ├── CrtToolbar.tsx
    ├── CrtDialogs.tsx
    ├── crtStore.ts
    ├── crtCommands.ts
    ├── crtHistory.ts
    ├── crtDraft.ts
    ├── crtLayout.ts
    └── __tests__/
```

The implementation may consolidate small components, but it must preserve the ownership boundary: server contracts in `api/`, graph/edit/recovery behavior in `features/crt/`, and existing tree persistence in backend tree services.

## Vertical TDD implementation path

The order below governs the generated `tasks.md`; each slice stays independently demonstrable and follows RED → GREEN → REFACTOR.

### Slice 0 — ADR-0026 compatibility writer

**Red tests first**:

- Storage/service tests load real legacy trees with no revision/schema fields, write through every retained aggregate mutation path, and prove revision starts at 1, advances exactly once, preserves schema fields, and clears stale command markers. Public API, tree-export and account-ZIP tests prove `last_command_id` is structurally excluded rather than relying on caller omission. Downgrade/roll-forward fixtures mutate through the Stage A-compatible writer and prove monotonic stale-save detection survives. Feature-flag downgrade tests initialize the five-row Stage B store and prove the exact Stage A reader remains healthy with `crt_canvas=OFF`.
- Regression tests prove legacy API/import/export clients remain readable and `crt_canvas` remains OFF with no Stage B mutation route exposed.

**Implementation**: Implement ADR-0025 plus ADR-0026 Stage A: add the fifth managed row as OFF and make the reader five-row aware; add/preserve top-level `revision`, `schema_version`, and the internal optional command marker; increment revision on all existing aggregate writers and clear the marker on legacy mutations. This slice is a separately releasable compatibility candidate; it does not expose the canvas or change legacy callers' accepted correlation-header vocabulary.

### Slice 1 — Flag and gated entry (D-01/D-02/D-05)

**Red tests first**:

- Backend: `019-FR-001` service/dependency tests prove selected internal account resolution, generic admin read-back, `/auth/me` key, normal ineffective `404 crt_canvas_disabled`, degraded-store `503 feature_flag_unavailable`, and wrong-owner behavior. The service returns health plus effective membership from one read (or raises a dedicated unavailable error); route dependencies never inspect the repository directly. CRT-facade tests prove absent correlation input uses the generated canonical UUID, a valid caller UUID is retained, malformed caller correlation/request IDs return `400` before CRT handler mutation, and legacy non-CRT routes retain their current compatibility behavior.
- Frontend: `019-FR-001/002` tests prove missing/false flag hides navigation and renders no canvas, while direct `/crt` and an already-open canvas use the content-free exposure probe to render `D-05-FD` for normal disabled versus `D-05-FU` for degraded storage; no tree request or mutation occurs until effective.
- Privacy/admin regression tests update the disclosed/runtime managed-flag count from four to five and name the CRT exposure-only purpose without implying authorization.

**Implementation**: Use Stage A's already-present OFF `crt_canvas` row. Add the health-preserving service resolver and gated `/api/crt/trees` facade while preserving legacy `/api/trees`; replace the current `/crt/*` placeholder with a route boundary and add gated Thinking Mode navigation. Preserve ordinary task/Brain Dump routes. Verify OFF/not-selected/degraded paths before enabling anything.

### Slice 2 — Read-only tree load and truthful first-run state (D-01/D-02/D-05)

**Red tests first**:

- Backend TestClient: list/load wrong-owner 404, empty list, legacy tree shape and correlation headers.
- Frontend API/hooks: typed list/load calls, owner/origin query key scope, loading/error/partial/empty states.
- Testing Library: owner/origin-scoped last-tree selection order (valid unexpired preference → most recently updated owner tree → empty), with expired/deleted/wrong-owner IDs cleared, initial fit-all, no fabricated demo content, retry and focus restoration. The empty-state/menu composition renders truthfully, but mutating actions are not wired in this slice.

**Implementation**: Add typed client methods/hooks and the CRT route/workspace read path using only GETs on the gated `/api/crt/trees` facade. Add only the render adapter for `@xyflow/react`; no card or tree mutation yet. Realize D-01 read state, D-02 truthful first-run/menu disabled states, and D-05 loading/error/partial states.

### Slice 3 — ADR-0026 command receipts, idempotency and full-snapshot save

**Red tests first**:

- Backend service/API: expected-revision success, stale `409`, no mutation on stale request/delete, whitespace-only snapshot label rejection with no mutation, stable client UUID validation, preservation of existing cards' legacy type/highlight values, matching/missing/conflicting schema-version rules, required owner/route-scoped mutation idempotency replay/conflict/tombstone behavior, legacy timestamp compatibility on legacy routes only, owner isolation, validated legacy export→fresh-ID import round trip and import atomicity. Crash-point tests stop after pending receipt, tree write/delete, index publication and receipt commit for create/import, update/rename and delete, then prove deterministic startup/request reconciliation and exact response replay. Concurrent create/import/replay tests prove preallocated resources, receipt state, tree writes and index publication share the command/resource guard and cannot race through the old unlocked paths.
- Frontend client/store: correlation and idempotency headers, pre-request durable attempt state when storage is available, explicit in-memory-only/no-reload-recovery behavior when storage is unavailable/full, 15-second read/30-second mutation timeouts, immutable save generation, edits queued during in-flight save, same-key replay after committed-response loss, stable-ID rebase, canonical response application without overwriting newer edits, saved/saving/unsaved/error status, support reference on HTTP/network/timeout failures.

**Implementation**: Add ADR-0026's Thinking/CRT-owned `crt_commands.sqlite3` repository/service, container wiring, persisted tree command marker, per-resource command guard that now covers create/import as well as mutation/delete, deterministic pending reconciliation, content-free delete tombstones, 30-day committed-receipt sweep, tree/account purge integration, and whole-data-directory backup/restore verification. Do not claim a cross-store transaction: pending receipt → locked tree write/delete → locked index repair → committed receipt is the explicit protocol. Implement the ADR-0001 `Idempotency-Key` replay contract for every CRT mutation and one debounced full-tree save path for canvas edits. New local entities use stable validated UUID-v4 IDs. Persist an immutable in-flight snapshot/key before sending when storage works; otherwise retain it in memory and expose the honest no-reload-recovery state. After replay/success, install its canonical response and reapply commands from newer generations before touching selection/history/draft. Do not show “saved” until no queued generation remains and the final canonical response is applied.

### Slice 4 — Tree menu, local draft/recovery and conflict review (D-02/D-03/D-06)

**Red tests first**:

- Backend/API tests: reads (list/get/export) use no idempotency or revision precondition; create/import use idempotency; rename/full-snapshot uses idempotency plus expected revision; confirmed delete uses idempotency plus query `expected_revision`; stale delete is non-mutating.
- Pure draft tests: pre-canonical create-key and canonical owner/origin/tree keying; Web-Lock single-writer ownership, generation checks, second-tab read-only behavior, BroadcastChannel/storage notifications and crash release; copy/verify rekey crash points (source only, both keys, quota failure, verified canonical cleanup) with `migration_id` deduplication; serialization, schema mismatch, storage unavailable/full, successful-sync cleanup, next-owner isolation, 30-day inactivity boundaries, startup/focus/interval sweep, expired preference removal, stale-draft backup/recover/discard and recovery-clock reset. Active-origin sign-out/account-switch/account-deletion tests seed multiple tree drafts/preferences plus a pre-canonical draft, require every pending decision, remove every departing-owner key only after resolution, preserve other owners/origins, and fail closed on enumeration/removal failure. Server tests prove 30-day receipt expiry/post-expiry reconciliation, canonical trees and receipts are purge-covered, and browser-local records/receipts are deliberately absent from export.
- Component tests: complete title-menu actions; empty-tree CTA creates only the tree; export with pending/conflicting edits is explicitly labelled saved-server-copy, warns that visible unsynced edits are excluded, offers local backup, and mutates neither graph nor draft; parameterized rejected imports for malformed JSON, unsupported/conflicting schema, missing endpoint, duplicate relation and cycle each show an actionable inline/live-region reason plus server correlation when applicable and leave the visible graph and pending draft byte-equivalent; failed save retention; reload/stale-draft recovery; leave/import/tree-switch/delete/sign-out/account-switch barriers; account transition retains all departing-owner records until each is saved/retried or explicitly discarded, then clears all active-origin CRT draft/preference keys for that owner and proves the next owner cannot see/apply them; optional backup; D-03 review focus and D-06 named-loss confirmation. Privacy-page tests require disclosure of browser-local CRT content/identifiers, 30-day inactivity, export/purge limits, and content-free CRT observability disposition before updating `PrivacyPolicyPage.tsx`.
- Playwright: create/rename/switch/import/export/cancel-delete, then confirm-delete after passing the pending-work barrier and prove server removal, preference invalidation and remaining-tree/empty fallback; one representative cyclic rejected import preserves the visible graph/draft and announces correction guidance; forced save failure → reload → recover → retry → server read-back; stale server copy preserves both and requires explicit choice.

**Implementation**: Wire the D-02 title menu after Slice 3's mutation foundation. Add `crtDraft.ts`, pre-canonical create recovery, recovery state machine, `beforeunload` protection, explicit navigation barriers, local backup download, and D-03/D-06 dialogs. Integrate cleanup with auth scope transitions. Never auto-merge or silently overwrite.

### Slice 5 — Card editing, manual Connector, and semantics (D-01/D-04)

**Red tests first**:

- Store/command tests: add/edit/move/delete, cascade confirmation, manual relation creation/deletion, invalid self/duplicate/cycle, semantic projection red effect/yellow cause/white intermediate, neutral labels.
- Component tests: inline label validation/focus, long-label wrapping/full-text access/no off-screen controls, inspector incoming/outgoing lists, visible directed arrows, relation selection/delete and error live region.
- Backend contract tests: existing relation invariants remain green for manual and full-snapshot paths.

**Implementation**: Add feature store/command layer and card/edge adapters around `@xyflow/react`. Keep relation source cause → target effect independent of screen position. Add the compact inspector and manual Connector. Realize design tokens and semantic color decisions with redundant text/icon/border cues.

### Slice 6 — Keyboard-first creation/navigation and history (D-04)

**Red tests first**:

- Pure command tests: Enter below-and-link; Tab with multiple outgoing effects selects the unique visually nearest effect in the upward direction; equal-distance/otherwise ambiguous or missing upward effect creates an unlinked sibling; both Enter and Tab with no selection create exactly one unlinked card within a defined viewport-center tolerance, select it and enter inline edit mode; occupied placement chooses a free grid slot while retaining intended depth; arrow-key spatial related traversal.
- Testing Library: each required key is covered explicitly — Enter, Tab, Delete, Cmd/Ctrl+Z, Shift+Cmd/Ctrl+Z, Ctrl+Y, Space+drag, plus/minus, zero, directional arrows and Escape; shortcuts are active only in composite canvas mode; inputs/menus/dialogs retain native keys; Escape exits so browser Tab resumes; undo/redo keeps graph/save state consistent. Accessibility-tree assertions prove a labelled canvas group, native card buttons with one roving tab stop and `aria-pressed`, semantic/selection names independent of color, and connection-handle sibling buttons with unique side/card names and keyboard operation.
- Playwright: strictly keyboard-only 10-card branching tree, persisted after reload. The representative internal user performs one timed candidate/deployed-SHA acceptance run from opening Thinking Mode through the persisted tenth branching card; record duration and keyboard-only result and require less than two minutes. Verify Space+pointer-drag and both redo variants in separate FR-012 cases.

**Implementation**: Add `crtCommands.ts`, `crtHistory.ts`, focus/selection management, shortcut sheet, and keyboard-accessible tool rail. Use Enter/Tab auto-links plus the manual Connector; do not remove either path.

### Slice 7 — Pan/zoom/layout/performance and full state matrix (D-01/D-05)

**Red tests first**:

- Deterministic Chromium/Playwright benchmark in the CI container loads a fixed 200-card/260-relation DAG fixture and records 20 samples each for selection, drag, Enter creation, Tab creation, pan and zoom. Each sample measures `performance.now()` from dispatched input to the first animation frame where the expected DOM/viewport state is observable. The exact-SHA artifact records all samples, per-operation p95 and aggregate pass rate; acceptance requires aggregate p95 ≤200 ms and at least 95% of all samples ≤200 ms. Fit-all has separate FR-014/FR-022 functional and no-freeze coverage but is excluded from the SC-003 latency denominator.
- Axe/Playwright: supported desktop widths have no horizontal scroll/clipping/overlap, no serious/critical accessibility violations, visible focus and names.
- State tests cover loading, empty, error, whole-payload integrity rejection (no partial canonical graph), offline-local, local-storage-unavailable, flag-disabled, flag-service-unavailable, conflict, and every D-06 confirmation/recovery state. Fake-timer assertions enforce no spinner flash before 300 ms, `aria-busy`/status onset at 300 ms, “Still working…” at 10 seconds, and transition to actionable timeout at 15-second reads/30-second mutations.
- Viewport tests retain/center the selected card across viewport changes and make a selected card or relation initially obscured by the inspector/floating controls reachable without losing selection.
- Persistence tests serialize accepted viewport state to canonical layout and drafts, prove normal route entry still fits all, and restore draft center/zoom only after the user explicitly chooses that draft.
- Responsive tests at 390×851 and just below 1024 CSS px prove the web editor is replaced by `D-05-UW` with no graph request, horizontal scroll, clipping or blocked controls; normal disabled `D-05-FD` and degraded `D-05-FU` have distinct copy/actions/support-reference behavior. Mobile regression asserts there is no CRT/Thinking Mode entry in v1.
- Dynamic rollout test begins with exposure effective and a dirty draft, revokes exposure, verifies the draft remains recoverable and proves no further CRT mutation is sent until refreshed exposure returns.
- Negative-scope acceptance records CRT-route network requests and proves no `/ai-feedback` or external AI/provider call occurs; accessible-name/route assertions prove Task/Project links, Brain Dump promotion, sharing, comments, AND/OR, evidence/actions and version controls are absent. Keep the separate native-mobile no-entry assertion.

**Implementation**: Tune graph rendering/memoization/viewport updates, ensure controls remain reachable behind panels, and complete D-05/D-01 state treatment. No mobile editor is added.

### Slice 8 — Rollout and release evidence

Run backend/frontend/unit/e2e/coverage/taxonomy/build checks, then the repository validators. Delivery is two-stage under ADR-0026: first land/deploy/smoke the Stage A compatibility writer with `crt_canvas` OFF and record its exact SHA as the minimum rollback image; only then land/deploy Stage B. Keep `crt_canvas` OFF until Stage B's exact-SHA ASK evidence is approved. Roll out to the selected internal account, verify the primary keyboard journey and highest-risk save/conflict recovery, then expand only by explicit owner decision. Record both SHAs, flag read-back, pending-receipt read-back, rollback behavior, production smoke, 200-card evidence, one successful `crt.canvas_open` signal and the absence/presence as expected of `crt.save` guardrail outcomes.

## Test matrix and quality gates

| Area | Required evidence |
|---|---|
| Backend contracts | Tree CRUD/list/load, owner 404, import/export, relation integrity, revision conflict, correlation ID, flag-off mutation/read behavior. |
| Frontend data layer | Typed wire parity, credentials, JSON/correlation headers, bounded timeouts, create-request reconciliation, `ApiError` correlation, cache scope by account/origin, query invalidation after canonical save. |
| Canvas behavior | Card/edge render, drag, manual Connector, Enter/Tab, arrows, pan/zoom/fit, delete confirmation, undo/redo, inspector. |
| Recovery | Save failure/timeout, local retention, reload, storage unavailable, leave protection, stale canonical conflict, local backup, explicit discard, account switch. |
| Backup/restore | Quiesced whole-`BRAIN_BUDDY_DATA_DIR` backup includes tree JSON/index and `crt_commands.sqlite3`; restore into a disposable data dir/app proves coherent committed receipts and deterministic pending reconciliation before read-back. Production uses the documented Fly volume snapshot or whole-mount copy, never cherry-picked tree files. |
| Accessibility | Keyboard-only route, composite focus mode and Escape exit, dialog focus/return, live regions, accessible icon names, no color-only meaning, axe scan. |
| Performance | Fixed 200-card/260-relation fixture in CI Chromium; 20 samples for selection, drag, Enter/Tab, pan and zoom, observable-state timing, aggregate p95 ≤200 ms and ≥95% samples within 200 ms; fit-all functional/no-freeze evidence is separate; exact-SHA artifact retained. |
| Observability | Backend log-capture tests cover open/save success, stale conflict and retryable failure; assert correlation plus allowlisted fields and reject graph text, labels, bodies, hashes, keys, credentials and local paths. Product signal: successful selected-user `crt.canvas_open`; guardrail: `crt.save` conflict/failure outcome. |
| Regression | Existing backend `make test-backend`, frontend `make test-frontend`, Playwright/e2e, mobile suite unchanged, build/type/lint, Allure taxonomy and coverage floors. |

Tests must be named with `019-FR-*`/`019-SC-*` so `scripts/check_requirement_coverage.py` can trace them after implementation. No product code or tests are created by this planning change.

## Rollout, rollback, and observability

- **Stage A**: deploy the ADR-0026 compatibility writer with `crt_canvas=off`; mutate/read back a disposable tree through a legacy path and prove monotonic revision/schema preservation. Record this exact SHA as the oldest permitted rollback target.
- **Stage B initial state**: deploy command receipts/facade/UI with `crt_canvas=off`; reconcile all pending receipts and verify the receipt store healthy before cohort exposure.
- **Internal stage**: `selected_users` containing only the approved internal account; verify `/auth/me` read-back and `/crt` exposure.
- **Broader stage**: only after keyboard speed, save/recovery, accessibility, and performance evidence; then `on` is a separate owner decision.
- **Rollback**: set flag OFF first. The client hides new exposure; a currently open canvas keeps unsynchronized local work but sends no further CRT mutations while ineffective. Reconcile/resolve every pending CRT receipt before image rollback. After any Stage B write, roll back only to the recorded Stage A compatibility SHA; never run a pre-Stage-A writer against migrated data. If Stage A cannot run, use forward fix or restore a pre-migration backup rather than erase revision/schema state.
- **Signals**: count gated opens, load success/error, save success/conflict/failure, retry, local recovery, conflict choice, import rejection, relation rejection, deletion confirmation, receipt pending/reconciled/expired and recovery failure by opaque IDs/enums/timings. No card labels or graph text. Platform-retained CRT log records are export-excluded and cannot be erased by application purge; after purge their opaque identifiers no longer resolve.
- **Failure response**: correlation ID appears in the user-facing error reference; operator uses the exact tree/operation ID and revision to diagnose. Flag-store degradation fails closed and is visible as a status/error, never as successful exposure.
- **Visual evidence**: on the exact deployed Stage B SHA and supported desktop viewport, retain bounded screenshots/recording of D-01 loaded canvas, D-02 first-run/menu, D-03 conflict review, D-05 boundary states and D-06 confirmation/recovery family. Use only synthetic account/tree/card data, repository-relative artifact references, and scrubbed metadata; never retain real names, emails, local filesystem paths or production graph text. Record comparison results against the approved D-series artifacts/state contracts; do not claim visual acceptance from axe/layout checks alone.

## Constitution Check — post-design

- **Data consent/safety**: PASS; no external processing, owner/origin-scoped local drafts, explicit destructive decisions, existing account export/purge preserved.
- **Tested delivery**: PASS if the vertical slices remain red-before-green and all affected backend/frontend/e2e/taxonomy gates run.
- **Contract-first**: PASS; `contracts/http.md` and `data-model.md` define the revision, flag, import, error, and interaction contracts before implementation.
- **Observability**: PASS; correlation IDs and redacted structured events are retained for failures/retries/conflicts.
- **Responsive/resilient**: PASS for supported desktop; mobile is explicitly unaffected and narrow web has a truthful boundary.
- **Design binding**: PASS; D-01 through D-06 are named in the implementation path and test matrix.
- **Delivery risk**: HIGH/ASK remains. This is not waived by the internal flag. It requires recorded human approval, exact-SHA required CI, production smoke/read-back, and the repository's verified rollback evidence before exposure.

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Add one graph rendering dependency | Pan/zoom, handles, directed edges, fit view, selection and 200-card interaction are core first-release behavior. | Custom SVG/canvas would recreate complex interaction/accessibility/performance primitives and was not present in the current manifest. |
| Add a local draft/conflict state machine | The accepted feature explicitly promises recoverable unsynchronized edits and no silent overwrite. | Server-only autosave cannot protect edits across a failed request/reload and would violate D-03/D-06 and FR-018/019. |
| Extend the existing tree contract with revision | ADR-0001 requires revision-based contracts and the current timestamp-only guard cannot describe stale conflicts reliably to the UI. | Reusing timestamps alone leaves ambiguous equal/clock-skew behavior and does not satisfy explicit conflict review. ADR-0026's Stage A prevents rollback writers from erasing the token. |
| Add a Thinking/CRT command-receipt SQLite store | ADR-0001 requires idempotent mutations and the file-backed tree/index cannot atomically replay a response after a crash. | A memory cache or uncoordinated receipt file loses exact replay; ADR-0026 uses persisted markers and deterministic reconciliation without duplicating graph ownership. |
