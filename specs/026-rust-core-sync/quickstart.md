# Validation guide: shared core and sync

Status: planned implementation acceptance, 2026-10-09. Existing commands below validate the repository today. Rust crates, sync endpoints, and fault suites described by the PR map are future deliverables; their results are not claimed here. Use synthetic accounts and content, isolated databases, and a disposable server. Never run crash/restore/purge scenarios against production.

## Document verification now

From the repository root:

```bash
make check-specs
python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py
git diff --check
```

Spec Kit uses the installed, repository-pinned v1.0.11 assets; no integration refresh is required. Select this existing feature rather than creating a second numbered directory:

```bash
SPECIFY_FEATURE_DIRECTORY=specs/026-rust-core-sync bash .specify/scripts/bash/check-prerequisites.sh --json --require-spec --require-tasks --include-tasks
```

## Reused behavioral baseline

Run the sufficient affected suites while developing each slice. Existing examples are the expected behavior, not evidence that the future protocol works:

```bash
cd backend
python -m pytest tests/test_review_formulation_vectors.py tests/test_review_traces.py tests/test_project_archive_traces.py tests/test_task_smart_add_api.py
```

```bash
swift test --package-path ios/BrainBuddyKit
swift test --package-path macos
```

The Mac package command requires macOS/Xcode 26. Linux can exercise the Foundation-only BrainBuddyKit boundary with the repository's documented Swift toolchain. Use `make verify-all` and the required `ios-kit`, `ios-app`, and `macos-app` CI lanes on the frozen implementation candidate; a bare test runner does not replace coverage/Allure gates. The final shared implementation additionally runs `cargo test --manifest-path rust/Cargo.toml --workspace` once the workspace exists. Slice-specific commands are in [tasks.md](tasks.md).

## Acceptance environment and evidence

Use an iPhone 11/iOS 26 and MacBook Air M1/8 GB/macOS 26 for the performance baseline, plus the repository's supported simulator/build matrix. Record exact OS patch, device, compiler/binding versions, release build SHA, server SHA, schema/rule/protocol versions, effective flags, and fixture seed. These are proposed minimum measurement devices, not a change to supported hardware. Hardware unavailability is an unmet acceptance gate, never a simulated pass.

Use two synthetic owners A/B, two native devices for A, one supported legacy client, web, CLI, MCP, Capture, Review and internal workers. The golden oracle consists of existing formulation/archive/Review vectors and accepted ADRs. New fault coverage adds only missing invariants at real transaction, process, HTTP and FFI boundaries. Observe an initial failing invariant before implementing its protection under Constitution II; do not duplicate an already sufficient check.

For every row record input/seed, exact fault point, expected/actual domain state, receipt outcome, remaining queue/issues, and safe correlation ID. A timeout or missing result is not a pass. Evidence contains no real user content, credentials or content fingerprints.

| Scenario | Procedure and observable pass condition | Coverage |
| --- | --- | --- |
| Q01 offline capture | Disconnect A's phone; create, move and edit; kill/reopen after local success. Reconnect, then observe Mac and server. Every acknowledged local intent survives and is reflected once after convergence. Account-less work issues no account request. | US1; FR-001/003/004/005/006/009/025; SC-002 |
| Q02 concurrent edits | From one base edit the same task differently on both devices; deliver in each order. Resolve against the displayed version, then change it again before submitting. Both original texts remain available; stale resolution conflicts again; an unrelated task syncs. Repeat delete/edit on an existing deletable Tag. | US2; FR-007/008; SC-002/008 |
| Q03 delivery faults | Drop request, response and hint separately; crash before/after server commit and local apply; reorder ACK/feed; retry original IDs and retired-version envelopes. Exactly one internal effect, no cursor jump, eventual known or explicit unknown outcome. Replay a rejected dependency and independent command. | US1/2; FR-005/006/012/014; SC-002/004 |
| Q04 reset with live edits | Expire cursor; page snapshot while capturing new local tasks; interrupt/restart; close old epoch and lose new registration ACK. Preserve immutable old uncertainty and new intake; activate latest live queue atomically; independent new work resumes. Include oversized atomic domain operations and incomplete body download. | US3; FR-010/012/025; SC-002/005 |
| Q05 isolation | Expire A's session, switch to B with the documented pending-work choice, then deliver A's old response. B receives none of A's cache/queue/receipts. Reauthenticate A without moving pending work across owners. Cross-owner IDs reveal no content. | US3; FR-003/011/022; SC-002/007 |
| Q06 import | Import each legacy reference shape including local aliases, desired outcomes, Review state, unknown sends and drafts. Compare all fields/relations, not counts alone. Inject low disk, corrupt input and competing widget writer. Failure leaves original active/intact; no guessed replay or lost local-only value. | US3; FR-013/017/025; SC-005 |
| Q07 parity and writers | Run the same normative vectors through Rust, PyO3 and Swift. Exercise each writer in the command catalog, including Capture/Review/internal jobs, and read the resulting feed on the other client. Each rule has one active authority and every mutation publishes its atomic public changes. | US4; FR-002/009/014/016/017/021/024; SC-001 |
| Q08 jobs and restore | Let a worker lease expire after submission, then retry with old/new fences. Restore a consistent disposable backup behind closed access; replay control decisions and fence old responses. Internal effect is not duplicated; unknown external effect stops for reconciliation. Deleted owners/revoked sessions cannot reappear. | US3/4; FR-010/011/015/022; SC-007 |
| Q09 AI | Exercise suitable/absent/failed local model; on-device-only; denied/revoked consent; provider/input-version change; invalid/stale proposal; cancel before/after transmission. Blocked recipients receive zero content-bearing requests; only explicit valid confirmation changes a task; AgentRun success alone does not. | US5; FR-018/019/020/021/022; SC-006 |
| Q10 retention | Advance controlled time across 24-hour response and seven-day Review content expiry with owner inactive and flag OFF. Read receipt/feed/snapshot; export and purge. No expired payload returns; content-free replay remains until purge; scoped Capture exception and legacy matching-record success remain intact. | US3/4; FR-005/014/016/022; SC-002/007 |
| Q11 web regression | Execute existing task capture, edit, archive, Review and agent workflows through unchanged public routes after server cutover. Existing response shapes, authority, and error behavior remain; CRT 200-node scenario retains its existing performance gate. | FR-014/021/024/026; SC-001 |
| Q12 user recovery | On each Apple client, show waiting and persistent failure, open a two-version conflict, apply a chosen version, interrupt a rebuild and resume it. A representative user explains what is local versus confirmed, completes all three journeys without coaching/files, and can reach actions using keyboard/VoiceOver. Compare all applicable M-/D- states and status timings. | FR-023/026; SC-008 |

