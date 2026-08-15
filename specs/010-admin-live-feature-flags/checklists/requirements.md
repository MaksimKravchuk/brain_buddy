# Requirements Checklist

**Purpose**: quality gate for [spec.md](../spec.md) itself — is it written well
enough to build from and to accept against?
**Created**: 2026-08-14 · **Revised**: 2026-08-14 (campaign-2 regrade — campaign
2 closed `product-decision-required`, two product decisions left open and
several blocking/important findings unfixed), 2026-08-14 (post-campaign
regrade — both product decisions and every verified campaign-2 finding are now
fixed directly in spec.md/plan.md/tasks.md; none of that correction work was
re-reviewed by a fresh panel, because the two-campaign cap forbids a third
one, so the package's recorded verdict stays `product-decision-required`
under founder acceptance regardless — see
[review-history.md](../review-history.md)'s Post-campaign disposition tables
and Founder acceptance section for exactly what changed and what that
acceptance does and does not mean)
**Feature**: [spec.md](../spec.md) · [plan.md](../plan.md) ·
[design.md](../design.md) · [tasks.md](../tasks.md) ·
[analysis.md](../analysis.md) · [review-history.md](../review-history.md)

Every box grades **planning quality only**. None of them claims any code exists:
this feature is unimplemented by design. A box is ticked only where the
statement is true of the artifacts on disk right now. Every link in this file is
relative to this file's own directory (`checklists/`), so a sibling document is
`../name.md`, not `name.md` — campaign 1 found the prior revision's links broken
for exactly that reason.

## Scope

- [x] The spec states exactly **10** functional requirements (010-FR-001…010) and
      **8** success criteria (010-SC-001…008), and every one of them traces to a
      point of the founder's frozen slice in [intake.md](../intake.md) or to an
      owner decision recorded in spec.md's Derived decisions table.
- [x] The six behaviours the slice names — operator mode control, exact-lookup
      cohort membership, the durable overlay document, the single server-side
      resolver, live propagation, and the operator screen's states — each have at
      least one requirement, and no requirement exists that serves none of them.
- [x] Requirements an earlier planning pass invented are gone rather than
      renamed: no CLI reset command, no cohort sweep beyond the one purge
      integration DD-9 requires, no user-facing privacy-summary rewrite, no new
      audit-record schema/store/UI, no deploy byte-equivalence assertion, and no
      rollback machinery beyond the two claims in 010-SC-003.
- [x] Each of those removals is named explicitly in [spec.md](../spec.md)'s Out of
      Scope section, so a later reader can tell it was cut on purpose rather than
      forgotten, and a reviewer proposing it back has a written answer.
- [x] The original out-of-scope list from the founder's brief is preserved intact
      and extended, never narrowed — the two narrowly-scoped campaign-1 reopenings
      (DD-9's purge/retention-row edit, DD-10's audit log lines) are each named as
      exceptions with their own boundary, not silent expansions.
- [x] [spec.md](../spec.md) states that reviewer suggestions cannot expand the cap
      or reopen the frozen slice beyond the campaign-1 owner decisions, and
      [plan.md](../plan.md) repeats it in its Risks section, so the boundary
      survives a review round.

## Clarity

- [x] Every requirement is testable by a mechanical check or a real command; each
      of 010-FR-001…010 names an observable behaviour rather than an intention.
      **Fixed.** Campaign 2's requirements-consistency review found three
      blocking internal contradictions; all three are now resolved directly in
      spec.md: DD-3 carries a three-field split (`override_mode`/`source`/
      `deploy_default_state`) instead of forcing the inherited `internal` state
      onto a mode value; DD-3 and tasks.md **C3** now agree clear-override
      deletes the flag's entire runtime entry, cohort included; and DD-10
      clarifies "exactly one *new* record" so SC-006 no longer contradicts
      routing add through `AdminService.find_account`. None of the three fixes
      was re-reviewed by a fresh panel — see
      [review-history.md](../review-history.md)'s Post-campaign disposition
      table.
