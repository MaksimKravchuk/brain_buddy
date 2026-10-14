# Contract: test control API (027)

Black-box suites (conformance, Playwright E2E, Swift/Rust rehearsal, CLI
journey) seed data and control time only through this API. It replaces every
Python hook used today (`python -m app.cli create-invite`, inline
`python -c` with `build_container`, `review-seed-aged-task`,
`review-run-sweep`, `scripts/rehearsal/ui_backend.py` `seed_stalled`,
`modern_auth_e2e_app.py` monkeypatching).

Both servers implement it identically until cutover (research R4).

## Availability

- Mounted under `/api/__test__/` **only** when `BRAIN_BUDDY_ENV=test`. In any
  other environment the prefix is not routed (404 like any unknown path) and
  the startup log states that test control is disabled.
- Requires header `X-Test-Control-Token` equal to `BRAIN_BUDDY_TEST_CONTROL_TOKEN`
  (required when `BRAIN_BUDDY_ENV=test`; the server refuses to start without it).
- Every response carries `X-Correlation-ID`; errors use the normal error
  envelope.
- Production images are built without the feature (`cfg(feature =
  "test-control")` on the Rust server); a CI check asserts the production
  image binary does not contain the routes.

## Operations

| Method + path | Body | Effect | Replaces |
| --- | --- | --- | --- |
| `POST /api/__test__/invites` | `{ "count": 1 }` | returns invite codes | `app.cli create-invite` |
| `POST /api/__test__/admin` | `{ "email", "password" }` | creates an operator account | `auth_service.seed_admin` via container |
| `PUT /api/__test__/flags/{key}` | `{ "mode": "off"\|"on"\|"selected", "owners": [] }` | sets a feature-flag mode without the admin UI | `feature_flag_service` via container |
| `POST /api/__test__/clock` | `{ "advance_seconds": n }` or `{ "set": RFC3339 }` | moves the server clock used by tasks, review, sync retention, jobs, sessions | `FrozenClock`, `seed_stalled` |
| `DELETE /api/__test__/clock` | — | back to wall clock | — |
| `POST /api/__test__/sweeps/{name}` | `{}` | runs one named sweep now (`review`, `retention`, `purge`, `voice`, `agents`) and returns its counters | `app.cli review-run-sweep` |
| `POST /api/__test__/review/aged-task` | `{ "owner_email", "days" }` | seeds an aged formulation for Review | `app.cli review-seed-aged-task` |
| `GET /api/__test__/owners/{email}/tasks` | — | read-back of an owner's tasks for assertions | `admin-users.spec.ts` inline Python |
| `PUT /api/__test__/providers/{kind}` | `{ "mode": "mock", "script": [...], "hold": false }` | scripts mock AI/STT/identity/SMTP providers; with `"hold": true` each call blocks until released, so a test can revoke consent or start deletion while a request is in flight | `modern_auth_e2e_app.py` transports |
| `GET /api/__test__/providers/{kind}/calls` | — | call ledger: count, purpose, owner id, correlation id (no content) — proves "zero provider calls" | — |
| `POST /api/__test__/providers/{kind}/release` | `{ "count": n }` | releases held calls | — |
| `GET /api/__test__/mail` | — | captured outbound mail (synthetic owners only) | SMTP capture |
| `POST /api/__test__/reconcile` | `{}` | runs the SC-007 receipt↔feed reconciliation and returns counters | — |

Every operation is idempotent under its inputs except invite minting, which
returns fresh codes.