Each technical variation in [sync-v1.md §10](contracts/sync-v1.md#10-required-validation-scenarios) belongs to Q03/Q04/Q07/Q08/Q10; none may be silently dropped because the table uses grouped scenarios. [tasks.md](tasks.md) binds every FR/SC to its implementation slice and checks. Planned scenarios are not delivered traceability evidence.

## Performance procedure

SC-003: deterministic synthetic fixture with 10,000 tasks across all four lists, 100 projects, 100 Tags, representative children/notes, and 100 pending commands. Use Release builds, no attached debugger, normal thermal state, low-power mode off, and no inference running. After one warmup, collect at least 1,000 mixed create/title-edit/move/complete operations over five runs per reference device. Measure from user command entry until durable local success; report per-run and pooled p95, with failures reported separately. Pooled p95 must be ≤50 ms on each device; background replay must introduce no main-thread stall ≥100 ms while scrolling/editing. Record memory and thermal conditions so a bad run is not silently excluded. Full-disk/error cases verify truthful failure, not the latency target.

SC-004: two foreground clients, RTT constrained to ≤100 ms, no server throttling, at most 100 pending commands. Run 100 deterministic batches, alternating the final writer. Measure from last server commit until both clients have applied the final watermark and expose the same projection; p95 ≤2 s with the selected hint transport. Drop all hints in a separate run and commit immediately after a fallback poll completes. Force the longest allowed jittered interval: poll starts remain at most 30 s apart, and each active client applies the update and exposes the new projection within 60 s of the server commit, including requests and catch-up. Assert both bounds; a timer firing or request starting alone is not convergence. Measure clock intervals in the harness using one clock; never subtract unsynchronized client wall clocks. Background OS scheduling is excluded explicitly.

## Cutover and rollback drill

1. Freeze a candidate and verify the complete Apple/server path while the new scope capability is OFF by default. Confirm all writers and durable job fencing before enrollment.
2. Enroll only the explicit internal pilot scope. Read back effective capability, schema epoch and exact SHA; run Q01–Q12 and the performance measurements. Removing enrollment stops new exposure; it never switches a migrated queue/database back to an incompatible writer.
3. For PostgreSQL, obtain separate ASK authorization, stop all task writers and workers, and take a consistent aggregate/receipt/feed/job backup. Import into staging, compare every record/relationship and terminal receipt, then switch one authority and generation. On any mismatch, keep access closed and the old store authoritative.
4. Before reopening writes, rollback may restore the unchanged old store and its compatible image. After the first new-store commit, an old snapshot is not a lossless rollback: stop writes and use the tested compatible image on the current store, or forward-repair/reconcile under an explicit incident decision. Never erase newer receipts/effects to make an old binary work.
5. Proposed disaster objectives are RPO ≤24 hours and RTO ≤4 hours for the synthetic acceptance workload. Take and verify a protected daily consistent backup (including restore metadata); the separate control ledger must not roll back with it. Simulate loss up to the RPO and report any lost acknowledged commits explicitly; clients' old receipts cannot prove restored data exists. Fail closed when control-ledger completeness or privacy cleanup cannot be proved. Source content TTLs and purge obligations apply to backup material too; RPO is not permission to replay uncertain external effects.

The release maintainer owns the drill and incident decision. Missing hardware, failed recovery, exceeded performance/RPO/RTO targets or incomplete write inventory blocks expansion. Produce `acceptance.md`, delivered `traceability.md` and `report.md` only from actual implementation evidence, not from this planned guide.
