# Phase 0 research: mobile task classification

No `NEEDS CLARIFICATION` markers entered this phase, and none were created.
The research below is mostly negative findings — things that did not need
building — which is the most useful kind here.

## The wire contract already carries the feature

**Decision**: reuse `PATCH /tasks/{id}`. Add no route.

**Rationale**: `TaskUpdateRequest` in `mobile/src/api/types.ts` already declares
`project_id?: string | null`, `tag_ids?: string[]` and a **required**
`expected_revision: number`. `mobile/src/api/client.ts` already calls it with an
idempotency key. Nothing is missing.

**Consequence that is not optional**: because `expected_revision` is required
rather than optional, a change queued offline necessarily carries a revision
observed before it was queued. Rejection is therefore an ordinary outcome of the
deferred-send behaviour, not a rare race, which is why FR-008 is a requirement
and not a refinement.

**Alternatives considered**: a bulk classification route (rejected — new task
route, ASK-classified path, and bulk assignment is an explicit non-goal); an
optional `expected_revision` (rejected — it would trade the concurrency guard
for convenience, and the guard is what makes conflict detection possible at all).

## Inline creation needs no new endpoint either

**Decision**: reuse `POST /projects` and `POST /tags`.

**Rationale**: `createProject(payload, idempotencyKey)` and
`createTag(payload, idempotencyKey)` already exist in the mobile API client.

**Consequence**: identity is assigned by the server, so creation cannot be
queued — there would be nothing stable for a queued assignment to reference.
This is FR-016 and it narrows User Story 3 against User Story 2. Confirmed with
the human at clarify rather than assumed.

## The flag already reaches the client

**Decision**: add one name to `KNOWN_FEATURE_FLAGS` in
`backend/app/core/config.py`; read it in `SessionProvider` beside the existing
`voiceEnabled`.

**Rationale**: `/auth/me` already returns `feature_flags: dict[str, bool]`
(`backend/app/schemas/auth.py:95`, populated at `backend/app/api/auth.py:58`),
and `mobile/src/auth/SessionProvider.tsx:128` already reads
`me?.feature_flags?.voice_brain_dump === true` with a comment stating the read
is **fail closed**. The same pattern applies unchanged.

**Why this matters for the ASK constraint**: `config.py` is not one of the
ASK-classified paths (`dependencies.py`, `middleware.py`, `routes.py`,
`tasks.py`). The flag wiring therefore costs nothing against the constraint that
actually binds this feature.

**Alternatives considered**: a client-side constant (rejected — AGENTS.md
requires the flag be server-owned); a new flags endpoint (rejected — one exists
in all but name).

## Storage for the queue

**Decision**: `AsyncStorage`, one key per account-and-server pairing.

**Rationale**: `mobile/src/config/serverUrl.ts` already uses
`@react-native-async-storage/async-storage` for `bb.serverUrl`. No new
dependency. Keying by identity is what makes FR-011 enforceable by construction
rather than by remembering to check: entries for another account or server are
not merely hidden, they are not in the key being read.

**Alternatives considered**: SQLite via `expo-sqlite` (rejected — the queue is
tens of entries, not a dataset, and it would add a dependency for nothing);
in-memory only (rejected — FR-009 requires surviving a restart).

## Testing approach under a real constraint

**Decision**: push every assertable rule into pure modules; use
`make integration-mobile` for wire behaviour; accept typecheck and build as the
only evidence for component rendering.

**Rationale**: `mobile/` has no component-render test library. This is a
repository-level gap, not something this feature can close, and pretending
otherwise would produce acceptance evidence that describes itself as stronger
than it is.

**Alternatives considered**: adding `@testing-library/react-native` (rejected
*for this feature* — it is a real improvement and a real scope increase, and
smuggling it into a feature branch as a side effect is how test infrastructure
decisions get made badly. Worth raising separately).
