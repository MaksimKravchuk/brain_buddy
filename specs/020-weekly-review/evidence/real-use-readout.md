# Feature 020 real-use read-out

**Status: PENDING.** No week recorded yet. The window opens at the owner's first counted
review after the `weekly_review` flag is ON for them and runs 8 weeks.

Procedure (plan "Post-release acceptance"): once a week the owner runs
`python -m app.cli review-metrics --owner <id> --since <date>` in the production backend
container (read-only, aggregates only) and appends the printed numbers below. Numbers and
sample sizes only (see `README.md`). Weekly, because `navigator_usage` rows live 35 days.

Minimum samples, as the owner confirmed them on 2026-10-06:

| criterion | needs | else |
|---|---|---|
| SC-001 (a counted review in at least 3 of every 4 weeks) | all 8 weeks recorded | not read out |
| SC-003 (at least 70% "clear how to start the week: yes") | at least 6 answered reviews | not read out |
| SC-004 (median active time: quick at most 5 min, full at most 20 min) | at least 4 reviews per mode | "insufficient" for that mode |
| SC-005 | not read out while the navigator clients are deferred (tasks.md Notes) | |

## Weekly records

| week | `--since` | weeks with a counted review (of weeks so far) | SC-003 yes / answered | SC-004 quick: median min (n) | SC-004 full: median min (n) | parks returned / parks |
|---|---|---|---|---|---|---|
| 1 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

## 8-week figures

Computed from the weekly records once all 8 weeks exist.

| criterion | result | sample | verdict |
|---|---|---|---|
| SC-001 | PENDING | PENDING | PENDING |
| SC-003 | PENDING | PENDING | PENDING |
| SC-004 quick | PENDING | PENDING | PENDING |
| SC-004 full | PENDING | PENDING | PENDING |

## Park-safety cycle for the `BBWeeklyReviewLocal` decision

Filled in over one full cycle of the synced path for the owner (see `rollout-decisions.md`);
a non-zero count restarts the cycle after its fix.

| count | value |
|---|---|
| cycle start (flag reached SELECTED_USERS) / end | PENDING / PENDING |
| early parks (checked against `review_park_acks` rows and `review_auto_park` log lines) | PENDING |
| park-related sync issues (`autoParkTask`, a yielding `decideTask`, a park acknowledgement, any owner device) | PENDING |
| yield failures (a card decision made before the park instant that lost to the park) | PENDING |
| duplicate parks (more than one `review_park_acks` row per parked formulation) | PENDING |
