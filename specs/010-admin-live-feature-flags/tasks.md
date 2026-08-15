# Tasks: Live Feature-Flag Management in the Admin Portal

Grouped into **independently acceptable lanes**, each with its own RED → GREEN
ordering and its own evidence checkpoint. See [plan.md](plan.md) for why each
exists, [design.md](design.md) for the `F-01`…`F-13` states lanes D and E
realize, and [spec.md](spec.md) for the derived decisions DD-1…DD-13.

This list covers **exactly** the ten functional requirements and eight success
criteria in [spec.md](spec.md), as revised after campaign 2 — see
[review-history.md](review-history.md) for the full record and
[analysis.md](analysis.md) for the per-requirement trace. There is no lane for a
reset command, a cohort sweep beyond the one purge integration DD-9 requires, a
privacy-policy rewrite, a new audit schema/store/UI, or a deploy/CI/script
change — all are out of scope by spec.md, and a task that appeared for one of
them would be the scope creep the plan's Risks section refuses.

Everything here is **runtime-neutral**: no task requires Hermes, a Kanban
runtime, or any other control plane (ADR-0010, ADR-0011).

**Nothing is ticked, and that is accurate.** No lane has been started: this run
was explicitly scoped to correcting planning artifacts and forbidden to touch
product code or tests. Tick a box only when the tree actually contains the work
and its checkpoint has been run green.

**Lane dependencies, stated rather than assumed.** Lane B needs lane A's
repository. Lane C needs lane B's service. Lanes D, E and F need C's routes or
B's service and are otherwise independent of each other. Lane G is documentation
and can run at any point. Lane H is last by construction.

Every test named below must carry the **feature-qualified** requirement id
(`010-FR-001`, or `010_FR_001` in a Python name) in its function name, docstring
or Allure story, so
`python3 scripts/check_requirement_coverage.py specs/010-admin-live-feature-flags`
can trace it. A bare `FR-001` is rejected. Every test must also satisfy the
Allure taxonomy (`epic`/`feature`/`story`, a human title, at least one named
step) per `docs/test-allure-taxonomy.md`.

## Lane A — the durable runtime store (010-FR-001, 010-FR-004, 010-FR-005)

- [ ] **A1** RED: `backend/tests/test_feature_flag_repository.py` — a document
  written through the repository round-trips its modes and cohorts; a
  never-yet-written data directory reports the **healthy** empty overlay
  (DD-2) rather than raising or reporting degraded; the file lands under
  `{data_dir}/feature-flags/runtime.json`. This is a unit-level round-trip
  check on the repository object; the process-restart half of 010-SC-001 is
  proven at the application boundary by **C7**, not here (campaign-1
  testability finding: a fresh repository instance does not exercise startup
  wiring). *(010-FR-001, 010-FR-005)*
- [ ] **A2** RED: same module — **atomicity and idempotence**: a mutation that
  raises between the temporary write and the rename leaves the previous document
  byte-identical and readable; repeating any targeted mutation leaves the
  document byte-identical and still reports success; no partially written
  document is ever observable. *(010-FR-005, 010-SC-005)*
- [ ] **A3** RED: same module — **concurrency**: N threads each applying a
  targeted mutation to a *different* flag all survive, and N threads adding
  *different* accounts to one flag all survive; assert against the document on
  disk, not against a return value. *(010-FR-005, 010-SC-005)*
- [ ] **A4** RED: same module — **healthy-absence vs. degraded-corruption, and
  forward compatibility (DD-2, DD-8)**: an absent document reads as the healthy
  empty overlay and a mutation against it succeeds and creates the file; a
  truncated document, a syntactically invalid document and a document whose top
  level is not an object each read as the **degraded** marker rather than
  raising, and a mutation attempted against any of them writes nothing and
  leaves the bytes unchanged (or leaves nothing on disk, for the truncated
  case); the healthy → degraded transition emits exactly one coarse `WARNING`
  log record and a second consecutive degraded read emits none; an entry naming
  a flag the build does not declare, an entry naming a flag this build declares
  but does not manage, and an unrecognized field inside an otherwise-known
  managed-flag entry are each ignored for evaluation and for `describe()`, but a
  subsequent targeted mutation to a *different*, known flag leaves each of them
  present and byte-identical afterward; a managed flag's entry whose `mode`
  value is outside `off`/`on`/`selected_users` is different from all three —
  malformed content in a recognized field, not forward compatibility — and
  reads as the **degraded** marker exactly like a syntactically invalid
  document, not as an ignored-and-preserved unknown entry. Separately from
  malformed *content*, an I/O failure on the read itself — inject an `OSError`
  and a `PermissionError` from the file read, not from JSON parsing — reads as
  the same **degraded** marker rather than raising or crashing the caller, a
  mutation attempted while the read fails writes nothing and leaves the
  existing document's bytes unchanged, and each I/O-failure case emits the
  same one coarse `WARNING` log record on the transition and none on a
  repeated consecutive failure, exactly like the malformed-content cases
  above. Assert that the WARNING carries only the correlation id, a coarse
  reason band and the count of overrides that stopped applying, and contains
  no account id, email, display name or member content.
  *(010-FR-004, 010-SC-005, 010-SC-008, DD-8)*
