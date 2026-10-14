# Migration requirements quality checklist: Rust server (027)

**Purpose**: unit tests for the requirements text of a whole-server port with
a single destructive cutover. Reviewer-owned; `[x]` means the requirement text
is judged complete and unambiguous, not that anything is implemented.
**Created**: 2026-10-14
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md)
**Focus**: parity contract, cutover and data safety, privacy/retention,
client compatibility. Audience: reviewer before `/speckit-tasks` and the
acceptance auditor.

## Parity contract completeness

- [ ] CHK001 Does every capability-inventory section (HTTP, MCP, jobs, CLI, middleware, external, config, store) have a defined evidence kind? [Completeness, plan Phase A.2]
- [ ] CHK002 Are the criteria for "same behavior" between servers defined (status, body shape, headers, side effects), not just "tests pass"? [Clarity, Spec FR-001, research R4]
- [ ] CHK003 Is every `change` and `remove` disposition traceable to an explicit owner decision in spec Clarifications? [Traceability, Spec FR-001]
- [ ] CHK004 Is it specified how a defect discovered in the Python oracle during porting is handled (fix-first vs `change`) without violating FR-022? [Consistency, plan quirks policy]
- [ ] CHK005 Are the 17 inventory ambiguities each resolved to port/fix/remove with no item left implicit? [Completeness, plan quirks policy]

## Cutover and data safety

- [ ] CHK006 Is the stop-first order defined for both cutover and rollback, including how "stopped" is verified? [Clarity, Spec FR-019, research R10]
- [ ] CHK007 Is it unambiguous which actions are automatic in the release run and which require a separate ASK commit? [Consistency, plan F.2, research R10]
- [ ] CHK008 Are all copies of old production data (volume, snapshots, forks, off-platform copies) enumerated for the erase? [Completeness, research R10]
- [ ] CHK009 Is the point after which rollback is impossible stated in user-facing terms in the spec? [Clarity, Spec FR-019, US3]
- [ ] CHK010 Are migration compatibility rules after cutover specified with an objective check? [Measurability, research R12]
- [ ] CHK011 Is the restore protocol's fail-closed condition (ledger gap, unreadable entry) specified with an operator-visible outcome? [Edge case, research R11]
- [ ] CHK012 Are per-module post-restore rules defined for every module that holds external effects? [Coverage, research R11]

## Privacy and retention

- [ ] CHK013 Is every new durable record (pending signups, control ledger, cutover record, object-store audio) given retention, export and purge disposition? [Completeness, data-model]
- [ ] CHK014 Is "deletion complete" defined consistently across spec, data-model and docs/data-retention.md obligations? [Consistency, Spec FR-009]
- [ ] CHK015 Is server-side consent required on every provider path, and is late-result discard defined for each? [Coverage, Spec FR-011]
- [ ] CHK016 Are evidence and fixture hygiene rules specific enough to be checked mechanically? [Measurability, research R13/R15]

## Client compatibility

- [ ] CHK017 Is the gated/exempt route split complete against the inventory, with a rule for new routes? [Completeness, contracts/release-epoch.md]
- [ ] CHK018 Is the behavior of every pre-cutover client type (web tab, iPhone, Mac, CLI, MCP) at the new server specified? [Coverage, Spec FR-018]
- [ ] CHK019 Is the fresh-start trigger defined so that no pre-cutover data can reach the new server in any ordering of update, launch, foreground and sync? [Edge case, Spec FR-021, release-epoch]
- [ ] CHK020 Is the legacy artifact inventory defined as a checkable list with a coverage rule? [Measurability, data-model]
- [ ] CHK021 Are invite-step outcomes (invalid, expired, rate-limited, existing account) defined without revealing which codes exist? [Clarity, contracts/invite-handoff.md]

## Acceptance measurability

- [ ] CHK022 Can SC-005 be computed from the defined bench without interpretation? [Measurability, quickstart V7]
- [ ] CHK023 Is SC-007's reconciliation definition precise about what counts as lost or duplicated? [Clarity, Spec SC-007]
- [ ] CHK024 Are production pilot evidence fields (SHAs, builds, authorization receipts) specified? [Completeness, plan F.5]
- [ ] CHK025 Is every design screen/state id traced to a requirement and to a planned test? [Traceability, design.md, plan Phase D]
