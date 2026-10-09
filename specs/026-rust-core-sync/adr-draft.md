# Proposed ADR: shared Rust core and task sync

Status: **Enacted as [ADR-0031](../../docs/decisions/0031-shared-rust-core-and-task-sync.md) on 2026-10-09** (PR-01, per [approval.md](approval.md)). This draft is kept unchanged below as history; the ADR is the authority. Original status line: Proposed, 2026-10-08. An accepted ADR number is not reserved yet. The user confirmed the Rust + custom sync direction; the concrete protocol, UX, and migration boundaries below are proposed for acceptance.

## Decision

The normative Tasks and native-task Review rules are implemented in one pure Rust library. Native clients use a Rust client runtime with SQLite and a durable queue; the backend calls the domain core through PyO3 and preserves the current Identity authority. New task sync transports commands, receipts, and atomic changes. PostgreSQL is the target task store, introduced through a separate controlled migration. The modular monolith remains.

## Decisions being amended

ADR-0001 changes only in the implementation of Tasks rules and its server persistence. Data ownership, application ports, and Capture/Organize/Tasks/Thinking/Execution/Identity boundaries remain. ADR-0027's storage technology and shared-rule implementation change, with the command-metadata extension below; its auto-park, yield, review semantics, content-retention limits, and task+review atomicity remain mandatory.

The new protocol additionally proposes durable content-free command deduplication metadata until account purge, beyond the current ordinary 24-hour idempotency window. It preserves ADR-0027's existing matching-record replay and content limits: ordinary task/Review full responses expire within 24 hours, and Review undo/bulk snapshot content within seven days, including copies in the new feed and snapshots. Capture's original commit-recovery exception and CRT's separate policy remain scoped to their existing contracts. This metadata extension must be recorded in the accepted ADR and retention documentation before rollout; it does not authorize longer retention of user text.

Constitution IV requires a proposed narrow amendment before implementation: dedicated owner-scoped command IDs may identify an immutable command for durable deduplication, while observability/correlation IDs remain neither authorization nor deduplication inputs. No client-supplied ID grants authority, changed content under one command ID is rejected, and entity IDs alone do not authorize upsert or replay outside accepted domain contracts. ADR-0027's bounded Review exception remains intact. Acceptance must update the constitution and dependent documentation with preserved history; this draft does not claim that amendment is already approved.

The current `ios/AGENTS.md` instruction, “No third-party dependencies,” needs a narrow allowance for audited, pinned Rust bindings and their required runtime. The product dependency policy can change only after that amendment is accepted; arbitrary Apple packages are not permitted.

Spec 021's last-push-wins behavior for current sync is replaced by explicit conflicts for the new protocol cohort. Legacy clients retain their documented contract during the compatibility window; their writes remain visible to new clients. The new UX must be accepted explicitly rather than presented as an invisible internal optimization.

ADR-0026's CRT protocol and ADR-0028's Identity authority are not superseded. Their databases, receipts, exports, and recovery remain in their respective modules. Moving Tasks does not justify treating every storage system as one transaction.

## Why not the alternatives

Server rules without a shared client runtime cannot provide identical offline behavior. Managed sync would reduce some transport work, but the user selected custom sync, so we own snapshots, ordering, retention, deduplication, and recovery. A universal CRDT does not solve authorization, AI confirmation, or external effects; a command protocol and explicit conflicts are sufficient for current tasks. Rewriting the whole backend in Rust would enlarge the migration surface without being necessary to share rules.

## Consequences

The team maintains an FFI/build matrix and its own sync protocol. Shared rules are tested once, but platform boundaries, databases, networking, and different AI models still need their own checks. Conservative conflicts sometimes require an extra user choice. Duplicate prevention and recovery of legacy uncertainty matter more than a smooth happy-path demonstration.

## Acceptance conditions

Acceptance requires review of the concrete [contract](contracts/sync-v1.md), UX sign-off for [design.md](design.md), validated limits, and an exact migration/rollback boundary. This draft does not authorize data deletion, production schema changes, or automatic release.

## Exact amendment proposal

These are proposed replacement/addition texts for the first governance slice, not changes already made to accepted policy. Reserve the next available ADR number across all refs at that time; do not reuse an occupied number.

**Constitution IV**, replace its first bullet with:

> Backend responses MUST include `X-Correlation-ID`. Correlation and observability IDs are labels only and never authorization or idempotency inputs. Dedicated owner-scoped command IDs MAY identify an immutable command for durable deduplication under an accepted domain contract. No client-supplied ID grants authority; replay MUST recheck current authority and reject changed command content under the same ID. Entity IDs alone do not authorize upsert or replay beyond the accepted domain contract.

This narrow breaking clarification requires the constitution's version/history and sync impact report to be updated in the governance slice. Audit dependent `AGENTS.md`, `CLAUDE.md`, `.specify/templates/`, and observability/retention docs for the same distinction; do not change unrelated consent or delivery principles.

**Apple dependency policy**, retain the no-third-party default with this exception:

> The shared Rust domain/runtime and their audited, pinned generated Swift bindings are allowed. Their build inputs, licenses, lockfile, reproducible packaging, supported targets, and Foundation-only Linux test boundary must be reviewed. This exception does not permit arbitrary Swift packages, bundled model weights, or unrelated native dependencies.

**Retention additions**, reflect in `docs/data-retention.md` and the existing privacy disclosure before rollout: ordinary task/Review full responses retain their 24-hour maximum; content-free command identity/outcome/fingerprint metadata survives only until account purge. Feed, snapshot, oversized-transaction staging and backup copies inherit source expiry/deletion, including seven-day Review recovery content, and cannot extend it. Device SQLite/outbox/issues/drafts preserve the current owner-specific sign-out, local export and legacy backup policy; no diagnostic upload is implied. Protected restore points have a maximum seven-day horizon. Purge cannot finish while a recoverable controlled backup still contains the purged owner; invalidate/erase affected restore material first. The minimal external control ledger is bounded by the last affected restore point and is not an indefinite person-linked audit log.

**Architecture and legacy sync**, preserve module ownership and existing public Task/Review DTO behavior, while authorizing the narrow sync-only projection fields specified in the data model. Atomic visibility permits bounded transfer pages for a large transaction; it does not permit partial bulk/archive effects. New protocol clients use explicit conflicts; legacy clients keep their accepted concurrency behavior during the compatibility window. PostgreSQL cutover stops all task writers, preserves receipts/feed/jobs together, and follows the rollback boundary in plan §9 and quickstart.

No amendment authorizes production secrets, migrations, CI changes or release by itself. [approval.md](approval.md) records the separate gates and actual approval status.
