# ADR-0021: Add task-title autocomplete as a fourth runtime-managed flag

Date: 2026-08-25
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0007, ADR-0008, ADR-0018, ADR-0019, `specs/012-task-title-autocomplete/`
Narrows: ADR-0019's fixed three-flag managed set for this one additional experiment

## Context

ADR-0019 makes SQLite the sole runtime authority for exactly three managed flags and says adding another runtime-managed flag requires its own ADR. Web Task title autocomplete is a remote-AI experiment: it sends owner content only with current consent, must start OFF, and needs immediate cohort rollback without a deploy. Treating it as environment-only would contradict the requested runtime management; enabling it without a flag would violate ADR-0008's default-OFF rollout rule.

The experiment needs no durable suggestion or memory data. Its only persistence effect is one additional rollout row using the existing feature-flag schema and operator controls.

## Decision

Add `task_title_autocomplete` to `KNOWN_FEATURE_FLAGS`, `RUNTIME_MANAGED_FLAGS`, and the SQLite repository's `MANAGED_FLAGS`. It is the fourth runtime-managed flag and resolves exclusively from its SQLite row through `FeatureFlagService`. It appears in the existing `/api/auth/me` effective-flag map and existing Admin Feature Flags section. Like every flag, it controls exposure only and grants no authentication, owner access, provider consent, or provider capability.

Initialization is fail-closed:

- a fresh store seeds this newly introduced row OFF unconditionally; the retired pre-ADR-0019 environment/legacy migration inputs never seed this name, even if stale configuration happens to contain it;
- an existing volume carrying the durable migration-complete marker adds the newly declared missing row as OFF in the repository's existing post-marker initialization transaction;
- after initialization, a missing or malformed managed row degrades the whole managed store exactly as ADR-0019 specifies: every managed flag is ineffective and mutations are refused;
- the legacy JSON document is never consulted for this flag.

Provider configuration is a separate capability axis. A runtime ON/SELECTED_USERS answer exposes autocomplete only when the configured title-completion adapter is supported and has credentials, and every remote generation additionally requires current request-scoped consent. Any unfavorable axis fails closed. This mirrors ADR-0019's rollout/capability separation for the relay without reusing relay credentials or provider construction.

The flag does not gate ordinary Task create, Smart Add, title edits, owner Task reads, mobile/voice capture, or any standing privacy authority. Turning it OFF cancels/hides new autocomplete work only; it cannot alter or delete Tasks, drafts, Projects, or prior experiment logs.

## Rationale

- Runtime OFF is the fastest safe rollback for an interactive AI experiment.
- Reusing the existing SQLite row/mode/cohort schema avoids another persistence surface.
- Explicit provider capability and consent checks prevent a rollout decision from becoming egress authority.
- An OFF insertion path for already-migrated volumes preserves ADR-0019's sole-source invariant without replaying retired migration inputs.

## Alternatives considered

### Environment-owned flag

Rejected: it would require a deploy for every rollout/rollback and would not satisfy the fixed runtime-management decision.

### Reuse another AI feature flag

Rejected: Voice Brain Dump and autocomplete have different data, consent, UI, cost, and rollback boundaries. Coupling them would make rollout authority too broad.

### No server flag; client-only toggle

Rejected: a client toggle is neither server-owned nor authoritative and cannot prevent direct endpoint calls.

## Consequences

- Implementation changes to the runtime flag store, member flag projection, authenticated Tasks API, and remote-AI data path are ASK/high under ADR-0008 and require explicit approval plus exact-SHA evidence; they never auto-land.
- Account purge automatically scrubs the fourth row's selected-user cohort through the existing all-managed-flags loop; no new personal data category is introduced.
- Store health tests, migration-marker tests, Admin UI tests, and member flag-key tests must update from three to four managed rows.
- Rollback is flag OFF first. Code/image rollback leaves Tasks untouched; an older image ignores the extra SQLite row according to its contemporaneous managed set.
- Percentage rollout, schedules, a new role model, a new audit store, and generalized dynamic flag registration remain out of scope.

## Verification

- Repository tests prove fresh and post-marker stores contain an OFF row, missing/malformed rows degrade, purge scrubs all four cohorts, and legacy JSON never seeds this flag.
- Service/API tests prove flag OFF denies generation, ON without provider/consent still denies egress, and the effective flag remains non-authoritative.
- Feature 012 acceptance proves turning OFF removes the menu and provider calls while ordinary Task creation and existing Tasks remain unchanged.

## Related files

- `backend/app/core/config.py`
- `backend/app/repositories/feature_flag.py`
- `backend/app/services/feature_flag_service.py`
- `backend/app/api/tasks.py`
- `frontend/src/features/admin/AdminFeatureFlagsSection.tsx`
- `specs/012-task-title-autocomplete/contracts/title-completions.md`