- [ ] **A5** RED: same module — **clearing an override**: `clear(flag)` removes
  a flag's entry entirely; evaluating afterward matches the environment-only
  answer exactly (including `internal`); clearing a flag with no entry is a
  no-op that still reports success; clearing does not touch any other flag's
  entry or an unknown entry preserved under DD-8. *(010-FR-003, 010-FR-005,
  DD-3)*
- [ ] **A6** RED: same module — **purge scrub, widened to every parseable
  cohort (DD-9, campaign-2 correction)**: `scrub_user(account_id)` removes that
  account ID from every managed flag's `selected_users` set **and** from a
  `selected_users` array reachable inside any other parseable entry — one
  naming a flag this build does not declare, and one naming a flag this build
  declares but does not manage — while leaving that entry's other content and
  shape otherwise byte-identical; this is the one narrow, named exception to
  DD-8's opaque byte-preservation, scoped to this one field for this one ID and
  nothing else in the entry. It leaves every other stored ID untouched and is
  idempotent — calling it again, or calling it for an ID that was never
  present, still succeeds and changes nothing on disk. Separately: called
  against a **degraded** document (unreadable or malformed), `scrub_user`
  raises rather than silently completing or silently skipping — it cannot
  honor the widened scrub against content it could not parse — so the caller
  (Lane C's `AccountService.purge_account`) can enforce DD-13's fail-closed
  ordering. *(010-FR-001, 010-FR-007, DD-8, DD-9, DD-13)*
- [ ] **A7** RED: same module — **document-shape privacy**: the repository's
  write path has no field, parameter or code path that can place an email
  address, display name, credential, token or session-hash fragment into the
  document — asserted at the schema/shape level (the pure mutation function's
  signature and the on-disk JSON's key set admit only flag names, modes and
  account-ID arrays). The *request-to-document* sentinel proof — that a real
  add call carrying a distinctive display name never reaches the file — is
  **C8**, not here, because it needs the real account-lookup path Lane C
  introduces (campaign-1 testability finding: A5 as originally scoped proved
  only that the test itself supplied no PII). *(010-FR-001, 010-SC-007)*
- [ ] **A8** GREEN: `backend/app/repositories/feature_flag.py` —
  `FeatureFlagOverrideRepository` with `read()`, `mutate(fn)`, `clear(flag)` and
  `scrub_user(account_id)`. `mutate` and `clear` take an advisory `fcntl.flock`
  on `runtime.json.lock`, re-read under the lock, apply the pure function to the
  known portion of the parsed document while carrying the unknown portion
  through unchanged (DD-8), and commit through `app.utils.file_ops.atomic_write`.
  `scrub_user` walks every parseable entry's `selected_users` array, known or
  unknown, removing the ID from each while preserving everything else about
  that entry (DD-9), and raises when `read()` reports degraded rather than
  attempting a partial scrub (DD-13). Make A1–A7 pass.

*Checkpoint: `cd backend && pytest tests/test_feature_flag_repository.py`.*

## Lane B — the overlay and effective resolution (010-FR-002, 003, 004, 005, 008)

- [ ] **B1** RED: `backend/tests/test_feature_flag_service.py` — **fallback
  parity**: with no runtime document, `effective_flags(user)` equals
  `config.feature_flags.effective_flags(user.email)` for every combination of
  `off`/`internal`/`on` across all four `KNOWN_FEATURE_FLAGS`, for an
  internal-cohort user and a non-cohort user — including `delivery_canary` and
  `external_agent_relay`, which must match the environment answer
  unconditionally because they never have a runtime entry (DD-1). This is the
  requirement that makes the overlay removable. *(010-FR-003, 010-FR-008,
  010-SC-003)*
- [ ] **B2** RED: same module — **rollback equivalence**: evaluating with the
  runtime store unavailable (the code path a pre-010 image takes) against a data
  directory that *does* hold a runtime document yields exactly the
  environment-only result and raises nothing. This plus B1 is the entire rollback
  obligation; nothing further is built for it. *(010-SC-003)*
- [ ] **B3** RED: same module — **per-flag overlay, never a merge**: for each of
  the two managed flags, a flag at runtime `off` is effective for nobody even
  when the environment says `on`; a flag at runtime `on` is effective for
  everyone even when the environment says `off`; a flag at runtime
  `selected_users` is effective exactly for the account IDs in its set and for
  nobody else, including for a user who is in the environment `internal`
  cohort; and an account ID in a set that belongs to no account makes the flag
  effective for nobody. *(010-FR-003, 010-FR-007)*
- [ ] **B4** RED: same module — **scope refusal**: `set_mode`, `clear_override`,
  `add_selected_user` and `remove_selected_user` refuse `admin_portal`,
  `delivery_canary`, `external_agent_relay`, any other `PRIVATE_FEATURE_FLAGS`
  entry, and an undeclared name; nothing is written; and each refused flag's
  effective value stays exactly what `config.feature_flags.effective_flags` /
  `private_flag_effective` returns. *(010-FR-002, 010-FR-006, 010-SC-006)*
- [ ] **B5** RED: same module — **cohort retention across mode changes
  (DD-6)**: a flag's `selected_users` set survives `set_mode` to `off` and to
  `on` and is exactly restored on a later `set_mode` back to `selected_users`;
  `add_selected_user`/`remove_selected_user` against a flag currently `off` or
  `on` are refused without changing the cohort; `describe()` reports the
  retained count while the flag is `off` or `on`. *(010-FR-005, 010-FR-010,
  DD-6)*
- [ ] **B6** RED: same module — **cache invalidation**: a mutation is visible to
  the very next `effective_flags` call, and a document replaced underneath the
  service (same size, new modification time) is picked up rather than served from
  cache. *(010-FR-005)*
- [ ] **B7** RED: same module — **degraded behaviour**: with an unreadable
  document, `effective_flags` returns the environment baseline, `describe()`
  reports `degraded`, and every mutation is refused with the document's bytes
  unchanged; with an absent document, `describe()` reports healthy, not
  degraded (DD-2). *(010-FR-004, 010-SC-008)*
- [ ] **B8** RED: same module — **call-site coverage, narrowed to the two
  managed flags (DD-1), and exhaustive for all three `voice_brain_dump` call
  sites (campaign-2 addition)**: with a runtime `off` override, `voice_brain_dump_
  enabled` 404s the voice-capture gate even when the environment says `on`;
  with a runtime `selected_users` override naming the caller, it admits even
  when the environment says `off`. The same two assertions repeat against the
  third call site — the direct `voice_brain_dump_enabled(current_user, config)`
  check inside `command_brain_dump_operation` (`backend/app/api/tasks.py:340-346`)
  that gates the brain-dump command route's `commit`, `retry` and
  `review_provisional` actions — a call site campaign 2 found missing from the
  prior revision's own changed-surface table. `external_agent_relay_enabled` is
  deliberately **not** asserted here — it is not wired to the service (plan.md,
  DD-1) — and a companion assertion confirms it keeps reading
  `config.feature_flags.effective_flags` directly and is unaffected by any
  runtime override. Proves no managed-flag call site was missed and no
  unmanaged one was accidentally touched. *(010-FR-008)*
- [ ] **B8a** RED: same module — **consent-boundary regression (FR-008
  campaign-2 addition)**: a caller newly admitted to voice capture by a
  `selected_users` cohort still fails visibly when attempting to capture
  without explicit per-recording consent — a runtime override narrows only the
  capture gate, it does not move the ADR-0002/constitution Principle I consent
  boundary; a caller under a runtime `off` override on `voice_brain_dump` still
  reaches the `_VOICE_OFF_REACHABLE_ACTIONS` owner-authority voice routes
  (withdraw consent, cancel, delete raw audio) exactly as today, proving the
  override narrows exposure, not data-deletion or consent-withdrawal
  authority. *(010-FR-008)*
- [ ] **B9** GREEN: `backend/app/services/feature_flag_service.py` —
  `FeatureFlagService` with `effective_flags`, `is_effective`, `describe`,
  `set_mode`, `clear_override`, `add_selected_user`, `remove_selected_user`,
  delegating to `config.feature_flags` for `delivery_canary`,
  `external_agent_relay`, and any managed flag with no runtime entry; caching on
  the document's `st_mtime_ns`/`st_size`; emitting one content-free log record
  per mutation (DD-10). Make B1–B8a pass.
- [ ] **B10** GREEN: **route the three `voice_brain_dump` call sites and the one
  `mobile_task_classification` call site through the resolver** —
  `backend/app/container.py` builds the repository and service (with
  `UserRepository` for later cohort-email resolution) and passes the `User`
  that `_voice_enabled_for_owner` (`container.py:293`) already fetches;
  `backend/app/api/dependencies.py` gains `get_feature_flag_service` and routes
  `voice_brain_dump_enabled` (`:278`) through it; `backend/app/api/tasks.py`'s
  `command_brain_dump_operation` gate (`:340-346`) resolves through the same
  service call rather than reading `config.feature_flags` directly;
  `backend/app/api/auth.py` resolves the two managed flags inside
  `_me_response`'s (`:50`) `feature_flags` dict through it, leaving
  `delivery_canary`/`external_agent_relay` on `config.feature_flags.effective_flags`
  in the same call. `external_agent_relay_enabled` (`dependencies.py:313`),
  `require_operator` and `require_admin_portal_enabled` are **not** touched.
  Make B8/B8a's call-site-coverage and consent-boundary assertions pass.
  *(010-FR-008)*

*Checkpoint: `cd backend && pytest tests/test_feature_flag_service.py`.*

## Lane C — operator routes behind the 009 gate (010-FR-002, 003, 004, 005, 006, 007, 008, 010)

- [ ] **C1** RED: `backend/tests/test_admin_feature_flags_api.py` —
  **authorization, all five routes named explicitly, GET included**: the `GET`
  read and each of the four mutations (set mode, clear override, add account,
  remove account) — five routes total, matching FR-006's own count — each
  answer 401 unauthenticated and 403 to an authenticated non-operator in
  **both** `admin_portal` states, and 404 to an authorized operator when
  `admin_portal` is not effective. A denied request performs no repository
  read or write **on any of the five, `GET` included, not only the four
  mutations** (FR-006's own wording; proved by poisoning the target-facing
  service methods) and leaves the stored document unchanged. The existing
  009-FR-008 denial records are unchanged and no new record type is introduced
  by a denial. *(010-FR-006, 010-SC-006)*
- [ ] **C2** RED: same module — **exact-match add**: adding by exact account ID
  and by exact canonical email succeeds; a prefix, suffix, case variant,
  whitespace variant and the path-shaped variants (`../users/<id>`,
  `users/<id>`, `<id>.json`) each add nobody and report "no account found";
  `admin@localhost` still matches; only the resolved account ID is stored. No
  route added by this feature can list or enumerate accounts.
  *(010-FR-007, 010-SC-007)*
- [ ] **C3** RED: same module — **contract, idempotence and mode transitions**:
  `GET` returns exactly the two managed flags, each with `override_mode`
  (`off` \| `on` \| `selected_users` \| `null`), `source` (`runtime` \|
  `deploy_default`), `deploy_default_state` (`off` \| `internal` \| `on`,
  always present even when `source` is `runtime`) and cohort, and never
  `admin_portal`, `delivery_canary` or `external_agent_relay`; a flag under a
  runtime override reports `override_mode` non-null and `source: "runtime"`; a
  flag inheriting the deploy default reports `override_mode: null` and
  `source: "deploy_default"`, never a synthesized non-null mode (DD-3); every
  mutation returns the full authoritative post-mutation state; repeating an
  add, a remove, a mode set or a clear-override returns success and changes
  nothing; a malformed mode, an unknown flag name, and an add naming an
  unresolvable account are each refused without a partial write, while
  removing an unresolvable or absent account ID succeeds idempotently (DD-7);
  setting a managed flag to each of the three modes and reading it back leaves
  the other managed flag and both unmanaged `KNOWN_FEATURE_FLAGS` entries
  untouched; switching a flag `selected_users` → `on` → `selected_users`
  leaves its cohort exactly as it was, and an add/remove against the flag
  while it is `on` is refused (DD-6); **clearing an override on a flag with a
  non-empty retained cohort deletes the flag's entire runtime entry, cohort
  included** — unlike a mode change to `off`/`on`, which retains the cohort,
  clearing removes it entirely, and a subsequent `GET` reports `override_mode:
  null` and an empty cohort for that flag, exactly as if it had never been set
  (DD-3, DD-6 — campaign-2 correction: the prior revision wrongly claimed the
  cohort survives a clear). *(010-FR-002, 010-FR-003, 010-FR-005, 010-FR-007,
  010-FR-010, 010-SC-001, DD-3)*
- [ ] **C3a** RED: same module — **route-level persistence-failure evidence**:
  with the repository's write path forced to raise (e.g. the lock file or the
  data directory made unwritable), a mutation route surfaces a 5xx error
  response rather than a false 200, and a subsequent `GET` — and the raw bytes
  on disk — show the document unchanged by the failed attempt; this is the
  route-boundary complement to A2's repository-level atomicity proof, closing
  the gap between "the repository never leaves a partial write" and "the route
  never reports success for one." *(010-FR-005, 010-SC-005)*
