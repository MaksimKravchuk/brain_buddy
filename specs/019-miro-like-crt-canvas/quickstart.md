# Quickstart Validation: Miro-like CRT Canvas

This is a validation guide for the implemented feature. It intentionally does not contain implementation code. Follow [contracts/http.md](contracts/http.md) and [data-model.md](data-model.md) for payload/state details.

## Prerequisites

- Repository checkout at the current worktree root; committed evidence must use repository-relative paths only.
- Backend/frontend dependencies installed using the repository's documented toolchain.
- `cp .env.example .env` for a local compose run when needed; do not commit `.env` or real data.
- An authenticated test account and a disposable test data directory.
- A server-owned `crt_canvas` flag row available in the local feature-flag store. Start OFF; use the existing admin/runtime flag mechanism to assign the internal test account to `selected_users` only for enabled-path checks.
- Desktop browser viewport at least 1024 CSS px wide.

## Fast deterministic checks

From the repository root:

```bash
python3 scripts/check_spec_kit_specs.py
python3 scripts/check_requirement_coverage.py specs/019-miro-like-crt-canvas
make test-backend
make test-frontend
make test-e2e
```

During implementation, run the smallest red/green loop first:

```bash
cd backend && pytest tests/test_feature_flags.py tests/test_feature_flag_repository.py tests/test_feature_flag_service.py tests/test_api_trees.py tests/api/test_tree_import_export.py
cd ../frontend && npm test -- --run src/api/__tests__/crtClient.test.ts src/features/crt/__tests__
npm run typecheck
npm run build
```

The exact new test filenames may be split differently, but every product test must include a `019-FR-*` or `019-SC-*` identifier and Allure taxonomy.

## Scenario 1 — Flag-off fail-closed boundary

1. Set `crt_canvas` to `off`.
2. Authenticate and open the existing workspace.
3. Verify Thinking Mode is unavailable or visibly disabled; no canvas request or tree mutation is made by navigation.
4. Navigate directly to `/crt`.
5. Verify the safe unavailable boundary renders, no other owner/tree content appears, and task and Brain Dump routes still work.
6. Read `/api/auth/me` and verify `feature_flags.crt_canvas` is `false`.

Expected: `019-FR-001`, `019-FR-002`, `019-SC-006` pass; no CRT server mutation is issued.

Before any Stage B canvas write, validate ADR-0026 Stage A separately: deploy its exact SHA with `crt_canvas=off`, mutate a disposable legacy tree through retained tree/node/relation/restore/validation paths, and read back monotonically increasing `revision` plus preserved `schema_version`. Record that SHA as the oldest permitted rollback image. Also verify absent/valid/malformed correlation-header behavior at the shared middleware boundary.

## Scenario 2 — First run and tree menu

1. Assign only the test account to `crt_canvas=selected_users` and reload the session so `/auth/me` refreshes.
2. Open Thinking Mode from navigation and verify `/crt` loads the D-02 truthful empty state.
3. Verify no demo cards or fabricated tree exist.
4. Create a tree from the title menu/empty-state action, rename it, reload, and verify the same owner-scoped tree opens with all cards initially fitted into the unobscured viewport.
5. Create a second tree, switch between them, export one in the current legacy-compatible format, import it, and verify import receives a fresh tree ID plus freshly remapped card/relation IDs while preserving labels, topology and cause→effect direction.
6. Request deletion and cancel the confirmation; verify the tree and any pending work remain. Then pass the pending-work barrier, confirm deletion, verify owner-scoped server removal and preference invalidation, and verify the most recently updated remaining tree opens or the truthful empty state appears.
7. Try malformed JSON, unsupported/conflicting schema, missing-endpoint, duplicate-relation and cyclic imports. Verify each shows an actionable inline/announced reason (and server correlation reference when applicable) while the visible graph and pending draft remain unchanged.
8. With unsynchronized/conflicting visible edits, choose export. Verify the action is labelled “Export saved server copy,” warns that unsynced edits are excluded, offers “Download local backup,” downloads only canonical content, and leaves the graph/draft unchanged.

Expected: `019-FR-003`, `019-FR-004`, and `019-FR-020` pass; D-02 focus returns to the initiating title/menu control.

## Scenario 3 — Keyboard-only causal tree

