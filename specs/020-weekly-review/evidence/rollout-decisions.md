# Feature 020 rollout decisions

Owner decisions (confirmed with the slice map on 2026-10-06; navigator scope cut on
2026-10-07). Landing PR-14 is ASK class (`Makefile` and the gate-integrity manifest change).

**ASK approval for the PR-14 landing: PENDING.** To be recorded by the owner (who, when,
which SHA) before the landing. Nothing here is an approval.

## Flag stages

1. Backend with `weekly_review` OFF.
2. iOS and web builds with the review surfaces (the flag still OFF).
3. SELECTED_USERS (the owner only).
4. Wider stages only after the 8-week read-out in `real-use-readout.md`, and only after
   the independent `/speckit-accept` verdict. A missed bar is reported to the owner as a
   product signal and does not revert the flag automatically.

The cloud navigator source stays out of this rollout (clients deferred, tasks.md Notes).

## `BBWeeklyReviewLocal` (account-less iOS)

Decision: it stays `NO` in the Release configuration. It flips later, in its own change,
after one clean threshold cycle on the synced path. "Clean" is measured: over one full
cycle for the owner (from the flag reaching SELECTED_USERS, at least the owner's
`threshold_days` + 7 days), `real-use-readout.md` records 0 early parks, 0 park-related
sync issues, 0 yield failures and 0 duplicate parks. The cycle's dates and these four
counts are copied here when it ends.

| | value |
|---|---|
| cycle dates | PENDING |
| early parks / park-related sync issues / yield failures / duplicate parks | PENDING |

## Mutation scope (T170, deferred)

Promoting `app/modules/tasks/formulation.py` to `backend/mutation-enforced-scope.txt` is
pending: it needs two clean nightly mutation runs (deploy-and-ci rules), and the follow-up
feature takes it.
