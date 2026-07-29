# Implementation Plan: Verified trunk delivery

**Branch**: `feat/trunk-first-delivery` | **Date**: 2026-07-22 | **Spec**:
`specs/004-verified-trunk-delivery/spec.md`
**Input**: Approved delivery model (no persistent staging; PR-less serial landing;
flag-gated production exposure) and ADR-0003's preserved safety invariants.

## Summary

One bounded vertical infrastructure slice: (1) typed, allow-listed, fail-closed feature
flags in the backend config exposed as effective booleans on `/api/auth/me`; (2) an
authenticated production smoke script with deterministic offline contract tests; (3) a
PR-less serial landing path — candidate refs run full (write-permission-free) CI and
the default-branch release workflow's serialized `land` job fast-forwards the exact
tested SHA to `main`; (4) a production deploy that runs only behind the landing proof,
fails closed before mutation, and rolls back to captured images on failed smoke; (5)
ADR-0008 plus runbook/AGENTS/README updates defining Ship/Show/Ask.

## Technical Context

- **Backend**: Python 3.11, FastAPI, frozen Pydantic config (`app/core/config.py`),
  session-cookie auth (`app/api/auth.py`), 95% line+branch coverage gate, central Allure
  taxonomy.
- **CI**: `.github/workflows/ci.yml` (workflow-lint → spec-kit → backend/frontend →
  docker → e2e → allure-report → full-ci), validated by
  `scripts/validate_ci_artifacts.py`; mutation and preview workflows are report-only /
  label-gated and unchanged.
- **Deploy**: `.github/workflows/deploy-fly-production.yml` triggered by completed
  successful push CI runs on `main` and `trunk-candidate/**` (`workflow_run`, so the
  default-branch definition always executes); it owns both landing (`land` job) and
  deploy (`deploy` job). Fly apps `brain-buddy-backend` (Flycast-private) and
  `brain-buddy-frontend` (public proxy).

## Module boundaries and design decisions

1. **Feature flags live in config, not a new service.** `FeatureFlagSettings` is a frozen
   Pydantic model with an explicit code-level allow-list (`KNOWN_FEATURE_FLAGS`), states
   parsed from `BRAIN_BUDDY_FEATURE_FLAGS`, cohort from
   `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`. Any unknown flag, malformed entry,
   duplicate, invalid state, or non-email cohort entry raises at startup (fail closed).
   Evaluation (`effective_flags(email)`) is pure and returns only booleans. One
   infrastructure flag, `delivery_canary`, exists so rollout plumbing is verifiable
   end-to-end without wiring an unfinished product feature.
2. **Exposure extends `MeResponse`.** `feature_flags: dict[str, bool]` is additive and
   backward compatible for the frontend (`AuthUser` ignores unknown fields; no frontend
   change required). Signup/login/me share one `_me_response` helper. Unauthenticated
   requests keep getting 401 with no flag payload.
3. **Landing is a default-branch release-workflow job, never candidate CI.**
   `trunk-candidate/**` joins the push trigger so candidates run the identical required
   jobs, but `ci.yml` executes from the pushed (candidate-controlled) ref: it therefore
   holds no write permission, pushes nothing, and contains no promotion machinery.
   The `land` job of `deploy-fly-production.yml` — whose definition GitHub always
   takes from the default branch (`workflow_run`) — consumes the completed successful
   push CI run, verifies single-parent + parent==origin/main, re-runs the trusted
   `origin/main` classifier over NUL-separated `--no-renames` changed paths, and
   pushes `<sha>:refs/heads/main` without force so a raced `main` fails the push
   itself. It holds no `GITHUB_TOKEN` write scope (job permissions `contents: read`;
   no PAT secret): it runs in the GitHub `landing` environment and authenticates the
   push with the dedicated `TRUNK_LANDING_SSH_KEY` SSH deploy key
   (`actions/checkout` `ssh-key` + `persist-credentials: true`). The environment's
   `main`-only branch policy keeps the key out of candidate-controlled CI's reach,
   and the `main` ruleset must keep `restrict_updates` with the deploy key as the
   only bypass actor plus required `Full CI`/`Docker Images` checks. For every
   consumed run (candidate and `main`) it ends by proving `origin/main` equals the
   tested SHA; the `deploy` job needs that proof. The deploy-key push retriggers
   push CI on `main`; the resulting release run is proof-only and its same-SHA
   redeploy is idempotent. `full-ci` fails when any required job failed, was cancelled, or
   was skipped, so a landing can never ride a vacuous gate. Bootstrap is explicit:
   until the release workflow exists on `main`, green candidate CI promotes nothing —
   delivery-machinery changes are ASK class and land only with explicit recorded
   approval, green exact-SHA CI, and an audited temporary ruleset intervention (a
   PR carries review evidence but cannot merge while the deploy key is the sole
   `restrict_updates` bypass actor).
