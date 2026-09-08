# Planning review resolutions

Campaign 1: completion-ui-20260906-1. Actual aggregate status: escalated. Five standard lenses ran; the automatically derived high-risk lens was missing. No approval is claimed. Its sole high-risk path was a reference to the unchanged design-validator script, not an intended changed file. That executed diagnostic command is now retained in local logs rather than the design authority section. The actual frontend scope is not lowered or concealed; the second preflight will classify the amended artifacts afresh.

## Requirements, architecture and evidence

- Clarify the exact existing control: Show completed drives both terminal flags today; replacement Show cancelled controls cancellation only and deliberately removes hiding completed tasks.
- Explicitly identify the narrow web exceptions to spec 011 FR-029 and FR-030 and ADR-0006. Native/API behavior and open-only counts remain unchanged.
- History choice follows the owner's explicit request that completed work remains visible and their latest exclusion of search/filter scope: all fetched completed tasks, no newly invented history limit. Existing mixed 50-row pages are accepted as existing query behavior; unfetched open tasks can require Load more. This is now explicit, not a claim that pagination has separate budgets. Agent-summary limits remain unchanged.
- Actual state/project/tag/search matrix, filtered reload, grouped order, empty heading, completed-only, loaded page, detail/reopen, mixed save outcome, motion timing and no-motion cases are named in plan/tasks.
- Existing task-management and shell tests that expect disappearing completed tasks or Show completed are named for narrow updates.
- Acknowledgement timing is observable without arbitrary sleeps; no success before save, <=600ms duration and reduced-motion immediate placement. Concurrent acknowledgements replace visual animation only; displaced buttons hit-test at their transformed position.
- Dependency repair precedes product RED tests. Writer evidence and independent exact-candidate review/QA are distinct.

## Privacy and evidence

- The widened list cache gets account/origin query scope and captured-scope canonical list patches. The focused first-paint and late-acknowledgement test prevents previous-owner completed history from entering the current list. This is a bounded task-list concern, without changing authentication endpoints or broad unrelated cache policy.
- Production verification reuses a clearly synthetic existing canary task, then explicitly reopens it to its original destination and verifies read-back. There is no task erase endpoint; no erasure or new synthetic-record cleanup is claimed.
- Evidence has a closed field list in plan.md; crop to synthetic rows and exclude real task/account content. A seeded admin is not presumed synthetic-only.
- Product guardrail is exactly-one row after canonical completion/reload, canonical state matches UI, then verified original open state restoration.

## Dependency prerequisite

Main's grouped dependency upgrade breaks the existing frontend before UI implementation. Eight direct constraints restore demonstrated compatibility. A Node20 baseline of 986 tests, coverage/taxonomy, type/lint/build and Docker npm10 build was established.

Advisory comparison found HEAD production 0/full 2 moderate; the initial Allure compatibility pin introduced an adm-zip advisory. Allure 3.15 also fails the Node20 canary, so a precise scoped Allure -> adm-zip 0.6.0 override removes that regression. Final production audit is 0 and full audit is exactly the same two moderate findings as HEAD (qs/typed-rest-client). ZIP roundtrip and the actual repository Allure canary pass; Docker npm10 build and Node20 npm ci pass. Unrelated advisory remediation is outside scope. Evidence lives outside the candidate under work/dependency-audit; independent dependency review is separate from the repair author's report.

The repair is not tooling-only: React Query is runtime code; restored compiler/linter versions affect semantics. No gate threshold or runner is changed. One executable candidate is the minimal delivery unit; rollback uses the previous deployed images, not a rebuild of broken HEAD. A later UI-only forward revert must preserve the repair.

## Owner-resolved release exposure rule

The owner replied on 2026-09-06: «Флаг не нужен. Это потому что уже, по идее, так-то давно было бы быть. Давай мы зафиксируем, что флаг нужен для каких-то значительных новых фич, типа агентского харнеса, брейндампа, current reality 3. Вот там вот будут флаги.» This explicitly approves no new flag for the completion correction and directs a general policy update for significant new capabilities. The faithful rule is recorded in AGENTS.md, ADR-0022 and the delivery runbook. Existing feature gates and all tests/review/verified delivery/rollback requirements remain intact. delivery_canary stays release-smoke-only. This owner decision resolves the rollout product point; it is not a fabricated passing review verdict or founder acceptance of other findings.

## Campaign-two technical follow-up

Campaign 2 produced requirements-consistency and testability-evidence reviews with changes-required. The three Claude lenses failed because their previously configured authentication was unavailable; no pass is claimed. Technical findings were addressed in the planning artifacts: supported-browser motion has no silent immediate fallback, delivery repair is explicitly in candidate scope and SC-004, the owner policy is a new superseding ADR-0022 while ADR-0008 remains historical, account-switch isolation is in FR-003/SC-004, and tasks now identify US1, concrete RED paths, all FR/SC markers, requirement-coverage validation and repeated-tap/transformed-hit-target checks. These edits make the original campaign-two artifact digest stale; they do not turn its verdict into approved. No third campaign or fabricated founder acceptance is created.

## Owner-directed continuation, 2026-09-08

After disclosure of the incomplete planning review and the proposed bounded continuation decision, the owner instructed: «ты оркестратор. Гоняй маленьких агентов пока фича не будет готова». This continuation instruction is the authorization basis for founder-accepted closure through 2026-09-13, with the previously disclosed targeted tests, full verification, independent implementation review/QA and standard release gates retained. This is an interpreted authorization to continue, not a claim that the automated panel approved the amended plan. Both original escalated summaries, the missing Claude lenses, stale Codex findings and preparatory attempts remain recorded in planning-review-closure.json. The owner also clarified overlapping project/tag/search views of one canonical task; this is included in the current scope.
