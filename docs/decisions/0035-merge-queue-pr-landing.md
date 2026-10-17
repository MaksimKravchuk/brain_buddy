# ADR-0035: Every change lands as a pull request through the merge queue

Date: 2026-10-17
Status: Accepted by the product owner, 2026-10-17
Decision owner: BrainBuddy
Partially supersedes: [ADR-0008](0008-verified-trunk-serial-landing.md) (delivery path,
ASK landing procedure, `main` ruleset requirements, landing identity, bootstrap ruleset
steps); [ADR-0023](0023-proportionate-fast-lane-for-test-stage-ship-show.md) and
[ADR-0030](0030-pre-launch-narrow-ask-class.md) where they name the verified-trunk
landing path or `scripts/submit_to_trunk.sh`
Preserves: Ship/Show/Ask classification through `scripts/classify_path_risk.py`
(as narrowed by ADR-0030), exact-SHA required CI, the release workflow's re-verification
of `origin/main` before deploy, the authenticated production smoke and verified rollback
Related: ADR-0003, ADR-0034, `docs/autonomous-delivery-runbook.md`, issues #513 and #514

## Context

ADR-0008 made PR-less landing the normal path for SHIP and SHOW changes:
`scripts/submit_to_trunk.sh` pushed one candidate commit to `trunk-candidate/<sha>`,
full CI ran there, and the release workflow's `land` job fast-forwarded `main` with the
`TRUNK_LANDING_SSH_KEY` deploy key. That path depended on the `main` ruleset letting
only that deploy key update `main` (`restrict_updates`, deploy key as the sole bypass
actor). ASK changes needed a short, audited, temporary ruleset intervention because no
PR merge could update `main`.

The `main` ruleset `Tests` (id 11196382) matched that design up to version 50837207
(2026-09-25): bypass actors `DeployKey` and `RepositoryRole 5` (both `always`), and
the rules `deletion`, `required_status_checks` (`Full CI` and `Docker Images`, strict)
and `update` (restrict updates).

On 2026-10-16, between 00:07 and 00:38 CEST, a repository administrator (GitHub user
105209543) edited the ruleset five times. Read with
`gh api repos/maxk-lab/brain_buddy/rulesets/11196382` on 2026-10-17, it now has:

- bypass actors: `OrganizationAdmin` and two `User` actors, all `always`; the deploy
  key is no longer a bypass actor;
- `required_status_checks`: `Full CI` and `Docker Images`, strict;
- `pull_request`: 0 required approvals, review threads must be resolved;
- `merge_queue`: merge method `MERGE`, grouping `ALLGREEN`;
- no `update` rule and no `deletion` rule.

Since then:

- The release workflow's `land` job cannot push `main`. Run 38977046868 failed at
  "Fast-forward main to the exact tested SHA" with "Permission to
  maxk-lab/brain_buddy.git denied to deploy key" (#513). Candidate
  `trunk-candidate/58b5c07d` was green and later landed as PR #505.
- The deploy key itself is not the cause #513 suggested. The key
  `verified-trunk-landing` (id 158071892) has write access (`read_only: false`), and
  the `landing` secret `TRUNK_LANDING_SSH_KEY` was written when the key was created
  (2026-07-22T21:24). The deciding change is the removed deploy-key bypass. Separately,
  the organization setting `deploy_keys_enabled_for_repositories` reads `false`
  (checked 2026-10-17, also recorded in
  `docs/runbooks/results/manual-mac-028-030-retest-2026-10-16.md`). GitHub documents
  that this disables existing deploy keys, so the old path would need both settings
  reversed.
- PRs #500, #505 and #518–#521 landed through the merge queue behind `Full CI` and
  `Docker Images`. Each merge pushed `main`, and that push ran CI and the release
  workflow's deploy path.
