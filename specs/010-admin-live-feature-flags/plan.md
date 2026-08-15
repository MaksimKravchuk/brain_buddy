# Implementation Plan: Live Feature-Flag Management in the Admin Portal

**Branch**: `feat/010-admin-live-feature-flags` | **Date**: 2026-08-14 | **Revised**: 2026-08-14 (campaign-2 corrections)
**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Tasks**: [tasks.md](tasks.md)
**Analysis**: [analysis.md](analysis.md) · **Review record**: [review-history.md](review-history.md)

**Risk class: ASK (high).** See [Landing](#landing-adr-0008-ask) — it decides how this feature reaches `main`, and it is not a footnote.

## Summary

Add one durable, server-owned JSON document on the existing data volume that overlays the deploy-staged rollout string per **managed flag** (`voice_brain_dump` and `mobile_task_classification` only — DD-1), one service that resolves effective flags from it (falling back to today's environment computation when a flag has no entry, or is not runtime-managed at all), four operator mutation routes plus one clear-override route behind feature 009's existing authorization gate, one new section on the existing `/admin` screen, and a bounded 15-second polling refresh of the identity-and-flags endpoint on **both** clients that read a managed flag — the web auth store's `refreshSession()` and the mobile `SessionProvider`'s poll effect — each using a session-refresh path distinct from its own initial hydration/`probe()` (FR-009, Lane E).

Two review campaigns (`product-decision-required`) found the package narrower than claimed — it managed `delivery_canary` and `external_agent_relay` without accounting for either, asserted logging/privacy dispositions that were not true, reused `hydrate()` for polling in a way that would sign a member out on a network blip, missed a `voice_brain_dump` call site (`backend/app/api/tasks.py`), and left several artifacts contradicting each other at their edges (the `external_agent_relay` rationale, the flag-state response shape, the scope of the purge scrub, and the documentation edits DD-9 requires). All of it is resolved by the owner decisions in [spec.md](spec.md)'s Derived decisions table (DD-1 through DD-13) and carried through this plan; see [review-history.md](review-history.md) for the full finding record. No change to the frozen ten-FR/eight-SC slice.

No new dependency, no new identity, no new transport, no new CLI command, no migration, no deploy or CI edit. Four documentation surfaces change, each narrowly scoped and named by DD-9: a new ADR, three edits inside `docs/data-retention.md`, one bullet in `docs/auth.md`, and one sentence plus a `LAST_UPDATED` bump in `frontend/src/pages/PrivacyPolicyPage.tsx`.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5 / React 18 (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2, zustand, TanStack Query — all already present. Nothing is added.

**Storage**: one JSON document on the existing mounted volume, `{BRAIN_BUDDY_DATA_DIR}/feature-flags/runtime.json` (`/app/data/feature-flags/runtime.json` in production, per the `brain_buddy_data` mount in `fly.backend.toml`). Written through `app/utils/file_ops.atomic_write` (`backend/app/utils/file_ops.py:22` — temporary file, `os.replace`) and serialized by an `fcntl.flock` advisory lock on a sibling lock file.

**Testing**: pytest + FastAPI `TestClient` (backend), Vitest + Testing Library with fake timers (frontend). No paid provider call, no `verify-live`.

**Target Platform**: Linux server (Fly), web frontend, and the mobile app's `SessionProvider` (FR-009's mobile sublane only).

**Project Type**: web service + web client, inside the existing modular monolith.

**Performance Goals**: effective-flag resolution stays O(1) per request with at most one `stat` on the document; re-read only when its modification time or size changed. Polling adds one small authenticated GET per open tab per 15 seconds.

**Constraints**: single backend process on a single Fly machine (`min_machines_running = 1`); state must survive an image swap; an image built before this feature must ignore the document entirely.

**Scale/Scope**: two managed flags; cohorts of a handful of accounts, unbounded by this feature (spec.md Assumptions); one operator in practice.

## Approach

**Overlay, do not replace.** `FeatureFlagSettings` in `backend/app/core/config.py` keeps doing exactly what it does today, including `_is_effective`, `effective_flags` and `private_flag_effective`. A new `FeatureFlagService` asks the new repository whether a **managed** flag has a runtime entry and, only when it does, answers from that entry; otherwise it delegates to the existing config computation unchanged — for an unmanaged managed-set flag with no entry and for `delivery_canary`/`external_agent_relay`, which never have entries because the repository refuses to write one (FR-002). That is what makes FR-003 and SC-003 provable by construction: delete the overlay and the old answer is what remains.

**Two managed flags, not four (DD-1).** `delivery_canary` is the flag `scripts/production_smoke.sh` reads out of the authenticated `/api/auth/me` payload to prove the deploy-staged internal cohort is wired end-to-end (`.github/workflows/deploy-fly-production.yml`'s "Authenticated production smoke" step); runtime-managing it would let one operator click durably fail and auto-roll-back every subsequent production deploy. `external_agent_relay` already has a per-request backend gate (`external_agent_relay_enabled`/`require_external_agent_relay_enabled` in `dependencies.py`, wired into eight routes in `agents.py`), but exclusion still holds because `container.py:130-140`'s `_build_agent_secret_box` makes a **construction-time**, not request-time, decision: in production with no `BRAIN_BUDDY_AGENT_RELAY_KEYS` and the flag OFF, the container returns a fail-closed placeholder that raises `SecretsUnavailable` on first use, and no request-time re-evaluation reaches back into a completed construction step. Both flags stay exactly what they are today, untouched by this feature (FR-002, FR-008).

**One resolver, four call sites.** `backend/app/api/auth.py:61` (`_me_response`) computes `feature_flags` via `config.feature_flags.effective_flags`; this plan replaces just the two managed-flag values in that dict, leaving `delivery_canary`/`external_agent_relay` computed exactly as today, in the same call. `backend/app/api/dependencies.py:281` (`voice_brain_dump_enabled`) and `backend/app/container.py:303` (`_voice_enabled_for_owner`) move to the service (FR-008), as does `backend/app/api/tasks.py:340-346`'s direct `voice_brain_dump_enabled(current_user, config)` check inside `command_brain_dump_operation`, which gates the brain-dump command route's `commit`, `retry` and `review_provisional` actions and today reads `config.feature_flags` directly. `external_agent_relay_enabled` (`dependencies.py:316`) is **not** touched. `mobile_task_classification` has no dedicated backend gate today; its only call site is the same `effective_flags` dict `_me_response` builds. `private_flag_effective` (`dependencies.py:259`, for `admin_portal`) deliberately does **not** move (DD-1, FR-006).

**The resolver needs the account ID, not only the email.** Cohorts are keyed on the immutable account ID (DD-5), and today's helpers already hold the `User` at every call site.

**Reuse the 009 boundary rather than restating it.** Every new route depends on `require_admin_portal_enabled` (`dependencies.py:240`), which already composes `require_operator` and produces the 401/403/404 precedence, deny-before-touch and content-free denial records 009-FR-002/008/013 specify.

**Reuse the 009 lookup for adding, not for rendering.** Adding goes through `AdminService.find_account`, including its `ACCOUNT_ID_PATTERN` guard and post-fetch re-check, inheriting 009-FR-003's exact-match semantics (FR-007). Rendering cohort emails on `GET` does **not** go through `find_account` — that would write one attributed lookup record per cohort member per page load, diluting the 009 audit signal. `FeatureFlagService.describe()` instead takes a plain, non-logging `UserRepository.get_by_id` read; the container wires `UserRepository` into `FeatureFlagService` directly for this. Removing needs no lookup (DD-7).

**Account IDs, not emails, in the store.** Emails resolve for display at read time through the plain account read above, keeping the durable artifact free of personal data; an unresolvable ID still renders and stays removable until purge removes it outright (FR-007, SC-007, DD-9).

**Purge scrubs the cohort store (DD-9, DD-13).** `AccountService.purge_account` (`account_service.py:377-402`) already calls `self.invite_repo.scrub_user(user_id)` before deleting the user record ("GDPR erasure support"). This plan adds `self.feature_flag_repo.scrub_user(user_id)` in the same place, before `self.user_repo.delete(user_id)`, removing the purged ID from every managed flag's `selected_users` set **and** from any other parseable entry's `selected_users` array — the one narrow, named exception to DD-8's byte-preservation. Idempotent, crash-safe by the same mechanism as every other repository write. When the document is **degraded**, `scrub_user` raises rather than silently completing or skipping; `purge_account` lets that exception abort the purge **before** `user_repo.delete` runs, and `purge_due_accounts`'s sweep loop isolates that one account's failure so a corrupt document does not block every other account's due purge in the same pass.

**Atomicity by the mechanism the repository already trusts.** Every mutation is a targeted read-modify-write inside an advisory file lock, committed by `atomic_write`'s temporary-file-then-`os.replace`. Because each operation is targeted and idempotent, last-writer-wins across *different* flags is already correct and no revision token is needed. `mutate()`'s read-modify-write applies the pure function to the *known* portion of the parsed document and re-serializes the unknown portion unchanged (DD-8).

**Absence is healthy; corruption is degraded — two different fallbacks (DD-2).** An absent document means every flag resolves from the deploy baseline and the *very next* mutation creates it. A document that exists but fails to parse means every flag still resolves from the baseline, but every mutation is refused, and the transition logs one coarse `WARNING` (correlation id, reason band, count of overrides that stopped applying, no member data). No reset command, repair button or recovery subsystem for either case.

**Polling in the auth store, through a distinct refresh path (DD-11).** `useAuthStore.hydrate()` keeps its current initial/startup behavior: any failure, including a transient one, resolves to `{ user: null, status: "anon" }`. FR-009's background poll instead calls a new `refreshSession()`: same `GET /api/auth/me`, but a transient (non-401) failure leaves `user`/`status` untouched and surfaces nothing, while a 401 clears the session exactly as `hydrate()` already does. `startFlagRefresh()` wires a single named-constant 15-second interval plus `focus`/`visibilitychange` listeners while `status === "authed"`, torn down otherwise; wired at module scope in `frontend/src/queryClient.ts:10`, next to the existing `bindAdminSession(queryClient)` call, because `main.tsx` never executes under Vitest.

**FR-009 is client-generic.** `mobile/src/auth/SessionProvider.tsx` gets the same treatment as the web store: a poll effect alongside the existing mount-time `probe()` call, using the same named-constant 15-second interval and the identical transient-tolerant/401-clearing split (DD-11). The poll runs only while `AppState.currentState === "active"`, mirroring the `AppState.addEventListener("change", ...)`/`subscription.remove()` idiom already used by `useClassificationQueue.ts` and `useAgentRunsFeed.ts`, and foregrounding triggers an immediate refetch. `probe()` itself is unchanged.

## Constitution check

- **Spec workflow**: [spec.md](spec.md) is current, DD-1…DD-13 are recorded in place, and no `NEEDS CLARIFICATION` marker remains.
- **Consent & Safety (Principle I)**: no AI, transcription or remote processing is involved and no consent surface changes. The stored document holds account IDs only (FR-001, SC-007). Every operator mutation and cohort-resolving read is recorded content-free (FR-006, DD-10). Manual acceptance uses purpose-seeded `@example.com` accounts with redaction required before evidence enters a PR.
- **Tests (Principle II)**: RED before GREEN in every lane of [tasks.md](tasks.md). Backend via pytest and `TestClient`; frontend via Vitest with fake timers. Edge cases covered explicitly: invalid payloads, refused flag names, idempotent repeats, concurrent writers, a crash between write and rename, a malformed document versus an absent one (DD-2), an unresolvable cohort entry, purge scrubbing a cohort (DD-9), a transient poll failure and a 401 during a poll (DD-11).
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
├── api/admin.py            # + five runtime-flag routes (four mutations + clear-override)
├── api/auth.py             # _me_response resolves the two managed flags via the service
├── api/dependencies.py     # + get_feature_flag_service; only voice_brain_dump_enabled reads it
├── api/tasks.py            # command_brain_dump_operation's direct check routes through the service
├── services/feature_flag_service.py   # NEW — overlay + effective resolution + audit logging
├── services/account_service.py  # + feature_flag_repo.scrub_user call; sweep isolation (DD-13)
├── repositories/feature_flag.py  # NEW — locked read-modify-write, atomic replace, opaque preservation
├── schemas/admin.py        # + runtime-flag request/response contracts
├── core/config.py          # unchanged behaviour; one comment records the managed set
└── container.py            # wire repository + service + UserRepository

backend/tests/  # test_feature_flag_repository.py, test_feature_flag_service.py,
                # test_admin_feature_flags_api.py, + assertions in
                # test_account_service.py and test_auth_routes.py

frontend/src/
├── api/{adminTypes.ts, client.ts, adminHooks.ts}
├── features/admin/AdminFeatureFlagsSection.tsx   # NEW — F-01…F-13
├── features/admin/AdminPage.tsx                  # mounts the section
├── stores/authStore.ts                           # + refreshSession(), startFlagRefresh()
├── queryClient.ts                                # starts the subscription, next to bindAdminSession
├── pages/PrivacyPolicyPage.tsx                    # + one sentence + LAST_UPDATED bump (DD-9)
└── **/__tests__/

mobile/src/auth/SessionProvider.tsx   # + poll effect: 15s interval + AppState listener (FR-009, Lane E)

docs/decisions/0018-runtime-feature-flag-overlay.md   # NEW ADR
docs/data-retention.md                                # + retention row, export exclusion, Admin-access amendment (DD-9)
docs/auth.md                                          # + one operator-authority bullet (DD-9)
```

**Structure decision**: the backend change stays inside the existing `api → services → repositories` layering wired in `container.py`; the new repository is a sibling of `repositories/session.py`, the new service a sibling of `services/admin_service.py`. The frontend change stays inside `features/admin/` plus the one store that owns session state, plus the one sentence DD-9 adds to the privacy-policy page. The mobile change is the single `SessionProvider.tsx` poll effect FR-009's mobile sublane requires. `scripts/` and `.github/` are deliberately untouched; the documentation edits are exactly the new ADR, the three named edits inside `docs/data-retention.md`, the one bullet in `docs/auth.md`, and the one sentence in `PrivacyPolicyPage.tsx`.

## Changed surfaces

| File | Change |
| --- | --- |
| `backend/app/repositories/feature_flag.py` | **NEW** `FeatureFlagOverrideRepository`: `read()` distinguishes **absent** (healthy, empty overlay) from **unreadable/malformed** (degraded marker) (DD-2); `mutate(fn)` holds an `fcntl.flock` on `runtime.json.lock`, re-reads under the lock, applies the function to the known portion while re-serializing the unknown portion unchanged (DD-8), commits with `atomic_write`; `clear(flag)` removes a flag's entry entirely (DD-3); `scrub_user(user_id)` removes one account ID from every parseable entry's cohort, raising when the document is degraded (DD-9, DD-13) |
| `backend/app/services/feature_flag_service.py` | **NEW** `FeatureFlagService`: `effective_flags(user)`, `is_effective(name, user)`, `describe()` (per managed flag: mode, source, deploy-default state, cohort — via a plain `UserRepository.get_by_id` read, not `AdminService.find_account`), `set_mode`, `clear_override`, `add_selected_user`, `remove_selected_user`. Delegates to `config.feature_flags` for unmanaged flags and any managed flag with no entry; refuses names outside the managed set (FR-002); refuses every mutation while degraded (FR-004); emits content-free log records (DD-10); caches on `st_mtime_ns`/`st_size` (FR-005) |
| `backend/app/schemas/admin.py` | + `AdminFeatureFlagMode`, `AdminFeatureFlagSelectedUser` (`account_id`, `email: str \| None`), `AdminFeatureFlagState` (`name`, `override_mode: AdminFeatureFlagMode \| None`, `source`, `deploy_default_state: AdminFeatureFlagMode`, `selected_users` — DD-3's three-field split), `AdminFeatureFlagsResponse` (`degraded`, `flags`), `AdminFeatureFlagModeRequest`, `AdminFeatureFlagSelectedUserRequest` (exactly one of `account_id`/`email`) |
| `backend/app/api/admin.py` | + `GET /admin/feature-flags`, `PUT .../mode`, `DELETE /admin/feature-flags/{flag}` (clear override — deletes the entire runtime entry, cohort included, unlike a mode change to OFF/ON which retains it, DD-3/DD-6), `POST .../selected-users`, `DELETE .../selected-users/{account_id}` — every one `Depends(require_admin_portal_enabled)`, returning full authoritative post-mutation state (FR-006, FR-010) |
| `backend/app/api/dependencies.py` | **ASK path.** + `get_feature_flag_service`; `voice_brain_dump_enabled` (`:278`) resolves through the service. `external_agent_relay_enabled` (`:313`), `require_operator`, `require_admin_portal_enabled` are **not** touched (FR-006, FR-008, DD-1) |
| `backend/app/api/tasks.py` | **ASK path.** `command_brain_dump_operation`'s direct `voice_brain_dump_enabled(current_user, config)` check (`:340-346`) resolves through the service instead of reading `config.feature_flags` directly (FR-008) |
| `backend/app/api/auth.py` | **ASK path.** `_me_response` (`:50`) resolves the two managed flags through the service inside `feature_flags`; `delivery_canary`/`external_agent_relay` unchanged. Covers `/auth/me`, `/auth/login` and `/auth/signup`. Key set unchanged and pinned by test (FR-008) |
| `backend/app/container.py` | wire `FeatureFlagOverrideRepository`, `FeatureFlagService` (with `UserRepository`), pass the `User` `_voice_enabled_for_owner` (`:293`) already fetches. `_build_agent_secret_box` (`:130`) is **not** touched (DD-1) |
| `backend/app/core/config.py` | no behaviour change; one comment records the two-flag managed subset of `KNOWN_FEATURE_FLAGS` (DD-1) |
| `backend/app/services/account_service.py` | + one call in `purge_account` (`:400`, next to `invite_repo.scrub_user`, before `user_repo.delete`): `feature_flag_repo.scrub_user(user_id)`, raising rather than completing when degraded, aborting the purge before deletion; `purge_due_accounts`'s sweep loop (`:363-375`) gains per-account failure isolation (DD-9, DD-13) |
| `frontend/src/api/{adminTypes.ts,client.ts,adminHooks.ts}` | mirrored types; `getAdminFeatureFlags`/`setAdminFeatureFlagMode`/`clearAdminFeatureFlagOverride`/`addAdminFeatureFlagUser`/`removeAdminFeatureFlagUser`; `useAdminFeatureFlags` under the existing owner-scoped `adminKeys` (refetchable, unlike `useAdminStatus`, only from `AdminPage`, 009-FR-011 preserved) |
| `frontend/src/features/admin/AdminFeatureFlagsSection.tsx` | **NEW** — realizes `F-01`…`F-13` |
| `frontend/src/features/admin/AdminPage.tsx` | mounts the section inside the operator-confirmed branch only (never inside `D-01`, `D-08` or `D-09`) |
| `frontend/src/stores/authStore.ts` | **ASK path.** + `refreshSession()` and `startFlagRefresh()`/teardown: 15-second interval plus `focus`/`visibilitychange` listeners while `status === "authed"`. `hydrate()` unchanged (DD-11, FR-009) |
| `frontend/src/queryClient.ts` | starts `startFlagRefresh()` once, next to `bindAdminSession(queryClient)` at module scope (`:10`) |
| `frontend/src/pages/PrivacyPolicyPage.tsx` | + one sentence under "How long we keep it" naming the runtime document, plus the `LAST_UPDATED` bump (DD-9) |
| `mobile/src/auth/SessionProvider.tsx` | **NEW poll effect**, alongside the mount-time `probe()` call (`:269`): a 15-second interval (same constant as web) plus an `AppState` listener, same DD-11 split; `probe()` unchanged (FR-009, Lane E) |
| `docs/decisions/0018-runtime-feature-flag-overlay.md` | **NEW ADR** — per-flag precedence, the two-flag managed set and exclusion reasons, the audit obligation (DD-10), the purge obligation (DD-9) |
| `docs/data-retention.md` | + one retention-table row, one export-exclusion line, an amendment to the existing Admin access records section (DD-9) |
| `docs/auth.md` | + one operator-authority bullet pointing at ADR-0018 (DD-9, FR-007) |

Nothing else is edited beyond the rows above: no file under `.github/` or `scripts/`, no `.env*` file, no `mobile/` file other than `SessionProvider.tsx`, no privacy-policy surface beyond the one sentence DD-9 names.

## Key decisions

Each decision below is the plan-level consequence of the matching spec.md Derived Decision; see the DD table there for the full rationale.

1. **Two managed flags, not the full `KNOWN_FEATURE_FLAGS` set** (DD-1) — lets this feature leave the deploy workflow entirely alone.
2. **Per-flag overlay, never a merge, plus an explicit clear that deletes the whole entry, cohort included** (DD-3) — blending would make OFF not mean off and would make SC-003's fallback claim untestable.
3. **The environment string keeps its job** for the flags it still governs (DD-4) — baseline, rollback floor, and for the two excluded flags the *only* source of truth.
4. **Rollback safety is structural, not procedural** — a pre-010 image has no code that reads `runtime.json`, so it is inert to the document; the current image falls back to the environment when absent, and the first mutation creates it (DD-2, SC-003).
5. **Targeted idempotent operations instead of a document PUT** — correct under concurrency without a revision token; removal idempotent by ID regardless of resolution (DD-7).
6. **`flock` plus atomic replace, not a lock service** — justified by the stated, checkable single-machine assumption in spec.md.
7. **Absence is healthy, corruption is degraded — no reset lever** (DD-2, FR-004) — a CLI reset command was proposed and deliberately cut: new operational surface to reach a state the system already reaches by itself.
8. **A purged account's ID is scrubbed from every parseable cohort; a degraded store halts the purge rather than silently skipping** (DD-9, DD-13) — mirrors `InviteRepository.scrub_user`'s precedent; one repository method, one purge call, four named documentation edits.
9. **Two distinct auth-store code paths for two distinct failure tolerances** (DD-11) — initial hydration fails closed so a cold load doesn't hang forever; background refresh fails open so network noise doesn't sign a member out.
10. **Every operator mutation and every cohort-resolving read gets one content-free log line** (DD-10) — `find_account`'s record doesn't fire for a flag mutation, and using it for cohort rendering would misattribute lookups the operator never performed.
11. **One ADR, and it is not optional.** ADR-0017 states "no admin data store" and "anything beyond point 1 requires its own ADR." This feature adds a durable operator-owned document plus a narrowly-scoped purge integration and audit obligation, so ADR-0018 narrows it explicitly and records the single-process serialization assumption.

## Landing (ADR-0008 ASK)

**Class: ASK (high risk).** Triggers, any one sufficient: it edits `backend/app/api/dependencies.py` (an explicit ASK exact path in `scripts/classify_path_risk.py`); it edits `backend/app/api/auth.py` and `frontend/src/stores/authStore.ts`, both carrying the `auth` token that classifier treats as ASK; it introduces a new durable persistence surface whose contents change what members can reach. ADR-0012 derives `high` from any ASK surface, so the review campaign runs at high risk and requires a recorded human sign-off in addition to the automated lenses.

Consequences, all mandatory: **no automatic promotion** (must not land through the PR-less verified-trunk deploy-key path reserved for SHIP/SHOW); **explicit recorded approval** from the maintainer before landing; **green required CI on the exact SHA being landed**; **a short, audited, temporary ruleset intervention**, recording who, why, and when.

**Rollback.** Ordered, each step independently safe:

1. **Fastest, no deploy:** an operator sets the affected flag back through the portal, or clears its override entirely — reversible in one click, reaching open sessions within ~15 seconds. This is the intended rollback path and the reason no reset command is needed.
2. **Image rollback:** restoring the previous image is a no-op for flag resolution — the document is inert to a pre-010 build (key decision 4, SC-003). The existing deploy-workflow flag-staging contract keeps working for every flag.
3. **Code revert:** leaves the document on the volume as an unread file; a later re-land picks it up again; deleting the file is an ordinary operational action, not a feature.
4. **Nothing here is irreversible** — every operation this feature adds has an inverse, though that is not the reason for the ASK class; the ASK triggers above are about the surfaces touched.

## Risks

- **Self-inflicted outage by turning a flag off.** Accepted: it is the requested capability, reversible by its inverse, and flags are exposure control — no data is lost and no session is invalidated. Mitigated by the source note (`F-02`) plus the confirmation step FR-010 requires for this transition.
- **The single-process assumption.** `flock` plus atomic replace is correct for one machine. Fly volumes are single-attach and per-machine — if `min_machines_running` is ever raised, each additional machine gets its own volume and its own `runtime.json`, not a second writer racing the first. The failure mode is divergence, not interleaving: each machine's document drifts independently, and an operator's change lands on only whichever machine served the write. Recorded in spec.md Assumptions and ADR-0018; not solved here.
- **Polling cost and log noise.** One authenticated GET per open tab per 15 seconds, bounded by stopping while hidden or signed out; `/api/auth/me` is a cheap session read.
- **No bound on cohort size.** Built one exact-match add at a time with no listing or bulk-import path, expected to stay small; the per-read email-resolution fan-out is not proven against an unbounded cohort. Named in spec.md Assumptions; bounding it is a follow-up if it ever matters.
- **Scope creep from reviewer speculation.** The Out of Scope section in [spec.md](spec.md) is the boundary and names the specific proposals an earlier pass invented. A finding proposing any of these — or percentages, segments, schedules, an audit store, a revision protocol or a user directory — is out of scope unless a failing test proves it necessary. **Reviewer suggestions cannot raise the 10-FR/8-SC cap or reopen the frozen slice; the owner decisions in spec.md's DD table are the only reopening, and they are now closed.**

## Complexity tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| A new persistence surface (`repositories/feature_flag.py`) in a feature whose stated ideal is "reuse, do not invent" | FR-001/FR-005 require volume durability, and no existing repository owns deployment-wide configuration | An owner-scoped store would break the ADR-0001 invariant every other repository upholds; in-memory state fails FR-005 on the first restart |
| Two sources of truth for one flag (environment and runtime) | DD-4 requires the environment string to remain the baseline and rollback floor | Migrating the environment configuration into the store would make a rollback lose the rollout and force the deploy-workflow redesign spec.md rules out |
| One purge call and four named documentation edits, reopening a line the founder's slice had excluded | DD-9/DD-13: `InviteRepository.scrub_user`'s precedent and `purge_account`'s "erase every trace" contract both point the same direction | Leaving the ID in place would make `purge_account`'s docstring false, contradicting the repository's own precedent |
| A new ADR in a feature touching several small product-facing surfaces | ADR-0017 forbids an admin data store and requires an ADR for anything beyond its point 1 | Not writing it leaves an accepted decision silently contradicted |