- [ ] **C4** RED: same module — **removal of an unresolvable entry**: an account
  ID in a cohort that resolves to no account is returned by `GET` with a null
  email rather than being dropped or raising, and the `DELETE` route removes it.
  *(010-FR-007, 010-SC-007)*
- [ ] **C5** RED: same module — **member-visible effect and purge (DD-9)**: with
  `voice_brain_dump` in `selected_users` and account A selected, `GET
  /api/auth/me` reports it `true` for A and `false` for B; after A is removed
  the next `/api/auth/me` reports `false` for A, and A's session is still
  valid; after account A is added to a cohort and then purged through
  `AccountService.purge_account`, the flag's `GET /admin/feature-flags` cohort
  no longer lists A's ID. *(010-FR-008, 010-SC-002, DD-9)*
- [ ] **C6** RED: same module — **auditability (DD-10)**: each of `set_mode`,
  `clear_override`, `add_selected_user` and `remove_selected_user` emits
  exactly one content-free `logger.info` record (operator id, flag, action,
  outcome, no email/display name); `GET` emits exactly one aggregate record per
  call (operator id, flag count, resolved-account count, no email); the
  existing 009 `find_account`/`revoke_sessions` records are unaffected and are
  **not** emitted by the `GET`'s cohort-email resolution (plan.md: it uses a
  plain `UserRepository.get_by_id` read, not `AdminService.find_account`).
  *(010-FR-006, 010-SC-006)*
