# Spec 026 conductor handoff

State on **2026-10-10 ~10:50 UTC**, when the multi-agent implementation session stopped. This page tells the next agent, of any vendor, exactly where spec 026 (`specs/026-rust-core-sync`) stands and how to continue.

The authoritative plan is `specs/026-rust-core-sync/tasks.md`: the `## PR-срезы` JSON slice map, its `depends_on` edges and the owner decision notes near the top. The rendered graph is `specs/026-rust-core-sync/delivery-graph.md`, which has 64 slices and 98 edges.

## Continuation decisions — October 10

The owner instructed Codex to continue implementation from this handoff, with independent agents and model routing from `AGENTS.md`, until the accepted migration is complete. Existing merge authorization and the advisory slice budgets remain in effect.

- **Scheduler gate:** the owner delegated the open PR-64 decision. Keep the prepared `BRAIN_BUDDY_DURABLE_SCHEDULER` boot-time gate, default OFF. Changing it requires a process restart. This decision approves the mechanism, not feature activation or the Apple/SQLite pilot.
- **Workspace validation:** the owner explicitly approved asynchronous saving with the existing validation errors and preservation of entered text. Callers must await durable completion before reporting success, clearing a draft, or dismissing a form. Add asynchronous throwing runtime methods; preserve legacy synchronous entry points for legacy workspaces. An observable late-error property cannot stand in for successful durable submission.
- **Progress accounting:** the historical headline below does not agree with its enumerated slice IDs. Those IDs contain 33 completed slices before PR-24, plus the partially implemented PR-64 runner. Main `19acf48a66ef3d34855f6319c357f976d2db0295` adds PR-24 (#347), giving 34 completed slices and one partial PR-64. The scheduler handoff must merge before PR-25 can land. Partial implementation and a green review are not acceptance or release evidence.
- **Local verification:** the restored executor now has isolated CPython 3.14.7 and Rust 1.99.0 toolchains. Backend TestClient checks need the supported network-enabled execution sandbox, including for in-process test transports. Without it, the same API fixture stalls on unchanged main; it is not a PR-25 regression.

The remaining sections retain Claude's historical snapshot. Questions resolved above do not need to be asked again.

## Progress

**33 of 64 slices are merged.** Merged so far:

- **Foundation:** PR-01 to PR-06, plus PR-61
- **Rust rules:** PR-07 to PR-16, plus PR-62
- **Facades:** PR-17 to PR-19
- **Durable jobs:** PR-20, PR-21 and PR-23, plus the PR-64 runner (#324)
- **Client sync:** PR-34 to PR-39, plus PR-41 (legacy store import, #350)
- **Other:** PR-47 (AI policy), PR-53 (web compat)

### Open PRs (all opened by this session, all stacked)

| Slice | PR | Branch | Stacked on | State at handoff |
|---|---|---|---|---|
| PR-24 agent job adapters | #347 | `claude/026-agent-adapter` | main | All review threads resolved. CI running on `7d29c466` (a main merge after a taxonomy conflict). It was green on the previous head. **Merge when CI is green.** |
| PR-22 Review job adapter | #349 | `claude/026-review-job-adapter` | main | All threads resolved. CI running on `bc542895`. **Merge when green.** |
| PR-42 legacy outbox classify | #351 | `claude/026-legacy-outbox` | main (its base #350 is merged) | All threads resolved. CI running on `c0e24097`. **Merge when green**, after first merging `origin/main` into it if the secret scan complains. |
| PR-64 scheduler handoff | #352 | `claude/026-scheduler-handoff` | #347 and #349 | Both review findings are fixed in `748b1c96` and their threads resolved. CI running. Merge after #347 and #349. See the note below on the full suite. |

### In-progress slices (never pushed as PRs)

These are pushed as **draft WIP PRs** so nothing is lost. Each PR body lists the exact remaining steps.

| Slice | Draft PR | Branch | Stacked on | Done | Remaining |
|---|---|---|---|---|---|
| PR-25 SQLite unit of work | #353 | `claude/026-unit-of-work` | #352 | Most of it: see below | Lint, the full suite and the gates; see below |
| PR-43 Workspace binds runtime | #354 | `claude/026-workspace-runtime` | #351 | `visible_snapshot()` / `projection_generation()` in `bb-client/src/execute.rs` | Nearly everything; see below |

### PR-25 (#353)

**Done.**
- `backend/app/modules/tasks/sync/unit_of_work.py`: `TaskUnitOfWork.begin(owner_id, *, cleanup=False)` is built on `owner_write_lock`. It uses one `BEGIN IMMEDIATE` connection, commits once and rolls back everything on error. Mirrors are written after the commit, and nesting is refused.
- `OwnerUnitOfWork` has `schedule(JobIntent)`, which uses the same connection through the new `JobRepository.schedule_in`. It also has `load()`/`verify()` read sets, `record_write` and `after_commit`.
- The write entry points in `repository.py` and `review_repository.py` join an open unit, so the unit is opt-in.
- `Container.task_unit_of_work` is wired.
- 24 tests in `backend/tests/test_sync_unit_of_work.py`.

**Remaining.**
1. Fix 5 ruff `SIM117` findings in the test file, then run black.
2. Run `mypy app` and lint-imports.
3. Run the full suite with coverage, then the floor and Allure validators.
4. Run `check_spec_kit_specs.py` and requirement coverage for 026-FR-006, FR-014, FR-015, SC-002 and SC-007.
5. Merge the moved upstream branches.
6. Recommit as `feat(026)`.

### PR-43 (#354)

**Remaining, in order:**
1. **Bridge** (`rust/bindings/swift/src/lib.rs`): add `open_store`, `execute` (wrapping `bb_client::execute`), `snapshot`, and a `subscribe` handle with `next(after, timeout)` and `cancel()`.
2. **Swift wrappers** in `BrainBuddyRustBridge.swift`.
3. **Core:** public `RustDomainFacade` hooks to encode a `GTDCommand` and to rebuild a `GTDState` from a snapshot. Strip the `<prefix>_` only from UUID IDs.
4. **`RustWorkspaceAdapter`** actor. Its epoch gate refuses to bind unless the legacy outbox status reports `mayRun`.
5. **Workspace:** async `submit` and query entry points on a serial chain. In bound mode, the legacy engine and `store.json` stay inert.
6. **`SyncRuntimePort`** in `BrainBuddySync.swift`.
7. **`RustWorkspaceTests.swift`.**
8. **Legacy outbox conversion:** turn unsent entries into commands, keyed by their idempotency key.

**Owner decision needed:** the sync `perform` reports refusals through typed `throws(GTDValidationError)`, which cannot work once the Workspace is bound to the runtime. The proposal is to surface refusals through an observable failure property instead, which changes the validation UX.

**Size:** an estimated ~800 lines. Consider splitting into (a) the Rust port plus the Swift bridge and (b) the adapter plus the Workspace wiring.

## What to do next, in order

1. **Merge the green PRs in stack order: #347, #349 and #351, then #352.**
   - Use `merge_method: merge` and the exact 40-char head SHA from `git ls-remote`.
   - Merging pre-approval: the owner pre-approved merging every slice PR, ASK-class included.
   - Before merging a stacked PR whose base has moved, merge `origin/main` into it and push. The Gitleaks secret scan fails with "could not verify a safe commit range" unless current `main` is an ancestor of the PR head.
2. **Land #352 (PR-64).** Both review findings are fixed in `748b1c96`:
   - **Boot recovery ordering.** `AgentRecoveryAdapter.boot_sweep()` now marks interrupted exchanges synchronously in `create_app()` before the worker starts and before any request is served, so only the per-run lookups run on the worker.
   - **Worker lanes.** `WorkerLanes` in `worker.py` runs one `JobWorker` per lane:
     - `maintenance`: Review and privacy;
     - `agent`: observation and recovery;
     - `voice`: voice, only when its cadence is above 0.
   - **Full suite not yet run on the final code.** It was stopped at about 61% with no failures. The pre-fix run was green: 5596 passed, 98.41% coverage. CI runs the full suite. If it is red, fix it on this branch.
   - **Budget:** `main.py` + `worker.py` come to about 390 product lines against an advisory 350, and `agent_adapter.py` is a third product file. This is acceptable under the advisory-budget decision.
   - **Owner question still open:** is the boot-time env gate `BRAIN_BUDDY_DURABLE_SCHEDULER` (default OFF, read once at startup, documented in `.env.example`) acceptable as the plan's "recorded default-OFF/storage epoch gate"? No process-level storage epoch exists yet.
3. **Continue the in-progress slices above** (PR-25 and PR-43) from their pushed WIP branches.
4. **Then follow the slice map.** A slice is ready when every `depends_on` entry has merged.
   - Server chain: PR-25 → PR-26 … PR-33, plus PR-58 and PR-63.
   - Client lane: PR-43 → PR-44, then PR-40 (it depends on PR-41, PR-42 and PR-63).
   - **PR-55** (PostgreSQL adapter) may *start* once PR-25 merges, but must not *merge* before PR-54 (the Apple/SQLite pilot). This is the one conductor exception, recorded in tasks.md.
   - Each slice records its `paths`, `tests`, `acceptance`, `budget` and `implementer`.

## Decisions already made by the owner (do not re-ask)

- **Merging** is pre-approved, including ASK-class PRs.
- **Slice size budgets are advisory** for feature 026 (owner decision 2026-10-09 in tasks.md). Decline reviewer "split this slice" comments with that citation.
- **Parallel lanes** (owner decision 2026-10-10 in tasks.md):
  - PR-41 depends on PR-39, not PR-40.
  - PR-55 may start after PR-25 but lands only after PR-54.
- **Same-name projects and tags** resolve to the oldest record.
- **Python** is 3.14.
- **Docker Hub 429** in CI: re-run the job; do not change auth.
- **Flag-ON (Rust facade) behaviour differences** are accepted:
  - native `<prefix>_<uuid>` IDs;
  - a stricter 7-day Undo window.
- **Owners whose deletion has begun** (`deletion_requested_at` set) are not current owners for job writes (PR-21). Review *retention cleanup* still runs for them through `owner_write_lock(..., cleanup=True)` (PR-22, #349).

## Known gaps recorded on merged or open PRs

- **PR-17:** in the Rust epoch, device auto-park returns `applied: false` until the runtime supplies `last_effective_sweep_at`.
- **PR-37:** a local gesture between the ACK and the feed can be refused by local rules.
- **PR-42 (#351):**
  - Unsent legacy outbox entries are classified but **not yet converted** into Rust outbox commands, so `may_run` stays false. That conversion belongs to PR-43, reusing each entry's idempotency key as the command ID.
  - Uncertain or rejected legacy issues can only be cleared by a later receipt; there is no user dismiss yet.
- **PR-41 (#350):** while the import runs, app, widget and App Intent writers block on the legacy document lock, so run the import at a quiet moment such as launch.

## Working conventions in this repo

- Read `CLAUDE.md`, `AGENTS.md` and `ios/AGENTS.md`.
- **Tests** carry feature-qualified requirement IDs (`test_026_FR_014_...`, `import_026_sc_005_...`). `scripts/check_requirement_coverage.py` traces them.
- **Every new backend test module** needs an entry in `backend/tests/allure_taxonomy.py`. Parallel PRs conflict there often; resolve by keeping every entry.
- **Never** skip or disable tests, lower coverage floors or add coverage suppressions.
- **Never** run `/verify-live`; it spends real provider money.
- **Commits** use conventional prefixes. GitHub comments end with the Claude Code attribution footer when written by Claude.
- **No Swift toolchain in cloud sessions.** The iOS kit on Linux, iOS app and Mac app lanes in CI are the only Swift compile.
- **Cancelled runs.** A "Full CI" failure on a superseded head is usually a cancelled run. Check the run's `conclusion` before treating it as real.

## Monitoring dashboard

The current owner-private progress dashboard is https://brain-buddy-rust026-progress.alightpanda2.chatgpt.site. It reads public GitHub PRs and Actions runs every five minutes while visible, matches checks to the current PR head SHA, and exposes dependency readiness for all 64 slices. A retained baseline is clearly marked when GitHub is unavailable. Completion counts exclude the partially merged PR-64 runner until its scheduler handoff lands; slice merges do not imply pilot acceptance or a verified production release.

The historical Claude artifact is https://claude.ai/artifact/4hy8Zqd9vNN2RdZwLZk22E. Only a Claude session with its Artifact tools can update that copy.
