# Acceptance: shared Rust core and custom synchronization

> **Update after the code-only gap closure.** Blockers A1, A3, A4, A5 and A6 below are closed (marked CLOSED). A2 (real-backend Rust suites in CI) and A7 (Rust/Swift Allure output) need `ci.yml` or tooling changes and remain open. The verdict below is the auditor's, unchanged: the pilot run, PR-55/56/57 and the device UX evidence are still outstanding, and a re-grade belongs to the auditor.

**VERDICT**: reject
**Feature**: `specs/026-rust-core-sync/`
**Graded**: 2026-10-14  **Implementation SHA**: 3764dfc6a5dd82eaafb3226d3259be143f0c5d85 (`origin/main`)
**Auditor**: `acceptance-auditor` (did not write the code under grade)

Writer-owned pre-freeze evidence is a separate artifact validated by
`scripts/validate_pre_freeze_receipt.py`; this post-freeze acceptance verdict
must not substitute for it. Review, QA, CI, landing, deploy, and smoke are
post-freeze obligations under ADR-0008.
<!-- BrainBuddy pre-freeze receipt contract: acceptance. Preserve this section. -->

The spec defines the first acceptance boundary as iOS ↔ server ↔ macOS plus the post-pilot PostgreSQL migration (spec.md Clarifications). The feature is rejected for three reasons:

- The reference-device pilot (T054 / PR-54 run) has not been executed.
- PR-55/56/57 have not landed.
- Several gaps can be closed now, without devices or PostgreSQL. They are listed under Blockers, group A.

## Tally

| | count |
|---|---|
| criteria total | 54 (26 FR, 8 SC, 20 acceptance scenarios) |
| covered | 36 as graded; US5-AS4 now covered |
| weak | 0 (US5-AS4 closed) |
| missing | 0 (026-SC-008 now has model-level tests; the device part stays pending) |
| PostgreSQL-pending | 11 (FR-005/006/010/011/013/014/015/022, SC-002/005/007) |
| device-evidence-pending | 4 (FR-018, FR-023, FR-026, SC-003) |
| rehearsal-only | 1 (SC-004) |
| hollow tests found | 3 classes (below) |

Full matrix: `traceability.md`

## Blockers

### A. Closable now (no devices, no PostgreSQL)

1. **CLOSED: 026-SC-008**: no test named it, so `check_requirement_coverage.py specs/026-rust-core-sync` fails (33/34).
   - Would satisfy it: tag the automatable part with 026-SC-008. That is the state-to-design mapping in `SyncPresentationTests`, `RustSyncRecoveryTests` (macOS) and `ConflictDecisionWiringTests`, plus accessibility-label and keyboard-reachability assertions for the recovery actions. The representative-user and VoiceOver part stays device-pending.
2. **Real-backend Rust suites pass vacuously in CI.** The CI step `cargo test --locked` sets neither `BB_BACKEND_PYTHON` nor `BB_REQUIRE_BACKEND=1`. As a result, the 25 tests in `bb-client/tests/{protocol_faults,e2e_backend,hints_backend}.rs` return early and report green. Their last real run was at cf28db8d. HEAD has since changed `storage.rs`, `transport.rs`, `projection_cache.rs` and others.
   - Would satisfy it: the Rust core job builds the backend environment plus `bb_core` and runs these suites with `BB_REQUIRE_BACKEND=1`. `ci.yml` is guarded, so re-record the hash with `check_gate_integrity.py --update`. At minimum, record a real run at the exact HEAD SHA.
   - Recorded real run (conductor, 2026-10-14, MacBook Air M4, local backend) at 3764dfc6: `BB_REQUIRE_BACKEND=1 cargo test -p bb-client --test protocol_faults --test e2e_backend --test hints_backend -- --include-ignored` → protocol_faults 16 passed, e2e_backend 9 passed, hints_backend 3 passed; 0 failed, 0 ignored (28 tests: the three added with the Q01b refusal fixes included). The CI wiring itself stays open (ASK: workflow change).
3. **CLOSED: US5-AS4**: no 026 test checks that a *completed* AgentRun leaves the Task unchanged until a confirmed Tasks command.
   - Would satisfy it: add `test_026_FR_021_a_completed_run_leaves_the_task_unchanged_until_confirmed` in `test_agent_job_handoff.py`.
4. **CLOSED: mislabelled ids.** `park_026_sc_006_*` is now `park_026_fr_016_*`; `test_026_FR_021_*` in `test_rust_core_holder.py` is now `test_026_FR_002_*`.
   - `rust/crates/bb-domain/tests/park_parity.rs::park_026_sc_006_*` (4 tests) test auto-park, not AI consent.
   - `backend/tests/test_rust_core_holder.py::test_026_FR_021_*` (6 tests) test the runtime holder, not AgentRun separation.
   - Would satisfy it: relabel them to the right ids (FR-016, FR-002/FR-025).
5. **CLOSED: SC-003 harness had no budget assertion.** The ignored run now asserts p95 against `BB_SC003_P95_BUDGET_MS` (default 50). `perf_026_sc_003_ten_thousand_tasks_thirteen_hundred_outbox_rows` is `#[ignore]` and only prints percentiles.
   - Would satisfy it: make the device harness emit a machine-checkable p95/stall verdict that the pilot run can record.
