# ADR-0025: Add CRT canvas as a fifth runtime-managed flag

Date: 2026-09-19
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0008, ADR-0019, ADR-0021, ADR-0022, `specs/019-miro-like-crt-canvas/`
Narrows: ADR-0019's fixed managed set for this one additional product surface

## Context

ADR-0019 makes SQLite the sole runtime authority for its named managed flags and requires a new ADR before another flag enters that store. ADR-0021 established the post-migration expansion pattern for `task_title_autocomplete`. Feature 019 adds an authenticated Current Reality Tree editor at `/crt`. Its owner/privacy mutation paths are ASK/high, it must start unavailable, and its first exposure is one selected internal account. ADR-0022 requires a server-owned flag for this rollout but deliberately does not choose the owning mechanism.

An environment-only flag would require a deploy for cohort changes and rollback. Reusing another product flag would couple unrelated data and failure boundaries. A client-only flag could not protect direct CRT facade calls.

## Decision

Add `crt_canvas` to `KNOWN_FEATURE_FLAGS`, the runtime-managed flag declarations, and the SQLite repository's managed row set. It is the fifth runtime-managed flag and resolves exclusively from its SQLite row through `FeatureFlagService`. It appears in the existing generic Admin Feature Flags controls and the member-facing `/api/auth/me` effective-flag map.

Initialization and migration are fail-closed:

- a fresh feature-flag store creates `crt_canvas` as `OFF` unconditionally;
- an existing store with ADR-0019's durable migration marker adds the missing `crt_canvas` row as `OFF` in the repository's post-marker initialization transaction;
- retired environment and legacy JSON inputs never seed this flag, even if stale configuration contains its name;
- after initialization, a missing or malformed managed row degrades the complete managed store as ADR-0019 specifies: all managed flags resolve ineffective and operator mutations are refused;
- the legacy JSON document is never consulted for this flag.

The flag controls exposure only. Authentication, owner checks, revision checks, graph validation, and local-draft account/origin isolation remain mandatory. Normal OFF/not-selected CRT requests fail closed without content; degraded store resolution remains distinguishable as service unavailability. Turning the flag OFF during an editing session stops further server mutations and preserves unsynchronized work in the already owner/origin-scoped local recovery record.

No provider, secret, consent, or external-processing capability is attached to this flag. The CRT v1 makes no AI call.

## Rationale

- Runtime `selected_users` is the narrowest practical internal rollout and fastest rollback for a new owner-scoped editing surface.
- Reusing the existing SQLite mode/cohort schema avoids another rollout persistence mechanism.
- Unconditional OFF initialization prevents a stale deploy setting or legacy file from exposing the canvas.
- Keeping exposure separate from authorization prevents a rollout decision from granting data access.

## Alternatives considered

### Environment-owned flag

Rejected: cohort changes and emergency rollback would require a deploy and would not satisfy the selected-account runtime rollout.

### Reuse an existing managed flag

Rejected: CRT has independent data, routes, recovery behavior, evidence, and rollback. Coupling it to Voice Brain Dump, mobile classification, external relay, or title autocomplete would broaden authority incorrectly.

### Client-only navigation toggle

Rejected: it would hide UI only and could not fail closed on direct `/api/crt/trees*` calls.

## Consequences

- The managed-row count increases from four to five; repository, service, admin, member projection, migration-marker, degraded-store, and purge tests must update together.
- Account purge scrubs `crt_canvas` selected-user membership through the existing all-managed-flags loop. The flag row contains account IDs only and introduces no tree content category.
- Existing volumes receive exactly one OFF row through post-marker initialization; normal reads never replay retired migration inputs.
- Rollback is flag OFF first. ADR-0026 Stage A adds the fifth-row-aware reader and OFF row before any Stage B write, and becomes the oldest permitted rollback image. Pre-Stage-A four-row images do **not** safely ignore an extra row—their exact-set reader degrades—so they must never be used after the fifth row exists. Canonical trees and owner-scoped local drafts are not deleted by rollout rollback.
- These runtime-store and authenticated CRT boundary changes remain ASK/high under ADR-0008 and require the recorded approval, exact-SHA evidence, verified landing, smoke, and rollback path before production exposure.
- Percentage rollout, schedules, dynamic flag registration, a second writer, or a new audit store remain out of scope and require another decision.

## Verification

- Repository tests prove fresh and post-marker stores contain an OFF `crt_canvas` row, retired inputs never seed it, and missing/malformed rows degrade the managed store.
- Service/API tests prove OFF, selected-user, ON, degraded, admin read-back, `/auth/me`, cohort scrub, and direct CRT facade denial behavior.
- Feature 019 acceptance proves flag revocation stops mutations without exposing another owner or discarding unsynchronized local work.

## Related files

- `backend/app/core/config.py`
- `backend/app/repositories/feature_flag.py`
- `backend/app/services/feature_flag_service.py`
- `backend/app/api/auth.py`
- `frontend/src/features/admin/AdminFeatureFlagsSection.tsx`
- `specs/019-miro-like-crt-canvas/contracts/http.md`
