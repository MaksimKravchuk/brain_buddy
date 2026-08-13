# ADR-0017: Operator account administration is a narrow exception to owner scoping

Date: 2026-08-13
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0008, ADR-0012
Supersedes: nothing. Narrows one assumption in ADR-0001 going forward.

## Context

ADR-0001, "Authorization and privacy assumptions", states two rules this
repository has enforced ever since:

> All reads, transitions, references, media, and list queries are owner-scoped.
> A wrong owner receives `404` …
> The MVP has one role: owner. No sharing, teams, delegated execution, or admin
> access to user content.

Feature 009 (`specs/009-admin-portal/`) needs one operator to look up another
member's account record by immutable account ID or canonical email, and to
revoke that account's sessions. Both operations are cross-owner by
construction. Without a recorded decision, the feature either contradicts an
accepted ADR silently, or the ADR is read as forbidding any support and
abuse-response capability at all — the operational gap the feature exists to
close.

ADR-0012 forbids amending an accepted record retroactively, so ADR-0001's text
stays as written. This record states the exception separately and dates it.

## Decision

Owner scoping remains the rule. One exception is added, and it is bounded by
the four sentences below rather than by a general "admin role".

1. **Account administration only.** A server-authorized operator may read the
   account *record* of any account — account ID, canonical email, optional
   display name, deletion-requested state — and may revoke that account's
   sessions. Nothing else crosses the owner boundary.
2. **Member content stays owner-scoped, without exception.** Trees, versions,
   validation history, tasks, projects, tags, subtasks, comments, voice
   operations, transcripts, raw audio, exports and invites remain reachable
   only by their owner. ADR-0001's "no admin access to user content" is
   unchanged and this record does not create a path toward it. An operator
   reaching for member content is a new decision, not an extension of this one.
3. **Authorization is server-owned and not self-assignable.** The operator set
   comes from deployment configuration (`BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`),
   never from request input and never from a table a member can edit. It fails
   closed when unset. Because the matching key is an account attribute, the
   configured addresses are *reserved*: ordinary signup and self-serve email
   change must refuse them, so authority cannot be claimed by moving an account
   onto a listed address. Provisioning the configured identity stays with the
   startup seed path.
4. **The exception is auditable and denies before it touches.** Authorization
   runs before any lookup or mutation, so a denial cannot vary with whether the
   target account exists, and every denial and every successful operation is
   recorded through the existing application logger, content-free.

No new role model, no delegation, no impersonation, no admin data store. This
record authorizes exactly the two cross-owner operations named in point 1.

## Consequences

- ADR-0001's owner-scoping rule now reads with one carve-out: account-record
  reads and session revocation performed by a configured operator. Every other
  read and transition in the system is still owner-scoped and still answers a
  wrong owner with `404`.
- The system gains a privileged identity it did not have. The credential of a
  configured operator is an admin-grade credential and must be handled as one
  (see `docs/auth.md`).
- The audit obligation is real but deliberately minimal: content-free log
  records, retained for the platform log window, excluded from a member's data
  export and not reached by account purge (see `docs/data-retention.md`). That
  disposition is a controller decision, recorded there rather than left to
  omission.
- Changes to this boundary are ASK class under ADR-0008 — they touch
  authentication/privacy enforcement — and never land automatically.
- Anything beyond point 1 (roles, delegation, impersonation, access to member
  content, an audit-history platform) requires its own ADR. Citing this record
  is not sufficient.
