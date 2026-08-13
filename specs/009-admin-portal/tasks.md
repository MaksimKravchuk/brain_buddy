# Tasks: Minimum Admin Portal

Grouped into **independently acceptable lanes**, each with its own RED → GREEN
ordering and its own evidence checkpoint. A lane can be finished, run and
judged without any other lane being finished. See [plan.md](plan.md) for why
each exists and [spec.md](spec.md) for the product decisions (PD-1…PD-5) that
several lanes now encode.

Everything here is **runtime-neutral**: no task requires Hermes, a Kanban
runtime, or any other control plane. A managed overlay may adopt these tasks,
but nothing here depends on one (ADR-0010, ADR-0011).

**A box is ticked only when the tree actually contains the work.** Campaign 1
found T008 ticked for an edit that was never made, which cost the whole
checklist its credibility. As of the campaign-2 repair pass, lanes A–I are
ticked because the code, the tests and the documents all exist on this branch
and the named checkpoints were run green. J1's full verification has since
been run on this tree and is green end to end — `make check-specs`, the
`validate-ci` validators, the backend suite (2341/2341 with its coverage floor
and a fresh Allure taxonomy run), the frontend chain (typecheck, lint, build,
full coverage at 97.89% branches / 98.75% functions / 98.86% lines / 98.82%
statements, focused 91/91), `verify-mobile` after `npm ci`, the Playwright
`make test-e2e` run, `check_requirement_coverage.py` at 20/20, and
`git diff --check`. **Only J2 remains**: the human ASK landing.

**Lane independence, corrected.** The opening claim that any lane can be
finished and judged alone was false and is withdrawn for two edges: lane B's
flag-ON case is the lane C–F behaviour, so B's fixtures set the flag state
explicitly and B is judged against C–F; and lanes B, C, E and F share
`backend/tests/test_admin_api.py` and `backend/app/services/admin_service.py`,
so they are sequenced, not parallel. Lane D is a **landing precondition**, not
a deferrable lane: until the reservation is enforced, an unclaimed operator
address is claimable and `docs/auth.md` / `.env.example` describe a control
that does not exist.

## Lane A — operator allow-list configuration (009-FR-001) — landed

- [x] **A1** RED: `backend/tests/test_admin_config.py` — normalization,
  invalid-email fail-closed, empty default. *(009-FR-001)*
- [x] **A2** GREEN: `AdminSettings.operator_emails` in
  `backend/app/core/config.py`, mirroring `FeatureFlagSettings.internal_users`;
  wired into `AppConfig` and `_build_config` from
  `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`. *(009-FR-001)*

*Checkpoint: `cd backend && pytest tests/test_admin_config.py`.*
*Note: A1 was authored after A2 in the first pass — GREEN before RED. The
result is correct and is left as landed; the ordering error is recorded here
rather than hidden, and every lane below is RED-first.*

## Lane B — default-OFF rollout flag (009-FR-013, 009-SC-007)

- [x] **B1** RED: extend `backend/tests/test_admin_config.py` — `admin_portal`
  is a known flag and is OFF unless configured. *(009-FR-013)*
- [x] **B2** RED: `backend/tests/test_admin_api.py` — with the flag not
  effective, every `/admin` route is unavailable to an **allow-listed
  operator** (404), while an unauthenticated caller still gets 401 and an
  authenticated non-operator still gets 403 — the founder's
  authorization-first precedence, recorded in 009-FR-013. With the flag
  effective the lane C–F behavior returns. Depends on lane C's fixtures
  (`admin_world` / `admin_world_flag_off` set the flag state explicitly).
  *(009-FR-013, 009-SC-007)*
- [x] **B3** GREEN: `admin_portal` is declared in a new `PRIVATE_FEATURE_FLAGS`
  tuple (`backend/app/core/config.py`) — configured from the same
  `BRAIN_BUDDY_FEATURE_FLAGS` string and read through
  `FeatureFlagSettings.private_flag_effective`, but deliberately **not** in
  `KNOWN_FEATURE_FLAGS`, because `effective_flags` projects that tuple into
  every member's `/api/auth/me`/`login`/`signup` payload and adding a key
  there would break 009-FR-010. `require_admin_portal_enabled`
  (`backend/app/api/dependencies.py`) composes `require_operator`, so
  authorization is decided first and only an allow-listed operator sees the
  flag-OFF 404. The flag is exposure control **in addition to**
  `require_operator`, never instead of it (ADR-0008).