6. **CLOSED: `tasks.md` was stale.** T001-T053 and T058-T064 are now ticked after checking the files each names; T054-T057 stay open. Only T041 and T047 are checked; 62 of 64 are unchecked. In reality T001–T053 and T058–T064 have landed (for example `sync/delta.py`, `sync/restore.py`, `jobs/worker.py` and both `ReviewSuggestionSheet.swift` files). Only T054 (pilot run) and T055–T057 (PostgreSQL) are genuinely open.
7. **Rust and Swift results emit no Allure output.** About half of the 026 evidence never reaches the graded Allure report. This is not a constitutional violation (the taxonomy rule names pytest, Vitest and Playwright), but it is a traceability weakness.

### B. Needs reference devices (iPhone 11 / iOS 26, MacBook Air M1 / 8 GB / macOS 26)

8. `evidence/apple-pilot.md` Q01–Q12 plus §5 SC-003, §6 SC-004, §8 OFF/pilot/recovery. All are `pending`.
9. `apple-ux.md`, `mac-ux.md` (FR-023, design M-/D- states, SC-008), `iphone-ai.md`, `mac-ai.md`, `ai-consent.md` (FR-018/019, Q09). All are `pending`. Note: rehearsal S4 Findings 1–3 and 5 were fixed in 3764dfc6 but have not been re-observed in the UI.

### C. Needs PostgreSQL (PR-55/56/57)

10. `postgres.py` transaction-fixture parity (PR-55). `migrate_postgres.py` rehearsal with recorded RPO/RTO in `recovery.md` (PR-56). `evidence/postgres-cutover.md` (PR-57). Together these cover FR-005/006/010/011/013/014/015/022 and SC-002/005/007.

## Evidence

The CI artifacts come from run 38530856766 at 3764dfc6, downloaded and re-validated by the auditor.

| check | command | result |
|---|---|---|
| product-e2e stories | `validate_ci_artifacts.py product-e2e-results` | pass (93 results, 6 stories) |
| result freshness | `validate_ci_artifacts.py results --since-file` (marker = commit time 07:20:08Z) | pass for backend, frontend and playwright. Fail for the Rust real-backend suites (last real run at cf28db8d) |
| allure taxonomy | `validate_allure_taxonomy.py` | pass (backend 6193, frontend 2784, playwright 94) |
| requirement coverage | `check_requirement_coverage.py specs/026-rust-core-sync` | **fail**: 026-SC-008 (graded); pass 34/34 after the closure |
| backend coverage | enforced by the CI Backend job (green); not independently recomputed | pass (CI) |
| frontend coverage | enforced by the CI Frontend job (green) | pass (CI) |

There are 1139 backend and 111 frontend Allure results with 026 ids, all passed. There are none in Playwright.

## Measured criteria

| criterion | target | measured | source | tier |
|---|---|---|---|---|
| SC-003 | p95 ≤ 50 ms, stall < 100 ms on iPhone 11 / M1 | 32.0 ms p95 on M4 (not reference); stall not measured | rehearsal-2026-10-14.md | INTERNAL floor not met (no reference measurement) |
| SC-004 | p95 ≤ 2 s; ≤ 60 s lost hint; polls ≤ 30 s | 0.256 s p95 on M4 loopback, no RTT shaping; fallback not driven | rehearsal-2026-10-14.md S3 | INTERNAL floor not met |
| SC-005 | reference dataset import lossless | Simulator/M4 field-by-field PASS; devices pending | rehearsal S3 Q06 | not met |
| SC-008 | users complete journeys uncoached | not measured | — | not met |

No criterion is voice-related, so `voice_evidence_report.py` does not apply.

## Design state coverage

| design state id | tested by | status |
|---|---|---|
| M-01 / D-01 status | `SyncPresentationTests.swift`, `WorkspaceSyncStatusPresenterTests.swift`, `RustSyncFailurePopoverTests.swift` | model covered; device rows pending |
| M-02 / D-02 conflict | `ConflictDecisionWiringTests.swift`, `RustSyncRecoveryTests.swift` | model covered; device rows pending |
| M-03 / D-03 recovery | `ConflictDecisionWiringTests.swift::"026-FR-010: the recovery card words update-needed…"` | model covered; device rows pending |
| M-04 / D-04 AI sheet | `ReviewSuggestionModelTests.swift`, `macos/…/ReviewSuggestionTests.swift` | model covered; iPhone sheet UI only in non-CI rehearsal UITests; device rows pending |

None of these has a waiver. The 110 screen-state combinations are verified only through the pending device documents.

## Spot-checked for hollowness

| test | would it still pass with the feature deleted? |
|---|---|
| `bb-client/tests/protocol_faults.rs` + `e2e_backend.rs` + `hints_backend.rs` (25 tests) in CI | **YES**: `support::start_with` returns `None` without `BB_BACKEND_PYTHON`, and the test returns before any assertion |
| `park_parity.rs::park_026_sc_006_a_device_park_after_a_sweep_gap_applies_the_floor_first` | **YES for SC-006** (it tests auto-park); it is real for FR-016 |
| `test_rust_core_holder.py::test_026_FR_021_a_healthy_holder_keeps_one_runtime` | **YES for FR-021** (runtime holder identity) |
| `test_rust_ai_policy.py::test_026_SC_006_a_core_denial_stops_the_request_before_any_provider_call` | no: asserts 400 and `provider.calls == 0` |
| `test_agent_job_handoff.py::test_026_FR_021_observation_reads_the_agent_and_never_sends_or_edits_a_task` | no: asserts no SendMessage and unchanged titles |

## Waivers

| criterion | why it is not tested | approved by |
|---|---|---|
| — | none requested; the auditor cannot waive | — |
