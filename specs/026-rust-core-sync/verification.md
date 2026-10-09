# Specification verification

## Completion pass — 2026-10-09

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
