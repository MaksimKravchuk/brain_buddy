# Requirements Checklist

**Purpose**: quality gate for [spec.md](../spec.md) itself — is it written well enough to build from and to accept against?
**Created**: 2026-08-14 · **Revised**: 2026-08-14 (post-campaign-2 regrade — both product decisions and every verified campaign-2 finding are now fixed directly in spec.md/plan.md/tasks.md; none re-reviewed by a fresh panel, since the two-campaign cap forbids a third one, so the package's recorded verdict stays `product-decision-required` under founder acceptance regardless — see [review-history.md](../review-history.md)'s Post-campaign disposition and Founder acceptance sections)
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) · [design.md](../design.md) · [tasks.md](../tasks.md) · [analysis.md](../analysis.md) · [review-history.md](../review-history.md)

Every box grades **planning quality only** — no code exists; this feature is unimplemented by design. A box is ticked only where true of the artifacts on disk right now. Every link is relative to this file's own directory (`checklists/`).

## Scope

- [x] The spec states exactly **10** functional requirements (010-FR-001…010) and **8** success criteria (010-SC-001…008), each tracing to the founder's frozen slice in [intake.md](../intake.md) or to a Derived Decision.
- [x] The six behaviours the slice names — mode control, exact-lookup cohort membership, the durable overlay, the single resolver, live propagation, the operator screen's states — each have ≥1 requirement, and no requirement serves none of them.
- [x] Requirements an earlier planning pass invented are gone, not renamed: no CLI reset, no cohort sweep beyond DD-9's purge call, no privacy-summary rewrite, no new audit schema/store/UI, no deploy byte-equivalence assertion, no rollback machinery beyond SC-003's two claims — each named in spec.md's Out of Scope section.
- [x] The founder's original out-of-scope list is preserved and extended, never narrowed; the two narrow campaign-1 reopenings (DD-9's purge/retention edit, DD-10's audit log lines) are named exceptions with their own boundary.
- [x] spec.md and plan.md's Risks section both state that reviewer suggestions cannot expand the cap or reopen the frozen slice beyond the owner decisions.

## Clarity

- [x] Every requirement (010-FR-001…010) is testable and names an observable behaviour. **Fixed**: campaign 2's three blocking contradictions — the mode-model/`internal` conflict, the clear-override cohort mutual exclusion, and the audit-cardinality/`find_account` conflict — are resolved by DD-3's three-field split and DD-10's "exactly one *new* record," none re-reviewed by a fresh panel (review-history.md).
- [x] The three override modes are named exactly as the founder named them (OFF/ON/SELECTED_USERS) plus one explicit inheritance action ("Use deploy default", DD-3); no fourth mode, percentage or rule expression appears anywhere.
- [x] "Which flags are runtime-manageable" is disambiguated: DD-1 pins it to the two flags and gives a repository-grounded reason for each exclusion — corrected post-campaign-2 to acknowledge `external_agent_relay_enabled`'s existing per-request gate and ground the exclusion in `_build_agent_secret_box`'s construction-time check instead.
- [x] The thirteen points the brief and both campaigns left unsettled are decided in spec.md (DD-1…DD-13), each traced to a brief sentence, a repository fact, or a named finding — DD-12 and DD-13 close the confirmation-rule traceability gap and the degraded-document purge question, neither re-reviewed by a fresh panel.
- [x] The one added surface is stated explicitly with stable ids `F-01`…`F-13` ([design.md](../design.md)), distinguished from feature 009's `D-` ids; `F-13` is distinguished explicitly from `F-11`.
- [x] The propagation mechanism is specified as an observable contract — 15s/focus/visibility, no polling while anonymous/hidden, no WebSocket/SSE, transient tolerance via `refreshSession()` distinct from initial hydration (DD-11) — not as "the client stays in sync."

## Coverage

