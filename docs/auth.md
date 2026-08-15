# Authentication

Brain Buddy uses email+password accounts with server-side opaque sessions. This doc is the threat model in plain English — refer back when you need to understand why a control is shaped the way it is.

## The ten decisions that matter

1. **Passwords are hashed with Argon2id** (`argon2-cffi`). Argon2 is the current recommendation — slow, memory-hard, resists GPU cracking. Plaintext passwords are never stored. If the `data/` directory leaks, hashes alone don't grant access.

2. **Sessions are opaque random tokens** generated with `secrets.token_urlsafe(32)` (256 bits of entropy). The token is set in an HTTP-only cookie. Server-side, only the SHA-256 hash of the token is persisted (`data/sessions/<sha256>.json`), so a disk leak cannot be replayed. Logout deletes the file — instant revoke.

3. **Cookies are `HttpOnly` + `SameSite=Lax` + `Secure` (in prod)** with a 30-day expiry and `Path=/`. JavaScript cannot read the cookie (XSS can't steal it), and browsers will not attach it to cross-site POSTs (blocks most CSRF). `Secure=True` is automatic in production so the cookie is only ever sent over HTTPS.

4. **Same-origin in both dev and prod.** In production the Fly frontend app proxies `/api` to the private backend. In development, `vite.config.ts` proxies `/api` and `/health` to `http://localhost:8000`. Same-origin eliminates CORS complexity and closes the cross-site CSRF hole, which is why no CSRF tokens are needed.

5. **Login never leaks whether an email exists.** Wrong-user and wrong-password both return "Invalid email or password." The wrong-user branch runs an Argon2 verify against a dummy hash so the timing matches the wrong-password branch. This prevents account enumeration.

6. **Login is rate-limited per source IP** — 10 attempts per 10 minutes, held in memory. Simple, loses state on restart (acceptable at current scale), blocks basic brute force. Documented as a known limitation — a real service would also limit per-email and persist counters across restarts.

7. **Passwords must be ≥12 and ≤128 characters.** Length beats complexity rules (NIST guidance). The upper bound prevents a DoS via 10 MB passwords locking up an Argon2 worker.

8. **Invites are one-shot random codes** minted via CLI (`python -m app.cli create-invite`) and stored under `data/invites/`. Signup consumes exactly one invite; re-using a used invite fails. This is what "invite-gated signup" means — there is no open registration.

9. **Ownership is checked on every tree read and mutation.** Wrong owner returns **404**, not 403, so a user can't probe tree IDs to find ones that exist. Every route in `app/api/routes.py` calls `tree_service.assert_owner` (or `get_tree_for_owner`) before delegating to a child service.

10. **Imported trees get `owner_id` stamped to the importing user** and are assigned a fresh tree id. An attacker cannot craft an import payload that claims ownership of someone else's tree id or pollutes with a specific `owner_id`.

## Creating an invite

```bash
docker compose exec backend python -m app.cli create-invite
```

The command prints a URL-safe code. Share it with the user who should sign up — they enter it on `/signup`. It can only be used once.

## Seeding an admin account from environment variables

If you want a known account to exist on startup without SSHing in to mint an invite — useful on Fly where you want to bootstrap your own account from a secret — set both of these environment variables:

- `BRAIN_BUDDY_ADMIN_EMAIL` — the email the seeded account should have
- `BRAIN_BUDDY_ADMIN_PASSWORD` — the password; must satisfy the password policy (≥12 characters)

On startup the backend will:

1. **Create** the account if no user with that email exists. The invite flow is bypassed entirely.
2. **Rotate** the stored password hash if the user exists and the password in the env var doesn't match. This gives you "env is the source of truth" semantics — change the Fly secret and redeploy to rotate.
3. **Refuse to start** if the password is shorter than the policy minimum. A misconfigured deploy fails loudly instead of silently skipping and leaving you locked out.

On Fly:

```bash
fly secrets set \
  BRAIN_BUDDY_ADMIN_EMAIL=you@yourdomain.com \
  BRAIN_BUDDY_ADMIN_PASSWORD='a-long-random-password' \
  -a <backend-app>
```

### The seeded account now carries operator privilege in production

This changed with the minimum admin portal (spec 009, [ADR-0017](decisions/0017-operator-account-administration-narrow-owner-scoping-exception.md)). The seeded account used to be a normal account that merely happened to exist at boot. It is no longer:

- The `/admin` portal authorizes operators from `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`, a server-owned, fail-closed allow-list (`.env.example` documents the format).
- **In production that list comes from the dedicated `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` production environment secret**, staged by `.github/workflows/deploy-fly-production.yml` on every release. It is deliberately independent of the rotating smoke admin identity.
- An operator can look up any account (id, canonical email, optional display name, deletion-requested state) and revoke every session for any account. Member *content* — trees, tasks, voice operations, exports — stays owner-scoped and is not reachable; ADR-0017 bounds the exception to those two operations.
- An operator can also change, without a deploy, which members are exposed to the three runtime-manageable rollout flags (`voice_brain_dump`, `mobile_task_classification`, `external_agent_relay`): set each to off, on, or a named list of accounts. There is no deploy default left to clear or inherit — each flag's row in the SQLite store is the entire answer. This is exposure control, never authorization — no authorization decision reads a runtime-managed flag. `/admin` itself is never gated by a flag: an authorized, allow-listed operator always reaches the portal. See [ADR-0019](decisions/0019-sqlite-runtime-feature-flag-store.md) for the three-flag scope, the audit and purge obligations, and the migration from the prior JSON-overlay design.

**Credentials for an account named in `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` are therefore admin-grade credentials.** A leak confers cross-account lookup and session revoke over every member. The production smoke credentials are managed separately and do not grant operator authority unless that address is also deliberately included in the operator allow-list.

Two operational consequences worth knowing before you touch it:

- Rotating `BRAIN_BUDDY_ADMIN_EMAIL` changes the smoke identity without transferring operator power.
- Change the GitHub production environment secret `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` to change operators; direct Fly secret edits are reverted by the next deploy.

A configured operator address is **reserved**: signup and self-serve email change refuse to bind an account to it, so nobody can grant themselves operator power by moving their account onto a listed address. Only the seed path above may provision that identity.

Outside production, an empty `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` (the default) means nobody is an operator and `/admin` is unreachable.

## Account management (GDPR data rights)

`/api/account` gives every signed-in user self-serve control over their data
(see `docs/data-retention.md` for retention and purge mechanics):

- **Profile** — `PATCH /api/account/profile` sets a display name.
- **Email change** — `POST /api/account/email` re-checks the current password
  and rewrites the email index atomically. A conflicting address returns the
  same generic 400 as any other rejection so the endpoint is not an
  account-enumeration oracle.
- **Password change** — `POST /api/account/password` re-checks the current
  password, enforces the signup policy, and revokes every *other* session.
- **Export** — `GET /api/account/export` streams a ZIP of everything the
  account owns (never the password hash or session records).
- **Deletion** — `POST /api/account/delete` deactivates the account (all
  sessions revoked) and schedules a hard purge after a 14-day grace period.
  Logging back in inside the grace period cancels the deletion; past-due
  logins fail with the generic credential error. The maintenance sweep (and
  `python -m app.cli purge-due-accounts`) performs the purge.

The three credential-sensitive actions return **403** on a failed password
re-check (401 is reserved for "session gone") and share a per-user in-memory
rate limit (10 attempts / 10 minutes).

## Known limitations (ordered by urgency if you scale)

| Limitation | How to fix later |
|---|---|
| In-memory rate limiters (login per-IP, sensitive actions per-user) lose state on restart. | Move to a small persistent store (SQLite, `data/rate_limit.json`). |
| Login limiting is per-IP only — an attacker rotating IPs can still brute force a single account. | Add per-email limiting alongside per-IP. |
| No password reset / email verification. | Requires an email provider. Until then, a forgotten password means deleting the user file and re-issuing an invite. |
| Email changes are unverified — a typo'd new address silently corrupts the contact channel (nothing emails users today, but it will matter once reset mail exists). | Send a confirmation link to the new address before switching. |
| Stolen credentials can cancel a pending account deletion by logging in during the grace period. | Require an explicit "keep my account" confirmation after login instead of auto-cancelling. |
| No session list / remote revoke UI. | Add `GET/DELETE /api/auth/sessions` (bulk revocation already exists internally for password change and deletion). |
| No audit log. | Append-only record of logins, signups, deletions. |
| Passwords and sessions live in loose JSON files. | Move to SQLite once you have more than a handful of users. |

None of these are urgent at the current scale, but they're worth knowing about.

## Where the code lives

- **Schemas** — `backend/app/schemas/auth.py`, `backend/app/schemas/account.py`
- **Repositories** — `backend/app/repositories/{user,session,invite}.py`
- **Auth service** — `backend/app/services/auth_service.py`
- **Account service (profile, export, deletion)** — `backend/app/services/account_service.py`
- **Routes** — `backend/app/api/auth.py`, `backend/app/api/account.py`
- **Dependency injection** — `get_current_user` in `backend/app/api/dependencies.py`
- **Rate limiter** — `backend/app/core/rate_limit.py`
- **CLI** — `backend/app/cli.py`
- **Frontend auth store** — `frontend/src/stores/authStore.ts`
- **Frontend pages** — `frontend/src/pages/{LoginPage,SignupPage}.tsx`
- **Route guard** — `frontend/src/components/auth/ProtectedRoute.tsx`
