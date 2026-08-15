# Review history: Live Feature-Flag Management in the Admin Portal

Recorded honestly per [checklists/requirements.md](checklists/requirements.md)'s
Risk section: what has and has not been run, including a campaign whose verdict
was not favorable. This file did not exist when campaign 1's own checklist
claimed it did (a campaign-1 finding in itself — see below); it now exists at
the path that claim named.

## Campaign 1 — `product-decision-required`

**Run**: `010-live-flags-c1` · **Artifacts digest**:
`b5a9e895aaedda597f3157f8755571458d226b78743b4db1e66b9b0d067c26fe` ·
**Declared risk**: medium → **escalated to high** by the risk classifier ·
**Panel**: 6 reviewers, providers `claude` (4: fable, opus×2, sonnet) and
`codex` (2: gpt-5.6-sol), not single-provider, not correlated ·
**Architect action**: "Hold implementation and put this decision packet to the
human. These are product decisions; no agent may answer them for them."

| Reviewer | Verdict | One-line summary |
| --- | --- | --- |
| requirements-consistency | product-decision-required | Blocking contradictions in fresh-store init, baseline restoration/`internal` display, `delivery_canary`, transient polling failures; idempotent-removal, forward-compat, cohort-retention and artifact-integrity gaps |
| architecture-consistency | product-decision-required | Overlay design sound; `delivery_canary` runtime-management durably breaks the production release smoke; `analysis.md`/`review-history.md` cited but absent; `container.py:132` (external_agent_relay startup check) unenumerated; two stale file citations |
| testability-evidence | changes-required | Strong unit/component intent, but restart evidence stops at a repository object, polling tasks conflict with `hydrate()`, FR-008 call-site coverage partial, cross-layer acceptance not required pre-landing, lane ordering issues |
| privacy-consent-security | product-decision-required | New durable store excluded from account purge (blocking); missing from retention register/export disposition; operator mutations and cohort GET unlogged; fail-open degraded direction unsignaled outside `/admin`; `hydrate()` reuse breaks FR-009 |
| ux-accessibility-mobile | product-decision-required | Mode control claimed "inherited" but no radio-group primitive exists anywhere in the codebase; Remove action lacks accessible-name disambiguation and focus management; no state for the initial fetch failing outright; 390px density claim unproven; no-confirmation-for-OFF is a live product question |
| adversarial-high-risk | changes-required | Confirms most load-bearing claims verify against the repository; `analysis.md`/`review-history.md` absent (blocking); `hydrate()` claim wrong; unknown-entry "dropped on read" is a version-skew data-loss path; cohort lifecycle across mode transitions unpinned |

### Product decisions raised (7) and their resolutions

The owner resolved all seven directly, without a second review round to
re-litigate them. Each resolution is recorded as a Derived Decision in
[spec.md](spec.md) and is frozen; a later campaign does not reopen it.

| # | Reviewer | Question (short) | Resolution |
| --- | --- | --- | --- |
| 1 | requirements-consistency | May the first mutation create an absent document? | **Yes** — absence is healthy baseline inheritance (spec.md DD-2) |
| 2 | requirements-consistency | How is inherited `internal` displayed/restored? | Named inheritance state + explicit "Use deploy default" clear action (DD-3) |
| 3 | requirements-consistency | Is `delivery_canary` runtime-manageable? | **No** — excluded from the managed set (DD-1) |
| 4 | requirements-consistency | Must unknown future-flag entries survive a mutation? | **Yes**, preserved opaquely (DD-8) |
| 5 | requirements-consistency | Are selected IDs retained when a flag leaves SELECTED_USERS? | **Retained**, shown as a count while inactive (DD-6) |
| 6 | architecture-consistency | Which boundary moves for `delivery_canary` — managed set or the deploy/scripts freeze? | **The managed set** — `delivery_canary` (and, by the same reasoning, `external_agent_relay`) excluded; deploy/scripts freeze stays intact (DD-1) |
| 7 | privacy-consent-security | Does account purge remove the ID from the runtime document, and is the store registered? | **Yes to both** — purge scrubs the cohort (DD-9); one retention-table row and one export-exclusion line, not a privacy-policy rewrite |
| — | ux-accessibility-mobile | Should OFF / last-member-removal require confirmation? | **Yes, narrowly** — confirmation required only for those two transitions (owner decision 12, folded into FR-010/design.md F-08a) |

### Technical findings (18) and their resolutions