- [ ] **C7** RED: same module — **application-level restart evidence**: mutate a
  flag through the HTTP API, construct a **fresh FastAPI application / test
  client** over the same `data_dir` (not merely a fresh repository or service
  object), and confirm `GET /admin/feature-flags` reports the mutated state.
  This is the process-boundary half of 010-SC-001 that A1's repository-level
  round-trip does not exercise (campaign-1 testability finding). *(010-SC-001)*
- [ ] **C8** RED: same module — **request-to-document privacy sentinel**: add an
  account through the real `POST .../selected-users` route whose seeded display
  name and email carry distinctive sentinels, then read the document's raw
  bytes directly and assert the account ID is present and neither sentinel
  appears anywhere in the file. Meaningful specifically because it exercises
  `AdminService.find_account`, unlike A7's shape-level check.
  *(010-FR-001, 010-FR-007, 010-SC-007)*
- [ ] **C9** GREEN: `backend/app/schemas/admin.py` gains `AdminFeatureFlagMode`,
  `AdminFeatureFlagSelectedUser`, `AdminFeatureFlagState` (`name`,
  `override_mode: AdminFeatureFlagMode | None`, `source`,
  `deploy_default_state: AdminFeatureFlagMode`, `selected_users` — DD-3's
  three-field split, not a single `mode`), `AdminFeatureFlagsResponse`,
  `AdminFeatureFlagModeRequest` and `AdminFeatureFlagSelectedUserRequest`
  (exactly one of `account_id`/`email`, mirroring `AdminAccountLookupRequest`);
  `backend/app/api/admin.py` gains the five routes (`GET`, `PUT .../mode`,
  `DELETE .../feature-flags/{flag}` for clear-override — which calls
  `clear(flag)` and returns the post-clear state with an empty cohort, never a
  retained one — `POST .../selected-users`, `DELETE .../selected-users/{id}`),
  each `Depends(require_admin_portal_enabled)`, each resolving an added user
  through `AdminService.find_account` and each resolving cohort emails for
  `GET` through a plain `UserRepository.get_by_id` read. Make C1–C3a and C4–C8
  pass.
