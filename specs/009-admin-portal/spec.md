# Feature Specification: Minimum Admin Portal

**Feature Branch**: `feat/009-admin-portal-minimum` · **Created**: 2026-08-13
**Status**: In implementation — planning artifacts repaired after review
campaign `009-admin-portal-campaign-1`; code repair outstanding (see
[tasks.md](tasks.md)).
**Input**: see [intake.md](intake.md) for the founder's ask, verbatim.

A web-only `/admin` surface for a small, explicitly allow-listed set of
operators to find one member account and revoke its sessions. Reuses the
existing session-cookie auth, the `SessionRepository` bulk-delete capability,
and the API envelope/logging conventions already in the backend; adds no new
subsystem. The cross-owner reach this requires is authorized narrowly by
[ADR-0017](../../docs/decisions/0017-operator-account-administration-narrow-owner-scoping-exception.md).

## Product decisions (accepted, do not re-ask)

Campaign 1 raised five product questions and stopped for the founder. These
are the founder's answers, recorded here so no later review re-opens them.

| # | Question | Decision |
| --- | --- | --- |
| PD-1 | Do operators discover `/admin` through the global account menu? | **No — direct `/admin` only.** No navigation entry, no account-menu item, and no capability query on any screen other than `/admin` itself. The shipped `AppShell` menu entry and its shell-wide probe are out of intended scope and must be removed (009-FR-011). |
| PD-2 | Who are production operators? | **The seeded admin account is the sole operator.** `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` is deliberately pinned to `BRAIN_BUDDY_ADMIN_EMAIL` and restaged by the production deploy on every release. The founder accepts that `BRAIN_BUDDY_ADMIN_PASSWORD` is therefore an admin-grade credential, and that an out-of-band `fly secrets set` is reverted by the next deploy. No dedicated operator account and no separate operator secret are created (009-FR-001). |
| PD-3 | What does revoke return for an unknown account ID? | **404.** An account that exists with zero active sessions still returns 2xx with `revoked_count: 0`. A typo or a purged account is distinguishable from a real zero-session account (009-FR-007). |
| PD-4 | What is the retention, purge and export disposition of admin access records? | **Content-free stdout/platform logs.** Retained for whatever window the platform (Fly) applies, deliberately excluded from `GET /api/account/export`, and not reached by account purge. Recorded in `docs/data-retention.md` as its own processing category (009-FR-008, 009-SC-005). |
| PD-5 | Is the smoke identity allowed to be the production operator? | **Yes — same decision as PD-2.** The blast radius is accepted and documented in `docs/auth.md` rather than mitigated with a second identity. |

## User Scenarios & Testing

The "user" is an allow-listed operator (founder/support), authenticated the
same way any member is. See [design.md](design.md) for the single screen.

1. **Operator looks up an account by ID.** An allow-listed operator, signed
   in, opens `/admin` directly, enters an account ID, and sees exactly:
   account ID, canonical email, optional display name, deletion-requested
   state.
2. **Operator looks up an account by email.** Same as above, entering a
   canonical email instead; only an exact match is returned.
3. **No match.** The operator enters an ID or email with no exact match —
   including a value that is a prefix or near-match of a real account; the
   portal reports "not found" and discloses nothing else.
4. **Operator revokes sessions.** After a successful lookup, the operator
   clicks revoke, confirms in an explicit second step, and every current
   session for that account is deleted — all of them, not one. A repeat
   revoke on an account with no active sessions still reports success
   (revoked count 0). Revoking an account ID that does not exist reports "no
   account found", not success.
5. **Non-operator is denied.** A signed-in member whose email is not on the
   allow-list gets a 403 from every `/admin` API route, before any lookup or
   mutation runs and with no repository read or session change as a
   side effect; the portal shows a generic access-denied state.
6. **Unauthenticated caller is denied.** A caller with no valid session gets
   401 from every `/admin` API route, and opening `/admin` in a browser
   follows the existing app-wide sign-in redirect.
7. **Existing journeys are untouched, with one stated exception.** Every
   non-admin route, cookie, response shape and screen behaves exactly as
   before this feature, except that signup and self-service email change now
   refuse a configured operator address (009-FR-012) with the existing
   conflict behavior. No member who never opens `/admin` issues an admin
   request at all.
8. **The portal is off until it is turned on.** With the `admin_portal`
   rollout flag OFF — its default — an unauthenticated caller still gets 401
   and an authenticated non-operator still gets 403, exactly as with the flag
   on; an allow-listed operator gets 404, and the page renders the same
   generic denied state (D-08). Nobody who is not already an operator can tell
   the flag's state from the API.

## Requirements

- **FR-001**: The backend MUST maintain an explicit, server-owned operator
  allow-list of normalized email addresses, sourced from configuration (not
  request input, not a database table an operator can self-edit), fail-closed
  when unset. Per PD-2 the production value is the seeded admin identity
  (`BRAIN_BUDDY_ADMIN_EMAIL`), staged by the deploy workflow.
