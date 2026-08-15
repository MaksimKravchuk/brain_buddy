# Review history: Live Feature-Flag Management in the Admin Portal

Recorded honestly per [checklists/requirements.md](checklists/requirements.md)'s Risk section: what has and has not been run, including two campaigns whose verdict was not favorable.

## Campaign 1 — `product-decision-required`

**Run**: `010-live-flags-c1` · **Declared risk**: medium → escalated to high · **Panel**: 6 reviewers, `claude` (fable, opus×2, sonnet) and `codex` (2× gpt-5.6-sol), not single-provider, not correlated · **Architect action**: hold implementation, put the decision packet to the human — product decisions are not an agent's to answer.

| Reviewer | Verdict | One-line summary |
| --- | --- | --- |
| requirements-consistency | product-decision-required | Blocking contradictions in fresh-store init, baseline restoration/`internal` display, `delivery_canary`, transient polling failures; idempotent-removal, forward-compat, cohort-retention, artifact-integrity gaps |
| architecture-consistency | product-decision-required | Overlay design sound; `delivery_canary` runtime-management breaks the production release smoke; analysis.md/review-history.md cited but absent; `container.py:132` unenumerated; stale citations |
| testability-evidence | changes-required | Restart evidence stops at a repository object; polling conflicts with `hydrate()`; FR-008 call-site coverage partial; no pre-landing cross-layer acceptance; lane ordering issues |
| privacy-consent-security | product-decision-required | New store excluded from account purge (blocking); missing retention/export disposition; mutations/cohort GET unlogged; fail-open degraded direction unsignaled; `hydrate()` reuse breaks FR-009 |
| ux-accessibility-mobile | product-decision-required | Mode control claimed "inherited" but no radio-group primitive exists; Remove action lacks a11y naming/focus; no fetch-failure state; 390px density unproven; no-confirmation-for-OFF is a live product question |
| adversarial-high-risk | changes-required | Most load-bearing claims verify; analysis.md/review-history.md absent (blocking); `hydrate()` claim wrong; unknown-entry "dropped on read" is a data-loss path; cohort lifecycle unpinned |

**Seven product decisions**, resolved directly by the owner rather than a second review round, each now a Derived Decision in [spec.md](spec.md): may the first mutation create an absent document (**DD-2**, yes); how is inherited `internal` displayed/restored (**DD-3**); is `delivery_canary` runtime-manageable (**DD-1**, no); must unknown future-flag entries survive a mutation (**DD-8**, yes, opaque); are selected IDs retained leaving SELECTED_USERS (**DD-6**, retained); which boundary moves for `delivery_canary` (**DD-1**, the managed set, not the deploy/scripts freeze); does purge remove the ID and is the store registered (**DD-9**, yes to both); should OFF/last-member-removal require confirmation (folded into **DD-12**, yes narrowly).

**Eighteen technical findings**, each closed by the spec.md Derived Decision or artifact fix named: initial-store-state → DD-2; baseline-state-model → DD-3 (narrowed by DD-1); deployment-contract-scope → DD-1; polling-failure-semantics → DD-11; idempotent-removal → DD-7; forward-compatibility → DD-8; cohort-lifecycle → DD-6; error-correlation-contract → FR-010/design.md F-10 fallback copy; artifact-integrity → this file and analysis.md now exist; deploy-contract-conflict → DD-1; factual-claims (analysis.md/review-history.md absence) → both now exist; incomplete-call-site-enumeration (`container.py:132`) → moot under DD-1; factual-claims (`main.tsx` vs `queryClient.ts`) → corrected to `queryClient.ts:10`; contract-ownership (cohort email resolution) → `UserRepository.get_by_id`, not `AdminService.find_account` (DD-10); factual-claims (E3/B9 paths) → corrected; durability-lifecycle-evidence → application-boundary check added (**C7**); polling-failure-evidence → DD-11 (**E2** pinning test); resolver-callsite-coverage → **F1**/**B8**/**B10** scoped explicitly; cross-layer-acceptance-evidence → **H2**; lane-independence-and-ordering → A7/C8 split, B7 reordered; retention-purge-gap → DD-9; retention-register/export → DD-9 (**G2**); auditability → DD-10; fail-open-degradation → DD-2 WARNING; session-handling → DD-11; bounded-exception (cohort size) → spec.md Assumptions states it explicitly; keyboard-focus (mode control, Remove action) → design.md Accessibility corrected; state-completeness (fetch failure) → design.md F-13; mobile-viability → design.md "Mobile reflow" subsection; data-loss (unknown entries) → DD-8; acceptance-behavior (cohort lifecycle) → DD-6.

**What campaign 1 explicitly did not find wrong**: the overlay design's layering (api → services → repositories), the `flock` + `os.replace` durability story, the "delete the overlay and the old answer remains" fallback property, the 401/403/404 precedence inherited from feature 009, the `KNOWN_FEATURE_FLAGS`/`PRIVATE_FEATURE_FLAGS` split, the ASK classification triggers, and the `adminKeys`/`purgeAdminRecords`/`bindAdminSession` machinery — all verified against the repository as claimed.

