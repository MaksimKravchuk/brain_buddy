# Runtime, binding and server-core contract

Status: **frozen-v1** (2026-10-09, PR-01; ADR-0031) first-launch Apple/Python contract; semantics are frozen, while exact toolchain and binding versions are pinned only after the bridge build proof below. Implementation homes (still to be created) are `rust/crates/{bb-domain,bb-protocol,bb-client}`, `rust/bindings/{swift,python}` and `backend/app/modules/tasks/rust_adapter.py`. Android/Kotlin, Windows/C and Linux bindings are separate future stages. Current facade seams are `ios/BrainBuddyKit/Sources/BrainBuddy{Core,Persistence,Sync,Workspace}` and `macos/Package.swift`.

## Pure core

Historical native import compatibility: an existing formulation reference may
be an exact 36-character ASCII UUID from the Swift store. Its hexadecimal case
and value remain unchanged through task clocks, park markers, Review migration,
draft keys and commands; identity is established by the admitted source and
matched owning task/park, never by adding a prefix or an inferred alias. This is
an exception to the prefixed reference wording for existing imported IDs only.
New client IDs remain `form_<lowercase UUID>`; trusted allocations accept only
that shape or the existing server `form_<12 lowercase hex>` shape. Other Review
ID types and backend REST `FormulationRef` validation retain their contracts.

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

An `execute` batch refusal also carries optional LOCAL `failed_command_id`: the exact original prepared request whose command or admission check refused. Batch-global failures and migration conversion may omit it; callers must not guess an authored command when it is absent. This context is not part of the immutable envelope, fingerprint or durable result, and a refusal still rolls back the entire batch.

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

A durably bound account (the existing trusted session binding: linked account,
validated account/scope/device identities) may save an Undo whose public source,
task revision, dependencies and original seven-day deadline pass, but whose
server-private beforeimage is absent from the native read. The owning domain
reports only that precise absence as `INCOMPLETE_READ_SET`, with the Undo source
entity and `undo_snapshot`, `released_private` or `clock_before` field. Actual
stale/expired/purged authoritative snapshots and malformed present facts remain
refusals. Account-less/imported-but-unbound stores gain no private authority.

Such a bound Undo saves its immutable intent and original fingerprint to the
existing outbox without changing public rows, inventing result versions or
marking a bulk release undone. Every required missing bulk beforeimage or Next
clock holds the whole Undo, even when all public items would be skipped; only a
stored already-undone result can answer its genuine no-op without that proof.
Queue/status tokens invalidate even when the
projection generation does not advance. Replay holds that exact missing-private
case and its descendants, including never-sent intents, while independent work
continues. An atomic batch requiring the unavailable Undo result version rolls
back; verified receipt/feed outcomes retain their normal semantics. Known retry
lookup precedes later expiry. An optimistic decision's absent
`undo_available_until` is not sufficient by itself to decide whether to offer
Undo; capability must come from the owning domain and bound runtime contract.

Expected local errors include `VALIDATION_FAILED`, `STORE_BUSY`, `STORE_FULL`, `STORE_CORRUPT`, `STORE_UPGRADE_REQUIRED`, `WORKSPACE_CLOSED`, `AUTH_REQUIRED`, `CANCELLED`, `QUERY_RESTART_REQUIRED` and typed sync issues. A bounded lock timeout is retryable and never reports local save success. Panic handling rolls back a live transaction and marks the runtime unusable if safety cannot be established; reopening follows normal recovery. Platform suspension may prevent a callback but cannot invalidate a committed gesture receipt.

Local Review form ports return one selected typed `{text, savedAt}` form, its
exact source key, and the effective live count under one projection generation.
`load_review_form(key, now)`, `review_form_count(now)`,
`save_review_form(key, source_key?, draft?, now, operation)` (null clears) and
`clear_review_forms_for_task(canonical_task_id, now, operation)` use existing
draft rows. The immutable `legacy-form:<source_key>` carrier remains unchanged;
one deterministic `runtime:review-form:<sha256(source_key)>` overlay stores a
typed form or a content-free cleared tombstone. Expired overlays still shadow
their carriers. Generic draft CRUD cannot modify or delete these overlays.
Mutation, cancellation arbitration, derived count and one generation increment
share a transaction; draft-only commits invalidate the existing cross-process
subscription. No form index, whole-form body export or persisted count exists.