- **FR-002**: Every `/admin` API route MUST require a valid session AND
  allow-list membership, checked server-side, before any account lookup or
  mutation logic runs. An unauthenticated caller MUST get 401; an
  authenticated non-operator MUST get 403. A denied request MUST leave no
  observable effect: no account read, no session deleted, and a response that
  does not vary with whether the target account exists.
- **FR-003**: The account-lookup endpoint MUST accept exactly one of an
  immutable account ID or a canonical email per request and return an exact
  match only — no partial, prefix, or fuzzy search. A value that is a prefix,
  suffix, or case/whitespace variant of a real account ID or email MUST
  return no match.
- **FR-004**: A successful lookup response MUST contain only: account ID,
  canonical email, optional display name, and deletion-requested state.
  No other stored field may be returned.
- **FR-005**: The `/admin` frontend route MUST be web-only, reachable only to
  a signed-in caller (the existing `ProtectedRoute` redirect applies to the
  real `/admin` route, not only to the page component), and MUST render only
  the four fields in FR-004 for a found account.
- **FR-006**: The frontend MUST require an explicit confirmation step,
  separate from the initial click, before the session-revoke request is
  sent.
- **FR-007**: The revoke endpoint MUST use the existing
  `SessionRepository.delete_all_for_user` bulk-delete capability and MUST
  delete every current session for the target account. It MUST be idempotent
  for an **existing** account: zero active sessions returns success with a
  revoked count of 0, not an error. An account ID that does not exist MUST
  return 404 (PD-3), so a typo or purged account is never reported as a
  successful revoke.
- **FR-008**: Every admin authorization denial and every successful lookup or
  revoke MUST be recorded through the existing application logger, per this
  matrix — a single "always identify the operator and the target" rule is
  impossible, because an unauthenticated caller has no resolved operator and a
  denial that resolved a target would violate deny-before-touch (FR-002):

  | Event | Required fields | Deliberately absent |
  | --- | --- | --- |
  | 401 (no valid session) | correlation id, route template, event, outcome | operator id (none is resolved), target id |
  | 403 (authenticated non-operator) | correlation id, route template, event, operator account id, outcome | target id — none may be resolved before the denial |
  | 404 (allow-listed operator, flag not effective) | correlation id, route template, event, operator account id, outcome | target id |
  | successful lookup | operator account id, **resolved** target account id, outcome | the submitted query key |
  | successful revoke | operator account id, **resolved** target account id, outcome, revoked count | the submitted path value |

  No record may include email, display name, credentials, tokens, session
  hashes, member content, or raw request input — including the raw lookup
  query string (which may itself be an email) and the raw revoke path value;
  the route **template** is logged, not the interpolated path. Records for the
  capability check (FR-011) MUST be distinguishable from records for lookup
  and revoke, so the denial stream stays a usable signal.
- **FR-009**: The admin mutation MUST rely on the repository's existing
  same-origin protections (no CORS allow-list, `SameSite=Lax` session
  cookie) already enforced for every other mutating route; this feature adds
  no new cross-origin or CSRF mechanism. Both relied-upon properties MUST be
  pinned by an automated check so their removal is detected.
- **FR-010**: No existing member-facing route, response shape, cookie
  behavior, or screen may change as a result of this feature, **with exactly
  one exception: the FR-012 rejection of a configured operator address by
  signup and self-service email change.** That exception is bounded to the
  rejection itself — no other input, response shape, status code, cookie,
  route or screen changes, and the rejection is byte-identical to the existing
  already-registered refusal. In particular the `feature_flags` map returned by
  `/api/auth/me`, `/api/auth/login` and `/api/auth/signup` MUST NOT gain an
  `admin_portal` key, so the rollout state is never broadcast to a member who
  can never use it. No member-facing screen may issue an admin request as part
  of ordinary navigation (PD-1).
- **FR-011**: `/admin` MUST determine the caller's operator capability from a
  server-side check scoped to that route. The check MUST NOT run from the
  application shell or any other screen. Its denial for a non-operator MUST
  NOT be indistinguishable, in the logs, from a denial on the lookup or revoke
  routes (FR-008).
- **FR-012**: Operator authority MUST NOT be claimable by a member. A
  configured operator address is reserved: signup and self-serve email change
  MUST refuse to bind an account to an address on the allow-list, while the
  startup admin seed path MUST still be able to provision the configured
  identity. Claiming a reserved address MUST fail with the existing conflict
  behavior and MUST NOT disclose that the address is an operator address.
