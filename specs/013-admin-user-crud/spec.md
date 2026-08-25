# Feature Specification: Admin Users CRUD and two-tab portal

**Feature Branch**: `013-admin-user-crud`
**Created**: 2026-08-23
**Status**: Planned; implementation and production evidence outstanding
**Input**: [intake.md](intake.md)

This feature supersedes only the `specs/009-admin-portal/spec.md` Out-of-Scope exclusions for a global account list and account create/edit/delete. Feature 009 remains immutable history, and its direct-route, `require_operator`, deny-before-touch, exact-lookup, session-revoke, privacy and content-free logging contracts remain binding. [ADR-0021](../../docs/decisions/0021-operator-account-lifecycle-administration.md) expands ADR-0017's account-record exception without allowing operator access to member content.

## User Scenarios & Testing

### User Story 1 — See accounts immediately (Priority: P1)

An authenticated configured operator opens `/admin`, lands on **Users**, and sees every account in a compact table ordered by canonical email then immutable account id. Each row shows email, display name, deletion-requested state, and actions.

**Independent test**: seed accounts in reverse filesystem/creation order and assert one authorized list response and rendered table have the same total order; unauthenticated/non-operator calls are denied before the repository is touched.

### User Story 2 — Create and maintain an account (Priority: P2)

The operator creates a non-operator account with email, optional display name and an initial password, then changes its email or display name. The password follows the existing policy and Argon2 hash path and is never returned, stored as plaintext, logged or attached to evidence.

**Independent test**: create, log in with the supplied password, update, reload and log in with the same password at the new canonical email. Duplicate/reserved-address conflicts use the existing generic conflict behavior.

### User Story 3 — Contain access or erase an account (Priority: P3)

From a row, the operator can retain the existing revoke-all-sessions action or explicitly confirm immediate hard deletion of another non-operator account. Delete invokes the existing purge orchestration so the account and all owned data disappear together. Self-delete and configured-operator deletion are refused server-side.

**Independent test**: seed all owned-data categories for a synthetic member, delete through the admin route, and reuse existing purge assertions to prove the account, sessions, trees/tasks/voice/relay data and feature-flag cohort references are gone. Prove self/operator refusals cause no mutation.

### User Story 4 — Manage flags without behavior drift (Priority: P4)

The operator selects **Feature flags** and uses the current `AdminFeatureFlagsSection` with its existing mode, cohort, degraded-store, confirmation and polling behavior unchanged.

**Independent test**: tab accessibility/mount tests plus the existing feature-flag suites prove the section is hidden while Users is selected, visible when its tab is selected, and semantically unchanged.

## Functional Requirements

- **FR-001**: Every new and existing `/api/admin/*` route MUST depend on `require_operator`. Unauthenticated callers receive 401 and authenticated non-operators 403 before any account read/mutation. UI hiding MUST NOT grant or enforce authority.
- **FR-002**: `/admin` MUST remain direct-URL, web-only and expose exactly two accessible tabs: `Users` and `Feature flags`. `Users` MUST be selected by default. No global navigation entry is added.
- **FR-003**: `GET /api/admin/accounts` MUST return all account records as `{accounts: [...]}`, stably ordered by `(canonical email ASC, immutable account id ASC)`, with no pagination or query/search parameter. A successful response containing zero accounts is rendered as the exact user-visible state `No accounts to manage yet.`.
- **FR-004**: Every account projection MUST contain only `id`, canonical `email`, optional `display_name`, and boolean `deletion_requested`. The Users table MUST render the requested four columns: email, display name, deletion-requested state and actions; account id may be used only for row identity, accessible action naming and confirmations.
- **FR-005**: `POST /api/admin/accounts` MUST accept exactly `email`, nullable/optional `display_name`, and `password`; normalize email through `UserRepository`, enforce the existing password policy, create a fresh immutable user id, hash through `AuthService`, create no invite and no session, return 201 with only FR-004, and use the existing generic conflict behavior for taken or reserved operator addresses.
- **FR-006**: The plaintext initial password MUST exist only in request processing and the existing password validation/hash call. It MUST NOT enter a model, repository, response, application/admin/access log, telemetry, screenshot, fixture committed with real credentials, or evidence attachment.
- **FR-007**: `PUT /api/admin/accounts/{account_id}` MUST accept the complete mutable projection `{email, display_name}` and change no other field. Email MUST be normalized and unique. Omitting extra fields is rejected by the strict schema; setting `display_name` to null clears it.
- **FR-008**: Updating a configured operator account is allowed only when the normalized submitted email equals its current canonical email; changing that email MUST return 403 with no write. Taken/reserved-address conflicts for other targets use the existing generic conflict behavior. A pending-deletion marker MUST survive every update unchanged.
- **FR-009**: `DELETE /api/admin/accounts/{account_id}` MUST first resolve the exact target, refuse the current operator's own id and every target whose canonical email is in the configured operator allow-list with 403, return 404 for an absent/non-exact id, then call `AccountService.purge_account` rather than duplicate erasure logic. Success returns `{account_id, deleted: true}` only after purge completes.
- **FR-010**: The delete UI MUST require a distinct confirmation dialog naming the target account id/email and the irreversible consequence. Cancel/Escape sends no request and restores focus. The row is removed only from the server-confirmed success result; failure keeps/refetches authoritative state.
- **FR-011**: Immediate admin delete deliberately overrides a target's pending-deletion grace period. The existing self-service request/login-cancellation/due-sweep behavior remains unchanged for every account not admin-deleted. Create/update/revoke MUST NOT clear `deletion_requested_at`.
- **FR-012**: Existing `POST .../{account_id}/revoke-sessions` remains a per-row action with its feature-009 confirmation, idempotent zero-count behavior, unknown-account 404 and content-free response. It is not password reset.
- **FR-013**: Every authorized admin list/create/update/delete/revoke attempt that reaches the service MUST emit exactly one content-free audit record with `operator`, `action`, `outcome`, and resolved `target` when available. Failed create/conflict has no target id. Records MUST exclude email, password, display name, raw body/path value, credentials, tokens and member content. Existing 401/403 denial logging remains authoritative before service entry.
- **FR-014**: Responses and errors MUST preserve the existing API envelope/correlation-id behavior. Validation is strict; malformed payloads do not partially mutate. Unknown exact ids return 404. No response reveals password hashes or owned data. If the account list request fails, the Users surface renders the exact contraction-aware copy `Couldn't load users. Ref: <correlation-id>` when a correlation id is available (and `Couldn't load users.` otherwise), exposes a `Retry` control that performs a real refetch, and retains the last confirmed account list during a refetch failure. An initial failure may have no stale list; a successful retry clears the prior list error and renders the recovered response.
- **FR-015**: `AdminFeatureFlagsSection` MUST move under the Feature flags tab without changing its API, SQLite store, managed-name registry, polling, mode/cohort semantics, degraded behavior or confirmation rules. Runtime flag-name CRUD remains unsupported.
- **FR-016**: Existing exact account lookup API remains supported for compatibility and feature-flag cohort resolution, but the Users tab does not expose fuzzy search or a second lookup-first workflow.
- **FR-017**: All new pytest, Vitest and Playwright product tests MUST carry feature-qualified `013-FR-nnn` references and the repository Allure epic/feature/story/title/named-step taxonomy.

