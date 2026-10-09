# Protocol requirements quality

**Purpose**: peer review of the completed planning requirements, not a product test result.
**Created**: 2026-10-09. **Feature**: [spec.md](../spec.md).

Reviewer-owned checklist: a checked item means its written requirements satisfy the quality criterion. It does not mean software is implemented or approved for release. Evaluate against the same artifact revision as the formal review; preserve any reported gap in verification evidence.

## Completeness and consistency

- [ ] CHK001 Are local success, server acceptance, no-op, unknown outcome and feed confirmation distinguished without conflicting state transitions? [Consistency, FR-001/005/006; sync-v1 §§3–7/11]
- [ ] CHK002 Are command identity, dependencies, legacy aliases and post-reset intake specified without rekeying uncertain work? [Completeness, FR-005/010/013; command-catalog; data-model]
- [ ] CHK003 Are every current writer and all public Review projections assigned to one authoritative transaction boundary? [Coverage, FR-014/016; command-catalog; data-model]
- [ ] CHK004 Are existing large atomic operations covered without a new product-size limit or partial visibility? [Consistency, FR-006/009/014; sync-v1 §§6/11]
- [ ] CHK005 Are response/feed/snapshot/transfer/backup retention and purge rules consistent with source content limits? [Consistency, FR-022; data-model; ADR proposal]
- [ ] CHK006 Are workspace/session/restore generations, permissions, stale responses and worker fences defined at their boundaries? [Coverage, FR-010/011/015; sync-v1 §§4/7/9]

## Measurability and delivery

- [ ] CHK007 Are performance and recovery objectives tied to hardware, workload, sampling and an observable pass/fail condition? [Measurability, SC-003/004/007; quickstart]
- [ ] CHK008 Are affected UX states, account-switch choices, focus behavior and recovery outcomes specified and mapped to requirements? [Coverage, FR-003/007/010/023; design]
- [ ] CHK009 Are local AI availability, denied/revoked consent, proposal confirmation and AgentRun separation consistent? [Consistency, FR-018–021; runtime-ffi; design]
- [ ] CHK010 Does every FR/SC have a bounded task/slice, and do dependencies place job fencing, all-writer coverage and safe migration before enrollment? [Traceability, tasks; plan §7/9]
- [ ] CHK011 Are factual code baselines, proposed new paths, future platform scope and unmeasured implementation outcomes clearly distinguished? [Clarity, research; spec Assumptions; quickstart]
- [ ] CHK012 Are pending human/governance decisions explicit and separate from technical completeness and product acceptance? [Clarity, approval; ADR proposal; verification]
