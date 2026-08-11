# Review history — 006-mobile-task-classification

The campaign artifacts live under `.specify/workflows/runs/`, which is
gitignored: run state, not source. That is right for a machine that keeps
running and wrong for a record anyone needs later, so the durable facts are
copied here. This file is the audit trail; the run directory is the scratch it
was derived from.

## Campaigns

| run id | verdict | lenses | product decisions | findings |
|---|---|---|---|---|
| `006-mobile-task-classification-c1` | `product-decision-required` | 6/6 | 4 | blocking across privacy, architecture, requirements, testability, adversarial |
| `006-mobile-task-classification-c2` | `technical-changes-required` | 6/6 | **0** | 49 — 13 blocking, 32 important, 4 advisory |

The cap is two campaigns (ADR-0011). Both are spent.

**Provenance, stated rather than implied.** `codex` is not installed on the
machine these ran on, and the three Claude lenses run as in-session subagents by
design, so all six reviews were hand-placed rather than harness-stamped. The
summary records every lens as `oracle_unknown` and the aggregator prints that
their independence is *unmeasured, not verified*. Six lenses on one model is
weaker corroboration than six lenses. No `oracle` block was fabricated to make
that look better — the script's own guard says a model cannot author its own
provenance, and forging it would have made this gate decorative.

## What campaign 1 raised, and how it closed

Four product decisions went to the human, who declined to answer twice and
instructed that defaults be taken instead. They are recorded in `spec.md` under
"Session 2026-08-11 (b)" as **agent-proposed defaults adopted under an explicit
instruction to proceed** — not elicited requirements, and labelled so no later
reader mistakes them for such: 30-day retention, involuntary session end
retains the queue, coalescing keeps the original value, partial-failure states
removed as unreachable.

## What campaign 2 found

Zero product decisions — the result worth keeping. Every lens was told the
human would take a stated default, and every lens filed findings with defaults
instead of questions. Nothing in this feature still needs the founder.

The 13 blocking findings, all fixed before acceptance:

1. **FR-017's idempotency key was specified in a way the backend makes
   unsendable.** Found independently by three lenses and confirmed against
   `backend/app/modules/tasks/service.py:1110`. "Coalescing keeps the existing
   key" produced an entry that 409s forever and ages out silently. This one was
   introduced by the previous round's fix, and `mobile/src/utils/ids.ts` already
   documented the correct convention.
2. **The rollout flag is read from `/auth/me`**, so an offline cold start
   rendered the flag-OFF screen — the feature was unavailable on exactly the
   path it exists for. Two other offline cold-start dependencies had been fixed
   the round before; this was the third, and it gates the other two.
3. **`sending` stranded on app kill** — persisted with no rehydration rule, and
   invariant 5 makes every later drain skip it. ADR-0002 already solves this for
   the voice queue with lease reconciliation.
4. **FR-018 deleted unseen work on an unvalidated device clock** with no
   confirmation, in both directions (forward jump deletes everything; a
   timestamp written while ahead never expires).
5. **Read-scoped expiry never runs on an abandoned key**, so a different account
   signing in left the previous one's queue and project/Tag names on the device
   indefinitely. Identity-in-the-key closes disclosure; it cannot delete.
6. **The project/Tag name cache was unmodelled** while three artifacts asserted
   the queue was the only new store — and it holds names the person wrote, where
   the queue holds only ids.
7. **Edit-while-sending was undefined**, and every reading of the existing
   invariants lost the edit or poisoned the entry.
8. **FR-019 had no testable home** — its logic sat in a React provider the plan
   itself says cannot be tested.
9. **SC-008 had no evidence at any level.**
10. **Two User Story 3 scenarios still demanded the per-change marker** the
    human personally reversed at design sign-off.
11–13. Owner-scoping via an unescaped concatenated key; the M-04 mockup never
    updated for FR-010; partial-failure citations left stale in `plan.md`.

## Founder acceptance

Recorded 2026-08-11 by **maksim.v.kravchuk@gmail.com**, expiring
**2026-11-09**.

The loop converged on evidence but not on a verdict. The cap forbids a third
campaign, so no automated verdict can now rise above
`technical-changes-required` however complete the fixes are. Risk derived
`high` (the spec names auth and config surfaces), and that class requires a
named human to accept the residual.

**The residual risk, stated plainly:** the fixes to campaign 2's findings have
not themselves been reviewed by a fresh panel, and the panel that found them was
fully correlated with unrecorded provenance.