- [ ] **C10** RED: `backend/tests/test_account_service.py` — **DD-13
  fail-closed purge ordering and sweep isolation**: with the runtime flag
  document degraded, `AccountService.purge_account` raises before
  `user_repo.delete` is ever called — the account, its email and its password
  hash are retained; `AccountService.purge_due_accounts`'s sweep loop
  (`account_service.py:363-375`, which today calls `self.purge_account(user.id)`
  with no isolation) isolates that one account's failure so every other
  due account in the same pass still purges and the method's return count
  reflects only the accounts that actually succeeded; with a **healthy**
  document, `purge_account` calls `feature_flag_repo.scrub_user(user_id)`
  before `user_repo.delete`, mirroring the existing
  `self.invite_repo.scrub_user(user_id)` call immediately above it
  (`account_service.py:400`), and the purged ID is gone from every parseable
  cohort afterward (DD-9). *(010-FR-004, 010-FR-007, DD-9, DD-13)*
- [ ] **C11** GREEN: `backend/app/services/account_service.py` — add
  `self.feature_flag_repo.scrub_user(user_id)` in `purge_account`, next to the
  existing `self.invite_repo.scrub_user(user_id)` call (`:400`), before
  `self.user_repo.delete(user_id)`; wrap `purge_due_accounts`'s per-user
  `self.purge_account(user.id)` call (`:373`) in isolation — catching and
  logging one account's raised failure rather than letting it abort the loop —
  so a single degraded runtime document blocks only the accounts whose cohort
  it would have needed to scrub, not the whole sweep pass. Make C10 pass.
  *(010-FR-004, 010-FR-007, DD-9, DD-13)*

*Checkpoint: `cd backend && pytest tests/test_admin_feature_flags_api.py
tests/test_account_service.py`.*

## Lane D — the operator screen section (010-FR-010; design F-01…F-13)

- [ ] **D1** RED: `frontend/src/features/admin/__tests__/AdminFeatureFlagsSection.test.tsx`
  — the design states by id: `F-01` loading, `F-02` list with the native
  `fieldset`/`legend` mode control, the runtime-vs-deploy-default source note
  (deploy state shown as its own value, not mapped onto a mode) and the "Use
  deploy default" action, `F-03` retained count shown even in OFF/ON mode,
  `F-04` cohort rows carrying account ID plus resolved email plus a Remove
  action whose accessible name includes the row's identity, `F-05`
  empty-cohort copy, `F-06` add form rendered only in SELECTED_USERS mode,
  `F-07` no-match copy identical to 009's `D-04`, `F-08` saving, `F-08a`
  confirm gating for the **exact three-operation allowlist** (DD-12) — setting
  a flag OFF, removing the last remaining cohort member, and clearing a
  runtime override via "Use deploy default" — and *only* those three: ON,
  SELECTED_USERS, adding a user and removing a non-last member each apply
  immediately with no confirm step, `F-09` re-render from the server's
  response with focus moved to a defined target after a row removal, `F-10`
  failure carrying the correlation ID when present and named fallback copy
  when no response was received, with the row reverting to the last
  server-confirmed state, `F-11` degraded store (a successful `degraded: true`
  response) with every control disabled and no retry or reset affordance,
  `F-12` unresolvable selected user still removable, `F-13` the initial fetch
  itself failing (distinct from `F-11`) with a retry action. *(010-FR-010,
  010-FR-003, 010-FR-005, 010-FR-007, 010-SC-008)*
