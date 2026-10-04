# Research: Miro-like CRT Canvas

**Feature**: `019-miro-like-crt-canvas`
**Inputs**: `spec.md`, `design.md`, `intake.md`, accepted ADR-0001, ADR-0008, ADR-0022, ADR-0025, ADR-0026
**Research date**: 2026-09-19

## Decision 1: Reuse the existing tree aggregate and HTTP surface

**Decision**: Keep Thinking/CRT ownership in the existing tree services and repositories. Add a gated `/api/crt/trees` facade for the canvas while leaving legacy `/api/trees` unchanged. Extend the shared tree contract only where the canvas needs optimistic concurrency, neutral card semantics, and safe recovery.

**Evidence**:

- `backend/app/container.py` already wires `TreeRepository`, `IndexRepository`, `TreeService`, `NodeService`, and `RelationService`.
- `backend/app/api/routes.py` already exposes owner-scoped tree, node, relation, import, export, and delete endpoints.
- `backend/app/services/tree_service.py` already validates relation endpoints/duplicates/cycles, preserves layout metadata, maintains the index, and has an LRU cache.
- `backend/app/repositories/tree.py` serializes `mutate`/`update_if_current` with an exclusive per-tree lock, but current `create`/`save` and create/import service paths are unlocked. ADR-0026 implementation must bring create/import plus receipt and index publication inside the command/resource serialization boundary.
- ADR-0001 explicitly says the current tree services may remain in place and must not be duplicated by a new module.

**Consequence**: The first slice is a gated API facade and contract evolution, not a second CRT persistence model. The canvas uses only full-snapshot graph saves; legacy low-level node/relation routes remain available to existing consumers. Version UI, AI feedback, and task/project links stay out of this feature even though the backend has version and AI endpoints.

The persistence evolution follows ADR-0026's two-stage release: deploy a compatibility writer that preserves and advances revision/schema fields before any Stage B canvas write, then permit rollback only to that compatibility SHA. CRT idempotency receipts are a Thinking/CRT command store, not a second graph model.

## Decision 2: Add a new managed server-owned flag, `crt_canvas`

**Decision**: Under ADR-0025, add `crt_canvas` to the existing managed flag allow-list and SQLite-backed runtime flag store. It is default OFF, supports the existing `off | selected_users | on` modes, and is initially assigned only to the internal account selected by the rollout operator.

**Evidence**:

- `backend/app/core/config.py` is the allow-list source for `KNOWN_FEATURE_FLAGS` and derives `RUNTIME_MANAGED_FLAGS`.
- `backend/app/repositories/feature_flag.py` defines `MANAGED_FLAGS`, migration/seeding, fail-closed degraded behavior, and GDPR cohort scrubbing.
- `backend/app/services/feature_flag_service.py` resolves effective flags by authenticated account ID.
- `backend/app/api/auth.py` includes the effective boolean map in `/api/auth/me`; `frontend/src/api/auth.ts` already has `hasFeatureFlag()` and fails closed for missing flags.
- ADR-0025 narrowly authorizes the fifth managed row and fresh/post-marker OFF initialization. ADR-0022 requires a server-owned CRT flag; ADR-0008 requires OFF → INTERNAL → ON rollout and says flags are never authorization.

**Consequence**: No new flag service, admin route, or client-side configuration is invented. The existing generic admin flag endpoints become capable of managing `crt_canvas` after the allow-list/store changes. The route still requires normal session authentication and owner checks; the flag only controls exposure and the ability to make CRT mutations.

## Decision 3: Use `@xyflow/react`, not the historical `reactflow` package or a custom graph engine

**Decision**: Use `@xyflow/react` as the canvas interaction/rendering dependency, pinned in `frontend/package-lock.json` at implementation time. Do not re-add the historical `reactflow` package.

**Evidence from this repository**:

- Current `frontend/package.json` has no graph/canvas dependency, and the current `frontend/package-lock.json` is the lockfile that must receive the implementation-time addition.
- Git history shows the earlier canvas used `reactflow` `^11.10.0` in commit `bf120b8` (`frontend/src/components/canvas/TreeCanvas.tsx`, `BrainNode.tsx`, and the old `treeStore.ts`).
- Commit `b186aaa` removed that canvas and the `reactflow` dependency while simplifying the product shell. Those files are historical reference only; none exists in the current checkout.
- The current frontend already has React 19, Zustand 5, React Query 5, strict TypeScript, Vitest/Testing Library, Playwright, Tailwind, and Lucide. `@xyflow/react` can be isolated to the new CRT feature without replacing those foundations.

**Registry check**: `npm view @xyflow/react version dist-tags --json` returned latest `12.11.6`; `npm view reactflow version dist-tags --json` returned latest `11.11.4`. The scoped package is the maintained successor line to the package used by the removed canvas and is the justified choice for nodes, edges, pan/zoom, handles, selection, fit-view, and viewport events.

**Alternatives considered**:

- **Historical `reactflow`** — rejected. It is the removed dependency and would preserve the old package line rather than adopt the successor.
- **Custom SVG/canvas implementation** — rejected for this release. It would recreate hit testing, handles, pan/zoom, selection, keyboard focus, edge routing, and viewport performance without reducing product scope.
- **Another graph library** — rejected because no other graph package is present in the manifest or history, and adding an unverified package would violate the request not to invent dependencies.