**Compensating measures:** all 13 blocking findings fixed with per-finding
rationale in the PR #148 commit messages; the idempotency defect verified
against backend source rather than accepted on assertion; `plan.md` now traces
all 30 requirements where it named 7, so `check_requirement_coverage.py` can
grade the feature at all; `quickstart.md` gained manual steps for every
non-automatable path; `docs/data-retention.md` gained rows for both device
stores, closing the gap where FR-018 cited a document that did not cover the
store it bounded; and the acceptance expires rather than persisting silently.

**The expiry is not decoration.** If this has not landed and been accepted by
2026-11-09, the gate closes and a fresh campaign is required.

## Implementation outcome

Built 2026-08-11 by six parallel agents on disjoint file sets, plus an
integration pass and a later round of render tests. **1146 mobile tests, 1069
backend tests, 30/30 requirements traced.** Typecheck, lint, Metro bundle and
the mobile integration suite all green; mobile coverage 96.68 statements /
92.27 branches / 97.59 functions / 96.62 lines against a 94/88/95/94 floor.

**A premise this record asserted, and how it stopped being true.** Every lane
was briefed that `mobile/` cannot render a component in a test, so component
evidence was typecheck and a bundle and nothing else. That was true of the
base this work started from. While it was in flight, main gained a fake-backend
harness that mounts real screens, a 94% coverage floor and every eslint rule.
The gap this file once described as an unavoidable limit was, by the time the
work landed, simply unfinished — and closing it found three more defects that
the pure-module tests could not see, including a green test asserting the exact
behaviour that was broken.

### Every defect found during implementation was at a seam

Three, and all three lived in a file no single lane owned:

1. **The idempotency 409 loop, rebuilt from two correct halves.**
   `conflictDecision` distinguished the two things the backend returns 409 for
   and carried `reuseIdempotencyKey: false`; `applyRejected` had no parameter
   to honour it. This is the same defect campaign 2 caught in the requirement
   text — the gate stopped it in prose and it came back in code.
2. **`AuthGate` did not know about `signed-in-offline`.** The session lane
   added the status for FR-019 and correctly left a file it did not own alone.
   One equality check stranded an authenticated offline person on the sign-in
   screen with a full queue behind it — the exact path SC-009 exists for.
3. **The conflict sheet could not tell why an entry was parked.** The sheets
   lane built a discard-only sheet for a target deleted elsewhere; the queue
   recorded only *that* an entry was `conflicted`. Every 404 would have offered
   "Keep mine, replace theirs" for a task that no longer exists, and the sheet
   built for that case was unreachable.

Disjoint file ownership is what makes parallel agents safe from each other and
is exactly what makes them blind to what lies between them. **The integration
pass is not cleanup; it is where this bug class exclusively lives.**

### Things the lanes found that the spec had wrong

- **The SC-007 key derivation did not work.** Campaign 2 said "escape
  components separately"; `encodeURIComponent` does not escape `.`, and `.` was
  the separator, so `("a.b","c")` and `("a","b.c")` collided. `serverUrl` is a
  URL and always contains dots. Because the design rejects a filter, that
  collision *is* cross-account disclosure. Found independently by two lanes.
- **`observedAt` did not exist**, so M-04 could not honestly date the value it
  shows. The sheets lane omitted the age rather than back-filling it from
  `firstQueuedAt`, which would have claimed the phone's knowledge was minutes
  old when it may be weeks old — the precise falsehood the labelled row exists
  to prevent.
- **A repo-wide gate bug**: `mobile/integration` was listed as a test tree and
  then filtered back out by filename hints, so every integration assertion in
  the repository was invisible to `check_requirement_coverage.py`.
- **`target-missing` had no design state**, only a spec edge case.
- **T064's premise was wrong** — `sign-in.tsx` has no `signOut` call.

### Not done, and why

- **T052, T069 — the manual quickstart runs need a physical iPhone.** Every
  criterion whose only honest evidence is a person looking at the screen
  (SC-001, SC-006, and the rendering halves of FR-007 and FR-012) is therefore
  ungraded. `/speckit-accept` must not be run until they are.
- **Component-layer evidence was weaker, and then was not.** While the lanes
  were building, this said `mobile/` installs no React renderer, so `.tsx`
  files had typecheck and a bundle and nothing else — and the lanes pushed
  every decision they could into pure modules (`pickerState`, `sheetState`,
  `taskScreenState`, `drainStep`) to shrink that gap, two of them checking the
  Hermes bundle by byte-search rather than trusting a passing export.

  That paragraph is kept because the caution was real at the time and shaped
  the architecture. It is no longer the state of the work: the components are
  now covered by tests that mount them, and closing that gap is what found the
  picker error state nobody could reach, the offline detach that could not be
  undone, and a green test asserting the exact behaviour that was broken. The
  same expired premise appeared in four places in these artifacts and was
  corrected in each — see the "Implementation outcome" note above.