Effective counts stream forms and match the existing native liveness contract:
`now - savedAt < 7 days`; decision forms require an existing task and, when named,
an exact current or parked formulation ID. Project and step forms use age only.
Reverse identity requests are bounded to 200 typed canonical IDs and return only
an exact unique source alias; canonical IDs and opaque step items remain verbatim
without such proof. Canonical-key and source-key forms both present are refused
as ambiguous, never merged. Imported normalized identities acquire aliases only
at the source-validated import/Review activation transaction. Cleared overlays
carry no authored draft for ambiguity checks, so explicit task-wide clearing can
be followed by a fresh editor save while both fallback shadows remain.
Earlier imports
without that proof are not backfilled heuristically. An unexpired decision form
whose source task is a bare UUID, lacks an exact alias, and has no same-ID task
refuses as identity unproven, including an uncertain historical deletion until
expiry. Formulation IDs are never matched by stripping or adding a prefix.
Project discovery similarly refuses an unexpired bare source-project key
without an exact alias or same-ID canonical project. Step discovery refuses an
unexpired bare source-session key with the same exact step and opaque item when
its identity has no such proof. These conservative refusals preserve text until
proof recovery or expiry; project/step aggregate eligibility still uses age only.

`prune_review_forms(now, operation)` is the existing native upkeep's narrow
runtime port, including when Review is off or the workspace is accountless.
Load, foreground, completed pull/snapshot and background upkeep schedule it.
Within one transaction it examines validated mutable overlays only, tombstones
expired/orphaned/formulation-stale text without revealing a legacy fallback,
and returns count/generation. Generation advances once only when text changes;
repeated no-op pruning does not invalidate. Malformed relevant data or unproven
identity aborts safely. Immutable imported carriers retain the import backup
policy. Cleanup failures retry separately and cannot relabel a committed command
or form save as failed.

## Migration and packaging boundary

Import reads `StoreDocument`/`FileDocumentStore` through the existing canonicalizers into a staging DB, preserving aliases, ever-sent/idempotency bodies, Review local state, issues and drafts. It validates schema/counts/relationships and replay before an atomic activation marker. The source file/report remains under its accepted backup policy. A failure leaves the original active and returns a typed recovery result; unknown old outcomes become issues, not new commands.

Legacy receipt proof requires the original idempotency key and immutable command body. If any carried entries share a normalized key but have different bodies, the key-only receipt boundary excludes all sends under that key and classifies them without proof, even when a host supplies acceptance or rejection. Sent entries await proof inside the prior retention window and remain uncertain issues afterward; carried intent is never rewritten or reissued. Identical key/body pairs may share proof only when each entry actually used that key. An ever-sent entry whose current key was never used remains immediately uncertain: a receipt for that key cannot prove the earlier send. An accepted receipt's aliases must agree for each `(entity_type, old_local_id)` both with prior proof and with every alias in the receipt; a contradiction installs no aliases and leaves the send unproven.

The first bridge slice proves Swift async lifetime/cancellation, app/widget multi-process writes, iOS device/simulator and macOS artifact linking, and the Linux-testable BrainBuddyKit boundary. Pin exact Rust/MSRV/UniFFI/PyO3/SQLite versions only after that build proof. Server/container packaging consumes the same pinned core rule version. Domain parity evidence is shared; binding tests focus on type conversion, decimal-counter precision, nullable/omitted edits, error transport and handle lifetimes, not a duplicate suite for every reducer.

## AI adapter port

A capability request includes feature/language/required response schema, explicit privacy mode, allowed recipient and budget/deadline. Local availability is reported by the OS/model adapter; on-device-only never selects a network adapter on error. A Proposal carries its capability/schema version, recipient/model provenance and candidate command intents; it is not a committed task. Structural + core validation and explicit existing confirmation precede `execute`. Cloud inference is a separate authenticated consent-checking call under the current feature contract; task sync authority cannot authorize it. Cancellation stops unsent transmissions; a started remote effect follows existing uncertainty rules. Model download/runtime selection remains an adapter decision and does not add a new model dependency in this documentation slice.

Suggestion lifecycle follows design M-04/D-04.13–15: persist explicit local cancellation before releasing the request, fence late responses by request/owner/consent generation, and discard cancelled transient results without losing authored drafts. UI closure alone does not cancel; reconnect to a still-live request or the existing ADR-0002 operation. A lost synchronous navigator request becomes interrupted/unknown without automatic resubmission. New transmission requires another explicit request and current consent; no adapter promises to recall already sent data.

The existing task navigator returns exactly one of proposals or a clarifying question. The adapter preserves that typed union and implements M-04/D-04.16–20: the explicit answer action saves one ordinary notes command, adopts the saved projection/revision, then requests suggestions with updated input and current consent. Persist notes-command identity and save/inference phase; an unknown save is reconciled, and an inference retry cannot append the answer twice. Draft and separate save/inference errors survive interruption.