- [x] Every FR has ≥1 task naming it in [tasks.md](../tasks.md); every SC has a named executable observation, not a documentation edit standing in for evidence. **Fixed**: campaign 2's five evidence gaps — save-failure (**C3a**), degraded-store field shape (**A4**), 390×851/focus (**D1a**), poll-recovery (**E2**/**E7**), and Lane A's dependency inversion (assertion moved to **C8**) — are all closed, none re-reviewed by a fresh panel.
- [x] Traceability is written out per requirement in [analysis.md](../analysis.md). **Fixed**: its FR-007 row now correctly cites `AdminService.find_account` for the add lookup only, not the cohort-email `GET` read (`FeatureFlagService.describe()`'s `UserRepository.get_by_id` job, per **C9**).
- [x] The failure mode motivating the feature (rollout state can only move via an ASK-class workflow edit plus a full release) is covered by executable checks: SC-001 (stored mode), SC-002 (member-visible effect), SC-004 (propagation).
- [x] The compatibility claims are evidenced, not just asserted in prose: SC-003 pins an older image ignoring the document, the current image falling back when absent, and the first-mutation-creates-the-document case (DD-2).
- [x] Concurrency/durability claims each have an observation: SC-005 (atomicity, idempotence, unknown-entry preservation), SC-001 (restart survival, proven at the application boundary by **C7**, not only the repository object), SC-008 (degraded document). **Fixed**: DD-9 widened so `scrub_user` reaches any parseable entry (**A6**); DD-8 separately names an unrecognized field, a declared-but-unmanaged entry and an out-of-vocabulary `mode` (degraded, not preserved); "byte-for-byte" softened to "value-intact under this build's canonical serialization"; **A4** now covers malformed known entries and injected read errors.
- [x] FR-008's "every existing flag check for the two managed flags" is checkable: plan.md enumerates call sites by file/line and states which `KNOWN_FEATURE_FLAGS` sites are deliberately untouched and why; **B8**/**B10** assert both. **Fixed**: the third call site, `backend/app/api/tasks.py:340` (`command_brain_dump_operation`), missed pre-campaign-2, is now named and routed.
- [x] No task is ticked — the feature is unimplemented, and a ticked box here would be the exact flattering-checklist defect feature 009's campaign 1 found.

## Consistency

- [x] The mode vocabulary matches across spec.md/design.md/plan.md (`off`/`on`/`selected_users`, plus the separate `clear_override` operation). **Fixed**: campaign 2's two blocking contradictions — inherited `internal` forced into the mode schema, and `clear_override`'s cohort outcome disagreeing between DD-3 and tasks.md's old C3 — are resolved by the three-field split and by correcting **C3** to match DD-3; not re-reviewed by a fresh panel.
- [x] Every `010-FR-`/`010-SC-` reference in design.md/plan.md/tasks.md resolves to a requirement that exists in the spec; no citation points at a deleted id.
- [x] The changed-surface table in [plan.md](../plan.md) names symbols and paths that exist in the repository today, or marks the file **NEW**. **Fixed**: campaign 2 found the table omitted `backend/app/api/tasks.py:340` and mischaracterized `external_agent_relay_enabled` as construction-time-only; both corrected, not re-reviewed by a fresh panel.
- [x] The lookup contract is inherited, not restated: FR-007 points at 009's exact-match semantics for adding and separately states idempotent semantics for removing (DD-7); design.md points at 009's client classification contract for the add form.
- [x] No requirement contradicts an accepted ADR without resolving it: ADR-0008's "flags are exposure control, never authorization" is re-asserted by FR-006; ADR-0017's "no admin data store" is narrowed by ADR-0018 (**G1**), and its audit condition is satisfied by FR-006/DD-10. **Fixed**: `docs/auth.md` now gets the missing third-authority bullet (**G3**); **G1** records the ADR-0017 §4 narrowing for the bulk cohort-email read.
- [x] The feature 009 contracts this package preserves are named by requirement id where preserved (009-FR-001, 002, 003, 005, 006, 008, 010, 011, 013, PD-1), not referred to collectively.

## Risk

- [x] The self-lockout hazard is closed by DD-1/FR-002 structurally, not left to operator discipline.
- [x] The deploy-gate hazard (managing `delivery_canary` could durably fail the production release smoke) is closed structurally: `delivery_canary` is not a managed flag (DD-1), so no runtime entry for it can ever exist.
- [x] The rollback story is structural: a pre-010 image cannot read the document; the current image falls back when absent and creates it on the first mutation (SC-003, DD-2). **Fixed**: DD-8 now names each of the three rollback-produced states explicitly (unknown fields, unrecognized modes, unmanaged entries), and **A4** tests the distinction; not re-reviewed by a fresh panel.
- [x] The single-process serialization assumption is written down in spec.md Assumptions and named as a risk in plan.md. **Fixed**: plan.md's Risks section now describes the real Fly failure mode (per-machine divergence, not a shared-document interleaving race impossible on Fly's single-attach volumes); advisory severity, not re-reviewed by a fresh panel.
- [x] The purge question is answered, not assumed: DD-9 requires `purge_account` to scrub a purged ID from every managed flag's cohort, mirroring `InviteRepository.scrub_user`. **Fixed**: DD-9 widened to any parseable entry (**A6**), and new DD-13 resolves the FR-004/DD-9 collision on a degraded document as halt-and-retry (**A6**, **C10**, **C11**) — closing product decision #2 in [review-history.md](../review-history.md); neither fix re-reviewed by a fresh panel.
- [x] The residual after DD-9 — a one-row addition to `docs/data-retention.md` (**G2**) rather than a full retention audit — is stated openly in plan.md. **Fixed**: G2 now names DD-10's record types explicitly; the privacy-policy-sync product decision is answered too (DD-9 authorizes one sentence, tasked as **G4**), mirroring 009's precedent; neither re-reviewed by a fresh panel.
- [x] The feature's risk class — **ASK/high** under ADR-0008 — is recorded with its triggers named to specific classifier rules and landing constraints in plan.md.
- [x] Manual acceptance uses purpose-seeded non-real accounts and requires redaction, so ASK-class PR evidence cannot carry a member's email or account id (constitution Principle I).
- [x] The planning-review status is recorded honestly in [review-history.md](../review-history.md), including both campaigns' full `product-decision-required` verdicts, the owner decisions and post-campaign corrections that resolved them, and the founder acceptance that closes the loop under the two-campaign cap — stated explicitly as acceptance of residual risk, not an `approved` verdict this package cannot currently earn.
