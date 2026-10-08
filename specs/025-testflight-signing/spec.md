# Feature Specification: Reusable TestFlight signing identity

**Feature Branch**: `codex/025-testflight-signing`
**Created**: 2026-10-07
**Status**: Planning
**Input**: Fix the owner's failed TestFlight archive and set up signing directly.

## User Scenarios & Testing

### User Story 1 - Upload repeatedly without certificate churn (Priority: P1)

As the owner, I can upload app and widget builds from fresh GitHub runners
without consuming a new Apple Development certificate on every archive.

**Independent Test**: two signed workflow runs succeed, each comparing app and
widget leaf certificates with the unchanged configured bundle; the development
certificate list gains no additional identities after either run. At least one
run must exercise automatic `workflow_run` upload from the landed main SHA.

**Acceptance Scenarios**:
1. Given the two signing secrets and existing Apple API configuration, when a
   TestFlight job runs, it imports the reusable identity before archive and
   archives app and widget using automatic provisioning and existing export signing.
2. Given a malformed bundle, wrong password, expired or untrusted identity, or
   a certificate for another team, when installation runs, it fails before archive.
3. Given an archive/upload failure or cancellation, when the job's cleanup runs,
   it deletes temporary keychain and signing files before artifact upload.

### Edge Cases

- When existing Apple API/team setup is absent, retain the existing explicit
  configuration-skipped setup behavior; never count that as upload success.
  When that setup is present, either missing new signing secret fails the upload.
- Nonempty but unusable signing input fails visibly; no fallback to creating a
  new development identity. Apple availability and profile renewal still depend
  on the existing API key, identifiers, capabilities and registered device.
- A runner lost before cleanup is ephemeral; the job always requests cleanup
  for success/failure/cancellation and GitHub destroys hosted runners afterward.

## Requirements

- **FR-001**: Require owner-provided development certificate/private-key bundle
  and password in `testflight` secrets; never commit, log, or upload them as artifacts.
- **FR-002**: Install one currently valid Apple Development identity for the
  configured team in a temporary runner keychain before archive. Reject invalid
  bundle/password/identity/team before invoking archive. Accept exactly one
  private-key identity and one development leaf; reject additional private
  identities before entering the search list. Public issuer chain certificates
  are permitted.
- **FR-003**: Preserve automatic provisioning, cloud-managed distribution export,
  app/widget identifiers, upload triggers, build numbers, and serial concurrency.
- **FR-004**: Remove decoded signing files immediately after installation and
  delete temporary keychain and API-key files via always-run cleanup before artifacts.
  Cleanup is idempotent, attempts every target, verifies absence, and fails on
  any remaining target. Artifact upload requires successful redaction and cleanup.
  Redact signer names/identifiers and runner paths from logs before retention;
  signing evidence reports comparisons as fixed pass/fail text, without identifiers.
- **FR-005**: Document required secrets, secure one-time export, expiry/rotation
  recovery and the observed quota failure without recommending routine revocation.

## Success Criteria

- **SC-001**: Two successful signed TestFlight jobs verify both archive targets
  against the same unchanged environment secret, with no new development certificates
  after each run. Privately compare the development-certificate identity set as
  well as its count, emitting only changed/unchanged. Include the landed SHA's
  automatic main upload among these runs.
- **SC-002**: Deterministic installer tests cover success, invalid input, wrong
  password, wrong team, unusable identity and cleanup after partial failure.
- **SC-004**: Secret-name/metadata readback confirms environment-only placement,
  no repository duplicates, unchanged deployment-branch/reviewer policy and no
  update to either signing secret between the two accepted runs.
- **SC-003**: Secrets remain absent from logs/artifacts; repository CI, exact-SHA
  review and authorized ASK landing evidence pass. No Fly product journey changes.
  The owner-accepted bounded exception in plan.md makes Fly deployment/smoke
  N/A for this signing-only slice until 2026-10-15.
  Exact-SHA signed TestFlight acceptance remains mandatory.

## Clarifications

### Session 2026-10-07
- Owner authorized a reusable Apple Development identity and saving its `.p12`
  plus password only in `MaksimKravchuk/brain_buddy` environment `testflight`.
- Existing distribution export and branch-upload access policy stay unchanged.
- No product UI, persisted customer data, feature flag, or product metric changes.
  Product signal is successful signed upload; guardrail is unchanged certificate count.
- Existing branch policy remains unrestricted: repository writers able to run
  branch workflows can extract the reusable development key as well as the already
  available Admin API key. Recovery requires owner-authorized revocation of only
  the compromised identity and replacement/removal of its two secrets; no auto-revocation.
