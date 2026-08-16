# ADR-0020: Ratify RTM priority and lossless List archive semantics

- **Status**: Accepted
- **Date**: 2026-08-15
- **Decision owner**: Max (founder)
- **Supersedes in part**: ADR-0006, only its `Priority` vocabulary/sort mapping and
  its Project archive assignment-clearing rule
- **Related**: feature 011 (`specs/011-rtm-task-parity/`), ADR-0011, ADR-0012

## Context

ADR-0006 established the first native GTD baseline. It deliberately chose public
priority values `none|low|medium|high` and required Project archive to clear every
member Task's `project_id`. Feature 011 adds RTM task-management parity and exposes two
costs of those choices:

1. the private word-based priority vocabulary differs from the intended public task
   contract; and
2. clearing membership makes archive destructive to organization, so unarchive cannot
   restore the List with its members.

Campaign 1 correctly treated changing either accepted rule as a founder decision. On
2026-08-15 Max explicitly selected numeric priority and retained archive membership as
named answers HD-01 and HD-03. This is not an automated inference and is not the
run-bound high-risk sign-off required by ADR-0012.

## Decision

### Public Priority contract

The public and eventual stored priority vocabulary is:

```text
1 | 2 | 3 | none
```

`1` is highest. User-facing labels are exactly:

- `1 — High`
- `2 — Medium`
- `3 — Low`
- `None`

The reversible value mapping is `high ↔ 1`, `medium ↔ 2`, `low ↔ 3`, and
`none ↔ none`. Priority remains independent of due date, lifecycle, and agent
Execution/Run state. Priority ordering is `1, 2, 3, none`, followed by the existing
total tie-breakers.

This decision does not authorize a lockstep breaking deploy. Feature 011 must use a
staged dual-read compatibility window, a safe legacy response fallback, a reversible
rewrite of both SQLite JSON payloads and compatibility mirrors, and an operational gate.
The default response/stored vocabulary may switch only after the release-evidence owner
has verified every active internal backend, web, and installed mobile build.

### Lossless List archive

Archiving a regular List changes the List from active to archived while retaining every
member Task's `project_id`, including open, completed, cancelled, and trashed Tasks.
Archive changes no Task lifecycle or Trash state. The archived List leaves active
navigation and accepts no new assignment until unarchived, but its name remains resolvable
for existing members and its tasks remain governed by their own lifecycle/query rules.

An unrelated Task PATCH may retain its existing archived List membership. Explicitly
clearing that membership or moving to an active List is valid; assigning a different Task
to an archived List remains invalid. Unarchive restores the List to active navigation
with membership intact.

List deletion remains a separate, confirmed, irreversible operation: it clears the List
ID from every member Task and deletes the List record without deleting a Task. Existing
archived Lists whose memberships were already cleared by the ADR-0006 behavior cannot be
reconstructed and receive no speculative backfill.

## Scope of supersession

This ADR supersedes only:

- ADR-0006 `## Field and query semantics` → `### Priority`, including its public values
  and priority sort mapping; and
- ADR-0006 `## Organization semantics`, only the sentence requiring Project archive to
  clear `project_id` from every member Task, plus capability row B-29's prescribed
  assignment-cleanup fix.

Every other ADR-0006 rule remains accepted, including the six commitment states,
explicit reopen destination, Waiting metadata, owner isolation, optimistic concurrency,
idempotent command handling, Task/Run separation, and Tag terminology.

## Consequences

**Positive.** Public priority matches the chosen RTM-shaped contract, and archive becomes
reversible in the sense users expect: unarchive recovers the same List membership.

**Costs.** Numeric priority requires a high-risk staged migration across independently
updated clients. Retained archive membership requires active-only assignment validation
to distinguish a carried reference from a new assignment, and every task renderer must be
able to resolve archived List names.

**Historical limit.** The decision cannot recover assignments already removed under the
old archive behavior. The migration and UI must state that limit rather than fabricate
membership.

**Gate limit.** This accepted product decision resolves HD-01, HD-02, and HD-03. It does
not constitute ADR-0012 human sign-off for a campaign, does not bind approval to an
artifact digest, and does not permit implementation before the review gate closes.

## Alternatives rejected

**Keep word priorities.** Rejected by Max because the public feature contract is numeric.

**Archive clears membership.** Rejected because the action cannot be losslessly undone;
unarchive would restore an empty container.

**Retain membership and allow assignment to archived Lists.** Rejected because archive
would no longer remove a List from active organization. Existing membership is retained;
new assignment waits for unarchive.
