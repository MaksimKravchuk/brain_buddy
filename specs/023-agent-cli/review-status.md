# Planning review status

Date: 2026-10-06. Product implementation, native binaries and publication have not started. External Codex login is unnecessary and is no longer a prerequisite.

## Campaign history

1. cli-023-r1: escalated, high risk, valid reviews0/6. The separate reviewer CLI failed authentication; no missing review is counted as a pass. [Actual summary](review/campaign-1-summary.json).
2. cli-023-r2: all six native reviewer sessions ran against unchanged digest2c189ad0a6c54769e0f5c3904757a4a14a46add1a1e021e9327a9ff3ab733511. Every original verdict was changes-required, with20 findings and no product decisions. [Original reports](review/campaign-2-initial/) and [actual harness summary](review/campaign-2-summary.json) remain unchanged. The harness reports escalated because its unchanged oracle schema cannot represent this native transport and no high-risk human sign-off exists. No external adapter/executable pin or independent-provider provenance is invented.

The owner rejected a separately authenticated Codex reviewer while pointing out that this is already Codex. That steering overrides the execution-channel/adapter requirement narrowly. [Native execution record](review/native-execution.json) identifies actual session names and requested model; actual provider/model identity remains unverified and the panel is correlated. Gate code, risk classification, human authority and original verdicts were not rewritten.

## Corrections and bounded verification

During the frozen review, origin/feat/modern-auth@bc7fc72c35b7bf794eff912c07bdd38a1d1f0816 became available, while main advanced to21f08d26698a434f7b1d16b991b2b43d4e0ea0f2. Published modern-auth is not claimed landed/deployed. The following implementation-owned corrections are represented in the current plan:

- Extend accepted modern Identity AuthStore/auth.sqlite3 with atomic device consumption/session issuance, version and provider lineage, rollback/replay rules and existing purge/expiry/export ownership. Remove the obsolete JSON/flock/fsync design and tests.
- Require the landed shared-auth implementation base, completed modern-auth release/import and a SQLite-capable predecessor before CLI release. Preserve task_mcp and all six required flags; cli_auth is optional seventh, activated only after the separate CLI-compatible rollback floor.
- Reserve unique ADR-0029 and update its rollout hash. Capture and clear the browser code before login; retain only its short code/deadline in bounded tab storage, returning through exact /cli/authorize across existing methods.
- Wire unfiltered feature023 requirement coverage into Makefile/check-specs and the corresponding integrity invariant, including Rust test discovery. Restrict generic dispatch to member business roots, keep auth/account/operator flows specialized, and reject generic-write field selectors before dispatch.
- Document macOS15 on both architectures, with native minimum-OS and released-installer evidence required. Correct generic quickstart to /tags while auth status retains /auth/me.

[Six bounded correction reports](review/campaign-2-corrections/) reviewed snapshotc5778eef47ef975a22cdd239ad289973151f6a9b07d422ecbf3269bd4a9e8ddd. Five passed; requirements found the remaining generic quickstart contradiction. Its final limited verification passed after the quickstart-only change at digest28073fd7e1991aa4c27141ba0c0ed9bbe8e0f7eb100b6104829ac0c8a80498d5. The original reports and intermediate changes-required verdict are retained. These are bounded finding-closure checks within campaign2, not a third campaign or software/native/release evidence. Reports from the prior snapshot are not stamped with the final digest.

## Remaining authority

Current artifact digest:28073fd7e1991aa4c27141ba0c0ed9bbe8e0f7eb100b6104829ac0c8a80498d5. No technical finding or product decision remains open within those verification scopes. High-risk planning acceptance is still pending; no human-signoff or founder-acceptance record has been fabricated. The two-campaign cap is reached. [Concrete approval packet](review/approval-packet.md) proposes bounded founder acceptance for isolated implementation and testing, including ADR-0029, with compensating measures and expiry.

Only approved or honestly recorded founder-accepted permits implementation under speckit-review. Exact-SHA implementation review/QA, required CI, ASK landing and production/binary publication are subsequent concrete gates. No authorization for production is inferred from approved UX or reviewer agreement.

Spec artifact completeness, deterministic defects, manifest consistency, gate integrity and diff formatting are planning checks. Native builds, installation, shared-login journeys, production smoke and publication remain unpassed.
