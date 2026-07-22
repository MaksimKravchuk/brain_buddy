# Feature Specification: Verified trunk delivery

**Feature Branch**: `feat/trunk-first-delivery`
**Created**: 2026-07-22
**Status**: Ready for implementation
**Input**: User-approved delivery model — BrainBuddy is a small agentic product with no
persistent staging; landing happens through ephemeral CI on candidate refs, serial
fast-forward to `main` without a PR, exact-SHA production deploy, authenticated smoke, and
server-owned feature-flag rollout.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Land a verified change without a PR (Priority: P1)

An agent (or the maintainer) finishes an isolated, TDD-built change, submits it as one
candidate commit on a `trunk-candidate/<sha>` ref; full required CI runs on that ref, and
the default-branch release workflow's serial `land` job fast-forwards `main` to the exact
tested SHA. No PR is created for SHIP/SHOW class changes.

**Why this priority**: The PR ceremony adds latency without adding verification for a
single-maintainer agentic repo; the merge gate must become CI evidence, not review theater.

**Independent Test**: Push a single fresh commit to `trunk-candidate/<sha>`; observe full
CI running the same required jobs as `main`, the release workflow's `land` job
fast-forwarding `main` to that exact SHA and deleting the candidate ref, and its `deploy`
job deploying after re-proving the landing. The deploy-key fast-forward (unlike a
`GITHUB_TOKEN` push) retriggers push CI on `main`; that re-run re-verifies the landed
SHA and its release run takes the proof-only, no-push path and idempotently redeploys
the same SHA — the completed candidate CI run plus the landing proof remain the
evidence for the landed SHA.

### User Story 2 - Stale or malformed candidates never land (Priority: P1)

If `main` moved after a candidate was cut, or the candidate is a merge commit or a
multi-commit series, promotion fails closed with an actionable message and `main` is not
mutated.

**Independent Test**: Advance `main`, then let a previously pushed candidate finish CI —
promotion must fail on the parent check; the local submit script must refuse dirty trees,
stale bases, merge commits, and multi-commit series before pushing.

### User Story 3 - Production exposure is flag-gated and smoke-verified (Priority: P1)

A deploy of the exact green `main` SHA is followed by an authenticated production smoke:
sign in as the internal smoke user through the frontend `/api` proxy, verify `/auth/me`
including the server-owned feature-flag payload, create and delete a uniquely named
temporary tree, verify cleanup, and log out. New behavior ships dark (flags default OFF),
then rolls out OFF → INTERNAL (allow-listed cohort) → ON.

**Independent Test**: Backend tests prove flags default OFF, invalid configuration fails
startup, INTERNAL is visible only to the allow-listed cohort, and `/auth/me` exposes only
effective booleans. Script contract tests prove the smoke fails closed on missing
credentials, missing flag payload, or unverified cleanup, and never prints secrets.

### User Story 4 - Failed post-deploy smoke rolls back loudly (Priority: P2)

If post-deploy verification fails, the workflow redeploys the previously captured backend
and frontend images (frontend first), re-verifies basic health, and still fails the run.
If rollback images cannot be captured and validated beforehand, the deploy fails before
any mutation.

**Independent Test**: Workflow contract tests assert the capture-before-deploy guard, the
rollback step, the health re-verification, and that no failure path is masked.

## Requirements *(mandatory)*

- **FR-001**: CI MUST run the identical required job set for `trunk-candidate/**` pushes
  as for `main` pushes, without cancelling `main` CI. Candidate-controlled CI
  (`ci.yml` executes from the pushed ref) MUST hold no write permission, push nothing,
  and contain no promotion machinery: it can never promote `main`, even when a
  candidate edits the workflow itself.
