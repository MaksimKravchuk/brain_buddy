# ADR-0008: Verified trunk serial landing replaces mandatory PRs for SHIP/SHOW changes

Date: 2026-07-22
Status: Accepted
Decision owner: BrainBuddy
Supersedes: the PR-mandatory release path and PR-preview trigger surface of
[ADR-0003](0003-autonomous-delivery-guardrails.md) (its identity, least-privilege,
evidence, bounded-retry, exact-SHA deployment, and cost-control requirements remain in
force)
Related: ADR-0003, ADR-0005, `docs/autonomous-delivery-runbook.md`,
`specs/004-verified-trunk-delivery/`

## Context

BrainBuddy is a small agentic product with a single maintainer and no persistent staging
environment. ADR-0003 made a reviewed PR the only road to `main`. In practice the PR adds
latency and ceremony without adding verification: the actual gates are deterministic CI,
E2E, artifact/report contracts, and production smoke — none of which need a pull request
object to run. Meanwhile a PR-per-change model multiplies remote mutations (branches, PRs,
comments, preview eligibility churn) that ADR-0003 itself tries to budget.

What must not regress: only exact CI-tested SHAs reach production; every landing is
attributable and auditable; credentials stay least-privilege; failures fail closed; costs
stay bounded.

## Decision

### Delivery path

SpecKit micro-slice → isolated implementation/TDD in a worktree → one candidate commit →
`scripts/submit_to_trunk.sh` pushes the exact SHA to a unique `trunk-candidate/<sha>` ref
→ full required CI runs on that ref (identical job set as `main`, with **no write
permission and no pushes**: candidate-controlled CI can never promote) → the
**default-branch release workflow** (`deploy-fly-production.yml`, consumed via
`workflow_run`, so its definition always comes from `main`) lands the change: its
`land` job — read-only token, running in the GitHub `landing` environment — fast-forwards
`main` to the exact tested SHA without a PR, authenticating with the dedicated
`TRUNK_LANDING_SSH_KEY` SSH deploy key, then proves `origin/main` equals the tested
`workflow_run.head_sha` — the deterministic landing proof → its `deploy` job (which
needs that proof) re-verifies the exact main head before any Fly mutation →
authenticated production smoke as the provisioned internal smoke identity, asserting
the `delivery_canary` flag is effectively TRUE for it → feature-flag cohort rollout
(OFF → INTERNAL → ON). On any failure the path fails closed; post-deploy smoke failure
triggers a verified rollback to the captured previous images and the run stays failed.
Direct pushes to `main` (ASK-class PR merges) still run push CI on `main`; the release
workflow consumes that run too, pushes nothing, proves the landing, and deploys the
same way.

`main` is integration. Production exposure of new behavior is controlled by server-owned,
allow-listed, default-OFF feature flags (`app/core/config.py`); flags are exposure
control, never authorization. There is no persistent staging and no ad-hoc workstation
deploy.

### Ship / Show / Ask

- **SHIP (low risk)** — refactors, docs, tests, small features behind an OFF flag,
  dependency patches: land via verified trunk, no PR, no announcement required beyond the
  commit and CI evidence.
- **SHOW (medium risk)** — user-visible behavior changes, new endpoints, notable
  performance or UX changes: land via verified trunk, then surface the change (commit
  message, changelog, or demo) for after-the-fact review. Rollout starts OFF or INTERNAL.
- **ASK (high risk)** — authentication/privacy changes, destructive data or schema
  migrations, billing or provider credentials, CI/CD/security/infrastructure changes,
  and irreversible external effects: never lands automatically. In this
  one-maintainer repository an ASK landing requires explicit recorded approval,
  green required CI on the exact SHA being landed, and a short, audited,
  **temporary ruleset intervention** (record who, why, and when the ruleset was
  re-enabled) — or, if a separately accountable human reviewer is added in the
  future, a reviewed PR merged behind the required checks. A PR remains the
  vehicle for review evidence, but — stated honestly — while the landing deploy
  key is the **only** `restrict_updates` bypass actor, no PR merge and no direct
  human push can update `main`: the PR carries the evidence; the audited
  intervention performs the landing. Routine SHIP/SHOW landings are unaffected
  (deploy-key automatic landing).

