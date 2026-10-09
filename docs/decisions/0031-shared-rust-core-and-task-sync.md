# ADR-0031: Shared Rust core and custom task sync

- **Status**: Accepted
- **Date**: 2026-10-08 (drafted); accepted 2026-10-09
- **Decision owner**: MaksimKravchuk (product owner)
- **Sign-off**: the owner accepted the specification 026 technical baseline and its
  residual risks on 2026-10-09 (`specs/026-rust-core-sync/approval.md`,
  `evidence/026-native-20261009-1/owner-acceptance.json` and `human-signoff.json`;
  planning gate `approved` in `accepted-summary.json`). That record accepted this
  proposal "for enactment in PR-01". On 2026-10-09 the owner also answered "Да, делай PR-01"
  (yes, do PR-01) in the delivery conductor session, authorizing exactly this enactment:
  this ADR as Accepted, the Constitution IV exception, the Apple dependency allowance,
  frozen contracts with generated schema/OpenAPI, and a default-OFF `rust_core_sync`
  capability. That answer is recorded here as relayed; no separate evidence file exists.
- **Landing**: slice PR-01 of `specs/026-rust-core-sync/`.
- **Source**: `specs/026-rust-core-sync/adr-draft.md`, kept as history.
- **Amends**: ADR-0001 (implementation of Tasks rules and its server persistence only)
  and ADR-0027 (storage technology and shared-rule implementation, plus the command
  metadata extension below).
- **Preserves**: ADR-0001 data ownership, application ports and module boundaries;
  ADR-0027 auto-park, yield and review semantics, content-retention limits and
  task+review atomicity; ADR-0026 CRT protocol; ADR-0028 Identity authority.

## Decision

The normative Tasks and native-task Review rules are implemented in one pure Rust
library. Native clients use a Rust client runtime with SQLite and a durable queue; the
backend calls the domain core through PyO3 and keeps the Identity authority. New task
sync transports commands, receipts and atomic changes. PostgreSQL is the target task
store, introduced through a separate controlled migration. The modular monolith remains.

Moving Tasks does not make every storage system one transaction: the CRT, Identity,
Capture and Organize databases, receipts, exports and recovery stay in their modules.

Spec 021's last-push-wins behavior is replaced by explicit conflicts for the new protocol
cohort only. Legacy clients keep their documented contract during the compatibility
window and their writes stay visible to new clients.

## Enacted amendments

1. **Constitution IV** (version 4.0.0, `.specify/memory/constitution.md`): correlation and
   observability IDs stay labels only. Dedicated owner-scoped command IDs may identify an
   immutable command for durable deduplication under an accepted domain contract. No
   client-supplied ID grants authority; replay rechecks current authority and rejects
   changed content under the same ID. Entity IDs alone never authorize upsert or replay.
   ADR-0027's bounded Review exception is unchanged.
2. **Apple dependency policy** (`ios/AGENTS.md`): the no-third-party default stays. The
   shared Rust domain/runtime and their audited, pinned generated Swift bindings are
   allowed, with reviewed build inputs, licenses, lockfile, reproducible packaging,
   supported targets and the Foundation-only Linux test boundary. Arbitrary Swift
   packages, bundled model weights and unrelated native dependencies stay forbidden.
3. **Command metadata retention**: ordinary task/Review full responses keep their 24-hour
   maximum. Content-free command identity, outcome and fingerprint metadata survives until
   account purge. Feed, snapshot, oversized-transaction staging and backup copies inherit
   the source expiry or deletion (including seven-day Review recovery content) and cannot
   extend it. Device SQLite, outbox, issues and drafts keep the current owner-specific
   sign-out, export and legacy backup policy; no diagnostic upload is implied. Restore
   points last at most seven days, and purge cannot finish while a recoverable controlled
   backup still holds the purged owner. This obligation is carried into
   `docs/data-retention.md` and the privacy disclosure before rollout; it authorizes no
   longer retention of user text.
4. **Contracts frozen** as v1: `contracts/command-catalog.md`, `contracts/runtime-ffi.md`,
   `contracts/sync-v1.md`, with `sync-v1.schema.json` and `sync-v1.openapi.yaml` generated
   from the same catalog.

## Why not the alternatives

Server rules without a shared client runtime cannot give identical offline behavior.
Managed sync would cut transport work, but the owner chose custom sync, so we own
snapshots, ordering, retention, deduplication and recovery. A universal CRDT does not
solve authorization, AI confirmation or external effects. Rewriting the backend in Rust
would widen the migration without being needed to share rules.

## Consequences

The team maintains an FFI/build matrix and its own sync protocol. Shared rules are tested
once; platform boundaries, databases, networking and AI models still need their own
checks. Conservative conflicts sometimes need an extra user choice.

## Not authorized by this record

No production secret, migration, data deletion, CI change, cutover or release. ASK-class
actions keep their exact-SHA checks and separate authorization. The `rust_core_sync`
capability is specified OFF by default (plan section 9) and is enabled only after the
gates listed there; this ADR does not enable it. The measurements for the complex slices (PR-03/04/05/34/49/59/60/61/62/64) are still
outstanding; this ADR certifies no slice size.
