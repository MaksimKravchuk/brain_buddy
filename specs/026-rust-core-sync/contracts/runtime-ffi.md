# Runtime, binding and server-core contract

Status: proposed first-launch Apple/Python contract. Proposed implementation homes are `rust/crates/{bb-domain,bb-protocol,bb-client}`, `rust/bindings/{swift,python}` and `backend/app/modules/tasks/rust_adapter.py`. Android/Kotlin, Windows/C and Linux bindings are separate future stages. Current facade seams are `ios/BrainBuddyKit/Sources/BrainBuddy{Core,Persistence,Sync,Workspace}` and `macos/Package.swift`.

## Pure core

`decide(read_set, command, execution_inputs) -> ChangeSet | DomainError` is deterministic. `execution_inputs` explicitly contains rule version, effective instant/time zone, allocated IDs and trusted policy/capability facts. It has no clock, network, filesystem, credential or random-number access. Read sets include required parents, unique-name candidates, memberships, Review settings/session/receipts and private Undo/park data **only on the authoritative side**. Missing required facts return a typed incomplete-read-set result; they are not silently defaulted.

`ChangeSet` carries domain changes, affected keys, outcome/no-op, result references and durable effect intents. The server adapter authorizes and loads the protected read set under its scope transaction, invokes the core, assigns record/commit versions, and commits domain+receipt+feed+job intent together. Rust never commits a second independent transaction. PyO3 converts expected domain failures into typed values mapped to existing HTTP errors; panics cannot unwind into Python. Calls must not hold the Python GIL during CPU work that does not need Python objects. No provider/network call occurs while holding the scope lock.

`query(consistent_state, query, now, device_zone, policy)` reuses canonical list/order/Review rules. Normalization and date math use the parity vectors; no new platform copy of a reducer is permitted. A synced client lacking private server snapshots can queue a valid intent and show its existing deferred state, but cannot fabricate a successful Undo/yield projection.

## Native runtime surface

The Swift facade owns one runtime handle per open workspace. Shared app-group paths and the migration/writer locks, not a single Swift actor alone, coordinate app/widget/intents. Credentials remain in the platform secure store/HTTP adapter. Call names below describe typed semantics, not a prescribed C-style ABI.

| Call | Input / success result | Failure or lifecycle contract |
| --- | --- | --- |
| `open` | workspace identity/path, supported storage epoch, OS transport/scheduler capabilities, explicit account/session generation → runtime handle + store status | Unknown/newer schema opens protected/read-only recovery state; no destructive fallback. Opening a different account requires a different workspace binding. |
| `execute` | stable gesture command ID, typed command, shown revisions/dependencies → `{command_id, local_sequence, projection_generation, status: locally_saved}` | Success only after durable enqueue+projection commit. Retrying unknown local completion with the same ID returns the stored result; changed content gives typed ID reuse. Network confirmation is not implied. |
| `query` | typed list/detail/project/tag/Review/status query, page size/token → bounded rows + projection generation + continuation | Page token is bound to query and projection generation. Changed generation returns `QUERY_RESTART_REQUIRED`; UI restarts the query, not the sync engine. Never bridge all 10,000 rows for an ordinary list query. |
| `subscribe` | query interests, callback executor → subscription handle | Emits bounded invalidations `{projection_generation, changed_kinds, sync_status_changed}`. Coalesce slow consumers to latest invalidation; they requery. Unsubscribe/close prevents future delivery; queued callbacks check handle/workspace generation. |
| `sync_now` | reason (foreground, network, hint, manual), current authenticated transport context → operation handle | Coalesces concurrent wakes per scope. All request/response fences in sync-v1 §7 apply. Widget queues locally; app owns network work. |
| `cancel` | operation handle → acknowledgement | Before local commit: no write. After commit: command remains saved. Cancelling transport leaves uncertain sends for receipt reconciliation; it is not cancellation of an accepted server effect. |
| `resolve_issue` | issue ID, explicit choice, revision shown, dependent-action choices → atomic issue/queue update | Replacement uses new immutable IDs only after known rejection/reconciliation; current server data changing again can conflict. No force overwrite. |
| `close` | handle → completion after local transactions settle/roll back | Idempotent; cancels transport/subscriptions and invalidates queued callbacks. Durable commands survive. No callback into a released handle. |

All disk, query and network work runs off the UI thread. The Swift facade dispatches completion/invalidation onto its chosen actor/executor; Rust callbacks never synchronously re-enter `execute` while a DB lock is held. DTOs own their values across FFI; high-level UI receives no borrowed pointers or raw SQLite handles. Cancellation and errors are values; errors contain a stable code, retryability, safe reference and relevant version/field names, never raw payload/log strings.

Expected local errors include `VALIDATION_FAILED`, `STORE_BUSY`, `STORE_FULL`, `STORE_CORRUPT`, `STORE_UPGRADE_REQUIRED`, `WORKSPACE_CLOSED`, `AUTH_REQUIRED`, `CANCELLED`, `QUERY_RESTART_REQUIRED` and typed sync issues. A bounded lock timeout is retryable and never reports local save success. Panic handling rolls back a live transaction and marks the runtime unusable if safety cannot be established; reopening follows normal recovery. Platform suspension may prevent a callback but cannot invalidate a committed gesture receipt.

## Migration and packaging boundary

Import reads `StoreDocument`/`FileDocumentStore` through the existing canonicalizers into a staging DB, preserving aliases, ever-sent/idempotency bodies, Review local state, issues and drafts. It validates schema/counts/relationships and replay before an atomic activation marker. The source file/report remains under its accepted backup policy. A failure leaves the original active and returns a typed recovery result; unknown old outcomes become issues, not new commands.

The first bridge slice proves Swift async lifetime/cancellation, app/widget multi-process writes, iOS device/simulator and macOS artifact linking, and the Linux-testable BrainBuddyKit boundary. Pin exact Rust/MSRV/UniFFI/PyO3/SQLite versions only after that build proof. Server/container packaging consumes the same pinned core rule version. Domain parity evidence is shared; binding tests focus on type conversion, decimal-counter precision, nullable/omitted edits, error transport and handle lifetimes, not a duplicate suite for every reducer.

## AI adapter port

A capability request includes feature/language/required response schema, explicit privacy mode, allowed recipient and budget/deadline. Local availability is reported by the OS/model adapter; on-device-only never selects a network adapter on error. A Proposal carries its capability/schema version, recipient/model provenance and candidate command intents; it is not a committed task. Structural + core validation and explicit existing confirmation precede `execute`. Cloud inference is a separate authenticated consent-checking call under the current feature contract; task sync authority cannot authorize it. Cancellation stops unsent transmissions; a started remote effect follows existing uncertainty rules. Model download/runtime selection remains an adapter decision and does not add a new model dependency in this documentation slice.
