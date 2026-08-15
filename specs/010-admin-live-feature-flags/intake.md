# Business Intake: Live Feature-Flag Management in the Admin Portal

**Feature**: `specs/010-admin-live-feature-flags/` · **Date**: 2026-08-14
**Interviewee**: BrainBuddy founder, via written brief (single-session,
non-interactive run)

No live elicitation was possible: `AskUserQuestion` is unavailable to a
non-interactive session, and the brief that opened this run is itself the
human interview and clarification evidence. Everything below is transcribed or
directly derived from it; nothing was invented and nothing was asked back.

## The ask, as given

> Implement and release live feature-flag management inside the existing
> `/admin` portal.

Frozen product slice, transcribed:

1. An authorized operator can set each known flag to exactly one of **OFF**,
   **ON**, or **SELECTED_USERS**.
2. In `SELECTED_USERS` mode, **exact-account lookup** is used to add and remove
   users. No general user directory is added.
3. Changes take effect for **already logged-in browser users without
   logout/login**, using a bounded simple mechanism. Default mechanism: refetch
   `/api/auth/me` every 15 seconds while authenticated, plus an immediate
   refetch on window focus and on visibility becoming visible. No WebSockets,
   no SSE.
4. The **server is authoritative**. Flags are exposure control, never
   authorization.
5. Runtime flag state is **durable on the existing backend data volume**,
   **atomic and concurrency-safe**, and **default/fallback compatible** with
   the current env-based rollout and with the existing rollback path.
6. The existing feature 009 admin authorization and privacy contracts are
   **preserved**, not re-litigated.
7. The UI shows current mode, the selected-user count and a list sufficient to
   remove a user, save/error/loading states, and updates the operator's view
   after a mutation.

Explicit non-goals, transcribed: a separate feature-flag service; percentage
rollouts; segments or groups; schedules; environments; an audit database or
audit UI; a global user list; mobile changes; arbitrary flag creation;
generalized governance; and a deploy-workflow redesign unless strictly required
by rollback compatibility.

Planning authority, transcribed: reviewer proposals for adjacent hardening do
not expand this scope.

## 1. Problem

Rollout state is currently a single deploy-staged environment string
(`BRAIN_BUDDY_FEATURE_FLAGS` in `.github/workflows/deploy-fly-production.yml`).
Changing who sees a feature therefore means editing an ASK-class workflow line
and running a full release; an out-of-band `flyctl secrets set` is reverted by
the next deploy. The cohort itself
(`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`) is one global list shared by every
flag, so "let this person try voice brain dump" and "let this person try the
relay" cannot be answered separately. There is no way to move one person into
or out of a rollout in minutes, and no way for that change to reach a browser
session that is already open.

## 2. Who is affected

- **Operators** (the feature 009 allow-list; in production exactly the seeded
  admin identity) gain a live rollout control.
- **Members** are affected only in that a capability they already had gated
  can appear or disappear without them signing out. No member-facing response
  shape changes and no new member-facing screen exists.

## 3. Success, in the founder's terms

An operator opens `/admin`, sets a known flag to OFF, ON or SELECTED_USERS,
adds or removes one exactly-identified account, and an already-open browser
session picks the change up within about fifteen seconds — with the state
surviving a restart and a redeploy, and with a rollback to the previous image
landing back on exactly the env-configured rollout.

## 4. Out of scope (explicit)

A separate feature-flag service or vendor; percentage or gradual rollouts;
segments, groups or rules; scheduled changes; multiple environments; an audit
database, audit history API or audit UI; a global user list or user directory;
any mobile client change; creating or deleting flag names at runtime;
generalized permission governance or roles; and any redesign of the deploy
workflow. See [spec.md](spec.md) for the enforced boundary.
