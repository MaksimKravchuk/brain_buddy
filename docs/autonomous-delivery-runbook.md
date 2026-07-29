# Autonomous Delivery Guardrails Runbook

This runbook operationalizes
[ADR-0003](decisions/0003-autonomous-delivery-guardrails.md) and
[ADR-0008](decisions/0008-verified-trunk-serial-landing.md). It is the authority for
verified trunk landings, agent-created PRs (ASK class), visual review apps, normal
production releases, and incidents involving those paths. It does not grant authority to
mutate remote resources.

## Verified trunk landing (SHIP/SHOW changes)

ADR-0008 makes PR-less serial landing the normal path for low-risk (SHIP) and
medium-risk (SHOW) changes. ASK-class changes — authentication/privacy, destructive
data/schema, billing/provider credentials, CI/CD/security/infrastructure, irreversible
external effects — never land automatically; they use the ASK landing procedure below
(review evidence via PR, landing via an audited temporary ruleset intervention).

### Procedure

1. Implement the slice test-first in an isolated worktree, as one candidate commit whose
   parent is the current `origin/main` (squash an atomic series before submitting).
2. Run `scripts/submit_to_trunk.sh`. It validates clean state, current base, and a single
   non-merge commit, mechanically classifies every changed path with
   `scripts/classify_path_risk.py` fed by `git diff --no-renames --name-only -z`
   (NUL-separated, so non-ASCII paths classify on their real names and a rename away
   from an ASK path still surfaces as its deletion; ASK-class paths — CI/workflows,
   delivery scripts, Fly/Docker/deploy config, auth/session/user/invite code including
   the explicit per-owner privacy-enforcement API modules
   `backend/app/api/dependencies.py`, `middleware.py`, `routes.py`, and `tasks.py`,
   migrations/destructive persistence, secrets/permissions — fail the submission; this
   gate is never skippable), runs fast local checks, pushes the exact SHA to
   `trunk-candidate/<sha>`, and prints the Actions URL. It never pushes `main` and
   never force-pushes.
3. Full required CI (the same job set as `main`) runs on the candidate ref.
   Candidate-controlled CI holds **no write permission and pushes nothing** — it can
   never promote. A skipped required job fails `full-ci`, so a landing can never ride
   on a vacuously green gate.