- `AGENTS.md`, the runbook and ADR-0008 still required `restrict_updates` with the
  deploy key as the only bypass actor, and a temporary ruleset intervention for ASK
  (#514).

The owner confirmed on 2026-10-17 that the ruleset change was intentional and chose to
make the documentation match it (option B of #514).

## Decision

### Delivery path

Every change, whether SHIP, SHOW or ASK, lands as a pull request against `main`
through the merge queue:

1. Work in an isolated worktree and branch created from the current `origin/main`.
2. Classify the change. `scripts/classify_path_risk.py --null`, fed by
   `git diff --no-renames --name-only -z origin/main...HEAD`, decides ASK versus
   non-ASK. Every user-visible non-ASK change is semantically SHOW. Record the class
   in the PR description.
3. Freeze the PR head and obtain the gates the change needs: ADR-0023's single
   risk-selected independent gate for an eligible fast-lane change, or every gate of the
   full path. A new push to the PR head invalidates verdicts given for the old head.
4. Open the PR. `Full CI` and `Docker Images` run on the PR head, and every review
   thread must be resolved.
5. Add the PR to the merge queue. The queue builds a merge-group commit on top of the
   current `main` (and of any queue entries ahead of it) and runs `Full CI` and
   `Docker Images` on that exact commit. Only a fully green group lands. `main` then
   points to the merge-group commit that passed.
6. The push to `main` runs CI on `main`. The default-branch release workflow consumes
   that successful run, proves in its `land` job that `origin/main` equals the tested
   SHA (it pushes nothing for a `main` run), and its `deploy` job re-verifies the same
   SHA immediately before any Fly mutation, runs the authenticated production smoke and
   rolls back verified on failure (unchanged ADR-0008 mechanics).

The SHA that is tested, lands and deploys is the merge-group commit. The independent
gate covers the PR head that commit merges. Evidence records both SHAs: the reviewed
PR head and the tested and deployed merge-group SHA.

### Ship / Show / Ask

The classes and the classifier (ADR-0008, narrowed by ADR-0030) are unchanged. Only the
landing differs:

- **SHIP**: enqueue once the selected gate and the required checks are green.
- **SHOW**: as SHIP, and surface the change after landing (the PR description serves).
  Rollout starts OFF or INTERNAL where a flag applies.
- **ASK**: as SHIP, and additionally requires **explicit recorded owner approval on
  the PR** for the exact PR head SHA (a PR review approval or a PR comment by the owner
  naming that SHA) before the PR enters the queue. A new push to the PR head needs a
  fresh approval. No temporary ruleset intervention exists any more.

Stated honestly: the ruleset requires 0 approvals, so the ASK approval is a recorded
procedural rule, not a mechanical one. No landing gate runs the classifier any more:
`submit_to_trunk.sh` is retired, and the release workflow's classifier step only runs
for `trunk-candidate/**` refs. The classifier remains the authority for the class and
for ADR-0023 eligibility and planning-risk derivation. Agents never enqueue an ASK PR
without the recorded approval, and never use a ruleset bypass to land anything.

### `main` protection (owner-maintained, ASK)

The `main` ruleset MUST:

- require the `Full CI` and `Docker Images` status checks, strict (up to date with
  `main`);
- require a pull request, with every review thread resolved;
- require the merge queue (merge method `MERGE`, grouping `ALLGREEN`);
- block deletion of `main`. This rule is missing since 2026-10-16. The owner restores
  it by hand; it is a bootstrap verification item below.

The pull-request and merge-queue rules reject direct pushes to `main` from every actor
that is not a bypass actor, including the workflow `GITHUB_TOKEN`. The bypass actors
(`OrganizationAdmin` and two `User` actors) are the owner's emergency access. A landing
through a bypass is an incident: record it with the runbook's evidence packet. Agents
never use it. Changing the ruleset is ASK class and done by the owner only.

The `production` environment requirements of ADR-0008 are unchanged: a custom
deployment branch policy allowing only `main`, `FLY_API_TOKEN` as an environment secret
only (no repository-level `FLY_API_TOKEN`), and the smoke identity and cohort secrets.

### Retired

- PR-less landing through `trunk-candidate/<sha>`. `scripts/submit_to_trunk.sh` stays
  in the repository but fails fast with a pointer to this ADR and pushes nothing.
- The temporary ruleset intervention for ASK, and the `restrict_updates` /
  deploy-key-sole-bypass requirement.
- The landing identity's landing power. The `verified-trunk-landing` deploy key and the
  `landing` environment secret `TRUNK_LANDING_SSH_KEY` still exist, but no ruleset lets
  the key update `main`. Whether to delete the key and the secret is an owner decision
  (a smaller credential surface), best taken together with the workflow cleanup below.

The `trunk-candidate/**` trigger in `ci.yml` and the candidate-only `land` steps in
`deploy-fly-production.yml` remain until a separate ASK workflow change removes them.
No candidate refs are pushed any more, so they do not run. The trunk delivery validator
pins them in the meantime.

### What ADR-0008 still governs

- Ship/Show/Ask classes and `scripts/classify_path_risk.py` (as narrowed by ADR-0030).
- Exact-SHA required CI with the no-skip `full-ci` aggregate; it now runs on the PR
  head and on the merge-group commit.
- Candidate-controlled CI holds no write permission, and no workflow holds
  `GITHUB_TOKEN` write.
- The default-branch release workflow (`workflow_run`): the landing proof for every
  consumed run, the deploy job's re-verification of `origin/main` before any Fly
  mutation, the smoke identity preflight, image capture, the authenticated production
  smoke and the verified rollback.
- Server-owned, default-OFF feature flags as exposure control, and the preserved
  ADR-0003 controls.

### Precisely superseded

In ADR-0008:

- **Delivery path**: the chain from `scripts/submit_to_trunk.sh` through
  `trunk-candidate/<sha>` to the `land` job's deploy-key fast-forward. Every landing is
  now a merge-queue push to `main`, which the paragraph's last sentence already
  covers.
- **Ship / Show / Ask**: "land via verified trunk, no PR" for SHIP and SHOW; the ASK
  temporary ruleset intervention and the statement that no PR merge can update `main`;
  the sentences saying `submit_to_trunk.sh` and the `land` job run the classifier as
  landing gates.
- **Landing guardrails**: item 2's ruleset requirement (`restrict_updates`, deploy key
  as the only bypass). Items 3–6 (candidate checks, the classifier re-run, the
  fast-forward, candidate-ref deletion) are inert. The paragraph on deploy-key pushes
  retriggering CI, and the audit trail built from the candidate ref, are replaced: the
  audit unit is the PR, its merge-group CI run, the `main` CI run and the release run.
- **Bootstrap (ASK)**: step 1's landing identity and steps 3–5's ruleset activation
  and verification items. The verification list below replaces them.
- **Consequences**: the bullets on PR-less landing, the candidate-ref audit unit, the
  ruleset (`restrict_updates`, sole deploy-key bypass, ASK intervention), and
  delivery-machinery changes landing through the intervention.
- **Verification**: `scripts/test_submit_to_trunk.py` now covers the retirement
  behaviour.

In ADR-0023: "verified-trunk path" and "verified-trunk landing" mean the merge-queue
landing above, and "one primary exact-SHA candidate CI evidence run" means the
merge-group CI run. The fast lane is otherwise unchanged.

In ADR-0030: "Preserves: ADR-0008 landing mechanics" now refers to this ADR's
mechanics, and `submit_to_trunk.sh` no longer accepts anything. The ASK path list is
unchanged.

### Bootstrap and verification (owner, by hand)

Agents do not change GitHub settings. The owner:

1. Restores the `deletion` rule in the `main` ruleset `Tests`.
2. Verifies with `gh api repos/maxk-lab/brain_buddy/rulesets/11196382` that the
   ruleset is active and has: `required_status_checks` with `Full CI` and
   `Docker Images` (strict); `pull_request` with review-thread resolution;
   `merge_queue` with `MERGE`/`ALLGREEN`; `deletion`; and only the intended bypass
   actors.
3. Verifies that the `production` environment still allows only `main` and holds
   `FLY_API_TOKEN` and the smoke secrets, and that no repository-level
   `FLY_API_TOKEN` exists.
4. Decides whether to delete the unused `verified-trunk-landing` deploy key and the
   `TRUNK_LANDING_SSH_KEY` secret.

### Known follow-ups (not changed here)

- A release run for a `main` push that a newer merge has already superseded fails at
  "Prove origin/main equals the tested revision" (for example runs 39015900101,
  39015104318 and 39011410547). Failing closed is correct, but it shows as a red run.
  Cancelling superseded runs instead (`concurrency`) is a separate ASK workflow change.
- Removing the `trunk-candidate/**` trigger and candidate-only steps from the
  workflows, and the matching requirements in `scripts/validate_trunk_delivery.py`, is
  a separate ASK change.
- ADR-0034's `trunk-candidate/**` bullet no longer applies because no candidates run.
  A merged PR's `main` push is verified in full, as ADR-0034 already states.

## Consequences

- One path for every class. Every change leaves a PR page, which is now the audit unit
  together with the merge-group CI run, the `main` CI run and the release run.
- The merge queue serializes landings and tests the exact commit that lands, so the
  exact-SHA guarantee holds. The reviewed PR head and the deployed SHA can differ by
  the merge with newer `main`; evidence names both.
- ASK enforcement at landing is weaker than ADR-0008 described: a recorded owner
  approval and the required checks, not a mechanical refusal. In practice that
  mechanical refusal stopped working on 2026-10-16, and the documentation no longer
  claims it.
- Each landing runs required CI on the PR head and on the merge group, and then
  push CI on `main`. ADR-0034's saving on the `main` push no longer applies.

## Verification

- `scripts/test_submit_to_trunk.py` asserts that the retired script exits non-zero,
  names this ADR and the merge-queue path, and pushes nothing, even for an otherwise
  valid candidate.
- The `main` ruleset and environment checks above are verified by the owner with
  `gh api`; they are not testable in-repo.