The ASK class is additionally enforced mechanically, not just by convention:
`scripts/classify_path_risk.py` deterministically classifies changed paths
(CI/workflows, delivery scripts, Fly/Docker/deploy configuration,
auth/session/user/invite code, migrations/destructive persistence, and
secrets/permissions surfaces are ASK; ambiguity fails toward ASK;
documentation-only paths are SHIP). The API modules that wire session auth
and per-owner privacy enforcement but carry no auth token in their names —
`backend/app/api/dependencies.py`, `middleware.py`, `routes.py`, and
`tasks.py` — are explicit ASK paths (exact matches; sibling API modules stay
SHIP). Both gates feed it the NUL-separated
`git diff --no-renames --name-only -z` listing (`--null` mode): git never
quotes `-z` output, so non-ASCII or otherwise unprintable paths classify on
their real names, and a rename away from an ASK path still surfaces as its
deletion. In newline (human) mode, quoted or backslash-escaped listings fail
closed as ASK. `scripts/submit_to_trunk.sh` runs the classifier as a
non-skippable preflight, and the release workflow's `land` job re-runs the
**trusted `origin/main` copy** before pushing `main`, so a PR-less candidate
can neither carry ASK-class changes nor weaken the gate on itself.

### Landing guardrails (default-branch release workflow)

The architectural invariant: **candidate-controlled CI must never be able to promote
`main`.** `.github/workflows/ci.yml` executes from the pushed ref, so a candidate could
edit it; it therefore holds no `contents: write`, pushes nothing, and contains no
promotion machinery (all validator-enforced). Landing lives in the `land` job of
`.github/workflows/deploy-fly-production.yml`, which GitHub always executes from the
**default branch's** workflow definition (`workflow_run` trigger) — a candidate's edits
to any workflow file have no effect on how it is landed.

The `land` job:

1. consumes only completed **successful push CI runs** for `main` or
   `trunk-candidate/**`; the whole workflow holds the serial `fly-production-deploy`
   concurrency group with `cancel-in-progress: false`. This is **safety serialization,
   not a FIFO queue**: at most one landing+deploy runs at a time and at most one
   further run stays pending — additional pending runs may be cancelled by GitHub
   rather than queued. Cancellation fails closed: nothing lands and nothing deploys;
   the candidate is simply resubmitted. `full-ci` in CI fails when any required job
   failed, was cancelled, or was **skipped** — a skipped gate can never count as
   success, so a "successful" consumed run always means the entire required job set
   passed;
2. carries **no production secrets, no production environment, and no `GITHUB_TOKEN`
   write scope** — its token permissions are pinned to `contents: read`, and its only
   landing power is the dedicated SSH **deploy key** exposed as the
   `TRUNK_LANDING_SSH_KEY` secret of the GitHub `landing` environment
   (`actions/checkout` `ssh-key` with `persist-credentials: true`, so the
   fast-forward push authenticates as that identity). No PAT secret exists. The
   `landing` environment MUST carry a custom deployment branch policy allowing only
   `main`: `workflow_run` runs execute with the default branch as their ref, so only
   this default-branch release workflow can read the key, while candidate-controlled
   push CI — whose ref is the candidate branch, and which holds `contents: read`
   only — can never access it (validator-enforced in-repo as well: `ci.yml` may
   reference neither the key nor the environment). The `main` ruleset MUST enable
   `restrict_updates` with the landing deploy key as the **only** bypass actor and
   MUST require the `Full CI` and `Docker Images` status checks for every human/PR
   path, so the default `GITHUB_TOKEN` cannot push `main` at all and force pushes
   and deletions stay rejected;