**Constraint**: This is a planning decision, not an install. Implementation must verify the chosen version against the lockfile/CI Node toolchain and run a small 200-card benchmark before accepting the dependency. If the package cannot build under the repository's current toolchain, stop and amend this research/plan rather than silently substituting a package.

## Decision 4: Autosave uses a local draft envelope plus server optimistic concurrency

**Decision**: Keep the canonical tree on the server and retain only unsynchronized owner/origin/tree-scoped drafts in browser storage. Use an integer server revision as the primary optimistic-concurrency token and retain `updated_at` for compatibility/diagnostics. A failed save never clears or marks the draft saved.

**Current gap**: The existing `PUT /api/trees/{tree_id}` contract accepts `metadata.updated_at`, and `TreeRepository.update_if_current()` compares timestamps. The existing tree documents do not expose the integer `revision` required by ADR-0001, and legacy routes cannot be gated wholesale without affecting existing consumers.

**Chosen evolution**:

- Add top-level `revision` and `schema_version` to `TreeDocument`, `TreeDetailResponse`, imports and exports; increment revision for every successful persisted aggregate mutation.
- Add an explicit required `expected_revision` to `/api/crt/trees/{tree_id}` full-tree saves; return the existing error envelope with `409`, `detail.reason = "stale_revision"`, current server revision metadata, and `X-Correlation-ID`.
- Preserve the existing timestamp-token compatibility path only on legacy `/api/trees/{tree_id}`. The new canvas always sends the top-level revision and never calls low-level node/relation mutation routes.
- Store a draft envelope under an origin/account/tree key containing the local graph, layout/viewport, base revision, base timestamp, and schema version. Do not store another account's draft, raw credentials, or support-sensitive fingerprints.

**Recovery policy**:

- If the server revision still equals the draft base revision, offer/restore the compatible local draft.
- If the server is newer, preserve both copies and show the D-03 difference review. The user explicitly chooses local or server; there is no silent merge or overwrite.
- Choosing the server copy requires D-06 confirmation naming lost local edits and offering a local JSON backup first.
- On successful sync or explicit discard, remove the scoped draft. Same-browser sign-out/account change/account deletion enumerates and clears every departing-owner CRT draft/preference key on the active origin after pending-work decisions; server purge covers canonical trees and receipts but cannot erase another browser's storage. If storage is unavailable/full, continue online-only and say that local recovery is unavailable.
- Browser drafts and last-tree preferences expire after 30 days of inactivity; stale drafts receive one explicit backup/recover-or-discard decision on the next app run. Server CRT command receipts guarantee exact replay for 30 days, after which recovery refetches and requires explicit reconciliation.

## Decision 5: Keep the design states binding

`design.md` is authoritative for the implementation surface. The plan must realize:

- D-01 default loaded canvas and saved status;
- D-02 truthful first-run empty state and title menu;
- D-03 retained local draft/server conflict review;
- D-04 keyboard shortcuts and inspector;
- D-05 loading, error, partial, and storage-unavailable states;
- D-06 destructive conflict confirmation.

The product-owner decisions recorded in the feature context are binding: manual Connector remains available alongside Enter/Tab auto-links; semantic colors are red effects, yellow root causes, and white intermediate cards. The canvas uses neutral causal language in controls and accessible text; color never carries the meaning alone.

## Resolved implementation unknowns

| Question | Resolution | Source |
|---|---|---|
| Where does the feature enter? | Existing Thinking Mode navigation becomes a gated `/crt` route; task/project/Brain Dump entry points remain out of scope. | `spec.md` FR-002/026, `design.md` D-01/D-02 |
| Which persistence store? | Existing owner-scoped tree JSON/index remains the only canonical graph store; ADR-0026 adds separate `crt_commands.sqlite3` receipt/reconciliation metadata with whole-volume backup/restore coverage. | ADR-0001, ADR-0026, current `TreeRepository`/`TreeService` |
| How are invalid relations handled? | Reuse service validation for missing endpoints, self-links, duplicates, and cycles; surface actionable error envelope and correlation reference. | Current `RelationService`, `TreeService`, `spec.md` FR-011 |
| How does rollout work? | `crt_canvas` managed flag, OFF by default, selected internal user first, then ON only after evidence. | ADR-0025, ADR-0022, ADR-0008 |
| Does mobile change? | No. Native mobile remains unaffected with no CRT entry; narrow web shows an unavailable boundary rather than a clipped editor. | `spec.md` assumptions, `design.md` mobile viability |
| Does AI run? | No. Do not call `/api/trees/{tree_id}/ai-feedback` or add any AI affordance. | `spec.md` FR-025/026 |

## Risks still requiring implementation evidence

1. The old React Flow canvas was deleted; interaction behavior must be rebuilt behind tests rather than copied from stale code.
2. The existing `type: parent | child` wire field conflicts with the neutral-card UX. The compatibility rule in `contracts/http.md` must be implemented and tested before frontend work consumes the new shape.
3. The file-backed tree aggregate is adequate for the stated single-user/internal rollout, but the 200-card benchmark and save-conflict tests are release gates. A measured failure requires a follow-up architecture decision, not an unbounded optimization effort.
4. `backend/app/api/routes.py` and `backend/app/api/dependencies.py` are explicit ASK paths under ADR-0008's classifier because they enforce authenticated owner privacy. The feature is therefore classified high/ASK for delivery evidence even though its rollout is internal and flagged.