- [x] The three override modes are named exactly as the founder named them — OFF,
      ON, SELECTED_USERS — plus one explicit, separately-named inheritance action
      ("Use deploy default", DD-3) the founder's brief implied but never spelled
      out; the spec never introduces a fourth *mode*, a percentage, or a rule
      expression. **Fixed.** DD-3's three-field response split
      (`override_mode`/`source`/`deploy_default_state`) shows the
      deploy-default `internal` value in the source note as its own value,
      never mapped onto a mode, while `override_mode` is `null` and no radio
      is checked while inheriting — the contradiction campaign 2 found is
      resolved by the split, not by picking one side of it.
- [x] "Which flags are runtime-manageable" is disambiguated rather than assumed:
      DD-1 pins it to exactly `voice_brain_dump` and `mobile_task_classification`
      and states, with reasons tied to specific repository facts (the production
      smoke's read of `delivery_canary`, the construction-time-only
      `external_agent_relay` check), why the other two `KNOWN_FEATURE_FLAGS`
      entries and `admin_portal` are excluded. A later reader can tell each
      exclusion was decided, not forgotten. **Fixed.** DD-1's text now
      acknowledges `external_agent_relay_enabled`/
      `require_external_agent_relay_enabled` gates eight routes in
      `backend/app/api/agents.py` per request — the fact campaign 2 found
      DD-1 had denied — and grounds the exclusion instead in
      `_build_agent_secret_box`'s construction-time-only secret-box decision,
      which a request-time re-evaluation cannot retroactively satisfy. The
      exclusion itself was never wrong; only the stated reason was, and that
      reason is now corrected.
- [x] The thirteen points the brief and campaigns 1–2 together did not leave
      settled are decided in the spec (DD-1…DD-13), each traced to a sentence of
      the brief, a repository contract, or a named campaign finding, so no later
      review round has to re-derive them. **Fixed.** DD-12 (new) now carries the
      confirmation decision (owner decision 12) into the canonical table,
      closing the advisory traceability gap campaign 2 found; the two further
      product decisions campaign 2 raised — the privacy-policy sync question and
      the degraded-document purge disposition — are answered too, folded into
      DD-9 (widened) and DD-13 (new) respectively, rather than left open. None
      of DD-12/DD-13 was re-reviewed by a fresh panel; see
      [review-history.md](../review-history.md)'s founder acceptance for why
      that gap can't currently be closed.
- [x] The one surface this feature adds is stated explicitly, with stable state
      ids `F-01`…`F-13` an acceptance test can cite ([design.md](../design.md)),
      and the `F-` prefix is justified against feature 009's `D-` ids on the same
      screen. `F-13` is new in this revision and is distinguished explicitly from
      `F-11` (a failed request vs. a successful degraded response).
- [x] The propagation mechanism is specified as an observable contract — 15
      second interval, focus, visibility, no polling while anonymous or hidden, no
      WebSocket or SSE, a transient failure tolerated via a session-refresh path
      distinct from initial hydration (DD-11) — not as "the client stays in sync".

## Coverage

