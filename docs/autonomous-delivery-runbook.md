# Autonomous Delivery Guardrails Runbook

This runbook operationalizes
[ADR-0003](decisions/0003-autonomous-delivery-guardrails.md) and
[ADR-0008](decisions/0008-verified-trunk-serial-landing.md), as amended for bounded
SHIP/SHOW work by [ADR-0023](decisions/0023-proportionate-fast-lane-for-test-stage-ship-show.md)
and partially superseded by [ADR-0035](decisions/0035-merge-queue-pr-landing.md), under
which every change lands as a pull request through the merge queue.
It is the authority for
merge-queue landings, agent-created PRs, visual review apps, normal
production releases, and incidents involving those paths. It does not grant authority to
mutate remote resources.

## Writer pre-freeze receipt (local, typed, fail-closed)

Before freezing a candidate, the implementation writer owns a receipt conforming
to `.specify/templates/pre-freeze-receipt.schema.json` and validates it with
`python3 scripts/validate_pre_freeze_receipt.py <receipt> --sha <full-lowercase-sha>`.
The contract is `brainbuddy.pre-freeze-writer-receipt/v1`: it records the full
lowercase implementation SHA, changed-path inventory, and each stable writer gate
(`writer.tests`, `writer.verify_all`, `writer.path_classification`, and
`writer.diff_review`) as `PASS` or concretely justified `NOT_APPLICABLE`, with
the exact command, observation, and evidence. Missing, failed, unverified,
duplicate, unknown, malformed-SHA, or unjustified-N/A entries are rejected.

These are only local pre-freeze writer gates. The risk-selected independent review
or QA gate, exact-SHA CI, landing, deployment, and production smoke are post-freeze
obligations; they remain governed by ADR-0008 and ADR-0023 and cannot be claimed or
replaced by this receipt.

No landing tool consumes the receipt any more: `scripts/submit_to_trunk.sh`, which
required it through `SUBMIT_TRUNK_PRE_FREEZE_RECEIPT`, is retired by ADR-0035 and
fails fast. Where a task or the full path requires a receipt, validate it against the
frozen PR head SHA before the independent gate.

## Balanced fast lane (eligible SHIP/SHOW changes)

ADR-0023 is the default for a bounded change mechanically proven non-ASK and explicitly
classified semantically as SHIP or SHOW. The full path applies to a significant new
capability, a cross-surface contract change, a persistence/schema change, a materially
changed workflow/state-machine boundary, or any ASK-class outcome. The path classifier
enforces ASK versus non-ASK; every user-visible non-ASK change is semantically SHOW.

1. Record the lightweight brief: accepted outcome, non-goals, acceptance evidence,
   and untouched scope. Do not create a Spec Kit campaign or managed Kanban outcome
   merely to restate that bounded slice.
2. Run the smallest relevant deterministic writer checks, then freeze one candidate
   SHA. `writer.verify_all` may be `NOT_APPLICABLE` only with a concrete receipt
   justification; full required CI still runs on the exact candidate SHA.
3. Choose exactly one independent gate by dominant risk: code
   review for implementation/contract correctness, or QA for rendered interaction and
   the user journey. The actor must not be the writer. Material mixed risk or a contract
   requiring both disciplines moves the outcome to the full path; replace an incapable
   selected gate or escalate instead of accumulating a second fast-lane gate.
4. After the standard authenticated production smoke, add one bounded production
   journey only for user-visible SHOW work. A separate protected browser/identity gate
   is triggered only by changes to auth, permissions, cohort/flag exposure,
   browser-only behavior, or an explicit accepted criterion.

All ASK changes and ineligible SHIP/SHOW changes use the existing full path. Fast-lane
eligibility never bypasses path classification, CI, landing proof, smoke, cleanup, or
rollback.

## Merge-queue landing (every change)

ADR-0035 makes a pull request through the merge queue the only landing path, for SHIP,
SHOW and ASK alike. PR-less landing through `scripts/submit_to_trunk.sh` and
`trunk-candidate/<sha>` refs is retired; the script fails fast and pushes nothing.
ASK-class changes (under ADR-0030: persisted data and migrations, secrets, GitHub
workflows, GDPR account deletion/export, `allurerc.mjs`, and the landing gate itself)
take the same path and additionally need recorded owner approval (below).