Severity as reported by the reviewer that raised it. "Resolution" names the
spec.md Derived Decision, or the artifact fix, that closes the finding in this
revision.

| Reviewer | Category | Severity | Resolution |
| --- | --- | --- | --- |
| requirements-consistency | initial-store-state | blocking | DD-2 (absence = healthy; first mutation creates the document) |
| requirements-consistency | baseline-state-model | blocking | DD-3 (named inheritance state + "Use deploy default"); DD-1 narrows the flags this even applies to |
| requirements-consistency | deployment-contract-scope | blocking | DD-1 (`delivery_canary` excluded from the managed set) |
| requirements-consistency | polling-failure-semantics | blocking | DD-11 (`refreshSession()` distinct from `hydrate()`) |
| requirements-consistency | idempotent-removal | important | DD-7 (add refuses / remove idempotent by ID) |
| requirements-consistency | forward-compatibility | important | DD-8 (unknown entries preserved opaquely across mutations) |
| requirements-consistency | cohort-lifecycle | important | DD-6 (cohort retained across mode changes; edit-gated to SELECTED_USERS) |
| requirements-consistency | error-correlation-contract | advisory | FR-010/design.md F-10: named fallback copy when no response was received (no correlation ID to show) |
| requirements-consistency | artifact-integrity | important | This file and [analysis.md](analysis.md) now exist; checklist links fixed |
| architecture-consistency | deploy-contract-conflict | blocking | DD-1 (`delivery_canary` excluded — the managed set moved, not the deploy/scripts freeze) |
| architecture-consistency | factual-claims (analysis.md/review-history.md) | blocking | Both files now exist; checklist re-graded honestly |
| architecture-consistency | incomplete-call-site-enumeration (`container.py:132`) | important | Moot under DD-1: `external_agent_relay` is not a managed flag, so its construction-time check is never asked to route through the resolver; plan.md now names this explicitly rather than leaving it an accidental omission |
| architecture-consistency | factual-claims (`main.tsx` vs `queryClient.ts`) | important | plan.md/tasks.md corrected to `frontend/src/queryClient.ts:10` |
| architecture-consistency | contract-ownership (cohort email resolution) | important | plan.md now names `UserRepository.get_by_id` (not `AdminService.find_account`) for `describe()`, with the audit-dilution reasoning stated (DD-10) |
| architecture-consistency | factual-claims (E3/B9 paths) | advisory | tasks.md E3 points at `BrainDumpGate.test.tsx`; the phantom `test_dependencies.py` checkpoint is gone (B7/B8's call-site coverage now lives in `test_feature_flag_service.py`) |
| testability-evidence | durability-lifecycle-evidence | blocking | Owner decision 14: restart/redeploy evidence now includes an application-boundary check (tasks.md C7), not only a repository object (A1) |
| testability-evidence | polling-failure-evidence | important | DD-11 (E2 now asserts both paths distinctly, plus a pinning test for `hydrate()`'s unchanged startup behavior) |
| testability-evidence | resolver-callsite-coverage | important | F1 extended to assert login/signup, not only `/me`; B8/B10 scoped to the two managed flags with an explicit non-involvement assertion for the excluded ones |
| testability-evidence | cross-layer-acceptance-evidence | important | Owner decision 13: tasks.md H2, a named pre-landing task |
| testability-evidence | lane-independence-and-ordering | important | A7 now does the shape-level check only; the sentinel/request-level proof moved to C8; B7 (call-site coverage) now precedes B9/B10 (GREEN) |
| testability-evidence | evidence-record-integrity | important | Same fix as architecture-consistency's factual-claims finding above |
| privacy-consent-security | retention-purge-gap | blocking | DD-9 (purge scrubs the cohort, mirroring `InviteRepository.scrub_user`) |
| privacy-consent-security | retention-register-and-export-disposition | important | DD-9 (tasks.md G2: one retention-table row, one export-exclusion line) |
| privacy-consent-security | auditability | important | DD-10 (content-free log record per mutation + aggregate cohort read) |
| privacy-consent-security | fail-open-degradation | important | DD-2 (one coarse WARNING log record on the healthy→degraded transition) |
| privacy-consent-security | session-handling | important | DD-11 (`refreshSession()`) |
| privacy-consent-security | bounded-exception (cohort size) | advisory | spec.md Assumptions now states the no-bound position explicitly rather than by omission |
| ux-accessibility-mobile | keyboard-focus (mode control) | important | design.md Accessibility section corrected: native `fieldset`/`legend` radio group specified as new work, not inherited |
| ux-accessibility-mobile | keyboard-focus (Remove action) | important | design.md F-04/F-09: `aria-label` naming + defined focus target after removal |
| ux-accessibility-mobile | state-completeness (fetch failure) | important | design.md F-13, distinct from F-11 |
| ux-accessibility-mobile | mobile-viability | important | design.md "Mobile reflow at 390×851" subsection added |
| adversarial-high-risk | gate-integrity | blocking | Same fix as architecture-consistency's factual-claims finding above |
| adversarial-high-risk | correctness (`hydrate()` claim) | important | DD-11 |
| adversarial-high-risk | data-loss (unknown entries) | important | DD-8 |
| adversarial-high-risk | acceptance-behavior (cohort lifecycle) | important | DD-6 |
| adversarial-high-risk | factual-drift (paths) | advisory | Same fix as architecture-consistency's factual-claims finding above |

### What campaign 1 explicitly did not find wrong

Per the adversarial-high-risk review: the overlay design's layering
(api → services → repositories), the `flock` + `os.replace` durability story,
the "delete the overlay and the old answer remains" fallback property, the
401/403/404 precedence inherited from feature 009, the `KNOWN_FEATURE_FLAGS`/
`PRIVATE_FEATURE_FLAGS` split, the ASK classification triggers, and the
`adminKeys`/`purgeAdminRecords`/`bindAdminSession` machinery all verified
against the repository as claimed. This revision does not touch any of that —
only the eighteen findings and seven product decisions above.

## Campaign 2 — `product-decision-required`

**Run**: `010-live-flags-c2` · **Artifacts digest**:
`5856f5bffc96592e7833c1d6e6ed8462e36ec30153394809b0c4a28d16f22afd` (artifacts
unchanged since preflight) · **Declared risk**: medium → **escalated to high**
by the risk classifier · **Panel**: 6 reviewers, providers `claude` (4: fable,
opus×2, sonnet) and `codex` (2: gpt-5.6-sol), not single-provider, not
correlated · **Human sign-off**: present
(`.specify/workflows/runs/010-live-flags-c2/human-signoff.json`, `approved_by`
Maksim, `approved_on` 2026-08-14, bound to this run's artifacts digest) ·
**Architect action**: "Hold implementation and put this decision packet to the
human. These are product decisions; no agent may answer them for them."

| Reviewer | Verdict | One-line summary |
| --- | --- | --- |
| requirements-consistency | changes-required | Three blocking contract contradictions — deploy-default inheritance unrepresentable in the declared mode model, clear-override's cohort outcome mutually exclusive between artifacts, audit-log cardinality conflicts with the required `find_account` lookup path — plus scope-rationale, confirmation-trigger and route-inventory inconsistencies |
| architecture-consistency | changes-required | A missed managed-flag call site (`backend/app/api/tasks.py:340`) leaves FR-008 only partially satisfied; DD-1's `external_agent_relay` rationale is false (it does have a per-request gate, contradicting FR-008 itself); plan.md/tasks.md disagree on which layer performs the cohort-email read; degraded-document/purge collision and a restart-silent WARNING gap |
| testability-evidence | changes-required | Lane A cannot reach its advertised checkpoint independently of Lane B (blocking dependency inversion); GET-route denial coverage, server-save-failure route evidence, degraded-store semantic-corruption evidence, SC-008's 390×851/focus evidence, and poll-recovery evidence are each gapped |
| privacy-consent-security | product-decision-required | Campaign 1's erasure gap is closed in principle, but DD-8's byte-for-byte preservation is not carved out for `scrub_user` (an undeclared flag's account IDs survive purge forever, blocking) and FR-004/FR-007 collide on a degraded-document purge (escalated as a product decision); the retention register and `docs/auth.md` go stale; the privacy-policy sync question is escalated |
| ux-accessibility-mobile | changes-required | Campaign 1's four findings verified closed against current code; one new blocking gap ("Use deploy default" can silently zero a flag's population with no confirmation and no visible deploy-default state) plus two new important focus/Escape gaps and one advisory mobile-density gap |
| adversarial-high-risk | product-decision-required | The same degraded-document/purge collision escalated independently as a controller decision; DD-10's audit shape leaves `remove_selected_user` unattributable; the `tasks.py:340` call-site miss confirmed independently; DD-8's version-skew protection is unspecified for unknown fields, unknown modes and declared-but-unmanaged entries |

### Product decisions raised (2) at campaign 2, resolved post-campaign

At the moment campaign 2 closed, neither question had been resolved into a
spec.md Derived Decision — the table below records that raw, as-closed state
unedited. The owner subsequently answered both directly, the same way
campaign 1's seven decisions were answered: not through a third review round
(the cap forbids one), but by owner decision, now frozen as DD-9 (widened)
and DD-13 in [spec.md](spec.md)'s Derived decisions table. Neither answer was
re-reviewed by a fresh panel; the exact-SHA campaign-2 lenses evaluated the
*question*, not this *answer*, which is exactly the residual risk recorded
under Founder acceptance below.

| # | Reviewer | Question (short) | Disposition at campaign-2 close | Post-campaign resolution |
| --- | --- | --- | --- | --- |
| 1 | privacy-consent-security | `docs/data-retention.md:5-7` requires the in-app privacy policy to stay in sync with the retention register; this feature registers a new durable, member-linked store but freezes the policy page. Does the owner authorize a one-sentence, text-only policy addition (mirroring 009's task I7), or knowingly accept the divergence? | **Open** — not answered in this campaign; accepted as residual risk | **Authorized.** DD-9 now names the one-sentence, text-only addition to `frontend/src/pages/PrivacyPolicyPage.tsx`'s "How long we keep it" section (plus the routine `LAST_UPDATED` bump) as in-scope, mirroring 009's precedent — not the privacy-summary rewrite the founder's slice still excludes. tasks.md **G4** is the named task. |
| 2 | adversarial-high-risk (independently escalated by privacy-consent-security as a blocking finding) | When the runtime flag document is degraded, does account purge halt-and-retry until the document is repaired, or complete on schedule with the cohort scrub skipped and recorded as a residual? | **Open** — not answered in this campaign; accepted as residual risk | **Halt and retry.** New DD-13: `scrub_user` raises rather than silently skipping when the document is degraded, so `AccountService.purge_account` aborts before `user_repo.delete` runs; the account is retained past its 14-day promise until the document is repaired, and the maintenance sweep retries every pass, isolating this one account's failure from every other due account's purge in the same pass. tasks.md **A6**, **C10**, **C11** are the named tests and the GREEN task. |

### Technical findings (34 raised across 6 reviewers, several independently duplicated) and their disposition

None of campaign 2's findings were fixed **before** campaign 2 closed: the loop
closed by founder acceptance, not by an in-campaign fix. The table immediately
below is that as-closed record, unedited. Duplicate findings — the same
underlying gap raised independently by more than one lens — are merged into
one row and every reviewer that raised it is named, matching the severity each
one assigned.

Nearly all of them **were** subsequently fixed, post-campaign, directly in
spec.md (DD-1, DD-3, DD-8, DD-9, DD-10, DD-12, DD-13), plan.md and tasks.md —
the corrections a later reader can see in those files today. None of that
post-campaign work was re-reviewed by a fresh panel; the campaign cap forbids
a third one. The second table below, "Post-campaign disposition," records
each finding's current concrete resolution honestly, including the handful
that remain only partially closed. Treat the first table as history and the
second as the current state of the artifacts.

| Reviewer(s) | Category | Severity | Finding (short) |
| --- | --- | --- | --- |
| requirements-consistency | inheritance-state-model | blocking | Deploy-default inheritance and its `internal` value cannot be represented by the declared three-mode radio/schema contract |
| requirements-consistency | clear-override-cohort-lifecycle | blocking | DD-3/FR-003/plan.md/tasks.md A5 say clear deletes the entry entirely; tasks.md C3 requires a retained cohort — mutually exclusive |
| requirements-consistency | audit-log-cardinality | blocking | SC-006's "exactly one record" per mutation is incompatible with routing add through `AdminService.find_account`, which always emits its own lookup record |
| requirements-consistency, architecture-consistency, adversarial-high-risk | scope-rationale-factual-consistency / false-repository-claim / rationale-factual-drift | important (requirements-consistency, architecture-consistency: blocking); advisory (adversarial-high-risk) | DD-1's claim that `external_agent_relay`'s only backend consequence is startup-time construction is false — `dependencies.py:313-345` gates eight routes in `agents.py` per request, and FR-008 already says so |
| requirements-consistency | confirmation-trigger-consistency | important | FR-010/F-08a's confirmation rule is stated both as an exact operation allowlist and as a false effect-based "nonzero-to-zero" invariant; SELECTED_USERS-empty and clear-to-off can also zero exposure without triggering it |
| requirements-consistency, testability-evidence | route-inventory-and-authorization-coverage / authorization-route-coverage | important | Five runtime-flag routes are inconsistently counted as "four mutations plus clear," leaving GET's denial-test coverage ambiguous |
| requirements-consistency | owner-decision-traceability | advisory | The confirmation decision (owner decision 12) is missing from the canonical DD-1…DD-11 table the checklist claims is complete |
| architecture-consistency, adversarial-high-risk | false-repository-claim / call-site-enumeration-wiring | blocking (architecture-consistency); important (adversarial-high-risk) | `backend/app/api/tasks.py:340` calls `voice_brain_dump_enabled` directly, a third managed-flag call site the plan's "two call sites" claim and changed-surfaces table both omit; no wiring mechanism is specified for the `(user, config)` helper to reach the DI'd service |
| architecture-consistency | layering-violation | important | plan.md attributes the cohort-email `UserRepository.get_by_id` read to `FeatureFlagService`; tasks.md C9 attributes it to the `api/admin.py` route handler, which would be the backend's first route→repository read |
| architecture-consistency, privacy-consent-security, adversarial-high-risk | failure-handling / retention-purge-gap / privacy-erasure-conflict | important (architecture-consistency); blocking (privacy-consent-security, adversarial-high-risk) | FR-004's "refuse every mutation while degraded" and DD-9/FR-007's "purge scrubs the cohort" collide on a degraded document with no stated resolution — **this is product decision #2 above** |
| architecture-consistency | observability | important | The degraded-state WARNING fires only on a healthy→degraded transition, so a process that starts already degraded after a restart/deploy emits nothing |
| architecture-consistency | scope-coherence | advisory | The 15-second propagation contract is never stated as web-client-only; `mobile_task_classification`'s only consumer is the mobile client, which is out of scope |
| testability-evidence | lane-dependency-inversion | blocking | Lane A's repository tests assert `effective_flags()`/`describe()` behaviour that Lane B's service alone supplies, so Lane A cannot pass independently despite being the declared prerequisite |
| testability-evidence | server-save-failure-evidence | important | No `TestClient`-level test proves a persistence failure returns the correlation-bearing error, preserves prior state, and permits a successful retry |
| testability-evidence | degraded-store-evidence | important | Concrete corrupt-store cases omit semantically malformed known entries and injected read errors, and the WARNING's required fields (correlation id, reason band, absence of member data) are unasserted |
| testability-evidence | responsive-accessibility-evidence | important | SC-008's 390×851 usability outcome is assigned only to a JSDOM component test with no browser-viewport evidence; D1 does not assert the confirmation-step focus behaviour design.md requires |
| testability-evidence | poll-recovery-evidence | important | The transient-refresh test preserves state but never advances a further interval to prove polling actually recovers after a transient failure |
| testability-evidence | lane-ownership | advisory | No GREEN task explicitly owns the `AccountService`/purge-integration wiring the C5 acceptance test depends on |
| privacy-consent-security | retention-purge-gap (DD-8/scrub_user) | blocking | DD-8's byte-for-byte preservation of an undeclared flag's entry is not carved out for `scrub_user`; a purged member's account ID inside such an entry survives every future purge with no sweep in scope |
| privacy-consent-security | retention-register-disposition | important | tasks.md G2 restricts the retention-register edit and forbids naming DD-10's new record types, so the register will not describe what the feature actually emits |
| privacy-consent-security | threat-model-staleness | important | `docs/auth.md` still states ADR-0017 bounds operator power to two operations; this feature adds runtime flag management as a third, undocumented authority |
| privacy-consent-security | consent-regression-coverage | advisory | No lane asserts that a runtime override cannot move the `voice_brain_dump` consent boundary (newly-admitted members still hit consent; OFF-override owners keep their existing rights) |
| privacy-consent-security, adversarial-high-risk | audit-obligation-narrowing / audit-attributability | advisory (privacy-consent-security); important (adversarial-high-risk) | The bulk, non-per-account cohort-email read narrows ADR-0017 §4's per-operation audit clause without recording the narrowing; DD-10's mutation record omits the target account ID, leaving `remove_selected_user` unattributable |
| ux-accessibility-mobile | destructive-action-confirmation | blocking | "Use deploy default" can silently zero a flag's effective population with no confirmation and no on-screen indication of what the deploy-default state currently is |
| ux-accessibility-mobile | keyboard-focus (F-09 scope) | important | Post-mutation focus restoration is stated only for cohort-row removal, leaving four other mutation/failure paths with no defined focus target |
| ux-accessibility-mobile | keyboard-focus (F-08a Escape) | important | F-08a's confirm step does not state whether Escape dismisses it, unlike the screen's existing `RevokeConfirmDialog`/`Overlay` convention |
| ux-accessibility-mobile | mobile-viability | advisory | The Mobile reflow subsection omits F-08a's own Confirm/Cancel tap-target treatment |
| adversarial-high-risk | version-skew-preservation | important | DD-8 protects only undeclared flag names, leaving unknown fields inside a managed entry, unrecognized mode values, and declared-but-unmanaged flag entries unspecified — reachable by the same rollback scenario DD-8 exists to close; "byte-for-byte" is also stronger than the parse-then-reserialize mechanism can guarantee |
| adversarial-high-risk | stale-confirmation-bypass | advisory | F-08a's confirmation gate is computed from client-side last-rendered state and is bypassable by concurrent stale tabs; design.md states it as absolute rather than best-effort |
| adversarial-high-risk | risk-model-accuracy | advisory | plan.md's multi-machine risk paragraph describes a shared-document lost-update model that Fly's single-attach, per-machine volumes cannot produce; the real scale-out failure is app-wide state divergence |

### Post-campaign disposition (not re-reviewed by a third panel)

| Category | Current resolution |
| --- | --- |
| inheritance-state-model | **Resolved.** DD-3 now carries the three-field split — `override_mode` / `source` / `deploy_default_state` — instead of forcing the inherited state onto a mode value; FR-010 states no radio is checked while inheriting. |
| clear-override-cohort-lifecycle | **Resolved.** DD-3 states clearing deletes the flag's entire runtime entry, cohort included; tasks.md **C3** is corrected to match rather than requiring a retained cohort. |
| audit-log-cardinality | **Resolved.** DD-10 now defines "exactly one" as exactly one *new* record from this feature, in addition to — not instead of — `find_account`'s existing "Admin lookup" record on a successful add; FR-006 states it explicitly. |
| scope-rationale-factual-consistency / false-repository-claim / rationale-factual-drift | **Resolved.** DD-1's `external_agent_relay` rationale is corrected: it acknowledges the flag's existing per-request gate and grounds the exclusion in `_build_agent_secret_box`'s construction-time-only decision instead. |
| confirmation-trigger-consistency | **Resolved.** New DD-12 replaces the effect-based "nonzero-to-zero" rule with an exact three-operation allowlist — OFF, last-member removal, "Use deploy default" — and FR-010 states it as an allowlist, not an invariant. |
| route-inventory-and-authorization-coverage / authorization-route-coverage | **Resolved.** FR-006 and tasks.md **C1** now name all five routes explicitly, `GET` included, matching the stated count. |
| owner-decision-traceability | **Resolved.** DD-12 is now in the canonical DD-1…DD-13 table. |
| false-repository-claim / call-site-enumeration-wiring (`tasks.py:340`) | **Resolved.** plan.md, spec.md's FR-008 and tasks.md **B8/B10** now name `backend/app/api/tasks.py:340` as a third `voice_brain_dump` call site and route it through the resolver. |
| layering-violation (cohort-email read) | **Resolved.** plan.md and tasks.md **C9** now agree the read goes through `FeatureFlagService.describe()`'s plain `UserRepository.get_by_id` call, not `AdminService.find_account` and not a route-handler-level read. |
| failure-handling / retention-purge-gap / privacy-erasure-conflict (degraded-document purge) | **Resolved — this was product decision #2 above.** New DD-13: halt and retry, not a silent skip or an unconditional scrub attempt. |
| observability (restart-already-degraded) | **Resolved.** FR-004 now states a process whose very first read after startup is already degraded still emits the WARNING exactly once, because the in-process "was the last read healthy" state starts unset, not healthy. |
| scope-coherence (mobile-only propagation) | **Resolved by widening, not by caveat.** FR-009 and Lane E now cover the mobile `SessionProvider` explicitly (E6–E8), so the 15-second contract is genuinely client-generic rather than silently web-only. |
| lane-dependency-inversion | **Resolved.** Lane A's tasks (A1–A7) now assert only the repository's own `read()`/`mutate()`/`clear()`/`scrub_user()` behaviour; the `effective_flags()`/`describe()`-level assertion that depended on Lane B's service moved to **C8**, so Lane A no longer needs Lane B to pass. |
| server-save-failure-evidence | **Resolved.** New task **C3a** forces the repository's write path to raise and asserts the route surfaces a 5xx (not a false 200) and leaves the document unchanged. |
| degraded-store-evidence | **Resolved.** **A4** covers a semantically malformed `mode` value and injected `OSError`/`PermissionError` read failures as degraded cases, and asserts the WARNING's bounded field shape (correlation id, coarse reason band, affected-override count, no member data). |
| responsive-accessibility-evidence | **Resolved.** New task **D1a** asserts the confirm step's focus/Escape behaviour and 390×851 reflow's 44px minimum, while **H2** requires the same checks in a real 390×851 browser viewport before landing. |
| poll-recovery-evidence | **Resolved** (see Fixed post-campaign, below). **E2**/**E7** now advance a further interval after the transient failure and assert the poll recovers and applies the new flags without a sign-out. |
| lane-ownership | **Resolved.** New task **C11** is the named GREEN task that wires `AccountService.purge_account` to `feature_flag_repo.scrub_user`. |
| retention-purge-gap (DD-8/`scrub_user`) | **Resolved.** DD-9 is widened: `scrub_user` now reaches a `selected_users` array inside *any* parseable entry, declared or not, overriding DD-8's byte-preservation for that one field/ID; **A6** tests it. |
| retention-register-disposition | **Resolved.** tasks.md **G2** now explicitly names this feature's per-mutation and aggregate-read record types in the amended Admin access records section, rather than forbidding it. |
| threat-model-staleness | **Resolved.** New task **G3** adds the operator-authority bullet to `docs/auth.md`, pointing at ADR-0018. |
| consent-regression-coverage | **Resolved.** New task **B8a** asserts a runtime-admitted caller still hits the consent gate and a runtime-OFF caller still reaches the owner-authority voice routes. |
| audit-obligation-narrowing / audit-attributability | **Resolved.** DD-10 includes the target account id in add/remove mutation records, and **G1** explicitly requires ADR-0018 to record the bounded narrowing of ADR-0017 §4 for the bulk cohort-email read: one aggregate count record, never one log per resolved account. |
| destructive-action-confirmation ("Use deploy default") | **Resolved.** DD-12 adds "Use deploy default" to the confirmation allowlist alongside OFF and last-member removal. |
| keyboard-focus (F-09 scope) | **Resolved.** FR-010 now states a defined focus target after *any* mutation succeeds, naming the target per mutation type, not only row removal. |
| keyboard-focus (F-08a Escape) | **Resolved.** FR-010 and new task **D1a** require Escape dismissal, with focus received on appearance and returned to the triggering control on Cancel or Escape. |
| mobile-viability (F-08a reflow) | **Resolved.** FR-010 and **D1a** require the confirm step's Confirm/Cancel controls to reflow with the same 44px-minimum treatment as the section's other controls. |
| version-skew-preservation | **Resolved.** DD-8 now separately names an unrecognized field inside a known entry, a declared-but-unmanaged flag's entry, and an out-of-vocabulary `mode` value (treated as degraded, not preserved); "byte-for-byte" is softened to "value-intact under this build's own canonical serialization." |
| stale-confirmation-bypass | **Resolved.** DD-12 states the stale-tab race explicitly as an accepted residual — "reversible by its own inverse" — rather than presenting the confirmation gate as absolute. |
| risk-model-accuracy (Fly divergence) | **Resolved** (see Fixed post-campaign, below). plan.md's Risks section now describes the correct failure mode — per-machine volume divergence — not a shared-document lost-update race impossible on Fly's single-attach volumes. |

**Fixed post-campaign — the three gaps this correction pass targeted directly:**
the Fly divergence risk-model text (`risk-model-accuracy`, above), the `A4`
injected-`OSError`/`PermissionError` read-failure cases (part of
`degraded-store-evidence`, above), and the `E2`/`E7` next-interval poll-recovery
assertion (`poll-recovery-evidence`, above). All three are now closed in
plan.md/tasks.md exactly as recorded in the rows above.

## Founder acceptance

**This is acceptance of residual risk, not an approval verdict.** Campaign 1's
true status is `product-decision-required`, resolved directly by seven owner
decisions rather than by a second campaign returning `approved`. Campaign 2's
true status is also `product-decision-required`, with two open product
decisions and thirty-four raised findings, closed by this founder acceptance
rather than by a third campaign returning `approved`. Neither campaign's
recorded verdict is rewritten by anything below or by the post-campaign
corrections in the "Post-campaign disposition" tables above: no automated
review of this package has ever returned, or now returns, `approved`. What
follows is the human accepting a stated, bounded residual risk in place of a
verdict this package cannot earn again under the cap — a distinct thing from
the package having passed review.

- **Accepted by**: Maksim
- **Accepted on**: 2026-08-14
- **Expires**: 2026-09-13

Maksim explicitly requested implementation and production release of live
per-user feature-flag control in the admin portal, accepting campaign 2's
`product-decision-required` verdict under the two-campaign cap rather than
spending a third campaign that ADR-0011 does not permit. This sign-off is
bound to the reviewed bounded slice recorded in campaign 2's
`human-signoff.json`: two safe member-product flags only, existing admin
authorization preserved, account IDs scrubbed on purge, content-free audit
logs, and no deploy-workflow or release-canary mutation surface. Since
campaign 2 closed, the two open product decisions were answered (DD-9 widened;
new DD-13 — see "Product decisions raised (2)," above) and the great majority
of campaign 2's thirty-four findings were fixed directly in spec.md, plan.md
and tasks.md (see "Post-campaign disposition," above) — but none of that
correction work was re-reviewed by a fresh panel, because the cap forbids a
third campaign. The loop converged on evidence at every stage — every finding
above traces to a specific, verified repository fact, and every post-campaign
fix traces to a specific spec.md/plan.md/tasks.md edit named above — but the
package's recorded verdict stays `product-decision-required` regardless of how
thoroughly those findings are eventually addressed, because only a review
campaign can raise a verdict, and none is available.

**The residual risk, stated plainly, is now narrow:** the post-campaign
corrections recorded above — the resolution of both open product decisions,
the fixes to the great majority of campaign 2's findings, and the three
specific corrections this pass added (the Fly divergence risk-model text, the
`A4` injected-`OSError`/`PermissionError` degraded-read cases, and the
`E2`/`E7` next-interval poll-recovery assertion) — could not receive a third
panel's independent review before this feature lands, because the campaign cap
is two and campaign 2 already spent it. Every one of those corrections is
self-graded against the same rubric campaign 2's reviewers used, not
independently re-verified by a fresh oracle. No verified campaign-2 finding
remains deliberately unfixed; the residual is the lack of a third independent
panel over the corrections.

**Compensating measures:**

- Every reviewer across both Codex and Claude oracles — all six lenses in
  campaign 2 — certified against the identical artifacts digest
  `5856f5bffc96592e7833c1d6e6ed8462e36ec30153394809b0c4a28d16f22afd`, so the
  underlying finding list this acceptance covers is pinned to an exact,
  verifiable state of spec.md, plan.md, design.md, tasks.md and
  checklists/requirements.md, not a moving target — even though the artifacts
  have since moved past that digest to apply the fixes above.
- Implementation must pass the canonical CI job graph and the same Docker
  Compose stack production runs (`docker compose up --build`) with no bypass
  of the mutation gate or coverage floors before any PR touching this feature
  can land, per the `deploy-and-ci` skill and CLAUDE.md.
- tasks.md's **H2** pre-landing task requires an executed cross-layer
  acceptance pass covering both the web admin operator flow and the mobile
  `mobile_task_classification` propagation path before this feature is marked
  delivered, closing the gap between mocked-layer evidence and the real
  application seam.
- tasks A6, C10 and C11 give the degraded-document purge halt-and-retry
  (DD-13) and the undeclared-flag-entry scrub widening (DD-9) executable
  evidence, closing privacy-consent-security's and adversarial-high-risk's two
  blocking retention-purge-gap findings with tests rather than leaving the
  disposition assumed.
- `admin_portal`, `delivery_canary` and `external_agent_relay` remain
  structurally excluded from the runtime-manageable set (DD-1) — no code path
  in this feature can ever write a runtime entry for any of the three,
  bounding the blast radius of every finding above, resolved or residual, to
  the two authorized member-facing flags.

**The expiry is not decoration.** If this has not landed and been accepted by
2026-09-13, the gate closes and this package requires a fresh, bounded
campaign — governed by whatever cap policy is current at that time — before
any further planning-artifact change lands.
