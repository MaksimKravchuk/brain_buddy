# Intake: RTM task-management parity

**Feature**: `011-rtm-task-parity`
**Branch**: `feat/011-rtm-task-parity`
**Created**: 2026-08-15
**Stage**: intake / founder clarification complete; implementation gated
**Interview mode**: projected brief plus named founder answers — see "Provenance" below.

## Provenance and its limits

`/speckit-interview` requires `AskUserQuestion` in the main session. This intake was
**not** produced that way. It began as a faithful projection of the portable founder-brief
snapshot embedded in `research.md` (2026-08-15), which fixed the outcome, frozen scope,
and named reversible defaults. The repository no longer depends on the original temporary
file or on any machine-local path.

What that buys and what it does not:

- Everything in "Business requirements" and "Founder-set defaults" is quoted from or
  directly entailed by the brief. It is founder-authored, not agent-inferred.
- Two defaults contradicted ADR-0006. They remained open through campaign 1 and were not
  silently absorbed.
- On 2026-08-15 Max (founder) explicitly answered campaign-1 HD-01 through HD-09. Those
  named answers and rationales are recorded below. They authorize ADR-0020 and the repaired
  requirements; they are **not** a fabricated HD-10 approval of a later artifact digest.
- Anything else is either derived from the repository audit in `capability-matrix.md` or
  explicitly deferred.

## Who is affected

The single-owner BrainBuddy user, on all three tiers (backend API, web, Expo mobile).
There is no multi-user, sharing or assignment dimension in this feature.

## What hurts

BrainBuddy already stores tasks, but a user coming from Remember The Milk hits supported-
looking paths that stop:

- A task can be cancelled but never trashed, and nothing can be restored
  (`capability-matrix.md` C-25, C-26).
- A List can be archived but never unarchived and never deleted, and archiving silently
  strips every member task's List membership (C-36, C-38, C-39).
- Adding one tag to a task means resending the whole tag set, so two concurrent edits
  lose one of them (C-14).
- There is no start date, no time of day, and priority uses a private vocabulary
  (C-09…C-12).
- Filters that look supported are silently ignored rather than rejected — asking for
  "tasks with no due date" returns every task (C-55, C-56).
- Mobile can read Lists and Tags but cannot rename, archive or delete them (C-68).

## Goals

1. A user can create, organize, find, edit, complete, reopen, trash and restore tasks.
2. A user can manage regular Lists and Tags with explicit, safe membership semantics.
3. The same supported contract holds on backend, web and mobile.
4. Task lifecycle stays strictly separate from agent Execution/Run state.

## Non-goals

- Replacing or deriving Task state from Execution/Run state. Routing or starting an agent
  never completes a Task (C-30).
- Two-way synchronization with a real Remember The Milk account. RTM is the **reference
  model** for this feature, not an integration target (see `p2-decisions.md` P2-05).
- Anything in the P1 backlog (`tasks.md` §P1) or the P2 decision package
  (`p2-decisions.md`).

## Business requirements (founder-stated)

| id | requirement | source |
|---|---|---|
| BR-1 | Task create/read/detail/update, including create into a selected List | brief, frozen scope P0 |
| BR-2 | Edit title, due date + optional time, start date + optional time, priority, Tags incrementally, List membership | brief |
| BR-3 | Complete, reopen, trash, restore — idempotent on client retry, explicit on invalid transitions | brief |
| BR-4 | List create/list/detail/rename/archive/unarchive/delete with safe membership semantics; a non-deletable virtual Inbox | brief |
| BR-5 | Tag create/list with usage count/rename/delete; incremental add/remove must not disturb unrelated tags | brief |
| BR-6 | Search by name/details; filter by List, Tag, status, priority, due and start windows; completed history; stable order; pagination; documented AND semantics | brief |
| BR-7 | Same supported contract across the three tiers; owner isolation; Voice Brain Dump / Smart Add / idempotency recovery preserved | brief |

## Founder-set defaults and ratified clarifications

Items 1–8 came from the portable founder brief. Campaign 1 then surfaced nine decisions;
Max ratified the package below on 2026-08-15. `spec.md` owns the observable contract and
ADR-0020 owns the two narrow ADR-0006 supersessions.

1. Preserve `inbox|next|waiting|someday|completed|cancelled`. Add Trash as an
   **orthogonal** soft-deletion axis, so trash neither erases nor masquerades as
   completion/cancellation. Restore clears only the Trash marker: it preserves the Task's
   commitment state and ordinary metadata, including legitimate List/Tag changes caused
   after trashing by a later List/Tag deletion.
