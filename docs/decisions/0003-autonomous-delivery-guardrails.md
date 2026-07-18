# ADR-0003: Gate autonomous delivery through auditable previews and the normal release path

Date: 2026-07-12
Status: Proposed
Decision owner: BrainBuddy
Related: ADR-0001, ADR-0002, `docs/autonomous-delivery-runbook.md`, Kanban task
`t_ad20c33d`

## Context

BrainBuddy uses agents to prepare changes in isolated worktrees and propose them through pull
requests. The repository also has a Fly frontend review-app workflow, while the active
production workflow on `main` deploys the exact revision that passed CI. Remote deployment,
model inference, data mutation, and PR creation all have cost or irreversible side effects.
Retries and overlapping automation can multiply those effects.

A preview is useful only when a reviewer must judge rendered UI. Deploying every PR wastes
money and gives architecture, documentation, backend, and CI changes an unnecessary remote
mutation path. Conversely, an implicit path filter is not enough authority to spend money:
a reviewer or explicitly authorized agent needs a visible, attributable way to request the
preview.

The current review workflow predates this decision. It deploys every same-repository PR,
has no per-PR concurrency or stale-head guard, and suppresses cleanup failures. This ADR is
the target policy; the operational runbook identifies those gaps. This task changes policy
and documentation only, not deployment configuration.

## Decision

### Normal implementation and production release path

Every product change is implemented in an isolated git worktree and feature branch. The
agent commits and pushes that branch and opens or updates one PR against `main`. Review and
all required CI checks are merge gates.

Production deployment occurs only through the repository's existing merge-to-`main` path:
a successful CI run for a `push` to `main` causes the production workflow to deploy the
CI-tested commit. Agents and operators must not run ad-hoc `flyctl deploy` commands against
production, dispatch production deployment for an unmerged branch, change a workflow event
to bypass review, or treat a preview as production. Manual workflow dispatch is not a
routine release path; it may only re-run the production workflow for the current `main`
revision during an authorized incident or recovery, with the evidence described in the
runbook.

A rollback is an incident action, not an alternate release path. Prefer reverting the bad
change through a reviewed emergency PR so `main`, CI evidence, and production converge. A
Fly release revert is permitted only to contain an active incident under scoped human
authority; the repository must then be reconciled immediately through the normal PR path.

### Explicit visual-preview trigger

The single preview trigger is the GitHub label `preview:visual` on an open PR. A workflow
run caused by adding, reopening with, or synchronizing a PR that has this label is auditable
in the PR timeline and Actions history. A natural-language request, commit message, path
match, bot comment, or direct `flyctl` invocation is not a trigger.

A human reviewer may apply the label. An agent may apply it only when its task or a current
PR comment explicitly grants authority to obtain a visual preview for that PR. The actor,
trigger event, PR number, head SHA, eligibility result, and workflow run URL are retained in
workflow evidence.

A labeled PR is eligible only when all of these are true:

1. it is open and targets `main`;
2. its head repository is this repository (forks are ineligible for secret-bearing runs);
3. its current head SHA has a successful frontend build and required preview checks;
4. its effective diff contains a reviewable frontend visual change, such as files under
   `frontend/src/`, visual assets served by the frontend, frontend styling/configuration,
   or an explicitly reviewable prototype under `frontend/`;
5. it is not docs-only, backend-only, CI/workflow-only, deployment-only, test-only without a
   rendered UI change, or architecture/ADR/spec-only.

Path eligibility is necessary but not sufficient: the explicit label is always required.
If a mixed PR includes an eligible visual change it may receive one preview; reviewers must
not add an unrelated frontend file merely to qualify. Eligibility evaluation and the reason
for deploy or skip must appear in the job summary.

### One preview identity per PR

A PR has exactly one stable preview identity:

- logical key: `<repository-id>:pull-request:<number>`;
- Fly app name: the validated configured prefix plus `-<PR number>`;
- canonical URL: `https://<app-name>.fly.dev`;
- deployed revision: the latest eligible PR head SHA.

Synchronize and rerun events update the same app; they never create a second app for the
same PR. Deployment uses concurrency group `preview-<repository-id>-<PR number>` with
`cancel-in-progress: true`. Before any create, secret update, or deploy, the run re-reads the
PR and stops unless it is open, still labeled and eligible, and its head SHA equals the run's
SHA. App creation is create-or-observe: an already-existing correctly named app is success,
not a reason to create a variant.

On success, automation upserts one bot-authored PR comment containing the canonical preview
URL, deployed head SHA, deployment time, workflow run URL, and smoke-check result. It also
writes the same URL and SHA to the Actions job summary. It must not emit only a transient log
line or create a new comment on every run.

Removing `preview:visual` or closing the PR starts cleanup. Cleanup validates repository,
PR number, prefix, and derived app name before mutation; it never accepts a free-form app
name from PR content. It destroys only that PR's preview, treats an already-absent app as
success, verifies absence, and reports the outcome. A stale deploy must not recreate an app
after close. Cleanup failure is visible and retryable; it is never hidden with an unconditional
success. A scheduled orphan reconciler may compare open, labeled, eligible PR identities to
prefix-matching apps, but defaults to dry-run and requires separately authorized destructive
execution.

