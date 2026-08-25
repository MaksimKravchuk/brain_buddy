# ADR-0021: Permit bounded operator account lifecycle administration

Date: 2026-08-23
Status: Accepted
Decision owner: Founder (Maksim)
Related: ADR-0001, ADR-0008, ADR-0012, ADR-0017, ADR-0019, `specs/012-admin-user-crud/`
Supersedes: ADR-0017 only where that record limits the operator exception to lookup and session revocation; all member-content and authorization constraints remain.

## Context

ADR-0017 created a deliberately narrow owner-scoping exception: a configured operator could read one account record and revoke that account's sessions. It explicitly authorized exactly those two cross-owner operations. Feature 012 now has founder-authorized fixed scope to make `/admin` operationally useful: list account records, create a member, change email/display name, and immediately hard-delete an eligible member through the existing erasure orchestration.

Silently treating those operations as an extension of ADR-0017 would violate its explicit cap and ADR-0012's preserved-history rule. This record dates and bounds the expansion. It does not authorize access to anything an account owns.

## Decision

A server-authorized operator selected by `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` may:

1. list every account's safe account record (id, canonical email, optional display name, deletion-requested state) in stable order;
2. create a non-operator account with canonical email, optional display name and an initial password processed only by the existing password policy/hash path, without an invite or session;
3. update only canonical email and display name; and
4. hard-delete another non-operator account by invoking the existing complete `AccountService.purge_account` orchestration after explicit UI confirmation.

The boundary is subject to these mandatory restrictions:

- every route uses `require_operator`; denial happens before account access and frontend hiding is not authorization;
- a configured operator account's email cannot be changed through admin CRUD;
- the current operator cannot delete itself, and no configured operator account can be deleted;
- hard delete may end a pending-deletion grace period early, but does not redesign self-service deletion for any other account;
- create/update uniqueness and reserved-address conflicts retain generic behavior;
- plaintext passwords never enter persistence, responses, logs, telemetry or evidence;
- every authorized operation emits content-free application audit metadata (operator id, resolved target id when available, action, outcome), not a new audit store;
- trees, versions, validation history, tasks, projects, tags, voice operations/transcripts/audio, relay data, exports, invites and all other member content remain inaccessible to operators. Delete may orchestrate their erasure but provides no read path or content response.

No role model, delegation, impersonation, password reset, bulk operation, mobile admin, generalized directory/search subsystem or audit-history platform is authorized.

## Rationale

The existing modular-monolith already has the required trust and lifecycle primitives: a server-owned operator allow-list, safe account projection, password hashing, user repository and complete erasure orchestration. Reusing them produces the smallest coherent vertical and avoids a second identity system, deletion implementation or persistence authority. Server-side self/operator restrictions protect the only production operator from destructive UI or client mistakes.

## Alternatives considered

### Keep lookup-only administration

Rejected for this atom: it leaves routine account provisioning and cleanup dependent on direct datastore/CLI intervention and does not satisfy the founder's production outcome.

### Add roles or a general user-directory subsystem

Rejected: mutable role assignment would expand authority and self-escalation risk; pagination/search/directory infrastructure is unnecessary at current scale.

### Implement a separate admin deletion path

Rejected: duplicating erasure ownership would drift from retention, cohort scrub and crash-safe marker ordering. The accepted path delegates to `AccountService.purge_account`.

### Allow operator password reset

Rejected: the requested create-only initial password is sufficient. Reset introduces a separate account-takeover-sensitive capability and requires its own future decision.

## Consequences

Positive:

- `/admin` can perform the bounded account lifecycle from one web surface.
- Password and erasure ownership remain in existing services.
- Member content stays owner-scoped and unreadable.

Tradeoffs/risks:

- The operator can view all account emails/display names and irreversibly erase eligible accounts.
- A completed hard purge and session revocation cannot be rolled back.
- The implementation is auth/privacy/destructive ASK class under ADR-0008 and cannot land automatically.
- Full account listing is intentionally unpaginated at current scale; scale growth requires a new bounded spec.

Future agents must preserve:

- `require_operator` on every admin API;
- server-side operator-email and self/operator-delete refusals;
- delegation to the existing purge orchestration;
- no operator read access to member content;
- content-free logs and no plaintext password output;
- direct `/admin` reachability and code-owned feature-flag registry under ADR-0019.

## Verification

- Backend service/API tests cover the authorization matrix, stable safe projection, password hashing/no leakage, update invariants, self/operator delete refusal, purge delegation and content-free audit.
- Existing account purge tests prove every owned-data category and feature-flag cohort reference is erased.
- Frontend tests cover accessible tabs, row actions and explicit destructive confirmation.
- Independent review/QA and required CI bind to one exact candidate SHA.
- Acceptance completes only after browser verification on the exact deployed production SHA with purpose-created `@example.com` data.

## Related files

- `backend/app/api/admin.py`
- `backend/app/services/admin_service.py`
- `backend/app/services/auth_service.py`
- `backend/app/services/account_service.py`
- `backend/app/repositories/user.py`
- `frontend/src/features/admin/AdminPage.tsx`
- `frontend/src/features/admin/AdminFeatureFlagsSection.tsx`
- `specs/012-admin-user-crud/`