4. The completed successful candidate CI run triggers the **default-branch release
   workflow** (`deploy-fly-production.yml`; `workflow_run` always executes the `main`
   copy of the definition, so a candidate's workflow edits cannot affect its own
   landing). Its `land` job — read-only token (`contents: read`), no PAT, running in
   the GitHub `landing` environment and pushing with the dedicated
   `TRUNK_LANDING_SSH_KEY` SSH deploy key (which the environment's `main`-only branch
   policy keeps out of candidate-controlled CI's reach) —
   re-verifies that the candidate still has exactly one parent equal to the current
   `origin/main`, re-runs the ASK path gate using the trusted `origin/main` copy of
   the classifier over the NUL-separated changed paths, fast-forwards `main` to the
   exact tested SHA with a plain (never force) push, best-effort deletes the candidate
   ref, and proves `origin/main` equals the tested SHA. Stale candidates, merge
   commits, raced pushes, and ASK-class paths fail closed without mutating `main`.
   The `fly-production-deploy` concurrency group is safety serialization, **not a FIFO
   queue**: at most one landing+deploy runs and at most one more stays pending; GitHub
   may cancel additional pending runs. A cancelled run fails closed (nothing lands) —
   resubmit the candidate.
5. The `deploy` job of the same run starts only after the landing proof
   (`needs: land`), holds the production environment and Fly secrets under
   `contents: read`, and re-verifies for **every** consumed run (candidate and `main`)
   that `origin/main` equals the tested `workflow_run.head_sha` immediately before any
   Fly mutation, so a stale CI run that completes late can never redeploy a superseded
   SHA. The deploy-key fast-forward (unlike a `GITHUB_TOKEN` push) retriggers push CI
   on `main`; that re-run re-verifies the landed SHA on `main` and its release run
   takes the proof-only path (no push, so no recursion) and idempotently redeploys the
   same SHA, failing closed if a newer landing superseded it. The consumed candidate
   CI run plus the landing proof remain the evidence. Production exposure of
   the new behavior remains gated by server-owned feature flags (default OFF; rollout
   OFF → INTERNAL → ON via `BRAIN_BUDDY_FEATURE_FLAGS` /
   `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`).
6. Evidence for the landing is the candidate push (actor + SHA), the candidate CI run,
   and the release workflow run (its `land` and `deploy` jobs) — record their URLs
   where a task requires an evidence packet. No PR object exists for SHIP/SHOW
   landings.

ASK-class changes never land through automatic promotion. Stated honestly: while the
landing deploy key is the **only** `restrict_updates` bypass actor, no PR merge and no
direct human push can update `main` — a PR can carry the review evidence, but it
cannot itself land. An ASK landing in this one-maintainer repository therefore
requires all three of: explicit recorded approval, green required CI on the exact SHA
being landed, and a short, audited, **temporary** ruleset intervention (record who,
why, and when the ruleset was re-enabled) — or, if a separately accountable human
reviewer is added in the future, a reviewed PR merged behind the required checks.
Routine SHIP/SHOW landings are unaffected (deploy-key automatic landing). For
bootstrap-class changes to the delivery machinery itself, see the bootstrap section
below.

### Bootstrap of the delivery machinery (ASK)

The power to land lives **only** in the default-branch copy of
`.github/workflows/deploy-fly-production.yml` plus the landing identity below. Two
consequences:

- A candidate CI run can be fully successful and still nothing auto-promotes it —
  by design — until that release workflow (or the change to it) exists on `main`
  and the landing identity is configured.
- Changes to the delivery machinery itself (workflows, delivery scripts) are ASK
  class and cannot self-land. The bootstrap path is a **reviewed PR against `main`**,
  or an **explicitly authorized manual high-risk landing** of the exact SHA that
  passed candidate CI.

The bootstrap MUST happen in this exact order:

1. **Create the landing identity first**: register a dedicated **write deploy key**
   for landing; create the GitHub `landing` environment with a **custom deployment
   branch policy allowing only `main`**; store the key's private half as the
   `landing` environment secret `TRUNK_LANDING_SSH_KEY`. In the same step, create
   the GitHub `production` environment with a **custom deployment branch policy
   allowing only `main`**; move `FLY_API_TOKEN` into it as an environment secret and
   **delete any repository-level `FLY_API_TOKEN`**; store `BRAIN_BUDDY_ADMIN_EMAIL`,
   `BRAIN_BUDDY_ADMIN_PASSWORD`, and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` there.
2. Run **exact-SHA candidate CI** on the bootstrap change and let the full required
   job set pass.
3. Perform the **explicitly authorized manual admin fast-forward** of `main` to that
   exact SHA (never force) **while the old ruleset still permits it** — record
   approver, target SHA, candidate CI run URL, and reason in the evidence packet, and
   let the resulting `main` push CI run drive the normal release path.
4. **Immediately activate** the `main` ruleset: `restrict_updates` enabled, the
   landing deploy key as the **only** bypass actor, and the `Full CI` and
   `Docker Images` checks required — **before declaring the PR-less flow active**.
5. Verify the remote configuration — every item is a MUST: ruleset active
   (`restrict_updates`, deploy key sole bypass, required checks); `landing` **and**
   `production` environments each restricted to branch `main`;
   `TRUNK_LANDING_SSH_KEY` present in `landing`; `FLY_API_TOKEN`,
   `BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`, and
   `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` present in `production`; **no
   repository-level `FLY_API_TOKEN` remaining**; and a test candidate landing
   end-to-end. Do **not** claim the automation is active before this remote
   verification.

Evidence for a bootstrap landing must include: the candidate CI run URL proving the
exact SHA passed the full required job set, the authorization (actor, scope, expiry),
and the resulting release workflow run URL.

### Activation canary record (2026-07-22)

Bootstrap SHA `938abd4cbf9fe73ad234d4247d40fb780d0db5a6` passed exact-SHA
candidate CI run `29961113907`, was explicitly fast-forwarded during the bounded
bootstrap window, and passed main CI run `29961801317` plus production release and
authenticated smoke run `29962336315`. The ruleset and environment checks in step 5
were verified immediately afterward. The docs-only commit containing this activation
record is the required first end-to-end automatic candidate: its successful release
run is the canonical evidence that the dedicated deploy key can land a fresh SHIP
candidate while ordinary workflow tokens remain unable to update `main`.

### Required `main` protection, landing identity, and production environment (maintainer, ASK)

Configure the repository so `main` accepts only verified landings. These are GitHub
settings changes performed manually by the maintainer — never automated — and they
are requirements (MUST), not recommendations. Each is also a bootstrap verification
item (step 5 above):

- The `main` ruleset MUST enable **`restrict_updates`**, with the landing **deploy
  key as the only bypass actor**. The default `GITHUB_TOKEN` (and every workflow
  token) then cannot push `main`; force pushes and deletions stay rejected.
- The **`Full CI`** and **`Docker Images`** status checks MUST be required on `main`,
  so every human/PR path merges only behind the no-skip aggregate gate.
- The `landing` environment MUST restrict its deployments to branch `main` (custom
  branch policy) so only default-branch `workflow_run` executions can read
  `TRUNK_LANDING_SSH_KEY`.
- The `production` environment MUST restrict its deployments to branch `main`
  (custom branch policy) and MUST hold `FLY_API_TOKEN`, `BRAIN_BUDDY_ADMIN_EMAIL`,
  `BRAIN_BUDDY_ADMIN_PASSWORD`, and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` as
  environment secrets, so only default-branch `workflow_run` executions can read
  them.
- **No repository-level `FLY_API_TOKEN` may exist** — the token lives only in the
  `production` environment. (In-repo defense-in-depth: the trunk validator forbids
  candidate-controlled CI from requesting either the `landing` or the `production`
  environment.)
- ASK-class changes: a PR carries the review evidence, but while the deploy key is
  the sole bypass actor **no PR merge and no direct human push can update `main`**.
  Landing an ASK change requires explicit recorded approval, green required CI on
  the exact SHA, and a short, audited, **temporary** ruleset intervention with audit
  evidence (who, why, when re-enabled) — never a routine path. Adding a separately
  accountable human reviewer in the future would restore a merge-behind-required-
  checks path without weakening the ruleset.

### Leftover candidate refs

Deleting the candidate ref after the fast-forward is best-effort cleanup
(`continue-on-error` in the release workflow's `land` job): `main` has already been
fast-forwarded, so a failed deletion must never fail the run and thereby suppress the
production deploy of an already-landed SHA. A leftover `trunk-candidate/<sha>` ref is
inert — re-running a landing on it fails the fresh-parent check because `main` has
moved — and is removed manually with:

```bash
git push origin --delete trunk-candidate/<sha>
```

### Required secrets (GitHub `landing` and `production` environments)

- `TRUNK_LANDING_SSH_KEY` (**`landing` environment**, branch policy `main` only) — the
  private half of the dedicated write deploy key the release workflow's `land` job
  uses for the fast-forward push. No PAT secret exists and no workflow holds
  `GITHUB_TOKEN` write; candidate-controlled CI holds no write credential at all and
  can never read this secret. It is the only secret the `land` job may reference;
  everything below lives in the separate `production` environment, readable only by
  the `deploy` job.
- `FLY_API_TOKEN` (**`production` environment**, branch policy `main` only) — Fly
  deploy credential. It MUST exist only as a `production` environment secret; a
  repository-level `FLY_API_TOKEN` MUST NOT exist (verified at bootstrap).
- `BRAIN_BUDDY_ADMIN_EMAIL` / `BRAIN_BUDDY_ADMIN_PASSWORD` — the production smoke
  identity. The deploy stages them into the Fly backend (see below) so the backend
  seeds/rotates this admin account on release; the smoke logs in with the same values.
  Missing secrets fail the deploy before any mutation.
- `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` — comma-separated internal cohort; it must
  include the admin email. This is enforced mechanically before any remote mutation:
  `scripts/check_smoke_identity_cohort.py` fails the deploy (naming variable names
  only, never values) when any secret is missing or the identity would not survive
  backend startup validation, which the preflight mirrors — the normalized admin
  email and every normalized cohort entry must be email-shaped (contain `@`), the
  password must satisfy the backend password policy (12–128 characters), and the
  normalized admin email must be a member of the normalized cohort.
- These three are the only smoke-related GitHub secrets. The smoke script's
  `BRAIN_BUDDY_SMOKE_EMAIL` / `BRAIN_BUDDY_SMOKE_PASSWORD` are its private process-env
  names, mapped inside the deploy step from the admin secrets — do not create GitHub
  secrets with the `BRAIN_BUDDY_SMOKE_*` names.
- The `main` ruleset MUST keep `restrict_updates` enabled with the landing deploy key
  as the only bypass actor and the `Full CI` + `Docker Images` checks required (see
  the protection section above). Changing that ruleset is itself ASK-class.

### Production smoke and automatic rollback

The deploy workflow captures the previous backend and frontend release images before
deploying, using the documented `flyctl releases --app <app> --image --json` form parsed
by `scripts/capture_fly_release_image.py` (tolerant of Fly's JSON field casings; only
`registry.fly.io/` refs are accepted, and only from releases whose status — when
present — is a known successful terminal state: `complete`, `succeeded`, or
`success`); failed capture aborts the run before any mutation. It then stages the smoke identity into the Fly backend with
`flyctl secrets set --stage` (`BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`,
`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`, and
`BRAIN_BUDDY_FEATURE_FLAGS=delivery_canary=internal,voice_brain_dump=on`; values are
never printed), so the deploy release seeds the admin smoke account and marks it
internal. That staged value is the authoritative production flag state — it is
restaged on every deploy, so a manual `flyctl secrets set BRAIN_BUDDY_FEATURE_FLAGS`
is reverted by the next release; change the rollout in the workflow instead.

After deploying it
verifies reachability and runs `scripts/production_smoke.sh` (authenticated login
through the frontend `/api` proxy as that identity, `/auth/me` asserting
`delivery_canary` is effectively TRUE for this internal user, temporary-tree lifecycle
with verified cleanup, logout; credentials and bodies are never logged). If the smoke
is interrupted after the temporary tree was created, an EXIT trap best-effort deletes
the tree without masking the original failure; cleanup counts as done only once the
404 read-back confirms it, so an accepted-but-ineffective DELETE is retried by the
trap. If verification fails, the workflow redeploys the captured images frontend-first, re-verifies `/health`
and frontend reachability, and stays failed. If the rollback itself cannot be verified,
the run fails without claiming recovery — then follow the manual path: identify the last
healthy release with `flyctl releases --app <app> --image`, redeploy its image with
`flyctl deploy --config <config> --app <app> --image <captured registry.fly.io ref>`
(frontend first, then backend), and re-run `scripts/production_smoke.sh` against
production before declaring containment.

## Current preview implementation

`.github/workflows/fly-review-frontend.yml` implements the ADR-0003 preview boundary:
`preview:visual` is mandatory, rendered frontend paths are checked, fork/backend-only/docs-only
PRs fail closed, per-PR concurrency cancels stale deployments, and the live head is re-read
immediately before Fly mutation. Removing the label or closing the PR destroys only the
derived PR app and verifies absence. The workflow requires a separate preview-only
`FLY_PREVIEW_API_TOKEN`; production credentials are not a fallback.

The active production workflow is maintained on `main`. The ASK-class release shape is:
reviewed PR -> required CI green -> land on `main` -> successful `push` CI workflow ->
production workflow checks out and deploys that tested SHA -> smoke checks. Under the
active ADR-0008 ruleset the "land on `main`" step is not a plain PR merge: it requires
the audited temporary ruleset intervention described in the protection section, because
the landing deploy key is the sole `restrict_updates` bypass actor. No operator or
agent runs an ad-hoc Fly production deploy.

## Roles and authority

| Role/event | Permitted action | Not permitted without new authority |
|---|---|---|
| Agent assigned implementation work | Create worktree/branch, commit, push, create or update one PR | Add preview label unless the task/comment requests visual preview; merge; production deploy; destructive cleanup |
| Human reviewer | Review, request changes, apply/remove `preview:visual`, approve merge | Credential bypass or unaudited remote mutation |
| Preview workflow | Create/update/destroy only the derived PR preview after all guards pass | Production apps, arbitrary app names, fork code with secrets, other PR previews |
| Successful `main` CI event | Start normal production workflow for the tested SHA | Deploy an untested, unmerged, or substituted SHA |
| Incident commander/explicit approver | Authorize a named rollback, collector apply, or data repair with scope and expiry | Open-ended future destructive authority |

Approval evidence must identify actor, timestamp, repository, action, target(s), reason or
incident ID, expiry/single-use scope, and—where applicable—the reviewed dry-run manifest.
A task body or current PR/incident comment is acceptable if it contains those facts. A prior
approval for a different target, an old chat message, or credential access is not.

## Standard implementation and PR procedure (ASK class)

The PR is the review-evidence vehicle for ASK-class changes. Note (stated honestly):
while the `main` ruleset keeps `restrict_updates` with the landing deploy key as the
only bypass actor, the PR cannot merge — landing additionally requires the explicit
approval, exact-SHA green CI evidence, and audited temporary ruleset intervention
described in the protection section above.

1. Sync from the current `origin/main`; create an isolated worktree and uniquely owned
   feature branch. Never make product changes in the primary worktree.
2. Record the task ID in branch/PR context. Inspect existing open and closed PRs for that
   head branch before creating one.
3. Implement only the assigned scope. Run relevant local tests and inspect the diff for
   secrets, generated data, and unrelated changes.
4. Commit and push the branch. Create one PR against `main`, or update the existing open PR
   for that branch. If branch ownership is ambiguous or multiple PRs exist, stop; do not
   guess which remote object to update.
5. Report the PR URL, head SHA, test evidence, and unresolved risks. Do not merge your own
   change unless separately authorized and repository protections permit it.
6. Treat review and required green CI as merge gates. A red, missing, cancelled, or stale CI
   run is not green.

PR creation idempotency key is
`pr-create:<repository-id>:<base-branch>:<head-branch>`. Before retrying an API timeout,
query by repository and head branch. If an open PR exists, return/update it. If only a closed
PR exists, require an intentional reopen or a new uniquely named branch; do not silently
create duplicate review history. One initial API attempt and two bounded retries are the
maximum.

## Requesting and operating a visual preview

### Request and eligibility

1. Confirm the PR is open, targets `main`, and comes from this repository.
2. Inspect the effective diff against its merge base. Confirm at least one rendered visual
   frontend path is changed and record the matching paths.
3. Reject docs-only, backend-only, CI/workflow-only, deployment-only,
   architecture/ADR/spec-only, and non-visual-test-only changes. For a mixed PR, explain the
   eligible rendered change.
4. Obtain authority: a human applies `preview:visual`, or an agent with explicit task/comment
   authority applies it. The label event is the trigger; paths alone never trigger deploy.
5. Wait for the required frontend build/checks for the current head SHA. Failed or stale
   checks stop the preview deployment.

### Deploy/update

The implementing workflow must:

1. derive the app name only from the validated configured prefix and numeric PR number;
2. enter concurrency group `preview-<repository-id>-<PR number>` and cancel an older run;
3. immediately before every remote mutation, query GitHub again and verify open state,
   label, eligibility, and exact head SHA;
4. create-or-observe the stable app, then deploy the current SHA using a preview-only token;
5. run reachability and route-specific visual smoke checks;
6. upsert one PR comment and write the job summary with:
   - canonical HTTPS preview URL;
   - PR number and deployed head SHA;
   - deployment timestamp;
   - Actions workflow run URL;
   - eligibility reason and smoke-check result.

Operation key is `preview-deploy:<repository-id>:<PR number>:<head SHA>`. If a run times out,
query the app's current release before retrying. A matching healthy release is success. A
different release is updated only after the latest-head guard passes. Stop after two failed
deploy attempts for that SHA and open the circuit; a human or a new head SHA may resume.

### Cleanup

Removing `preview:visual` or closing the PR revokes deploy authority and requests cleanup.

1. Re-read immutable event fields and current PR state. Derive—not accept—the app name.
2. Validate repository ID, numeric PR number, allowed prefix, expected full app name, and
   that the target is not a configured production app.
3. Cancel/serialize deploy and cleanup in the same per-PR concurrency group. The deploy path
   must recheck closed/unlabeled state so it cannot recreate the app.
4. Query the app. Absent means idempotent success. If present, capture app/release identity,
   destroy it with the preview-only token, then query again to verify absence.
5. Update the single PR comment/job summary with cleanup status. A failed query, destroy, or
   verification fails the job and alerts the owner; never hide it with `|| true`.

Cleanup operation key is `preview-cleanup:<repository-id>:<PR number>:closed-or-unlabeled`.
Retry only transient Fly failures twice with exponential backoff and jitter. Target mismatch,
permission error, or inability to verify absence opens the circuit immediately.

A scheduled orphan collector first produces a non-mutating inventory: app name and ID,
derived PR, PR state/labels, age, last release, proposed action, and exclusions. Apply mode
requires explicit human approval of that exact manifest, has a configured maximum app count,
uses the preview token, revalidates each target immediately before destroy, and stops on the
first identity mismatch. Production app names are hard exclusions.

## Normal production release

This section describes the ASK-class (PR-evidenced) release path. Note that while the
`main` ruleset keeps the landing deploy key as the sole `restrict_updates` bypass, step
2 cannot be a plain merge: landing the reviewed SHA requires the audited temporary
ruleset intervention from the protection section above.

1. Verify the PR was reviewed and all required checks succeeded for the merge candidate.
2. Land the reviewed, exact CI-tested SHA on `main` (via the audited ASK landing
   procedure while the deploy key remains the sole bypass actor).
3. Verify the `push` CI run on `main` succeeded. Record its URL and tested head SHA.
4. Verify the production workflow was caused by that successful CI run and checked out the
   same SHA. No branch, local checkout, artifact, or SHA substitution is allowed.
5. Verify backend health, frontend reachability, unauthenticated API behavior, and the
   production workflow conclusion. Record deployment/release IDs and smoke evidence.
6. If smoke checks fail, declare an incident. Do not repeatedly dispatch or deploy from a
   workstation.

Production operation key is `production-deploy:<environment>:<main SHA>`. A completed
matching release is success. An uncertain run is reconciled by checking workflow, Fly
release, and health evidence. Automated production deployment does not retry the whole
release more than once after a transient platform failure and never auto-rolls back. The
production concurrency group permits only one active deployment. Superseded queued runs
must be reviewed so an older SHA cannot deploy after a newer successful release.

Manual workflow dispatch is permitted only to re-run the workflow for the current `main`
SHA after an incident commander records the failed run, target SHA, reason, and bounded
single-use authority. It is not a way to release an unmerged branch or skip CI.

## Shared controls for costly and mutating operations

Before the first side effect, create or record an operation with action class, idempotency
key, target, desired revision, authority evidence, estimated cost/blast radius, attempt
count, and status. Valid statuses are `planned`, `in_progress`, `succeeded`,
`retryable_failure`, `circuit_open`, `reconciling`, and `failed`. Never log credentials,
private prompts, raw voice, or user content as evidence.

### Retry policy

- Default maximum: one initial attempt plus two retries within 15 minutes.
- Use exponential backoff with jitter and provider `Retry-After` guidance.
- Retry only explicit transient transport, rate-limit, or platform-unavailable failures.
- Never retry validation, authorization, stale revision, target mismatch, budget exceeded,
  deterministic 4xx, or unknown-result mutation without reconciliation.
- After a timeout, read current state using the idempotency key/target revision before any
  retry. Unknown state opens the circuit for destructive operations.

### Paid model calls

- Key each call by operation ID, stage, sealed input hash, model, and prompt version.
- Estimate tokens and worst-case cost before invocation; reject calls above the configured
  per-call or remaining operation/daily budget.
- Cache successful results under the key. Do not bill a second call because response
  delivery failed.
- Enforce model allow-list, maximum output tokens, maximum attempts, operation token/cost
  ceiling, daily project ceiling, and maximum concurrent calls.
- Open the provider/model circuit after three consecutive transient failures or any budget
  breach. Explicit authority and restored budget/provider health are required to resume.

### Data mutations

- Use command idempotency keys and expected record revisions; apply compare-and-set or a
  transaction.
- Record a dry-run manifest for bulk operations. It includes record IDs, expected revisions,
  changes, count, bytes, exclusions, and rollback/backup reference.
- Require human approval above configured record/byte thresholds or for delete, external
  dispatch, credential, privacy, or irreversible changes.
- Stop on the first revision conflict or unexpected target. Partial success is reconciled
  per record; never replay the whole batch blindly.

### PR/API mutation budgets

- One open PR per task-owned branch; no agent recursively creates follow-up PRs.
- Bound repository-wide concurrently open agent PRs and API attempts in configuration.
- Search before create and reconcile API timeouts before retrying.
- Permission errors, duplicate open PRs, or ambiguous ownership open the circuit.

A missing limit or spend cap is a fail-closed configuration error for paid calls, preview
creation, bulk mutation, and autonomous PR creation.

## Acceptance checks

Complete these before declaring an implementation of ADR-0003 conformant. Preserve links to
test runs or a redacted evidence packet.

### Preview trigger and eligibility

- [ ] An eligible open same-repository UI PR without `preview:visual` produces no Fly
      mutation and records `skipped: label absent`.
- [ ] Adding `preview:visual` to that PR triggers exactly one preview operation after current
      frontend checks pass.
- [ ] Docs-only, backend-only, CI/workflow-only, deployment-only, architecture/ADR/spec-only,
      and non-visual-test-only labeled fixtures each skip with the correct reason.
- [ ] A mixed PR with a real visual frontend change is eligible and reports matching paths.
- [ ] Fork PRs never receive secrets or a preview deploy.

### Identity, races, and reporting

- [ ] Open, synchronize, reopen, and rerun use one app name and canonical URL per PR.
- [ ] Two overlapping runs cannot create two apps; the older run is cancelled and a stale
      SHA cannot overwrite the newer preview.
- [ ] Closing or removing the label while deploy waits prevents every later mutation.
- [ ] The single upserted PR comment and job summary contain URL, latest head SHA, run URL,
      timestamp, eligibility reason, and passing smoke result.
- [ ] A rerun after successful deploy reconciles to the same release without duplicate app,
      comment, or avoidable secret mutation.

### Cleanup safeguards

- [ ] Close and label removal destroy only the derived preview and verify absence.
- [ ] Repeated cleanup of an absent app succeeds without mutation.
- [ ] Invalid prefix, nonnumeric PR, production target, repository mismatch, and target
      mismatch fail closed before destroy.
- [ ] A destroy/query failure is visible, opens the circuit where required, and cannot be
      reported as success.
- [ ] Orphan collection defaults to dry-run; apply rejects an expired/changed manifest and
      enforces its maximum target budget.

### Production and shared controls

- [ ] A reviewed PR with green required checks deploys production only after merge and the
      successful `push` CI run on `main`; deployed SHA equals CI-tested SHA.
- [ ] PR, branch, failed/stale CI, and ad-hoc local paths cannot trigger production.
- [ ] Manual dispatch rejects a non-`main` or unapproved incident context.
- [ ] Deploy, model-call, data-mutation, and PR-create fixtures prove idempotency after a
      simulated timeout and bounded retries after transient failure.
- [ ] Authorization, validation, stale revision, target mismatch, and budget errors are not
      retried.
- [ ] Each action class opens its circuit at the documented threshold, enforces configured
      spend/count/concurrency limits, and requires explicit resume.
- [ ] Audit evidence is complete and redacted; a secret-scanning test finds no credentials
      or private content.

## Incident and rollback procedure

### Declare and contain

1. Stop new side effects: remove `preview:visual` where relevant, disable or pause the narrow
   failing workflow/action, cancel queued runs, and open the applicable circuit. Do not
   delete evidence or broadly rotate/change infrastructure without authority.
2. Record incident owner, start time, affected environment/resources/users, last known good
   SHA/release, suspect SHA/run, symptoms, and links to CI, workflow, Fly release, and smoke
   evidence.
3. Classify target mismatch or possible cross-environment credential use as high severity.
   Revoke/rotate the affected scoped credential and inspect audit logs under human authority.

### Preview recovery

- If a preview is wrong but isolated, remove the label or close the PR and run guarded
  cleanup. Verify absence.
- If cleanup is failing, leave the circuit open and preserve the app identity. Use a
  human-approved exact-target destroy only after validating it is not production.
- Correct the workflow through a separate reviewed PR. Reapply the label only after the
  fix is merged and authority is renewed.

### Production rollback

1. Prefer a reviewed emergency revert PR against `main`. Run required CI, merge, and let the
   normal production workflow deploy the revert commit.
2. If active impact cannot wait, the incident commander may authorize `flyctl release
   revert` for the named production app and exact known-good release. Record approver,
   command/action, app ID, source and target release IDs, reason, time, and operator.
3. Revert backend before/with frontend only when compatibility is understood. Never roll
   back data schema or persisted data without a tested data rollback/forward-fix plan and
   backup evidence.
4. Run production smoke checks and focused user-path checks. If health is not restored,
   stop further automatic attempts and escalate.
5. Immediately create an emergency PR that makes `main` represent the safe production state
   or provides the forward fix. A platform-only revert is temporary containment.

### Close and learn

- Reconcile every operation whose outcome was unknown; mark duplicate/partial effects.
- Verify circuits are reset only after the cause is fixed, checks pass, budgets are restored,
  and an owner explicitly resumes them.
- Capture timeline, root cause, impact, evidence gaps, credential/budget effects, rollback
  result, and follow-up owners. Update this ADR/runbook if policy was ambiguous; implement
  workflow changes in separate reviewed PRs.

## Evidence packet template

```text
Action class / operation key:
Authority actor, source, scope, expiry:
Repository / PR / branch / head SHA:
Target resource IDs and expected state:
Eligibility or dry-run manifest:
Estimated and actual cost/blast radius:
Attempts, retry decisions, circuit state:
CI URL / workflow run URL / PR URL:
Resulting release or mutation IDs:
Smoke/postcondition result:
Rollback reference (if any):
Redactions applied:
```

## Related documentation

- [ADR-0003](decisions/0003-autonomous-delivery-guardrails.md)
- [Fly frontend review apps](fly-review-apps.md)
- [Fly deployment runbook](fly-deployment.md)
- [Agent delivery workflow](../AGENTS.md#agent-delivery-workflow)