1. Focus the composite canvas shortcut region and confirm the shortcut sheet exposes Enter, Tab, Delete, undo/redo, Space+drag, plus/minus, zero, arrows, and Escape.
2. With one selected effect, press Enter; name the new card. Verify it appears below, is selected/editing, and the relation is `new cause -> selected effect`.
3. Press Tab on a card with one unique nearest effect; name the sibling. Verify the original relation remains and the sibling inherits the same effect.
4. Press Tab where no unique effect exists. Verify an unlinked same-level card is created and no guessed relation appears.
5. On the exact candidate/deployed SHA, have the representative internal user start a timer outside `/crt`, open Thinking Mode, create the first effect and a branching 10-card tree using only keyboard creation/navigation, stop after the persisted tenth card, and record a duration under two minutes plus the keyboard-only result.
6. Focus a text input/menu/dialog and press the same keys; verify native input/focus behavior is not hijacked. Press Escape to leave canvas shortcut mode and verify ordinary Tab/Shift+Tab leaves the canvas.

Expected: `019-FR-007` through `019-FR-013`, `019-SC-001`, and `019-SC-002` pass.

## Scenario 4 — Pointer editing and graph integrity

1. Use the manual Connector to link two cards; verify the curved directed arrow and source/target IDs.
2. Attempt self-link, duplicate relation, and cycle. Verify no graph mutation, actionable inline/live-region error, and correlation reference when a request occurred.
3. Drag cards, pan, zoom, use fit-all, select a relation, delete the relation, and inspect a card's incoming causes/outgoing effects.
4. Delete a connected card, cancel the cascade confirmation, then confirm it and verify the card and its relations are removed.
5. Use undo and redo after card, relation, label, and layout operations; verify visible graph and save state stay consistent.

Expected: `019-FR-005`, `019-FR-006`, `019-FR-010` through `019-FR-016`, and `019-SC-005` pass. Semantic meaning is written as text and is not conveyed by red/yellow/white color alone.

## Scenario 5 — Save failure, reload recovery, and conflict

1. Make a card edit and wait for autosave; verify `saving` then `saved`, and read the tree back from the API.
2. Force a network failure or timeout during the next save. Verify the graph remains visible, status becomes unsaved/error or offline-local, Retry is available, and the correlation reference is copyable when a request was sent.
3. Simulate a server commit followed by a lost response, then make another local edit while the original save is unresolved. Reload/retry in the same authenticated account/origin and verify the same idempotency key resolves the first save, the newer edit rebases by stable IDs, and every card/relation exists exactly once with the recovered graph, draft and queued edits intact. Undo/redo history starts a new editing session after reload.
4. Seed multiple tree drafts plus one pre-canonical draft for the same owner/origin, then attempt tree switch, import, delete, sign-out, account switch, and leave. Verify the barrier requires each pending item to save/retry or receive explicit named-loss discard and offers an optional backup first. Before account transition retain every departing-owner draft; afterward remove every CRT draft/in-flight/pre-canonical key for that owner on the active origin, preserve other owners/origins, and prove the next owner cannot see or apply prior content. Inject one cleanup failure and verify the transition fails closed.
5. Make a newer canonical server change, then reconnect/retry the local draft. Verify D-03 previews both versions and requires a choice.
6. Choose the server copy. Verify D-06 names the local edits, offers a local backup, focuses the safe action first, and requires a second explicit destructive confirmation.
7. Choose defer and verify both copies remain preserved. Separately choose local after explicit review and verify the warning states that synchronization may replace canonical server state; do not claim the prior server copy is retained unless the user downloaded/exported it.
8. Sign out, sign in as a different test account, and verify the previous owner's draft is neither displayed nor applied.
9. With a pending draft in the active browser, run the account export and verify canonical trees are included by the existing server export while the browser-local draft is absent. Exercise the same-browser account-deletion flow and verify that origin/account-scoped draft keys are cleared before the next account may open CRT. Do not claim cleanup in another browser or device.
10. Disable/fill browser storage and edit online. Verify the exact save request/key and newer commands remain retryable only in memory, the UI persistently warns that reload/close/crash recovery is unavailable, and a successful online save still becomes canonical without claiming local protection.
11. Advance a draft and last-tree preference to the 30-day inactivity boundary. Verify the preference is removed by startup/focus/interval cleanup; the stale draft is not auto-applied and offers backup, recover (resetting the clock), or discard. Verify same-browser identity transitions clear both record types for the departing owner and that server export contains neither.
12. Exercise a CRT idempotency receipt before and after its 30-day committed window. Before expiry, replay returns the original response exactly; after expiry, the client refetches and enters explicit reconciliation rather than blindly repeating the mutation. Verify tree/account purge removes receipts and export excludes them.
13. Quiesce mutations/checkpoint SQLite, back up the entire `BRAIN_BUDDY_DATA_DIR` (not selected files), restore it into a disposable data directory/app, and verify tree JSON/index plus `crt_commands.sqlite3` restore together. Boot recovery must replay committed receipts exactly and deterministically reconcile a seeded pending receipt before canonical read-back.