- **FR-002**: Landing MUST be owned by the DEFAULT-BRANCH release workflow
  (`deploy-fly-production.yml`, consumed via `workflow_run` so the definition always
  comes from `main`). Its `land` job MUST carry no production secrets, no production
  environment, and no `GITHUB_TOKEN` write scope (job permissions `contents: read`
  only — no job anywhere holds `contents: write`): it MUST run in the GitHub
  `landing` environment and authenticate its push via `actions/checkout` with
  `ssh-key: TRUNK_LANDING_SSH_KEY` and `persist-credentials: true`, using that key
  only to fast-forward the exact tested SHA to `main` and delete the candidate ref.
  The `landing` environment MUST restrict its deployments to branch `main` (custom
  branch policy), so candidate-controlled push CI — whose run ref is the candidate
  branch — can never read the key, while `workflow_run` executions (ref `main`) can;
  candidate CI MUST also reference neither the key nor the environment
  (validator-enforced). The `main` ruleset MUST enable `restrict_updates` with the
  landing deploy key as the only bypass actor and require the `Full CI` and
  `Docker Images` checks, so the default `GITHUB_TOKEN` cannot push `main`. The job
  MUST run mutating steps only for candidate runs, and — after every required CI job
  succeeded — verify the candidate has exactly one parent equal to the current
  `origin/main`, fast-forward the exact tested SHA with a plain (never force) push,
  delete only its own candidate ref, and prove for EVERY consumed run (candidate and
  `main`) that `origin/main` equals the tested SHA. The deploy-key push retriggers
  push CI on `main`; the resulting release run is proof-only (no push) and its
  redeploy of the same SHA is idempotent. Serialization is safety, not FIFO: GitHub
  keeps at most one further run pending and MAY cancel additional pending runs; a
  cancelled run fails closed (nothing lands) and is resubmitted. Candidate-ref
  deletion is best-effort cleanup after the `main` mutation (`continue-on-error`); a
  deletion failure MUST NOT fail the run or suppress the deploy, and leftover refs
  are documented as inert. Bootstrap is explicit and ordered: create the write deploy
  key + `landing` environment (branch policy `main`) + secret, and the `production`
  environment (branch policy `main`) holding `FLY_API_TOKEN` as an environment
  secret only (no repository-level copy) plus the admin/cohort secrets, first; run
  exact-SHA candidate CI; perform the explicitly authorized manual admin
  fast-forward while the old ruleset still permits it; immediately activate
  `restrict_updates` with the deploy-key bypass and required checks; verify remotely
  (ruleset, both environments' `main`-only branch policies, secrets present, no
  repository-level `FLY_API_TOKEN`, end-to-end test landing) before declaring the
  flow active. Until then, a fully successful candidate CI run auto-promotes
  nothing; delivery-machinery changes are ASK class and land only with explicit
  recorded approval, green required CI on the exact SHA, and a recorded,
  **temporary** ruleset intervention — a PR may carry the review evidence but
  cannot merge while the deploy key is the sole `restrict_updates` bypass actor
  (never routine).
- **FR-003**: `scripts/submit_to_trunk.sh` MUST validate clean state, current base, and a
  single non-merge commit, run fast local checks, push the exact SHA to a unique
  `trunk-candidate/<sha>` ref, and never push `main` or force-push.
- **FR-004**: Backend feature flags MUST be typed, allow-listed, frozen, default OFF, and
  fail closed on any invalid configuration. The states mapping MUST be genuinely
  read-only (item mutation raises), not merely attribute-frozen. Rollout states are
  OFF / INTERNAL / ON with an allow-listed internal email cohort. Flags are exposure
  control, never authorization.
- **FR-005**: Effective flags MUST be exposed only to authenticated users via
  `/api/auth/me` (and login/signup payloads) as booleans; rollout stages, cohort
  membership, and configuration MUST never be exposed.
- **FR-006**: `scripts/production_smoke.sh` MUST authenticate with
  `BRAIN_BUDDY_SMOKE_EMAIL`/`BRAIN_BUDDY_SMOKE_PASSWORD` (the script's private
  process-env names, mapped inside the deploy step from the `BRAIN_BUDDY_ADMIN_*`
  GitHub secrets — no `BRAIN_BUDDY_SMOKE_*` GitHub secrets exist), verify `/auth/me`
  including that `delivery_canary` is effectively TRUE for this internal user,
  create/delete/verify a temporary tree, log out, fail closed on any unexpected
  response, and never print credentials, cookies, or response bodies. If any check
  fails after the temporary tree was created, an EXIT trap MUST best-effort delete it
  without masking the original failure.
