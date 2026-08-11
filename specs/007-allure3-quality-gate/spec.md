# Feature Specification: Allure 3 aggregate Quality Gate and single-file report

**Feature Branch**: `feat/allure3-quality-preview` · **Created**: 2026-08-11
**Status**: Implemented; awaiting independent verification and landing.
**Input**: see [intake.md](intake.md) for the founder's ask, verbatim.

BrainBuddy is already on Allure Report 3 end to end. This adopts two unused
capabilities of that working baseline — the native quality gate and the
single-file Awesome report. It is not a migration.

## User Scenarios & Testing

The "user" is the founder reading a CI run, and the agents citing its evidence.
No product surface changes; see [design.md](design.md).

1. **A lane goes red.** A pytest case fails. The lane fails, the aggregate is
   still assembled and published, and the last step of `allure-report` fails the
   job — so `Full CI` is red for a reason the artifact explains.
2. **Reading the report.** The reviewer opens the pull-request comment, downloads
   `allure-report-single-file`, unzips GitHub's envelope, and opens one
   `index.html` in a browser. No local server, no directory of assets.
3. **Everything passes.** The gate exits 0 and the run is green, exactly as
   before this feature.
4. **The gate is weakened.** Someone raises the failure budget or adds a
   gate-replacing CLI flag. The path classifier marks the config ASK so it cannot
   land through automatic promotion, and the workflow validator rejects the flag.

## Requirements

- **FR-001**: The repository MUST own one Allure 3 configuration file that
  declares the native quality gate with a failure budget of zero, and the
  `allure-report` job MUST execute that verdict so any failed or broken result in
  the aggregate fails the job and `Full CI` with it.
- **FR-002**: The existing multi-file HTML report MUST still be generated and
  uploaded as `allure-report-html`, unchanged.
- **FR-003**: An Awesome `--single-file` report MUST be generated in addition
  to it, and only its `index.html` uploaded, as `allure-report-single-file`.
- **FR-004**: Both uploads and the pull-request comment MUST run before the
  verdict and remain available when the verdict is red.
- **FR-005**: Every run MUST prove the gate can still fail, by running the
  real CLI and the real configuration over a clean and a dirty fixture and
  requiring exit 0 and a non-zero exit respectively.
- **FR-006**: The gate MUST have no fail-open lever: no `continue-on-error`
  on the job, no CLI argument that replaces the configured ruleset, and explicit
  (not implicit) config discovery, since Allure's defaults declare no gate.
- **FR-007**: The configuration file MUST be classified ASK by the path
  classifier, so a threshold change cannot land through automatic promotion.
- **FR-008**: The pull-request comment MUST name both artifacts, say which to
  open first and how, and state retention truthfully: 7 days on a pull request,
  30 days on a push.
## Success Criteria

- **SC-001**: The gate exits 0 on a wholly passing aggregate and non-zero on
  an otherwise identical one containing a failed result.
- **SC-002**: When the verdict is red, both report artifacts and the comment
  are still present on the run.

## Manual Acceptance Checks

- The downloaded single-file artifact unzips to exactly one `index.html` that
  opens in a browser without a server.
- Diff review confirms 0 new CI permissions, secrets, jobs, actions,
  dependencies, services, or network calls.

## Out of Scope

Report storage/hosting, rerun policy, environment labels, lane completeness,
freshness, duplicate detection, artifact size ceilings, any general-purpose gate
framework, and product code. A missing lane is **not** detected by this feature:
the gate judges the aggregate this run produced, and `allure-report` depends on
every lane, so a lane that dies fails the run on its own account.

## Assumptions

- The Allure 3 CLI already installed under `frontend/` is the only CLI needed;
  `npx allure quality-gate` is a published command of that version (3.14.3).
- Per-lane result uploads, the taxonomy validators and aggregate timing
  semantics are unchanged, so no existing evidence rule is weakened.
