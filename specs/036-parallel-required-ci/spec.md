# Feature Specification: Parallel required CI
**Branch**: codex/parallel-ci. **Created**: 2026-10-17. **Status**: Founder-accepted planning; implementation pending.

## User Scenarios & Testing
### Story 1 - Faster complete queue verdict
The repository owner receives the same complete required verification sooner by using independent runners. Test the actual merge-group execution, not merely a workflow graph.
Acceptance scenarios:
1. Given a full landing run, the backend partitions execute disjoint complete portions of the collected suite; their union equals the original collection and merged coverage clears the unchanged floor.
2. Given a nonempty enforced mutation scope, two partitions cover that complete scope; the existing aggregate score and base comparison judge combined counts. Missing, corrupt, overlapping, interrupted or wrong-SHA evidence fails closed. An intentionally empty partition is accepted only when its declared assigned scope is empty.
3. Given affected iOS inputs, app/widgets build for iOS Simulator and the whole package suite builds/tests on macOS concurrently; both outcomes remain required.
4. Given any failed/canceled/missing shard or native job, Full CI cannot pass. Existing diagnostic evidence remains available on failures.
5. Given successful delivery, report exact reviewed/tested/landed SHAs, before/after whole queue duration (including Allure), lane timings, counts and runner/cache differences.

## Requirements
- **FR-001**: Partition the existing selected-or-full backend collection into exactly two deterministic disjoint parts, run every assigned case with existing xdist behavior, and prove complete execution against collection/assignment manifests and JUnit counts.
- **FR-002**: Combine both raw coverage databases before the unchanged full-suite floor and main test-impact map generation. Preserve the existing PR-only selected-test semantics, Allure taxonomy/results, base-floor comparison and canonical coverage/Allure artifacts.
- **FR-003**: Partition both head and applicable PR-base mutation measurements into two independent complete scope parts; combine validated raw counts rather than averaging scores, then invoke the existing mutation gate unchanged. Preserve no-tests/zero-checked failure, threshold 95%, base regression comparison, summaries, survivors, raw state and blocking-gate Allure evidence.
- **FR-004**: Split ios-app and a new ios-tests job, both using the existing ios path decision, platform/toolchain and exact bridge cache identity. Keep app/widgets build and complete swift test --parallel, with both required by Full CI and final Allure aggregation.
- **FR-005**: Require every partition, coverage aggregation and native job. Missing/wrong-SHA/overlapping evidence must fail. Preserve all other checks, secrets/permissions, retention expressions, protections, release authority and product code.
- **FR-006**: Obtain independent frozen PR-head review before enqueue and real exact-tested queue/main evidence under the recorded Spec 036 exception, compare complete test/mutant sets and total queue elapsed time, and report concurrency/cache/runner limits without claiming a fabricated speedup.

## Success Criteria
- **SC-001**: Executed backend assignments form the exact collected suite; all existing applicable tests, combined coverage and taxonomy pass on the queued SHA.
- **SC-002**: Combined mutation scope and mutant identities are complete/disjoint, the existing gate passes on aggregate head/base stats, and native app/package verification both pass.
- **SC-003**: Real merge-group wall time is measured against a warm pre-change baseline; report absolute and relative differences. If no improvement is observed, investigate the critical path before declaring acceleration achieved; no arbitrary hard timing threshold.

## Clarifications
The owner authorizes complete backend/mutation and parallel iOS verification, extra concurrent runners, CI and queue delivery. On 2026-10-17 Max explicitly selected “Разрешить исключение для этой задачи” in response to the fresh one-task exception question. This covers only this baseline and implementation PR, expires 2026-10-19, and permits independent frozen PR-head review before ordinary queue entry while the generated merge-group SHA is fully tested and verified at landing. The reviewed PR-head SHA may differ from that tested/landed queue SHA. Preserve protections, all checks, secrets and product code. See founder-acceptance.json for waived ADR-0008 mechanics, compensating measures and true campaign history; spec035 approval is not reused. Broader governance repair is outside scope.
