# Tasks: shared Rust core and custom synchronization

**Status:** amended implementation map following the owner's October 9 requirement for atomic PRs and maximum safe parallel execution; technical baseline accepted in [approval.md](approval.md), empirical boundary approval remains conditional. The specification request authorizes these documents, not implementation, new UX approval, migration or deployment. No implementation task is complete. The JSON below is deliberately present for review and structural validation while its status remains `proposed`.

**Input:** [spec.md](spec.md), [plan.md](plan.md), [design.md](design.md), [data-model.md](data-model.md), [command catalog](contracts/command-catalog.md), [sync contract](contracts/sync-v1.md), and [runtime/FFI contract](contracts/runtime-ffi.md), [quickstart acceptance procedures](quickstart.md) Q01–Q12, and [owner approval packet](approval.md).

**Accepted outcome:** one normative Rust domain implementation, durable local/offline commands, receipt/feed transactions for every writer, explicit conflict/recovery, current authorization, durable fenced jobs and consent-bound AI on iOS, macOS and the server. PostgreSQL follows the accepted Apple/current-SQLite pilot as a separate stopped-writer cutover. Android, Windows and Linux require separate specifications and approved device/shell/packaging slices; they are architectural consumers, not acceptance gates or invented shells in this map. Sharing, E2EE, offline web, new recurrence/reorder/task-deletion APIs, CRT synchronization and a Rust HTTP-server rewrite remain outside this feature.

**Prerequisites:** actual design/default/ADR/Constitution decisions, ADR-0011/0012 admissible six-lens verdict (five standard lenses plus the high-risk adversarial lens) and explicit human slice-boundary approval precede coding. PR-01 is the contract/approval slice, not a mechanism to approve itself. Before candidate freeze each implementation writer produces and validates the typed pre-freeze receipt with `python3 scripts/validate_pre_freeze_receipt.py <receipt> --sha <full-lowercase-sha>`. Independent review/QA, exact-SHA CI, verified landing, production release/smoke and feature acceptance are later gates under ADR-0008/0023. ASK-class cutovers require their recorded authorization; this plan grants none.

**Paths and budgets:** existing paths were inspected at base `c16daecd13247e35fea280bd9322c8a4b09dabb1`. All `rust/` paths, the new Rust facades, `backend/app/modules/tasks/{jobs,sync}/`, generated wire artifacts and evidence files below are explicitly **proposed additions**. Existing service/reducer modules are integration points, not a request to rewrite whole files in one slice. Each rule slice ports one named rule family; facade slices change bounded dispatch/mapping and make replaced implementations unreachable for migrated epochs. Large obsolete-file deletion is optional later cleanup, not a hidden part of a 400-line budget. Pre-cutover stores remain on their compatible old image until migration; a migrated store has only the new writer/rules. No double mutation or second live authority is permitted. Budgets count added **and deleted** product lines, including manifests/build scripts/generated committed sources; documentation/tests are excluded by the current budget checker (Cargo.lock currently counts as product, so its changed lines are included). Generated bridge output must be a reproducible build artifact, not a way to hide handwritten product changes. Every candidate runs `python3 scripts/check_slice_budget.py specs/026-rust-core-sync/tasks.md PR-NN --base <accepted-base-sha>` after commit. If a measured diff cannot fit, stop and revise the proposed boundaries before implementation proceeds; do not put a stage-sized diff under a small nominal budget.

**Rust/FFI boundary feasibility:** PR-03/04/05 and the PR-34 runtime/SQLite package budgets are unmeasured caps, not size evidence. Before approving these boundaries, prepare a disposable sizing spike with the selected dependency versions, complete lockfile deltas, bridge scaffolding and Linux/Apple packaging inputs. Record each spike commit/base, toolchain versions, `check_slice_budget.py` output and the planned CI-owned paths in verification.md. The spike must not wire a live writer or ship product behavior. If any diff exceeds its cap, revise the map into smaller reviewable boundaries and repeat measurement before owner approval; do not exclude Cargo.lock or generated committed sources. A successful docs-only budget check does not validate these future code sizes. The corrected AI boundary is split into shared adapter (PR-49), iPhone surface (PR-59) and Mac surface (PR-60); their proposed caps also require measurement before boundary approval, including the actual native entry points and shared model wiring. No sizing spike has run in this specification session.

**Testing, Principle II:** first run the sufficient existing checks named in each phase/slice. The parity oracle is existing Swift/Python golden rules, not the Rust output. Behavior-preserving ports need no duplicate test per task or language. Genuinely missing critical coverage is test-first: SQLite commit/crash/full-disk/interprocess locking; receipt/feed atomicity and all-writer authority; lease/fence handoff; ACK/feed/snapshot/generation/epoch recovery; legacy uncertain import; retention/restore of deletion/revocation; and FFI serialization/lifetime/panic/concurrency at the actual boundary. Reuse existing consent/review/archive/session/account tests and extend only gaps. Test filters must execute the named relevant cases (zero selected tests is not evidence). Every pytest/Vitest/Playwright product test retains the repository Allure taxonomy and feature-qualified requirement IDs. Affected checks run while iterating; full applicable suites run on the prepared candidate, not after every task.

**Execution resources:** every approved slice gets its own branch `026/PR-NN`, worktree, DB/data directory, ports, E2E project and artifacts. The JSON declares owned write paths and merged-base dependencies. No worker starts on a speculative sibling branch. The conductor records slice/owner/branch/base/SHA/checks/review; assigned implementer roles describe future execution and do not spawn workers during this specification session.

## Phase 1 — Setup and foundational contract

Freeze shared inputs and prove safe packaging before any writer changes. Independent evidence is the accepted contract, unchanged default-OFF capability, existing oracle and actual Python/Swift/Linux bridge smoke. PR-02 can run alongside the later bridge validation once PR-01 is accepted.

- [ ] T001 Obtain actual owner acceptance of design.md, adr-draft.md, the Constitution IV command-identity exception, retention/defaults, device/load baseline, Apple dependency policy exception, and these boundaries; freeze contracts/command-catalog.md, contracts/runtime-ffi.md and contracts/sync-v1.md, generate contracts/sync-v1.schema.json and contracts/sync-v1.openapi.yaml from the same catalog, and add only the default-OFF rust_core_sync capability in backend/app/core/config.py. Record the ADR-0011 review and analyze verdict in verification.md; no approval is inferred from this checkbox. (PR-01).

- [ ] T002 Reconcile the existing backend/tests/fixtures/review_formulation_vectors.json, review_flow_vectors.json and project_archive_traces.json with BrainBuddyCoreTests resources and current task/Smart Add/date tests; freeze bounded synthetic reference data at contracts/reference-store.json. Freeze contracts/web-presentation-vectors.json with the shared rule version, stable source-linked cases and expected web payload/display outcomes; reuse existing Smart Add/transition examples in the Rust and web parity checks. Document accepted contradiction resolutions, field/ID/outbox inventory, scheduler/writer inventory and lower-bound device/load in verification.md. Reuse vectors rather than cloning every language test. (PR-02).

- [ ] T003 Create the proposed rust/Cargo.toml workspace, bb-domain and bb-protocol manifests and lib.rs entry points; encode typed command identity, scope, generations, dependency/precondition and result envelopes in bb-protocol/src/envelope.rs. Pin the validated toolchain/bridge versions; serialization accepts only catalog forms, rejects unknown execution variants and keeps the stable receipt-recovery envelope. Register modules only when implemented, without empty future crates. (PR-03).

- [ ] T004 Implement the PyO3 codec/lifecycle bridge in rust/bindings/python/src/lib.rs and backend/app/modules/tasks/rust_adapter.py; package it through the existing backend/pyproject.toml. Prove typed conversion/errors and lifecycle using the completed PR-06 primitives; PR-18 connects decide/query after PR-62. Use explicit execution inputs; release the GIL for pure CPU work, catch panics, own buffers, and release cancellation/close resources. Do not switch TaskService or load secrets into domain DTOs. (PR-04).

- [ ] T005 Implement the coarse UniFFI bridge in rust/bindings/swift/src/lib.rs and a Foundation-only BrainBuddyRustBridge.swift facade; add the tested Linux/Apple build wiring in ios/BrainBuddyKit/Package.swift, ios/project.yml and macos/Package.swift. Produce generated sources/XCFramework as reproducible build artifacts rather than committing unrestricted generated output. Prove strict Swift concurrency, error delivery, cancellation and app/widget linking using the completed primitives; PR-17 connects decide/query after PR-62. (PR-05).

- [ ] T061 Freeze the accepted domain state subsets, command/query inputs, ChangeSet and typed errors in rust/crates/bb-domain/src/types.rs, reusing bb-protocol wire types; export them in src/lib.rs and verify source-linked conversions in tests/types.rs. Resolve DTO/codec sizing before boundary approval; do not add empty rule modules or change the catalog. (PR-61).

## Phase 2 — US4: consistent rules and durable background authority (P2 foundation for P1)

Each pure rule family is independently checked against existing examples. The selected epoch switches only after all rules agree. Jobs are established through compatible ports before receipts/feed connect internal writers. All scheduler responsibilities from main.py are inventoried; auth dispatch remains under its existing owner, and CRT keeps its existing storage/receipt contract.

- [ ] T006 [US4] Port only Python-compatible NFKC, whitespace, full casefold, Unicode-scalar limits and CalendarDay/time-zone primitives to bb-domain/src/normalization.rs and calendar.rs; run existing NameNormalizerTests, CalendarDayTests and formulation vectors via tests/primitives_parity.rs and the shared immutable tests/support/mod.rs loader. Register only these completed primitives in src/lib.rs. Make time and identifiers explicit inputs, preserving calendar-day versus instant and DST behavior. (PR-06).

- [ ] T007 [US4] Implement only task-create, edit and complete/cancel/move/reopen rule dispatch in bb-domain/src/task_rules.rs using current Reducer.swift and TaskService validation as the oracle; preserve four open lists, Waiting requirements, expected revisions and priority vocabulary. Keep catalog constraints verbatim: "task title 500, details/comment 20,000, name 500, project outcome 1,000 Unicode scalar values"; omitted/null/value PATCH semantics and decimal-string counters remain distinct. Return typed changes and errors without performing I/O. (PR-07).

- [ ] T008 [US4] Implement create/update Project, create/update/delete Tag, outcome and explicit tag membership operations in bb-domain/src/organize.rs; preserve owner-scoped name uniqueness, references, validation and delete tombstone semantics from Reducer+Organize.swift and TaskService. Do not add new task-deletion or reorder commands. (PR-08).

- [ ] T009 [US4] Port only archive/unarchive cascade and detached-member handling to bb-domain/src/archive.rs from accepted ADR-0020 and project_archive_traces.json. Include complete multi-record changes in the result and preserve completed-task placement and archived project display facts. (PR-09).

- [ ] T010 [US4] Port only subtask create/edit/transition and comment create/edit rules to bb-domain/src/children.rs using Reducer+Children.swift, existing API schemas and child fixtures; preserve parent checks, scalar limits, child revisions and supported ordering. Public projections normalize children without duplicating authority. (PR-10).

- [ ] T011 [US4] Port only current SmartAddParser.swift/SmartAdd+Resolution.swift grammar and classification resolution to bb-domain/src/smart_add.rs, with the current backend Smart Add vectors. Resolve references using the protected read set and return a proposed create command; do not introduce another grammar or provider call. (PR-11).

- [ ] T012 [US4] Implement the existing pure list/order/project-display query decisions in bb-domain/src/queries.rs using Queries+List.swift, Queries+Ordering.swift and Queries+ProjectDisplay.swift. Keep SQL pagination separate, and return capabilities/actions for the current record; preserve due-day and completed-placement behavior. (PR-12).

- [ ] T013 [US4] Port formulation identity, substantive-title rules, due floors, start/close/move/edit clocks and threshold classification/evaluation-view predicates to bb-domain/src/formulation.rs. Preserve the stalled-count scalar after leaving Next, IANA-zone instants and edit-revision distinctions from formulation.py/Formulation.swift; reuse review_formulation_vectors.json. (PR-13).

- [ ] T014 [US4] Port only auto-park, timely offline-decision yield, park acknowledgement and clock restoration/Undo primitives to bb-domain/src/park.rs; use ADR-0027 and existing auto-park/clock-seam tests as the oracle. Keep automatic bookkeeping distinct from a human edit revision. (PR-14).

- [ ] T015 [US4] Port decision application, Keep/release receipts, per-item bulk eligibility/skip rules ("bulk release 500, park acknowledgment 200") and Undo eligibility to bb-domain/src/review_decisions.rs. Preserve history/source links, substantive/stall/AI metadata and existing deferred Undo requiring server-only snapshots; reuse decision/review trace tests. (PR-15).

- [ ] T016 [US4] Port session start/progress/finish, settings validation and Review queue/summary predicates to bb-domain/src/review_sessions.rs using review_flow_vectors.json, ReviewPlanners.swift and Queries+Review.swift. Preserve progress merge, captured-empty queues, active seconds, qualifying activity and revision rules; no generic entity CAS replaces progress merge. (PR-16).