- [x] **B4** GREEN: `.github/workflows/deploy-fly-production.yml` stages
  `admin_portal=off` explicitly in the authoritative
  `BRAIN_BUDDY_FEATURE_FLAGS` value, with the ASK-class edit-and-deploy
  requirement and the emergency allow-list lever recorded in place.
  Pinned by `scripts/validate_trunk_delivery.py` (+ its mutation test) and by
  `backend/tests/test_admin_deploy_contract.py`. *(009-FR-013, PD-2)*

*Checkpoint: the flag-off and flag-on cases in `test_admin_api.py`.*

## Lane C — authorization boundary and denial records (009-FR-002, 008, 011)

- [x] **C1** RED: `backend/tests/test_admin_api.py` — 401 unauthenticated and
  403 non-operator on **every** admin route; the 403 is identical whether or
  not the target account exists; a denied lookup performs no repository read
  and a denied revoke leaves the target's sessions valid (assert the effect,
  not just the status). *(009-FR-002, 009-SC-002)*
- [x] **C2** RED: denial-record evidence — a 401 record, a 403 record on
  `GET /admin/status`, and a 403 record on a data route are each present and
  the capability-check record is **distinguishable** from the data-route
  record (different level or message). No record carries a cookie, token or
  email. *(009-FR-008, 009-FR-011)*
- [x] **C3** RED: session-resolution parity — `require_operator` and
  `get_current_user` accept and reject the same cookie states (missing,
  unknown, expired), so the two paths in `dependencies.py` cannot diverge.
  *(009-FR-002)*
- [x] **C4** GREEN: `backend/app/api/dependencies.py` — keep the deliberate
  duplication documented in plan.md key decision 7, and split the probe
  denial from the data-route denial in the log line. Make C1–C3 pass.

*Checkpoint: the authorization cases in `test_admin_api.py`.*

## Lane D — operator identity is not self-claimable (009-FR-012, 009-SC-006)

- [x] **D1** RED: `backend/tests/test_admin_operator_reservation.py` — a
  member who calls
  `POST /api/account/email` with an address on the operator allow-list is
  refused, the refusal does not disclose that
  the address is reserved, and every `/admin` route still answers that member
  403 afterwards. *(009-FR-012, 009-SC-006)*
- [x] **D2** RED: the same module — signup with an allow-listed address is
  refused the same way, byte-identically to an already-registered address;
  `AuthService.seed_admin` **may** still create or rotate the configured
  identity, and once it has, that identity really is an operator. A dedicated
  module rather than cases inside `test_account_api.py`/`test_auth_routes.py`:
  those build their app with no operator allow-list, and the reservation only
  exists when one is configured. *(009-FR-012)*
- [x] **D3** GREEN: reserve the configured addresses in
  `AuthService.signup` and `AccountService.change_email`, leaving
  `AuthService.seed_admin` as the only provisioning path. The allow-list
  reaches both services as a plain `reserved_emails` frozenset injected by
  `backend/app/container.py` — not an `AdminService` handle, which would
  couple auth to the admin portal for one config value. No email verification
  is added. Make D1–D2 pass.

*Checkpoint: `cd backend && pytest tests/test_admin_operator_reservation.py`.*

## Lane E — exact lookup and log content (009-FR-003, 004, 008; SC-001, SC-004)

- [x] **E1** RED: `backend/tests/test_admin_service.py` — exact ID and exact
  email match; **negative cases derived from a real account**: a prefix of its
  id, a prefix of its email, a case variant, a whitespace variant, a suffix,
  and the path-shaped variants (`../users/<id>`, `users/<id>`, `<id>.json`) —
  all return no match. A separate case proves the charset guard runs *before*
  `UserRepository.get_by_id`, so a traversal id never reaches path
  construction, and one proves a server-accepted address without a dotted
  domain (`admin@localhost`) still matches. *(009-FR-003, 009-SC-001)*
- [x] **E2** RED: `backend/tests/test_admin_api.py` — response contains only
  the four allowed fields; the request rejects zero and both identifier
  fields. *(009-FR-004)*
- [x] **E3** RED: log-content evidence for a **successful lookup**, captured
  independently of the revoke record: the account under test has a distinctive
  display-name sentinel and the request body carries a distinctive canary; the
  record contains the operator id and the **resolved** account id and contains
  neither sentinel, nor the email, nor any credential/token/session-hash
  fragment. *(009-FR-008, 009-SC-004)*