### Authority and evidence for remote actions

Possession of credentials is not authority. Every destructive or cost-bearing remote action
requires all of:

1. **Scoped authority:** a repository event, task statement, or current human approval that
   names the action class and target; production rollback and bulk cleanup always require a
   human authorization tied to the incident or dry-run inventory.
2. **Precondition evidence:** target identity, expected current state/revision, eligibility,
   and blast radius captured before mutation.
3. **Least privilege:** separate preview and production credentials and environment-scoped
   secrets; no untrusted PR code receives credentials.
4. **Postcondition evidence:** immutable run URL or audit record, resulting resource ID and
   state, smoke result, and a redacted failure reason. Secrets and private user content are
   never evidence payloads.

Delete/destroy, force-update, production rollback, remote data repair, secret rotation, and
bulk mutation are destructive. Ambiguous target identity, stale expected revision, missing
approval, or unavailable audit storage fails closed.

### Duplicate, retry, circuit-breaker, and budget controls

All side-effecting operations use a durable operation record keyed by
`<action-class>:<target-id>:<desired-revision>`. Before acting, automation checks for a
completed operation and returns its evidence; a retry resumes or reconciles an uncertain
operation rather than starting another.

| Action class | Idempotency and retry boundary | Circuit breaker | Budget/limit |
|---|---|---|---|
| Preview/production deploy | One operation per app/environment and commit SHA; query current release before retry; latest-head guard for previews | Stop after 2 failed deploy attempts for a target revision or any target mismatch; no automatic production rollback | At most one active preview per PR; per-PR concurrency; repository-wide preview count and monthly Fly spend caps |
| Paid model call | Key by workflow operation, stage, sealed input hash, model, and prompt version; cache a completed response; retry only provider-declared transient failures with jitter | Open after 3 consecutive provider failures or the configured token/cost estimate is exceeded; require explicit resume | Per-operation token/cost ceiling, daily project ceiling, max attempts, and model allow-list checked before invocation |
| Data mutation | Key by command and target revision; use compare-and-set/transaction; reconcile timeout by reading the target before retry | Stop on revision conflict, unknown outcome, validation failure, or repeated partial failure | Max records and bytes per operation; bulk actions require dry-run manifest and human approval above the configured threshold |
| PR creation/update | One PR identity per worktree branch and target base; search open and closed PRs before create; update the existing open PR | Stop on ambiguous branch ownership, duplicate open PR, permission failure, or repeated API failure | One open PR per task/branch; no recursive PR creation; bounded API attempts and repository-wide agent PR concurrency |

Retries use bounded exponential backoff with jitter, honor provider retry hints, and never
retry authorization, validation, stale-revision, or budget errors. Defaults are one initial
attempt plus two retries unless a stricter row applies. Automated retries stop within 15
minutes; resumption creates linked audit evidence. Budget configuration must be explicit in
the implementing workflow/service. A missing budget is a configuration failure, not
unlimited permission.

## Consequences

- Review apps become intentional visual-review artifacts instead of a side effect of every
  PR, reducing cost and remote mutation surface.
- Reviewers get a stable URL and can tie what they saw to a head SHA and workflow run.
- Production remains reproducible from reviewed, CI-tested `main`, while incident rollback
  remains possible under explicit authority.
- Delivery automation must add state checks, evidence, rate/cost limits, and observable
  cleanup before it conforms to this policy.
- The explicit label adds one reviewer action. This is deliberate friction at the spend and
  remote-mutation boundary.

## Alternatives considered

### Preview every same-repository PR

Rejected. It spends money and creates remote resources for changes with no visual acceptance
value, while path changes alone do not express authority.

### Trigger previews from paths only

Rejected. Paths establish eligibility, not intent. A visible label gives reviewers an
attributable trigger and supports removal to revoke authority.

### Use one preview app per commit

Rejected. It leaks apps across updates and makes the URL unstable. One app per PR with a
recorded deployed SHA preserves both usability and auditability.

### Allow agents to deploy production directly after local tests

Rejected. Local evidence is not a substitute for review, required CI, merge provenance, and
the protected production credential boundary.

## Verification

Implementation conforms only when all acceptance checks in
`docs/autonomous-delivery-runbook.md` pass. In particular, tests must demonstrate ineligible
PRs are skipped, stale runs cannot overwrite or recreate previews, one URL is reported for
the latest head SHA, cleanup is safe and observable, and production deploys only the
CI-successful `main` revision.

No workflow or deployment configuration is changed by this ADR.

## Related files

- `docs/autonomous-delivery-runbook.md`
- `docs/fly-review-apps.md`
- `docs/fly-deployment.md`
- `.github/workflows/fly-review-frontend.yml`
- `.github/workflows/ci.yml`