### Explicit accountless local Review capability (T043; activation remains T044)

The trusted workspace lifecycle port `establish_account_less` selects durable
`account_link_state=account_less` only for a wholly unbound workspace without
remote-sent history, receipts or an active server base. Missing credentials or
scope do not select it. The imported-base variant
`establish_account_less_from_import(retained_source_path)` uses an importer-only,
non-serializable proof: exact retained source length and SHA-256 match the admitted
activation marker, the existing importer parses the source and proves its account
is absent, and the setup transaction rechecks the marker and unbound pre-conversion
sequence/history. Neither operation relabels an existing command or server record.

The Rust-only local Review dispatcher grants private Review bookkeeping to the
same Review rule bodies. The ordinary serialized `ExecutionInputs.authoritative`
contract stays unchanged. Versioned private-field overlays live in the reserved
`runtime:local-review-private:` draft namespace, inaccessible to generic host draft
CRUD, and bind a typed record identity and its exact public fingerprint to a local
command provenance and the original source instant/deadline. Matching evidence is
injected only into the private local decision read set. All public records use
`Record::public()` before persistence or bridge reads.

Accepted local commands settle atomically: immutable original intent/fingerprint,
sequence, dependencies and local result references; final public confirmed and
visible records; private overlays; local confirmed origins; and completed outbox
state. Each retained local record version advances from its own previous version,
including tombstones. No receipt, feed cursor, watermark or server generation is
invented. Completed commands are skipped by replay and cannot be send candidates. Send selection additionally requires the durable linked
mode, validated bound owner identities and an original envelope carrying that
exact scope/device. Registration alone cannot make an unbound historical intent
sendable.
A known retry returns its original saved result before expiry or upkeep checks.

`prune_local_review_private(now, limit)` is bounded to 1–200 expired overlay rows
and may be coalesced independently of Review exposure. Decision and bulk beforeimages
expire at their original seven-day deadlines; saving/retrying does not extend them.
Upkeep never changes completed public effects, and replay cannot recreate expired
private evidence. Importing public Review rows alone grants no Undo beforeimage:
missing or unproved source snapshots remain a refusal until an exact typed private
activation is admitted. Production selection, account linking and pilot evidence
remain T044 work; these ports do not activate the capability automatically.

LOCAL Undo evidence additionally preserves a replaced receipt and session activity
before-state. A receipt is restored only while the current receipt still belongs
to the decision/bulk being undone; its task revision is rebound only when the
original task-match evidence proved it valid. A session restores its previous
qualification/activity only when its exact saved postdecision time and revision
still match. Subsequent receipts and session progress stay intact. These optional
private fields are absent on the ordinary server path and do not change public
record formats.

Private migration uses `capture_local_review_private_fragment(retained_source_path,
selected_source, after, now)` and `admit_local_review_private_fragment(retained_source_path,
prepared_page, now, operation)`. The source selector names one decision, bulk,
parked task, session, or the settings singleton (`source_id="settings"`). Capture
returns one optional page; expired decision/bulk sources return null. Each page
has at most 200 total array entries, typed aliases, task witness/pin rows and
present session witness/pin rows, and at most 8 MiB. Task witnesses carry only
identity, original optional server revision and update time. Scalar TaskBefore
omits child collections and tags; separate tag components retain all original
tags. Session scalar excludes queues, set-aside IDs and progress IDs. Bulk source
and public rows contain matching released slices, never a repeated whole bulk.
These narrow witnesses make no full-task or child-completeness claim.

The capture-owned header binds the codec version, exact importer/Review source
token, whole original source digest, owner public digest/record version, component
lengths and original deadline. `source_at` is nullable for timeless settings;
absence of `thresholdChangedAt` remains absence. Decision/bulk dates and seven-day
deadlines are required and immutable. Each prepared page echoes the header,
ordinal, component, offset/count, fragment digest and bounded task/session pins.
The existing native business codec supplies typed private fields independently
for each page; Swift does not concatenate a large final payload.

Contiguous validated components accumulate in a reserved pending draft distinct
from an active private overlay. A gap, overlap or changed same-ordinal submission
refuses; an exact retry is a no-op. Incomplete components never enter a private
ReadSet. The final transaction recomputes every original slice, checks complete
coverage, all public/task/session pins and current original expiry, constructs the
whole shared private type in Rust, installs it and removes the pending draft
atomically. Admission returns `pending { next_ordinal }`, `admitted`, or
`already_admitted`. A small completion manifest retains only header/request
digests; known completion lookup precedes backup reopening and expiry checks.
Upkeep prunes expired pending and active private content without changing public
records or recreating private content from the immutable backup.

