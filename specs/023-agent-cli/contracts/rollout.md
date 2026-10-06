# Rollout and rollback contract

Dedicated proposed decision: docs/decisions/0028-runtime-managed-cli-authentication.md. Owner planning approval must explicitly cover its narrow amendment of ADR-0019; no accepted ADR is silently edited.

The initial release adds a reader for the five existing required rows plus optional cli_auth, missing optional row→OFF without insertion/degradation. Strict failures remain for required-row absence/corruption, malformed optional rows and unknown rows. Every seed/upgrade/read/unrelated mutation/scrub/metadata write preserves optional absence; current mutate upserts all MANAGED_FLAGS entries and must be corrected narrowly.

No CLI row or grants before the compatible main/Fly release completes successfully. Record its exact deployed SHA/image and passing release as oldest rollback floor. Only then existing authorized admin mutation creates/enables cli_auth for intended account/cohort and reads it back. The same candidate supports two activation stages; there is no separately released partial API or additional PR boundary.

First deployment failure may restore predecessor because physical inventory/grants are unchanged. After activation, subsequent rollback must use a compatible image supporting cli_auth and grant purge. OFF blocks new/unconsumed approval; it does not silently revoke issued sessions. Existing revoke controls do that. Flag scrub stays fail-closed and hard deletion includes new grants.

Source configuration includes reviewed fly.backend.toml BRAIN_BUDDY_CLI_VERIFICATION_ORIGIN=https://brain-buddy-frontend.fly.dev through normal release. This is a source change, not permission for an ad-hoc deploy. Compose passes a per-run trusted frontend origin; scripts/run_playwright_e2e.sh derives its isolated frontend URL, then enables/reads back cli_auth for synthetic accounts through existing operator API. Production activation is separately gated on verified compatible release and recorded actor decision.

Tests prove absent optional row survives all writes, old-reader rollback after initial failure, subsequent six-row rollback plus account purge, no grants before exposure, malformed stores remain degraded, startup/periodic cleanup with OFF, and actual intended-account exposure. Reconcile any newly landed flag inventory before freeze.

Reviewed ADR source SHA-256: b98e06c46598119f0fc74df9a9caae718b852fe41c4475ae79d5cfb3d31b5604. Editing that proposed ADR requires updating this reviewed binding and rerunning preflight.
