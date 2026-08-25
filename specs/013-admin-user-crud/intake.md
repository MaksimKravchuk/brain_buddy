# Business Intake: Admin Users CRUD and two-tab portal

**Feature**: `specs/013-admin-user-crud/` · **Date**: 2026-08-23
**Interviewee**: BrainBuddy founder, via the written Kanban brief

The brief is the human intake and clarification record. The product decisions below are fixed; adjacent reviewer suggestions do not enlarge this atom.

## Outcome

Make the production `/admin` page useful as two explicit tabs: **Users** and **Feature flags**. Users is the default. The operator can list every account, create one with an initial password, edit email/display name, hard-delete an eligible account through the existing erasure orchestration, and revoke all sessions. The current runtime-flag section moves under its tab without changing behavior or storage.

## Fixed boundaries

- Every admin API call remains behind the existing server-owned `require_operator` allow-list. Frontend visibility is never authorization.
- The Users table has stable ordering and columns for email, display name, deletion-requested state and actions. Current scale does not need pagination, fuzzy search or bulk actions.
- Creation accepts email, optional display name and an operator-entered initial password under the existing password policy/hash path. Plaintext is never returned, persisted or logged.
- Update changes only email and display name. The canonical email stays unique. A configured operator account's email is immutable.
- Delete is an explicitly confirmed, immediate hard purge of another non-operator account through existing erasure orchestration. Self-delete and deletion of every configured operator are refused server-side.
- Existing pending-deletion semantics and per-row revoke-all-sessions remain coherent.
- Feature-flag name creation/rename/deletion remains code-owned and out of scope. Existing mode/cohort operations remain unchanged.
- Content-free audit records contain operator id, resolved target id when one exists, action and outcome; never email, password, display name, raw body or member content.
- No roles, impersonation, password reset, audit UI/store, mobile admin or generalized user-directory subsystem.

## Success definition

Local tests and screenshots are implementation evidence, not Definition of Done. Done requires browser verification against the exact deployed production SHA using only purpose-created `@example.com` accounts, after ASK approval and landing, without exposing credentials or real account data in evidence.