- [x] Every functional requirement has at least one task in [tasks.md](../tasks.md)
      that names it, and every success criterion has a named executable
      observation — a concrete test file plus a runnable checkpoint command —
      rather than a documentation edit standing in for evidence. **Fixed.**
      Campaign 2's testability-evidence review found five gaps, all
      now closed: new task **C3a** is the `TestClient`-level save-failure test;
      **A4** now covers a semantically malformed `mode` value and injected
      `OSError`/`PermissionError` read failures as degraded cases; new task
      **D1a** asserts the 390×851 reflow's 44px minimum and the confirm step's
      focus/Escape behaviour; **E2**/**E7** now advance a further interval
      after a transient poll failure and assert recovery; and Lane A's tasks
      (A1–A7) no longer assert `effective_flags()`/`describe()`-level behaviour
      that depends on Lane B — that assertion moved to **C8** — closing the
      blocking dependency inversion. A4 now pins the WARNING field shape and
      absence of member data; H2 requires the 390×851 checks in a real browser
      before landing. None of these post-campaign fixes was re-reviewed by a
      fresh panel; see [review-history.md](../review-history.md)'s
      Post-campaign disposition table.
- [x] The traceability is written out per requirement in
      [analysis.md](../analysis.md), so a missing or orphaned lane is visible
      without re-reading three artifacts. (Campaign 1 found this file did not
      exist while this box was already ticked; it now exists on disk, at the path
      this box names.) **Fixed.** analysis.md's FR-007 row cites
      `AdminService.find_account` for the **add** lookup FR-007/DD-9
      themselves require, not for the cohort-email read on `GET` — that read
      is `FeatureFlagService.describe()`'s job (FR-010), and plan.md's changed
      surfaces table and tasks.md's **C9** now agree it goes through a plain
      `UserRepository.get_by_id` read, closing the layering disagreement
      campaign 2 raised as blocking.
- [x] The failure mode that motivated the feature (rollout state can only move by
      an ASK-class workflow edit plus a full release, and never reaches an open
      session) is covered by executable checks: 010-SC-001 for the stored mode,
      010-SC-002 for the member-visible effect, 010-SC-004 for the propagation.
- [x] The compatibility claims are covered by evidence and not only by prose:
      010-SC-003 pins both halves — an older image ignoring the document, and the
      current image falling back to the environment baseline, including the
      newly-explicit first-mutation-creates-the-document case (DD-2).
- [x] The concurrency and durability claims each have an observation: 010-SC-005
      for atomicity, idempotence and unknown-entry preservation across a mutation
      (DD-8), 010-SC-001 for restart survival — proven at the application
      boundary by tasks.md's **C7**, not only at the repository object (a gap
      campaign 1 found and this revision closes) — and 010-SC-008 for the
      degraded document. **DD-8's preservation claim is fixed.** Campaign 2
      found two gaps, both now closed: DD-9 is widened so `scrub_user` reaches
      a `selected_users` array inside *any* parseable entry, declared or not
      (**A6**), closing the undeclared-flag-account-ID-survives-forever gap;
      and DD-8 now separately names an unrecognized field inside a known
      entry, a declared-but-unmanaged flag's entry, and an out-of-vocabulary
      `mode` value (treated as degraded per DD-2, not preserved) — "byte-for-
      byte" is also softened to "value-intact under this build's own canonical
      serialization," matching what the mechanism can actually guarantee.
      010-SC-008's degraded-document evidence now covers semantically
      malformed known entries and injected read errors too (**A4**; see the
      Coverage box above). None of this was re-reviewed by a fresh panel.
- [x] 010-FR-008's "every existing flag check for the two managed flags" is
      checkable rather than aspirational: [plan.md](../plan.md) enumerates the
      call sites by file and line and states explicitly which `KNOWN_FEATURE_
      FLAGS` call sites are deliberately *not* touched and why, and lane B's
      **B8/B10** assert both the managed-flag gate and the unmanaged flag's
      non-involvement. **Fixed.** Campaign 2's architecture-consistency and
      adversarial-high-risk reviews independently found a third
      `voice_brain_dump` call site, `backend/app/api/tasks.py:340`
      (`command_brain_dump_operation`'s direct check), missing from plan.md's
      "two call sites" claim and changed-surfaces table. FR-008, plan.md and
      tasks.md's **B8/B10** now name it explicitly and route it through the
      resolver alongside the other two.
- [x] No task is ticked. The feature is unimplemented, and a ticked box here would
      be the exact defect feature 009's campaign 1 found — a checklist that
      flatters the package.

## Consistency

- [x] The mode vocabulary in [spec.md](../spec.md), [design.md](../design.md) and
      [plan.md](../plan.md) matches the schema names the plan declares
      (`off` / `on` / `selected_users`, plus the separate `clear_override`
      operation), so the contract cannot drift between artifacts. **Fixed.**
      Campaign 2 found two blocking contradictions in this exact vocabulary,
      both now corrected: DD-3's inherited `internal` state is represented by
      the three-field `override_mode`/`source`/`deploy_default_state` split
      rather than forced into the mode schema, and `clear_override` is now
      specified one way everywhere — DD-3, FR-003, plan.md, tasks.md **A5**
      and the corrected tasks.md **C3** all agree it deletes the flag's entire
      runtime entry, cohort included. Not re-reviewed by a fresh panel.
- [x] Every `010-FR-` and `010-SC-` reference in [design.md](../design.md),
      [plan.md](../plan.md) and [tasks.md](../tasks.md) resolves to a requirement
      that exists in the spec; no citation points at a deleted id.
- [x] The changed-surface table in [plan.md](../plan.md) names symbols and paths
      that exist in the repository today — `require_admin_portal_enabled`
      (`backend/app/api/dependencies.py:240`), `voice_brain_dump_enabled`
      (`:278`), `external_agent_relay_enabled` (`:313`, named as **untouched**),
      `private_flag_effective` (`:259`), `_me_response`
      (`backend/app/api/auth.py:50`), `_voice_enabled_for_owner`
      (`backend/app/container.py:293`), `_build_agent_secret_box`
      (`backend/app/container.py:130`, named as **untouched**),
      `file_ops.atomic_write` (`backend/app/utils/file_ops.py:22`),
      `AdminService.find_account`, `InviteRepository.scrub_user`,
      `AccountService.purge_account` (`backend/app/services/account_service.py:377`),
      `adminKeys`, `bindAdminSession` — corrected to its actual location,
      `frontend/src/queryClient.ts:10`, not `main.tsx` (a campaign-1 factual-drift
      finding this revision fixes) — `useAuthStore.hydrate` — or marks the file
      **NEW**. **Fixed.** Campaign 2 found the table omitted
      `backend/app/api/tasks.py:340`, a third `voice_brain_dump_enabled` call
      site, and mischaracterized `external_agent_relay_enabled` (`:313`) as
      only a construction-time check when it actually gates eight routes in
      `agents.py` per request. The table now adds a named row for
      `backend/app/api/tasks.py` (edited alongside `dependencies.py` and
      `auth.py` to route through the service) and DD-1/the approach text
      correctly describe `external_agent_relay_enabled`'s existing per-request
      gate, grounding the exclusion in `_build_agent_secret_box`'s
      construction-time check instead. Not re-reviewed by a fresh panel.
- [x] The lookup contract is inherited, not restated: 010-FR-007 points at the 009
      exact-match semantics for **adding**, and separately states the idempotent
      semantics for **removing** (DD-7, a distinction campaign 1 found missing);
      [design.md](../design.md) points at the 009 client classification contract
      for the add form, so there is one add rule and one remove rule, not two
      copies of either that can diverge.
- [x] No requirement contradicts an accepted ADR without resolving it. ADR-0008's
      "flags are exposure control, never authorization" is re-asserted by
      010-FR-006; ADR-0017's "no admin data store" sentence is narrowed
      explicitly by the ADR-0018 planned in [plan.md](../plan.md) and tasked as
      **G1**, and ADR-0017's audit condition ("every operation is recorded") is
      now actually satisfied by 010-FR-006/DD-10 rather than asserted by a false
      Assumption (a campaign-1 finding this revision corrects). **Fixed.**
      Campaign 2's privacy-consent-security review found
      `docs/auth.md` still stated ADR-0017 bounds operator power to two
      operations; new task **G3** adds the missing third-authority bullet,
      pointing at ADR-0018. G1 also explicitly records that the bulk
      cohort-email read narrows ADR-0017 §4's per-operation audit clause to one
      aggregate count record, never one record per resolved account — see
      [review-history.md](../review-history.md)'s Post-campaign disposition
      table.
- [x] The feature 009 contracts this package claims to preserve are named by
      requirement id where they are preserved (009-FR-001, 009-FR-002,
      009-FR-003, 009-FR-005, 009-FR-006, 009-FR-008, 009-FR-010, 009-FR-011,
      009-FR-013, PD-1), not referred to collectively.

## Risk

- [x] The self-lockout hazard (managing the flag that gates the managing surface)
      is identified and closed by DD-1 / 010-FR-002 rather than left to operator
      discipline.
- [x] The deploy-gate hazard campaign 1 found — that managing `delivery_canary`
      would let a runtime override durably fail the production release smoke — is
      closed structurally, not by an accepted-residual note: `delivery_canary` is
      not a managed flag (DD-1), so no runtime entry for it can ever exist.
- [x] The rollback story is structural and stated: a pre-010 image cannot read the
      document, so an image rollback is a no-op for flag resolution, and the
      current image falls back to the environment baseline when the document is
      absent — and creates it on the first mutation rather than requiring a
      provisioning step (010-SC-003, DD-2). **Fixed.** Campaign 2's
      adversarial-high-risk review found DD-8's forward-compatibility carve-out
      was unspecified for three states a rollback produces: unknown fields
      inside a managed entry, unrecognized mode values, and declared-but-
      unmanaged flag entries. DD-8 now names each of the three explicitly —
      the first two preserved opaquely, the third (an out-of-vocabulary `mode`
      value) treated as degraded per DD-2 — and **A4** tests the distinction.
      Not re-reviewed by a fresh panel.
- [x] The single-process serialization assumption is written down in
      [spec.md](../spec.md) Assumptions and named as a risk in
      [plan.md](../plan.md), so scaling out is a deliberate decision rather than a
      silent correctness loss. **Fixed.** Campaign 2 found plan.md's Risks
      section described the scale-out failure as writers on different
      machines interleaving reads of one shared document — impossible on Fly,
      where volumes are single-attach and per-machine. plan.md's "The
      single-process assumption" risk paragraph now states the real failure
      correctly: each machine's flag document drifts from the others
      independently, and an operator's change lands on only whichever machine
      served the write. Advisory severity; not re-reviewed by a fresh panel.
- [x] The purge question is answered, not assumed: DD-9 requires
      `AccountService.purge_account` to scrub a purged account's ID from every
      managed flag's cohort, mirroring `InviteRepository.scrub_user`'s existing
      precedent, closing the erasure-gap finding campaign 1's privacy-consent-
      security review raised as blocking. **Fixed.** Two gaps surfaced in
      campaign 2, both now closed: DD-9 is widened so `scrub_user` reaches a
      `selected_users` array inside *any* parseable entry, declared or not —
      overriding DD-8's byte-preservation for that one field/ID — closing the
      permanent-orphan gap (**A6** tests it); and new DD-13 resolves the
      FR-004/DD-9 collision on a degraded document as halt-and-retry:
      `scrub_user` raises rather than silently skipping, `purge_account` aborts
      before deleting the account record, and the maintenance sweep retries
      every pass, isolating this one account's failure (**A6**, **C10**,
      **C11**). This closes product decision #2 recorded in
      [review-history.md](../review-history.md). Neither fix was re-reviewed
      by a fresh panel.
- [x] The residual that remains after DD-9 — a one-row addition to
      `docs/data-retention.md` (tasks.md **G2**) rather than a full retention
      audit — is stated openly in [plan.md](../plan.md) Changed surfaces and
      Complexity tracking, with the precedent (the existing Invites row) that
      scopes it. **Fixed.** Campaign 2 found G2 forbade naming DD-10's new
      mutation/aggregate-read record types in the retention register; G2 now
      explicitly names them in the Admin access records amendment. The second
      product decision campaign 2 escalated — whether the frozen in-app
      privacy policy needs a one-sentence addition naming the new durable
      store, per `docs/data-retention.md:5-7`'s policy/register sync rule — is
      answered too: DD-9 now authorizes exactly that one-sentence, text-only
      addition (tasks.md **G4**), mirroring 009's precedent. Neither answer was
      re-reviewed by a fresh panel; see
      [review-history.md](../review-history.md)'s founder acceptance.
- [x] The feature's risk class is recorded — **ASK / high** under ADR-0008 — with
      its triggers named to specific classifier rules and its landing constraints
      written down in [plan.md](../plan.md).
- [x] Manual acceptance uses purpose-seeded non-real accounts and requires
      redaction, so ASK-class PR evidence cannot carry a member's email or account
      id (constitution Principle I).
- [x] The planning-review status is recorded honestly in
      [review-history.md](../review-history.md), including campaign 1's and
      campaign 2's full `product-decision-required` verdicts, every finding
      each one raised, the owner decisions and post-campaign corrections that
      resolved them, and the founder acceptance that closes the loop under the
      two-campaign cap — stated explicitly as an acceptance of residual risk,
      not as an `approved` verdict this package has not earned and, under the
      cap, cannot currently earn from a third campaign.
