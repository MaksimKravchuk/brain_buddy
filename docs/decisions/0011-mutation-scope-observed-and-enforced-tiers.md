# ADR-0011: Separate the observed mutation scope from the enforced one

Date: 2026-08-10
Status: Accepted
Decision owner: BrainBuddy
Related: ADR-0004, ADR-0006, ADR-0008

## Context

ADR-0004 established a report-only mutation campaign over the deterministic
Reality Tree core and wrote down what promotion to a blocking gate requires:
two consecutive successful scheduled runs, complete artifacts, and a score of
at least 95% for an unchanged allow-list. The nightly workflow has now
completed successfully on twelve consecutive scheduled runs, so that
precondition is satisfied for the existing allow-list.

Two things have become clear since.

**The allow-list covers the canvas, not the product's risk.** The mutated
modules are the tree, version and relation services and their repositories.
Session authentication and the native GTD task module — the capability
baseline of ADR-0006, and the code that enforces per-owner data separation —
are outside it. `app/modules/tasks/repository.py` alone carries 129
owner-scoped predicates. A defect there is a cross-tenant data leak, and in
the case of `delete_all_for_owner`, an account purge that erases every
account rather than one.

**Line coverage was not evidence that those predicates were defended.** Every
cross-owner assertion lived at the HTTP layer, and ADR-0004 already records
that ASGI fixtures cannot run under mutmut's stack-statistics instrumentation.
The mutation-compatible task tests used a single owner, where a filtered and
an unfiltered query return the same rows. The predicates were fully covered
and entirely unverified; a hand-applied mutation removing the owner filter
passed all 62 non-ASGI task tests. Repository-level two-owner tests now close
that specific gap.

A calibration campaign over the two candidate modules, using only
mutation-compatible tests, produced:

- 879 mutants, 600 killed, **279 survived — a score of 68.3%**;
- 237 survivors in `app/modules/tasks/repository.py`, 42 in
  `app/services/auth_service.py`.

That is far below the 95% ADR-0004 requires. The naive options are both bad:
promoting the wider scope would red-line every pull request that touches the
task module, and keeping the scope narrow would leave the product's highest-
risk code permanently unmeasured.

## Decision

Mutation scope is split into two tiers with different obligations.

**Observed scope** — mutated by the nightly report-only campaign:

- the ADR-0004 Reality Tree modules;
- `app/modules/tasks/repository.py`;
- `app/services/auth_service.py`.

**Enforced scope** — the tier that is allowed to gate pull requests:

- the ADR-0004 Reality Tree modules only, for now.

The gate is **built and connected**. `scripts/mutation_gate.py` implements
ADR-0004's requirements and the `mutation-gate` job in
`.github/workflows/ci.yml` calls it on every pull request and every push to the
landing path.

ADR-0004 asks for two things before promotion: two consecutive successful
scheduled runs with complete retained artifacts, and a recorded score of at
least 95% for the unchanged allow-list. An earlier revision of this ADR
asserted the second on the strength of the first, which does not follow: a
green nightly means the campaign completed, not that it scored well, and the
campaign is report-only precisely so a low score cannot fail it. Measured
directly on 2026-08-10 over this exact list: **1279 killed, 70 survived, 1
timeout of 1350 mutants — 94.81%**. Below the bar.

Those 70 survivors have since been worked down. Re-measured over the same
unchanged list with `make mutation-gate-backend`: **1319 killed, 28 survived of
1347 mutants — 97.92%**, which clears the bar. They resolved as 39 killed by
focused regression tests in `backend/tests/test_mutation_survivor_exact.py`, 3
that stopped existing when the unreachable `or [...]` fallback in
`TreeService.generate_ai_feedback` was deleted, and 28 classified as
non-behavioral. The classification is itemised per mutant in
`backend/mutation-enforced-scope.txt`; every entry is a mutation whose
observable output is identical to the original — redundant explicit defaults,
falsy sentinels the callee tests for truthiness, a deep copy over fields that
are all strings — and not a widened exclusion, which ADR-0004 forbids.

The other half of the precondition — two consecutive successful scheduled runs
retaining complete artifacts — is satisfied by the nightly's run history; the
score that revision history could not establish is the one measured above. On
that evidence the gate was promoted, and the enforced tier now defines what
*does* gate rather than what is merely eligible to.

Two shapes of that promotion are worth recording, because both were choices
rather than defaults.

**The landing path measures the whole list, not a diff.** SHIP/SHOW changes
land by pushing `trunk-candidate/**` with no pull request at all (ADR-0008), so
that push is the only gate those changes ever meet. Scoping it to a diff would
leave the majority of delivery ungated. Pull requests keep the narrow scope
ADR-0004 asked for.