## Campaign 2 — `product-decision-required`

**Run**: `010-live-flags-c2` · **Declared risk**: medium → escalated to high · **Panel**: same 6-reviewer, dual-provider composition · **Human sign-off**: present (`.specify/workflows/runs/010-live-flags-c2/human-signoff.json`, approved by Maksim, 2026-08-14, bound to this run's artifacts digest) · **Architect action**: same as campaign 1.

| Reviewer | Verdict | One-line summary |
| --- | --- | --- |
| requirements-consistency | changes-required | Three blocking contradictions — deploy-default inheritance unrepresentable in the mode model, clear-override's cohort outcome mutually exclusive between artifacts, audit-log cardinality conflicts with the required `find_account` path — plus scope-rationale, confirmation-trigger and route-inventory inconsistencies |
| architecture-consistency | changes-required | Missed managed-flag call site (`tasks.py:340`) leaves FR-008 only partial; DD-1's `external_agent_relay` rationale is false (it does have a per-request gate); plan.md/tasks.md disagree on which layer reads cohort emails; degraded-document/purge collision; restart-silent WARNING gap |
| testability-evidence | changes-required | Lane A cannot reach its checkpoint independently of Lane B; GET-denial coverage, server-save-failure evidence, degraded-store semantic-corruption evidence, SC-008's 390×851/focus evidence, and poll-recovery evidence each gapped |
| privacy-consent-security | product-decision-required | Erasure gap closed in principle, but DD-8's preservation isn't carved out for `scrub_user` (blocking); FR-004/FR-007 collide on a degraded-document purge (escalated); privacy-policy sync question escalated |
| ux-accessibility-mobile | changes-required | Campaign 1's four findings verified closed; one new blocking gap ("Use deploy default" can silently zero a population with no confirmation/visible state) plus two focus/Escape gaps and one mobile-density gap |
| adversarial-high-risk | product-decision-required | Same degraded-document/purge collision escalated independently; DD-10's audit shape leaves `remove_selected_user` unattributable; `tasks.py:340` miss confirmed; DD-8's version-skew protection unspecified for unknown fields/modes/unmanaged entries |

**Two product decisions**, open at campaign close, answered by the owner afterward (not re-reviewed — the two-campaign cap forbids a third round): does the frozen privacy policy need a one-sentence addition for the new store → **authorized**, folded into DD-9, tasked as **G4**; does a degraded-document purge halt-and-retry or complete with the scrub skipped → **halt and retry**, new **DD-13**, tasked as **A6**/**C10**/**C11**.

**Thirty-four findings raised** (several independently duplicated across lenses), none fixed *during* campaign 2 — the loop closed by founder acceptance, not an in-campaign fix. All were subsequently fixed post-campaign directly in spec.md/plan.md/tasks.md, **not re-reviewed by a fresh panel** (the cap forbids a third one). Disposition, grouped by the spec.md/tasks.md artifact that now closes each:

- **DD-3** — inheritance-state-model (blocking: `internal` unrepresentable in the mode schema) and clear-override-cohort-lifecycle (blocking: DD-3 said delete-entire-entry, tasks.md C3 said retain-cohort — mutually exclusive) → both resolved by the three-field `override_mode`/`source`/`deploy_default_state` split and by correcting tasks.md **C3** to match DD-3.
- **DD-10** — audit-log-cardinality (blocking: "exactly one record" incompatible with routing add through `find_account`) → "exactly one *new* record," stated explicitly in FR-006. audit-obligation-narrowing/audit-attributability → target account id added to mutation records; **G1** records the ADR-0017 §4 narrowing.
- **DD-1** — scope-rationale-factual-consistency/false-repository-claim (blocking: `external_agent_relay`'s "construction-time only" claim was false) → rationale corrected to ground exclusion in `_build_agent_secret_box` instead.
- **DD-12** — confirmation-trigger-consistency (the allowlist vs. a false "nonzero-to-zero" invariant) and owner-decision-traceability (the confirmation decision missing from the DD table) → new DD-12, the three-operation allowlist. destructive-action-confirmation (blocking: "Use deploy default" could silently zero a population) → added to the allowlist.
- **FR-006/C1** — route-inventory-and-authorization-coverage (five routes inconsistently counted) → **C1** names all five explicitly, GET included.
- **FR-008/B8/B10** — false-repository-claim/call-site-enumeration-wiring (blocking: `tasks.py:340` missed) → named and routed through the resolver.
- **C9** — layering-violation (plan.md vs. tasks.md disagreed on which layer reads cohort emails) → both now agree: `FeatureFlagService.describe()`'s plain `UserRepository.get_by_id` read.
- **DD-13** — failure-handling/retention-purge-gap/privacy-erasure-conflict (blocking: FR-004 "refuse while degraded" vs. DD-9 "purge scrubs" collide) → this is product decision #2 above: halt and retry.
- **FR-004** — observability (a process starting already-degraded emitted no WARNING) → FR-004 now states the in-process "was healthy" state starts unset, so the first degraded read emits once.
- **Lane E** — scope-coherence (15s contract never stated as web-only) → resolved by widening to mobile (**E6**–**E8**), not by caveat.
- **Lane A/C8** — lane-dependency-inversion (blocking: Lane A asserted `effective_flags()`/`describe()` behaviour that needs Lane B) → moved to **C8**; Lane A now asserts only the repository's own methods.
- **C3a** — server-save-failure-evidence (no test proved a persistence failure returns a correlation-bearing error and permits retry) → new task.
- **A4** — degraded-store-evidence (malformed known entries, injected read errors, WARNING field shape unasserted) → covers all three; risk-model-accuracy (Fly divergence) and poll-recovery-evidence (**E2**/**E7** advancing a further interval) fixed in the same pass.
- **D1a**/**H2** — responsive-accessibility-evidence (390×851 usability assigned only to JSDOM, no confirm-focus assertion) → **D1a** plus a real-browser check in **H2**.
- **C11** — lane-ownership (no GREEN task owned the `AccountService` wiring) → named.
- **DD-9/A6** — retention-purge-gap (DD-8's preservation not carved out for `scrub_user`, blocking) → widened to any parseable entry.
- **G2** — retention-register-disposition (forbade naming DD-10's record types) → now names them.
- **G3** — threat-model-staleness (`docs/auth.md` still stated only two operator authorities) → new bullet added.
- **B8a** — consent-regression-coverage (no lane asserted the consent boundary doesn't move) → new task.
- **D1a/FR-010** — keyboard-focus (F-09 scope: only cohort-row removal had a focus target; F-08a Escape undefined) and mobile-viability (F-08a's own tap-target treatment) → FR-010 now names a focus target per mutation type and requires Escape dismissal; D1a asserts both plus the 44px reflow.
- **DD-8** — version-skew-preservation (protection unspecified for unknown fields/modes/unmanaged entries) → each named explicitly, with an out-of-vocabulary mode treated as degraded, not preserved; "byte-for-byte" softened to "value-intact under this build's own canonical serialization."
- **DD-12** — stale-confirmation-bypass (advisory: the gate is client-side and bypassable by concurrent stale tabs) → DD-12 states this as an accepted residual explicitly.

## Founder acceptance

**This is acceptance of residual risk, not an approval verdict.** Both campaigns' true status is `product-decision-required` — campaign 1 resolved by seven owner decisions, campaign 2 by two further decisions plus the thirty-four post-campaign fixes above — closed by this founder acceptance rather than by a third campaign returning `approved`. No automated review of this package has ever returned `approved`; what follows is the human accepting a stated, bounded residual risk in place of a verdict this package cannot earn again under the two-campaign cap.

- **Accepted by**: Maksim · **Accepted on**: 2026-08-14 · **Expires**: 2026-09-13

Maksim explicitly requested implementation and production release of live per-user feature-flag control, accepting campaign 2's `product-decision-required` verdict under the two-campaign cap rather than spending a third campaign ADR-0011 does not permit. This sign-off is bound to the reviewed bounded slice recorded in campaign 2's `human-signoff.json`: two safe member-product flags only, existing admin authorization preserved, account IDs scrubbed on purge, content-free audit logs, no deploy-workflow or release-canary mutation surface. The great majority of campaign 2's findings were fixed directly post-campaign (above), but none of that correction work was re-reviewed by a fresh panel, because the cap forbids a third campaign — every fix is self-graded against the same rubric campaign 2's reviewers used, not independently re-verified.

**The residual risk, stated plainly, is narrow:** the post-campaign corrections above — both open product decisions, the great majority of the thirty-four findings, and the Fly-divergence/`A4`/poll-recovery corrections this pass added — could not receive a third panel's independent review before this feature lands, because campaign 2 already spent the cap. No verified campaign-2 finding remains deliberately unfixed; the residual is the lack of a third independent panel over the corrections.

**Compensating measures:**

- All six campaign-2 lenses, across both Codex and Claude oracles, certified against the identical artifacts digest, so the finding list is pinned to an exact, verifiable artifact state even though the artifacts have since moved past it to apply the fixes above.
- Implementation must pass the canonical CI job graph and the same Docker Compose stack production runs (`docker compose up --build`) with no bypass of the mutation gate or coverage floors before any PR touching this feature can land, per the `deploy-and-ci` skill and CLAUDE.md.
- tasks.md's **H2** requires an executed cross-layer acceptance pass covering both the web admin flow and the mobile propagation path before this feature is marked delivered.
- Tasks **A6**, **C10**, **C11** give the degraded-document purge halt-and-retry (DD-13) and the undeclared-flag-entry scrub widening (DD-9) executable evidence rather than an assumed disposition.
- `admin_portal`, `delivery_canary` and `external_agent_relay` remain structurally excluded from the runtime-manageable set (DD-1) — no code path in this feature can ever write a runtime entry for any of the three, bounding the blast radius of every finding above to the two authorized member-facing flags.

**The expiry is not decoration.** If this has not landed and been accepted by 2026-09-13, the gate closes and this package requires a fresh, bounded campaign — governed by whatever cap policy is current at that time — before any further planning-artifact change lands.
