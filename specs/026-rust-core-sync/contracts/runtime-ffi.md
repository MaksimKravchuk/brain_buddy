# Runtime, binding and server-core contract

Status: **frozen-v1** (2026-10-09, PR-01; ADR-0031) first-launch Apple/Python contract; semantics are frozen, while exact toolchain and binding versions are pinned only after the bridge build proof below. Implementation homes (still to be created) are `rust/crates/{bb-domain,bb-protocol,bb-client}`, `rust/bindings/{swift,python}` and `backend/app/modules/tasks/rust_adapter.py`. Android/Kotlin, Windows/C and Linux bindings are separate future stages. Current facade seams are `ios/BrainBuddyKit/Sources/BrainBuddy{Core,Persistence,Sync,Workspace}` and `macos/Package.swift`.

## Pure core

`decide(read_set, command, execution_inputs) -> ChangeSet | DomainError` is deterministic. `execution_inputs` explicitly contains rule version, effective instant/time zone, allocated IDs and trusted policy/capability facts. It has no clock, network, filesystem, credential or random-number access. Read sets include required parents, unique-name candidates, memberships, Review settings/session/receipts and private Undo/park data **only on the authoritative side**. Missing required facts return a typed incomplete-read-set result; they are not silently defaulted.

`ChangeSet` carries domain changes, affected keys, outcome/no-op, result references and durable effect intents. The server adapter authorizes and loads the protected read set under its scope transaction, invokes the core, assigns record/commit versions, and commits domain+receipt+feed+job intent together. Rust never commits a second independent transaction. PyO3 converts expected domain failures into typed values mapped to existing HTTP errors; panics cannot unwind into Python. Calls must not hold the Python GIL during CPU work that does not need Python objects. No provider/network call occurs while holding the scope lock.

`query(consistent_state, query, now, device_zone, policy)` reuses canonical list/order/Review rules. Normalization and date math use the parity vectors; no new platform copy of a reducer is permitted. A synced client lacking private server snapshots can queue a valid intent and show its existing deferred state, but cannot fabricate a successful Undo/yield projection.

## Query kinds

`query` takes one typed `Query`, tagged by `kind`, and answers one `QueryResult` tagged the same way (`bb-domain` `Query`/`QueryResult`, `dispatch::QueryKind`). Every kind has exactly one owning rule family; a kind no family claims is a typed refusal, never a placeholder.