- **FR-007**: The production `deploy` job MUST run only after the `land` job's landing
  proof (`needs: land`), with `contents: read`, in the GitHub `production` environment,
  with no manual dispatch trigger anywhere in the workflow. The `production`
  environment MUST restrict its deployments to branch `main` (custom branch policy)
  and MUST hold `FLY_API_TOKEN` — as an environment secret only; no repository-level
  `FLY_API_TOKEN` may exist — plus `BRAIN_BUDDY_ADMIN_EMAIL`,
  `BRAIN_BUDDY_ADMIN_PASSWORD`, and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`; both
  controls are bootstrap verification items, and candidate-controlled CI MUST
  reference neither the `landing` nor the `production` environment
  (validator-enforced defense-in-depth). It MUST check out the
  exact `workflow_run.head_sha` and re-verify `origin/main == workflow_run.head_sha`
  immediately before any Fly mutation (for EVERY consumed run — candidate and `main`
  alike) so a stale CI run can never redeploy a superseded SHA. It MUST fail before
  any remote mutation unless the smoke identity survives the backend-startup-mirroring
  preflight (`scripts/check_smoke_identity_cohort.py`: email-shaped admin and cohort
  entries, 12–128 character password policy, case-insensitive cohort membership),
  provision the staged smoke identity and internal canary rollout before deploying,
  fail before deploy when identity secrets or validated rollback images are missing
  (rollback capture MUST skip releases whose present status is not a known successful
  terminal state), and roll back to captured images with re-verified health on failed
  smoke while keeping the workflow failed.
- **FR-008**: Ship/Show/Ask MUST be documented: SHIP (low risk) and SHOW (medium risk)
  land via verified trunk; ASK (auth/privacy, destructive data/schema, billing/provider
  credentials, CI/CD/security/infra, irreversible external effects) never lands
  automatically and — stated honestly — cannot land via PR merge while the landing
  deploy key is the sole `restrict_updates` bypass actor: an ASK landing requires
  explicit recorded approval, green required CI on the exact SHA, and a short,
  audited, temporary ruleset intervention (a PR carries the review evidence; a
  separately accountable human reviewer added in the future would restore a
  merge-behind-required-checks path without weakening the ruleset).
- **FR-009**: The ASK class MUST be enforced mechanically for PR-less candidates:
  `scripts/classify_path_risk.py` deterministically classifies changed paths (failing
  closed toward ASK on CI/workflow, delivery-script, Fly/Docker/deploy,
  auth/session/user/invite, migration/destructive-persistence, and secrets/permissions
  surfaces, plus the explicit exact-path API auth/per-owner privacy-enforcement
  modules `backend/app/api/dependencies.py`, `middleware.py`, `routes.py`, and
  `tasks.py`), `submit_to_trunk.sh` runs it as a non-skippable preflight, and the release
  workflow's `land` job re-runs the trusted `origin/main` copy before pushing `main`.
  Both gates MUST feed it NUL-separated `git diff --no-renames --name-only -z` output
  consumed via the classifier's explicit `--null` mode, so quoted/non-ASCII names
  classify on their real bytes and a rename away from an ASK path surfaces as its
  deletion; newline-mode input that looks quoted or backslash-escaped MUST fail closed
  as ASK.

## Success Criteria *(mandatory)*

- **SC-001**: All promotion/deploy guards are enforced by deterministic offline contract
  tests (`scripts/test_validate_trunk_delivery.py`, `scripts/test_submit_to_trunk.py`,
  `scripts/test_production_smoke.py`, `scripts/test_classify_path_risk.py`,
  `scripts/test_check_smoke_identity_cohort.py`,
  `scripts/test_capture_fly_release_image.py`) wired into CI.
- **SC-002**: Backend flag behavior is covered by failing-first tests in
  `backend/tests/test_feature_flags.py` meeting the repo coverage and Allure taxonomy
  gates.
- **SC-003**: Existing CI artifact, mutation, preview, and Allure policies pass unchanged.
- **SC-004**: ADR-0008 supersedes the PR-mandatory parts of ADR-0003 while preserving
  identity, least privilege, evidence, bounded retries, exact-SHA deployment, and cost
  controls; the runbook and AGENTS.md describe the new path.