2. Preserve agent Execution/Run records and states unchanged.
3. Migrate `high|medium|low|none` to public `1|2|3|none` (`1` highest), across all clients
   and persisted projections, with an explicit migration and compatibility story.
4. Due/start are a local calendar date plus an optional **floating** local time. No
   reminder, timezone or DST promise until the separate reminders slice. The divergence is
   deliberate and must be documented.
5. Project is the internal name for a regular List. Archive **retains** membership, removes
   the List from active navigation, and blocks new assignment until unarchive. Delete is a
   separately confirmed, idempotent, destructive command that atomically unassigns member
   tasks without deleting, completing or trashing them. Inbox is a virtual system view, not
   a deletable row.
6. Tag global delete atomically removes the classification from every task; incremental
   task-level add/remove preserves unrelated tags.
7. Typed filters compose with AND across fields and OR within repeated values of one field.
   Negation and Smart Lists are P1.
8. The batch limit decision belongs to P1; recommend 20 for RTM familiarity unless
   repository evidence argues otherwise.

## Campaign-1 founder answers (Max, 2026-08-15)

| id | decision | rationale and consequence |
|---|---|---|
| HD-01 | Public priority is `1|2|3|none`, `1` highest. | Align the public task contract with the selected RTM model; ADR-0020 supersedes only ADR-0006's priority vocabulary/order. |
| HD-02 | Labels are `1 — High`, `2 — Medium`, `3 — Low`, `None`. | Preserve the familiar meaning while making the numeric wire value visible and unambiguous. |
| HD-03 | Archived Lists retain membership. | Archive must be losslessly reversible; clearing membership makes unarchive restore an empty List. ADR-0020 supersedes only ADR-0006's archive-clearing rule. |
| HD-04 | Restore only clears Trash and preserves legitimate later List/Tag changes. | A List/Tag deletion while a Task is trashed is authoritative and must not be resurrected from a pre-trash snapshot. |
| HD-05 | No automatic Trash purge initially; Trash is retained until explicit Empty Trash or permanent deletion. | Avoid invisible time-based loss. Explicit erasure is confirmed, idempotent, audited, and immediately removes the task content. |
| HD-06 | Deleted List/Tag names are erased immediately; a durable redacted audit retains IDs, action, and time only. | Preserve accountability without retaining the deleted user-authored name. The audit is life-of-account, included in export, and removed by account purge. |
| HD-07 | Every P0 mutation is idempotent. | Any retryable command in the frozen P0 surface must have the same owner-scoped key/body replay and key-conflict contract. |
| HD-08 | Numeric priority switches only after all active internal builds are verified. | Prevent an installed stale client from misrendering or rejecting numeric values; release evidence has a named owner and a fail-closed inventory. |
| HD-09 | Numbered design states are sufficient for planning; screenshots/video are mandatory before acceptance. | State/copy/accessibility contracts are the planning authority. Rendered evidence is a delivery artifact, not a prerequisite to this planning repair. |

The durable audit retention/export consequence in HD-06 is the narrow safe completion of
the selected answer: it contains no deleted name or content, remains owner-scoped for the
life of the account, appears in the account export, and is erased by the existing account
purge. No audit survives account purge.

## Decisions that exceeded the brief's original authority

Two brief defaults contradicted
`docs/decisions/0006-native-gtd-lifecycle-and-capability-baseline.md`. Campaign 1 kept them
open; Max decided both on 2026-08-15 and ADR-0020 now records the narrow supersession.

| id | conflict | ADR-0006 text | brief default | disposition |
|---|---|---|---|---|
| OD-1 / HD-01 | Priority vocabulary | §Priority fixes `none \| low \| medium \| high` and its sort order | public `1 \| 2 \| 3 \| none` | **resolved by Max, 2026-08-15; ADR-0020 accepted** |
| OD-2 / HD-03 | Archive membership | §Organization semantics requires archive to clear every member `project_id`; row B-29 prescribed that as a fix | archive **retains** membership | **resolved by Max, 2026-08-15; ADR-0020 accepted** |

ADR-0020 records why the earlier clearing fix is superseded and explicitly states that
memberships already removed under the old behavior cannot be reconstructed.

## Residual human action

HD-01 through HD-09 are resolved. HD-10 remains intentionally open: after campaign 2
computes its fresh artifact digest, a named human must either create the exact run-bound
ADR-0012 `human-signoff.json` or decline. The answers above are not that sign-off and must
not be copied into one automatically. `p2-decisions.md` remains frozen and non-blocking.

## Handoff

Agreed description passed to `/speckit-specify`: *the P0 frozen scope above, on all three
tiers, with the eight founder defaults, with Trash as an orthogonal axis, and with Task
lifecycle kept strictly separate from agent execution.*
