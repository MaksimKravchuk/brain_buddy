# Feature Specification: Minimum Admin Portal

**Feature Branch**: `feat/009-admin-portal-minimum` · **Created**: 2026-08-13
**Status**: In implementation.
**Input**: see [intake.md](intake.md) for the founder's ask, verbatim.

A web-only `/admin` surface for a small, explicitly allow-listed set of
operators to find one member account and revoke its sessions. Reuses the
existing session-cookie auth, the `SessionRepository` bulk-delete capability,
and the API envelope/logging conventions already in the backend; adds no new
subsystem.

## User Scenarios & Testing

The "user" is an allow-listed operator (founder/support), authenticated the
same way any member is. See [design.md](design.md) for the single screen.

1. **Operator looks up an account by ID.** An allow-listed operator, signed
   in, opens `/admin`, enters an account ID, and sees exactly: account ID,
   canonical email, optional display name, deletion-requested state.
2. **Operator looks up an account by email.** Same as above, entering a
   canonical email instead; only an exact match is returned.
3. **No match.** The operator enters an ID or email with no exact match; the
   portal reports "not found" and discloses nothing else.
4. **Operator revokes sessions.** After a successful lookup, the operator
   clicks revoke, confirms in an explicit second step, and every current
   session for that account is deleted. A repeat revoke on an account with no
   active sessions still reports success (revoked count 0).
5. **Non-operator is denied.** A signed-in member whose email is not on the
   allow-list gets a 403 from every `/admin` API route, before any lookup or
   mutation runs; the portal shows a generic access-denied state.
6. **Unauthenticated caller is denied.** A caller with no valid session gets
   401 from every `/admin` API route.
7. **Existing journeys are untouched.** Every non-admin route, cookie and
   response shape behaves exactly as before this feature.

## Requirements

- **FR-001**: The backend MUST maintain an explicit, server-owned operator
  allow-list of normalized email addresses, sourced from configuration (not
  request input, not a database table an operator can self-edit).
- **FR-002**: Every `/admin` API route MUST require a valid session AND
  allow-list membership, checked server-side, before any account lookup or
  mutation logic runs. An unauthenticated caller MUST get 401; an
  authenticated non-operator MUST get 403.
- **FR-003**: The account-lookup endpoint MUST accept exactly one of an
  immutable account ID or a canonical email per request and return an exact
  match only — no partial, prefix, or fuzzy search.
- **FR-004**: A successful lookup response MUST contain only: account ID,
  canonical email, optional display name, and deletion-requested state.
  No other stored field may be returned.
- **FR-005**: The `/admin` frontend route MUST be web-only, reachable only to
  a signed-in caller, and MUST render only the four fields in FR-004 for a
  found account.
- **FR-006**: The frontend MUST require an explicit confirmation step,
  separate from the initial click, before the session-revoke request is
  sent.
- **FR-007**: The revoke endpoint MUST use the existing
  `SessionRepository.delete_all_for_user` bulk-delete capability and MUST be
  idempotent: revoking an account with zero active sessions returns success
  with a revoked count of 0, not an error.
- **FR-008**: Every admin authorization denial and every successful lookup or
  revoke MUST be recorded through the existing application logger, and MUST
  NOT include email, display name, credentials, tokens, session hashes,
  member content, or raw request input — only operator/account identifiers
  and outcome.
- **FR-009**: The admin mutation MUST rely on the repository's existing
  same-origin protections (no CORS allow-list, `SameSite=Lax` session
  cookie) already enforced for every other mutating route; this feature adds
  no new cross-origin or CSRF mechanism.
- **FR-010**: No existing member-facing route, response shape, or cookie
  behavior may change as a result of this feature.

## Success Criteria

- **SC-001**: An allow-listed operator can find an existing account by ID and
  by canonical email and sees exactly the four FR-004 fields each time.
- **SC-002**: Every `/admin` route returns 401 for an unauthenticated caller
  and 403 for an authenticated non-operator, with no account data in either
  response.
- **SC-003**: Revoking sessions for an account with zero active sessions
  returns a 2xx response reporting 0 revoked, not an error.
- **SC-004**: No log line emitted by this feature contains an email address,
  display name, or raw request body (verified by test assertion against
  captured log records).

## Manual Acceptance Checks

- Sign in as a seeded operator, look up a real account by ID then by email,
  confirm the rendered fields match FR-004 exactly (no password hash, no
  session data, no other account's data).
- Sign in as a non-operator member and confirm `/admin` shows a generic
  denied state with no account form.

## Out of Scope

Partial/prefix search, pagination, bulk actions, account edit or delete,
role assignment/delegation, a native iOS admin surface, offline admin, a
generalized audit-history UI or audit database/lifecycle platform, a
per-account generation subsystem, a durable operation state machine, a
step-up auth system, a generalized rate limiter, a distributed protocol, or
any other invented infrastructure not already present on `origin/main`.

## Assumptions

- An operator is an existing authenticated member account whose normalized
  email is on the allow-list; this feature does not introduce a separate
  admin credential or login flow.
- The existing session cookie (`HttpOnly`, `SameSite=Lax`) and the absence of
  a CORS allow-list are sufficient same-origin protection for the mutation,
  matching every other mutating route in the backend today.