## Edge Cases

- Two accounts share an apparent display name: ordering is still email then id; display names are not identifiers.
- Create/update uses a case or whitespace email variant: normalization applies before uniqueness/operator checks and storage.
- The target becomes absent between render and action: update/delete/revoke returns 404 and the Users list refetches.
- The target is already deletion-requested: it remains listed as such; update/revoke preserve the marker; confirmed delete purges immediately.
- Purge is blocked by a degraded runtime-flag store: existing fail-closed purge behavior applies; delete reports failure and the account remains deletion-requested/past-due for retry rather than claiming success.
- A second tab changes users: mutation success and explicit refetch restore server authority; no optimistic identity changes.
- The operator may use `Retry` after a confirmed list as well as after an error; this explicit control makes a real refetch available for stale-list recovery without changing the last confirmed data until a replacement response succeeds.

## Success Criteria

- **SC-001**: With at least five accounts seeded out of order, API and UI show every account exactly once in canonical-email/id order and only the four FR-004 fields.
- **SC-002**: 401/403 matrices for every new route prove deny-before-touch by poisoning account-facing service/repository methods; no denied mutation changes data.
- **SC-003**: A created synthetic account can authenticate with the operator-entered password, while captured response/log/evidence sentinels contain neither plaintext nor hash; invalid policy input and duplicate/reserved email create nothing.
- **SC-004**: Update persists canonical email/display name, preserves password hash and deletion marker byte-for-byte, refuses operator-email mutation, and resolves concurrent conflict through the existing generic response.
- **SC-005**: Admin delete of a synthetic member removes the account and all owned data through the existing purge matrix; self/operator/unknown/degraded-store cases have the required refusal and no false success.
- **SC-006**: Revoke-all-sessions still invalidates every active target session and remains usable from each Users row without changing deletion/account data.
- **SC-007**: Keyboard and accessibility tests prove Users default, correct tab roles/selection, focus behavior for create/edit/revoke/delete, explicit destructive confirmation, status/error announcements and no horizontal overflow at 390px.
- **SC-008**: Existing 009 authorization/privacy/revoke suites and 010 runtime-feature-flag suites pass unchanged in behavior after the two-tab move.
- **SC-009**: After ASK-approved exact-SHA production deployment, a browser operator creates, lists, edits, revokes and deletes a purpose-created `@example.com` account, verifies deletion by list absence and failed target login, and opens Feature flags to verify the existing state; the evidence identifies deployed SHA and contains no credentials or real account data.

## Out of Scope

Password reset/change, role assignment, delegation, impersonation, audit UI/database, bulk operations, pagination, fuzzy/partial search, mobile admin, global navigation discovery, soft-delete redesign, changes to self-service deletion grace, a generalized directory subsystem, runtime feature-flag name create/rename/delete, new rollout modes, new feature-flag storage/service, deploy redesign, or access to member trees/tasks/voice/relay/export content.

## Assumptions

- Current account scale makes a complete unpaginated list bounded enough; growth-driven pagination is backlog, not hidden scope.
- The operator is an existing authenticated account selected by `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`; production currently pins it to the seeded admin identity.
- This operator-only web tooling has no impact on the capture → clarify → route → Weekly Review primary loop.
- Product and privacy authority for this bounded cross-owner lifecycle administration is the founder brief recorded in `intake.md` and ADR-0021; landing authority remains separate under ADR-0008.
