# Autonomous Delivery Guardrails Runbook

This runbook operationalizes
[ADR-0003](decisions/0003-autonomous-delivery-guardrails.md). It is the authority for
agent-created PRs, visual review apps, normal production releases, and incidents involving
those paths. It does not grant authority to mutate remote resources.

## Current-state warning

As of 2026-07-12, `.github/workflows/fly-review-frontend.yml` does **not** conform to
ADR-0003: it runs for every same-repository PR, lacks label/path eligibility, per-PR
concurrency, and a latest-head guard, and masks destroy failures. Do not infer compliance
from the workflow's existence. Deployment configuration changes belong in a separate,
reviewed implementation PR.

The active production workflow is maintained on `main`. Normal production release is:
reviewed PR -> required CI green -> merge to `main` -> successful `push` CI workflow ->
production workflow checks out and deploys that tested SHA -> smoke checks. No operator or
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

## Standard implementation and PR procedure

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

1. Verify the PR was reviewed and all required checks succeeded for the merge candidate.
2. Merge to `main` through the repository's normal merge controls.
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
