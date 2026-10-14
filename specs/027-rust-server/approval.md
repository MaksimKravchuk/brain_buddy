# Approval record: 027 Rust server

## Planning review — founder acceptance

```json
{
  "planning_review": {
    "risk": "high",
    "status": "founder-accepted",
    "founder_acceptance": {
      "accepted_by": "Max (product owner)",
      "accepted_on": "2026-10-14",
      "expires_on": "2026-12-14",
      "artifacts_digest": "1b8de04f3c6de00dd9236580b8ed12c4e3f26677831c047647561ffcb45cf603",
      "base_sha": "3764dfc6",
      "rationale": "Both allowed review campaigns ran (cap two). Every product decision they raised (nine across both campaigns) was answered by the owner and recorded in spec.md Clarifications; every technical finding (38 in campaign 1, 39 in campaign 2) was fixed in the artifacts and verified closed by an independent read-only closure check in two passes, with the last residual contradictions corrected afterwards. The service has no real users, the old production data is erasable by owner decision, and every irreversible step remains a separately authorized ASK action, so the owner accepts closing the loop rather than running further campaigns that would re-litigate fixed text.",
      "compensating_measures": [
        "Independent read-only closure verification of all campaign-2 findings, two passes, with remaining contradictions fixed (plan.md resolution tables).",
        "Every irreversible or high-risk step — Managed Postgres/Tigris provisioning, CI and gate changes, the cutover, rollback and erase commits, and each destructive production pilot step — needs its own recorded owner approval at the moment it runs.",
        "Differential conformance: each ported capability must pass the same black-box tests against the frozen Python server and the Rust server before cutover.",
        "Rust critical invariants (owner isolation, auth and provider-token verification, idempotent receipts, job fencing, purge, control ledger) run as an observed mutation scope from Phase A and are promoted under ADR-0016 before the Python scope is retired.",
        "The acceptance auditor grades the delivered feature against every FR/SC and design id before the report to the owner."
      ],
      "campaign_history": [
        { "run_id": "027-plan-20261014-1", "status": "product-decision-required" },
        { "run_id": "027-plan-20261014-2", "status": "product-decision-required" }
      ]
    }
  }
}
```

## Residual risks the owner accepts

- The review panel was single-provider (Codex CLI default route, ADR-0024);
  agreement across lenses is not independent evidence.
- The plan is large (whole-server port); slice sizing and the conformance
  suite's breadth are settled in `/speckit-tasks`, not here.
- WebM/Opus duration probing in pure Rust is unproven until the voice slice
  (research R8).

## Expiry

If implementation has not started by 2026-12-14, or any reviewed artifact
changes materially before implementation, this acceptance lapses and the
review gate must be run again.

## Not authorized by this record

No production secret, database or bucket provisioning, CI or gate change,
deploy configuration change, cutover, rollback, data erase or destructive
production test. Each needs its own exact-SHA ASK approval.

## Addendum 2026-10-14 — tasks stage

The owner approved the 168-slice PR map in `tasks.md` and the dispositions of
the eight inventory rows recorded in spec.md Clarifications (tasks session).
These are owner decisions within the accepted scope, not material changes to
the reviewed plan; the acceptance above stays in force. Artifacts digest after
the tasks stage: `cd9385b4f3a7684cf368178044ebc9654e57f4e6e7b0335d37c858e15991c581`.

## Addendum 2026-10-14 — analyze remediation

`/speckit-analyze` (0 critical, 5 high) found gaps in the approved map; they
were fixed without changing scope: two tasks added (an ASK classifier slice for
the Rust GDPR paths, and the auth-migration-guard removal split into its own
ASK slice), missing dependency edges added, the removed CRT reconciliation
dropped, Control-schema ownership defined (data-model), and the post-rollback
state-file commit made explicit. The map is now 170 slices (30 ASK). Artifacts
digest: `9e80919242c4953077b6bd4eac34c45f6ac3ffb0ca594465798070149bb15245`.