- [x] **E4** GREEN: `backend/app/services/admin_service.py` — record the
  resolved account id on the lookup log line (it logged only `found=<bool>`,
  so a lookup was unattributable), and add the exact-match repair the plan's
  changed-surface row now names: an `ACCOUNT_ID_PATTERN` charset guard before
  any repository read, plus a post-fetch identity check (`user.id ==
  account_id`, `user.email == email`) so the repository's normalizing
  `get_by_email` and a case-insensitive filesystem cannot turn a variant into
  a match. Make E1–E3 pass.

*Checkpoint: `cd backend && pytest tests/test_admin_service.py tests/test_admin_api.py -k lookup`.*

## Lane F — revoke (009-FR-007, 009-SC-003)

- [x] **F1** RED: `backend/tests/test_admin_service.py` /
  `test_admin_api.py` — an account with **two concurrent sessions** has both
  invalidated (read back through the API, not just a count); a repeat revoke
  on that existing account returns 2xx with `revoked_count: 0`; an unknown
  account id returns **404** (PD-3); and a traversal variant of a real id
  returns 404 rather than a 2xx `revoked_count: 0` that would read as success,
  leaving the real account's session untouched. *(009-FR-007, 009-SC-003)*
- [x] **F2** RED: revoke log record — separately captured from the lookup
  record, carrying operator id, target account id and outcome, with the same
  sentinel/canary absence assertions as E3. *(009-FR-008, 009-SC-004)*
- [x] **F3** GREEN: confirm `backend/app/services/admin_service.py` satisfies
  F1–F2; adjust only where the evidence shows it does not.

*Checkpoint: `cd backend && pytest tests/test_admin_service.py tests/test_admin_api.py -k revoke`.*

## Lane G — same-origin properties are pinned (009-FR-009)

- [x] **G1** RED: named tests in `backend/tests/test_admin_api.py` (the
  requirement ids moved off the module docstring onto the assertions, so the
  coverage gate tracks evidence rather than a header) — a check that fails if
  the session cookie stops being
  `SameSite=Lax`/`HttpOnly`, and one that fails if a permissive cross-origin
  response header appears on an admin route. FR-009 rests entirely on these
  two properties, so they need a test rather than a sentence.
- [x] **G2** GREEN: no production change expected — this lane passes on the
  current posture. If it does not, that is the finding.

*Checkpoint: the FR-009 cases in `backend/tests/test_admin_api.py`.*

## Lane H — `/admin` screen, direct route only (009-FR-005, 006, 010, 011; PD-1)

- [x] **H1** RED: `frontend/src/app/AppRoutes.test.tsx` — the **real**
  `/admin` route: signed-out redirects to sign-in, signed-in non-operator
  reaches the denied state, operator reaches the form. Mounting `AdminPage`
  directly cannot detect wrong route wiring. *(009-FR-005)*
- [x] **H2** RED: `frontend/src/features/admin/__tests__/AdminPage.test.tsx` —
  the design states by id: D-01 checking access, D-02 form, D-03 found, D-04
  not found, D-05 confirm (with the account named and the consequence stated),
  D-06 revoked count, D-07 request failed, D-08 denied, D-09 **could not
  verify** (a network failure must not render a permanent denial), plus:
  a flag-OFF 404 on the capability check renders D-08 and a network/5xx
  renders D-09 with a retry; a revoke that 404s renders the D-04 copy; the
  three input classifications (`admin@localhost` as email, `a@` as account id,
  an account id never as an email) and a whitespace variant sent as typed
  rather than trimmed into a match; a null capability body fails closed; the
  query runs once and does not refetch on focus; focus moves into the dialog
  on open and returns to the trigger on Cancel, Escape and a completed revoke;
  the self-revoke warning appears only when the target is the operator's own
  account. *(009-FR-005, 006, 011)*
- [x] **H3** RED: `frontend/src/components/shell/__tests__/AppShell.test.tsx` —
  rendering the shell as an authenticated member issues **no** request to any
  `/admin` route and shows no admin entry in the account menu. *(009-FR-010,
  009-FR-011, 009-SC-006, PD-1)*