### Procedure

1. Implement the slice in an isolated worktree and branch created from the current
   `origin/main`, under
   [Constitution Principle II's testing policy](../.specify/memory/constitution.md#ii-tested-delivery-across-stack).
2. Classify every changed path with `scripts/classify_path_risk.py --null`, fed by
   `git diff --no-renames --name-only -z origin/main...HEAD` (NUL-separated, so
   non-ASCII paths classify on their real names and a rename away from an ASK path
   still surfaces as its deletion). Every user-visible non-ASK change is semantically
   SHOW. Record the class in the PR description.
3. Freeze the PR head and obtain ADR-0023's risk-selected independent gate on that
   exact SHA. On the full path, obtain every gate required by its accepted criteria. A
   new push to the PR head invalidates verdicts given for the old head.
4. Open the PR against `main` (see the PR procedure below). Required `Full CI` and
   `Docker Images` run on the PR head; every review thread must be resolved. A skipped
   required job fails `full-ci`, so a landing can never ride on a vacuously green gate.
   PR CI holds **no write permission and pushes nothing**.
5. For ASK, obtain explicit recorded owner approval on the PR for the exact head SHA
   (a PR review approval, or a PR comment by the owner naming that SHA) before the PR
   enters the queue. A new push needs a fresh approval.
6. Add the PR to the merge queue. The queue builds a merge-group commit on the current
   `main` (and any entries ahead of it), runs `Full CI` and `Docker Images` on that exact
   commit, and moves `main` to it only when the whole group is green. A failed or
   ejected entry lands nothing; fix the PR and enqueue it again.
7. The push to `main` runs CI on `main`. The completed successful run triggers the
   **default-branch release workflow** (`deploy-fly-production.yml`; `workflow_run`
   always executes the `main` copy of the definition, so a PR's workflow edits cannot
   affect its own release). For a `main` run its `land` job (read-only token) pushes
   nothing and proves `origin/main` equals the tested SHA. The
   `fly-production-deploy` concurrency group is safety serialization, **not a FIFO
   queue**: at most one release runs and at most one more stays pending; GitHub may
   cancel additional pending runs, which then fail closed.
8. The `deploy` job of the same run starts only after that proof (`needs: land`),
   holds the production environment and Fly secrets under `contents: read`, and
   re-verifies that `origin/main` equals the tested `workflow_run.head_sha` immediately
   before any Fly mutation, so a stale CI run that completes late can never redeploy a
   superseded SHA. Significant new capabilities use server-owned feature flags
   (default OFF). Corrections to expected existing behavior do not require a new flag,
   per the owner's 2026-09-06 decision in ADR-0022; all verification and rollback
   requirements still apply. `delivery_canary` still rolls out OFF → INTERNAL → ON via
   `BRAIN_BUDDY_FEATURE_FLAGS` / `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` at
   deploy time. The SQLite-managed flags (`voice_brain_dump`,
   `external_agent_relay`, ...) instead roll out
   OFF → SELECTED_USERS → ON through the Admin Portal at runtime, independent
   of this landing/deploy path (ADR-0019).
9. Evidence for the landing is the PR (with the class and, for ASK, the approval), the
   selected independent-gate verdict on the PR head SHA, the merge-group CI run and its
   SHA, the `main` CI run, and the release workflow run (its `land` and `deploy` jobs),
   plus the bounded production journey for user-visible SHOW work. Record their URLs
   where a task requires an evidence packet.

Stated honestly: the ruleset requires 0 approvals and no landing gate runs the
classifier any more, so the ASK approval is a recorded procedural rule, not a mechanical
refusal. Never enqueue an ASK PR without it, and never land through a ruleset bypass.

**Known red runs (follow-up, not a failure of the landing).** When a newer merge moves
`main` before an older `main` CI run's release reaches it, that release fails at
"Prove origin/main equals the tested revision" (for example runs 39015900101,
39015104318 and 39011410547). Failing closed is correct, and the newer `main` run
releases the newer SHA. Cancelling superseded runs instead (`concurrency`) is a separate
ASK workflow change; until then, check that the newest `main` release succeeded rather
than retrying the superseded one.

### Bootstrap and verification of `main` protection (owner, ASK)

The power to deploy lives **only** in the default-branch copy of
`.github/workflows/deploy-fly-production.yml`. Changes to the delivery machinery
itself (workflows, the landing gate) are ASK class and land through the same PR path
with recorded owner approval.

Agents never change GitHub settings. The owner verifies, by hand and with
`gh api repos/maxk-lab/brain_buddy/rulesets/11196382`, before claiming the path is
healthy — every item is a MUST:

1. The `main` ruleset `Tests` is active and requires `Full CI` and `Docker Images`
   (strict), a pull request with every review thread resolved, and the merge queue
   (`MERGE`, `ALLGREEN`).
2. The ruleset blocks deletion of `main`. **Open item:** the `deletion` rule was
   removed on 2026-10-16; the owner restores it.
3. The bypass actors are only the intended owner accounts.
4. The `production` environment is restricted to branch `main`, holds
   `FLY_API_TOKEN`, `BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`,
   `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`, and `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`,
   and **no repository-level `FLY_API_TOKEN`** exists.
5. The owner decides whether to delete the unused `verified-trunk-landing` deploy key
   and the `landing` secret `TRUNK_LANDING_SSH_KEY` (see ADR-0035).

### Activation canary record (2026-07-22, historical)

This record documents the retired ADR-0008 trunk path and is kept as history.

Bootstrap SHA `938abd4cbf9fe73ad234d4247d40fb780d0db5a6` passed exact-SHA
candidate CI run `29961113907`, was explicitly fast-forwarded during the bounded
bootstrap window, and passed main CI run `29961801317` plus production release and
authenticated smoke run `29962336315`. The ruleset and environment checks of the
ADR-0008 bootstrap were verified immediately afterward. The docs-only commit containing this activation
record is the required first end-to-end automatic candidate: its successful release
run is the canonical evidence that the dedicated deploy key can land a fresh SHIP
candidate while ordinary workflow tokens remain unable to update `main`.

### Required `main` protection, landing identity, and production environment (maintainer, ASK)

Configure the repository so `main` accepts only merge-queue landings. These are GitHub
settings changes performed manually by the maintainer — never automated — and they
are requirements (MUST), not recommendations. Each is also a verification item in the
section above:

- The `main` ruleset MUST require a **pull request** (every review thread resolved)
  and the **merge queue** (`MERGE`, `ALLGREEN`), and MUST block **deletion**. Direct
  pushes to `main` from every actor that is not a bypass actor, including the default
  `GITHUB_TOKEN` and every workflow token, are then rejected. The bypass actors are the
  owner's emergency access; a landing through a bypass is an incident recorded with the
  evidence packet below, and agents never use it.
- The **`Full CI`** and **`Docker Images`** status checks MUST be required on `main`
  (strict), so every PR and every merge group lands only behind the no-skip aggregate
  gate.
- The `landing` environment keeps its branch policy allowing only `main` for as long
  as `TRUNK_LANDING_SSH_KEY` exists in it, although the key no longer has landing
  power.
- The `production` environment MUST restrict its deployments to branch `main`
  (custom branch policy) and MUST hold `FLY_API_TOKEN`, `BRAIN_BUDDY_ADMIN_EMAIL`,
  `BRAIN_BUDDY_ADMIN_PASSWORD`, `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`, and
  `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` as environment secrets, so only
  default-branch `workflow_run` executions can read them.
- **No repository-level `FLY_API_TOKEN` may exist** — the token lives only in the
  `production` environment. (In-repo defense-in-depth: the trunk validator forbids
  candidate-controlled CI from requesting either the `landing` or the `production`
  environment.)
- ASK-class changes land through the same PR and merge-queue path, with explicit
  recorded owner approval on the PR for the exact head SHA before enqueueing. There
  is no temporary ruleset intervention.

### Leftover candidate refs

No new `trunk-candidate/<sha>` refs are pushed since ADR-0035. A leftover ref from the
retired path is inert — a landing on it fails the fresh-parent check because `main` has
moved, and the deploy key can no longer push `main` — and is removed manually with:

```bash
git push origin --delete trunk-candidate/<sha>
```

### Required secrets (GitHub `landing` and `production` environments)

- `TRUNK_LANDING_SSH_KEY` (**`landing` environment**, branch policy `main` only) — the
  private half of the `verified-trunk-landing` deploy key that the retired ADR-0008
  path used for its fast-forward push. Since ADR-0035 it has no landing power (the
  ruleset no longer lets the key update `main`); deleting it is an owner decision. No
  PAT secret exists and no workflow holds `GITHUB_TOKEN` write; PR CI holds no write
  credential at all and can never read this secret. It is the only secret the `land`
  job may reference; everything below lives in the separate `production` environment,
  readable only by the `deploy` job.
- `FLY_API_TOKEN` (**`production` environment**, branch policy `main` only) — Fly
  deploy credential. It MUST exist only as a `production` environment secret; a
  repository-level `FLY_API_TOKEN` MUST NOT exist (verified at bootstrap).
- `BRAIN_BUDDY_ADMIN_EMAIL` / `BRAIN_BUDDY_ADMIN_PASSWORD` — the production smoke
  identity. The deploy stages them into the Fly backend (see below) so the backend
  seeds/rotates this admin account on release; the smoke logs in with the same values.
  Missing secrets fail the deploy before any mutation.
- `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` — the durable production operator allow-list,
  staged from this dedicated secret on every release and never aliased to the rotating
  smoke admin identity.
- `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` — comma-separated internal cohort; it must
  include the admin email. This is enforced mechanically before any remote mutation:
  `scripts/check_smoke_identity_cohort.py` fails the deploy (naming variable names
  only, never values) when any secret is missing or the identity would not survive
  backend startup validation, which the preflight mirrors — the normalized admin
  email and every normalized cohort entry must be email-shaped (contain `@`), the
  password must satisfy the backend password policy (12–128 characters), and the
  normalized admin email must be a member of the normalized cohort.
- The admin identity and internal cohort are the only smoke-related GitHub secrets.
  The operator allow-list is an independent deployment secret. The smoke script's
  `BRAIN_BUDDY_SMOKE_EMAIL` / `BRAIN_BUDDY_SMOKE_PASSWORD` are its private process-env
  names, mapped inside the deploy step from the admin secrets — do not create GitHub
  secrets with the `BRAIN_BUDDY_SMOKE_*` names.
- The `main` ruleset MUST keep the pull-request, merge-queue and deletion rules and
  the `Full CI` + `Docker Images` checks required (see the protection section above).
  Changing that ruleset is itself ASK-class.

### Production smoke and automatic rollback

The deploy workflow captures the previous backend and frontend release images before
deploying, using the documented `flyctl releases --app <app> --image --json` form parsed
by `scripts/capture_fly_release_image.py` (tolerant of Fly's JSON field casings; only
`registry.fly.io/` refs are accepted, and only from releases whose status — when
present — is a known successful terminal state: `complete`, `succeeded`, or
`success`); failed capture aborts the run before any mutation. It then stages the smoke identity into the Fly backend with
`flyctl secrets set --stage` (`BRAIN_BUDDY_ADMIN_EMAIL`, `BRAIN_BUDDY_ADMIN_PASSWORD`,
`BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`, `BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS`, and the
production feature-flag assignment; values are never printed), so the deploy release
seeds the admin smoke account, preserves the durable operator allow-list, and marks the
smoke account internal. The trusted deploy workflow is authoritative for the exact
production flag assignment. Its staged value is restaged on every deploy, so a manual
`flyctl secrets set BRAIN_BUDDY_FEATURE_FLAGS` is reverted by the next release; change the
rollout in the workflow instead.

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
healthy release with `flyctl releases --app <app> --image` and the exact `TESTED_SHA` of
the failed release. Derive `PREVIOUS_FEATURE_FLAGS` the same way the workflow's own
rollback step does — never hardcode or guess it — by reading the PREVIOUS revision of the
deploy workflow (`${TESTED_SHA}^`, the parent of the failed release) through the
unit-tested `scripts/extract_staged_feature_flags.py` parser:
`git show "${TESTED_SHA}^:.github/workflows/deploy-fly-production.yml" | python3
scripts/extract_staged_feature_flags.py`. That parser fails closed on anything malformed
or ambiguous and never prints a flag name or value; require its output to be non-empty.
If extraction is unavailable or its output is empty, refuse the image rollback outright —
do not guess or substitute a hardcoded delivery-only rollout — and use containment and
escalation instead. Otherwise stage the derived value with `flyctl secrets set --stage
--app <app> BRAIN_BUDDY_FEATURE_FLAGS="${PREVIOUS_FEATURE_FLAGS}"` BEFORE redeploying the
backend image — that deploy is the release which applies the pending secret, so staging
after it would leave the restored image running the failing release's flags — then
redeploy the captured images with `flyctl deploy --config <config> --app <app> --image
<captured registry.fly.io ref>` (frontend first, then backend), and re-run
`scripts/production_smoke.sh` against production before declaring containment.

## Current preview implementation

`.github/workflows/fly-review-frontend.yml` implements the ADR-0003 preview boundary:
`preview:visual` is mandatory, rendered frontend paths are checked, fork/backend-only/docs-only
PRs fail closed, per-PR concurrency cancels stale deployments, and the live head is re-read
immediately before Fly mutation. Removing the label or closing the PR destroys only the
derived PR app and verifies absence. The workflow requires a separate preview-only
`FLY_PREVIEW_API_TOKEN`; production credentials are not a fallback.

The active production workflow is maintained on `main`. The release shape for every
change is: reviewed PR -> required CI green -> merge queue lands the green merge-group
commit on `main` -> successful `push` CI workflow -> production workflow checks out and
deploys that tested SHA -> smoke checks. No operator or agent runs an ad-hoc Fly
production deploy.

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

## Standard implementation and PR procedure (every change)

Under ADR-0035 the PR is the landing vehicle for every change and the review-evidence
vehicle for ASK. It lands through the merge queue as described in the merge-queue
landing procedure above; ASK additionally needs the recorded owner approval before
enqueueing.

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

This section describes the release path every change takes after its PR (ADR-0035).

1. Verify the PR was reviewed and all required checks succeeded for the merge candidate.
2. Land through the merge queue, which moves `main` to the exact CI-tested merge-group
   commit (for ASK, only after the recorded owner approval).
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

Identity storage adds a mandatory boundary to every image restore. The release
workflow captures the actual running backend's storage capability with
`scripts/auth_migration_guard.py capture`, checks the fresh volume before any
deploy mutation, and checks it again before restoring either image or the old
rollout. Schema epoch 1 already requires a SQLite-capable binary, including an
empty database without a legacy import. A commit after capture, an unreachable
probe or malformed evidence forbids the restore. Do not override the guard or
restore JSON files to make an old image start.

For the first transition without a compatible captured image, keep the volume
and its migration checkpoint intact and leave the release failed. Under the
incident's recorded exact-target authority, drain ingress, disable machine
autostart and stop all backend writers; verify that none restarted before
repair. Record only the schema/checkpoint and correlation ID. Repair forward
from SQLite-capable code with green exact-SHA CI, the recorded ASK landing and
the normal release workflow. Native clients keep their local documents/outbox.
Redeploying the failed candidate is not evidence of recovery. Restoring an
encrypted preimport backup is a separately approved data-recovery operation
with a stated loss boundary. Rehearse this path against synthetic storage
before the first production migration.

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
- [ADR-0035](decisions/0035-merge-queue-pr-landing.md)
- [Fly frontend review apps](fly-review-apps.md)
- [Fly deployment runbook](fly-deployment.md)
- [Agent delivery workflow](../AGENTS.md#agent-delivery-workflow)