- [ ] **D1a** RED: same module — **`F-08a` dismissal and focus, and the
  390×851 reflow, asserted explicitly rather than assumed inherited**: the
  confirm step is dismissible by Escape, matching `RevokeConfirmDialog`/
  `Overlay`; it receives focus on appearance and returns focus to the control
  that opened it (the mode radio, the "Use deploy default" action, or the
  last-member Remove action) on both Cancel and Escape; and, at a 390×851
  viewport, the mode `fieldset`, the source note, cohort rows and the confirm
  step's Confirm/Cancel controls each reflow to the stacked layout design.md's
  "Mobile reflow at 390×851" section states, with every one of those controls
  measuring at least 44px tall. *(010-FR-010, 010-SC-008)*
- [ ] **D2** RED: same module — the input classification inherited from feature
  009: `admin@localhost` classifies as an email, `a@` as an account ID, an
  account ID is never sent as an email, and the value is sent **as typed** and
  never trimmed. *(010-FR-007)*
- [ ] **D3** RED: `frontend/src/features/admin/__tests__/AdminPage.test.tsx` —
  the section renders only inside the operator-confirmed branch and is absent in
  `D-01`, `D-08` and `D-09`; feature 009's existing `D-01`…`D-10` assertions
  still pass unchanged. *(010-FR-006, 009-FR-005)*
- [ ] **D4** RED: `frontend/src/components/shell/__tests__/AppShell.test.tsx` —
  rendering the shell as an authenticated member still issues **no** request to
  any `/admin` route, including the new flag routes. *(009-FR-010, 009-FR-011,
  PD-1)*
- [ ] **D5** GREEN: `frontend/src/api/adminTypes.ts`,
  `frontend/src/api/client.ts` (`getAdminFeatureFlags`,
  `setAdminFeatureFlagMode`, `clearAdminFeatureFlagOverride`,
  `addAdminFeatureFlagUser`, `removeAdminFeatureFlagUser`),
  `frontend/src/api/adminHooks.ts` (`useAdminFeatureFlags` under the existing
  owner-scoped `adminKeys`), `frontend/src/features/admin/
  AdminFeatureFlagsSection.tsx`, and the mount point in
  `frontend/src/features/admin/AdminPage.tsx`. Make D1–D4 pass.

*Checkpoint: `cd frontend && npx vitest run src/features/admin src/components/shell`.*

## Lane E — live propagation to signed-in sessions, web and mobile (010-FR-009)

- [ ] **E1** RED: `frontend/src/stores/__tests__/authStore.test.ts` with fake
  timers — while `status === "authed"`, exactly one `refreshSession()`-driven
  `/api/auth/me` refetch is issued per 15-second interval and the returned
  `feature_flags` replace the stored ones; a `focus` event and a
  `visibilitychange` to visible each trigger an immediate refetch; **no**
  request is issued while anonymous or while the document is hidden; the
  interval and listeners are torn down on sign-out and on teardown, leaving no
  timer behind. Assert against `startFlagRefresh()` directly so the test does
  not depend on which module happens to import it at startup. *(010-FR-009,
  010-SC-004)*
- [ ] **E2** RED: same module — **two distinct failure paths (DD-11)**: on the
  `refreshSession()` path, a refetch answering 401 clears the session exactly
  as today and stops the timer; a transient network or 5xx failure leaves
  `user` and `status` untouched, clears the timer for nothing, and surfaces no
  error. Advance one further interval after that transient failure, return a
  successful `/api/auth/me` response with changed flags, and assert the same
  poll recovered and applied them without a sign-out. Separately, a **pinning**
  assertion on the existing `hydrate()`
  (initial/startup load) confirms its current behavior is unchanged: any
  failure, including a transient one, still resolves to `{ user: null, status:
  "anon" }` — this is deliberate, not a regression, so it must not be
  accidentally "fixed" by a later change that conflates the two paths.
  *(010-FR-009, 010-SC-004)*
- [ ] **E3** RED: a component-level assertion in
  `frontend/src/features/brain-dump/BrainDumpGate.test.tsx` (the existing gate
  test, co-located rather than under a `__tests__/` directory) — a gated
  capability appears when a later `/api/auth/me` payload turns its flag on,
  with no logout, login or reload. *(010-FR-009, 010-SC-004)*
- [ ] **E4** RED: `frontend/src/__tests__/App.test.tsx` — no WebSocket and no
  EventSource is constructed anywhere in the app. *(010-FR-009, 010-SC-004)*
- [ ] **E5** GREEN: `frontend/src/stores/authStore.ts` — `refreshSession()` (the
  transient-tolerant, 401-clearing path) and `startFlagRefresh()` driving a
  single named-constant 15-second interval plus `focus` and `visibilitychange`
  listeners, each calling `refreshSession()`; `hydrate()` itself is
  **unchanged**. Started once from `frontend/src/queryClient.ts`, next to the
  existing `bindAdminSession(queryClient)` call at module scope (`:10`) —
  **not** `main.tsx`, which contains no such wiring and never executes under
  Vitest. Make E1–E4 pass.
