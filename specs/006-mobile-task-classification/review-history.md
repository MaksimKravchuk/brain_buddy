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

## Post-merge review, 2026-08-13

The five-PR stack merged, and adversarial review of the merged diff found nine
further defects. They are recorded here because the acceptance record above is
what a later reader will consult, and it would otherwise close on the state of
the code the day it landed rather than the state it is in.

Eight are the kind the gate is not shaped to catch — they live in wiring,
serialisation order and process lifetime, not in requirements:

- **A drain pass kept sending after its identity was replaced.** `owns()` scoped
  what a pass *read and wrote on the device* and nothing scoped what it *sent*;
  the api client resolves its base URL and cookie at call time, so the next
  entry in the loop went out as account A's write under account B's session —
  SC-007 over the wire, which is where it matters most.
- **A queued device write could be redirected by a later identity.** Writes are
  serialised and each reads the live queue when its turn comes, which is what
  stops two writers clobbering each other; but the identity-change effect
  empties that ref, so a write for A waiting behind another called
  `saveQueue(A, [])` and deleted the unsent work FR-011 keeps *specifically*
  through an involuntary end.
- **Clearing an identity's stores was not a barrier.** A stale drain pass and
  the fire-and-forget picker-cache write both outlive the clear and could put
  the queue, or the project and Tag names the person wrote, back on a device
  that had just forgotten how to name them.
- **A different account signing in deleted only the previous account's flag
  record**, leaving its queue and picker cache to a sweep that runs only when
  the *new* account has the rollout flag on. A retention rule conditional on an
  unrelated feature flag is not a retention rule.
- **The per-pass safety limit stranded the rest of the queue.** 25 bounds a
  pass, not a triage session, and the pass holds the drain lock while it runs.
- **The conflict sheet dated the phone's value from the account-wide sync
  clock**, which advances on any successful send for any task — so a task last
  read three weeks ago was labelled "as of just now".
- **The dismiss-once expiry notice reappeared on every task screen**, because
  the latch was consulted only when the identity key changed, and on an ordinary
  remount it has not.
- **Sign-in compared the server URL raw** where Settings compares it normalized,
  so a trailing slash took the discard path for a save that changed nothing.

Each carries a test that was mutation-checked: with the production change
reverted the new test fails, and with it restored it passes.

Review of those eight fixes then found three more, and the pattern in all three
is the same one: **a guard placed before an `await` is not a guard.**

- The pass checked ownership at the head of each iteration, then wrote the
  `sending` marker — an await — and issued its first request. An identity
  change landing inside that write slipped straight through; the extra check
  added for the rejection path only ever covered the *second* request of a
  step. Every request the pass issues is now preceded by a check with no await
  between the two.
- The cache writer checked the fence, then read the existing cache — an await —
  and wrote the merge. A sign-out inside the read was followed by a write that
  put the names back.
- The store fence was a boolean tombstone lifted when the same identity signed
  in again. The comment above it *acknowledged* that gap and argued past it on
  the grounds that an account resurrecting its own work is not a disclosure.
  That reasoning was sound and incomplete: the other half is that the stale
  pass's now-empty result deletes work the **new** session queued in the
  meantime, which is plain data loss and has nothing to do with disclosure. A
  documented exception is not a safe one — writing the gap down made it feel
  handled. Replaced with a generation counter, which answers "forgotten since
  *I* started" rather than "forgotten at all", and needs no lifting step.

The ninth is different in kind, and is the one worth carrying forward.

### FR-008 was violated by the shipped code

Past the 24 h replay window the drain re-reads the task before retrying. That
read has three possible answers; the code branched on two. Anything that was
not "the server already holds what I intended" was re-presented against the
revision just observed — which rebases `observedRevision`, so the send that
follows **cannot** 409, and the 409 is the only thing that ever opens M-04. An
entry attempted once, left more than 24 h (FR-018 permits 30 days), on a task
somebody else had reclassified meanwhile, therefore overwrote their work in
silence.

That is FR-008 ("MUST ask whether their change wins or is abandoned; MUST NOT
decide for them") and SC-005 ("zero classifications are overwritten or
discarded silently"), both, on the one path where the device already had in
hand every piece of evidence needed to ask.

What makes it worth recording rather than just fixing:

- **The doc comment above the function reasoned about "the conflict prompt"**
  while the code guaranteed it could not fire. Prose and behaviour disagreed and
  nothing compared them.
- **A passing test asserted the defect.** `drain.test.ts` "then sends it,
  carrying the revision the re-read observed" seeded eight revisions of somebody
  else's work and asserted the overwrite, with an approving comment. Test
  coverage was not the missing control; the test *was* the bug, written down.
- **Invariant 10 and T068 both described the two-branch rule**, so the artifact
  chain was internally consistent end to end. Six lenses, a requirement-coverage
  gate and a founder acceptance all passed a feature whose specification of this
  path was itself incomplete. Consistency checking cannot find a case nobody
  enumerated.
- **It survived founder acceptance**, and was found only by review of the merged
  diff. The lesson is not that the gate should have caught it — it is that "the
  artifacts agree with each other" and "the artifacts are complete" are
  different properties, and the campaign only ever measured the first.

Fixed by giving the re-read its missing third branch: park the entry
`conflicted` with the re-read's revision and values, `originalValue`
deliberately unrefreshed. The comparison is scoped to the fields the change
carries, so a title edit — or a Tag edit under a project-only change — is still
a plain resend and raises no prompt. `data-model.md` invariant 10 and T068 now
state all three branches; no requirement was weakened to fit the code. The fix
is mutation-checked: reverted, the new tests fail; restored, they pass.

### The evidence for all of this was being thrown away

One more, found in the same pass and not about the feature's code at all. The
Allure aggregation predicate named three uploading lanes and there are four:
`e2e` is never path filtered and uploads `playwright-allure-results` under a
bare `always()`. The three stack jobs run-but-skip-their-steps rather than
skipping — ADR-0008 counts a skipped required job as a failure — so `e2e` is
never skipped either. A docs-only pull request therefore ran the whole Compose
suite and then discarded its results: no aggregate report, no pull request
link, on precisely the branches a spec-driven feature is mostly made of, which
is most of this feature's own history. The validator now requires the fourth
term, key-anchored like the other three so it cannot be re-broken by binding
the key to a constant.

SC-001, SC-006 and the rendering halves of FR-007 and FR-012 remain ungraded —
T052 and T069 still need a physical iPhone.
