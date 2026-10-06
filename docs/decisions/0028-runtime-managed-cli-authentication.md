# ADR-0028: Runtime-managed CLI authorization and compatible activation

Date: 2026-10-06
Status: Proposed; requires owner acceptance of this reviewed plan before implementation
Amends: ADR-0019 only for the cli_auth inventory entry and its optional-OFF pre-activation state
Preserves: ADR-0001 Identity ownership/opaque sessions, ADR-0008 release authority, ADR-0022 significant-feature flags
Related: specs/023-agent-cli/ and ADR-0025 runtime-managed CRT rollout

## Decision

BrainBuddy owns a provider-neutral device approval issuing a distinct existing opaque session. Provider login/account linking remain the shared Identity authority. CLI access has the runtime-managed cli_auth flag, default OFF; it does not authorize an unauthenticated account.

The current five baseline SQLite rows remain required. cli_auth is optional before activation: absence resolves OFF without degrading existing flags. A malformed cli_auth row, any unknown row, or any missing/malformed required row remains degraded/fail-closed. Do not weaken the account purge's existing flag-scrub gate.

Use two persistence activation stages in one candidate:

1. Deploy a compatible reader and grant-purge support through normal exact-SHA ASK release. No seed, upgrade, read, unrelated mutation, cohort scrub or metadata refresh creates cli_auth's row. General flag writes retain absence; only an explicit cli_auth mutation may insert it. Anonymous start and device operations remain unavailable before activation, so no grants are persisted yet.
2. After that release succeeds, record its exact SHA/image as the oldest permitted rollback image. Only then may the approved operator explicitly create/set cli_auth using existing runtime flag mutation and read back intended exposure. All subsequent image rollbacks must understand the optional/sixth row and device-grant cleanup. Flag OFF is immediate exposure rollback; existing session revocation remains separate.

This does not require two PRs: the persistent row/grant boundary, not branch count, determines safety. Initial deployment failure may restore the old image because the volume still has only its original rows and no grants. Later deployment failure restores a compatible captured image. Do not enable during the first deployment's in-flight smoke; a successful compatible baseline is a release prerequisite, not an inferred property of a submitted branch.

Identity owns bounded expiring grant JSON and a shared reentrant process/file authorization lock with session mutations. Account markers/source-session revoke prevent issuance; hard purge erases account associations. Grant security material is excluded from server exports, like session verifiers. Logical expiry is600 seconds; existing startup/periodic privacy sweeps physically remove records independently of exposure. No business repository migration, provider credential store or new release authority.

## Verification and acceptance

Before acceptance, plan tests for five-row initialization, every unrelated write/scrub preserving optional absence, valid optional-row off/selected_users/on resolution using the existing FlagMode/API vocabulary, malformed/unknown-row degradation, initial failed-deploy old-reader compatibility, and later rollback/purge on six-row volume. Verify no grants before activation, production baseline SHA/release success, effective cohort, OFF recovery, separate-session revoke and account-purge readback. Exposure changes block newly admitted operations; previously admitted operations may complete, with final exposure/expiry/source/user checks deleting a newly minted session on failure. Flags are not the session-revocation authority. Runtime inventory changes remain ASK/high and need recorded review/landing/release evidence.

The five-row baseline must be reconciled with any newly landed feature inventory before candidate freeze; do not delete or hide another feature's required row.