- [ ] **E6** RED: `mobile/src/auth/__tests__/SessionProvider.test.tsx` (or a
  co-located `SessionProvider.poll.test.tsx`) with fake timers and a faked
  `AppState` — while signed in and `AppState.currentState === "active"`,
  exactly one `/auth/me` refetch is issued per 15-second interval (the same
  named-constant value as the web interval) and the resolved
  `taskClassificationEnabled`/`voiceEnabled` values update from the response;
  an `AppState` transition to `"active"` from `"background"`/`"inactive"`
  triggers an immediate refetch rather than waiting out the remainder of the
  interval; no refetch is issued, and the interval is suspended, while
  `AppState.currentState` is not `"active"`; the interval and the `AppState`
  subscription are torn down on sign-out and on unmount, leaving no timer or
  subscription behind — mirroring the `AppState.addEventListener("change",
  ...)` / `subscription.remove()` idiom already used in
  `mobile/src/features/tasks/useClassificationQueue.ts` and
  `mobile/src/features/agents/useAgentRunsFeed.ts`. *(010-FR-009, 010-SC-004)*
- [ ] **E7** RED: same file — **two distinct failure paths (DD-11), mirrored
  for mobile**: a transient (non-401) refetch failure during the poll leaves
  the session, `me` and the resolved flags untouched, the poll continues, and
  no error is surfaced; a 401 on the same poll path signs the session out
  exactly as an in-app 401 does today and stops the poll. After the transient
  case, advance one further interval, return a successful `/auth/me` response
  with changed flags, and assert the same poll recovered and applied them
  without a sign-out. A pinning assertion
  on the existing mount-time `probe()` call (`SessionProvider.tsx:269`, the
  mobile equivalent of web's `hydrate()`) confirms its current behavior is
  unchanged: any failure there, transient or not, still resolves to a
  signed-out session — deliberate, not a regression, so a later change must
  not conflate it with the poll's transient-tolerant path. *(010-FR-009,
  010-SC-004)*