- [ ] T062 [US4] Register the completed rule modules in rust/crates/bb-domain/src/lib.rs and route decide/query through src/dispatch.rs; tests/dispatch.rs exercises the public library against the already frozen family vectors. Only module declarations and dispatch belong here; no new rules, serialization model or facade rewrite. (PR-62).

- [ ] T017 [US4] Adapt GTDReducer dispatch, Smart Add and pure queries at Reducer.swift, SmartAdd.swift and Queries.swift to the bridge for the new rule/storage epoch; introduce the bounded mapping in RustDomainFacade.swift and connect the completed PR-62 dispatch in rust/bindings/swift/src/lib.rs. Retire Swift rule dispatch for that epoch; compare old/new only in tests or read-only shadow evaluation. Existing pre-cutover files continue on their compatible image until migrated; no mutation invokes both reducers. (PR-17).

- [ ] T018 [US4] Connect TaskService task/lifecycle/organization/children/Smart Add validation through rust_adapter.py and a bounded RustTaskFacade in rust_task_facade.py, connecting the completed PR-62 dispatch in rust/bindings/python/src/lib.rs; keep owner authorization, protected read-set loading, existing DTO responses and repository I/O in Python. Remove these Python decisions from migrated-epoch dispatch; do not rewrite or delete the entire service.py in this slice. (PR-18).

- [ ] T019 [US4] Connect ReviewService, ReviewFlowService and their domain-decision calls through rust_review_facade.py; retain private snapshots, permissions, provider reservations and storage in Python. Route all migrated-epoch formulation/park/decision/session decisions to Rust, preserve legacy matching-record replay and deferred Undo ports, and make old rule calls unreachable in that dispatch. (PR-19).

- [ ] T020 [US4] Add jobs/repository.py and jobs/domain.py to the current Tasks SQLite transaction adapter: job identity/dedup key, payload reference, run_at, status, attempts, lease owner/until, fencing generation and safe errors. Implement atomic claim/heartbeat/retry/cancel transitions with bounded retries. First add missing failing lease/crash tests in test_task_jobs.py; do not change the running schedulers yet. (PR-20).

- [ ] T021 [US4] Add jobs/execution.py and a typed execution context at the existing serialized_write/Review application ports, wired through container.py. Acquire and recheck the current job fence and current scope authority under the task writer lock, derive internal effect identity once, and reject caller-supplied writer_origin. This is an existing-port prerequisite and does not depend on sync endpoints. (PR-21).

- [ ] T022 [US4] Add jobs/review_adapter.py for the Review maintenance/auto-park responsibility through the existing compatible ports. Persist schedule identity and use the lease/fence in adapter tests; PR-64 registers it and hands over the main.py scheduler responsibility. Retention stays independent of owner activity and weekly_review flags. (PR-22).

- [ ] T023 [US4] Add jobs/voice_adapter.py and jobs/privacy_adapter.py to invoke existing voice recovery/retention, account purge, relay/CRT receipt retention ports; prepare durable schedule identities for their named responsibilities; PR-64 performs the main.py ownership handoff. Cross-module effects retain their existing recovery contract and are not falsely made one Tasks ACID transaction. Preserve unrelated auth-delivery ownership. (PR-23).

- [ ] T024 [US4] Add jobs/agent_adapter.py to schedule the existing AgentObserver observation/recovery responsibility durably; adapt the observation port in observer.py without changing the A2A lookup/retry state machine; PR-64 registers it and hands off its main.py scheduler responsibility. Attach lease/fence to any Task application port; external timeout uses lookup/reconciliation and remains uncertain when proof is absent. (PR-24).

- [ ] T064 [US4] Add the durable runner in backend/app/modules/tasks/jobs/worker.py using the PR-20 ledger and PR-21 execution context, register completed PR-22/23/24 adapters, and replace only their named main.py scheduling ownership at the verified handoff. backend/tests/test_scheduler_handoff.py proves one live owner across restart/lease expiry; preserve auth scheduling and the existing module transaction boundaries. Measure worker-loop plus scheduler-removal size before boundary approval. (PR-64).

- [ ] T053 [US4] Use the explicitly versioned-vector transition in plan §7 and command-catalog.md: retain synchronous Smart Add syntax/suggestion helpers in frontend/src/features/tasks/smartAdd.ts and their actual TaskListPage.tsx composer, plus state-to-affordance display in TaskDetailPanel.tsx. Verify them against PR-02's source-linked rule-version vectors; Rust-backed server mutations remain the final authority and taskHooks.ts consumes existing HTTP success/error DTOs. Preserve capture retry/drafts and HTTP rejection behavior. No server preview/per-task-capability producer or deletion of all web presentation logic is claimed; no offline web, WASM or CRT change. (PR-53).

## Phase 3 — US1: offline capture and convergent atomic synchronization (P1)

Independent user test: capture/edit offline on iPhone, terminate/reopen, reconnect and observe the Mac/server once. Server boundary slices are independently integration-testable while capability is dark; client slices have deterministic SQLite/fault harness checks. The cross-story recovery tasks interleaved below are prerequisites of that complete journey.

- [ ] T025 [US1] Add sync/unit_of_work.py and thread the same connection through finite repository write entry points in repository.py and review_repository.py. Load/protect complete read sets under the owner lock and commit Tasks/native Review with generated job intents once. Do not create a parallel DB or wrap independently committed writes in a pretend outer transaction. (PR-25).

- [ ] T026 [US1] Add sync/receipts.py and sync/change_log.py: owner-scoped immutable command digest/identity, terminal outcomes, per-scope commit sequence and complete transaction records in the same unit of work. Lookup precedes current execution schema/size checks for known retries; same ID/different envelope conflicts and retained recovery survives version retirement. (PR-26).

- [ ] T027 [US1] Add sync/command_handler.py and sync/legacy_adapter.py and route TaskService through them in container.py. Map the existing owner/idempotency-key to one receipt independently of command/transport; command/body remain conflict checks. Preserve legacy status/DTO/preconditions and deterministic new-entity identity aliases; web/CLI/MCP remain HTTP consumers. (PR-27).

- [ ] T028 [US1] Add sync/review_projection.py and route ReviewService/ReviewFlowService plus Navigator consent-grant/owner-wide-revoke through the command boundary while preserving matching-record recovery after 24 hours. Preserve the accepted legacy consent-revoke key-collision exception before generic mismatch rejection: original receipt retained, stable dedicated revoke identity, one atomic receipt/feed effect, and no repeat revocation of a newer grant. Emit all public settings/session/queue/decision/receipt/ack/bulk/consent upserts and tombstones with stable keys/versions; derive review-state/counts/advisory queries from that consistent base and explicit time; exclude private snapshots, applied_progress fingerprints and usage reservations. (PR-28).

- [ ] T029 [US1] Connect existing voice_brain_dump/task_port.py, operator/seed/sweep paths in backend/app/cli.py, agent Task ports in container.py and jobs/execution.py to the shared handler. Recheck current caller/job authority and fences at commit; retain the original Capture create_native_inbox_task until-purge exception. Inventory every route, REST/CLI/MCP/workflow/auto-park/job writer in contracts/command-catalog.md and fail a boundary audit for bypasses. (PR-29).

- [ ] T031 [US1] Add sync/router.py for device registration, command submit/result lookup and capabilities; wire it in main.py and serialize through sync/wire.py. Enforce scope capability, protocol/schema/command versions, current permissions and indistinguishable foreign/unknown-resource 404 responses, the approved request/record limits and actionable correlation IDs. Known-receipt recovery is tested before tighter execution validation. (PR-31).

- [ ] T032 [US1] Add sync/delta.py and its route in delta_router.py; encode opaque owner/access/feed-generation cursors, next_cursor/has_more and complete typed public after-images/tombstones. For a transaction exceeding the 4 MiB inline hard limit, materialize the immutable canonical Change-array stream and expose its manifest plus bounded decoded-byte chunks (≤1 MiB) through sync/transfers.py and the transaction transfer route. Chunks may cross record boundaries and never split a domain commit. Enforce only the new ingress 4 MiB limit, preserve legacy limits, impose no 500-changed-row ceiling and return RESET_REQUIRED on expiry/generation/deletion. Hints only wake pulls; PR-58 owns their server endpoint/publisher. Own delta_router.py and test its real APIRouter with the production authority/container dependencies; PR-63 mounts it in the application. (PR-32).

- [ ] T063 [US1] Mount delta_router.py, snapshot_router.py and hints_router.py in backend/app/modules/tasks/sync/router.py; verify production app route reachability, shared authorization and capability-OFF behavior in backend/tests/test_sync_routes.py. Keep endpoint logic and its detailed tests in the owning PRs. (PR-63).

- [ ] T034 [US1] Create bb-client manifest/lib.rs, update and own rust/Cargo.lock (including the new workspace package and SQLite dependencies), and add storage.rs with confirmed_records, outbox, receipts, issues, drafts, sync_meta and identity_aliases. Add WAL/write-lock and exclusive migration-lock handling in locking.rs, bounded busy timeout and protected workspace identity. First add real-process SQLite crash/full-disk/lock tests; a process-local actor alone is insufficient. (PR-34).

- [ ] T035 [US1] Implement execute.rs: accept the caller-stable gesture command ID, lock/reread affected records, allocate entity/dependency IDs, decide through bb-domain and save intent plus visible projection in one transaction. Local-only work requires no registered account; fresh epoch intake is durable with its first command. Dependencies refer to immutable identities, not guessed title/time matches. (PR-35).

- [ ] T037 [US1] Implement apply_changes.rs and receipts.rs to stage/verify byte chunks (indices/counts/bytes/digests) with a streaming decoder, then atomically apply full feed transactions, source-command receipt matching, remaining replay and cursor. ACK only marks accepted_awaiting_feed and retains intent/projection; no ACK after-image writes the confirmed base or jumps the cursor. No-op/rejected receipts complete under the frozen contract. (PR-37).

- [ ] T058 [US1] Add sync/hints.py and its authenticated route in sync/hints_router.py. Observe the shared committed scope counter at most 250 ms apart for connected scopes; publish bounded/coalesced content-free SSE events after commits from any process/writer. Enforce current authority, indistinguishable owner-safe 404, generation closure, heartbeat, reconnect and disabled buffering per sync-v1 §11. Prove the actual stream across separate writer/stream processes; no process-local-only hook or new broker. Own hints_router.py and test its real APIRouter with the production authority/container dependencies; PR-63 mounts it in the application. (PR-58).

- [ ] T040 [US1] Implement transport.rs and subscriptions.rs using the frozen ports: bounded send/retry/dependency scheduling, foreground/network-return pulls, the PR-58 authenticated SSE hints with immediate reconnect catch-up and fallback poll starts at most 30 seconds apart, including jitter, leaving up to 30 seconds for requests/catch-up/application within SC-004's 60-second commit-to-visible deadline. Query invalidations coalesce; credentials stay in the OS adapter, close/cancel releases subscriptions, and background application avoids main-thread I/O. (PR-40).

- [ ] T043 [US1] Connect Workspace.swift/Workspace+Review.swift and BrainBuddySync.swift to RustWorkspaceAdapter.swift and the coarse runtime bridge execute/query/subscribe ports. Select one store/engine for the activated epoch, preserve account-less local authority and existing GTDCommand-facing UI APIs; old engine cannot write that DB. Keep cancellation and structured safe errors visible. (PR-43).

## Phase 4 — US2: explicit conflicts without losing text (P1)

Independent test: edit both titles offline, reconnect in both orders, retain both versions and choose against the shown revision; delete-versus-edit cannot resurrect data and another task continues syncing. Pure replay is checked cheaply; rendered conflict/recovery actions require Apple device evidence.

- [ ] T036 [US2] Implement replay.rs and issues.rs for visible = confirmed + replay(allowed pending), revision/entity-deleted failures and blocked_dependency. Save local text/current shown record and explicit dismissal/replacement choice; Keep my version creates a new command against the shown version, never force writes. A dependent issue blocks only its chain. Persist M-02/D-02.11–12 preserve/reapprove/discard choices and decision drafts; never rekey unknown outcomes. (PR-36).

- [ ] T045 [US2] Implement accepted M-01/M-02/M-03 states in SyncStatusLabel.swift, SyncIssuesScreen.swift and SettingsScreen.swift using typed runtime issues. Show locally saved/pending/synced/auth/update/recovery distinctions, both conflict versions and explicit safe actions, blocked dependants and preserved draft/unknown-outcome recovery. Use safe IDs, current shown version and existing accessibility tokens. (PR-45).

- [ ] T046 [US2] Implement accepted D-01/D-02/D-03 states through SyncStatusPopover.swift, SyncPopoverModel.swift and SyncStatusLineModel.swift; add a bounded conflict-detail view. Use the same typed issues and shown revision, preserve existing status thresholds, keyboard/focus/accessibility and independent-queue progress; retain actionable safe reference IDs. (PR-46).

## Phase 5 — US3: upgrades, resets, account expiry and safe restoration (P1)

Independent test: update/import a populated store and uncertain queue, interrupt/expire a snapshot, restore with a revoked/deleted account and switch sessions. Data survives or activation stops before switching. New failure coverage protects actual transaction/generation/retention boundaries rather than duplicate happy-path tests.

