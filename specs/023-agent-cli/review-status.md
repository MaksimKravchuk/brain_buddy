# Planning review status

Date: 2026-10-06. Product implementation, release binaries and publication have not started.

## Canonical campaign

cli-023-r1: escalated; risk high; mandatory reviews0/6; no human risk sign-off. Actual [campaign-1 summary](review/campaign-1-summary.json) is copied verbatim from the harness. Five configured Codex executions failed authentication401 and refresh failure, so no valid reviewer JSON was produced; adversarial was not run through the broken runtime. No missing review is counted as a pass.

Original reviewed-artifact preflight digest: bc42250a4f80b8558333c3f20b65f1a8f997ba0fd764e5da417d2e28a1a3e62e. Subsequent draft task/contract corrections require a fresh preflight/campaign; this old digest does not approve current artifacts. A second campaign has not been spent on repeating the same unavailable authentication.

The repo-permitted external adapter alternative was inspected and rejected because a proposed out-of-band transport could not enforce reviewer read-only tool access. It was not used for canonical evidence. No gate code, provenance, risk class or pass status was altered to bypass the failure.

## Supplemental analysis and corrections

Five separate read-only collaborator lenses reviewed the initial artifacts: requirements-consistency, architecture-consistency, testability-evidence, privacy-consent-security and ux-accessibility-mobile. Every report was changes-required with product_decisions empty. These are supplemental findings from the same platform; no independent-provider or canonical-gate approval is claimed.

Corrections in the current plan/contracts:

- Remove unsupported project restore; synchronize key/query/error examples and fully redact dry-run content.
- Proposed ADR0028 and contracts/rollout.md establish optional missing→OFF cli_auth without automatic row writes, then explicit activation only after a successfully deployed compatible rollback floor. No new grants before that floor; deletion/scrub compatibility is preserved.
- Explicit grant export exclusion, startup/periodic idle/OFF cleanup and no quarantine; fresh bound-owner/source-session404 checks and fixed device validation errors.
- Collected desktop/mobile Playwright paths, Compose/per-run trusted origin/provisioned exposure/readback and reviewed normal production origin configuration.
- Separate-process/restart/termination lock evidence and concrete browser focus/loading30s/error/retry behavior.

The corrected artifacts have not yet been canonically re-reviewed. Supplemental adversarial review is pending. A human cannot clear missing mandatory evidence with the high-risk sign-off alone; a valid reviewed-runtime campaign is still required before the normal approval path.

## Required next gates

Restore the Codex CLI's environment login; run canonical second campaign against the final current artifact digest, carrying these findings forward. Resolve its actual findings under the two-campaign cap and obtain the required named/digest-bound high-risk planning sign-off, including ADR0028 acceptance. Only an approved or honestly recorded founder-accepted verdict permits product implementation. Exact-SHA implementation review/QA/CI and recorded ASK landing/production/binary publication decisions remain later gates.

Current evidence: Spec Kit artifact completeness, manifest consistency and gate integrity pass; these are planning checks, not software/native/install/authentication acceptance.