**The base revision is measured in its own CI job.** `pip install -e` points at
exactly one checkout, so measuring both revisions from a single job risks
running the base's tests against the head's code and reporting a comparison
that is silently meaningless — the worst failure available to a gate, because
it still shows green.

**Measuring and judging are separate jobs, and that is what makes the
comparison affordable.** The first shape had the gate both measure the head and
render the verdict, which forced `needs: mutation-base` on it so it could read
the base artifact — and since `needs` gates when a job *starts*, the two
campaigns ran strictly in sequence. A pull request paid two campaigns'
wall-clock, 623 mutants twice at about seven minutes each.

Splitting the verdict out fixes it: `mutation-base` and `mutation-head` depend
only on the scope calculation, so they overlap, and `mutation-gate` waits for
both to read two artifacts and decide, which takes seconds. A pull request now
pays one campaign's wall-clock. `validate_ci_artifacts.py` rejects a workflow
that reintroduces a dependency between the two measurements, because the
serialised shape looks perfectly reasonable in a diff.

The landing path never had this cost: a push has no base revision to measure,
so `mutation-base` skips every step.

A module enters the observed scope as soon as it has mutation-compatible tests
worth measuring. It moves to the enforced scope only once it independently
meets the ADR-0004 bar: at least 95% on an unchanged list across two
consecutive successful scheduled runs. The two tiers are configured
separately, so a module under calibration cannot block delivery and a promoted
module cannot silently regress.

Survivors in the observed scope are worked down incrementally, in changes
small enough to review, rather than in one campaign-wide sweep. Each such
change records the score it moved from and to. Broad exclusions remain an
unacceptable remedy, as under ADR-0004: a survivor is either killed by a
focused test or documented as a non-behavioral mutation.

`app/repositories/session.py` and `app/repositories/user.py` stay out of both
tiers. Under mutation-compatible tests they sit at 65% and 62% line coverage
respectively, so a campaign over them would mutate a minority of each file and
report a score about the wrong subset. They join the observed scope when their
non-ASGI coverage makes the measurement meaningful.

## Consequences

- The product's highest-risk modules become measurable immediately, without
  making delivery contingent on a number that is currently 68.3%.
- The enforced scope keeps the property ADR-0004 wanted from it: a score that
  is trustworthy because it was calibrated before it could block anything.
- The published mutation score is per-tier. A single repository-wide number
  would average a calibrated scope with an uncalibrated one and mean nothing.
- 279 survivors are now an explicit, itemised backlog rather than an unknown.
  Each one names a mutation the tests do not notice, which is a more
  actionable unit of work than a coverage percentage.
- Adding a module to the observed scope lengthens the nightly campaign. The
  selected tests run in roughly 7 seconds for the task module and 3 for auth,
  comparable to the existing scope, so this is affordable.

## Alternatives considered

### Promote the wider scope to a blocking gate now

Rejected. At 68.3% this fails on contact, and the pressure it creates is to
weaken the allow-list rather than to write assertions.

### Keep the allow-list unchanged until the new modules reach 95%

Rejected. Nothing would measure progress toward that threshold, so the
threshold would never be approached. Measuring first is the point.

### Raise line-coverage requirements instead

Rejected, and the reason is the substance of this ADR. The predicates in
question were already at 89% line coverage under the selected tests while
scoring 68.3% under mutation. Coverage records that a line executed; only
mutation records that breaking it would be noticed.

## Verification

`python3 scripts/validate_ci_artifacts.py mutation-workflow` continues to
check the nightly workflow's scheduling, report-only event policy, explicit
scope and retained evidence, and now also that it reports the enforced tier.

That last requirement closes a gap this ADR opened. Splitting the tiers left
the scheduled campaign measuring only the observed scope, so the number
ADR-0004 wants scheduled evidence for — the enforced one — had no producer at
all, and its promotion precondition could not have been satisfied by waiting.
The nightly now derives it with `scripts/mutation_gate.py summarize-mutmut`,
filtering the per-mutant verdicts it already writes down to the enforced
modules. The observed scope is a superset, so this costs no extra runtime and
gives the gating scope ongoing drift detection rather than a one-off number.

The enforced score is also reproducible on demand with
`make mutation-gate-backend`, which narrows `only_mutate` to this list for one
run and asserts the 95% bar with `scripts/mutation_gate.py check` — the same
validator the pull-request gate calls.
`backend/tests/test_task_owner_isolation.py` is the
regression suite that makes the task module's owner predicates mutable in the
first place, and its own kill-power was confirmed by hand-mutating both `_get`
and `delete_all_for_owner`.
