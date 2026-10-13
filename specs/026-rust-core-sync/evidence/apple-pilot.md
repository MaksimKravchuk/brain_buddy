# Apple pilot evidence: Q01–Q12, performance and cutover (T054)

Status: **pending**. Nothing below has been run on a device or against a pilot scope. This is the
template the PR-54 acceptance run fills in. Every cell reads `pending` until a person or the
named harness records an observed value; do not enter an estimate, a number from another build,
or a result from a simulator in place of the reference device. A timeout or a missing result is
not a pass (quickstart.md, Validation guide).

Source of the procedure: `quickstart.md` (Q01–Q12, Performance procedure, Cutover and rollback
drill) and `contracts/sync-v1.md` section 10. The protocol-level fault replay that precedes this
run is `rust/crates/bb-client/tests/protocol_faults.rs`; its green result is a precondition, not a
substitute for any row here.

Evidence contains no real user content, credentials or content fingerprints. Use two synthetic
owners A/B. Record safe correlation IDs only.

## 1. Run identity

| Field | Value |
|---|---|
| Exact commit SHA under test | pending |
| Build configuration | Release, no attached debugger (pending) |
| Server image / schema epoch | pending |
| Pilot scope (internal, explicit) | pending |
| `rust_core_sync` effective capability read back | pending |
| Storage: current SQLite (no PostgreSQL cutover in this PR) | pending |
| Run date / release maintainer | pending / pending |
| Writer / fence / retention / restore gates green before enrollment | pending |

## 2. Reference devices

| Role | Device | OS | Memory | Power / thermal | Build installed | Result |
|---|---|---|---|---|---|---|
| Phone | iPhone 11 | iOS 26 | pending | low-power mode off, normal thermal (pending) | pending | pending |
| Laptop | MacBook Air M1 | macOS 26 | 8 GB | normal thermal (pending) | pending | pending |

## 3. Reference-store import

| Item | Evidence | Result |
|---|---|---|
| Legacy reference store imported on iPhone 11 | field-by-field and relation comparison, not counts alone | pending |
| Legacy reference store imported on MacBook Air M1 | same | pending |
| Injected low disk / corrupt input / competing widget writer leaves the original active and intact | Q06 | pending |

## 4. Scenario matrix (Q01–Q12)

For every row record: input/seed, exact fault point, expected and actual domain state, receipt
outcome, remaining queue and issues, and a safe correlation ID.

| Scenario | Coverage | iPhone 11 / iOS 26 | MacBook Air M1 / macOS 26 | Correlation ID | Notes |
|---|---|---|---|---|---|
| Q01 offline capture | US1; FR-001/003/004/005/006/009/025; SC-002 | pending | pending | pending | pending |
| Q02 concurrent edits | US2; FR-007/008; SC-002/008 | pending | pending | pending | pending |
| Q03 delivery faults | US1/2; FR-005/006/012/014; SC-002/004 | pending | pending | pending | pending |
| Q04 reset with live edits | US3; FR-010/012/025; SC-002/005 | pending | pending | pending | pending |
| Q05 isolation | US3; FR-003/011/022; SC-002/007 | pending | pending | pending | pending |
| Q06 import | US3; FR-013/017/025; SC-005 | pending | pending | pending | pending |
| Q07 parity and writers | US4; FR-002/009/014/016/017/021/024; SC-001 | pending | pending | pending | pending |
| Q08 jobs and restore | US3/4; FR-010/011/015/022; SC-007 | pending | pending | pending | pending |
| Q09 AI | US5; FR-018/019/020/021/022; SC-006 | pending | pending | pending | pending |
| Q10 retention | US3/4; FR-005/014/016/022; SC-002/007 | pending | pending | pending | pending |
| Q11 web regression | FR-014/021/024/026; SC-001 | not applicable (server/web) | not applicable | pending | pending |
| Q12 user recovery | FR-023/026; SC-008 | pending | pending | pending | pending |

### 4.1 Protocol fault replay (precondition for Q03/Q04/Q08/Q10)

Automated, real backend. Record the exact SHA and the command; `ignored` cases must be listed
with their reason, never counted as passes.

| Fault case (`protocol_faults.rs`) | Q rows | Result at the exact SHA |
|---|---|---|
| crash between local commit and send | Q01/Q03 | pending |
| lost ACK, crash, later receipt replay | Q03 | pending |
| duplicate delivery of a command chain | Q03 | pending |
| replayed feed page | Q03 | pending |
| dependent overtakes its create | Q03 | pending |
| epoch closed mid-send | Q04 | pending |
| server rollback to a backup (restore path) | Q04/Q08 | pending |
| generation change with an active epoch (needs PR-52 epoch closure) | Q04/Q08 | pending |
| snapshot expiry mid-bootstrap | Q04 | pending |
| lost transfer pages | Q04 | pending |
| lost hint, poll fallback | Q03 | pending |
| lost Smart Add ACK across rename and 24 h | Q10 | pending |
| two devices, lost and duplicated deliveries | Q03 | pending |

