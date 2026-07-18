# ADR-0007: Make Smart Add an explicit atomic task command

Date: 2026-07-18
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0006, `specs/003-smart-add-classification/`, Kanban task `t_fe52d630`

## Context

The shipped desktop/web task composer accepts one plain title and calls `POST /tasks`.
Project and Tag assignment currently use IDs through contextual create, task-row selects, and
task detail. Project and Tag creation are separate idempotent commands. Their owner-scoped
active names are normalized with Unicode NFKC, collapsed whitespace, and case folding.

Smart Add adds an intentional mini-language to that composer: `#` classifies Tags and `@`
classifies one Project. Unknown completed names must create the classification and assign it
to the same new task. A client-only sequence of create-Tag/create-Project/create-Task calls
can leave an unused classification when a later call fails and cannot give the whole user
action one idempotency boundary. Reinterpreting every `POST /tasks.title` would instead
break existing API clients and legitimate literal titles.

## Decision

Keep `POST /tasks` and `PATCH /tasks/{id}` literal and backward compatible. Smart Add is
opt-in through `POST /tasks/smart-add`, one owner-scoped, idempotent Tasks-module command.
The browser parses and cleans inline syntax, then sends the clean title plus explicit
Project/Tag references. A reference contains exactly one of an existing ID or a display
name to resolve-or-create.

The command runs under the existing owner command lock and SQLite transaction. It validates
all existing references, resolves active names with the canonical Project/Tag normalization,
creates only missing active classifications, creates the task, and records one composite
idempotent result. Any validation or persistence failure rolls back the classification and
task database writes together. Replaying the same key and body returns the original task
and resolved classifications.

Inline parsing remains a desktop/web presentation contract for this feature. The backend
command does not infer syntax from `title`; therefore future clients may use the atomic
resolve-or-create command without adopting the inline grammar, and plain-title capture
cannot change accidentally.

## Rationale

- One explicit command matches one user submit and avoids orphan Project/Tag side effects.
- The command stays inside the Tasks bounded module, which owns all three records under
  ADR-0001 and ADR-0006; no new service or deployment boundary is introduced.
- Existing APIs, voice-created tasks, task title edits, and plain-title clients remain
  literal and compatible.
- Browser-local suggestions can reuse the already-loaded active Project/Tag lists with no
  new search endpoint or per-keystroke request.
- Server-side normalized resolve-or-create remains authoritative for casing, Unicode, race,
  owner, and active-state checks.

## Alternatives considered

### Client-side choreography over existing endpoints

The browser could create every unknown Tag/Project and then create the Task. This is smaller
but exposes partial success, requires compensating destructive behavior or orphan cleanup,
and spreads retry/idempotency logic across several requests. Rejected.

### Parse all `POST /tasks` titles on the server

This centralizes grammar but silently changes the meaning of existing titles containing
literal `#` or `@`, affects voice and non-web clients, and prevents callers from choosing
literal behavior. Rejected.

### Send raw Smart Add text and parse only on the server

This would keep one parser but cannot drive responsive caret-local suggestions without a
second browser parser. The two parsers would still need contract fixtures, and selected
multi-word suggestions would need hidden span/ID metadata. The explicit clean-title and
classification-reference payload is simpler and testable. Rejected for this desktop slice.

## Consequences

Positive consequences:

- unknown classification creation and task creation have one transactional/idempotent unit;
- plain-title and title-edit semantics remain unchanged;
- the UI can evolve independently while Project/Tag normalization remains canonical;
- contextual Project/Tag defaults can be represented as ID references and inline unknowns
  as name references in the same command.

Tradeoffs / risks:

- a new composite response and idempotency replay path must be implemented and tested;
- browser parsing and server classification resolution are separate responsibilities and
  require shared fixture expectations in the feature spec;
- the existing JSON compatibility sidecars still need reconciliation if a database commit
  succeeds but a sidecar write is interrupted; the composite replay path must repair every
  returned resource, not only the Task.

What future agents must preserve:

- do not reinterpret existing task create/update title fields;
- do not create superseded `@project` names;
- do not replace the compound command with unacknowledged client partial writes;
- keep Projects separate from CRT trees and keep Tags first-class task classifications;
- keep visible Smart Add suggestions local to active, owner-scoped loaded classifications.

## Verification / tests

- Parser unit tests cover grammar, escaping, title cleaning, duplicates, punctuation,
  whitespace, casing, quoted names, incomplete tokens, and last-Project-wins behavior.
- API/service tests cover resolve existing, create missing, composite rollback, same-key
  replay, conflicting-key reuse, active/owner validation, contextual ID references, and no
  creation of superseded projects.
- Browser tests cover mouse/keyboard suggestions, plain title compatibility, contextual
  create, clean persistence, and `#tag`/`@project` rendering.

## Related files

- `frontend/src/features/tasks/TaskListPage.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/api/taskTypes.ts`
- `backend/app/api/tasks.py`
- `backend/app/schemas/tasks.py`
- `backend/app/modules/tasks/service.py`
- `backend/app/modules/tasks/repository.py`
- `specs/003-smart-add-classification/contracts/smart-add.md`