| `kind` | Reads | Owner |
| --- | --- | --- |
| `task_list` | one open list (the server's `GET /tasks?state=`): sort, project/tag scope, keyset page, `counts_by_state` | `queries` |
| `task_detail`, `list_counts`, `projects`, `project_display`, `tags` | detail with children, badge counts, project and tag summaries | `queries` |
| `review_state`, `review_queue` | native Review reads (weekly-review flag gated) | `review_sessions` |
| `list_mode` | **amended 2026-10-09**: the native list modes below | `list_modes` |

`list_mode` (owner decision 2026-10-09: the Apple client's extra destinations become shared queries, so every client reuses them) is `{kind: "list_mode", mode, options?, page}`:

- `mode` is `{type: "history", kind: "completed"|"cancelled"}`, `{type: "agenda"}`, `{type: "date_view", view: "overdue"|"today"|"upcoming"}` or `{type: "search", text}`.
- `options` (all optional) is `{sort: manual|due|priority|title, group_by_project, show_completed, show_cancelled, priorities[], tag_filter}`, `ListOptions` of the Apple kit. Unknown members are refused.
- `page` is `{limit: 1..200, after}`. The result is `{sections: [{id, title, kind: {type: open|project|date_view|completed|cancelled, ...}, items: TaskView[]}], open_count, next_cursor, has_more}`: the rows of the whole result in section order, one bounded page of it. A section a page starts inside repeats its `id`. `open_count` counts the whole result. Memory is O(limit) for any store size.
- The cursor is the `task_list` token format (base64url JSON of the filters it must match and the last key) whose key starts with the id of the last row's section followed by that section's order key at the time the cursor was issued (a project's archived flag, folded and normalized name, display name and id), then the row's key. Renaming, archiving or unarchiving that section's project makes the cursor `invalid_value` on `cursor` instead of letting it skip or repeat rows; the client restarts from the first page. Sections are ordered by a key computed from each row's own project, so grouping adds no memory beyond the page. Another mode, option, filter or device day, an unknown section or a key of the wrong shape is refused as `invalid_value` on `cursor`. The Agenda and date views read `now` and `device_zone` for the day; History and Search do not.
- The Apple kit is normative for these modes (`GTDQueries.list`, `Queries+List.swift`, `Queries+Ordering.swift`), which decides register entries C-05 and C-06 of `reference-store.json` for them only: Search and title order fold diacritics as well as case, a search query collapses White_Space (not Python's class), and grouped sections follow `NameSortKey` (diacritic-folded name, archived last, "No project" last). `task_list`, `projects` and `tags` keep the server's rules. The kit's per-list placement of completed tasks (`lastOpenList`, local knowledge that is not replicated) is not part of `list_mode`.

Native `projects` also accepts `{kind: "projects", filter: "needs_next_action"}`. It selects active projects whose whole-project `next_action_count` is zero, including projects without open tasks. Eligibility and `open_task_count`/`next_action_count` use all canonical member tasks before pagination; the existing name/ID keyset and generation/query/frozen-input fences apply, with at most 200 summaries per page. The server's `state` parameter remains `active|archived|all`.

## Native runtime surface

The Swift facade owns one runtime handle per open workspace. Shared app-group paths and the migration/writer locks, not a single Swift actor alone, coordinate app/widget/intents. Credentials remain in the platform secure store/HTTP adapter. Call names below describe typed semantics, not a prescribed C-style ABI.

| Call | Input / success result | Failure or lifecycle contract |
| --- | --- | --- |
| `open` | workspace identity/path, supported storage epoch, OS transport/scheduler capabilities, explicit account/session generation → runtime handle + store status | Unknown/newer schema opens protected/read-only recovery state; no destructive fallback. Opening a different account requires a different workspace binding. |
| `execute` | stable gesture command ID, typed command, shown revisions/dependencies → `{command_id, local_sequence, projection_generation, status: locally_saved}` | Success only after durable enqueue+projection commit. Retrying unknown local completion with the same ID returns the stored result; changed content gives typed ID reuse. Network confirmation is not implied. |
| `lookup_known_batch` | original prepared commands/context → `Known { results }` or `NotKnown` | One read snapshot checks every original fingerprint. Any known ID with changed content gives ID reuse; any unknown ID gives whole-batch `NotKnown`. Never executes a suffix, validates admission, rebuilds/replays a projection, mints IDs or writes. |
| `query` | typed list/detail/project/tag/Review/status query, page size/token → bounded rows + projection generation + continuation | Page token is bound to query and projection generation. Changed generation returns `QUERY_RESTART_REQUIRED`; UI restarts the query, not the sync engine. Never bridge all 10,000 rows for an ordinary list query. |
| `subscribe` | query interests, callback executor → subscription handle | Emits bounded invalidations `{projection_generation, changed_kinds, sync_status_changed}`. Coalesce slow consumers to latest invalidation; they requery. Unsubscribe/close prevents future delivery; queued callbacks check handle/workspace generation. |
| `sync_now` | reason (foreground, network, hint, manual), current authenticated transport context → operation handle | Coalesces concurrent wakes per scope. All request/response fences in sync-v1 §7 apply. Widget queues locally; app owns network work. |
| `cancel` | operation handle → acknowledgement | Before local commit: no write. After commit: command remains saved. Cancelling transport leaves uncertain sends for receipt reconciliation; it is not cancellation of an accepted server effect. |
| `resolve_issue` | issue ID, explicit choice, revision shown, dependent-action choices → atomic issue/queue update | Replacement uses new immutable IDs only after known rejection/reconciliation; current server data changing again can conflict. No force overwrite. |
| `close` | handle → completion after local transactions settle/roll back | Idempotent; cancels transport/subscriptions and invalidates queued callbacks. Durable commands survive. No callback into a released handle. |

All disk, query and network work runs off the UI thread. The Swift facade dispatches completion/invalidation onto its chosen actor/executor; Rust callbacks never synchronously re-enter `execute` while a DB lock is held. DTOs own their values across FFI; high-level UI receives no borrowed pointers or raw SQLite handles. Cancellation and errors are values; errors contain a stable code, retryability, safe reference and relevant version/field names, never raw payload/log strings.

Native task reads additionally return `task_frames`, sibling metadata for each
original returned task: its content-free LOCAL `token` and `last_open_list`
(including explicit null when unknown). A v1 token identifies the canonical
workspace/task, child completeness, captured subtask IDs in relative order,
sorted comment IDs, a domain-separated SHA-256 digest of visible task/child
semantics, and the maximum retained committed local child-command sequence for
that task. Rust captures it in the same SQLite read transaction as the original
task response. Server revisions/ACK-only IDs, write timestamps and comment
authors are excluded; formulation clock facts remain visible semantics.
Full-known frames compare exact child sets and subtask order keys. Partial
frames compare only captured children and their relative order, accepting unseen
hydration; the local child witness still detects local insert/edit/revert.

Interactive Review cards/forms retain that original token through awaits and
send it unchanged in LOCAL `admission_tokens`; an old interactive card without
its original token safely refuses/reloads while preserving authored input.
Do not mint a replacement token by querying at save. `ShownTask` remains an
ephemeral content-bearing snapshot, never encoded or stored. Only the
content-free token and original request fingerprint accompany the existing
durable prepared-gesture draft; neither token nor snapshot is a sync-envelope,
receipt or server/replay field. No additional ledger or schema is introduced.
Under the write lock, original fingerprint/known-result lookup precedes local
admission and normalization: exact known retries return the durable result even
after the frame changed; unknown token mismatch returns `formulation_changed`
without enqueueing. Trusted noninteractive calls, legacy conversion and replay
retain their existing semantics; Rust validates every token that is supplied.
When an old restored interactive prepared gesture has no original token, the
host first uses `lookup_known_batch`: a fully known result recovers its saved
completion; `NotKnown` preserves its draft/input and refuses/reloads without
executing any unknown suffix. Empty token arrays are omitted from fingerprints,
so recovery compares old immutable requests unchanged.

Ordinary list/Review tokens describe only the actual returned child subset;
hosts replace older cached children and apply the associated knownness/origin.
They cannot pair a partial token with a previously hydrated display. A native
detail continuation repeats the parent with at most 200 total child rows per
page; every continuation/truncated frame is partial, including the final
continuation page. Only a source-complete first page without continuation may
claim full-known children. Combining pages must not silently promote the newest
page token into admission for an accumulated display.

For a new atomic batch, the runtime captures batch-start task revisions after
any stale-projection rebuild. A numeric shown task guard must match that start;
only the latest exact fresh same-batch task producer with domain-enforced
Task concurrency proof may substitute its actual result via `after_command`.
Ordinary numeric guards genuinely shown after historical producers still use
the existing exact-shown pending wire conversion; history cannot rebase a stale
numeric guard or provide fresh-batch proof. An original fresh `tag.delete` may carry task guards
only for explicit later dependents; its owning domain checks those guards before
any mutation. Unguarded standalone deletion remains unchanged. Historical
tag-delete results do not supply fresh producer proof or rebase a stale new
update; their immutable envelopes are never retrofitted. Fresh skipped bulk
items retain their separately proven original effective guard and dependency,
without inventing a result version or normalizing onto the skipped bulk item.

Expected local errors include `VALIDATION_FAILED`, `STORE_BUSY`, `STORE_FULL`, `STORE_CORRUPT`, `STORE_UPGRADE_REQUIRED`, `WORKSPACE_CLOSED`, `AUTH_REQUIRED`, `CANCELLED`, `QUERY_RESTART_REQUIRED` and typed sync issues. A bounded lock timeout is retryable and never reports local save success. Panic handling rolls back a live transaction and marks the runtime unusable if safety cannot be established; reopening follows normal recovery. Platform suspension may prevent a callback but cannot invalidate a committed gesture receipt.

## Migration and packaging boundary

Import reads `StoreDocument`/`FileDocumentStore` through the existing canonicalizers into a staging DB, preserving aliases, ever-sent/idempotency bodies, Review local state, issues and drafts. It validates schema/counts/relationships and replay before an atomic activation marker. The source file/report remains under its accepted backup policy. A failure leaves the original active and returns a typed recovery result; unknown old outcomes become issues, not new commands.

The first bridge slice proves Swift async lifetime/cancellation, app/widget multi-process writes, iOS device/simulator and macOS artifact linking, and the Linux-testable BrainBuddyKit boundary. Pin exact Rust/MSRV/UniFFI/PyO3/SQLite versions only after that build proof. Server/container packaging consumes the same pinned core rule version. Domain parity evidence is shared; binding tests focus on type conversion, decimal-counter precision, nullable/omitted edits, error transport and handle lifetimes, not a duplicate suite for every reducer.

## AI adapter port

A capability request includes feature/language/required response schema, explicit privacy mode, allowed recipient and budget/deadline. Local availability is reported by the OS/model adapter; on-device-only never selects a network adapter on error. A Proposal carries its capability/schema version, recipient/model provenance and candidate command intents; it is not a committed task. Structural + core validation and explicit existing confirmation precede `execute`. Cloud inference is a separate authenticated consent-checking call under the current feature contract; task sync authority cannot authorize it. Cancellation stops unsent transmissions; a started remote effect follows existing uncertainty rules. Model download/runtime selection remains an adapter decision and does not add a new model dependency in this documentation slice.

Suggestion lifecycle follows design M-04/D-04.13–15: persist explicit local cancellation before releasing the request, fence late responses by request/owner/consent generation, and discard cancelled transient results without losing authored drafts. UI closure alone does not cancel; reconnect to a still-live request or the existing ADR-0002 operation. A lost synchronous navigator request becomes interrupted/unknown without automatic resubmission. New transmission requires another explicit request and current consent; no adapter promises to recall already sent data.

The existing task navigator returns exactly one of proposals or a clarifying question. The adapter preserves that typed union and implements M-04/D-04.16–20: the explicit answer action saves one ordinary notes command, adopts the saved projection/revision, then requests suggestions with updated input and current consent. Persist notes-command identity and save/inference phase; an unknown save is reconciled, and an inference retry cannot append the answer twice. Draft and separate save/inference errors survive interruption.
