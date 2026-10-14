# Contract: invite step for a new identity (027)

Realizes spec FR-007 (every account creation requires an invite) for the
identity methods that today create accounts without one — email code, Sign in
with Apple (web and native), Google — and design D-04 (web). The CLI browser
grant (ADR-0029) only binds an existing browser session and never creates an
account, so it is unaffected. Design
and M-03 (iPhone). The Mac app offers only password sign-in and never creates
accounts (design D-05 not applicable). Password signup keeps its existing
invite field (`POST /api/auth/signup`).

## Completion response for a new identity

The existing completion routes (inventory CAP-HTTP-013 `POST /api/auth/email/verify`,
CAP-HTTP-019 `POST /api/auth/providers/complete`, CAP-HTTP-020
`POST /api/auth/providers/apple/native/complete`) behave as today for an
identity that already has an account. For a verified identity **without** an
account they answer:

```
403  { "message": "An invite code is required to create an account.",
       "detail": { "code": "INVITE_REQUIRED",
                   "pending": "<opaque handoff token>",
                   "expires_in": 600 } }
```

- Nothing is created: no user, no session, no invite consumed.
- `pending` is a random opaque token (not a JWT), stored hashed in
  `identity.pending_signups` with the verified identity (issuer + subject or
  email), the binder/session it was issued to, and an expiry of 10 minutes.
  Single use.
- Correlation ID as always; the error envelope is the existing modern-auth
  envelope (inventory CAP-MW-010) with the new code.

## Resubmission

```
POST /api/auth/signup/complete
{ "pending": "<token>", "invite_code": "<code>" }
```

- Gated by the release epoch (first-party clients only).
- In one transaction: verify the pending token (exists, unexpired, unused,
  issued to this binder/session), verify the invite (exists, unused,
  unexpired), create the user and external identity, consume the invite,
  consume the pending token, create the session (cookie per FR-007). All or
  nothing.
- Responses:
  - `200` `AuthCompletion` (same shape as today's completion).
  - `400 INVITE_INVALID` — unknown, used or expired invite; one message for
    all three so the reply does not reveal which codes exist (design D-04/M-03
    .03). The pending token stays usable until it expires.
  - `410 SIGNUP_EXPIRED` — pending token unknown, expired, used or bound to
    another session (design .04 "Back to sign in").
  - `429` with `Retry-After` — the existing login rate limit applies per IP
    and per pending token (design .07).
- Every outcome is in the conformance suite as `change` rows (Rust-only
  evidence) for the inventory rows above.

## Native

`POST /api/auth/providers/apple/native/complete` returns the same
`INVITE_REQUIRED` body; the iPhone shows M-03 and resubmits through
`/api/auth/signup/complete`.