- [ ] T030 [US3] Add sync/authority.py and sync/devices.py to bind owner/device/server generation and register immutable pending-registration epoch IDs idempotently. Recheck current Identity access for reads/writes/receipt replay; closed epochs reject unseen commands but preserve authorized retained lookup. Feed/access generation never comes from caller authority claims. (PR-30).

- [ ] T033 [US3] Add sync/snapshots.py and snapshot routes to materialize one consistent owner-scoped snapshot/watermark, page it immutably using the same canonical-byte chunk manifests/digests as transaction transfers and expire it at the approved TTL. Recheck authorization for each page; preserve public Review links/queues and normalize child projections. Concurrent writes, delete/retention invalidation and expired continuation never produce a silently partial base. Own snapshot_router.py and test its real APIRouter with the production authority/container dependencies; PR-63 mounts it in the application. (PR-33).

- [ ] T038 [US3] Implement snapshot.rs with staging completeness/checksum and one atomic activation under the cross-process lock. Incorporate the latest live queue/issues/drafts/intake epoch instead of an earlier copied queue; resolve accepted commands only with same-generation watermark proof and lookup every unknown outcome. Expiry/interruption restarts preserve active DB. (PR-38).

- [ ] T039 [US3] Implement sync_session.rs and epochs.rs: capture workspace/session/local-sync/server generations, invalidate/cancel on reset and ignore stale completions. Preserve immutable old envelopes and a pending-registration epoch for independent new work; register that same ID only under current authority and activate recovery base before sends. Unsupported versions retain store/queue. (PR-39).

- [ ] T041 [US3] Implement import.rs and BrainBuddyPersistence/RustStoreImporter.swift to back up the source file/schema manifest, import every field/ID/relation/Review/local-only datum into staging and validate before atomically switching the marker under migration lock. Reuse legacy-import-golden and Mac awkward/corrupt/newer fixtures; preserve drafts and identity aliases without heuristic merging. (PR-41).

- [ ] T042 [US3] Implement legacy_outbox.rs and RustOutboxImporter.swift to retain everSent, issuedAt, attempts, idempotency key/body, aliases and old Review marks. Lookup available legacy receipts; resolve only provable matches. Beyond the prior 24-hour window, keep uncertain submissions as issues rather than reissuing or using title/time similarity; exports include preserved unresolved intent. (PR-42).

- [ ] T044 [US3] Connect Workspace account-generation/merge flows, SharedWorkspace.swift and Mac WorkspaceHost.swift/MacSyncController.swift to the selected runtime, retaining explicit first-sign-in merge and sign-out local-copy warning. Derive paths from the current App Group/workspace identity; widget/intents execute through the same DB lock and never own sync. Current revocation hides account cache under existing policy. (PR-44).

- [ ] T050 [US3] Add sync/retention.py and extend receipts/change_log/snapshots adapters to enforce absolute source expiry on reads and independent scheduled cleanup. Redact ordinary response content at 24 hours, preserve minimal dedup and typed content-free Smart Add id_bindings until purge, seven-day Review content expiry and Capture/CRT scoped exceptions; emit canonical retention change or require reset, invalidate affected immutable snapshots, and never expose deleted payload copies. (PR-50).

- [ ] T051 [US3] Extend account_service.py and a local export.rs adapter to export new visible/local records, pending intents/issues and required identity aliases safely, and purge scope feed/snapshots/receipts/jobs/AI proposals with existing deletion authority. Document minimal protected dedup/control-ledger categories and backup retention in recovery.md; logs use IDs/timings/error stages only. (PR-51).

- [ ] T052 [US3] Add sync/control_ledger.py and sync/restore.py to preserve minimal deletion/purge and session/credential revocation decisions outside rollback-prone task backups, retained only while affected restore points remain recoverable (proposed backup/WAL horizon ≤7 days); purge completion retires those points and erases owner-linked markers. Restore with access closed, replay all later controls, revoke uncertain sessions, advance server/feed generation and close unsafe epochs; fail closed if completeness is unprovable. Reconcile external effects separately and verify proposed RPO≤24 hours/RTO≤4 hours on the reference workload. (PR-52).

## Phase 6 — US5: AI policy and confirmation boundary (P2)

Independent test: suitable/unavailable local executor, on-device-only denial, authorized specific recipient, revocation, invalid proposal and cancellation. Existing consent/operation tests are reused; only policy/adapter gaps add coverage. AgentRun success remains separate from Task completion.

- [ ] T047 [US5] Implement ai_policy.rs and proposal.rs in bb-domain: deterministic-first/suitable-local preference, language/capability/memory availability, recipient-specific current consent, budget/timeout/cancel and typed structural proposal validation against allowed catalog commands. This pure policy slice consumes frozen types, not the unfinished rule dispatcher; current-state validation still occurs at the confirmed ordinary execute boundary. A model response grants no capability and never applies a Task command before confirmation. (PR-47).

- [ ] T048 [US5] Connect shared policy/proposal validation through navigator.py and voice_brain_dump/confirmation.py/task_port.py, preserving ADR-0002 operation workspace/confirmation, current provider credentials and cancellation checks. AgentRun result stays evidence/proposal; ordinary Task mutation uses the fenced shared command handler. (PR-48).

- [ ] T049 [US5] Add Foundation-only LocalAIAdapter.swift and ReviewSuggestionModel.swift plus Workspace+ReviewAI.swift to connect shared capability policy with the first Weekly Review suggestion request/consent/proposal/apply path. Use the existing navigator endpoint/approved payload, current per-recipient consent and shown-version ordinary command path. Own request/cancellation/interruption state M-04/D-04.13–15 and the accepted clarifying-question/answer-save/rerun branch .16–20 with stable notes-command identity and phase recovery; unavailable/insufficient-memory/error in on-device-only mode returns manual continuation with no remote request. Native navigator clients were deferred in spec 020; these are additions, not existing voice UI. Do not promise a new model engine or language. (PR-49).

- [ ] T059 [US5] Add iPhone ReviewSuggestionSheet.swift and its entry from existing Review/DecisionCardSheet.swift. Render M-04 using PR-49's shared model: exact recipient/data consent, bounded proposal preview/edit, explicit apply against shown revision, no-result/manual continuation, .13–15 cancellation/interruption and .16–20 clarifying-question/answer-save/rerun states. Reuse existing review eligibility, forms and accessibility; no new Review workspace. (PR-59).

- [ ] T060 [US5] Add Mac ReviewSuggestionSheet.swift and a bounded entry from the existing task detail in ContentView.swift, with BrainBuddyModel.swift exposing the shared PR-49 model. Render D-04 for the same Weekly Review suggestion capability and eligibility/payload/confirmation policy; include current consent, stale proposal, cancellation/interruption, .16–20 clarifying-question/answer-save/rerun states and keyboard/VoiceOver behavior. VoiceCapture.swift remains transcription, not a substitute for this new suggestion surface. (PR-60).

## Phase 7 — Cross-story Apple pilot and acceptance

Run actual lower-bound iPhone and Mac scenarios plus the current SQLite server after every writer/worker/restore/privacy prerequisite. This is the first rollout acceptance gate. Capture exact deployed SHA, flag audience/OFF/recovery, metrics and independent acceptance; no product evidence is claimed by this documentation change.

- [ ] T054 Extend the existing replay harness at bb-client/tests/protocol_faults.rs with the genuinely new protocol crash/loss/reorder/reset/restore cases from sync-v1.md §10, reusing current convergence/archive/Review traces. Execute quickstart.md Q01–Q12 and record reference-store import, iPhone 11/iOS 26 plus MacBook Air M1/8 GB/macOS 26 timings (≥1,000 operations across five runs per device, p95≤50 ms and no main-thread stall≥100 ms), 100 two-client batches (RTT≤100 ms, p95≤2 s; lost-hint commit-to-visible≤60 s with poll starts≤30 s apart including jitter and a commit immediately after a completed poll), UX/AI/worker evidence and exact-SHA OFF/pilot/recovery results in evidence/apple-pilot.md and verification.md. Pilot only after every writer/fence/retention/restore gate is green; no PostgreSQL cutover here. (PR-54).

## Phase 8 — Separate post-pilot PostgreSQL migration

This stage is ordered after the accepted Apple/current-SQLite pilot. Rehearse before obtaining migration authorization; stop task writers and switch the aggregate, receipts, feed and jobs together. Identity/CRT retain their ownership, and OFF never revives an incompatible writer.

- [ ] T055 After the Apple/SQLite pilot, implement only postgres.py as a target implementation of the already-tested Tasks/receipt/feed/job unit-of-work ports. Preserve owner locks, commit order, read-set protection, lease/fences and generations; validate the same transaction fixtures against an isolated PostgreSQL instance. Do not activate it or migrate Identity/CRT. (PR-55).

- [ ] T056 Add migrate_postgres.py for a stopped-writer aggregate+receipts+feed+jobs+generations export/import and verification, with manifest/checksums/counts/relationships and no silent uncertain-outcome repair. Run a reference rehearsal, reconcile the control ledger/external effects and record the rollback-compatible image/storage epoch plus verified RPO/RTO in recovery.md. Never permit simultaneous task DB writers. (PR-56).

- [ ] T057 Prepare the exact-SHA PostgreSQL switch through container.py and postgres_cutover.py, recheck capability/storage epoch and refuse incompatible old binaries. Obtain the required ASK migration authorization only for the fully rehearsed candidate, stop task writers, switch once, reopen after ledger reconciliation and verify backup/export/purge/smoke. Record recovery and independent acceptance in evidence/postgres-cutover.md; flag OFF stops exposure rather than restoring the old writer. (PR-57).

## Dependencies, increments and parallel execution

The JSON map is topologically ordered. Checklist phases group tasks by story and therefore intentionally show some stable task IDs out of numeric order (for example T053 in Phase 2). IDs identify slices; the JSON `depends_on` edges determine execution order. A phase heading is not permission to skip cross-story dependencies. PR-20/21 establish durable scheduler authority and fencing through existing ports; PR-22/23/24 prepare independent adapters and PR-64 hands over their scheduling ownership; PR-25…29 then establish one aggregate/receipt/feed transaction for **all** writers. Only after those gates do PR-30/31 expose sync command boundaries; PR-32/33 and PR-58 implement the remaining endpoints, mounted together by PR-63. PR-34…44 deliver the Apple runtime/import/workspace. Conflict/recovery UI, AI adapter and Apple suggestion sheets (PR-49/59/60), retention/restore and server-authoritative web gates all join at PR-54, the current-SQLite Apple pilot. PR-55…57 are the subsequent PostgreSQL stage.

The complete [dependency graph](delivery-graph.md) renders every slice and every JSON edge; it is a view of this map, not a second scheduling authority. The conductor starts **every ready independent slice** up to the available worker limit, and fills a freed slot as soon as its merged prerequisites are ready; there is no whole-phase or whole-wave barrier. A ready slice has all `depends_on` slices accepted and merged, an approved/measured boundary where required, disjoint owned paths, and its own resources. Development can run in parallel; repository landing remains serialized.

Rust rule PRs own their production source and separate `tests/<family>_parity.rs` runners. PR-61 first exports frozen types; PR-06 exports completed normalization/calendar primitives and the shared test loader. Each family runner compiles the **actual** source with ordinary Rust `#[path = "../src/<family>.rs"] mod <family>;`, re-exports `bb_domain::{types, normalization, calendar}` at its test-crate root, and includes already-merged dependency modules under their production names. Rule source uses those same `crate::` paths before and after PR-62 registration. There are no copied rules, missing-module declarations, code generators, pretend successful stubs or speculative sibling builds. PR-62 owns only final module registration/dispatch and proves the public library reaches every family. Existing oracles are reused; each runner owns only missing family cases and harness glue. Every relevant runner must execute nonzero cases.

After PR-06, organization (08), children (10), formulation (13), AI policy (47) and Python bridge (04) can start together. Task lifecycle (07) really depends on formulation (13); Smart Add (11) needs task creation (07) and organization (08); decisions (15) need task/children/park (07/10/14). Queue/session queries consume clock facts and do not wait for unrelated decision mutations. After domain registration and bridge validation, the Apple facade (17), Python facade (18) and client storage (34) are independent. Client-local PR-34…39 runs alongside server job/receipt/API work. After PR-21, job adapters (22/23/24) run together before the bounded scheduler join (64). Web presentation parity (53) needs the completed Task facade (18), not unrelated sync endpoints or AI wiring; full real-server acceptance remains at PR-54. SSE (58) runs alongside delta (32); snapshot (33) retains the real transfer-encoding dependency on 32. PR-63 mounts the completed routers before transport (40). iPhone/Mac recovery (45/46), shared AI (49) and restore (52) can overlap once their own bases are ready; iPhone/Mac AI surfaces (59/60) then run together.

Shared package manifests, lockfiles, `container.py`, services, schedulers and the client transaction/replay sequence retain their required ordering. Workers never edit shared files outside their paths or invent a dependency just to hide an unresolved write collision. A newly discovered shared edit or true prerequisite stops that part, amends the map, and passes the existing dependency/path validator before resuming.