Expected: `019-FR-017` through `019-FR-021` and `019-SC-004` pass. If browser storage is disabled/full, the UI says recovery is unavailable and does not claim local protection.

## Scenario 6 — 200-card desktop performance and accessibility

1. In the CI container's pinned Chromium, load the fixed 200-card/260-relation DAG fixture used by the Playwright benchmark.
2. Capture 20 samples each for selection, drag, Enter creation, Tab creation, pan, and zoom. Measure `performance.now()` from dispatched input to the first animation frame where the expected DOM/viewport state is observable. Persist raw samples, per-operation p95, aggregate p95, browser version and exact SHA as the test artifact. Pass only when aggregate p95 is at most 200 ms and at least 95% of all samples are at most 200 ms. Exercise fit-all separately for correctness and absence of a long main-thread freeze; exclude it from the SC-003 latency denominator.
3. Run the affected Playwright axe scan and inspect at 1024px and wider for clipping, overlap, blocked controls, and horizontal page scroll.
4. Navigate the complete surface by keyboard, including title menu, tool rail, inspector, nonmodal shortcut disclosure, conflict dialog, and every D-06 confirmation/recovery state.
5. Confirm screen-reader-visible names/status/live announcements for selection, save, retries, imports, invalid relations, conflicts, and destructive actions.
6. At 390×851 and just below 1024 CSS px, verify `D-05-UW` replaces the editor with exact unsupported-width copy, heading focus, no graph request, horizontal scroll, clipping or blocked action. Separately verify `D-05-FD` normal disabled and `D-05-FU` degraded flag service use distinct copy/actions/reference behavior; verify the native mobile app exposes no CRT/Thinking Mode entry in v1.
7. Select a card and relation behind the inspector/floating controls; verify keyboard navigation or centering makes each reachable while retaining selection.
8. Capture screenshots/recording from the exact deployed SHA for the loaded canvas, first-run/menu, conflict review, destructive recovery and designed boundary/confirmation states using only synthetic accounts/content, repository-relative references and scrubbed metadata. Confirm no real name, email, local filesystem path or production graph text appears; compare with the approved D-series artifacts and retain the bounded result.
9. Record all CRT-route requests and assert there is no `/ai-feedback` or external AI/provider request. Assert the rendered accessible surface has no Task/Project linking, Brain Dump promotion, sharing, comments, AND/OR, evidence/actions or version controls.

Expected: `019-FR-022`, `019-FR-023`, `019-SC-003`, and `019-SC-007` pass.

## Rollout read-back

Before enabling the first internal user:

- Run `make verify-all` or the CI-equivalent required checks.
- Confirm the exact candidate SHA, risk/ASK approval, and review evidence.
- Confirm Stage A was deployed and smoked before Stage B, record both exact SHAs, and confirm rollback is limited to the Stage A compatibility SHA after any Stage B write.
- Read `/api/auth/me` for the intended account and confirm `crt_canvas=true`; confirm another account remains `false`.
- Run the timed authenticated keyboard journey from opening Thinking Mode through the persisted tenth branching card, record the sub-two-minute result, and run the save-failure/conflict recovery journey.
- Verify production smoke and feature-flag read-back on the exact deployed SHA.
- Verify one correlated, content-free successful `crt.canvas_open` product-signal event from the selected-user journey and inspect the `crt.save` conflict/failure guardrail outcome from the recovery journey; confirm only the allowlisted fields appear.
- To roll back, set `crt_canvas=off`, verify safe boundary/no mutations, preserve local drafts, reconcile every pending CRT receipt, then use only the recorded Stage A compatibility image. Never run a pre-Stage-A writer against migrated tree data.