Imported Undo task/created-task eligibility requires the exact original source
stamp (optional update-time wildcard, exact optional server revision equality),
unchanged imported record version, public fingerprint and pinned native edit
revision. Native zero is a representation, never proof. Source-stale bulk rows
retain a LOCAL-only false match witness and skip before missing clock restoration;
server behavior stays unchanged. Imported session progress retains exact source
progress IDs in `SessionPrivate.local_imported_progress`. Only LOCAL recognizes
those IDs as already applied, after checking the run's allowed steps. Native
progress keeps its existing body digest map; Done, replacement and idle-close
clear both sets. No digest or finished-empty classification is fabricated.

Native task pages also attach optional `TaskView.formulation_state` from the
owning formulation helper using the same read transaction and matching LOCAL
private evidence. This is a closed public DTO and avoids per-row bridge reads.
Pure/server task views omit the field; ordinary record reads remain public.


Bootstrap uses `capture_legacy_review_metadata()`, returning an owned
`BridgeLegacyReviewMetadata { token, source_counts, already_active }`. It exposes
no Review/source bodies, private beforeimages or alias collection. The host
resolves required identities through the existing bounded identity port.
`BridgeDigest` is an ephemeral, ordered SHA-256 stream over owned byte chunks:
`update` refuses a chunk larger than 8 MiB before changing state, and `digest`
returns repeatable lowercase hexadecimal without consuming state. It grants no
store authority. The host compares byte count and digest of the same immutable
Data it will decode with the admitted import report before bootstrap effects.

`local_review_private_source_completed(retained_source_path, selected_source)`
verifies the existing immutable import proof and reads a content-free completion
manifest. It returns true only for that exact original source, even after later
local public edits; it never repins edited records, promotes pending fragments,
installs an overlay or mutates generation. Pending/unknown sources return false.
A manifest retains a source-provenance digest alongside the existing header and
request digests. Successful private admission/upkeep requires host cache
invalidation because these private changes do not advance public projection
generation.

### Bounded native legacy conversion

Accountless preparation encodes the verified original never-sent sequence once in
host memory, including keys already converted on a prior attempt. It never bridges
the full queue. `beginLegacyConversion` freezes the existing execute context in an
import/workspace/authority-bound reserved draft before encoding; each request still
uses its original `issuedAt`. The context survives completion for deterministic
retry. Original IDs, key casing, timestamps and source order remain immutable.

`legacyConversionPage` uses immutable source ordinal keysets, with at most 200
items and 8 MiB of owned JSON before crossing FFI. The compatibility `legacyUnsent`
array refuses oversized results instead of returning an incomplete array. Ordinary
`convertLegacyConversionPage` commits only the earliest unresolved contiguous
prefix, allowing exact-known converted leading retries and checking every original
request fingerprint. It never skips a gap or reissues a sent/uncertain entry.

Any original never-sent `deleteTag` or `bulkRelease` conservatively forces the
whole original sequence into one prepared atomic group before prefix effects.
`convertLegacyConversionPage(atomicStage: true)` streams bounded typed fragments
into existing reserved drafts; source interval/count/digests and the runtime seal
replace an unbounded header ID array. Incomplete stages have no command or
conversion effects. `finalizeLegacyConversion` rechecks source pins, authority,
contiguous eligibility and the seal, then runs the existing `execute_batch_in`, all
resolution markers and payload-fragment cleanup in one transaction. It returns
scalar progress and global status. Fresh-only TagDelete/bulk-skip proof remains
restricted to that transaction; historical reference semantics do not change.

Exact completed retries check every supplied original fingerprint against known
intents and recompute the ordered seal, without recreating payload fragments. Mixed
converted/unconverted atomic groups, changed source/body, gaps and reordered pages
refuse without effects. Each write shares the existing BridgeOperation cancellation
and commit arbitration: precommit cancellation rolls back that write; durable
prefixes/stages remain saved after interruption. Workspace binding requires the
whole classified outbox's `mayRun`, never a page or caller completion assertion.

If classification already proves global `mayRun`, preparation skips conversion
altogether. Earlier full-port conversions may have no frozen-context header;
resolved work must not be re-encoded with today's actor, zone or policy merely to
create one. Explicit supplied bounded retries still check every original
fingerprint, and incomplete migrations still use their frozen context.