- [x] **H4** GREEN: remove `useAdminStatus()` and the "Admin portal" item from
  `frontend/src/components/shell/AppShell.tsx` (the three shell tests asserting
  the removed behavior are **inverted, not deleted**, and the shared
  `getAdminStatus` spy now asserts the call never happens); scope the status
  query in `frontend/src/api/adminHooks.ts` to `AdminPage` and cache it for the
  session (`staleTime: Infinity`, no refetch on focus/reconnect/mount); split
  D-08 (403 or flag-OFF 404) from D-09 (transient) in `AdminPage.tsx`; map a
  revoke 404 to D-04; widen the client email pattern to what the server
  accepts; stop trimming the submitted identifier; warn in the confirm dialog
  when the target is the operator's own account, read from the existing auth
  store so no auth payload grows. Focus restoration is kept **local to the
  admin dialog** — `frontend/src/components/ui/Overlay.tsx` is shared by the
  capture and task screens and this slice has no regression evidence for
  changing it app-wide. Make H1–H3 pass.

*Checkpoint: `cd frontend && npx vitest run src/features/admin src/app/AppRoutes.test.tsx src/components/shell`.*

## Lane I — governance and documentation (this pass)

- [x] **I1** ADR resolving the ADR-0001 cross-owner conflict:
  `docs/decisions/0017-operator-account-administration-narrow-owner-scoping-exception.md`
  — narrow exception for account-record lookup and session revoke only;
  member content stays owner-scoped.
- [x] **I2** Document `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` in `.env.example`:
  comma-separated, normalized, fail-closed when empty, reserved addresses,
  restaged on every production deploy. *(009-FR-001)*
- [x] **I3** Document the seeded admin account's operator privilege and the
  admin-grade nature of `BRAIN_BUDDY_ADMIN_PASSWORD` in `docs/auth.md`.
  *(PD-2, PD-5)*
- [x] **I4** Document the retention, purge and export disposition of admin
  access records in `docs/data-retention.md` — own retention row, own section,
  named in the export exclusions. *(PD-4, 009-SC-005)*
- [x] **I5** Record PD-1…PD-5 in [spec.md](spec.md) so campaign 2 does not
  re-ask them, and encode them as requirements (009-FR-007, 010, 011, 012).
- [x] **I7** Update `frontend/src/pages/PrivacyPolicyPage.tsx` — the
  user-facing summary `docs/data-retention.md` requires to stay in sync:
  operator/support account administration as a processing purpose, its
  legitimate-interest basis, the content-free platform-log retention, and that
  those records are outside both the export and account purge; `LAST_UPDATED`
  bumped. Text only, no new UI. *(PD-4, 009-SC-005)*
- [x] **I8** Executable 009-SC-005 evidence in
  `backend/tests/test_account_export.py`: a distinctive sentinel is planted in
  a real admin record, proved present in the log stream, then proved absent
  from the export archive's names, manifest counts and bytes; a second test
  proves an account purge leaves the record alone. This replaces the false
  claim that lanes B, D and H covered SC-005. *(009-SC-005)*
- [x] **I6** Repair [spec.md](spec.md), [design.md](design.md),
  [plan.md](plan.md), this file and
  [checklists/requirements.md](checklists/requirements.md) against the
  campaign findings: accurate changed surfaces and symbol names, the
  `/admin/status` capability route, D-01…D-10 state ids, the ASK/high-risk
  landing and rollback section, runtime neutrality, and honest checkboxes.

## Lane J — verification and landing (runtime-neutral)

- [x] **J1** Full verification, in CI order, naming the commands rather than a
  runtime: `cd backend && pytest` for the focused loop, then **`make
  verify-all`** — it already chains `check-specs` (including
  `scripts/check_spec_kit_specs.py`), `validate-ci`, `make test-backend`
  (pytest plus the coverage floor and the Allure taxonomy validator), the
  frontend and mobile CI chains and the Playwright e2e run; note its
  undocumented prerequisites in the Makefile comment. Then the two checks
  `verify-all` does **not** run:
  `python3 scripts/check_requirement_coverage.py specs/009-admin-portal`
  (the six ids that were failing are now covered: 009-FR-011 and 009-SC-006 by
  lanes C and H, 009-FR-012 by lane D, 009-FR-013 and 009-SC-007 by lane B,
  and 009-SC-005 by I8 — *not* by lanes B/D/H, as J1 previously claimed) and
  `git diff --no-renames --name-only -z | python3 scripts/classify_path_risk.py --null`.
  Finish with `git diff --check`.
- [ ] **J2** ASK landing per ADR-0008 (see [plan.md](plan.md#landing-adr-0008-ask)):
  explicit recorded maintainer approval, green required CI on the **exact SHA**
  being landed, and a short audited temporary ruleset intervention recording
  who, why and when the ruleset was restored. This change must not land
  through the automatic deploy-key path. Independent verification is performed
  by whoever holds that approval — no specific runtime is required, and a
  managed overlay is optional, not a precondition.
