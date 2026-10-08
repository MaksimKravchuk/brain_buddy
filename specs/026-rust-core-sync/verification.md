# Specification verification

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

## Reading copy

The main reading copy is the [specification in ChatGPT Pages](https://chatgpt.com/space/page_1c47ad1be37c819187af9b4e5707d966). The Page is private, without a Space/parent; broad sharing was not enabled. Saved content was read back and its native headings, requirements, and diagrams checked. A preview of the Page on an iPhone is unavailable; the separate HTML mock also has no successful runtime verification.