## 5. SC-003 local latency

Fixture: deterministic synthetic, 10,000 tasks across all four lists, 100 projects, 100 Tags,
representative children/notes, 100 pending commands. Release build, no debugger, low-power mode
off, no inference running. One warmup, then at least 1,000 mixed create / title-edit / move /
complete operations in each of five runs per device. Measured from user command entry until
durable local success. Failures are reported separately; a bad run is not excluded.

Target per device: pooled p95 ≤ 50 ms; no main-thread stall ≥ 100 ms during background replay
while scrolling and editing.

| Device | Run | Operations (≥1,000 across five runs) | p95 (ms) | Failures | Max main-thread stall (ms) | Memory | Thermal state |
|---|---|---|---|---|---|---|---|
| iPhone 11 / iOS 26 | 1 | pending | pending | pending | pending | pending | pending |
| iPhone 11 / iOS 26 | 2 | pending | pending | pending | pending | pending | pending |
| iPhone 11 / iOS 26 | 3 | pending | pending | pending | pending | pending | pending |
| iPhone 11 / iOS 26 | 4 | pending | pending | pending | pending | pending | pending |
| iPhone 11 / iOS 26 | 5 | pending | pending | pending | pending | pending | pending |
| iPhone 11 / iOS 26 | pooled | pending | pending (target ≤ 50) | pending | pending (target < 100) | pending | pending |
| MacBook Air M1 / 8 GB / macOS 26 | 1 | pending | pending | pending | pending | pending | pending |
| MacBook Air M1 / 8 GB / macOS 26 | 2 | pending | pending | pending | pending | pending | pending |
| MacBook Air M1 / 8 GB / macOS 26 | 3 | pending | pending | pending | pending | pending | pending |
| MacBook Air M1 / 8 GB / macOS 26 | 4 | pending | pending | pending | pending | pending | pending |
| MacBook Air M1 / 8 GB / macOS 26 | 5 | pending | pending | pending | pending | pending | pending |
| MacBook Air M1 / 8 GB / macOS 26 | pooled | pending | pending (target ≤ 50) | pending | pending (target < 100) | pending | pending |

Full-disk and error cases verify a truthful failure, not the latency target: pending.

## 6. SC-004 two-client freshness

Two foreground clients, RTT constrained to ≤ 100 ms, no server throttling, at most 100 pending
commands, the real authenticated SSE endpoint, final writer and stream in separate server
processes. One clock for all intervals; never subtract unsynchronized wall clocks. Background OS
scheduling is excluded explicitly.

| Measurement | Target | Observed | Result |
|---|---|---|---|
| 100 deterministic batches, alternating final writer: last commit to both clients applied and equal projection, p95 | ≤ 2 s | pending | pending |
| Constrained RTT during the run | ≤ 100 ms | pending | pending |
| Committed-counter publication, no proxy buffering, reconnect catch-up, bounded coalescing | verified | pending | pending |
| All hints dropped, longest allowed jittered interval: poll starts apart | ≤ 30 s | pending | pending |
| All hints dropped: commit to visible on each active client, including requests and catch-up | ≤ 60 s | pending | pending |
| Commit immediately after a completed fallback poll: commit to visible | ≤ 60 s | pending | pending |

## 7. UX, AI and worker evidence

| Area | Reference | Result |
|---|---|---|
| Sync status, conflicts and recovery journeys | `evidence/apple-ux.md`, `evidence/mac-ux.md` | pending |
| iPhone AI (Q09) | `evidence/iphone-ai.md`, `evidence/ai-consent.md` | pending |
| Mac AI (Q09) | `evidence/mac-ai.md`, `evidence/ai-consent.md` | pending |
| Worker lease expiry, old/new fences (Q08) | server run | pending |
| Keyboard and VoiceOver reachability of recovery actions (Q12) | per client | pending |
| Representative user completes the three journeys without coaching or files (Q12) | per client | pending |

## 8. Exact-SHA OFF / pilot / recovery results

| Phase | What is checked | Result at the exact SHA |
|---|---|---|
| OFF (capability OFF by default) | complete Apple/server path works; no new exposure; all writers and durable job fencing confirmed before enrollment | pending |
| Pilot (explicit internal scope) | effective capability, schema epoch and SHA read back; Q01–Q12 and sections 5–6 run | pending |
| Recovery | enrollment removed stops new exposure and never switches a migrated queue back to an incompatible writer; restore of a disposable backup behind closed access with control decisions replayed; lost acknowledged commits reported explicitly | pending |
| Disaster objectives (proposed, synthetic workload) | RPO ≤ 24 h; RTO ≤ 4 h | pending |

PostgreSQL cutover is out of scope for this evidence and needs its own ASK authorization.

## 9. Verdict

Not reached. Missing hardware, a failed recovery, a missed performance, RPO or RTO target, or an
incomplete write inventory blocks expansion. Overall result: **pending**.