3. for candidate runs, checks out `workflow_run.head_sha` with full history and
   verifies the candidate has exactly one parent equal to the current `origin/main` —
   a stale candidate or merge commit fails closed with nothing mutated;
4. runs the trusted `origin/main` copy of `scripts/classify_path_risk.py` over the
   candidate's NUL-separated `--no-renames` changed paths and fails closed **before
   pushing `main`** when any path is ASK class (mechanical Ship/Show/Ask enforcement,
   see above);
5. fast-forwards `main` with a plain (never force) push of the exact tested SHA; if
   `main` moved between verification and push, git rejects the push and the job fails;
6. deletes only its own candidate ref, and only after the fast-forward. Deletion is
   best-effort cleanup (`continue-on-error`): `main` has already been mutated, so a
   failed deletion must never fail the run and thereby suppress the production deploy
   of an already-landed SHA. Leftover `trunk-candidate/<sha>` refs are inert
   (re-running a landing on them fails the fresh-parent check) and are removed
   manually per the runbook;
7. for **every** consumed run — candidate and `main` alike — ends by proving
   `origin/main` equals the tested `workflow_run.head_sha`. For candidates this proves
   the landing; for `main` runs (which push nothing) it proves a stale main CI run
   that completed late cannot proceed. The `deploy` job runs only after this proof.

Unlike a `GITHUB_TOKEN` push, a deploy-key push **does** retrigger push CI on `main`.
That is accepted and bounded, not recursive: the `main` CI run independently re-verifies
the landed SHA on `main`, and the release workflow run it triggers takes the
proof-only path (its `land` job pushes nothing for `main` runs, so no further push CI
is generated) and then idempotently redeploys the same SHA — serialized in the same
concurrency group, and failing closed if a newer landing superseded it. The consumed
candidate CI run remains the landing evidence; main CI is never cancelled by candidates
or landings. No PR is created; the audit trail is the candidate ref push (actor + SHA),
the full CI run on the candidate, and the release workflow run that landed, proved, and
deployed it.

### Bootstrap (ASK)

The landing power lives exclusively in the default-branch release workflow plus the
landing identity. Until both exist, a candidate CI run can be **fully successful yet
nothing will auto-promote it** — that is the point: delivery-machinery changes are ASK
class. The bootstrap path for them is a reviewed PR against `main`, or an explicitly
authorized manual high-risk landing of the exact candidate-CI-tested SHA, recorded with
the usual evidence packet (see the runbook). The bootstrap MUST follow this exact
order:

1. Create the landing identity first: register a **write deploy key** dedicated to
   landing, create the GitHub `landing` environment with a **custom deployment branch
   policy allowing only `main`**, and store the key's private half as the environment
   secret `TRUNK_LANDING_SSH_KEY`. In the same step, create the GitHub `production`
   environment with a **custom deployment branch policy allowing only `main`**, move
   `FLY_API_TOKEN` into it as an environment secret — **deleting any repository-level
   `FLY_API_TOKEN`** — and store `BRAIN_BUDDY_ADMIN_EMAIL`,
   `BRAIN_BUDDY_ADMIN_PASSWORD`, and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` there.
2. Submit the delivery-machinery change and let **exact-SHA candidate CI** pass the
   full required job set.
3. Perform the **explicitly authorized manual admin fast-forward** of `main` to that
   exact SHA (never force) — this single bootstrap landing happens while the old
   ruleset still permits maintainer pushes, and is recorded with approver, SHA,
   candidate CI run URL, and reason.
4. **Immediately** activate the `main` ruleset with `restrict_updates`, the landing
   deploy key as the only bypass actor, and the required `Full CI` and `Docker Images`
   checks — before declaring the PR-less flow active.
5. Verify the remote configuration before claiming the automation is active — every
   item is a MUST: ruleset active with `restrict_updates` and the deploy key as sole
   bypass; `landing` **and** `production` environments each restricted to branch
   `main` by a custom deployment branch policy; `TRUNK_LANDING_SSH_KEY` present in
   `landing`; `FLY_API_TOKEN`, `BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`,
   and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` present in `production`; **no
   repository-level `FLY_API_TOKEN` remaining**; and a test candidate landing
   end-to-end. Automation MUST NOT be declared active before this remote verification.

