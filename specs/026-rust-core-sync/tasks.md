# Tasks: shared Rust core and custom synchronization

Status: draft sequence, not authorization to execute product changes. The user requested a specification. Before implementation, detailed PR slices must receive a separately agreed `brainbuddy-pr-slices/v2` map. The items below are stages, not claims that each stage fits one PR. Every future slice will have real paths, a budget of ≤ 400 product lines / 12 files, and its own verification.

## Phase 1 — Freeze the contract

- [ ] T001 Clarify and accept `specs/026-rust-core-sync/design.md`, `adr-draft.md`, and the proposed contract defaults; record actual decisions without assigning human sign-off automatically.
- [ ] T002 Run the mandatory ADR-0011 planning review against current `spec.md`, `design.md`, `plan.md`, and `contracts/sync-v1.md`; fix confirmed defects and obtain an admissible verdict.
- [ ] T003 Produce schemas/OpenAPI, a mapping of every current writer/command, and the PR-slice map in `specs/026-rust-core-sync/contracts/` and this file; verify FR-001…FR-026 coverage and run analyze. Coding does not begin before contracts are frozen.

## Phase 2 — US1 and US4, one core on Apple and the server

- [ ] T004 Reconcile existing normalization, formulation, and archive golden vectors in `ios/BrainBuddyKit/Tests/` and `backend/tests/`; freeze the parity oracle, target devices, and workload for SC-001/003.
- [ ] T005 Complete a Rust/Swift/Python vertical slice in the proposed `rust/crates/bb-domain/`, `rust/bindings/swift/`, and `rust/bindings/python/`, preserving one writer; verify FFI lifetime, errors, packaging, and `ios/AGENTS.md` requirements.
- [ ] T006 Move the reducer, Smart Add, normalization, queries, and Review from `BrainBuddyCore` and `backend/app/modules/tasks/` into the core by rule group; remove the replaced domain authority after parity is established, leaving no second live implementation.

## Phase 3 — US1, US2, and US3, reliable sync

- [ ] T012 Before T007, use the `backend/app/main.py` inventory to move existing jobs into a durable job adapter with leases/fencing. Establish and verify this authority through the existing compatible task application ports; it does not depend on the new sync transport. Disable the old scheduler owner only after equivalence and safe retries are verified, without overlapping scheduler ownership. T007 must not connect internal writers until this prerequisite passes.
- [ ] T007 After T012, add durable receipt/feed transactions and the compatibility adapter in `backend/app/modules/tasks/`, together with missing crash/deduplication/ordering tests; connect all writers through `backend/app/container.py` and application ports. Verify that every internal writer supplies current execution authority/fencing and publishes its mutation in the shared receipt/feed transaction before proceeding to a sync pilot.
- [ ] T008 Implement snapshot/delta/capabilities and version/epoch handling in the proposed `backend/app/modules/tasks/sync/`; prove commit order, expiry, account isolation, and current authorization rechecks.
- [ ] T009 Implement the SQLite/outbox/replay runtime in `rust/crates/bb-client/` and JSON import through `BrainBuddyPersistence`; verify multiple processes, full disk, legacy uncertain outbox entries, account-less use, and linked identity mapping.
- [ ] T010 Connect the runtime through `BrainBuddyWorkspace` and existing iOS/macOS sync surfaces; implement the agreed M-/D- states from `design.md` and verify conflict/reset/sign-out behavior on devices.
- [ ] T011 After T012 and T007–T010 pass, run the fault/convergence/compatibility suite and a pilot rollout for existing Apple clients with the current backend, before the separate server DB migration; retain exact-SHA and recovery evidence. The pilot is blocked until all writers, including auto-park/jobs, have verified authority/fencing and receipt/feed coverage.

## Phase 4 — US4 and US5, server responsibilities and AI adapters

- [ ] T013 Connect shared AI policy/proposal validation to existing `backend/app/workflows/voice_brain_dump/` and native adapters; verify consent denial, cancellation, and invalid proposals without changing ADR-0002.
- [ ] T014 Prepare a separate stopped-writer migration of the Tasks aggregate/receipts/feed/jobs to PostgreSQL; add the migration in `backend/app/modules/tasks/`, update backup/export/purge/recovery adapters, and obtain the required migration authorization.

## Phase 5 — New platforms

- [ ] T015 Freeze separate platform slices and implement the Android consumer in `rust/bindings/kotlin/` plus a native shell covering US1–US3; reuse shared rules and verify a real device and offline recovery.
- [ ] T016 After the Android portability gate, agree and implement the Windows C ABI consumer and Linux GTK shell; freeze their new product paths and packaging in the platform slice before coding.

## Dependencies and acceptance

T001–T003 → T004–T006 → T012 → T007–T011. T012 retains its identifier but runs first in Phase 3: durable job authority and fencing are prerequisites of the all-writer boundary and pilot, not a later follow-up. T013 may be prepared after the command contract is frozen, but cannot bypass domain-authority changes; T014 is a separate migration rollout. T015/T016 consume the accepted protocol/runtime. Parallel work within stages is allowed only for disjoint approved slices.

The criteria are US1–US5 and SC-001…SC-008 in `spec.md`; specific checks are listed in plan §8 and contract §10. Product acceptance, traceability, and the report are produced from actual implementation evidence. The current spec-only verification does not complete any implementation checkbox.
