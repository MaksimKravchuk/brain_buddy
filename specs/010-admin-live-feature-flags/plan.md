# Implementation Plan: Live Feature-Flag Management in the Admin Portal

**Branch**: `feat/010-admin-live-feature-flags` | **Date**: 2026-08-14 | **Revised**: 2026-08-15 (founder correction: SQLite sole store, `admin_portal` deleted)
**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Tasks**: [tasks.md](tasks.md)
**Analysis**: [analysis.md](analysis.md) · **Review record**: [review-history.md](review-history.md)

**Risk class: ASK (high).** See [Landing](#landing-adr-0008-ask) — it decides how this feature reaches `main`, and it is not a footnote.

## Summary

**2026-08-15 founder correction** (see [ADR-0019](../../docs/decisions/0019-sqlite-runtime-feature-flag-store.md) and spec.md's DD-14/DD-15/DD-16): the durable store is one SQLite table, the **sole source of truth** for three **managed flags** — `voice_brain_dump`, `mobile_task_classification`, and now `external_agent_relay` — populated once by a transactional, restart-idempotent migration from the pre-correction JSON overlay and the deploy-staged environment baseline. There is no environment fallback, no "deploy default" inheritance, and no clear-override route after migration. `admin_portal` is deleted as a feature flag everywhere; the Admin Portal is always available to an authenticated operator on the allow-list. The rest of the summary below states what that leaves in place.

One service resolves effective flags exclusively from SQLite for the three managed flags (`delivery_canary` stays environment-derived, untouched), three operator mutation routes (set mode, add account, remove account — no clear-override route) plus one `GET` behind feature 009's operator-authorization gate (now `require_operator` alone, since `admin_portal` no longer gates anything), one section on the existing `/admin` screen showing all three flags, and a bounded 15-second polling refresh of the identity-and-flags endpoint on **both** clients that read a managed flag — the web auth store's `refreshSession()` and the mobile `SessionProvider`'s poll effect — each using a session-refresh path distinct from its own initial hydration/`probe()` (FR-009, Lane E, untouched by the 2026-08-15 correction).

Two review campaigns (`product-decision-required`) found the original package narrower than claimed and several artifacts contradicting each other; all of that was resolved by the original owner decisions (DD-1 through DD-13) before the founder's 2026-08-15 storage/authorization correction layered on top (DD-14 through DD-16). See [review-history.md](review-history.md) for both the original finding record and the correction's own record — the correction is a founder directive, not a third review campaign, and none is required for it (ADR-0011/ADR-0012 do not mandate one for an owner-directed architecture correction to an unimplemented package).

No new dependency, no new identity, no new transport, no new CLI command. Documentation surfaces change, each narrowly scoped: ADR-0019 (new, narrowing ADR-0018), three edits inside `docs/data-retention.md`, one bullet in `docs/auth.md`, one sentence plus a `LAST_UPDATED` bump in `frontend/src/pages/PrivacyPolicyPage.tsx`, and the narrow deploy-config edits Lane G names (`.env.example`, `.github/workflows/deploy-fly-production.yml`, `scripts/validate_trunk_delivery.py` and their tests) to retire `admin_portal` and the three managed flags' entries from the staged rollout string.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5 / React 18 (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2, zustand, TanStack Query — all already present. Nothing is added.

**Storage**: one SQLite database on the existing mounted volume, `{BRAIN_BUDDY_DATA_DIR}/feature_flags.sqlite3` (`/app/data/feature_flags.sqlite3` in production, per the `brain_buddy_data` mount in `fly.backend.toml`), holding one `feature_flags` table and a `migration_ledger` table — reusing SQLite and the `BEGIN IMMEDIATE`/busy-timeout transactional discipline `TaskRepository` (`backend/app/modules/tasks/repository.py`) already applies on this volume, not a new persistence abstraction. This store deliberately stays on SQLite's default rollback journal rather than WAL: switching journal mode on every concurrent first-start connection can itself race, and for a table this small there is no throughput reason to accept that risk. Schema initialization and migration are each serialized, single-shot transactions. The pre-correction JSON overlay at `{BRAIN_BUDDY_DATA_DIR}/feature-flags/runtime.json` is read once, best-effort, by the one-time migration only, and is never deleted, renamed or written to by this feature.

**Testing**: pytest + FastAPI `TestClient` (backend), Vitest + Testing Library with fake timers (frontend). No paid provider call, no `verify-live`.

**Target Platform**: Linux server (Fly), web frontend, and the mobile app's `SessionProvider` (FR-009's mobile sublane only).

**Project Type**: web service + web client, inside the existing modular monolith.

**Performance Goals**: effective-flag resolution stays O(1) per request with at most one `stat` on the document; re-read only when its modification time or size changed. Polling adds one small authenticated GET per open tab per 15 seconds.

**Constraints**: single backend process on a single Fly machine (`min_machines_running = 1`); state must survive an image swap; an image built before this feature must ignore the document entirely.

**Scale/Scope**: three managed flags; cohorts of a handful of accounts, unbounded by this feature (spec.md Assumptions); one operator in practice.

## Approach

**SQLite is authoritative, not an overlay.** `FeatureFlagSettings` in `backend/app/core/config.py` keeps parsing `BRAIN_BUDDY_FEATURE_FLAGS`/`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` — it is still `delivery_canary`'s sole source, and the one-time migration reads it for the three managed flags' seed values — but `private_flag_effective` and `PRIVATE_FEATURE_FLAGS` are deleted (DD-14: `admin_portal` no longer exists to be private about). A new `FeatureFlagService` resolves each **managed** flag exclusively from its SQLite row; there is no per-request fallback to `config.feature_flags` for these three any more (DD-15). `delivery_canary` alone still resolves from `config.feature_flags.effective_flags` directly, in the same `_me_response` call. That per-flag exclusivity is what makes FR-003 and the migration-parity half of SC-003 provable by construction.

**Three managed flags now, not two (DD-1, DD-15, DD-16).** `delivery_canary` stays excluded: `scripts/production_smoke.sh` reads it out of the authenticated `/api/auth/me` payload to prove the deploy-staged internal cohort is wired end-to-end (`.github/workflows/deploy-fly-production.yml`'s "Authenticated production smoke" step); runtime-managing it would let one operator click durably fail and auto-roll-back every subsequent production deploy. `external_agent_relay` is now included: its per-request backend gate (`external_agent_relay_enabled`/`require_external_agent_relay_enabled` in `dependencies.py`, wired into eight routes in `agents.py`) resolves through SQLite like the other two, while `container.py:130-140`'s `_build_agent_secret_box` **construction-time** decision — production, no `BRAIN_BUDDY_AGENT_RELAY_KEYS`, no existing relay data — is kept as a separate capability the service ANDs with the SQLite rollout answer (DD-16); the construction step itself, and the `SecretsUnavailable` fail-closed placeholder it can return, are untouched. `admin_portal` is not "excluded" — it does not exist as a flag any more (DD-14).

**One resolver, every call site for all three flags.** `backend/app/api/auth.py:61` (`_me_response`) computes `feature_flags` via `config.feature_flags.effective_flags`; this plan replaces the three managed-flag values in that dict, leaving `delivery_canary` computed exactly as today, in the same call. `backend/app/api/dependencies.py`'s `voice_brain_dump_enabled` and `external_agent_relay_enabled`, and `backend/app/container.py`'s `_voice_enabled_for_owner`, all resolve through the service (FR-008), as does `backend/app/api/tasks.py:340-346`'s direct `voice_brain_dump_enabled(current_user, config)` check inside `command_brain_dump_operation`, which gates the brain-dump command route's `commit`, `retry` and `review_provisional` actions. `mobile_task_classification` has no dedicated backend gate today; its only call site is the same `effective_flags` dict `_me_response` builds. `private_flag_effective` and `require_admin_portal_enabled` are **deleted**, not preserved (DD-14).

**The resolver needs the account ID, not only the email.** Cohorts are keyed on the immutable account ID (DD-5), and today's helpers already hold the `User` at every call site.

**Reuse the 009 boundary rather than restating it — narrowed, not layered.** Every route (admin's existing two plus this feature's four) depends on `require_operator` (`dependencies.py:191`) directly now, which already produces the 401/403 precedence, deny-before-touch and content-free denial records 009-FR-002/008 specify. `require_admin_portal_enabled` — the wrapper that additionally checked the now-deleted `admin_portal` flag — is deleted, not bypassed; there is no flag check left to skip (DD-14, 009-FR-013 retired).

**Reuse the 009 lookup for adding, not for rendering.** Adding goes through `AdminService.find_account`, including its `ACCOUNT_ID_PATTERN` guard and post-fetch re-check, inheriting 009-FR-003's exact-match semantics (FR-007). Rendering cohort emails on `GET` does **not** go through `find_account` — that would write one attributed lookup record per cohort member per page load, diluting the 009 audit signal. `FeatureFlagService.describe()` instead takes a plain, non-logging `UserRepository.get_by_id` read; the container wires `UserRepository` into `FeatureFlagService` directly for this. Removing needs no lookup (DD-7).

**Account IDs, not emails, in the store.** Emails resolve for display at read time through the plain account read above, keeping the durable artifact free of personal data; an unresolvable ID still renders and stays removable until purge removes it outright (FR-007, SC-007, DD-9).

**Migration is one-time, transactional, and isolated inside the repository (DD-15).** `FeatureFlagOverrideRepository.__init__` runs the same ledger-guarded pattern `TaskRepository._migrate_legacy_json_once` already uses: a `migration_ledger` row check short-circuits every construction after the first; otherwise a `BEGIN IMMEDIATE` transaction seeds all three flag rows and the ledger row together, committing or rolling back as one unit. Per flag: the legacy JSON overlay's entry wins when it is present, well-formed, and for a flag the overlay ever wrote (`voice_brain_dump`/`mobile_task_classification` only); otherwise `config.feature_flags.states[flag]` supplies it, resolving `internal` to `selected_users` by resolving each `config.feature_flags.internal_users` email to its current account id through a plain `UserRepository.get_by_email` read passed in by `container.py`, skipping an email that does not resolve. `external_agent_relay` always reads the environment baseline, never the legacy JSON. This is the one place `config.feature_flags.states`/`internal_users` are read for these three flags; the normal per-request resolver never touches them again.

**Purge scrubs the cohort store (DD-9, DD-13).** `AccountService.purge_account` (`account_service.py:377-402`) already calls `self.invite_repo.scrub_user(user_id)` before deleting the user record ("GDPR erasure support"). This plan keeps the existing `self.feature_flag_repo.scrub_user(user_id)` call in the same place, before `self.user_repo.delete(user_id)`, removing the purged ID from each of the three managed flags' `selected_users` set — simpler than before since SQLite's fixed schema has no other parseable entry to widen the scrub into (DD-8 is retired). Idempotent, crash-safe by the same SQLite transaction every other write uses. When the store is **degraded**, `scrub_user` raises rather than silently completing or skipping; `purge_account` lets that exception abort the purge **before** `user_repo.delete` runs, and `purge_due_accounts`'s sweep loop isolates that one account's failure so a corrupt store does not block every other account's due purge in the same pass.

**Atomicity by SQLite's own transaction, not a file lock (DD-15).** Every mutation is a targeted read-modify-write inside one `BEGIN IMMEDIATE` transaction — SQLite's own locking (plus a busy timeout) is the concurrency primitive, the same pattern `TaskRepository.command_lock` already uses on this volume; no separate `fcntl.flock` file, and no revision token, since each operation is targeted and idempotent and last-writer-wins across *different* flags is already correct. There is no more "unknown portion of the document" to re-serialize unchanged: the `feature_flags` table's schema is fixed and owned solely by this feature (DD-8 retired).

**Migration replaces "absence is healthy; corruption is degraded" with a stronger invariant (DD-2, DD-15).** After the one-time migration commits, SQLite always holds a row for each of the three managed flags — there is no more healthy-absence branch. A store that cannot be read, is missing a row, or holds a `mode` outside its vocabulary is degraded: every flag resolves to ineffective, every mutation is refused, and the transition logs one coarse `WARNING` (correlation id only, no member data). No reset command, repair button or recovery subsystem beyond the one bounded migration.

**Polling in the auth store, through a distinct refresh path (DD-11).** `useAuthStore.hydrate()` keeps its current initial/startup behavior: any failure, including a transient one, resolves to `{ user: null, status: "anon" }`. FR-009's background poll instead calls a new `refreshSession()`: same `GET /api/auth/me`, but a transient (non-401) failure leaves `user`/`status` untouched and surfaces nothing, while a 401 clears the session exactly as `hydrate()` already does. `startFlagRefresh()` wires a single named-constant 15-second interval plus `focus`/`visibilitychange` listeners while `status === "authed"`, torn down otherwise; wired at module scope in `frontend/src/queryClient.ts:10`, next to the existing `bindAdminSession(queryClient)` call, because `main.tsx` never executes under Vitest.

**FR-009 is client-generic.** `mobile/src/auth/SessionProvider.tsx` gets the same treatment as the web store: a poll effect alongside the existing mount-time `probe()` call, using the same named-constant 15-second interval and the identical transient-tolerant/401-clearing split (DD-11). The poll runs only while `AppState.currentState === "active"`, mirroring the `AppState.addEventListener("change", ...)`/`subscription.remove()` idiom already used by `useClassificationQueue.ts` and `useAgentRunsFeed.ts`, and foregrounding triggers an immediate refetch. `probe()` itself is unchanged.

## Constitution check

- **Spec workflow**: [spec.md](spec.md) is current, DD-1…DD-13 are recorded in place, and no `NEEDS CLARIFICATION` marker remains.
- **Consent & Safety (Principle I)**: no AI, transcription or remote processing is involved and no consent surface changes. The stored document holds account IDs only (FR-001, SC-007). Every operator mutation and cohort-resolving read is recorded content-free (FR-006, DD-10). Manual acceptance uses purpose-seeded `@example.com` accounts with redaction required before evidence enters a PR.
- **Tests (Principle II)**: RED before GREEN in every lane of [tasks.md](tasks.md). Backend via pytest and `TestClient`; frontend via Vitest with fake timers. Edge cases covered explicitly: invalid payloads, refused/deleted flag names (including `admin_portal`), idempotent repeats, concurrent writers, a transaction failing before commit, migration idempotency and its per-flag preference rule (DD-15), a degraded store (DD-2), an unresolvable cohort entry, purge scrubbing a cohort (DD-9), a transient poll failure and a 401 during a poll (DD-11), and `external_agent_relay`'s rollout-AND-capability combination (DD-16).
- **Contracts (Principle III)**: new `StrictBaseModel` request/response schemas in `backend/app/schemas/admin.py`, backend-first, frontend types mirrored by hand. The member-facing `feature_flags` **key set** is pinned unchanged by test (FR-008, SC-003).
- **Observability (Principle IV)**: the existing 009 records already carry the correlation ID and route template; new routes inherit them, plus their own content-free mutation/aggregate-read records (DD-10). Errors reach the operator with the correlation ID visible in state `F-10`.
- **Mobile / resilience / performance**: `SessionProvider.tsx` gains the FR-009 poll effect (Lane E); no other mobile surface changes. Polling is bounded on both clients — stopped while hidden/backgrounded or signed out.
- **Delivery boundary**: [tasks.md](tasks.md) is planning input only. Isolated worktree, TDD, independent verification, the ADR-0008 ASK landing, CI and the Fly release gates all remain authoritative.
- **Design citation**: this plan cites [design.md](design.md)'s `F-01`…`F-13` states for the operator section, and its "Propagation behaviour" contract for FR-009. Feature 009's `D-01`…`D-10` are unchanged and re-asserted by regression test, not re-implemented.

## Project structure

### Documentation (this feature)

```text
specs/010-admin-live-feature-flags/
├── intake.md
├── spec.md
├── design.md
├── plan.md                     # this file
├── checklists/requirements.md
├── tasks.md
├── analysis.md                 # cross-artifact consistency pass, per requirement
└── review-history.md           # both campaigns' record and the owner-decision resolutions
```

### Source code (repository root)

```text
backend/app/
├── api/admin.py            # four runtime-flag routes (GET + 3 mutations, no clear-override); require_operator, not require_admin_portal_enabled
├── api/auth.py             # _me_response resolves all three managed flags via the service
├── api/dependencies.py     # + get_feature_flag_service; voice_brain_dump_enabled + external_agent_relay_enabled read it; require_admin_portal_enabled/ADMIN_PORTAL_FLAG deleted
├── api/tasks.py            # command_brain_dump_operation's direct check routes through the service
├── services/feature_flag_service.py   # rewritten — SQLite-exclusive resolution + audit logging + relay capability AND
├── services/account_service.py  # feature_flag_repo.scrub_user call unchanged; sweep isolation (DD-13)
├── repositories/feature_flag.py  # rewritten — SQLite table, transactional mutate, one-time migration
├── schemas/admin.py        # runtime-flag contracts simplified: mode always present, no override_mode/source/deploy_default_state
├── core/config.py          # PRIVATE_FEATURE_FLAGS/private_flag_effective deleted; ALL_FEATURE_FLAGS = KNOWN_FEATURE_FLAGS; comments record retirement of the three managed flags' env authority
└── container.py            # wire SQLite repository (legacy JSON path + config states/internal_users + UserRepository.get_by_email for migration) + service + relay capability boolean

backend/tests/  # test_feature_flag_repository.py, test_feature_flag_service.py,
                # test_admin_feature_flags_api.py, + assertions in
                # test_account_service.py and test_auth_routes.py

frontend/src/
├── api/{adminTypes.ts, client.ts, adminHooks.ts}   # mode always present; no deploy-default/clear types or call
├── features/admin/AdminFeatureFlagsSection.tsx   # F-01…F-13, minus the clear-override/source-note states; three flag rows
├── features/admin/AdminPage.tsx                  # mounts the section
├── stores/authStore.ts                           # + refreshSession(), startFlagRefresh() (untouched by the correction)
├── queryClient.ts                                # starts the subscription, next to bindAdminSession
├── pages/PrivacyPolicyPage.tsx                    # + one sentence ("store", three flags) + LAST_UPDATED bump (DD-9)
└── **/__tests__/

mobile/src/auth/SessionProvider.tsx   # + poll effect: 15s interval + AppState listener (FR-009, Lane E) — untouched by the correction

docs/decisions/0019-sqlite-runtime-feature-flag-store.md   # NEW ADR, narrows 0018
docs/data-retention.md                                # retention row + export exclusion say "store", three flags (DD-9)
docs/auth.md                                          # operator-authority bullet points at ADR-0019 (DD-9)
.env.example                                          # retire admin_portal + the three managed flags from the example BRAIN_BUDDY_FEATURE_FLAGS string (DD-14, DD-15)
.github/workflows/deploy-fly-production.yml           # staged rollout string drops admin_portal + voice_brain_dump (DD-14, DD-15)
scripts/validate_trunk_delivery.py                    # AUTHORIZED_STAGED_FEATURE_FLAGS / ROLLBACK_KNOWN_FEATURE_FLAGS drop admin_portal
```

**Structure decision**: the backend change stays inside the existing `api → services → repositories` layering wired in `container.py`; the repository is a sibling of `repositories/session.py` and now follows `modules/tasks/repository.py`'s SQLite/transaction/migration-ledger pattern rather than inventing one, the service a sibling of `services/admin_service.py`. The frontend change stays inside `features/admin/` plus the one store that owns session state, plus the one sentence DD-9 adds to the privacy-policy page. The mobile change is unaffected by the correction. Documentation edits are ADR-0019, the named edits inside `docs/data-retention.md`, the one bullet in `docs/auth.md`, the one sentence in `PrivacyPolicyPage.tsx`, and — new to the correction — the narrow deploy-config edits Lane G names, because `admin_portal`'s deletion and the three managed flags' retirement from the deploy-staged baseline are structural, not documentation-only, changes.

## Changed surfaces

| File | Change |
| --- | --- |
| `backend/app/repositories/feature_flag.py` | **Rewritten.** `FeatureFlagOverrideRepository` over one SQLite `feature_flags` table (three rows, always present after migration) plus a `migration_ledger` table: `read()` returns healthy (three well-formed rows) or degraded (unreadable, a missing row, or an out-of-vocabulary `mode` — DD-2); `mutate(fn)` runs inside one `BEGIN IMMEDIATE` transaction, SQLite's own locking serializes writers (DD-15, no `fcntl.flock`); the one-time `_migrate_once` (ledger-guarded, mirrors `TaskRepository._migrate_legacy_json_once`) seeds all three rows from the legacy JSON (two flags only) or the environment baseline, transactionally and restart-idempotently; `scrub_user(user_id)` removes one account ID from each managed flag's cohort, raising when degraded (DD-9, DD-13). No more `clear()` — there is nothing to clear |
| `backend/app/services/feature_flag_service.py` | **Rewritten.** `FeatureFlagService`: `effective_flags(user)`, `is_effective(name, user)`, `describe()` (per managed flag: mode — always present — and cohort, via a plain `UserRepository.get_by_id` read, not `AdminService.find_account`), `set_mode`, `add_selected_user`, `remove_selected_user`. No more `clear_override`. Resolves the three managed flags exclusively from SQLite, `delivery_canary` not at all (DD-15); refuses names outside the managed set (FR-002); refuses every mutation while degraded (FR-004); emits content-free log records (DD-10); `external_agent_relay`'s effective value additionally ANDs the constructor-supplied `relay_capability_available` boolean (DD-16); no in-process cache (every read hits SQLite directly, FR-005) |
| `backend/app/schemas/admin.py` | `AdminFeatureFlagMode`, `AdminFeatureFlagSelectedUser` (`account_id`, `email: str \| None`), `AdminFeatureFlagState` (`name`, `mode: AdminFeatureFlagMode` — always present, no `override_mode`/`source`/`deploy_default_state` — `selected_users`), `AdminFeatureFlagsResponse` (`degraded`, `flags`), `AdminFeatureFlagModeRequest`, `AdminFeatureFlagSelectedUserRequest` (exactly one of `account_id`/`email`). `AdminFeatureFlagDeployState`/`AdminFeatureFlagSource` deleted |
| `backend/app/api/admin.py` | `GET /admin/feature-flags`, `PUT .../mode`, `POST .../selected-users`, `DELETE .../selected-users/{account_id}` — every one `Depends(require_operator)` now, not `require_admin_portal_enabled` (DD-14). No more `DELETE /admin/feature-flags/{flag}` clear-override route. Returns full authoritative post-mutation state (FR-006, FR-010) |
| `backend/app/api/dependencies.py` | **ASK path.** `get_feature_flag_service`; `voice_brain_dump_enabled` and `external_agent_relay_enabled` both resolve through the service now (the latter previously read `config.feature_flags` directly). `ADMIN_PORTAL_FLAG` and `require_admin_portal_enabled` **deleted**; every admin route depends on `require_operator` directly (FR-006, FR-008, DD-1, DD-14, DD-16) |
| `backend/app/api/tasks.py` | **ASK path.** `command_brain_dump_operation`'s direct `voice_brain_dump_enabled(current_user, config)` check (`:340-346`) resolves through the service instead of reading `config.feature_flags` directly (FR-008) |
| `backend/app/api/auth.py` | **ASK path.** `_me_response` (`:50`) resolves all three managed flags through the service inside `feature_flags`; `delivery_canary` unchanged. Covers `/auth/me`, `/auth/login` and `/auth/signup`. Key set unchanged and pinned by test (FR-008) |
| `backend/app/container.py` | wire the SQLite `FeatureFlagOverrideRepository` (passing the legacy JSON path implicitly via `root`, `config.feature_flags.states`/`internal_users`, and a `UserRepository.get_by_email`-backed resolver for migration), compute `relay_capability_available` from whether `_build_agent_secret_box` returned the real box before constructing `FeatureFlagService`, pass the `User` `_voice_enabled_for_owner` already fetches. `_build_agent_secret_box` now reads the flag's SQLite-stored mode (via the already-built repository) instead of `config.feature_flags.states["external_agent_relay"]` to decide whether the placeholder shortcut is safe (DD-1, DD-16) |
| `backend/app/core/config.py` | `PRIVATE_FEATURE_FLAGS` and `private_flag_effective` **deleted**; `ALL_FEATURE_FLAGS = KNOWN_FEATURE_FLAGS`; comments record that the three managed flags' `states`/`internal_users` values are read only by one-time migration code, never by the normal resolver (DD-1, DD-14, DD-15) |
| `backend/app/services/account_service.py` | unchanged call shape: `purge_account`'s existing `feature_flag_repo.scrub_user(user_id)` call (next to `invite_repo.scrub_user`, before `user_repo.delete`) and `purge_due_accounts`'s per-account sweep isolation both carry over onto the SQLite repository unchanged (DD-9, DD-13) |
| `frontend/src/api/{adminTypes.ts,client.ts,adminHooks.ts}` | mirrored types with `mode` always present, no deploy-default/source fields; `getAdminFeatureFlags`/`setAdminFeatureFlagMode`/`addAdminFeatureFlagUser`/`removeAdminFeatureFlagUser` — no `clearAdminFeatureFlagOverride` call; `useAdminFeatureFlags` under the existing owner-scoped `adminKeys` |
| `frontend/src/features/admin/AdminFeatureFlagsSection.tsx` | realizes `F-01`…`F-13` minus the clear-override/source-note states (`F-02` narrows, DD-3 retired); renders all three managed flags including `external_agent_relay` |
| `frontend/src/features/admin/AdminPage.tsx` | mounts the section inside the operator-confirmed branch only (never inside `D-01`, `D-08` or `D-09`) — unaffected by the correction beyond the section it mounts |
| `frontend/src/stores/authStore.ts` | untouched by the 2026-08-15 correction: `refreshSession()`/`startFlagRefresh()` still 15s + focus/visibility while `status === "authed"`; `hydrate()` unchanged (DD-11, FR-009) |
| `frontend/src/queryClient.ts` | unchanged by the correction |
| `frontend/src/pages/PrivacyPolicyPage.tsx` | one sentence under "How long we keep it" naming the runtime **store** (not "document"), covering three flags, plus the `LAST_UPDATED` bump (DD-9) |
| `mobile/src/auth/SessionProvider.tsx` | unaffected by the correction (FR-009, Lane E, unchanged) |
| `docs/decisions/0019-sqlite-runtime-feature-flag-store.md` | **NEW ADR**, narrowing ADR-0018: SQLite sole-truth, the three-flag managed set and `external_agent_relay`'s capability/rollout split (DD-16), the migration contract (DD-15), `admin_portal`'s deletion (DD-14), the audit obligation (DD-10), the purge obligation (DD-9) |
| `docs/data-retention.md` | retention-table row, export-exclusion line and the Admin access records amendment now say "store" and name three flags, pointing at ADR-0019 (DD-9) |
| `docs/auth.md` | operator-authority bullet points at ADR-0019 instead of ADR-0018 (DD-9, FR-007) |
| `.env.example` | the `BRAIN_BUDDY_FEATURE_FLAGS` example/comment drops `admin_portal` and the three now-SQLite-managed flags, keeping only `delivery_canary` (DD-14, DD-15) |
| `.github/workflows/deploy-fly-production.yml` | the "Stage the smoke identity and feature-flag rollout" step's `BRAIN_BUDDY_FEATURE_FLAGS` value and its surrounding comment drop `admin_portal=internal` and `voice_brain_dump=on`, staging only `delivery_canary=internal` (DD-14, DD-15) |
| `scripts/validate_trunk_delivery.py` | `AUTHORIZED_STAGED_FEATURE_FLAGS` becomes `"delivery_canary=internal"`; `ROLLBACK_KNOWN_FEATURE_FLAGS` drops `"admin_portal"` (DD-14) |

Everything outside the rows above is untouched: no other file under `.github/` or `scripts/`, no `mobile/` file other than the already-unaffected `SessionProvider.tsx`, no privacy-policy surface beyond the one sentence DD-9 names.

## Key decisions

Each decision below is the plan-level consequence of the matching spec.md Derived Decision; see the DD table there for the full rationale. DD-1 through DD-13 are the original package; DD-14 through DD-16 are the 2026-08-15 founder correction.

1. **Three managed flags, not the full `KNOWN_FEATURE_FLAGS` set** (DD-1, DD-16) — `delivery_canary` alone still needs the deploy workflow left entirely alone.
2. **SQLite is exclusive per flag, never a merge, and there is no clear/inheritance action left to have** (DD-3, DD-15) — blending would make OFF not mean off; a "deploy default" would require a baseline this design no longer keeps live.
3. **The environment string is read exactly once, by migration, for the three managed flags — and keeps its standing job only for `delivery_canary`** (DD-4, DD-15) — narrower than before: no baseline, no rollback floor, for these three after migration.
4. **Rollback safety is structural, not procedural** — a pre-010 image has no code that reads `feature_flags.sqlite3`, so it is inert to the store; the current image's migration is idempotent and runs once (DD-15, SC-003).
5. **Targeted idempotent operations instead of a document PUT** — correct under concurrency without a revision token; removal idempotent by ID regardless of resolution (DD-7).
6. **SQLite's own transaction locking, not a file lock or a lock service** (DD-15) — reuses the exact pattern `TaskRepository` already trusts on this volume, justified by the same stated, checkable single-machine assumption in spec.md.
7. **Post-migration presence is an invariant, not a fallback state — no reset lever** (DD-2, DD-15, FR-004) — a CLI reset command was proposed and deliberately cut: new operational surface to reach a state the system already reaches by itself.
8. **A purged account's ID is scrubbed from every managed flag's cohort; a degraded store halts the purge rather than silently skipping** (DD-9, DD-13) — mirrors `InviteRepository.scrub_user`'s precedent; one repository method, one purge call, named documentation edits.
9. **Two distinct auth-store code paths for two distinct failure tolerances** (DD-11) — initial hydration fails closed so a cold load doesn't hang forever; background refresh fails open so network noise doesn't sign a member out. Untouched by the correction.
10. **Every operator mutation and every cohort-resolving read gets one content-free log line** (DD-10) — `find_account`'s record doesn't fire for a flag mutation, and using it for cohort rendering would misattribute lookups the operator never performed.
11. **Two ADRs, and neither is optional.** ADR-0017 states "no admin data store" and "anything beyond point 1 requires its own ADR." ADR-0018 narrowed it for the original JSON-overlay design; ADR-0019 narrows ADR-0018 the same way for the SQLite correction, rather than editing an accepted record (ADR-0012).
12. **`admin_portal` is deleted, not merely excluded from management** (DD-14) — resolves the original self-lockout concern structurally: there is no flag left that could hide `/admin` from its only operator.
13. **Rollout and capability are separate axes for `external_agent_relay`** (DD-16) — the construction-time secret-box decision is not redesigned into a live check; the service ANDs the two instead, so a runtime ON can never expose a relay with no configured capability.

## Landing (ADR-0008 ASK)

**Class: ASK (high risk).** Triggers, any one sufficient: it edits `backend/app/api/dependencies.py` (an explicit ASK exact path in `scripts/classify_path_risk.py`), deleting an authorization gate (`require_admin_portal_enabled`) as part of the change; it edits `backend/app/api/auth.py` and `frontend/src/stores/authStore.ts`, both carrying the `auth` token that classifier treats as ASK; it introduces a new durable persistence surface whose contents change what members can reach, now including a third flag (`external_agent_relay`) that gates a data-egress-adjacent capability. ADR-0012 derives `high` from any ASK surface, so the review campaign runs at high risk and requires a recorded human sign-off in addition to the automated lenses. The 2026-08-15 founder correction was accepted directly by the founder rather than through a fresh review campaign (see review-history.md) — that acceptance covers the correction's own scope; it does not change the ASK classification or the landing gate below.

Consequences, all mandatory: **no automatic promotion** (must not land through the PR-less verified-trunk deploy-key path reserved for SHIP/SHOW); **explicit recorded approval** from the maintainer before landing; **green required CI on the exact SHA being landed**; **a short, audited, temporary ruleset intervention**, recording who, why, and when.

**Rollback.** Ordered, each step independently safe:

1. **Fastest, no deploy:** an operator sets the affected flag back to OFF through the portal — reversible in one click, reaching open sessions within ~15 seconds. This is the intended rollback path and the reason no reset command is needed.
2. **Image rollback:** restoring the previous image is a no-op for flag resolution — the SQLite store is inert to a pre-010 build (key decision 4, SC-003). The rollback step's own restaged flag string is whatever the older image's own contemporaneous deploy revision staged, which for the two excluded flags (`delivery_canary`) keeps working unchanged.
3. **Code revert:** leaves the SQLite database on the volume as an unread file; a later re-land picks it up again; deleting the file is an ordinary operational action, not a feature.
4. **Nothing here is irreversible** — every operation this feature adds has an inverse, though that is not the reason for the ASK class; the ASK triggers above are about the surfaces touched.

## Risks

- **Self-inflicted outage by turning a flag off.** Accepted: it is the requested capability, reversible by its inverse, and flags are exposure control — no data is lost and no session is invalidated. Mitigated by the confirmation step FR-010 requires for this transition.
- **The single-process assumption.** SQLite's own transaction locking is correct for one machine. Fly volumes are single-attach and per-machine — if `min_machines_running` is ever raised, each additional machine gets its own volume and its own database, not a second writer racing the first. The failure mode is divergence, not interleaving: each machine's store drifts independently, and an operator's change lands on only whichever machine served the write. Recorded in spec.md Assumptions and ADR-0019; not solved here.
- **Migration runs at repository construction, inside application startup.** A migration transaction that cannot commit (e.g. a disk failure) propagates out of `FeatureFlagOverrideRepository.__init__`, which — like `TaskRepository`'s identical pattern already accepted in this codebase — fails application startup rather than silently starting in some other state. This is deliberate: a migration failure is a storage failure, and starting the app with three managed flags in an unknown state would be worse. A retried process start (the ordinary restart path) migrates cleanly once the underlying storage failure clears.
- **Polling cost and log noise.** One authenticated GET per open tab per 15 seconds, bounded by stopping while hidden or signed out; `/api/auth/me` is a cheap session read. Untouched by the correction.
- **No bound on cohort size.** Built one exact-match add at a time with no listing or bulk-import path, expected to stay small; the per-read email-resolution fan-out is not proven against an unbounded cohort. Named in spec.md Assumptions; bounding it is a follow-up if it ever matters.
- **Scope creep from reviewer speculation.** The Out of Scope section in [spec.md](spec.md) is the boundary and names the specific proposals an earlier pass invented, now including the correction's own boundary (no percentage rollout, no new roles, no generalized migration framework — DD-15/DD-16 are bounded, one-time, three-flag corrections, not a platform). A finding proposing any of these is out of scope unless a failing test proves it necessary. **Reviewer suggestions cannot reopen the frozen slice; the owner decisions in spec.md's DD table — including the 2026-08-15 founder correction — are the only reopening, and they are closed.**

## Complexity tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| A persistence surface (`repositories/feature_flag.py`) in a feature whose stated ideal is "reuse, do not invent" | FR-001/FR-005 require volume durability, and no existing repository owns deployment-wide configuration | Reused `TaskRepository`'s own SQLite/transaction/migration-ledger pattern rather than a bespoke one; an owner-scoped store would break the ADR-0001 invariant every other repository upholds; in-memory state fails FR-005 on the first restart |
| A one-time migration routine, transactional and restart-idempotent | DD-15 requires a safe, non-lossy move off the pre-correction JSON-overlay-plus-environment architecture without a manual operator step | A manual/scripted one-off migration (outside the repository's own construction path) could be skipped, run twice, or run against the wrong data directory; the in-repository, ledger-guarded transaction makes "already migrated" and "not yet migrated" the only two reachable states |
| One purge call, unchanged in call shape, plus named documentation edits | DD-9/DD-13: `InviteRepository.scrub_user`'s precedent and `purge_account`'s "erase every trace" contract both point the same direction | Leaving the ID in place would make `purge_account`'s docstring false, contradicting the repository's own precedent |
| Two ADRs (ADR-0018, now narrowed by ADR-0019) rather than one edited in place | ADR-0017 forbids an admin data store and requires an ADR for anything beyond its point 1; ADR-0012 forbids amending an accepted record retroactively | Editing ADR-0018 in place would falsify a record of what was actually decided and shipped-as-planned on 2026-08-14; a new record dated 2026-08-15 is the repository's own established pattern (ADR-0018 itself narrowed ADR-0017 the same way) |
| Deleting `admin_portal` from `PRIVATE_FEATURE_FLAGS`/gates/tests/docs/the deploy string in one correction, rather than leaving it inert | DD-14: the founder's explicit instruction, and a flag left inert but still declared would keep the self-lockout hazard's *shape* even if no code path could trigger it, contradicting "Admin Portal is key functionality" | A narrower "just stop checking it" change would leave dead configuration surface and a misleading `PRIVATE_FEATURE_FLAGS` tuple of one, exactly the kind of stale artifact the correction exists to remove |