### Production deploy, smoke, and rollback

The `deploy` job of the same release workflow runs only after the `land` job's proof
(`needs: land`), checks out the exact `workflow_run.head_sha`, and is the only job with
production credentials: it runs in the GitHub `production` environment under
`contents: read`. The `production` environment MUST carry a **custom deployment branch
policy allowing only `main`**, and MUST hold the production secrets —
`FLY_API_TOKEN` (an **environment secret only**: a repository-level `FLY_API_TOKEN`
MUST NOT exist), `BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`, and
`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` — so only default-branch `workflow_run`
executions can read them. Candidate-controlled CI can neither request the environment
(validator-enforced in-repo, like the `landing` environment) nor satisfy its branch
policy remotely. Both controls are bootstrap verification items (see Bootstrap). The
workflow has no manual dispatch trigger: a manual deploy would carry no deterministic
exact-tested-SHA proof. In addition it:

1. fails before any deploy when `BRAIN_BUDDY_ADMIN_EMAIL` / `BRAIN_BUDDY_ADMIN_PASSWORD`
   / `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` environment secrets are missing, or when
   the identity would not survive backend startup validation, which the unit-tested
   `scripts/check_smoke_identity_cohort.py` mirrors: the normalized admin email and
   every normalized cohort entry must be email-shaped (contain `@`), the password must
   satisfy the backend password policy (12–128 characters), and the normalized admin
   email must be a member of the normalized comma-separated internal cohort. Variable
   names only are ever printed — an unverifiable deploy is not attempted. The smoke
   script's `BRAIN_BUDDY_SMOKE_EMAIL` / `BRAIN_BUDDY_SMOKE_PASSWORD` are its private
   process-env names, mapped inside the smoke step from the admin secrets; they are
   not GitHub secrets;
2. for **every** consumed run — candidate and `main` alike — re-verifies **immediately
   before any Fly mutation** that `origin/main` equals the tested
   `workflow_run.head_sha`, even though the `land` job already proved it (the two jobs
   run at different times); a superseded SHA can therefore never redeploy;
3. captures and validates the previous backend and frontend release images before
   deploying, using the documented `flyctl releases --app <app> --image --json` form
   parsed by the unit-tested `scripts/capture_fly_release_image.py` (tolerant of Fly's
   JSON field casings, accepting only `registry.fly.io/...` refs from releases whose
   status — when present — is a known successful terminal state: `complete`,
   `succeeded`, or `success`); failed capture fails the run before any mutation,
   leaving the documented manual recovery path in the runbook;
4. stages the smoke identity and production feature-flag assignment into the Fly
   backend with `flyctl secrets set --stage`, so the deploy release seeds the admin
   account and marks it internal; the trusted deploy workflow is authoritative for the
   exact flag assignment, and secret values are never printed;
5. after deploying, verifies reachability and runs `scripts/production_smoke.sh` — an
   authenticated end-to-end check (login as the provisioned identity, `/auth/me`
   asserting `delivery_canary` is effectively TRUE for this internal user,
   temporary-tree lifecycle with verified cleanup, logout) that never logs credentials,
   cookies, or bodies. If any check fails after the temporary tree was created, an
   EXIT trap best-effort deletes it so no smoke data is stranded, without masking the
   original failure; cleanup counts as done only once the 404 read-back confirms it,
   so an accepted-but-ineffective DELETE is retried by the trap;
6. on failed verification, redeploys the captured images frontend-first (the frontend is
   never newer than the backend), re-verifies basic health, and keeps the workflow failed.
   A rollback is loud containment, never silent success; an unverified rollback is a
   failed rollback.

### Preserved ADR-0003 controls

