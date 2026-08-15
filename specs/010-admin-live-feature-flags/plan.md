# Implementation Plan: Live Feature-Flag Management in the Admin Portal

**Branch**: `feat/010-admin-live-feature-flags` | **Date**: 2026-08-14 | **Revised**: 2026-08-14 (campaign 2 corrections)
**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Tasks**: [tasks.md](tasks.md)
**Analysis**: [analysis.md](analysis.md) · **Review record**: [review-history.md](review-history.md)

**Risk class: ASK (high).** See [Landing](#landing-adr-0008-ask) — it decides how
this feature reaches `main`, and it is not a footnote.

## Summary

Add one durable, server-owned JSON document on the existing data volume that
overlays the deploy-staged rollout string per **managed flag** (`voice_brain_dump`
and `mobile_task_classification` only — DD-1), one service that resolves
effective flags from it (falling back to today's environment computation when a
flag has no entry, or is not runtime-managed at all), four operator mutation
routes plus one clear-override route behind feature 009's existing authorization
gate, one new section on the existing `/admin` screen, and a bounded 15-second
polling refresh of the identity-and-flags endpoint on **both** clients that read
a managed flag — the web auth store's `refreshSession()` and the mobile
`SessionProvider`'s poll effect — each using a session-refresh path distinct from
its own initial hydration/`probe()` (FR-009, Lane E).

Campaign 1 (`product-decision-required`) found the package narrower than it
claimed to be in three ways this revision closes: it managed `delivery_canary`
(a production release-smoke input) and `external_agent_relay` without
accounting for either; it asserted logging and privacy dispositions that were
not actually true; and it reused `hydrate()` for background polling in a way
that would sign a member out on a network blip. Campaign 2 then found this plan
itself had drifted from spec.md's and tasks.md's own campaign-1 and campaign-2
corrections at several edges — the `external_agent_relay` exclusion rationale,
the mobile half of FR-009, a missed `voice_brain_dump` call site in
`backend/app/api/tasks.py`, the flag-state response shape, the scope of the
purge scrub, and the full set of documentation edits DD-9 requires — and this
revision closes each of those, with no change to the frozen ten-FR/eight-SC
slice. All of it is resolved by the owner decisions in [spec.md](spec.md)'s
Derived decisions table (DD-1 through DD-13) and carried through this plan.

No new dependency, no new identity, no new transport, no new CLI command, no
migration, no deploy or CI edit. Four documentation surfaces change, each
narrowly scoped and named by DD-9: the new ADR, three edits inside
`docs/data-retention.md` (a retention-table row, an export-exclusion line, and
an amendment to the existing Admin access records row/section), one bullet in
`docs/auth.md`'s operator-authority list, and one sentence plus a
`LAST_UPDATED` bump in `frontend/src/pages/PrivacyPolicyPage.tsx`. Ten
functional requirements, eight success criteria; the spec's Out of Scope
section is the boundary and reviewer proposals cannot widen it.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript 5 / React 18 (frontend)

**Primary Dependencies**: FastAPI, Pydantic v2, zustand, TanStack Query — all
already present. Nothing is added.

**Storage**: one JSON document on the existing mounted volume,
`{BRAIN_BUDDY_DATA_DIR}/feature-flags/runtime.json`
(`/app/data/feature-flags/runtime.json` in production, per the `brain_buddy_data`
mount in `fly.backend.toml`). Written through the existing
`app/utils/file_ops.atomic_write` (`backend/app/utils/file_ops.py:22` —
temporary file, `os.replace`) and serialized by an `fcntl.flock` advisory lock on
a sibling lock file.

**Testing**: pytest + FastAPI `TestClient` (backend), Vitest + Testing Library
with fake timers (frontend). No paid provider call, no `verify-live`.

**Target Platform**: Linux server (Fly), web frontend, and the mobile app's
`SessionProvider` (FR-009's mobile sublane only — no other mobile surface
changes).

**Project Type**: web service + web client, inside the existing modular monolith.

**Performance Goals**: effective-flag resolution stays O(1) per request with at
most one `stat` on the document; the document is re-read only when its
modification time or size changed. Polling adds one small authenticated GET per
open tab per 15 seconds.

**Constraints**: single backend process on a single Fly machine
(`min_machines_running = 1`); state must survive an image swap; an image built
before this feature must ignore the document entirely.

**Scale/Scope**: two managed flags; cohorts of a handful of accounts, unbounded
by this feature (see spec.md Assumptions); one operator in practice.

## Approach

**Overlay, do not replace.** `FeatureFlagSettings` in
`backend/app/core/config.py` keeps doing exactly what it does today, including
`_is_effective`, `effective_flags` and `private_flag_effective`. A new
`FeatureFlagService` asks the new repository whether a **managed** flag has a
runtime entry and, only when it does, answers from that entry; otherwise it
delegates to the existing config computation unchanged — for both an unmanaged
managed-set flag with no entry and for `delivery_canary`/`external_agent_relay`,
which never have entries because the repository refuses to write one (FR-002).
That is what makes FR-003 and SC-003 provable by construction rather than by
review: delete the overlay and the old answer is what remains.

**Two managed flags, not four — and why the other two `KNOWN_FEATURE_FLAGS`
entries stay untouched (DD-1).** `delivery_canary` is the flag
`scripts/production_smoke.sh` reads out of the authenticated `/api/auth/me`
payload to prove the deploy-staged internal cohort is wired end-to-end
(`.github/workflows/deploy-fly-production.yml`'s "Authenticated production
smoke" step); making it runtime-manageable would let one operator click
durably fail and auto-roll-back every subsequent production deploy, a
cross-boundary consequence campaign 1 found no artifact had accounted for.
`external_agent_relay` is excluded for a different reason than campaign 1
claimed: it already has a per-request backend gate —
`external_agent_relay_enabled`/`require_external_agent_relay_enabled` in
`backend/app/api/dependencies.py`, wired into eight routes in
`backend/app/api/agents.py` — and campaign 2 found campaign 1's rationale had
wrongly asserted that gate did not exist. Exclusion still holds, because
`backend/app/container.py:130-140`'s `_build_agent_secret_box` makes a
**construction-time**, not request-time, decision: in production with no
`BRAIN_BUDDY_AGENT_RELAY_KEYS` and the flag OFF, the container returns a
fail-closed placeholder that raises `SecretsUnavailable` (an unhandled 500, not
the fail-closed 404 the flag contract promises elsewhere) on first use. Runtime
enabling the flag cannot retroactively satisfy that startup prerequisite once
the process has started — no request-time re-evaluation reaches back into a
completed construction step — so managing it at runtime would require
rebuilding that construction-time decision as a live, re-enterable one, which
this feature does not build. Both flags stay exactly what they are today —
environment-only, invisible to this feature's routes and screen — and neither
needs a carve-out in the resolver: `external_agent_relay_enabled`'s existing
per-request gate and `_build_agent_secret_box`'s existing construction-time
check are both preserved exactly as they are, untouched by this feature
(FR-002, FR-008).

**One resolver, the three `voice_brain_dump` call sites and the one
`mobile_task_classification` call site that check a managed flag today.**
`backend/app/api/auth.py:61` (`_me_response`) computes the whole
`feature_flags` dict via `config.feature_flags.effective_flags`; this plan
replaces just the two managed-flag values in that dict with the service's
answer, leaving `delivery_canary` and `external_agent_relay` computed exactly as
today, in the same call. `backend/app/api/dependencies.py:281`
(`voice_brain_dump_enabled`) and `backend/app/container.py:303`
(`_voice_enabled_for_owner`) move to the service (FR-008), and so does a third
call site campaign 2 found missing from this plan's own changed-surface table:
`backend/app/api/tasks.py:340-346`'s direct
`voice_brain_dump_enabled(current_user, config)` check inside
`command_brain_dump_operation`, which gates the brain-dump command route's
`commit`, `retry` and `review_provisional` actions and today reads
`config.feature_flags` directly rather than going through the dependency.
`external_agent_relay_enabled` (`dependencies.py:316`) is **not** touched — it
stays on `config.feature_flags.effective_flags` because `external_agent_relay`
is not a managed flag. `mobile_task_classification` has no dedicated backend
gate today (it is client-side-only exposure per `config.py`'s own comment); its
only call site is the same `effective_flags` dict `_me_response` already builds,
so no second backend surface needs enumerating for it. The sixth call site,
`backend/app/api/dependencies.py:259` (`private_flag_effective` for
`admin_portal`), deliberately does **not** move: that flag stays
environment-owned (DD-1, FR-006).

**The resolver needs the account ID, not only the email.** Cohorts are keyed on
the immutable account ID (DD-5), and today's helpers already hold the `User` at
every one of those call sites — `_voice_enabled_for_owner` even fetches it —
so the signature change is local and no new lookup is introduced.

**Reuse the 009 boundary rather than restating it.** Every new route depends on
`require_admin_portal_enabled` (`backend/app/api/dependencies.py:240`), which
already composes `require_operator` and therefore already produces the
401/403/404 precedence, the deny-before-touch property and the content-free
denial records that 009-FR-002, 009-FR-008 and 009-FR-013 specify. Adding a
second authorization mechanism here would be a second enforcement of a property
the repository already has, and a place for the two to drift.

**Reuse the 009 lookup for adding, but not for rendering (DD-9's precedent
corrected for reads).** Adding a selected user goes through
`AdminService.find_account`, including its `ACCOUNT_ID_PATTERN` charset guard
and its post-fetch identity re-check, so the exact-match semantics of
009-FR-003 are inherited rather than re-implemented (FR-007). Rendering the
cohort's canonical emails on every `GET` does **not** go through
`find_account`: that method unconditionally emits one "Admin lookup" log record
per call (009-FR-008), and resolving a whole cohort's emails on every read
would write one attributed-lookup record per cohort member per page load,
diluting the 009 audit signal with lookups the operator never actually
performed. `FeatureFlagService.describe()` instead takes a plain,
non-logging `UserRepository.get_by_id` read — the container wires
`UserRepository` into `FeatureFlagService` directly for this purpose, not
`AdminService`. Removing is idempotent by stored ID and needs no lookup at all
(DD-7).

**Account IDs, not emails, in the store.** Emails are resolved for display at
read time through the plain account read above. That keeps the durable artifact
free of personal data, and it is why an unresolvable ID still renders and stays
removable: a stale ID resolves to nothing, grants nothing (matching is against
the *authenticated* user's own ID), and stays removable until purge removes it
outright (FR-007, SC-007, DD-9).

**Purge scrubs the cohort store, mirroring the one existing precedent for this
exact shape — widened to every parseable entry, and fail-closed when the store
is degraded (DD-9, DD-13).** `AccountService.purge_account`
(`backend/app/services/account_service.py:377-402`) already calls
`self.invite_repo.scrub_user(user_id)` before deleting the user record, with the
documented rationale "GDPR erasure support" (`backend/app/repositories/
invite.py:44-50`). This plan adds one more call in the same place, before
`self.user_repo.delete(user_id)`: `self.feature_flag_repo.scrub_user(user_id)`,
removing the purged ID from every managed flag's `selected_users` set **and**
from a `selected_users` array reachable inside any other parseable entry — one
naming a flag this build does not declare, and one naming a flag this build
declares but does not manage — under the same `flock`/atomic-replace path every
other mutation uses; this is the one narrow, named exception to DD-8's opaque
byte-preservation, scoped to this one field for this one ID (DD-9 campaign-2
correction: scoping the scrub to only the two managed flags would leave a
purged ID permanently orphaned inside an entry DD-8 otherwise carries through
every write untouched). It is idempotent (an ID absent from every cohort is a
no-op) and crash-safe by the same mechanism as every other repository write.
When the document is **degraded** (unreadable or malformed), `scrub_user`
cannot honor either DD-8's carve-out or its own erasure obligation against
content it never actually parsed, so it raises rather than silently completing
or silently skipping; `purge_account` lets that exception abort the purge
**before** `user_repo.delete` runs, so the account, its email and its password
hash are retained past the documented 14-day promise for as long as the
document stays corrupt, and the 60-second maintenance sweep retries the purge on
every pass until an operator repairs the document. `purge_due_accounts`'s sweep
loop isolates that one account's failure so a single corrupt runtime document
does not also block every other unrelated account's due purge in the same pass
(DD-13).

**Atomicity by the mechanism the repository already trusts.** Every mutation is a
targeted read-modify-write inside an advisory file lock, committed by
`atomic_write`'s temporary-file-then-`os.replace`. Because each operation is
targeted and idempotent, last-writer-wins across *different* flags is already
correct and no revision token or `If-Match` protocol is needed — explicitly out
of scope in [spec.md](spec.md). An entry naming a flag this build does not
declare is preserved verbatim through every write (DD-8): `mutate()`'s
read-modify-write applies the pure function to the *known* portion of the parsed
document and re-serializes the unknown portion unchanged, rather than
re-serializing only what the current build's schema recognizes.

**Absence is healthy; corruption is degraded — two different fallbacks, not one
(DD-2).** An absent document means every flag resolves from the deploy baseline
and the *very next* mutation creates the document — there is no "refuse until
provisioned" state on a fresh volume. A document that exists but fails to parse
means every flag still resolves from the deploy baseline, but every mutation is
refused, and the transition (a previously successful read followed by a failed
one) logs one coarse `WARNING` — correlation id, reason band, count of managed
flags whose runtime entry stopped applying, no member data — so the fallback is
observable without opening `/admin`. There is no reset command, no repair button
and no recovery subsystem for either case: both fall back to a state the system
already reaches by itself, and building machinery to reach it deliberately is
the scope creep this plan exists to refuse.

**Polling in the auth store, through a distinct refresh path, not a reused
`hydrate()` (DD-11).** `useAuthStore.hydrate()` is used for initial/startup
load and keeps its current behavior: any failure, including a transient one,
resolves to `{ user: null, status: "anon" }`, because a cold load against an
unreachable backend must not hang on "loading" forever. FR-009's background
poll instead calls a new `refreshSession()` on the same store: it issues the
same `GET /api/auth/me` request, but on a transient (non-401) failure it leaves
`user` and `status` untouched and surfaces nothing, while a 401 (`me()`
returning `null`) clears the session and stops the subscription exactly as
`hydrate()` already does. `startFlagRefresh()` wires a single named-constant
15-second interval plus `focus`/`visibilitychange` listeners while
`status === "authed"`, each calling `refreshSession()`, torn down otherwise.
`bindAdminSession` — the existing precedent for "start something once against
the process-global `queryClient`" — is wired at module scope in
`frontend/src/queryClient.ts:10`, not in `frontend/src/main.tsx` (campaign 1
found the prior draft's file citation was wrong); `startFlagRefresh()` is wired
there too, next to it, for the same reason: `main.tsx` never executes under
Vitest, so wiring the subscription only there would leave it uncovered.

**FR-009 is client-generic, and campaign 2 found the prior revision had only
built the web half of it.** The founder's brief asks that "an already-open
session" pick up a change, not "the web tab" specifically, so
`mobile/src/auth/SessionProvider.tsx` gets the same treatment as the web store:
a poll effect alongside the existing mount-time `probe()` call, using the same
named-constant 15-second interval and the identical transient-tolerant/
401-clearing split (DD-11) — a transient failure leaves the session and its
resolved flags untouched and the poll continues; a 401 signs out and stops the
poll exactly as an in-app 401 does today. The poll runs only while
`AppState.currentState === "active"`, mirroring the
`AppState.addEventListener("change", ...)`/`subscription.remove()` idiom already
used by `mobile/src/features/tasks/useClassificationQueue.ts` and
`mobile/src/features/agents/useAgentRunsFeed.ts`, and foregrounding the app
triggers an immediate refetch rather than waiting out the remainder of the
interval. `probe()` itself is unchanged, for the same cold-load reason
`hydrate()` is unchanged on web.

## Constitution check

- **Spec workflow**: [spec.md](spec.md) is current, its derived decisions
  DD-1…DD-11 are recorded in place — the last seven resolve campaign 1's
  product-decision-required verdict directly rather than deferring them — and no
  `NEEDS CLARIFICATION` marker remains.
- **Consent & Safety (Principle I)**: no AI, transcription or remote processing
  is involved and no consent surface changes. The stored document holds account
  IDs only; no email, display name, credential, token, session hash or member
  content enters it (FR-001, SC-007). Every operator mutation and every
  cohort-resolving read is now recorded content-free through the existing
  logger (FR-006, DD-10) — no new record type, schema or store. Manual
  acceptance uses purpose-seeded `@example.com` accounts with redaction required
  before evidence enters a PR.
- **Tests (Principle II)**: RED before GREEN in every lane of
  [tasks.md](tasks.md). Backend behaviour via pytest and `TestClient`; frontend
  via Vitest with fake timers. Edge cases covered explicitly: invalid payloads,
  refused flag names, idempotent repeats (including idempotent removal by
  unresolvable ID, DD-7), concurrent writers, a crash between write and rename,
  a malformed document versus an absent one (DD-2), an unresolvable cohort
  entry, purge scrubbing a cohort (DD-9), a transient poll failure and a 401
  during a poll (DD-11).
- **Contracts (Principle III)**: new `StrictBaseModel` request/response schemas in
  `backend/app/schemas/admin.py`, backend-first, with the frontend types mirrored
  by hand as every other route already is. The member-facing `feature_flags`
  **key set** is pinned unchanged by test (FR-008, SC-003), so neither client
  sees a shape change; Lane E changes only when web and mobile refresh that
  unchanged payload.
- **Observability (Principle IV)**: the existing 009 records already carry the
  correlation ID and the route **template**; the new routes inherit them, plus
  their own content-free mutation/aggregate-read records (DD-10), and add no new
  schema. Errors reach the operator with the correlation ID visible in state
  `F-10`, with named fallback copy when no response was received at all.
- **Mobile / resilience / performance**: `mobile/src/auth/SessionProvider.tsx`
  gains the FR-009 poll effect described above (Lane E); no other mobile surface
  changes, and FR-008's member-facing contract is unchanged on both clients.
  Polling is bounded on both web and mobile — stopped while hidden/backgrounded
  or signed out — and never surfaces an error for a request the member did not
  make.
- **Delivery boundary**: [tasks.md](tasks.md) is planning input only. Isolated
  worktree, TDD, independent verification, the ADR-0008 ASK landing, CI and the
  Fly release gates all remain authoritative.
- **Design citation**: this plan cites [design.md](design.md) and names the states
  each section realizes — `F-01`…`F-13` for the operator section, and design.md's
  "Propagation behaviour" contract for FR-009, which deliberately has no state of
  its own. Feature 009's `D-01`…`D-10` are unchanged and are re-asserted by
  regression test, not re-implemented.

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
└── review-history.md           # campaign 1 record and the owner-decision resolutions
```

### Source code (repository root)

```text
backend/
├── app/
│   ├── api/
│   │   ├── admin.py            # + five runtime-flag routes (four mutations +
│   │   │                       #   clear-override)
│   │   ├── auth.py             # _me_response resolves the two managed flags
│   │   │                       #   via the service; delivery_canary and
│   │   │                       #   external_agent_relay unchanged in the same
│   │   │                       #   dict
│   │   ├── dependencies.py     # + get_feature_flag_service; only
│   │   │                       #   voice_brain_dump_enabled reads it.
│   │   │                       #   external_agent_relay_enabled and
│   │   │                       #   admin_portal's private_flag_effective are
│   │   │                       #   untouched
│   │   └── tasks.py            # command_brain_dump_operation's direct
│   │                           #   voice_brain_dump_enabled(current_user,
│   │                           #   config) check resolves through the service
│   │                           #   instead (the third voice_brain_dump call
│   │                           #   site, missed by the prior revision)
│   ├── services/
│   │   ├── feature_flag_service.py   # NEW — overlay + effective resolution +
│   │   │                             #   content-free audit logging
│   │   └── account_service.py  # + one call: feature_flag_repo.scrub_user
│   │                           #   next to invite_repo.scrub_user, before
│   │                           #   user_repo.delete; purge_due_accounts'
│   │                           #   sweep loop gains per-account isolation
│   │                           #   (DD-13)
│   ├── repositories/
│   │   └── feature_flag.py     # NEW — locked read-modify-write, atomic
│   │                           #   replace, opaque-entry preservation,
│   │                           #   scrub_user(user_id) reaching every
│   │                           #   parseable entry and raising when degraded
│   │                           #   (DD-8, DD-9, DD-13)
│   ├── schemas/admin.py        # + runtime-flag request/response contracts
│   ├── core/config.py          # unchanged behaviour; one comment records the
│   │                           #   runtime-manageable set (two flags, not the
│   │                           #   full KNOWN_FEATURE_FLAGS)
│   └── container.py            # wire repository + service + UserRepository
│                                # (for describe()'s email resolution)
└── tests/                      # test_feature_flag_repository.py,
                                # test_feature_flag_service.py,
                                # test_admin_feature_flags_api.py,
                                # + assertions in test_account_service.py and
                                # test_auth_routes.py

frontend/
└── src/
    ├── api/{adminTypes.ts, client.ts, adminHooks.ts}
    ├── features/admin/AdminFeatureFlagsSection.tsx   # NEW — F-01…F-13
    ├── features/admin/AdminPage.tsx                  # mounts the section
    ├── stores/authStore.ts                           # + refreshSession(),
    │                                                  #   startFlagRefresh()
    ├── queryClient.ts                                # starts the subscription,
    │                                                  #   next to bindAdminSession
    ├── pages/PrivacyPolicyPage.tsx                    # + one sentence under
    │                                                  #   "How long we keep it"
    │                                                  #   naming the runtime
    │                                                  #   document, + LAST_UPDATED
    │                                                  #   bump (DD-9)
    └── **/__tests__/

mobile/
└── src/
    └── auth/SessionProvider.tsx   # + poll effect: 15-second interval plus
                                    #   AppState listener, same DD-11 split as
                                    #   web; probe() itself unchanged (FR-009,
                                    #   Lane E)

docs/decisions/0018-runtime-feature-flag-overlay.md   # NEW ADR (see below)
docs/data-retention.md                                # + one retention-table
                                                        #   row, one export
                                                        #   exclusion, and one
                                                        #   amendment to the
                                                        #   existing Admin
                                                        #   access records
                                                        #   row/section (DD-9)
docs/auth.md                                           # + one bullet in the
                                                        #   operator-authority
                                                        #   list (DD-9)
```

**Structure decision**: the backend change stays inside the existing
`api → services → repositories` layering wired in `container.py`; the new
repository is a sibling of `repositories/session.py`, and the new service a
sibling of `services/admin_service.py`. The frontend change stays inside
`features/admin/` plus the one store that owns session state, plus the one
sentence DD-9 adds to the privacy-policy page. The mobile change is the single
`SessionProvider.tsx` poll effect FR-009's mobile sublane requires — no other
`mobile/` file changes. `scripts/` and `.github/` are deliberately absent from
this tree; the documentation edits are exactly the new ADR, the three named
edits inside `docs/data-retention.md`, the one bullet in `docs/auth.md`, and
the one sentence in `PrivacyPolicyPage.tsx` — DD-9 names all four, and no
broader privacy-summary rewrite is in scope.

## Changed surfaces

| File | Change |
| --- | --- |
| `backend/app/repositories/feature_flag.py` | **NEW** `FeatureFlagOverrideRepository`: reads/writes one document under `{data_dir}/feature-flags/runtime.json`; `read()` returns the parsed overlay, distinguishing an **absent** document (healthy, empty overlay) from an **unreadable/malformed** one (degraded marker) (DD-2); `mutate()` takes a pure function, holds an `fcntl.flock` on `runtime.json.lock`, re-reads under the lock, applies the function to the known portion, re-serializes the unknown portion unchanged (DD-8), and commits with `file_ops.atomic_write`; `clear(flag)` removes a flag's entry entirely (DD-3); `scrub_user(user_id)` removes one account ID from every managed flag's cohort and from a `selected_users` array inside any other parseable entry, declared or not, raising rather than silently skipping when the document is degraded; called from `AccountService.purge_account` before its destructive delete step (DD-9, DD-13) |
| `backend/app/services/feature_flag_service.py` | **NEW** `FeatureFlagService`: `effective_flags(user)`, `is_effective(name, user)`, `describe()` (the operator view: per managed flag its mode, source, deploy-default state, and cohort — resolved via a plain `UserRepository.get_by_id` read, not `AdminService.find_account`), `set_mode`, `clear_override`, `add_selected_user`, `remove_selected_user`. Delegates to `config.feature_flags` for `delivery_canary`, `external_agent_relay`, and any managed flag with no runtime entry; refuses any name outside the two-flag managed set (FR-002); refuses every mutation while degraded (FR-004); emits one content-free log record per mutation and one aggregate record per `describe()` call that resolves cohort emails (DD-10); holds a cache invalidated by the document's `st_mtime_ns`/`st_size` so a mutation is visible to the next evaluation (FR-005) |
| `backend/app/schemas/admin.py` | + `AdminFeatureFlagMode` (`off`/`on`/`selected_users`), `AdminFeatureFlagSelectedUser` (`account_id`, `email: str \| None`), `AdminFeatureFlagState` (`name`, `override_mode: AdminFeatureFlagMode \| None`, `source` (`runtime`/`deploy_default`), `deploy_default_state: AdminFeatureFlagMode` (always present, even when `source` is `runtime`), `selected_users` — DD-3's three-field split, not a single collapsed `mode`), `AdminFeatureFlagsResponse` (`degraded`, `flags`), `AdminFeatureFlagModeRequest`, `AdminFeatureFlagSelectedUserRequest` (exactly one of `account_id`/`email`, mirroring `AdminAccountLookupRequest`) |
| `backend/app/api/admin.py` | + `GET /admin/feature-flags`, `PUT /admin/feature-flags/{flag}/mode`, `DELETE /admin/feature-flags/{flag}` (clear override — deletes the flag's entire runtime entry, including any retained SELECTED_USERS cohort, unlike a mode change to OFF/ON which retains it, DD-3/DD-6), `POST /admin/feature-flags/{flag}/selected-users`, `DELETE /admin/feature-flags/{flag}/selected-users/{account_id}` — every one `Depends(require_admin_portal_enabled)`, every one returning the full authoritative post-mutation state (FR-006, FR-010) |
| `backend/app/api/dependencies.py` | **ASK path.** + `get_feature_flag_service`; `voice_brain_dump_enabled` (`:278`) resolves through the service instead of `config.feature_flags.effective_flags`. `external_agent_relay_enabled` (`:313`), `require_external_agent_relay_enabled`, `require_operator` and `require_admin_portal_enabled` are **not** touched — neither `external_agent_relay` nor `admin_portal` is a managed flag, and the relay's existing per-request gate stays exactly as it is (FR-006, FR-008, DD-1) |
| `backend/app/api/tasks.py` | **ASK path.** `command_brain_dump_operation`'s direct `voice_brain_dump_enabled(current_user, config)` check (`:340-346`), gating the brain-dump command route's `commit`, `retry` and `review_provisional` actions, resolves through the service instead of reading `config.feature_flags` directly — the third `voice_brain_dump` call site, missing from the prior revision's own table (FR-008) |
| `backend/app/api/auth.py` | **ASK path.** `_me_response` (`:50`) resolves the two managed flags' values through the service inside the same `feature_flags` dict; `delivery_canary` and `external_agent_relay` keep resolving through `config.feature_flags.effective_flags` in that call, unchanged. Covers `/auth/me`, `/auth/login` and `/auth/signup` in one place. The key set is unchanged and pinned by test (FR-008) |
| `backend/app/container.py` | wire `FeatureFlagOverrideRepository`, `FeatureFlagService` (with `UserRepository` for cohort-email resolution), and pass the `User` that `_voice_enabled_for_owner` (`:293`) already fetches. `_build_agent_secret_box` (`:130`) is **not** touched: `external_agent_relay` remains environment-only because a live flag override could not provision or replace its startup secret-box prerequisite; its existing request-time gates remain untouched too (DD-1) |
| `backend/app/core/config.py` | no behaviour change. One comment records that `voice_brain_dump` and `mobile_task_classification` are the runtime-manageable subset of `KNOWN_FEATURE_FLAGS`, and that `delivery_canary`/`external_agent_relay` are deliberately not (DD-1) |
| `backend/app/services/account_service.py` | + one call in `purge_account` (`:400`, next to `self.invite_repo.scrub_user(user_id)`, before `self.user_repo.delete(user_id)`): `self.feature_flag_repo.scrub_user(user_id)`, which now raises rather than completing when the runtime document is degraded, aborting the purge before the account record is deleted; `purge_due_accounts`'s sweep loop (`:363-375`) gains per-account failure isolation so one corrupt document does not block every other account's due purge in the same pass (DD-9, DD-13) |
| `frontend/src/api/adminTypes.ts` | mirrored types for the contracts above |
| `frontend/src/api/client.ts` | `getAdminFeatureFlags`, `setAdminFeatureFlagMode`, `clearAdminFeatureFlagOverride`, `addAdminFeatureFlagUser`, `removeAdminFeatureFlagUser` |
| `frontend/src/api/adminHooks.ts` | + `useAdminFeatureFlags` under the existing owner-scoped `adminKeys`, so `purgeAdminRecords`/`bindAdminSession` already cover it. Unlike `useAdminStatus` this query **is** refetchable, because flag state does drift — but only from `AdminPage`, never shell-wide (009-FR-011 preserved) |
| `frontend/src/features/admin/AdminFeatureFlagsSection.tsx` | **NEW** — realizes `F-01`…`F-13` |
| `frontend/src/features/admin/AdminPage.tsx` | mounts the section inside the operator-confirmed branch only (design.md: never inside `D-01`, `D-08` or `D-09`) |
| `frontend/src/stores/authStore.ts` | **ASK path.** + `refreshSession()` (transient failure preserves `user`/`status`; a 401 clears exactly as `hydrate()` does) and `startFlagRefresh()`/teardown: a 15-second interval plus `focus` and `visibilitychange` listeners while `status === "authed"`, each calling `refreshSession()`; nothing while anonymous or hidden. `hydrate()` itself is unchanged (DD-11, FR-009) |
| `frontend/src/queryClient.ts` | starts `startFlagRefresh()` once, next to the existing `bindAdminSession(queryClient)` call at module scope (`:10`) — corrected from the prior draft's `main.tsx` citation, which does not contain that wiring |
| `frontend/src/pages/PrivacyPolicyPage.tsx` | + one sentence under "How long we keep it" naming the runtime rollout document (holds only the account id, scrubbed on purge, excluded from data export) — the one authorized text-only addition DD-9 permits, plus the routine `LAST_UPDATED` bump that edit requires. No other privacy-policy surface changes |
| `mobile/src/auth/SessionProvider.tsx` | **NEW poll effect**, alongside the existing mount-time `probe()` call (`:269`): a single named-constant 15-second interval (the same value as web's) plus an `AppState` listener, driving a poll-specific refetch while signed in and the app is active; the same DD-11 transient-tolerant/401-clearing split as web; `probe()` itself unchanged (FR-009, Lane E) |
| `docs/decisions/0018-runtime-feature-flag-overlay.md` | **NEW ADR** — the per-flag precedence rule, the two-flag managed set and why the other two `KNOWN_FEATURE_FLAGS` entries are excluded, the audit obligation (DD-10), and the purge obligation (DD-9); see below |
| `docs/data-retention.md` | + one row in the retention table (mirroring the existing Invites row) naming the runtime flag document, one line in the export-exclusion list naming the same document, and an amendment to the existing **Admin access records** row/section naming this feature's own mutation and aggregate cohort-resolution log records under the identical disposition already decided for feature 009 (platform log window, excluded from export, not reached by purge) — three edits, not one, all named by DD-9. No other line in this file changes |
| `docs/auth.md` | + one bullet in the existing operator-authority list naming the new runtime-flag-management authority, pointing at ADR-0018 (G3). No other line in this file changes (DD-9, FR-007) |

Nothing else is edited beyond the rows above. In particular: no file under
`.github/` or `scripts/`, no `.env*` file, no `mobile/` file other than
`SessionProvider.tsx`'s poll effect, and no privacy-policy surface beyond the
one authorized sentence in `PrivacyPolicyPage.tsx` DD-9 names.

## Key decisions

1. **Two managed flags, not the full `KNOWN_FEATURE_FLAGS` set.** (DD-1.)
   `admin_portal` stays excluded as before (self-lockout). `delivery_canary` is
   newly excluded because it is a release-smoke input, not a member-capability
   flag, and runtime-managing it would durably break the production deploy gate.
   `external_agent_relay` is newly excluded too, but not because it lacks a
   per-request gate — it already has one (`external_agent_relay_enabled`, wired
   into eight routes in `backend/app/api/agents.py`), and campaign 2 found
   campaign 1's claim otherwise was wrong. The exclusion holds because
   `_build_agent_secret_box` makes a startup-time, construction-only decision
   about the relay's secret box that no request-time re-evaluation can
   retroactively satisfy once the process has started, and this feature does not
   rebuild that construction step as a live one. This is also what lets this
   feature leave the deploy workflow entirely alone.
2. **Per-flag overlay, never a merge — plus an explicit clear that deletes the
   whole entry, cohort included.** (DD-3.) A flag with a runtime entry answers
   from that entry alone. Blending would make OFF not mean off, and would make
   SC-003's fallback claim untestable. Clearing an entry (not just setting it to
   match the deploy default) is a distinct, named operation, because setting a
   mode is still a runtime override — only deleting the entry restores actual
   environment inheritance, including `internal`. Unlike a mode change to OFF or
   ON, which retains a non-empty SELECTED_USERS cohort (DD-6), clearing deletes
   the cohort along with the rest of the entry: a subsequent read reports no
   override and an empty cohort, exactly as if the flag had never been set
   (campaign-2 correction — the prior revision wrongly claimed the cohort
   survives a clear).
3. **The environment string keeps its job, for the flags it still governs.**
   (DD-4.) It is the baseline a fresh volume starts from, the floor a rollback
   lands on, and — for `delivery_canary` and `external_agent_relay` specifically
   — the *only* source of truth, because this feature never gives either flag a
   runtime entry to overlay it with. No workflow, script or CI file is touched.
4. **Rollback safety is structural, not procedural.** A pre-010 image has no code
   that reads `feature-flags/runtime.json`, so the document is inert to it and it
   resolves flags from the environment exactly as it did before. That is one
   half of SC-003; the other half is that the current image falls back to the
   environment when the document is absent — *and* the first mutation against an
   absent document creates it rather than requiring a provisioning step (DD-2).
   Those are the whole rollback obligation — no further rollback machinery is in
   scope.
5. **Targeted idempotent operations instead of a document PUT.** Correct under
   concurrency without a revision token, and it removes the whole class of
   "operator saved a stale snapshot" bugs. Removal is idempotent by ID
   regardless of whether the ID currently resolves (DD-7); add is not, because
   an add is only ever meant to name an account that exists right now.
6. **`flock` plus atomic replace, not a lock service.** Justified by a stated,
   checkable assumption: one backend process on one machine
   (`fly.backend.toml`, `min_machines_running = 1`). The assumption is written in
   [spec.md](spec.md) so that scaling out is a decision someone must make
   deliberately rather than a silent correctness loss.
7. **Absence is healthy, corruption is degraded — and there is still no reset
   lever.** (FR-004, DD-2.) Falling back to the deploy-staged baseline when the
   document cannot be read falls back to the last audited state; refusing writes
   in that case means a document nobody could parse is never overwritten with a
   half-known one. An *absent* document is not that case: it is the ordinary
   starting state of a fresh volume, and refusing the first mutation against it
   would make the feature unusable on day one. A CLI reset command was proposed
   by an earlier planning pass and is deliberately cut: it would be a new
   operational surface to build, test and document in order to reach a state the
   system already reaches by itself.
8. **A purged account's ID is scrubbed from every parseable cohort, mirroring
   the repository's own precedent — and a degraded store halts the purge rather
   than silently skipping the scrub.** (DD-9, DD-13.) `InviteRepository.
   scrub_user` already answers the equivalent question for a comparable
   non-owner-scoped durable file, with the documented rationale "GDPR erasure
   support". `AccountService.purge_account`'s "erase every trace" contract would
   otherwise become false the moment this feature's store exists — and,
   campaign 2 found, would stay false for an ID orphaned inside an unmanaged or
   undeclared flag's entry if the scrub were scoped to only the two managed
   flags, since DD-8 otherwise carries such an entry through every write
   untouched. When the document cannot be parsed at all, `scrub_user` raises
   instead of pretending to have scrubbed content it never read, so
   `purge_account` aborts before deleting the account record — the account is
   retained past its 14-day promise until the document is repaired and a
   retried purge succeeds, and the maintenance sweep isolates that one
   account's failure so it does not block every other account's due purge in
   the same pass. One repository method, one purge call, four named
   documentation edits (a retention-table row, an export-exclusion line, an
   Admin-access-records amendment, and one `docs/auth.md` bullet) — narrower
   than a full privacy-surface reopen, and it is the whole DD-9/DD-13
   obligation.
9. **Two distinct auth-store code paths for two distinct failure tolerances.**
   (DD-11.) Initial hydration must fail closed (anon) so a cold load against an
   unreachable backend does not hang forever. Background refresh must fail open
   (keep the session) so ordinary network noise does not sign a member out. One
   function cannot honor both, so the poll calls a new, narrow `refreshSession()`
   rather than reusing `hydrate()` — the blast radius stays *when* a request is
   made and how its failure is handled, not the request or its payload.
10. **Every operator mutation and every cohort-resolving read gets one
    content-free log line.** (DD-10.) `AdminService.find_account`'s "Admin
    lookup" record does not fire for a flag mutation, and using it for cohort
    rendering would misattribute a lookup the operator never performed. This
    feature's own log lines, in the same content-free shape 009 already uses,
    close that gap without a new store, schema or history surface.
11. **One ADR, and it is not optional.** ADR-0017 states "no admin data store"
    and "anything beyond point 1 requires its own ADR". This feature adds a
    durable operator-owned document plus one narrowly-scoped purge integration
    and one narrowly-scoped audit obligation, so proceeding without a record
    would silently contradict an accepted decision — the exact failure ADR-0017
    was written to prevent. ADR-0018 narrows it explicitly, records the per-flag
    precedence rule, the two-flag managed set and why the other two
    `KNOWN_FEATURE_FLAGS` entries are excluded, the purge and audit obligations
    (DD-9, DD-10), re-states that flags remain exposure control and that the
    operator allow-list stays deployment configuration, and names the
    single-process serialization assumption. It is a decision record, not a new
    subsystem.

## Landing (ADR-0008 ASK)

**Class: ASK (high risk).** Triggers, any one sufficient:

- it edits `backend/app/api/dependencies.py`, an explicit ASK exact path in
  `scripts/classify_path_risk.py`;
- it edits `backend/app/api/auth.py` and `frontend/src/stores/authStore.ts`, both
  carrying the `auth` token that classifier treats as ASK;
- it introduces a new durable persistence surface whose contents change what
  members can reach.

ADR-0012 derives `high` from any ASK surface, so the review campaign runs at high
risk and requires a recorded human sign-off in addition to the automated lenses.

Consequences, all mandatory:

- **No automatic promotion.** This must not land through the PR-less
  verified-trunk deploy-key path reserved for SHIP/SHOW.
- **Explicit recorded approval** from the maintainer before landing.
- **Green required CI on the exact SHA being landed** — not an ancestor, not a
  rebased equivalent.
- **A short, audited, temporary ruleset intervention**, recording who, why, and
  when the ruleset was re-enabled.

**Rollback.** Ordered, each step independently safe:

1. **Fastest, no deploy:** an operator sets the affected flag back through the
   portal, or clears its override entirely. Reversible in one click, and the
   effect reaches open sessions within about fifteen seconds. This is the
   intended rollback path and the reason no reset command is needed.
2. **Image rollback:** restoring the previous image is a no-op for flag
   resolution — the document is inert to a pre-010 build (key decision 4,
   SC-003). Nothing must be un-staged, and the existing deploy-workflow
   flag-staging contract is untouched and keeps working for every flag,
   including the two this feature never gives a runtime entry.
3. **Code revert:** leaves the document on the volume as an unread file. A later
   re-land picks it up again; deleting the file on the volume is an ordinary
   operational action, not a feature.
4. **Nothing here is irreversible.** Every operation this feature adds has an
   inverse. That is *not* a reason to lower the class — the ASK triggers above are
   about the surfaces touched — but it does mean the containment story has no
   dead end.

## Risks

- **Self-inflicted outage by turning a flag off.** An operator can make
  `voice_brain_dump` disappear for everyone in one click. Accepted: that is the
  requested capability, the change is reversible by its inverse, and flags are
  exposure control — no data is lost and no session is invalidated. Mitigation is
  the source note in `F-02` (so an override is never mistaken for the deploy
  default) plus the confirmation step FR-010 now requires specifically for this
  transition (design.md Interaction notes).
- **The single-process assumption.** `flock` plus atomic replace is correct for
  one machine. Fly volumes are single-attach and per-machine, not shared storage
  — if `min_machines_running` is ever raised, each additional machine gets its
  own volume and its own `runtime.json`, not a second writer racing the first
  over one file. There is no interleaving or lost-update failure mode to solve;
  the failure mode is divergence — each machine's flag document drifts from the
  others independently, and an operator's change lands on only whichever machine
  served the write. Recorded in [spec.md](spec.md) Assumptions and in ADR-0018 so
  the next person to scale out meets it; not solved here, because solving it
  would mean the shared/replicated storage or distributed coordination the
  founder's slice excludes.
- **Polling cost and log noise.** One authenticated GET per open tab per 15
  seconds. Bounded by stopping while hidden or signed out; `/api/auth/me` is a
  cheap session read with no repository fan-out.
- **No bound on cohort size.** Cohorts are built one exact-match add at a time
  with no listing or bulk-import path, and are expected to stay small; the
  per-read email-resolution fan-out and the operator screen are not proven
  against an unbounded cohort. Named explicitly in spec.md Assumptions rather
  than silently omitted; bounding it is a follow-up if it ever matters.
- **Scope creep from reviewer speculation.** The Out of Scope section in
  [spec.md](spec.md) is the boundary, and it names the specific proposals an
  earlier pass invented: a reset command, a cohort sweep beyond the one purge
  integration DD-9 requires, a privacy-summary rewrite, a new audit schema,
  deploy byte-equivalence assertions and generalized recovery machinery. A
  finding proposing any of these — or percentages, segments, schedules, an audit
  store, a revision protocol or a user directory — is out of scope unless a
  failing test proves it necessary to satisfy a requirement already written
  down. **Reviewer suggestions cannot raise the 10-FR / 8-SC cap or reopen the
  frozen slice; the owner decisions in spec.md's DD table are the only campaign-1
  reopening, and they are now closed.**

## Complexity tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| A new persistence surface (`repositories/feature_flag.py`) in a feature whose stated ideal is "reuse, do not invent" | FR-001 and FR-005 require durability on the data volume, and no existing repository owns deployment-wide configuration — every one is owner-scoped | Storing overrides in an existing store would give a *global* record an owner-scoped home, breaking the ADR-0001 invariant every other repository upholds. Keeping them in memory fails FR-005 on the first restart |
| Two sources of truth for one flag (environment and runtime) | DD-4 requires the environment string to remain the baseline and the rollback floor, so it cannot simply be replaced | Migrating the environment configuration into the store would make a rollback lose the rollout entirely and would force the deploy-workflow redesign [spec.md](spec.md) rules out. The precedence rule is one sentence (DD-3) and is pinned by SC-003 |
| One purge call and four named documentation edits, reopening a line the founder's slice had excluded | DD-9/DD-13: the repository's own erasure precedent (`InviteRepository.scrub_user`) and `AccountService.purge_account`'s stated "erase every trace" contract both point the same direction, and campaign 1 found the alternative reasoning did not transfer; campaign 2 widened the scrub to every parseable entry and added the degraded-store halt-and-retry rule | Leaving the ID in place would make `purge_account`'s docstring false and would need its own accepted-residual argument that the repository's own precedent already contradicts |
| A new ADR in a feature that touches several small product-facing surfaces (`docs/data-retention.md`, `docs/auth.md`, the privacy-policy page, and a mobile session provider) | ADR-0017 forbids an admin data store and requires an ADR for anything beyond its point 1 | Not writing it leaves an accepted record silently contradicted. Writing it is one file, plus the small, individually named edits DD-9 and FR-009 require elsewhere |
