# Cross-artifact analysis: RTM task-management parity

**Feature**: `specs/011-rtm-task-parity/` | **Repair date**: 2026-08-15
**Scope**: Task-0 campaign-1 repair across `intake.md`, `research.md`, `spec.md`,
`capability-matrix.md`, `design.md`, `plan.md`, `checklists/requirements.md`, `tasks.md`,
`p2-decisions.md`, ADR-0020 and `review-history.md`. No product code/test was changed.

## Method

- Extract FR/SC definitions and detect duplicates, gaps and malformed zero-padding.
- Trace every FR/SC into `design.md` and `tasks.md` (contract-only requirements may be
  listed under design's no-affordance section).
- Recount every C-01…C-70 row from the matrix itself.
- Reconcile every campaign-1 blocking/important/advisory finding through the digest-visible
  disposition table in `research.md`.
- Verify repository claims against task repository/service/domain, account export/purge,
  retention docs and observed/enforced mutation scope.
- Keep product decisions HD-01…HD-09 distinct from HD-10 run/digest sign-off.

## Mechanical results after repair

| check | result |
|---|---|
| FR definitions | 39, `FR-001`…`FR-039`, unique, contiguous, zero-padded |
| SC definitions | 15, `SC-001`…`SC-015`, unique, contiguous, zero-padded |
| Capability rows | 70, `C-01`…`C-70`, unique and contiguous |
| Every FR in design | 39/39 through a screen/backend row or no-affordance inventory |
| Every FR in tasks | 39/39 through the full P0 outcome map and owning tasks |
| Every SC in tasks | 15/15 through task acceptance references |
| Preflight markers/placeholders | none |
| Requirements checklist | fully verified/checked; no claim of implementation readiness |
| Absolute machine-local paths in feature artifacts | none |

## Product decisions

Max resolved HD-01…HD-09 on 2026-08-15. `intake.md` records decision, date, rationale and
consequence. ADR-0020 narrowly supersedes ADR-0006 on public priority values/order and List
archive membership. No P1/P2 item moved into P0 and no P0 capability was removed.

HD-10 is intentionally not resolved: campaign 2's run ID and artifact digest do not exist
until preflight. The founder answers are not a substitute for an ADR-0012
`human-signoff.json` and are not represented as founder acceptance.

## Campaign-1 repair completeness

`research.md` carries all 39 campaign-1 findings with stable C1-B/I/A IDs:

- **15/15 blocking resolved** in the planning package;
- **18/18 important explicitly dispositioned**, all resolved rather than silently deferred;
- **6/6 advisory carried**, five repaired directly and the operational-evidence item raised
  into required SC-014/T-020 evidence.

The central corrections are:

1. truthful planning/gate status and phase-qualified priority acceptance;
2. Max's restore/retention/name-erasure/idempotency/design decisions;
3. FR-037/SC-012 durable IDs/action/time-only audit with export/account-purge ownership;
4. repository-relative embedded source provenance in `research.md`;
5. accurate SQLite JSON payload, scalar index, normalized membership, JSON mirror and
   migration-ledger topology;
6. archived-member PATCH/name/filter behavior, delete replay without resurrection,
   trashed-task guards, and exact exclusion/count predicates;
7. complete P0 idempotency/owner/correlation/cache/order/pagination/export/cross-tier/mobile
   real-backend evidence;
8. observed-vs-enforced mutation-tier correction and qualified `[P after …]` dependencies;
9. exact UI copy plus keyboard/VoiceOver/TalkBack entry, announcement and focus restoration;
10. named ownership for API compatibility, retention and in-app privacy documentation.

## Persistence and rollback consistency

The repaired artifacts agree that tasks are Pydantic documents serialized into SQLite
`payload` JSON, not one SQL column per field. Due/start/Trash use backward-compatible JSON
defaults. Priority stage 2 rewrites canonical SQLite payloads and regenerates every task
mirror; a content-free ledger makes interruption resumable. Rollback disables numeric
default responses, applies the inverse mapping, rebuilds/verifies mirrors, and only then
permits an older image.

List/Tag/task erasure acknowledges success only after canonical SQLite mutation, redacted
audit/idempotency result and compatibility mirror absence/read-back are reconciled. Replay
returns a redacted receipt and never passes through resource-reconstruction helpers.

## Scope and denominator

The canonical RTM P0 gap denominator remains exactly 12: C-09, C-10, C-11, C-12, C-14,
C-25, C-26, C-36, C-38, C-39, C-55, C-56. C-14/C-47 are one capability. C-46 moves from
PASS to PARTIAL because its current delete retains a name-bearing deleted row; this is
HD-06 privacy completion work, not a newly invented RTM gap. Matrix totals are now 38 PASS,
6 PARTIAL, 2 DIVERGENT and 24 ABSENT.

P1 and P2 are frozen. Explicit permanent deletion/Empty Trash is the selected HD-05
retention endpoint of the already-in-scope Trash capability, not a new unrelated feature.
No automatic purge, reminder, timezone promise, RTM integration, collaboration, attachment,
automation sandbox or agent-state coupling was added.

## Dependency and evidence consistency

The dependency chain is contract-first:

```text
T-000/T-002
  -> Slice 1 backend audit/archive/delete/Trash substrate
  -> Slice 1 web + mobile
  -> Slice 1 cross-tier/mobile-real-backend gate
  -> Slice 2 priority stage 1
  -> dual-reader web + mobile
  -> Max-owned installed-build evidence
  -> priority stage 2 (then separately gated stage 3)
  -> Slice 2 cross-tier/mobile-real-backend gate
  -> Slice 3 predicates/order/cursors
  -> Slice 3 web + mobile + real-backend gate
  -> docs/rendered evidence/full verify
```

No client task is parallel with an unfinished backend contract; no Playwright/real-backend
journey precedes both clients. `repository.py` is in the ADR-0016 observed task scope only;
no task module is in the enforced mutation list.

## Readiness

The artifacts are ready for campaign 2 preflight and six-lens review. They are **not ready
for implementation**. Campaign 2 is the hard final campaign. If its technical findings are
clean but HD-10 remains absent, the terminal status is `escalated`, and the exact residual
human action is review of campaign 2's run-bound digest followed by a real sign-off record
or an explicit decision not to sign.