Authority and evidence rules, least-privilege credentials, bounded retries with fail-
closed defaults, exact-SHA-only production, budget/circuit controls, and the incident
procedure in the runbook remain binding. The `preview:visual` PR-preview workflow is
retained for ASK-class PRs but is deprecated as a routine path; it must not be triggered
for trunk candidates.

## Consequences

- SHIP/SHOW changes land minutes after CI instead of after PR round-trips, with full
  required CI on the exact SHA plus a deterministic landing re-verification at deploy.
- The audit unit becomes the candidate ref + workflow runs instead of a PR page.
- No PAT secret exists and no workflow holds `GITHUB_TOKEN` write. The landing identity
  is the `TRUNK_LANDING_SSH_KEY` deploy key in the `landing` environment (branch policy
  `main` only). The `production` environment MUST likewise restrict deployments to
  branch `main` and MUST hold `FLY_API_TOKEN` (environment secret only — a
  repository-level `FLY_API_TOKEN` MUST NOT exist), `BRAIN_BUDDY_ADMIN_EMAIL`,
  `BRAIN_BUDDY_ADMIN_PASSWORD`, and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` (which
  must include the admin email so the smoke user is in the internal cohort); their
  absence fails closed rather than degrading silently. The landing and production
  environments stay separate: neither job can read the other's secrets, and
  candidate-controlled CI may request neither environment (validator-enforced).
- The `main` ruleset MUST enable `restrict_updates` with the landing deploy key as the
  only bypass actor and MUST require the `Full CI` and `Docker Images` checks for
  human/PR paths — the default `GITHUB_TOKEN` cannot push `main`. These are ASK-class
  settings changes performed by the maintainer, in the bootstrap order above. Stated
  honestly: while the deploy key is the sole bypass actor, no PR merge and no direct
  human push can update `main` — a PR carries review evidence but cannot itself land.
  An ASK landing therefore requires explicit recorded approval, green required CI on
  the exact SHA, and a short, audited, **temporary** ruleset intervention (who, why,
  when re-enabled) — or, in the future, a separately accountable human reviewer added
  as an additional accountable path. This keeps the ruleset unweakened; routine
  SHIP/SHOW landings remain deploy-key automatic landings.
- Because landing lives only in the default-branch release workflow, changes to the
  delivery machinery itself cannot bootstrap themselves: candidate CI passes, nothing
  promotes, and the change lands via the ASK procedure — explicit approval, green
  exact-SHA CI evidence, and an audited temporary ruleset intervention (see
  Ship/Show/Ask and Bootstrap above).

## Verification

Deterministic offline contract tests enforce every guard:
`scripts/test_validate_trunk_delivery.py` (workflow guards, mutation-tested, including
that candidate-controlled CI holds no write permission or push and can reference
neither the landing deploy key nor the `landing` or `production` environments
(defense-in-depth beside the environments' main-only branch policies), that no job
holds
`GITHUB_TOKEN` write, and that the land job runs in the `landing` environment with a
read-only token and the `TRUNK_LANDING_SSH_KEY` SSH checkout scoped to it alone),
`scripts/test_submit_to_trunk.py` (real-git submission contract, including the
non-skippable ASK path gate over NUL-separated `--no-renames` paths),
`scripts/test_classify_path_risk.py` (Ship/Show/Ask path classification — including
the explicit API auth/privacy-enforcement ASK paths — NUL input mode, and
quoted-listing fail-closed behavior),
`scripts/test_check_smoke_identity_cohort.py` (backend-startup-mirroring smoke
identity preflight: email shapes, password policy, cohort membership),
`scripts/test_production_smoke.py` (stub-server smoke contract, including the
`delivery_canary` effectiveness assertion and best-effort trap cleanup on
interruption),
`scripts/test_capture_fly_release_image.py` (release-image capture parsing across
documented JSON casings, restricted to successful terminal release statuses), and
`backend/tests/test_feature_flags.py` (flag model, read-only states mapping, and
exposure). All are wired into CI workflow-lint and `make validate-ci`.
