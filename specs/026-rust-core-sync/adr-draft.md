# Proposed ADR: shared Rust core and task sync

Status: Proposed, 2026-10-08. An accepted ADR number is not reserved yet. The user confirmed the Rust + custom sync direction; the concrete protocol, UX, and migration boundaries below are proposed for acceptance.

## Decision

The normative Tasks and native-task Review rules are implemented in one pure Rust library. Native clients use a Rust client runtime with SQLite and a durable queue; the backend calls the domain core through PyO3 and preserves the current Identity authority. New task sync transports commands, receipts, and atomic changes. PostgreSQL is the target task store, introduced through a separate controlled migration. The modular monolith remains.

## Decisions being amended

ADR-0001 changes only in the implementation of Tasks rules and its server persistence. Data ownership, application ports, and Capture/Organize/Tasks/Thinking/Execution/Identity boundaries remain. ADR-0027 changes only in storage technology and shared-rule implementation; its auto-park, yield, and review semantics and task+review atomicity remain mandatory.

The current `ios/AGENTS.md` instruction, “No third-party dependencies,” needs a narrow allowance for audited, pinned Rust bindings and their required runtime. The product dependency policy can change only after that amendment is accepted; arbitrary Apple packages are not permitted.

Spec 021's last-push-wins behavior for current sync is replaced by explicit conflicts for the new protocol cohort. Legacy clients retain their documented contract during the compatibility window; their writes remain visible to new clients. The new UX must be accepted explicitly rather than presented as an invisible internal optimization.

ADR-0026's CRT protocol and ADR-0028's Identity authority are not superseded. Their databases, receipts, exports, and recovery remain in their respective modules. Moving Tasks does not justify treating every storage system as one transaction.

## Why not the alternatives

Server rules without a shared client runtime cannot provide identical offline behavior. Managed sync would reduce some transport work, but the user selected custom sync, so we own snapshots, ordering, retention, deduplication, and recovery. A universal CRDT does not solve authorization, AI confirmation, or external effects; a command protocol and explicit conflicts are sufficient for current tasks. Rewriting the whole backend in Rust would enlarge the migration surface without being necessary to share rules.

## Consequences

The team maintains an FFI/build matrix and its own sync protocol. Shared rules are tested once, but platform boundaries, databases, networking, and different AI models still need their own checks. Conservative conflicts sometimes require an extra user choice. Duplicate prevention and recovery of legacy uncertainty matter more than a smooth happy-path demonstration.

## Acceptance conditions

Acceptance requires review of the concrete [contract](contracts/sync-v1.md), UX sign-off for [design.md](design.md), validated limits, and an exact migration/rollback boundary. This draft does not authorize data deletion, production schema changes, or automatic release.