- **FR-013**: Every `/admin` API route and the `/admin` screen MUST be gated
  by a rollout flag that is **OFF by default**, following the existing
  allow-listed feature-flag mechanism (ADR-0008: flags are exposure control,
  never authorization — the flag is in addition to FR-002, never instead of
  it). **Authorization is evaluated first, and the precedence is fixed** — with
  `admin_portal` not effective: an unauthenticated caller MUST get 401, an
  authenticated non-operator MUST get 403, and only an allow-listed operator
  MUST get the feature-absent 404 (the repository's existing convention for an
  ineffective flag). Every non-operator response is therefore flag-invariant,
  so the rollout state is observable only to someone who is already an
  operator. Denial records follow the FR-008 matrix, including the 404 row.
  The production flag state is the `BRAIN_BUDDY_FEATURE_FLAGS` value staged by
  `.github/workflows/deploy-fly-production.yml`, restaged on every release. On
  this first release that value deliberately **omits** `admin_portal`, which is
  the OFF state: a staged secret survives an image swap, so naming a flag the
  rolled-back pre-009 image cannot parse would crash-loop it at startup.
  Turning the portal on later is an edit to that ASK-class line plus a deploy —
  never a `flyctl secrets set` — and is safe only once the image a rollback
  would restore already knows the name.

## Success Criteria

- **SC-001**: An allow-listed operator can find an existing account by ID and
  by canonical email and sees exactly the four FR-004 fields each time; a
  prefix or near-match of that same account returns no match.
- **SC-002**: Every `/admin` route returns 401 for an unauthenticated caller
  and 403 for an authenticated non-operator — in **both** flag states — with
  no account data in either response, no repository lookup performed (proved
  by poisoning the target-facing service methods, not only by comparing two
  bodies), and the target account's sessions still valid afterwards.
- **SC-003**: Revoking sessions for an existing account with zero active
  sessions returns a 2xx response reporting 0 revoked; revoking for an
  account ID that does not exist returns 404; revoking an account with two
  concurrent sessions invalidates both.
- **SC-004**: For each of the required events — 401 denial, 403 denial on the
  capability check, 403 denial on a data route, successful lookup, successful
  revoke — a log record exists that carries exactly the fields the FR-008
  matrix requires for that event (and not the ones it marks absent), and no
  record contains an email address, display name, credential, token, session
  hash, or raw request body (verified by test assertion against captured log
  records, using distinctive sentinel values planted in the display name and
  the request body).
- **SC-005**: Admin access records exist only as content-free application log
  output, proved executably: a distinctive sentinel planted in a real admin
  record is present in the log stream and absent from every name, manifest
  count and byte of `GET /api/account/export`, and an account purge leaves it
  in place. `docs/data-retention.md` names this processing category and
  `frontend/src/pages/PrivacyPolicyPage.tsx` — the user-facing summary that
  document requires to stay in sync — states the purpose, its legal basis, the
  platform-log retention, and the export/purge exclusion.
- **SC-006**: A member who never visits `/admin` issues no request to any
  `/admin` route during ordinary navigation, and a member whose email is
  changed to a configured operator address cannot be created — the change is
  refused and every `/admin` route still answers them 403.
- **SC-007**: With `admin_portal` OFF, every `/admin` API route is
  unavailable to an allow-listed operator, and turning the flag on restores
  the behavior in SC-001..SC-003 without any other change.

## Manual Acceptance Checks

Use a **purpose-seeded, non-real account** (an `@example.com` address created
for the check). Any pasted output or screenshot must have the account ID and
email redacted before it enters PR or acceptance evidence — constitution
Principle I forbids real user data there, and this feature's found-state and
confirm dialog both render an email on screen.

- Sign in as the seeded operator, look up the seeded check account by ID then
  by email, confirm the rendered fields match FR-004 exactly (no password
  hash, no session data, no other account's data).
- Sign in as a non-operator member, navigate directly to `/admin`, and confirm
  it shows a generic denied state with no account form — and that no admin
  entry appears anywhere in the account menu or navigation (PD-1).

## Out of Scope

Partial/prefix search, pagination, bulk actions, account edit or delete,
role assignment/delegation, a native iOS admin surface, offline admin, a
generalized audit-history UI or audit database/lifecycle platform, a
per-account generation subsystem, a durable operation state machine, a
step-up auth system, a generalized rate limiter, a distributed protocol, a
dedicated operator account or operator-only secret, global navigation or
menu discoverability for `/admin`, impersonation, a separate admin site, or
any other invented infrastructure not already present on `origin/main`.

## Assumptions

- An operator is an existing authenticated member account whose normalized
  email is on the allow-list; this feature does not introduce a separate
  admin credential or login flow. In production that account is the one
  `seed_admin` provisions from `BRAIN_BUDDY_ADMIN_EMAIL` (PD-2). FR-012 turns
  the "existing account" half of this assumption into an enforced invariant
  rather than a hope.
- The existing session cookie (`HttpOnly`, `SameSite=Lax`) and the absence of
  a CORS allow-list are sufficient same-origin protection for the mutation,
  matching every other mutating route in the backend today.
- **Primary loop:** `/admin` has no effect on the capture → atomic items →
  clarify/approve → route/CRT → Weekly Review → evidence loop (constitution
  Principle V). It is operator tooling reached only by direct URL.
- **Viewport:** `/admin` is expected to remain usable at a 390×851 viewport
  because it reuses the existing responsive form components, but it is not
  designed for mobile operation and no mobile-specific evidence is required.
- Session revoke is **irreversible**: a revoked member must sign in again on
  every device. There is no undo, which is one of the inputs to this
  feature's ASK landing class ([plan.md](plan.md)).
