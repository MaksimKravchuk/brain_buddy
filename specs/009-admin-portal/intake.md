# Business Intake: Minimum Admin Portal

**Feature**: `specs/009-admin-portal/` · **Date**: 2026-08-13
**Interviewee**: BrainBuddy founder, via written brief (Hermes → Claude Code)

No live elicitation: this run is non-interactive, so `AskUserQuestion` is
unavailable. Everything below is transcribed from the brief.

## The ask, as given

> Release the minimum admin portal. Do not expand scope.

Frozen product slice, transcribed: (1) an explicit server-owned operator
allow-list, checked server-side on every admin API request; (2) a web-only
`/admin` portal with exact lookup of one account by immutable account ID or
canonical email, returning only account ID, canonical email, optional display
name, and deletion-requested state; (3) explicit confirmation then revoke all
current sessions for that account, reusing the existing session repository
bulk-delete capability, idempotent on zero count; (4) a minimal internal
content-free security audit via existing application logging conventions;
(5) fail-closed authorization with no target-dependent disclosure on denial,
and same-origin protection for the mutation using existing repository
conventions; (6) existing member journeys unchanged.

Explicit non-goals, transcribed: partial search, pagination, bulk actions,
account edit/delete, role assignment/delegation, native iOS admin UI, offline
admin, generalized governance, exhaustive protocol catalogues, and new
subsystems built only to satisfy speculative reviewer findings.

Planning authority, transcribed: prior managed requirements panels for this
feature were declared non-convergent by the founder; their findings are
historical evidence, not a mandate. This package does not re-run an
open-ended requirements panel — it is authored directly against the frozen
slice above, using founder-accepted risk-acceptance mechanisms only where a
repository validator requires one, and recording the actual review status
rather than a fabricated verdict.

## 1. Problem

Support and moderation currently has no way to find one member's account or
force-revoke its sessions without direct data-store access. That is an
operational gap for account-recovery and abuse-response requests.

## 2. Who is affected

A small, explicitly allow-listed set of operators (founder/support). No
change reaches members outside an operator-initiated lookup.

## 3. Success, in the founder's terms

An allow-listed operator can find one account by its ID or canonical email
and revoke its sessions, from a web page, with nothing else exposed and
nothing else built.

## 4. Out of scope (explicit)

Partial/prefix search, pagination, bulk actions, account edit/delete, role
assignment or delegation, a native iOS admin surface, offline admin, a
general-purpose governance or audit-history platform, and any new
subsystem (durable operation state machine, step-up auth, generalized rate
limiter, distributed protocol) unless current `origin/main` already has it
and failing evidence proves it necessary. See [spec.md](spec.md).
