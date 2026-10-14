# ADR-0032: The server moves to Rust

- **Status**: Proposed. The owner accepted the specification 027 technical baseline on
  2026-10-14 (`specs/027-rust-server/approval.md`, founder acceptance valid to
  2026-12-14); this ADR is accepted in full when the cutover is authorized.
- **Date**: 2026-10-14
- **Decision owner**: MaksimKravchuk (product owner)
- **Landing**: slice PR-01 of `specs/027-rust-server/`.
- **Supersedes**: ADR-0031's "the backend stays FastAPI and calls the domain core
  through PyO3" and "PostgreSQL through a separate controlled migration"
  (specification 026, PR-55 to PR-57).
- **Amends**: ADR-0028 (provider sign-up no longer bypasses the invite).
- **Preserves**: ADR-0001 module boundaries and data ownership, ADR-0027 task and
  review semantics, ADR-0026 CRT protocol, ADR-0029 device grant, ADR-0016 mutation
  promotion, ADR-0008 Ship/Show/Ask classes.

## Decision

1. **One server implementation, in Rust.** The production server (HTTP, sync, MCP,
   device/CLI flows, A2A relay, background jobs, operator commands) is a Rust binary
   with two roles, `serve` and `worker`. Task and Weekly Review rules have exactly one
   implementation, the shared core the native runtime also uses (027-FR-001,
   027-FR-002, 027-FR-003). No Python runtime remains in production after cutover.
2. **PostgreSQL arrives with the move.** The separate PostgreSQL stage of 026 is
   dropped: the Rust server starts on PostgreSQL, one schema per owning module. A
   module's repository queries only its own schema; cross-module reads go through
   the owning module's port. No existing row is migrated (the old data is erasable by
   owner decision).
3. **Differential conformance oracle.** Each ported capability must pass the same
   black-box tests against the frozen Python server and the Rust server before
   cutover. The capability inventory is the checklist; the two servers never serve
   one user at once.
4. **Gate equivalents** (research R5): `cargo llvm-cov` with a ratcheting
   `rust/coverage-floor.json`; `cargo mutants` feeding the mutation gate;
   `clippy -D warnings` with complexity ceilings; a crate-graph check in place of
   import-linter; an Allure writer crate; OpenAPI generated and diffed. Thresholds
   are never lowered for an existing scope.
5. **Mutation promotion rule.** The Rust critical-invariant modules (owner isolation,
   sessions and auth, provider-token verification, command receipts and idempotency,
   job fencing, purge, control ledger) run as an *observed* scope from Phase A. A
   module becomes enforced only after two consecutive successful scheduled runs at or
   above 95% on an unchanged scope (ADR-0016). The six Python modules leave the
   enforced scope only after the Rust scope is promoted, through this ADR and the
   guarded `--update`.
6. **Freeze (027-FR-022).** From acceptance until cutover the Python server changes
   only to fix defects or to add test-only seams that exist solely in its test
   environment. It gains no product capability, so the capability inventory stays
   fixed. New server features land only in the Rust server after cutover.
7. **ADR-0028 amendment (027-FR-007).** Creating an account by any method (password,
   email code, Apple, Google, browser grant, device grant) requires a valid unused
   invite. A provider identity without an account receives `INVITE_REQUIRED` and a
   single-use, short-lived pending handoff; nothing is created until a valid invite is
   submitted. Signing in to an existing account never needs an invite. Cookie
   attributes are unchanged.

## Consequences

- The PyO3 bridge planned by 026 is not built; the core is linked directly.
- Every irreversible step (provisioning, CI or gate changes, cutover, rollback, erase,
  destructive pilot steps) stays a separate exact-SHA ASK approval.
- Two server implementations exist during the migration; the freeze and the oracle
  bound the cost.

## Alternatives rejected

- Keep FastAPI with PyO3 (026 first stage): leaves two runtimes and a second data
  migration later.
- Rewrite without an oracle: no evidence that behaviour is preserved.