The first independently useful MVP is the complete US1 journey plus its indispensable rule/job/authority/import/recovery/conflict safeguards, accepted through PR-54 on Apple/current SQLite. Pure-library and dark-boundary slices can merge earlier because they have their own oracle/integration evidence; they do not declare US1 complete. US4 rule and job foundations necessarily precede P1 synchronization, US2/US3 complete safe recovery, and US5 closes the accepted AI boundary before full-feature pilot acceptance. New platforms are follow-on specifications, not unchecked product work hidden in this plan.

Every FR-001…026 and SC-001…008 is assigned explicitly in the JSON. PR-54 is the end-to-end acceptance join, not a substitute for each preceding named guarantee. Proposed measurement defaults, target hardware and retention are frozen only with real PR-01 acceptance. The after_tasks `speckit.accept` extension hook is optional and applies after delivery; this specification session records it without inventing an implementation verdict.

## Atomic PR and full-diff limits

> **Owner decision, 2026-10-09 (implementation session):** the owner directed implementation to "focus on the migration, do not drown in processes". The per-slice product caps, the 800-line full-diff cap and the per-slice path lists below are **advisory for feature 026 from this date**, not merge gates. Implementation lands as reviewable, independently tested PRs that follow the dependency order of this map; each PR states the task IDs it covers. All other gates (CI, tests, Allure taxonomy, requirement coverage, ASK-class landing approval) are unchanged. See [approval.md](approval.md#owner-delivery-decision--october-9-implementation).

> **Owner decision, 2026-10-10 (implementation session):** to run more slices in parallel, the owner relaxed two ordering edges that were release order rather than code dependencies.
>
> - **PR-41** depends on PR-39, not PR-40. Legacy JSON import into a staging store needs the merged client store, replay, snapshot and session fencing, but not transport. PR-42 uses a lookup port with test fakes until PR-40 lands. This opens the client/Apple lane (PR-41 → PR-42 → PR-43 → PR-44) alongside the server chain.
> - **PR-55** may start once PR-25 merges, not after PR-54. The PostgreSQL adapter is written and tested against the unit of work that PR-25 freezes. It still **lands only after the PR-54 pilot passes**, so its `depends_on` keeps PR-54 as the landing gate and adds PR-25. This is the one slice the conductor launches before every `depends_on` entry has merged: its worker starts when PR-25 merges, and its PR does not merge until PR-54 has. Activation, migration and cutover (PR-56, PR-57) keep their order.
>
> Slices that write the same files stay ordered, which takes three new edges:
>
> - PR-40 now depends on PR-41 and PR-42. Those two entries move ahead of PR-40 in the map, and they share `bb-client/src/lib.rs`.
> - PR-51 now depends on PR-40.
> - PR-55 now depends on PR-25 as well as PR-54.
>
> The graph has 98 edges, up from 94. All other edges, gates and merge order are unchanged.

Each `T###` belongs to exactly one `PR-NN`; each PR delivers one named, independently checkable outcome and its necessary evidence. Contract foundations and dark modules may merge before exposure. Do not bundle another slice, unrelated cleanup, a broad rewrite or later platform work to fill a budget. The listed product caps remain at most 390 changed lines (repository ceiling 400); tests/docs exemptions in the repository checker do **not** exempt them from this feature's **800 total added + deleted text-line cap**. Count lockfiles and committed generated output; never split an unbuildable half of a lockfile. Binary/generated build artifacts are published by CI, not used to hide a large source diff.

Before assigning a worker, check its concrete outcome, owned files, expected code **and test/documentation** size and sufficient existing checks. The Rust/FFI/runtime/AI measurements above also cover PR-61 typed values, PR-62 dispatch and PR-64 worker/handoff. Measure the committed candidate against its accepted merged base before review. Both checks below must pass; `review_budget` records the feature-specific second cap, which the existing repository product checker does not enforce. No `oversize_reason` waiver is permitted for feature 026. If either cap fails, stop, split into smaller independently testable outcomes, update task coverage/dependencies/paths/budgets, and repeat boundary review before continuing. A cap is not evidence that an unimplemented slice will fit.

```bash
set -euo pipefail
# Set SLICE_BASE to the recorded accepted merged SHA and SLICE_ID to this PR-NN.
python3 scripts/check_slice_budget.py specs/026-rust-core-sync/tasks.md "$SLICE_ID" --base "$SLICE_BASE"
python3 - "$SLICE_BASE" <<'PY_SIZE'
import subprocess, sys
rows = subprocess.check_output(
    ["git", "diff", "--numstat", "--no-renames", f"{sys.argv[1]}...HEAD"], text=True
).splitlines()
counts = [row.split("\t", 2)[:2] for row in rows]
if any("-" in pair for pair in counts):
    sys.exit("Binary additions need a separate artifact plan, not a line-count exemption")
changed = sum(int(n) for pair in counts for n in pair)
print(f"Full review diff: {changed}/800 added + deleted lines")
sys.exit(0 if changed <= 800 else "Full diff exceeded: re-slice before review")
PY_SIZE
```

## PR-срезы

The Russian heading is the required repository parser key; the map and prose are English. **Amended proposal; empirical boundary approval remains conditional.** The owner requested this delivery refinement; [approval.md](approval.md) distinguishes it from the historically approved technical baseline. This map is not implementation permission.

```json
{
  "schema_version": "brainbuddy-pr-slices/v2",
  "status": "proposed",
  "approval": "Technical baseline accepted; delivery amendment requested 2026-10-09; empirical boundary approval remains conditional (approval.md).",
  "slices": [
    {
      "id": "PR-01",
      "outcome": "Accepted contract and dark rollout boundary precede coding",
      "tasks": [
        "T001"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-011",
        "026-FR-012",
        "026-FR-022",
        "026-FR-023",
        "026-SC-001",
        "026-SC-003",
        "026-SC-004"
      ],
      "paths": [
        "specs/026-rust-core-sync/design.md",
        "specs/026-rust-core-sync/adr-draft.md",
        "specs/026-rust-core-sync/contracts/command-catalog.md",
        "specs/026-rust-core-sync/contracts/runtime-ffi.md",
        "specs/026-rust-core-sync/contracts/sync-v1.md",
        "specs/026-rust-core-sync/contracts/sync-v1.schema.json",
        "specs/026-rust-core-sync/contracts/sync-v1.openapi.yaml",
        "specs/026-rust-core-sync/verification.md",
        "docs/decisions/0031-shared-rust-core-and-task-sync.md",
        ".specify/memory/constitution.md",
        "ios/AGENTS.md",
        "backend/app/core/config.py"
      ],
      "depends_on": [],
      "tests": [
        "python3 scripts/check_spec_kit_specs.py",
        "make validate-ci"
      ],
      "acceptance": [
        "Recorded human decisions, admitted six-lens review (five standard lenses plus the high-risk adversarial lens), complete command catalog and validation artifacts agree; capability is OFF. ADR number 0031 is proposed and must be re-reserved if occupied before implementation."
      ],
      "budget": {
        "product_loc": 80,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-02",
      "outcome": "Existing normative examples are the parity oracle",
      "tasks": [
        "T002"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-013",
        "026-FR-016",
        "026-FR-017",
        "026-FR-026",
        "026-SC-001",
        "026-SC-003",
        "026-SC-005"
      ],
      "paths": [
        "specs/026-rust-core-sync/contracts/reference-store.json",
        "specs/026-rust-core-sync/contracts/web-presentation-vectors.json",
        "specs/026-rust-core-sync/verification.md"
      ],
      "depends_on": [
        "PR-01"
      ],
      "tests": [
        "cd backend && pytest tests/test_review_formulation_vectors.py tests/test_review_flow_vectors.py tests/test_project_archive_traces.py tests/test_task_smart_add_api.py",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests",
        "cd frontend && npm run test -- src/features/tasks/__tests__/smartAdd.test.ts"
      ],
      "acceptance": [
        "The source of each oracle and all missing migration fields are explicit; differences are decisions, never changed expected outputs to suit Rust. The retained web adapter cases have stable IDs, the shared rule version and source/expected-output provenance; they do not invent an HTTP preview capability."
      ],
      "budget": {
        "product_loc": 1,
        "files": 1
      },
      "implementer": "mechanical-implementer"
    },
    {
      "id": "PR-03",
      "outcome": "Versioned codecs compile without any writer change",
      "tasks": [
        "T003"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-011",
        "026-FR-012",
        "026-SC-002"
      ],
      "paths": [
        "rust/Cargo.toml",
        "rust/Cargo.lock",
        "rust/crates/bb-domain/Cargo.toml",
        "rust/crates/bb-domain/src/lib.rs",
        "rust/crates/bb-protocol/Cargo.toml",
        "rust/crates/bb-protocol/src/lib.rs",
        "rust/crates/bb-protocol/src/envelope.rs",
        "rust/crates/bb-protocol/tests/envelope.rs"
      ],
      "depends_on": [
        "PR-01"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-protocol envelope"
      ],
      "acceptance": [
        "Catalog golden envelopes round-trip; command identity is distinct from correlation ID; unsupported execution retains a readable recovery envelope.",
        "Boundary approval requires the recorded sizing-spike commit/base and measured product-line/file budget, including Cargo.lock and complete packaging inputs; re-slice before approval if the cap is exceeded."
      ],
      "budget": {
        "product_loc": 350,
        "files": 7
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-61",
      "outcome": "Frozen domain values compile before independent rule ports",
      "tasks": [
        "T061"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-011",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/lib.rs",
        "rust/crates/bb-domain/src/types.rs",
        "rust/crates/bb-domain/tests/types.rs"
      ],
      "depends_on": [
        "PR-03"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test types"
      ],
      "acceptance": [
        "Typed state subsets, commands, execution inputs, changes and errors use the accepted catalog/data model and existing protocol types. Golden conversion cases preserve omitted/null/value, scalar limits and decimal counters; no placeholder rule implementation or new wire contract. Complete DTO/codec sizing must fit before this boundary is approved. Preserve complete Task/Review and required private execution inputs; if these do not fit, split real contract families rather than dropping fields or substituting untyped JSON."
      ],
      "budget": {
        "product_loc": 350,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-06",
      "outcome": "Unicode and calendar rules agree across languages",
      "tasks": [
        "T006"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-017",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/lib.rs",
        "rust/crates/bb-domain/src/normalization.rs",
        "rust/crates/bb-domain/src/calendar.rs",
        "rust/crates/bb-domain/tests/support/mod.rs",
        "rust/crates/bb-domain/tests/primitives_parity.rs"
      ],
      "depends_on": [
        "PR-02",
        "PR-61"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test primitives_parity",
        "sh ios/scripts/swift-linux.sh test --filter NameNormalizerTests",
        "sh ios/scripts/swift-linux.sh test --filter CalendarDayTests"
      ],
      "acceptance": [
        "Existing Unicode/DST examples agree; no recurrence feature or naive byte-length/lowercase replacement appears."
      ],
      "budget": {
        "product_loc": 350,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-04",
      "outcome": "Python bridge has a bounded safe lifecycle",
      "tasks": [
        "T004"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-011",
        "026-SC-001"
      ],
      "paths": [
        "rust/bindings/python/Cargo.toml",
        "rust/bindings/python/src/lib.rs",
        "rust/Cargo.toml",
        "rust/Cargo.lock",
        "backend/pyproject.toml",
        "backend/app/modules/tasks/rust_adapter.py",
        "backend/tests/test_rust_bridge.py"
      ],
      "depends_on": [
        "PR-06"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-python bridge",
        "cd backend && pytest tests/test_rust_bridge.py"
      ],
      "acceptance": [
        "New boundary tests cover serialization, error/panic containment and repeated open/close; existing behavior remains the active writer until cutover.",
        "Boundary approval requires the recorded sizing-spike commit/base and measured product-line/file budget, including Cargo.lock and complete packaging inputs; re-slice before approval if the cap is exceeded.",
        "Only completed codecs/primitives cross this early bridge. No placeholder decide/query export: actual domain dispatch and its FFI checks belong to PR-17/18 after PR-62."
      ],
      "budget": {
        "product_loc": 330,
        "files": 6
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-05",
      "outcome": "Apple bridge preserves Linux package and app/widget linking",
      "tasks": [
        "T005"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-025",
        "026-FR-026",
        "026-SC-001"
      ],
      "paths": [
        "rust/bindings/swift/Cargo.toml",
        "rust/bindings/swift/src/lib.rs",
        "rust/Cargo.toml",
        "rust/Cargo.lock",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/BrainBuddyRustBridge.swift",
        "ios/BrainBuddyKit/Package.swift",
        "ios/project.yml",
        "macos/Package.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/RustBridgeTests.swift"
      ],
      "depends_on": [
        "PR-04"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-swift bridge",
        "sh ios/scripts/swift-linux.sh test --filter RustBridgeTests",
        "xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination generic/platform=iOS\\ Simulator CODE_SIGNING_ALLOWED=NO build",
        "swift test --package-path macos --filter MacLaunchTests"
      ],
      "acceptance": [
        "New FFI lifetime/panic/threading smoke evidence and ios-kit/ios-app/macos-app lanes pass; accepted dependency-policy exception is recorded, Linux tests keep a real compiled bridge.",
        "Boundary approval requires the recorded sizing-spike commit/base and measured product-line/file budget, including Cargo.lock and complete packaging inputs; re-slice before approval if the cap is exceeded.",
        "Only completed codecs/primitives cross this early bridge. No placeholder decide/query export: actual domain dispatch and its FFI checks belong to PR-17/18 after PR-62."
      ],
      "budget": {
        "product_loc": 390,
        "files": 8
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-08",
      "outcome": "Project and tag commands preserve uniqueness and references",
      "tasks": [
        "T008"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-008",
        "026-FR-009",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/organize.rs",
        "rust/crates/bb-domain/tests/organize_parity.rs"
      ],
      "depends_on": [
        "PR-06"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test organize_parity",
        "cd backend && pytest tests/test_task_tag_project_mvp_api.py",
        "sh ios/scripts/swift-linux.sh test --filter 'ReducerProjectTests|ReducerTagTests'"
      ],
      "acceptance": [
        "The accepted catalog commands preserve relation identity and no late edit recreates a deletable entity."
      ],
      "budget": {
        "product_loc": 360,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-09",
      "outcome": "Archive and restoration retain membership",
      "tasks": [
        "T009"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-006",
        "026-FR-009",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/archive.rs",
        "rust/crates/bb-domain/tests/archive_parity.rs"
      ],
      "depends_on": [
        "PR-08"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test archive_parity",
        "cd backend && pytest tests/test_project_archive_lossless_api.py tests/test_project_archive_traces.py",
        "sh ios/scripts/swift-linux.sh test --filter ReducerArchiveTests"
      ],
      "acceptance": [
        "The existing lossless archive traces match with all task/project memberships present in one change set."
      ],
      "budget": {
        "product_loc": 340,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-10",
      "outcome": "Children remain attached and ordered under accepted commands",
      "tasks": [
        "T010"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-006",
        "026-FR-009",
        "026-FR-013",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/children.rs",
        "rust/crates/bb-domain/tests/children_parity.rs"
      ],
      "depends_on": [
        "PR-06"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test children_parity",
        "cd backend && pytest tests/test_task_api.py",
        "sh ios/scripts/swift-linux.sh test --filter 'ReducerSubtaskTests|ReducerCommentTests'"
      ],
      "acceptance": [
        "Existing child/comment examples match and every child has the preserved parent/identity/version."
      ],
      "budget": {
        "product_loc": 320,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-13",
      "outcome": "Formulation clocks preserve the accepted scalar and time semantics",
      "tasks": [
        "T013"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-016",
        "026-FR-017",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/formulation.rs",
        "rust/crates/bb-domain/tests/formulation_parity.rs"
      ],
      "depends_on": [
        "PR-06"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test formulation_parity",
        "cd backend && pytest tests/test_review_formulation_vectors.py tests/test_review_formulation.py",
        "sh ios/scripts/swift-linux.sh test --filter RecordContentFormTests"
      ],
      "acceptance": [
        "Accepted formulation vectors, including state outside Next and due floors, match without new revision side effects."
      ],
      "budget": {
        "product_loc": 390,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-07",
      "outcome": "Create, edit and lifecycle transitions have one pure decision result",
      "tasks": [
        "T007"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-007",
        "026-FR-009",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/task_rules.rs",
        "rust/crates/bb-domain/tests/task_rules_parity.rs"
      ],
      "depends_on": [
        "PR-13"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test task_rules_parity",
        "cd backend && pytest tests/test_task_lifecycle_detail_api.py tests/test_task_service.py",
        "sh ios/scripts/swift-linux.sh test --filter Reducer"
      ],
      "acceptance": [
        "Existing lifecycle/Waiting/priority examples match; stale completion does not undo a later reopen."
      ],
      "budget": {
        "product_loc": 380,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-11",
      "outcome": "Smart Add uses the accepted deterministic parser",
      "tasks": [
        "T011"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-017",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/smart_add.rs",
        "rust/crates/bb-domain/tests/smart_add_parity.rs"
      ],
      "depends_on": [
        "PR-07",
        "PR-08"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test smart_add_parity",
        "cd backend && pytest tests/test_task_smart_add_api.py",
        "sh ios/scripts/swift-linux.sh test --filter SmartAddParserTests"
      ],
      "acceptance": [
        "Accepted parser/reference/date examples match; basic capture remains independent of AI. The source-linked PR-02 web presentation vectors match the shared parser as well as the existing Apple examples."
      ],
      "budget": {
        "product_loc": 380,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-12",
      "outcome": "Task queries preserve existing list and history presentation facts",
      "tasks": [
        "T012"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-009",
        "026-FR-017",
        "026-FR-026",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/queries.rs",
        "rust/crates/bb-domain/tests/queries_parity.rs"
      ],
      "depends_on": [
        "PR-13"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test queries_parity",
        "sh ios/scripts/swift-linux.sh test --filter QueriesInvariantTests",
        "sh ios/scripts/swift-linux.sh test --filter QueriesHistoryTests"
      ],
      "acceptance": [
        "Existing query/order examples match, and a page does not materialize the entire 10,000-task store."
      ],
      "budget": {
        "product_loc": 380,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-14",
      "outcome": "Auto-park and human yield preserve specialized precedence",
      "tasks": [
        "T014"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-016",
        "026-SC-001",
        "026-SC-007"
      ],
      "paths": [
        "rust/crates/bb-domain/src/park.rs",
        "rust/crates/bb-domain/tests/park_parity.rs"
      ],
      "depends_on": [
        "PR-13"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test park_parity",
        "cd backend && pytest tests/test_review_auto_park.py tests/test_review_clock_seam.py",
        "sh ios/scripts/swift-linux.sh test --filter ReducerReviewReplayTests"
      ],
      "acceptance": [
        "A valid offline human decision yields an automatic move under accepted rules, rather than a generic stale rejection."
      ],
      "budget": {
        "product_loc": 390,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-15",
      "outcome": "Review decisions and releases retain per-item semantics",
      "tasks": [
        "T015"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-006",
        "026-FR-016",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/review_decisions.rs",
        "rust/crates/bb-domain/tests/review_decisions_parity.rs"
      ],
      "depends_on": [
        "PR-07",
        "PR-10",
        "PR-14"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test review_decisions_parity",
        "cd backend && pytest tests/test_review_decisions_api.py tests/test_review_traces.py",
        "sh ios/scripts/swift-linux.sh test --filter ReducerReviewReplayTests"
      ],
      "acceptance": [
        "Mixed eligible/stale bulk items produce the same accepted subset and one complete domain change set."
      ],
      "budget": {
        "product_loc": 390,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-16",
      "outcome": "Review session and query decisions preserve resume state",
      "tasks": [
        "T016"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-016",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/review_sessions.rs",
        "rust/crates/bb-domain/tests/review_sessions_parity.rs"
      ],
      "depends_on": [
        "PR-12",
        "PR-13"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test review_sessions_parity",
        "cd backend && pytest tests/test_review_flow_vectors.py tests/test_review_flow_api.py tests/test_review_settings_api.py",
        "sh ios/scripts/swift-linux.sh test --filter ReviewPlannersTests"
      ],
      "acceptance": [
        "Accepted flow/resume/query vectors match including captured-empty versus not captured; concurrent progress remains valid."
      ],
      "budget": {
        "product_loc": 390,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-20",
      "outcome": "A durable job ledger protects leases and retry budgets",
      "tasks": [
        "T020"
      ],
      "requirements": [
        "026-FR-015",
        "026-FR-022",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/jobs/repository.py",
        "backend/app/modules/tasks/jobs/domain.py",
        "backend/app/modules/tasks/repository.py",
        "backend/tests/test_task_jobs.py"
      ],
      "depends_on": [
        "PR-01"
      ],
      "tests": [
        "cd backend && pytest tests/test_task_jobs.py tests/test_task_repository.py"
      ],
      "acceptance": [
        "New integration coverage proves restart durability, lease expiry, stale fence rejection and retry exhaustion against the actual SQLite boundary."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-47",
      "outcome": "Shared AI policy validates local capability and proposal structure",
      "tasks": [
        "T047"
      ],
      "requirements": [
        "026-FR-018",
        "026-FR-019",
        "026-FR-020",
        "026-FR-021",
        "026-SC-006"
      ],
      "paths": [
        "rust/crates/bb-domain/src/ai_policy.rs",
        "rust/crates/bb-domain/src/proposal.rs",
        "rust/crates/bb-domain/tests/ai_policy_parity.rs"
      ],
      "depends_on": [
        "PR-06",
        "PR-61"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test ai_policy_parity"
      ],
      "acceptance": [
        "Only missing policy/proposal risks receive test-first coverage: prohibited fallback sends no content and invalid/unauthorized actions produce no command."
      ],
      "budget": {
        "product_loc": 380,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-62",
      "outcome": "Completed rule families are reachable through one tested dispatch",
      "tasks": [
        "T062"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-011",
        "026-FR-016",
        "026-FR-018",
        "026-SC-001"
      ],
      "paths": [
        "rust/crates/bb-domain/src/lib.rs",
        "rust/crates/bb-domain/src/dispatch.rs",
        "rust/crates/bb-domain/tests/dispatch.rs"
      ],
      "depends_on": [
        "PR-09",
        "PR-11",
        "PR-12",
        "PR-15",
        "PR-16",
        "PR-47"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain"
      ],
      "acceptance": [
        "Register only implemented modules and connect decide/query to their existing typed functions. Production-library dispatch reaches every catalog family and runs the frozen parity cases; no new rule, field translation or bulk cleanup belongs in this integration slice. Unready capability remains OFF."
      ],
      "budget": {
        "product_loc": 180,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-17",
      "outcome": "Apple facade selects the Rust rule version exclusively",
      "tasks": [
        "T017"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-009",
        "026-FR-016",
        "026-SC-001"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Reducer.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/SmartAdd.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/Queries.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyCore/RustDomainFacade.swift",
        "rust/bindings/swift/src/lib.rs",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/RustDomainParityTests.swift"
      ],
      "depends_on": [
        "PR-05",
        "PR-62"
      ],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests",
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain parity"
      ],
      "acceptance": [
        "Every catalog command/query selects one normative Rust result in a migrated epoch. Budget is for dispatch/mapping, not deletion of whole legacy modules; obsolete bodies are unreachable there.",
        "The real decide/query entry points are exported through this platform binding and checked for typed conversion, errors/panic containment and applicable lifetime/concurrency behavior; a primitive-only bridge smoke is insufficient here."
      ],
      "budget": {
        "product_loc": 380,
        "files": 5
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-18",
      "outcome": "Python task facade delegates task and organization rules",
      "tasks": [
        "T018"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-014",
        "026-FR-024",
        "026-SC-001"
      ],
      "paths": [
        "backend/app/modules/tasks/service.py",
        "backend/app/modules/tasks/rust_adapter.py",
        "backend/app/modules/tasks/rust_task_facade.py",
        "rust/bindings/python/src/lib.rs",
        "backend/tests/test_rust_task_parity.py"
      ],
      "depends_on": [
        "PR-04",
        "PR-62"
      ],
      "tests": [
        "cd backend && pytest tests/test_rust_task_parity.py tests/test_task_service.py tests/test_task_smart_add_api.py tests/test_project_archive_lossless_api.py"
      ],
      "acceptance": [
        "Each supported command obtains its decision from Rust once, while REST response/precondition/owner behavior is unchanged.",
        "The real decide/query entry points are exported through this platform binding and checked for typed conversion, errors/panic containment and applicable lifetime/concurrency behavior; a primitive-only bridge smoke is insufficient here."
      ],
      "budget": {
        "product_loc": 390,
        "files": 4
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-19",
      "outcome": "Python Review facade delegates review and clock rules",
      "tasks": [
        "T019"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-016",
        "026-FR-024",
        "026-SC-001"
      ],
      "paths": [
        "backend/app/modules/tasks/review_service.py",
        "backend/app/modules/tasks/review_flow.py",
        "backend/app/modules/tasks/rust_review_facade.py",
        "backend/tests/test_rust_review_parity.py"
      ],
      "depends_on": [
        "PR-18"
      ],
      "tests": [
        "cd backend && pytest tests/test_rust_review_parity.py tests/test_review_auto_park.py tests/test_review_decisions_api.py tests/test_review_flow_api.py tests/test_review_wire_fixtures.py"
      ],
      "acceptance": [
        "All existing Review/formulation examples match under one selected rule version, with server-only data absent from core/client DTOs."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-21",
      "outcome": "Worker command authority is checked before old-compatible writes",
      "tasks": [
        "T021"
      ],
      "requirements": [
        "026-FR-011",
        "026-FR-014",
        "026-FR-015",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/jobs/execution.py",
        "backend/app/modules/tasks/service.py",
        "backend/app/modules/tasks/review_service.py",
        "backend/app/container.py",
        "backend/tests/test_task_job_authority.py"
      ],
      "depends_on": [
        "PR-19",
        "PR-20"
      ],
      "tests": [
        "cd backend && pytest tests/test_task_job_authority.py tests/test_task_owner_isolation.py tests/test_review_auto_park.py"
      ],
      "acceptance": [
        "New test-first authority tests show revoked scopes and stale executors cannot create a mutation through compatible ports."
      ],
      "budget": {
        "product_loc": 380,
        "files": 4
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-22",
      "outcome": "Review job adapter preserves existing fenced effects",
      "tasks": [
        "T022"
      ],
      "requirements": [
        "026-FR-015",
        "026-FR-016",
        "026-FR-022",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/jobs/review_adapter.py",
        "backend/tests/test_review_job_handoff.py"
      ],
      "depends_on": [
        "PR-21"
      ],
      "tests": [
        "cd backend && pytest tests/test_review_job_handoff.py tests/test_review_auto_park.py tests/test_review_export_purge.py"
      ],
      "acceptance": [
        "Adapter crash/retry coverage preserves Review maintenance effects and flag-OFF/inactive-owner retention; integrated scheduling ownership is proved in PR-64.",
        "This slice tests the adapter through the PR-21 execution context while the existing scheduler remains its sole live owner. PR-64 performs registration and ownership handoff; this slice must not activate a second scheduler."
      ],
      "budget": {
        "product_loc": 360,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-23",
      "outcome": "Voice and privacy job adapters preserve module boundaries",
      "tasks": [
        "T023"
      ],
      "requirements": [
        "026-FR-014",
        "026-FR-015",
        "026-FR-022",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/jobs/voice_adapter.py",
        "backend/app/modules/tasks/jobs/privacy_adapter.py",
        "backend/tests/test_maintenance_job_handoff.py"
      ],
      "depends_on": [
        "PR-21"
      ],
      "tests": [
        "cd backend && pytest tests/test_maintenance_job_handoff.py tests/test_voice_brain_dump_recovery.py tests/test_brain_dump_flag_off_privacy.py tests/test_crt_receipt_retention.py"
      ],
      "acceptance": [
        "The adapter inventory names each cadence and existing privacy/recovery ports; retries and shutdown retain their accepted semantics. Actual scheduler ownership transfers only in PR-64.",
        "This slice tests the adapter through the PR-21 execution context while the existing scheduler remains its sole live owner. PR-64 performs registration and ownership handoff; this slice must not activate a second scheduler."
      ],
      "budget": {
        "product_loc": 380,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-24",
      "outcome": "Agent job adapter preserves lookup and uncertain outcomes",
      "tasks": [
        "T024"
      ],
      "requirements": [
        "026-FR-014",
        "026-FR-015",
        "026-FR-021",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/jobs/agent_adapter.py",
        "backend/app/modules/agents/observer.py",
        "backend/tests/test_agent_job_handoff.py"
      ],
      "depends_on": [
        "PR-21"
      ],
      "tests": [
        "cd backend && pytest tests/test_agent_job_handoff.py tests/test_agent_a2a_client.py"
      ],
      "acceptance": [
        "No old/new observer overlap; an expired lease cannot authorize a Task write and an unknown external effect is never reported as success.",
        "This slice tests the adapter through the PR-21 execution context while the existing scheduler remains its sole live owner. PR-64 performs registration and ownership handoff; this slice must not activate a second scheduler."
      ],
      "budget": {
        "product_loc": 360,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-64",
      "outcome": "One durable worker owns each handed-off scheduler responsibility",
      "tasks": [
        "T064"
      ],
      "requirements": [
        "026-FR-014",
        "026-FR-015",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/jobs/worker.py",
        "backend/app/main.py",
        "backend/tests/test_scheduler_handoff.py"
      ],
      "depends_on": [
        "PR-22",
        "PR-23",
        "PR-24"
      ],
      "tests": [
        "cd backend && pytest tests/test_scheduler_handoff.py tests/test_review_job_handoff.py tests/test_maintenance_job_handoff.py tests/test_agent_job_handoff.py tests/test_task_job_authority.py"
      ],
      "acceptance": [
        "Register completed adapters against the job ledger and existing execution context. Under the recorded default-OFF/storage epoch gate, switch each named scheduler exactly once; test restart/lease expiry and refusal of duplicate live owners. Auth scheduling and CRT storage/receipt ownership are unchanged. Measure full worker-loop plus old-scheduler changes before boundary approval; no effect implementation belongs in this join."
      ],
      "budget": {
        "product_loc": 350,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-25",
      "outcome": "Tasks and Review join one explicit SQLite unit of work",
      "tasks": [
        "T025"
      ],
      "requirements": [
        "026-FR-006",
        "026-FR-014",
        "026-FR-015",
        "026-SC-002",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/unit_of_work.py",
        "backend/app/modules/tasks/repository.py",
        "backend/app/modules/tasks/review_repository.py",
        "backend/tests/test_sync_unit_of_work.py"
      ],
      "depends_on": [
        "PR-64"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_unit_of_work.py tests/test_task_repository.py tests/test_review_repository.py"
      ],
      "acceptance": [
        "New test-first rollback/commit-race tests prove all aggregate writes and job intents use the same SQLite commit. Jobs/authority handoff is already green."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-26",
      "outcome": "Receipts and commit sequence are atomic with domain writes",
      "tasks": [
        "T026"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-006",
        "026-FR-011",
        "026-FR-012",
        "026-SC-002"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/receipts.py",
        "backend/app/modules/tasks/sync/change_log.py",
        "backend/app/modules/tasks/sync/unit_of_work.py",
        "backend/tests/test_sync_receipts.py"
      ],
      "depends_on": [
        "PR-25"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_receipts.py tests/test_sync_unit_of_work.py"
      ],
      "acceptance": [
        "New fault tests prove lost-response retry, before/after commit crash, mismatch, closed epoch known retry and retired-version receipt recovery without repeated mutation."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-27",
      "outcome": "Legacy task writers use the durable command boundary",
      "tasks": [
        "T027"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-006",
        "026-FR-014",
        "026-FR-024",
        "026-SC-002"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/command_handler.py",
        "backend/app/modules/tasks/sync/legacy_adapter.py",
        "backend/app/modules/tasks/service.py",
        "backend/app/container.py",
        "backend/tests/test_sync_legacy_tasks.py"
      ],
      "depends_on": [
        "PR-26"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_legacy_tasks.py tests/test_tasks_idempotency_repair.py tests/test_task_mcp.py tests/test_task_api.py"
      ],
      "acceptance": [
        "Every legacy task command publishes one receipt/feed transaction; changing operation or transport with the same legacy key cannot evade deduplication."
      ],
      "budget": {
        "product_loc": 390,
        "files": 4
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-28",
      "outcome": "Legacy Review writers publish complete public projections",
      "tasks": [
        "T028"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-006",
        "026-FR-014",
        "026-FR-016",
        "026-FR-022",
        "026-SC-002"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/review_projection.py",
        "backend/app/modules/tasks/sync/legacy_adapter.py",
        "backend/app/modules/tasks/review_service.py",
        "backend/app/modules/tasks/review_flow.py",
        "backend/app/modules/tasks/navigator.py",
        "backend/tests/test_sync_review_projection.py"
      ],
      "depends_on": [
        "PR-27"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_review_projection.py tests/test_review_traces.py tests/test_review_wire_fixtures.py tests/test_review_navigator.py"
      ],
      "acceptance": [
        "Snapshot/delta golden projections cover complete public Review state, captured-empty queues, links and no private fields; legacy replay remains exact. Existing grant-key/revoke collision and late colliding-revoke replay tests pass through the migrated adapter, including weekly_review OFF; original receipt and newer grant remain intact."
      ],
      "budget": {
        "product_loc": 390,
        "files": 5
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-29",
      "outcome": "Workflow, agent and internal writers cannot bypass receipts/feed",
      "tasks": [
        "T029"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-011",
        "026-FR-014",
        "026-FR-015",
        "026-FR-021",
        "026-FR-024",
        "026-SC-002",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/workflows/voice_brain_dump/task_port.py",
        "backend/app/cli.py",
        "backend/app/container.py",
        "backend/app/modules/tasks/jobs/execution.py",
        "backend/app/modules/tasks/sync/command_handler.py",
        "specs/026-rust-core-sync/contracts/command-catalog.md",
        "backend/tests/test_sync_writer_boundary.py"
      ],
      "depends_on": [
        "PR-28"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_writer_boundary.py tests/test_brain_dump_commit_ledger.py tests/test_task_mcp.py tests/test_review_auto_park.py"
      ],
      "acceptance": [
        "All named writers publish complete changes in the receipt/feed commit; forged origin, revoked authority and stale fences fail before mutation. No pilot can bypass this gate."
      ],
      "budget": {
        "product_loc": 380,
        "files": 5
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-30",
      "outcome": "Current authorization and epoch registration fence sync execution",
      "tasks": [
        "T030"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-010",
        "026-FR-011",
        "026-FR-012",
        "026-SC-002",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/authority.py",
        "backend/app/modules/tasks/sync/devices.py",
        "backend/app/modules/tasks/sync/command_handler.py",
        "backend/tests/test_sync_authority.py"
      ],
      "depends_on": [
        "PR-29"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_authority.py tests/test_task_owner_isolation.py"
      ],
      "acceptance": [
        "New test-first owner/epoch tests cover revoked receipt reads, forged internal origin, closed-epoch retry and lost registration response with the same ID. Unknown versus foreign scope/device/snapshot/transfer IDs have identical owner-safe 404 responses; authorized-scope command lookups preserve indistinguishable not_found."
      ],
      "budget": {
        "product_loc": 360,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-31",
      "outcome": "Command and capabilities endpoints expose the frozen contract",
      "tasks": [
        "T031"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-011",
        "026-FR-012",
        "026-FR-023",
        "026-FR-024",
        "026-SC-002"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/router.py",
        "backend/app/modules/tasks/sync/wire.py",
        "backend/app/main.py",
        "backend/tests/test_sync_commands_api.py"
      ],
      "depends_on": [
        "PR-30"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_commands_api.py tests/test_sync_authority.py"
      ],
      "acceptance": [
        "Each catalog form is accepted/rejected as documented; previous-major support/deadline is explicit and unsupported commands preserve recovery access."
      ],
      "budget": {
        "product_loc": 380,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-32",
      "outcome": "Delta pages preserve whole commit-ordered transactions",
      "tasks": [
        "T032"
      ],
      "requirements": [
        "026-FR-004",
        "026-FR-006",
        "026-FR-008",
        "026-FR-010",
        "026-FR-011",
        "026-SC-002",
        "026-SC-004"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/delta.py",
        "backend/app/modules/tasks/sync/transfers.py",
        "backend/app/modules/tasks/sync/delta_router.py",
        "backend/tests/test_sync_delta.py"
      ],
      "depends_on": [
        "PR-31"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_delta.py tests/test_sync_review_projection.py"
      ],
      "acceptance": [
        "New ordering/page/isolation tests include 500-item bulk with >500 changes, multi-page archive/tag deletion and crossing-record byte chunks; no partial operation or new legacy domain limit."
      ],
      "budget": {
        "product_loc": 370,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-33",
      "outcome": "Stable snapshots include every public aggregate record",
      "tasks": [
        "T033"
      ],
      "requirements": [
        "026-FR-006",
        "026-FR-010",
        "026-FR-011",
        "026-FR-013",
        "026-FR-016",
        "026-FR-022",
        "026-SC-002",
        "026-SC-005"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/snapshots.py",
        "backend/app/modules/tasks/sync/snapshot_router.py",
        "backend/tests/test_sync_snapshots.py"
      ],
      "depends_on": [
        "PR-32"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_snapshots.py tests/test_sync_review_projection.py"
      ],
      "acceptance": [
        "New snapshot integration coverage proves one watermark across concurrent writes, completeness/checksum and fail-closed expiry/redaction."
      ],
      "budget": {
        "product_loc": 390,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-58",
      "outcome": "Authenticated SSE wakes clients for committed changes from every writer",
      "tasks": [
        "T058"
      ],
      "requirements": [
        "026-FR-004",
        "026-FR-011",
        "026-FR-023",
        "026-SC-004"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/hints.py",
        "backend/app/modules/tasks/sync/hints_router.py",
        "backend/tests/test_sync_hints.py"
      ],
      "depends_on": [
        "PR-31"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_hints.py tests/test_sync_authority.py"
      ],
      "acceptance": [
        "Separate writer/stream processes prove committed-only, content-free publication, initial/reconnect catch-up, coalescing, owner-safe 404, revocation/generation closure and unbuffered delivery. The pilot measures the full <=2-second visible convergence bound."
      ],
      "budget": {
        "product_loc": 390,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-63",
      "outcome": "All sync routes are mounted with the same authority and OFF gate",
      "tasks": [
        "T063"
      ],
      "requirements": [
        "026-FR-004",
        "026-FR-011",
        "026-FR-024",
        "026-SC-002",
        "026-SC-004"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/router.py",
        "backend/tests/test_sync_routes.py"
      ],
      "depends_on": [
        "PR-33",
        "PR-58"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_routes.py tests/test_sync_commands_api.py tests/test_sync_delta.py tests/test_sync_snapshots.py tests/test_sync_hints.py"
      ],
      "acceptance": [
        "Mount the completed delta/transfer, snapshot and hint routers without reimplementing endpoint behavior. Real app route reachability, current authorization, owner-safe errors and default-OFF behavior pass before client integration."
      ],
      "budget": {
        "product_loc": 120,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-34",
      "outcome": "Local schema and cross-process lock preserve one writer",
      "tasks": [
        "T034"
      ],
      "requirements": [
        "026-FR-001",
        "026-FR-003",
        "026-FR-010",
        "026-FR-025",
        "026-SC-002"
      ],
      "paths": [
        "rust/crates/bb-client/Cargo.toml",
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/storage.rs",
        "rust/crates/bb-client/src/locking.rs",
        "rust/Cargo.toml",
        "rust/Cargo.lock",
        "rust/crates/bb-client/tests/storage.rs"
      ],
      "depends_on": [
        "PR-05",
        "PR-62"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client storage"
      ],
      "acceptance": [
        "New test-first durability/concurrent-process coverage proves confirmed local saves survive restart and lock/full-disk failures never report success. The measured slice includes the complete workspace/SQLite Cargo.lock delta within its product-line cap; oversize stops for boundary revision before approval."
      ],
      "budget": {
        "product_loc": 390,
        "files": 6
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-35",
      "outcome": "Local execute atomically persists immutable intent and projection",
      "tasks": [
        "T035"
      ],
      "requirements": [
        "026-FR-001",
        "026-FR-003",
        "026-FR-005",
        "026-FR-006",
        "026-FR-025",
        "026-SC-002"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/execute.rs",
        "rust/crates/bb-client/tests/execute.rs"
      ],
      "depends_on": [
        "PR-34"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client execute"
      ],
      "acceptance": [
        "New crash-boundary tests prove offline create/edit dependency order and restart persistence, including app/widget intake before registration."
      ],
      "budget": {
        "product_loc": 380,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-36",
      "outcome": "Replay preserves rejected intents and independent queue progress",
      "tasks": [
        "T036"
      ],
      "requirements": [
        "026-FR-007",
        "026-FR-008",
        "026-FR-010",
        "026-FR-023",
        "026-SC-002",
        "026-SC-008"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/replay.rs",
        "rust/crates/bb-client/src/issues.rs",
        "rust/crates/bb-client/tests/replay.rs"
      ],
      "depends_on": [
        "PR-35"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client replay"
      ],
      "acceptance": [
        "Existing conflict traces are adapted where sufficient; missing rejection/dependency tests prove no resurrection, no blind rekey and continued unrelated sync."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-37",
      "outcome": "Feed and receipt application cannot skip confirmed state",
      "tasks": [
        "T037"
      ],
      "requirements": [
        "026-FR-004",
        "026-FR-005",
        "026-FR-006",
        "026-FR-010",
        "026-SC-002"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/apply_changes.rs",
        "rust/crates/bb-client/src/receipts.rs",
        "rust/crates/bb-client/tests/apply_changes.rs"
      ],
      "depends_on": [
        "PR-36"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client apply_changes"
      ],
      "acceptance": [
        "New ACK-before/after-feed, missing-intermediate, multi-record/beyond-watermark and corrupted/missing/expired chunk cases prove durable confirmed+pending invariants; chunks never expose partial state."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-38",
      "outcome": "Snapshot activation preserves edits made during download",
      "tasks": [
        "T038"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-006",
        "026-FR-010",
        "026-FR-013",
        "026-FR-025",
        "026-SC-002",
        "026-SC-005"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/snapshot.rs",
        "rust/crates/bb-client/tests/snapshot.rs"
      ],
      "depends_on": [
        "PR-37"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client snapshot"
      ],
      "acceptance": [
        "New tests save/restart during snapshot and prove no newer queue loss, old-DB readability and no receipt proof from a different generation."
      ],
      "budget": {
        "product_loc": 390,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-39",
      "outcome": "Sync requests fence late responses and durable epoch registration",
      "tasks": [
        "T039"
      ],
      "requirements": [
        "026-FR-003",
        "026-FR-005",
        "026-FR-010",
        "026-FR-011",
        "026-FR-012",
        "026-SC-002",
        "026-SC-007"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/sync_session.rs",
        "rust/crates/bb-client/src/epochs.rs",
        "rust/crates/bb-client/tests/sync_session.rs"
      ],
      "depends_on": [
        "PR-38"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client sync_session"
      ],
      "acceptance": [
        "New test-first generation/epoch cases reject same-session pre-restore ACKs, stale registration and account-switch responses while independent recovered work proceeds."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-41",
      "outcome": "Legacy JSON imports to a verified staging store",
      "tasks": [
        "T041"
      ],
      "requirements": [
        "026-FR-010",
        "026-FR-013",
        "026-FR-022",
        "026-FR-025",
        "026-SC-005"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/import.rs",
        "ios/BrainBuddyKit/Sources/BrainBuddyPersistence/RustStoreImporter.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyPersistenceTests/RustStoreImporterTests.swift",
        "rust/crates/bb-client/tests/import.rs"
      ],
      "depends_on": [
        "PR-39"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client import",
        "sh ios/scripts/swift-linux.sh test --filter RustStoreImporterTests",
        "swift test --package-path macos --filter LegacyStoreImporterTests"
      ],
      "acceptance": [
        "Reference counts/IDs/links/flags equal the source or activation stops with source intact; full disk/corruption/unsupported epoch fail before switching."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-42",
      "outcome": "Legacy uncertain outbox entries retain provable identities",
      "tasks": [
        "T042"
      ],
      "requirements": [
        "026-FR-003",
        "026-FR-005",
        "026-FR-010",
        "026-FR-013",
        "026-SC-002",
        "026-SC-005"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/legacy_outbox.rs",
        "ios/BrainBuddyKit/Sources/BrainBuddyPersistence/RustOutboxImporter.swift",
        "rust/crates/bb-client/tests/legacy_outbox.rs"
      ],
      "depends_on": [
        "PR-41"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client legacy_outbox",
        "sh ios/scripts/swift-linux.sh test --filter StoreDocumentCodingTests"
      ],
      "acceptance": [
        "New uncertain-send migration coverage and existing coding fixtures prove no duplicate reconstruction and no falsely synchronized state."
      ],
      "budget": {
        "product_loc": 370,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-40",
      "outcome": "Transport drives bounded pull and subscription work",
      "tasks": [
        "T040"
      ],
      "requirements": [
        "026-FR-004",
        "026-FR-011",
        "026-FR-023",
        "026-FR-026",
        "026-SC-004"
      ],
      "paths": [
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/transport.rs",
        "rust/crates/bb-client/src/subscriptions.rs",
        "rust/crates/bb-client/tests/transport.rs"
      ],
      "depends_on": [
        "PR-39",
        "PR-63",
        "PR-41",
        "PR-42"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client transport",
        "sh ios/scripts/swift-linux.sh test --filter PeriodicSyncTickerTests"
      ],
      "acceptance": [
        "Controlled transport tests exercise loss/reorder/timeouts and bounded subscribers; hints only wake pull and never assert perpetual freshness. Real PR-58 SSE open/reopen, duplicate/coalesced hints and generation closure integrate with the unchanged poll deadline."
      ],
      "budget": {
        "product_loc": 380,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-43",
      "outcome": "Workspace binds the runtime without main-thread disk/network work",
      "tasks": [
        "T043"
      ],
      "requirements": [
        "026-FR-001",
        "026-FR-002",
        "026-FR-003",
        "026-FR-004",
        "026-FR-025",
        "026-FR-026",
        "026-SC-001",
        "026-SC-002"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace+Review.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/RustWorkspaceAdapter.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddySync/BrainBuddySync.swift",
        "rust/bindings/swift/src/lib.rs",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/RustWorkspaceTests.swift"
      ],
      "depends_on": [
        "PR-17",
        "PR-42"
      ],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter RustWorkspaceTests",
        "sh ios/scripts/swift-linux.sh test --filter WorkspaceCommandTests",
        "sh ios/scripts/swift-linux.sh test --filter WorkspaceSyncTests"
      ],
      "acceptance": [
        "Existing workspace journeys pass through one runtime; observer/cancel lifetime and nonblocking actor/UI delivery are verified at the actual Swift boundary."
      ],
      "budget": {
        "product_loc": 390,
        "files": 5
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-44",
      "outcome": "Sign-in, sign-out and shared extension access preserve scope isolation",
      "tasks": [
        "T044"
      ],
      "requirements": [
        "026-FR-003",
        "026-FR-011",
        "026-FR-013",
        "026-FR-025",
        "026-SC-002",
        "026-SC-005"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift",
        "ios/Shared/SharedWorkspace.swift",
        "macos/Sources/BrainBuddyMacCore/WorkspaceHost.swift",
        "macos/Sources/BrainBuddyMacCore/MacSyncController.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/RustAccountLifecycleTests.swift"
      ],
      "depends_on": [
        "PR-43"
      ],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter FirstSignInMergeTests",
        "sh ios/scripts/swift-linux.sh test --filter RustAccountLifecycleTests",
        "swift test --package-path macos --filter OfflineWorkspaceTests"
      ],
      "acceptance": [
        "New actual-boundary account/extension tests cover late old-owner responses and concurrent writes; existing merge/sign-out behavior is preserved."
      ],
      "budget": {
        "product_loc": 390,
        "files": 4
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-45",
      "outcome": "iPhone conflict and recovery journeys expose preserved work",
      "tasks": [
        "T045"
      ],
      "requirements": [
        "026-FR-007",
        "026-FR-008",
        "026-FR-010",
        "026-FR-012",
        "026-FR-023",
        "026-SC-008"
      ],
      "paths": [
        "ios/BrainBuddy/Components/SyncStatusLabel.swift",
        "ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift",
        "ios/BrainBuddy/Screens/Settings/SettingsScreen.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyCoreTests/SyncPresentationTests.swift",
        "specs/026-rust-core-sync/evidence/apple-ux.md"
      ],
      "depends_on": [
        "PR-44"
      ],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter SyncPresentationTests",
        "xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination generic/platform=iOS\\ Simulator CODE_SIGNING_ALLOWED=NO build"
      ],
      "acceptance": [
        "Bounded real-iPhone evidence exercises offline conflict/delete/reset/auth/version recovery with preserved text and accessible actions; required human design sign-off precedes work. M-02/D-02.11\u201312 covers preserved blocked descendants, explicit new-intent reapproval, named discard confirmation and interruption without silent loss."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-46",
      "outcome": "Mac conflict and recovery journeys preserve unobtrusive status",
      "tasks": [
        "T046"
      ],
      "requirements": [
        "026-FR-007",
        "026-FR-008",
        "026-FR-010",
        "026-FR-012",
        "026-FR-023",
        "026-SC-008"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/SyncStatusPopover.swift",
        "macos/Sources/BrainBuddyMac/SyncConflictView.swift",
        "macos/Sources/BrainBuddyMacCore/SyncPopoverModel.swift",
        "macos/Sources/BrainBuddyMacCore/SyncStatusLineModel.swift",
        "macos/Tests/BrainBuddyMacTests/RustSyncRecoveryTests.swift",
        "specs/026-rust-core-sync/evidence/mac-ux.md"
      ],
      "depends_on": [
        "PR-44"
      ],
      "tests": [
        "swift test --package-path macos --filter RustSyncRecoveryTests",
        "swift test --package-path macos --filter SyncStatusLineModelTests"
      ],
      "acceptance": [
        "Real-Mac evidence covers both conflict versions, interrupted recovery and update/auth states while existing quiet-status/accessibility checks pass. M-02/D-02.11\u201312 covers preserved blocked descendants, explicit new-intent reapproval, named discard confirmation and interruption without silent loss."
      ],
      "budget": {
        "product_loc": 390,
        "files": 4
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-48",
      "outcome": "Server AI adapters retain current consent and confirmation authority",
      "tasks": [
        "T048"
      ],
      "requirements": [
        "026-FR-019",
        "026-FR-020",
        "026-FR-021",
        "026-SC-006"
      ],
      "paths": [
        "backend/app/modules/tasks/navigator.py",
        "backend/app/workflows/voice_brain_dump/confirmation.py",
        "backend/app/workflows/voice_brain_dump/task_port.py",
        "backend/tests/test_rust_ai_policy.py"
      ],
      "depends_on": [
        "PR-29",
        "PR-47"
      ],
      "tests": [
        "cd backend && pytest tests/test_rust_ai_policy.py tests/test_review_navigator.py tests/test_brain_dump_consent_precedence.py tests/test_brain_dump_cancel_commit_race.py tests/test_brain_dump_commit_ledger.py"
      ],
      "acceptance": [
        "Existing consent/invalid-response/confirmation/cancel tests remain sufficient where protected; new tests cover only shared-policy integration gaps and AgentRun separation."
      ],
      "budget": {
        "product_loc": 350,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-49",
      "outcome": "Shared Apple suggestion adapter owns consent, proposals and request lifecycle",
      "tasks": [
        "T049"
      ],
      "requirements": [
        "026-FR-018",
        "026-FR-019",
        "026-FR-020",
        "026-FR-023",
        "026-SC-006"
      ],
      "paths": [
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/LocalAIAdapter.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/ReviewSuggestionModel.swift",
        "ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace+ReviewAI.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/LocalAIPolicyTests.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/ReviewSuggestionModelTests.swift",
        "specs/026-rust-core-sync/evidence/ai-consent.md"
      ],
      "depends_on": [
        "PR-44",
        "PR-47",
        "PR-48"
      ],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter 'LocalAIPolicyTests|ReviewSuggestionModelTests'"
      ],
      "acceptance": [
        "Actual available/unavailable local-adapter journeys plus denial/revocation/cancel/invalid proposal show no prohibited transmission and no unconfirmed Task change. Lost synchronous requests become interrupted without automatic resend; explicit cancellation ignores late results; closing the UI alone retains a live request. Native surface evidence follows in PR-59/60. Shared-model tests cover the valid clarifying-question branch, once-only answer append with stable command identity, save conflict/unknown outcome, saved revision adoption and inference-only retry; no duplicated platform state machine."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-59",
      "outcome": "iPhone Weekly Review suggestions expose recipient consent and explicit apply",
      "tasks": [
        "T059"
      ],
      "requirements": [
        "026-FR-018",
        "026-FR-019",
        "026-FR-020",
        "026-FR-023",
        "026-SC-006"
      ],
      "paths": [
        "ios/BrainBuddy/Screens/Review/DecisionCardSheet.swift",
        "ios/BrainBuddy/Screens/Review/ReviewSuggestionSheet.swift",
        "ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/LocalAIPolicyTests.swift",
        "specs/026-rust-core-sync/evidence/iphone-ai.md"
      ],
      "depends_on": [
        "PR-49"
      ],
      "tests": [
        "sh ios/scripts/swift-linux.sh test --filter LocalAIPolicyTests",
        "xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination generic/platform=iOS\\ Simulator CODE_SIGNING_ALLOWED=NO build"
      ],
      "acceptance": [
        "Real-iPhone evidence covers M-04 consent denial/revocation, local availability, proposal edit/stale apply, cancelling/cancelled and active-request close/reopen/process-loss outcomes; current payload and manual continuation remain intact. Question/answer .16\u201320 evidence includes answer-save failure, saved-answer/inference failure, explicit retry, revision adoption and unsaved-answer close/interruption without loss or duplicate append."
      ],
      "budget": {
        "product_loc": 390,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-60",
      "outcome": "Mac Weekly Review suggestions expose recipient consent and explicit apply",
      "tasks": [
        "T060"
      ],
      "requirements": [
        "026-FR-018",
        "026-FR-019",
        "026-FR-020",
        "026-FR-023",
        "026-SC-006"
      ],
      "paths": [
        "macos/Sources/BrainBuddyMac/ContentView.swift",
        "macos/Sources/BrainBuddyMac/ReviewSuggestionSheet.swift",
        "macos/Sources/BrainBuddyMacCore/BrainBuddyModel.swift",
        "macos/Tests/BrainBuddyMacTests/ReviewSuggestionTests.swift",
        "specs/026-rust-core-sync/evidence/mac-ai.md"
      ],
      "depends_on": [
        "PR-49"
      ],
      "tests": [
        "swift test --package-path macos --filter ReviewSuggestionTests",
        "swift build --package-path macos"
      ],
      "acceptance": [
        "Real-Mac D-04 evidence proves the bounded task-detail entry, same Weekly Review capability/payload, explicit consent/proposal/apply, request lifecycle and keyboard/VoiceOver; voice transcription is not accepted as this journey. Question/answer .16\u201320 evidence includes answer-save failure, saved-answer/inference failure, explicit retry, revision adoption and unsaved-answer close/interruption without loss or duplicate append."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-50",
      "outcome": "Deletion and retention apply to every sync copy",
      "tasks": [
        "T050"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-008",
        "026-FR-016",
        "026-FR-022",
        "026-SC-002"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/retention.py",
        "backend/app/modules/tasks/sync/receipts.py",
        "backend/app/modules/tasks/sync/change_log.py",
        "backend/app/modules/tasks/sync/snapshots.py",
        "backend/app/modules/tasks/jobs/privacy_adapter.py",
        "backend/tests/test_sync_retention.py"
      ],
      "depends_on": [
        "PR-33",
        "PR-48"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_retention.py tests/test_review_export_purge.py tests/test_brain_dump_idempotency_text_purge.py tests/test_crt_receipt_retention.py"
      ],
      "acceptance": [
        "New test-first inactive-owner/flag-OFF/read-deadline/page-crossing cases show no expired content or duplicate effects; legacy matching-record replay remains supported. Lost Smart Add ACK plus >24 hours offline and changed classification names/membership still resolves the immutable dependent alias using retained id_bindings."
      ],
      "budget": {
        "product_loc": 390,
        "files": 5
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-51",
      "outcome": "Export and purge include runtime records without leaking diagnostics",
      "tasks": [
        "T051"
      ],
      "requirements": [
        "026-FR-003",
        "026-FR-011",
        "026-FR-022",
        "026-FR-023",
        "026-SC-005",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/services/account_service.py",
        "rust/crates/bb-client/src/lib.rs",
        "rust/crates/bb-client/src/export.rs",
        "backend/tests/test_sync_export_purge.py",
        "rust/crates/bb-client/tests/export.rs",
        "specs/026-rust-core-sync/recovery.md"
      ],
      "depends_on": [
        "PR-42",
        "PR-50",
        "PR-40"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_export_purge.py tests/test_account_export.py tests/test_review_export_purge.py",
        "cargo test --manifest-path rust/Cargo.toml -p bb-client export"
      ],
      "acceptance": [
        "Existing export/purge evidence extended only for new categories proves complete relationships, no other-owner data and no text/media/credentials/fingerprints in diagnostics."
      ],
      "budget": {
        "product_loc": 380,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-52",
      "outcome": "Restore replays an independent deletion/revocation control ledger",
      "tasks": [
        "T052"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-010",
        "026-FR-011",
        "026-FR-015",
        "026-FR-022",
        "026-SC-002",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/control_ledger.py",
        "backend/app/modules/tasks/sync/restore.py",
        "backend/app/services/account_service.py",
        "backend/tests/test_sync_restore.py",
        "specs/026-rust-core-sync/recovery.md"
      ],
      "depends_on": [
        "PR-51"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_restore.py tests/test_sync_export_purge.py tests/test_sync_authority.py"
      ],
      "acceptance": [
        "New test-first backup-restore/purge/revocation cases prove no resurrected account/access or repeated internal effect; loss of confirmed commits is an incident, never ordinary successful reset."
      ],
      "budget": {
        "product_loc": 390,
        "files": 3
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-53",
      "outcome": "Web presentation stays compatible through versioned vectors and existing HTTP outcomes",
      "tasks": [
        "T053"
      ],
      "requirements": [
        "026-FR-002",
        "026-FR-009",
        "026-FR-014",
        "026-FR-024",
        "026-FR-026",
        "026-SC-001"
      ],
      "paths": [
        "frontend/src/features/tasks/smartAdd.ts",
        "frontend/src/features/tasks/TaskListPage.tsx",
        "frontend/src/features/tasks/TaskDetailPanel.tsx",
        "frontend/src/api/taskHooks.ts",
        "frontend/src/features/tasks/__tests__/smartAdd.test.ts",
        "rust/crates/bb-domain/tests/web_presentation.rs",
        "frontend/src/features/tasks/__tests__/TaskListPage.test.tsx"
      ],
      "depends_on": [
        "PR-18"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-domain --test web_presentation",
        "cd frontend && npm run test -- src/features/tasks/__tests__/smartAdd.test.ts src/features/tasks/__tests__/TaskListPage.test.tsx src/features/tasks/__tests__/TaskDetailPanel.test.tsx"
      ],
      "acceptance": [
        "Existing web task/Review/CLI/MCP behavior remains server-authoritative and CRT 200-node responsiveness retains its accepted baseline. The PR-02 source-linked rule-version vectors prove the retained parser/affordance adapter and actual composer agree with the shared oracle; HTTP rejections preserve drafts/retry. No per-record capabilities or raw-input preview is expected from sync capabilities, and no completed elimination of web presentation duplication is claimed."
      ],
      "budget": {
        "product_loc": 340,
        "files": 4
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-54",
      "outcome": "Apple/current-SQLite pilot proves the whole accepted outcome",
      "tasks": [
        "T054"
      ],
      "requirements": [
        "026-FR-001",
        "026-FR-002",
        "026-FR-003",
        "026-FR-004",
        "026-FR-005",
        "026-FR-006",
        "026-FR-007",
        "026-FR-008",
        "026-FR-009",
        "026-FR-010",
        "026-FR-011",
        "026-FR-012",
        "026-FR-013",
        "026-FR-014",
        "026-FR-015",
        "026-FR-016",
        "026-FR-017",
        "026-FR-018",
        "026-FR-019",
        "026-FR-020",
        "026-FR-021",
        "026-FR-022",
        "026-FR-023",
        "026-FR-024",
        "026-FR-025",
        "026-FR-026",
        "026-SC-001",
        "026-SC-002",
        "026-SC-003",
        "026-SC-004",
        "026-SC-005",
        "026-SC-006",
        "026-SC-007",
        "026-SC-008"
      ],
      "paths": [
        "rust/crates/bb-client/tests/protocol_faults.rs",
        "specs/026-rust-core-sync/evidence/apple-pilot.md",
        "specs/026-rust-core-sync/verification.md"
      ],
      "depends_on": [
        "PR-45",
        "PR-46",
        "PR-49",
        "PR-52",
        "PR-53",
        "PR-59",
        "PR-60"
      ],
      "tests": [
        "cargo test --manifest-path rust/Cargo.toml -p bb-client protocol_faults",
        "make verify-all",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyCoreTests",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddySyncTests",
        "sh ios/scripts/swift-linux.sh test --filter BrainBuddyWorkspaceTests",
        "swift test --package-path macos",
        "./scripts/production_smoke.sh"
      ],
      "acceptance": [
        "Actual independent acceptance and exact-SHA CI/release/smoke prove SC-001\u2026008 on Apple plus the current SQLite server; all pending issues are visible and pilot approval is separately recorded. SC-004 uses the actual cross-process SSE server/client path; Q02/Q09/Q12 include the new dependent-action and request-lifecycle states."
      ],
      "budget": {
        "product_loc": 1,
        "files": 1
      },
      "implementer": "mechanical-implementer"
    },
    {
      "id": "PR-55",
      "outcome": "PostgreSQL adapter satisfies the frozen unit of work",
      "tasks": [
        "T055"
      ],
      "requirements": [
        "026-FR-005",
        "026-FR-006",
        "026-FR-014",
        "026-FR-015",
        "026-SC-002",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/postgres.py",
        "backend/pyproject.toml",
        "backend/tests/test_sync_postgres.py"
      ],
      "depends_on": [
        "PR-25",
        "PR-54"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_postgres.py"
      ],
      "acceptance": [
        "The same rollback/receipt/feed/fence fixtures pass on PostgreSQL while current SQLite remains the only active writer."
      ],
      "budget": {
        "product_loc": 390,
        "files": 2
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-56",
      "outcome": "Stopped-writer migration verifies a complete target before switching",
      "tasks": [
        "T056"
      ],
      "requirements": [
        "026-FR-010",
        "026-FR-013",
        "026-FR-014",
        "026-FR-022",
        "026-SC-005",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/modules/tasks/sync/migrate_postgres.py",
        "backend/tests/test_sync_postgres_migration.py",
        "specs/026-rust-core-sync/recovery.md"
      ],
      "depends_on": [
        "PR-55"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_postgres_migration.py tests/test_sync_postgres.py"
      ],
      "acceptance": [
        "New migration-failure/restart tests stop before switching on incomplete copy; rehearsal preserves every aggregate/receipt/feed/job identity and original immutable outcomes."
      ],
      "budget": {
        "product_loc": 380,
        "files": 1
      },
      "implementer": "feature-implementer"
    },
    {
      "id": "PR-57",
      "outcome": "Authorized cutover keeps one storage epoch and proven recovery",
      "tasks": [
        "T057"
      ],
      "requirements": [
        "026-FR-010",
        "026-FR-011",
        "026-FR-013",
        "026-FR-014",
        "026-FR-015",
        "026-FR-022",
        "026-SC-005",
        "026-SC-007"
      ],
      "paths": [
        "backend/app/container.py",
        "backend/app/modules/tasks/sync/postgres_cutover.py",
        "backend/tests/test_sync_postgres_cutover.py",
        "specs/026-rust-core-sync/evidence/postgres-cutover.md"
      ],
      "depends_on": [
        "PR-56"
      ],
      "tests": [
        "cd backend && pytest tests/test_sync_postgres_cutover.py tests/test_sync_restore.py tests/test_sync_export_purge.py",
        "make verify-all",
        "./scripts/production_smoke.sh"
      ],
      "acceptance": [
        "Recorded migration authorization, one active DB, exact-SHA CI/release/smoke and actual restore rehearsal are present; a different SHA or partial rollback is not Done."
      ],
      "budget": {
        "product_loc": 300,
        "files": 2
      },
      "implementer": "feature-implementer"
    }
  ],
  "review_budget": {
    "total_changed_lines": 800,
    "count": "all additions plus deletions, including tests, docs, specifications, lockfiles and generated committed text",
    "on_exceed": "stop and re-slice; oversize_reason is not an exception for feature 026"
  }
}
```