- [ ] **E8** GREEN: `mobile/src/auth/SessionProvider.tsx` — add a poll effect
  alongside the existing mount-time `probe()` call (`:269`): a single
  named-constant 15-second interval (the same constant value as web's) plus
  an `AppState.addEventListener("change", ...)` listener, both driving a
  poll-specific refetch — not `probe()` itself, to preserve DD-11's split —
  while `status` is signed-in and `AppState.currentState === "active"`; a
  transient failure on that path leaves `me`/`status`/the resolved flags
  untouched and keeps the interval running; a 401 signs out and tears down
  the interval and listener. `probe()` itself is unchanged. Make E6–E7 pass.
  *(010-FR-009)*

*Checkpoint: `cd frontend && npx vitest run src/stores src/features/brain-dump
src/__tests__/App.test.tsx` and `cd mobile && npx jest src/auth`.*

## Lane F — the member-facing contract this feature must not move (010-FR-008)

- [ ] **F1** RED: `backend/tests/test_auth_routes.py` — the `feature_flags` key
  set returned by `/api/auth/me`, `/api/auth/login` and `/api/auth/signup` is
  exactly `KNOWN_FEATURE_FLAGS` (all four names — this feature does not remove
  `delivery_canary` or `external_agent_relay` from the payload, only from
  runtime management), `admin_portal` is absent, and the assertion fails if a
  key is added or removed. A runtime override on either managed flag changes
  only that flag's boolean in the `login` and `signup` responses too, proving
  `_me_response`'s single resolution point covers all three routes, not only
  `/me` (campaign-1 testability finding: prior coverage was `/me`-only). This
  is the evidence that the mobile client's **existing request/response
  contract** needs no change for FR-008: no production file or test in this
  lane touches a request/response shape, a status code, or a payload key on
  either client. It says nothing about FR-009's polling cadence — that is
  Lane E's mobile sublane (E6–E8), which does edit `mobile/src/auth/
  SessionProvider.tsx` and its tests for a different requirement, and this
  lane does not pin against or otherwise forbid that. *(010-FR-008,
  010-SC-003)*
- [ ] **F2** GREEN: no production change is expected in this lane — it passes on
  the surfaces lanes B and C already produce. If it does not, that is the
  finding, and the fix belongs in whichever lane broke it.

*Checkpoint: `cd backend && pytest tests/test_auth_routes.py`.*

## Lane G — the governance records

- [ ] **G1** `docs/decisions/0018-runtime-feature-flag-overlay.md` — new ADR:
  the per-flag precedence rule (DD-3), the two-flag managed set and the named
  reason each of the other two `KNOWN_FEATURE_FLAGS` entries is excluded
  (DD-1), the bounded narrowing of ADR-0017's "no admin data store" to one
  rollout-configuration document holding account IDs only, the purge obligation
  and its precedent (DD-9), the audit obligation and its content-free shape
  (DD-10), the re-assertion that flags stay exposure control and that the
  operator allow-list remains deployment configuration only, the explicit
  narrowing of ADR-0017's per-account-operation audit clause for the aggregate
  cohort-email read (one aggregate count record, never one log per resolved
  account), and the
  single-process serialization assumption a future scale-out must revisit.
- [ ] **G2** `docs/data-retention.md` — one new row in the retention table,
  mirroring the existing Invites row (`Data` / `Where` / `Retention` /
  `Enforced by`), naming the runtime flag document, its path, and "scrubbed by
  account purge (`FeatureFlagOverrideRepository.scrub_user`)" as its
  enforcement; one line added to the export-contents exclusion list naming the
  same document as excluded from a member's data export (DD-9); and the
  existing **Admin access records** row/section amended to also name this
  feature's own log records — the per-mutation `set_mode`/`clear_override`/
  `add_selected_user`/`remove_selected_user` records and the per-`GET`
  aggregate cohort-resolution record (DD-10) — under the identical disposition
  already decided for feature 009 (platform log window, excluded from export,
  not reached by purge). No other line in this file changes.
- [ ] **G3** `docs/auth.md` — one bullet added to the existing
  operator-authority list naming the new runtime-flag-management authority this
  feature grants an authorized operator, pointing at
  `docs/decisions/0018-runtime-feature-flag-overlay.md` (G1). No other line in
  this file changes (DD-9, FR-007).
- [ ] **G4** `frontend/src/pages/PrivacyPolicyPage.tsx` — one sentence added
  under the existing "How long we keep it" section naming the runtime rollout
  document: it holds only your account id, is scrubbed on account purge, and
  is excluded from your data export — the one authorized text-only addition
  mirroring feature 009's own precedent, not the privacy-summary rewrite the
  founder's slice still excludes — plus the routine `LAST_UPDATED` bump that
  edit requires. No other privacy-policy surface changes (DD-9, FR-007).

  Together, G1–G4 are the **only** files outside the tested surfaces of Lanes
  A–F this feature writes or edits, and the only documentation or in-app-copy
  files touched at all. `.env.example` is deliberately untouched (see
  [spec.md](spec.md) Out of Scope and [plan.md](plan.md) Risks); `docs/auth.md`
  and the privacy-policy page are edited exactly as narrowly as G3 and G4 state
  and no further.

*Checkpoint: `python3 scripts/check_spec_kit_specs.py` and a read-through against
[plan.md](plan.md)'s changed-surface table.*

## Lane H — verification and landing (runtime-neutral)

- [ ] **H1** Full verification, in CI order, naming commands rather than a
  runtime: `cd backend && pytest` for the focused loop, then **`make
  verify-all`** — it chains `check-specs` (including
  `scripts/check_spec_kit_specs.py`), `validate-ci`, `make test-backend` (pytest
  plus the coverage floor and the Allure taxonomy validator), the frontend and
  mobile CI chains and the Playwright e2e run. Then the two checks `verify-all`
  does **not** run:
  `python3 scripts/check_requirement_coverage.py specs/010-admin-live-feature-flags`
  (expect all ten 010-FR and all eight 010-SC ids traced) and
  `git diff --no-renames --name-only -z | python3 scripts/classify_path_risk.py --null`
  (expect it to report ASK and exit non-zero — that is the ADR-0008 gate doing
  its job, not a failure to fix). Finish with `git diff --check`.
- [ ] **H2** **Cross-layer pre-landing acceptance (campaign-1 testability
  finding — the founder's primary success criterion, intake.md "Success, in the
  founder's terms").** Before H4's landing approval, execute the Manual
  Acceptance Checks in [spec.md](spec.md) end-to-end and record the evidence
  (redacted per constitution Principle I): one real operator mutation, made
  through the running application, observed reaching an already-authenticated
  second browser session within about fifteen seconds without a reload or
  re-login. C5's backend-only assertion and D/E's mocked-`/api/auth/me`
  frontend assertions are necessary but not sufficient on their own — this task
  is the one that actually crosses the seam between them. In the same running
  build, repeat the operator screen at a real 390×851 browser viewport and
  capture evidence that controls reflow without horizontal overflow, remain at
  least 44px high and preserve the confirmation focus/Escape behavior. Finally,
  keep an already-signed-in mobile session active, apply a managed-flag change,
  and record that the corresponding capability updates within one poll interval
  without a sign-out, reload or app restart.
- [ ] **H3** Do not change planning artifacts during implementation: both review
  campaigns are spent and no third campaign is permitted. If implementation
  exposes a contract defect that requires a planning change, stop and return it
  to the owner rather than silently rewriting this founder-accepted package.
- [ ] **H4** ASK landing per ADR-0008 (see
  [plan.md](plan.md#landing-adr-0008-ask)): explicit recorded maintainer
  approval, green required CI on the **exact SHA** being landed, and a short
  audited temporary ruleset intervention recording who, why and when the ruleset
  was restored. This change must not land through the automatic deploy-key path.
- [ ] **H5** After landing, `/speckit-accept` and `/speckit-report` produce
  `acceptance.md`, `traceability.md` and `report.md`, which
  `scripts/check_spec_kit_specs.py` requires once every box above is ticked.
