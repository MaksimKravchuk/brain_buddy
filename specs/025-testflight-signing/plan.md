# Implementation Plan: Reusable TestFlight signing identity

**Branch**: codex/025-testflight-signing | **Date**: 2026-10-07
**Spec**: [spec.md](spec.md) | **Risk**: ASK / high (CI/CD and signing credentials)

## Summary

Reuse the existing upload path. Add two environment-secret checks and one Bash
installer under `ios/ci/`; import before archive, retain current provisioning
and distribution export, and extend always-run cleanup. Update `ios/README.md`.
No app, widget, backend, frontend or domain code changes.

## Technical Context

Bash, system `security`, `base64`, `openssl` on macos-26; standard-library Python
unittest mocks for deterministic failure evidence. No new runtime dependency.

## Constitution Check

Consent: the owner explicitly approved uploading bundle/private key and password
to this repository's `testflight` environment. No committed real credentials,
plaintext logs, profile artifacts, or broader access. No product contract or
persistence changes. [design.md](design.md) records product UX N/A. Primary
capture/review/route behavior, mobile/offline and feature flags stay unchanged.
ADR-0008 ASK CI/review/landing stay binding. Fly smoke is subject to the proposed
bounded founder exception below; it is not silently waived.

## Implementation

- FR-001/FR-003: extend existing config check in `.github/workflows/ios.yml`
  with the two required secrets. Install before archive via `ios/ci/install_signing_identity.sh`.
  Fail on either missing new signing secret when existing API/team setup is ready;
  preserve only the legacy unconfigured-API/team skip. Validate decoded bundle,
  password, exact team OU and valid development identity before archive. Restrict
  files with umask 077; prohibit tracing. Do not log certificate identifiers.
  Reject zero/multiple private-key identities and extra development leaves
  before import/search-list activation; permit necessary public chain certificates.
- FR-002: generate a random ephemeral keychain password; create/unlock/configure
  only the task keychain. Import with access for codesign/security and the required
  partition list. Add temporary keychain to the runner search list while preserving
  existing entries. The API key may obtain/renew profiles, but the valid development
  identity is already installed for both targets; distribution export is unchanged.
- FR-004: installer trap deletes decoded `.p12` on every exit and attempts to
  delete its keychain on failed installation. Retain only the public certificate
  and protected redaction map temporarily. After archive, compare the app and
  widget leaf certificates byte-for-byte with the configured certificate and
  report fixed pass/fail text. Mask signer metadata for live logs; before retention,
  sanitize signer names/identifiers/fingerprints and runner paths in raw logs.
  Always-run cleanup attempts every task target even if a deletion fails, verifies
  absence, aggregates errors, and treats never-created/already-deleted as success.
  Artifact upload requires both redaction and cleanup step success; genuine cleanup
  failure fails closed. Never store passwords in outputs, traces, artifacts or git.
- FR-005: replace the runbook's certificate-per-run workaround with setup and
  expiry/rotation/compromise/retirement guidance; preserve Admin export explanation
  accurately. Explain branch-writer private-key access under the unchanged policy
  and that code rollback does not revoke a disclosed identity. Operational secrets
  survive account purge and are excluded from account export, not product data.

## Verification and Delivery

Observed remote quota failure is the reproduction. Add only missing installer
behavior coverage to `scripts/test_validate_trunk_delivery.py`, already invoked
by validate-ci/CI. Tests use disposable synthetic inputs and stub `security`:
success/search-list preservation, missing new secrets with configured API/team,
wrong team/password, malformed bundle, expired/untrusted identities, partial
installation failure, never-created/repeated cleanup and partial cleanup failure.
Include multiple private identities (also wrong-team/purpose extras), legacy
API/team-missing visible skip and cancellation wiring: every sensitive target
belongs to `always()` cleanup and artifacts stay fail-closed.
Prove archive cannot run after installer rejection and artifact upload cannot
run after cleanup/redaction failure. Check secret and signer-metadata absence in
retained output. Reuse static exact-diff review for unchanged trigger, concurrency,
build-number, automatic provisioning and distribution export (FR-003).
Native import has already been verified; mocks cannot prove real provisioning.
Run affected validators first, `make verify-all` on frozen candidate, exact-SHA
independent code review and one ASK review PR, required exact-SHA CI, then a signed
branch upload with leaf-certificate comparison and portal readback. Verify both
new secret names exist only in the environment and existing environment policy
is unchanged. Final Done requires recorded landing approval, audited temporary
ruleset intervention (actor/reason/restoration time) and the landed SHA's automatic
main upload as the second reuse proof. Privately compare the development identity
set/count after each run and secret update metadata across runs; stop on drift.
Retain the public certificate as a non-repository operator record for precise
revocation matching. Independent acceptance/reporting starts only after the
operational task checklist is complete. No automatic revocation is authorized.
Keep raw secrets and signer identifiers outside committed evidence.

## Bounded founder exception — accepted 2026-10-08

Both campaigns found that `scripts/classify_deploy_paths.sh` marks every path in
this repair deploy-inert; the default release workflow skips Fly deployment and
authenticated smoke. Changing the Fly classifier/workflow would expand this
TestFlight signing repair into backend release infrastructure. Proposed exception,
for this slice only: Fly deployment/smoke is N/A because no Fly artifact or product
behavior changes. Compensating measures: exact-SHA full CI, independent code review,
approved ASK landing with restored ruleset, two signed TestFlight runs (including
automatic main), per-target configured-certificate equality, private portal
identity-set equality, unchanged secret metadata and verified credential cleanup.
The exception expires 2026-10-15. The owner explicitly accepted this exception on 2026-10-08; see planning-review.json.
No third campaign or fabricated approval.

## Complexity Tracking

One installer is necessary to isolate credential handling and test failure paths.
Extend existing tests rather than adding a parallel validation system. No new
dependencies, abstractions, product telemetry, UI, or workflow authority.

The existing requirement-coverage scanner omits all `scripts/` unit tests. Admit
only `scripts/test_*.py` (never product gate scripts) in
`scripts/check_requirement_coverage.py`, with its existing regression tests and
updated `.specify/gate-integrity.json`. This is needed to trace this CI-only
spec to the already-selected delivery tests; no coverage threshold is weakened.
Operational criteria still require the actual remote evidence, not marker presence.

Full verification exposed a millisecond-resolution Allure evidence failure in
the new upstream `backend/tests/test_review_navigator.py` CLI-startup test.
Preserve its assertions and attach only the observed exception type and required
variable name to its existing step; never attach exception payloads or credentials.
This bounded test-evidence correction is necessary for the required verification
gate and does not change navigator or signing product behavior.
