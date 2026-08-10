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

The gate is **built but not connected**, and its precondition is **not met**.
`scripts/mutation_gate.py` implements ADR-0004's requirements; nothing in CI
calls it.

ADR-0004 asks for two things before promotion: two consecutive successful
scheduled runs, and a recorded score of at least 95% for the unchanged
allow-list. The first is comfortably satisfied — twelve consecutive nightlies.
The second was asserted here in an earlier revision on the strength of the
first, which does not follow: a green nightly means the campaign completed, not
that it scored well, and the campaign is report-only precisely so a low score
cannot fail it.

Measured directly on 2026-08-10 over this exact list: **1280 killed, 70
survived of 1350 mutants — 94.81%**. Below the bar. Three more killed mutants
would clear it (1283/1350 = 95.04%).

So the enforced tier currently defines what is *eligible* to gate, not what
does. Connecting the gate is gated on killing those survivors, not on writing
more code.

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
scope and retained evidence. The observed-scope score is read from
`mutmut results --all` on a scheduled run; the enforced scope is exercised by
the pull-request gate. `backend/tests/test_task_owner_isolation.py` is the
regression suite that makes the task module's owner predicates mutable in the
first place, and its own kill-power was confirmed by hand-mutating both `_get`
and `delete_all_for_owner`.