4. **Deploy captures rollback identity before mutating.** The documented
   `flyctl releases --app <app> --image --json` output is parsed by the unit-tested
   `scripts/capture_fly_release_image.py` (tolerant of documented JSON field casings)
   and validated to a `registry.fly.io/` image ref per app; empty/unparseable capture
   fails the run before `flyctl deploy`. The smoke identity (admin email/password,
   internal cohort, `delivery_canary=internal`) is then staged into the Fly backend via
   `flyctl secrets set --stage` so the deploy release seeds it. Post-deploy verification
   is reachability plus `scripts/production_smoke.sh`, which asserts `delivery_canary`
   is effectively TRUE for the smoke user. On failure the captured images are redeployed
   frontend first (the frontend is never newer than the backend), health is re-verified,
   and the workflow stays failed. Missing identity secrets fail before deploy; there is
   no manual dispatch trigger. The GitHub `production` environment MUST restrict its
   deployments to branch `main` (custom branch policy) and MUST hold `FLY_API_TOKEN`
   as an environment secret only (no repository-level `FLY_API_TOKEN` may exist) plus
   the admin/cohort secrets — both bootstrap verification items; the trunk validator
   additionally forbids candidate-controlled CI from requesting the `landing` or
   `production` environments (defense-in-depth beside the branch policies).
5. **Ship/Show/Ask is enforced mechanically, not by convention.**
   `scripts/classify_path_risk.py` is a deterministic, ordered, fail-closed-toward-ASK
   path classifier (CI/workflows, delivery scripts, Fly/Docker/deploy config,
   auth/session/user/invite code including the explicit exact-path API
   privacy-enforcement modules `backend/app/api/{dependencies,middleware,routes,tasks}.py`,
   migrations/destructive persistence, secrets/permissions; docs-only paths are SHIP). Both gates feed it NUL-separated
   `git diff --no-renames --name-only -z` output (`--null` mode) so quoted/non-ASCII
   names classify on their real bytes and renames surface as delete+add; quoted
   newline-mode input fails closed as ASK. `submit_to_trunk.sh` runs it as a
   non-skippable preflight and the release workflow's `land` job re-runs the trusted
   `origin/main` copy before pushing `main`, so a candidate cannot weaken the gate on
   itself. The deploy preflight `scripts/check_smoke_identity_cohort.py` similarly
   verifies — before any remote mutation, printing variable names only — that the
   identity would survive backend startup (email-shaped admin and cohort entries,
   12–128 character password policy) and that the normalized admin email is in the
   normalized internal cohort.
6. **Contract tests are deterministic and offline.** `test_submit_to_trunk.py` uses real
   git repos with a local bare origin; `test_production_smoke.py` runs the real script
   against an in-process HTTP stub; `test_validate_trunk_delivery.py` proves each guard
   is enforced by mutating the real workflows. All three run in CI workflow-lint and
   `make validate-ci`.

## Constitution / gate check

- TDD: every slice landed test-first (backend tests, then script/workflow contract
  tests). Coverage, Allure taxonomy, mutation policy, and preview policy untouched.
- ADR alignment: ADR-0008 supersedes only ADR-0003's PR-mandatory/PR-preview-trigger
  aspects; identity, least privilege, evidence, bounded retries, exact-SHA deploys, and
  budget controls carry forward. The preview workflow is deprecated for the PR-less path
  but not deleted (ASK-class changes still use PRs and may use it).
- No new persistence, no Kanban board changes, no self-approval semantics.
