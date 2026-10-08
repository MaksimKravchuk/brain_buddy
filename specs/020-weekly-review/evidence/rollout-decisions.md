# Feature 020 rollout decisions

**Status: DRAFT, prepared from the defaults in `tasks.md` T169 on 2026-10-08. Awaiting the
owner's confirmation.** Nothing here is an approval until the owner fills in the
confirmation table at the end.

Owner decisions this draft builds on: the slice map (2026-10-06), the navigator scope cut
(2026-10-07), and the manual-check, gate and backlog decisions of 2026-10-08 (listed
under "Decisions of record").

Landing class: PR-14 is SHIP. Its paths are the coverage floors, `tasks.md` and the
evidence files. With the requirement-coverage gate not wired (T166, owner decision
2026-10-08), it no longer touches `Makefile` or the gate-integrity manifest.

## Flag stages

`weekly_review` is a runtime-managed flag in the ADR-0019 store (ADR-0027 §6), default OFF.
It moves OFF → SELECTED_USERS → ON at `/admin`. The change takes effect within about
fifteen seconds and needs no deploy. Exposure is not authorization: with the flag off,
writes that finish work a client already started (queued decisions, sessions,
acknowledgements) and consent revocation keep working. Setting it back to OFF is
therefore a safe rollback at every stage; no device's queued work is stranded.

| stage | what changes | entry criteria | rollback |
|---|---|---|---|
| 1. Backend, flag OFF | the review backend is deployed; every client shows the non-interactive "coming later" entry | #290 (PR-13) and #293 (PR-14) merged; CI green on the candidate | redeploy the previous image |
| 2. Client builds, flag OFF | web deploy, iOS TestFlight build, Mac build. The Mac keeps the non-interactive entry: its full review waits on a later feature | stage 1 live; T171 full verification green on the candidate | previous web image / previous TestFlight build |
| 3. SELECTED_USERS (owner only) | the owner gets Quick and Full review on web and iOS, auto-park, the markers and "While you were away" | the manual device checks pass (`manual-ios-increment1.md`, `manual-ios-increment3.md`, `macos-host-run.md`, run per `docs/runbooks/manual-device-tests-020-021.md`); any failure fixed in its own PR first | set the flag to OFF at `/admin` |
| 4. Wider (ON or a larger cohort) | everyone, or a named cohort | the 8-week read-out in `real-use-readout.md` meets its minimum samples (SC-001 all 8 weeks, SC-003 ≥ 6 answered reviews, SC-004 ≥ 4 reviews per mode), and the independent `/speckit-accept` verdict | set the flag back to SELECTED_USERS or OFF |

A missed read-out bar is reported to the owner as a product signal. It does not revert
the flag automatically. Widening the cohort is a separate, audited `/admin` action, never
a workflow or environment edit.

SC-005 (the navigator) is not read out, and the cloud navigator source stays out of this
rollout, because the navigator clients are deferred (`tasks.md` Notes).

## `BBWeeklyReviewLocal` (account-less iOS)

Decision: it stays `NO` in the Release configuration. It flips later, in its own change,
after one clean threshold cycle on the synced path.

"Clean" is measured over one full cycle for the owner: from the flag reaching
SELECTED_USERS, at least the owner's `threshold_days` + 7 days. Over that cycle,
`real-use-readout.md` must record:
- 0 early parks;
- 0 park-related sync issues;
- 0 yield failures;
- 0 duplicate parks.

Any non-zero count restarts the cycle after its fix. When the cycle ends, its dates and
these four counts are copied here.

| | value |
|---|---|
| cycle dates | PENDING |
| early parks / park-related sync issues / yield failures / duplicate parks | PENDING |

## Mutation scope (T170, deferred)

Promoting `app/modules/tasks/formulation.py` to `backend/mutation-enforced-scope.txt` is
pending. It needs two clean nightly mutation runs (deploy-and-ci rules), and the follow-up
feature takes it.

## Decisions of record

| date | decision |
|---|---|
| 2026-10-06 | Slice map and flag stages approved; minimum samples for the read-out confirmed. |
| 2026-10-07 | Navigator clients (iOS, web, downloadable model) and the cue/settings extras deferred to a follow-up feature; 020-FR-022, 020-FR-023 and 020-FR-049 accepted as deferred by scope. |
| 2026-10-08 | Manual device checks follow the merge: each slice merges to `main` once CI is green, with its test plan. The owner's agent runs the plans on the owner's devices, and a failure is fixed in its own PR. |
| 2026-10-08 | The 020 requirement-coverage gate is not wired (T166 stays open). The only allowed form is forbidden by a non-waivable gate-integrity invariant. |
| 2026-10-08 | Codex findings: P1s are fixed before merge; P2s are recorded for the follow-up feature. After 13 review rounds on #290, later web-review findings go to the backlog rather than narrowing PR-13's scope. |

## Owner confirmation

| | value |
|---|---|
| stages and entry criteria above confirmed (or edited) | PENDING |
| `BBWeeklyReviewLocal` decision confirmed | PENDING |
| confirmed by / date | PENDING |
