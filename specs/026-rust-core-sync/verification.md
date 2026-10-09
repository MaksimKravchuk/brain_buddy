# Specification verification

## Current owner acceptance — October 9

**Specification planning is complete; the planning verdict is approved.** After being shown the final [approval packet](approval.md), six-lens review, all four correction closures, the 12/12 protocol checklist, the passing [CI for 962a7fa](https://github.com/MaksimKravchuk/brain_buddy/actions/runs/37903755079) and [Claude re-review](https://github.com/MaksimKravchuk/brain_buddy/pull/305#issuecomment-6077167835), MaksimKravchuk explicitly answered “Yes” to accepting the prepared package and residual risks of custom sync, Rust/FFI and migration. The request retained complex-slice measurements before implementation.

The [human-signoff.json](evidence/026-native-20261009-1/human-signoff.json) record passes the existing `load_human_signoff()` validator for run `026-native-20261009-1` and unchanged core digest `968a327f01a50fb7e14ef84b1d73ab0731efbdd227d75fdeedbad5a394045623`. The exact reply, presented question, source commit and retained conditions are preserved in [owner-acceptance.json](evidence/026-native-20261009-1/owner-acceptance.json). The [accepted summary](evidence/026-native-20261009-1/accepted-summary.json) supersedes the former missing-human-sign-off escalation. Its approval follows the already authorized native route and the actual closed findings; no original reviewer report or earlier failed execution is rewritten.

Only decision/status records and this reading index change. Core requirements, plan, design, tasks, HTML and ADR proposal remain identical to the reviewed and approved source. Historical pending-approval labels in those frozen inputs now defer to approval.md. The original manifest's pre-acceptance approval.md hash is verified against source commit `962a7fa`, while all frozen core hashes still match current files. The existing slice-sizing, governance-enactment, implementation evidence and release gates remain conditions on later work, not unfinished specification decisions. No task is marked implemented.

Acceptance-record validation checks the current core digest, original report/closure hashes, all 12 reviewer checklist dispositions, valid current sign-off and refusal of mismatched run/digest, new decision-record hashes, relative links and Spec Kit structure. Exact-SHA CI for this metadata publication is recorded on PR #305; prior CI is evidence for its named commit only.

## Native review and closure before owner acceptance — October 9

**The requested review completed with 6/6 native Codex subagents. Four distinct important findings are corrected and independently confirmed closed.** The owner explicitly instructed the conductor to use native subagents instead of invoking a reviewer CLI. That instruction authorizes this panel after the failed CLI attempts and supersedes the CLI/adapter-only routing and campaign-cap objection for this requested panel. It does not approve content, design, residual risk or implementation. Historical CLI failure counts below are not the current review count.

Run `026-native-20261009-1` passed the unchanged Spec Kit preflight at source commit `7866bae27152da40b7c9c97f5e7a6c63870b48de`, core digest `5fdcc85f0496ce9dc68716d0cfd2442a065b446bd80143df180859fff354ea99`. The six required lenses used the existing rubrics and schema: requirements, architecture, testability, privacy, UX and high-risk adversarial review. Four sessions used `gpt-6.1-sol`/high and two used `gpt-6-astra`/high, all OpenAI. This is one-provider evidence, not six independent providers. Native tool selections and input hashes are recorded; no CLI/external-adapter oracle or OS-enforced read-only attestation is fabricated.

The initial aggregate was `technical-changes-required`: five important observations, deduplicated to four defects; privacy passed without findings. All six original reports remain unchanged in the [evidence index](evidence/026-native-20261009-1/README.md).

| Confirmed finding | Correction and closure |
| --- | --- |
| PR-53 depends on undefined web server decisions and omits the actual composer | Explicitly select the already-permitted versioned-vector transition. PR-02 owns synthetic rule-versioned examples; Rust/web tests share them; PR-53 owns TaskListPage and retains bounded presentation helpers while the existing HTTP server remains final domain authority. No unowned preview API or false helper-removal claim. Requirements reviewer confirmed closure. |
| Generic legacy command-key rejection contradicts accepted consent revoke | Preserve the narrow server-derived collision-revoke identity before ordinary mismatch rejection, retain the original grant receipt, publish through the common atomic transaction/feed, and keep a retry from revoking a newer grant. Flag-OFF behavior and the existing regression tests are assigned to PR-28/Q07. Architecture and adversarial reviewers confirmed closure. |
| PR-34 cannot own its necessary Cargo.lock change within five files | Own the lockfile, count six product files, and require complete measured runtime/SQLite sizing before boundary approval. No future LOC pass is invented. Testability reviewer confirmed closure. |
| Native AI sheets omit the accepted clarifying-question response | Add stable M/D-04.16–20, answer focus/actions, once-only notes command and save/inference phases, revision/current-consent rerun, separate failure/retry paths and interruption-safe drafts. PR-49/59/60 and Q09 own this existing capability. UX reviewer confirmed closure. |

The same five finding authors performed bounded closure and direct-regression checks at corrected core digest `968a327f01a50fb7e14ef84b1d73ab0731efbdd227d75fdeedbad5a394045623`. All five report resolved with no remaining finding in scope. These are targeted checks, not a second full panel or tests of unimplemented behavior. The [final summary](evidence/026-native-20261009-1/final-summary.json) records **technical review complete, all reported findings resolved**. High-risk implementation-gate status remains `escalated` solely because actual named-human residual-risk sign-off is absent; this is not a missing-review or CLI-provenance failure. The separate [owner decisions](approval.md) remain pending. The original architecture, testability and UX reviewers also recorded explicit item-level dispositions for all 12 [protocol quality criteria](checklists/protocol-quality.md); all are satisfied for written requirements only, with their reports retained in the same evidence directory.

Validation on the corrected planning artifacts:

- `make check-specs` and `make validate-ci` passed during the socket-enabled `make verify-all` attempt. The default sandbox first blocked loopback sockets; the allowed rerun then stopped at backend lint because `ruff` is not installed. No full local product-suite pass is claimed.
- Direct v2 map/dependency/path checks pass: 60 slices, 60 unique task assignments, 34/34 FR+SC IDs and product-file caps including PR-34's lockfile. Caps remain unmeasured future implementation boundaries.
- All six original reports pass the repository JSON schema and `validate_review`; all five closure reports bind to the corrected digest. Original and corrected input hashes plus saved evidence hashes are included.
- Static HTML parsing passes: balanced tags, unique IDs, five valid local anchors, 74 explicitly typed buttons, no scripts/external assets; design inventory has 55 paired rows / 110 combinations. Browser/native rendering and accessibility are not asserted.
- Relative Markdown links and `git diff --check` pass. No implementation task is checked complete, and no accepted policy/harness/application code changed.

Exact-head CI for the subsequent published commit is recorded on PR #305. The earlier passing [run for 7866bae](https://github.com/MaksimKravchuk/brain_buddy/actions/runs/37899717042) and [Claude review](https://github.com/MaksimKravchuk/brain_buddy/pull/305#issuecomment-6076565682) apply only to that earlier source commit. Prior failed CLI attempts and their original escalation are retained below as history; the current native review method and count above supersede their former routing/cap blocker.

## Historical completion pass — 2026-10-09

Scope: finish the existing planning package from merged PR #304/main `c16daecd13247e35fea280bd9322c8a4b09dabb1`. Only files under `specs/026-rust-core-sync/` change. Accepted constitution/ADRs, application code, schemas, credentials, CI and production are untouched. No task checkbox is marked implemented.

### Authored outcome

Added the logical data model, exact command/writer catalog, runtime/FFI contract, concrete wire/error/transfer envelopes, planned validation guide, and 57 bounded proposed PR slices. All 26 FR and 8 SC IDs have slice coverage, each task appears exactly once, dependencies pass the structural validator, and budgets are at most 390 product lines/8 files. Budgets remain implementation caps to measure, not a claim that future code has been sized empirically.

The contract completion corrected complete Review projection requirements, the stalled count outside Next, Smart Add identity aliases, and account-less merge identity. Existing large archive/tag/bulk operations use bounded immutable transfer chunks with atomic application instead of an incompatible 500-row product cap. Restore/purge metadata is bounded by recoverable restore points. The accepted legacy response, receipt-ordering, source-TTL and post-reset fresh-intent guarantees remain.

### Checks and limits

| Check | Current result |
| --- | --- |
| Official CLI version in isolated uv environment | PASS: repository-pinned `github/spec-kit@v1.0.11`, `specify version` reports 1.0.11; no installed project assets refreshed |
| Existing-feature prerequisite / plan / tasks / checklist setup | PASS with `SPECIFY_FEATURE_DIRECTORY=specs/026-rust-core-sync`; existing plan preserved in place |
| `make check-specs` | PASS; 247 validator tests, 246 passed and 1 normally skipped; artifact/manifests/gate checks pass |
| Shared design authority tests | PASS, 6 tests; unchanged mock remains static design evidence |
| Slice coverage / relative Markdown links / `git diff --check` | PASS: 34/34 FR+SC, 57 unique tasks, no broken relative links or whitespace errors |
| `make verify-all` | Attempted; passed spec checks and reached `validate-ci`, then local production-smoke unit tests could not create sockets in the sandbox. This is not a passing full-stack result. A separate local-socket-capable `make validate-ci` rerun passed, including the local production-smoke unit tests; no production endpoint was used. |
| HTML runtime rendering | Not verified. Default sandbox blocked Chromium startup; an allowed launch then hit the browser's local-file navigation restriction. No screenshot, geometry or native accessibility pass is claimed. |
| Product acceptance / migration / deployment | Not run: this request produces specifications. Q01–Q12, benchmark and restore procedures are future implementation gates. |

### Canonical planning review

The `speckit-review` skill was read and its canonical harness used. Preflight passed for run `026-completion-20261009-1`; risk derives **high**. The [machine summary](evidence/planning-review-summary.json) and [artifact manifest](evidence/planning-artifacts.json) preserve the actual digest. Aggregation is **escalated**, with **0/6 reviewer lenses run**, no invented findings, and no human sign-off.

Automatic approval review rejected launching the Codex CLI panel, first citing uncertain external disclosure and local report writes, then specifically the uncommitted additions being sent to OpenAI Codex. GitHub API confirmed the repository is public and the canonical command uses a read-only reviewer sandbox; those facts did not resolve the second rejection. The owner subsequently directed review to GitHub. No further local CLI panel is requested, and no alternate reviewer or hand-written approval is substituted. Local JSON evidence writes by the harness are distinct from product edits.

The committed manifest and summary are historical evidence for their recorded digest, not a review of the later PR corrections below. A future admissible campaign must bind all six configured lenses to the current artifacts, aggregate actual findings and record provider/model correlation and any degradation. Ordinary GitHub PR reviews are not silently treated as that formal campaign. Human design/governance/slice approval and the high-risk run/digest-bound sign-off are separate decisions in [approval.md](approval.md).

### Cross-artifact analysis

Read-only `/speckit-analyze` passes were applied to requirements, user stories, entities/transitions, plan dependencies, task coverage and constitution constraints after task generation. Structural coverage is 100% (34/34); unmapped tasks: 0; duplicate task ownership: 0; unresolved template placeholders: 0. The complete machine-readable requirement-to-task map is in tasks.md rather than duplicated here. This is author analysis, not independent review.

| Finding | Classification | Disposition |
| --- | --- | --- |
| Coarse stages lacked implementable boundaries, owned paths and coverage | Technical completeness | Replaced with proposed v2 PR map; all-writer/fence prerequisites precede pilot, PostgreSQL follows pilot |
| Model/API projection, alias and oversized-effect gaps | Technical contract consistency | Resolved in data-model and contracts; validation scenarios named in quickstart and slice map |
| Constitution IV and Apple dependency policy prohibit parts of the proposed implementation until amended | Governance gate | Exact narrow proposal in adr-draft; accepted policies remain unchanged; implementation blocked pending actual acceptance |
| New conflict/recovery UX and high-risk plan lack human sign-off | Human gate | Concrete baseline and status in approval.md; not inferred from the earlier PR merge |
| Mandatory panel did not execute | Review evidence gate | Escalated; owner selected GitHub PR review, no formal campaign pass claimed |

The optional after-tasks acceptance and after-analyze product-report hooks are not run: no product was implemented. A custom reviewer-owned protocol-quality checklist is supplied and remains unchecked until a reviewer evaluates it; this is distinct from the completed built-in requirements-quality checklist. The historical evidence below is retained for provenance and is not current-candidate evidence. The old ChatGPT Page was not updated by this repository task.

## PR #305 review corrections — October 9

Reviewed candidate: `a24f5e8a4434a023eb3800ac5fd3a3390a504ddf`. [Codex P2](https://github.com/MaksimKravchuk/brain_buddy/pull/305#discussion_r4227075130) and [Claude review](https://github.com/MaksimKravchuk/brain_buddy/pull/305#issuecomment-6075260212) are actual GitHub reviews; Claude explicitly reports a targeted read and no local validator execution.

| Finding | Resolution |
| --- | --- |
| A 60-second polling interval leaves no transport/application headroom for SC-004 | Active poll starts are at most 30 seconds apart including jitter; the unchanged ≤60-second end-to-end deadline includes requests, catch-up and visible application. The acceptance procedure forces a commit just after a completed poll and the longest allowed interval with all hints dropped. Spec, contract, plan, research and tasks agree. |
| Five versus six review lenses | All current feature gates name six lenses: five standard plus the high-risk adversarial lens. Historical review evidence remains unchanged. |
| Checklist task numbering appears out of order | The dependency section now explicitly distinguishes story-grouped checklist order from the topologically ordered JSON map and its executable dependency edges. |
| Rust/FFI size caps lack empirical evidence | PR-04/05 now own their Cargo.lock deltas and count the extra product file. PR-03/04/05 boundary approval explicitly requires disposable sizing evidence, including complete dependency and packaging inputs; an over-budget result requires a revised map. A docs-only diff cannot demonstrate future bridge size. |

The sizing spike is not executed: neither cargo nor rustc is available on this environment's PATH, and this session completes the specification, not the proposed bindings. Its result remains a visible prerequisite to approving those implementation boundaries; no empirical size pass is claimed. The existing 60-second persistent-failure UI threshold is retained and explicitly distinguished from polling and convergence timings.

Correction validation: `make check-specs` passed (247 tests, one normal skip); direct v2 dependency/path validation, 34/34 requirement coverage, 57 unique task assignments, Rust/FFI product-file counts, relative Markdown links and `git diff --check` passed. These checks validate the specification, not future implementation size or timing. Exact-SHA CI and subsequent reviewer results are recorded on PR #305. Product implementation, migration, deployment and owner sign-off remain outside this documentation correction.

## Historical requested CLI review — October 9, attempt 2

The owner explicitly requested the formal review after the PR corrections. The canonical [speckit-review skill](../../.specify/agent-commands/speckit-review/SKILL.md) was applied to published source commit `a060ddd531753b3ed8bcd339ea8cc8a907ac6d7c`. Preflight passed for `026-completion-20261009-2`, with high risk and artifact digest `cf9c1d1ce0c04793a293a38459e2567f528bb71eb89e3f8c7f5182638416fd17`.

All six configured read-only Codex CLI processes were launched. Each failed to connect to `wss://chatgpt.com/backend-api/codex/responses`: `HTTP CONNECT failed with status 403`. The clients fell back to HTTPS and waited for network access without producing a review. A separate credential-free HEAD request confirmed the proxy CONNECT denial. The six owned blocked processes were stopped; the harness returned failure for every role. The earlier automatic-approval execution rejection is not the blocker for this attempt: the managed environment's destination policy is.

The canonical aggregation is **escalated, 0/6 completed reviews**, no findings or human sign-off. This does not mean there are no defects: no model verdict was obtained. The full process stderr remained captured until process exit, so earlier progress messages about running processes did not establish that reviewers had reached a model or read the specification.

Evidence:

- [Preflight context](evidence/026-completion-20261009-2/planning-context.json)
- [Canonical summary](evidence/026-completion-20261009-2/planning-review-summary.json)
- [Per-role execution failures and log hashes](evidence/026-completion-20261009-2/execution-failures.json)

The preflight inputs remained unchanged while the hosted audits below ran; their subsequent fixes change the digest. Attempts 1 and 2 remain immutable historical evidence, both escalated with no completed canonical reviewer reports. No third canonical campaign, fallback approval, changed network route, altered gate or invented sign-off is introduced. The skill's hard two-campaign cap now applies: land the fixes and stop, retain explicit open lanes, or obtain a real complete founder-acceptance record. Enabling the required destination through the supported environment configuration would resolve a connectivity prerequisite only; it would neither reset that history nor grant approval.

## Earlier hosted content audit and finding closure — October 9

After the CLI destination denial, six actual hosted read-only reviewers audited the unchanged `a060ddd` core digest `cf9c1d1ce0c04793a293a38459e2567f528bb71eb89e3f8c7f5182638416fd17`. Four used `gpt-6.1-sol`/high and two used `gpt-6-astra`/high. All share the OpenAI provider; separate sessions do not establish six independent providers/models. The [audit evidence index](evidence/hosted-review-20261009/README.md) preserves their original schema-valid reports and runtime selection metadata. These reports are not installed as canonical CLI or external-adapter results.

There were eight important observations, deduplicated to six defects, and one advisory. All were corrected in the planning package:

| Finding | Correction and planned evidence |
| --- | --- |
| Smart Add aliases disappear after 24-hour receipt redaction | Typed content-free `id_bindings` survive until purge and remain available to authorized dependency recovery. Q10/PR-50 combine lost ACK, extended offline time and renamed classification with the original dependent envelope. |
| Selected SSE transport has no contract/server owner | The authenticated route, content-free events, per-connection authority, shared committed-counter publisher, generations, bounded queues and reconnect are specified. New PR-58 feeds PR-40; SC-004 traverses the actual stream across separate writer/stream processes. |
| Sync errors omit accepted wrong-owner 404 semantics | Unknown and foreign resources share owner-safe 404; 403 is limited to policy failures in an authorized scope. Preauthorization errors disclose no scope/generation. Q05 and authority/API/SSE slices cover equivalence. |
| Apple AI slice points to transcription instead of the Weekly Review journey | PR-49 owns the shared suggestion model; PR-59/60 own actual iPhone/Mac entry points and consent/proposal/apply sheets, acknowledged as proposed additions. The pilot depends on both. Their caps remain subject to measurement before boundary approval. |
| Conflict descendants lack actionable resolution states | Added conflict .11–12 with preserve/reapprove/discard choices, exact copy, focus and interruption behavior; static mock and Q02/Q12 agree. |
| AI cancellation/interruption lacks visible outcomes | Added AI .13–15 with truthful sent-data copy, live-request reopening, explicit retry after process loss and late-result rejection; Q09 and the mock agree. The full inventory now has 100 combinations. |
| PR-08/10 Swift filters select nonexistent suite names (advisory) | Filters now name `ReducerProjectTests|ReducerTagTests` and `ReducerSubtaskTests|ReducerCommentTests`. Declaration inspection verifies those suites exist; actual execution remains an implementation check. |

Four original reviewers performed bounded closure checks of those specific corrections. Every distinct important finding is resolved in the text, with no consequential defect reported in the fixes. The [closure reports](evidence/hosted-review-20261009/README.md#targeted-closure) bind to corrected core digest `5fdcc85f0496ce9dc68716d0cfd2442a065b446bd80143df180859fff354ea99`. They are targeted rereads, not a fresh full campaign or approval of unimplemented behavior. The original `changes-required` reports remain unchanged.

Current structural checks pass: 60 unique tasks/slices, 34/34 requirements, valid dependency/path map and declared product-file counts, relative Markdown links, six original report schemas, and `git diff --check`. Static HTML parsing confirms balanced tags, unique IDs, 67 explicitly typed buttons and 50 paired rows / 100 combinations. Rendering, native accessibility, timing, FFI sizing and product acceptance remain unverified. Accepted governance, all human approvals and canonical implementation permission remain pending; no task is marked implemented.

`make verify-all` was attempted for these corrections. The default sandbox again prevented loopback sockets in the production-smoke unit tests. A socket-enabled rerun passed the complete `check-specs` and `validate-ci` stages, then stopped before backend lint/tests because `ruff` is not installed (`Error 127`). This is not a passing full local product suite. No production endpoint, release or migration was invoked. Exact-SHA GitHub checks for the published correction are recorded on PR #305; previous `a060ddd` CI is not evidence for this new commit.

## Historical verification — October 8

Date: 2026-10-08. The subject is the documentation package, not a Rust or new-sync implementation. Product code, data, credentials, CI configuration, and production are unchanged. The owner's English-only documentation rule is recorded in `AGENTS.md`.

## Results

| Check | Result |
| --- | --- |
| Baseline `python3 scripts/check_spec_kit_specs.py` before changes | PASS |
| Feature-number reservation | 026 was free across all available local git refs; a separate branch/worktree was created |
| `make check-specs` on the initial specification | PASS: 247 unit tests in existing validator suites, 246 passed and 1 normally skipped; artifact/manifests/integrity and existing requirement coverage checks passed |
| Shared design reference tests | PASS, 6 tests; this is not runtime verification of the new screens |
| Design vocabulary and HTML structure | PASS after removing extra reorder UI and aligning sign-out/import; 8 screen IDs, 90 enumerated states, no external resources |
| Internal Markdown links and FR/SC IDs | Checked in the completed package |
| `git diff --check` | PASS |
| Browser rendering | The Chromium/Playwright attempt failed because the sandbox denied `setsockopt` during crashpad startup. iPhone geometry, screenshots, and runtime accessibility are not claimed as verified |
| Backend/native/new-sync product tests | N/A for the spec-only outcome; criteria for the future implementation are recorded in the plan and contract |

`make verify-all` and release/production smoke were not run locally: this work does not implement or release the described product. PR CI subsequently passed on `2e92e463efb0430c61c7c92b052a065f0d55e7c9` ([run 37837009146](https://github.com/MaksimKravchuk/brain_buddy/actions/runs/37837009146)); this is evidence for that revision only. Formal Spec Kit planning review, human design sign-off, ADR acceptance, and PR-slice approval are still outstanding and are not replaced by a passing validator.

## Independent review

A separate agent performed a read-only audit of current code. The package accounts for the already shared Mac/iPhone kit, JSON store and cross-process lock, local/server ID mapping, 24-hour legacy task receipts, Review clocks without revision bumps, archive semantics, and separate Identity/CRT authorities.

A separate adversarial protocol review found three consequential defects. All were fixed, and a targeted reread confirmed their resolution:

1. An ACK could update the confirmed base across a missing multi-record transaction. Only a sequential feed or consistent snapshot now changes the base; ACK retains `accepted_awaiting_feed` until inclusion is proven.
2. A delayed pre-restore response could apply after reset under the same session. Every response is now fenced by workspace/session/local-sync/server generations.
3. An old backup could restore purged data or a revoked session. Restore remains closed until subsequent purge/revocation decisions from a separate control ledger are applied; unproven reconciliation cannot reopen access.

This is substantive review of the text, not official five-lens approval or proof of correctness for code that has not been written.

## PR review corrections

[PR #304](https://github.com/MaksimKravchuk/brain_buddy/pull/304) identified two further contract contradictions, both confirmed against the accepted contracts and addressed in `contracts/sync-v1.md`:

1. Entity IDs retain their accepted per-field prefixes, including all six client-created Review ID forms. A sync command's bare UUID does not replace an entity's wire shape. The validation scenarios now require new-runtime records to pass legacy body/path validators.
2. Receipt lookup precedes the active-device-epoch check. An authorized retry can read the retained outcome after its epoch closes; only unseen commands require an active epoch. Current authorization and restore-generation checks remain mandatory. The validation scenarios cover a lost response followed by epoch closure, unknown-command rejection, and revoked access.

The smaller review notes about pending dependencies and account purge are already covered by contract sections 4 and 6: unresolved dependencies return `DEPENDENCY_PENDING`, and account purge removes all receipts. They do not change the agreed behavior. CI and review evidence for subsequent revisions is recorded on the PR.

A follow-up review identified an overbroad device-epoch requirement at the common write boundary. The contract now limits device registration to the new sync ingress. Legacy adapters retain their existing authenticated principal and stable replay identity; internal jobs use trusted execution authority, durable effect IDs, and lease fencing. Both still publish through the shared receipt/feed transaction. Caller-controlled origin fields cannot exempt a device command from epoch checks. Validation scenarios cover each writer, retries, forged origin, and a stale worker.

The subsequent sequencing review found that T007/T011 depended on job authority/fencing scheduled only in T012. T012 now runs first in Phase 3, through the existing compatible task ports, before T007 connects internal writers. The migration plan and pilot gate require verified authority/fencing and receipt/feed coverage for every writer; no new sync cohort starts while a scheduler still bypasses the feed.

A further receipt-ordering review found that mutable version/schema/size validation could prevent recovery of a retained outcome. Current authority and bounded generic envelope parsing now precede receipt matching; only unseen commands face current execution rules. Version retirement retains bounded parsing/fingerprint compatibility and authorized result lookup for retained receipts, without allowing retired commands to execute again.

The retention review found that a proposed 30-day full-response window contradicted the accepted 24-hour task/Review content bound. Full response bodies now expire within 24 hours, including when the owner is inactive or the Review flag is off; only content-free outcome/deduplication metadata survives until account purge. Capture and CRT exceptions retain their separate scope.

The independent retention/compatibility audit also applies source deadlines to every feed/snapshot/receipt copy, preserves legacy Review matching-record responses and Capture commit recovery, and retains Review progress merge and bulk per-item skip semantics instead of imposing universal revision conflicts. The ADR and T001 explicitly identify the proposed Constitution IV command-identity amendment and content-free metadata retention decision as prerequisites to implementation, without claiming acceptance.

The reset/read-model review identified two further gaps. Ordinary snapshot resets now retain an active device epoch; explicit closure preserves the old queue while permitting fresh local work in a durable pending-registration epoch, with idempotent authenticated registration and generation fencing before transmission. Snapshot activation preserves edits made during download. The feed and snapshot now explicitly enumerate the complete public Review projections, including sessions, decision queues, decisions, bulk releases, park acknowledgments, and current consents, while keeping protected/server-only storage fields private.

## Reading copy

The main reading copy is the [specification in ChatGPT Pages](https://chatgpt.com/space/page_1c47ad1be37c819187af9b4e5707d966). The Page is private, without a Space/parent; broad sharing was not enabled. Saved content was read back and its native headings, requirements, and diagrams checked. A preview of the Page on an iPhone is unavailable; the separate HTML mock also has no successful runtime verification.
