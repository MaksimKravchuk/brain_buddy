# Review record: feature 014 — A2A relay wire contract

This is the committed record of the portable spec review gate (ADR-0011,
ADR-0012, ADR-0014) for feature 014. The machine artifacts live under the
gitignored `.specify/workflows/runs/014-campaign-1/` and
`.specify/workflows/runs/014-campaign-2/`; this file carries what a reader of
the repository needs: every campaign with its true status, every product
decision with the product owner's answer, and the founder-acceptance record
that closed the gate.

**Gate verdict**: `founder-accepted` (never rendered as `approved`).
**Risk class**: `high` (derived by the classifier from the ASK-class surfaces
the plan names: auth, migration, secrets, deploy).
**Panel**: six lenses — requirements-consistency and testability-evidence ran
degraded on `claude/sonnet` because the `codex` CLI is unavailable in this
environment (ADR-0014); architecture-consistency on `claude/opus`;
privacy-consent-security and ux-accessibility-mobile on `claude/sonnet` and
`claude/opus`; adversarial-high-risk on `claude/fable`. Every lens ran on one
provider, so the panel is single-provider and correlated.

## Campaigns

| Run id | Artifacts digest | Status | Findings | Notes |
|---|---|---|---|---|
| `014-campaign-1` | `82b4a8975ff88e5b…` | `product-decision-required` | 4 blocking, 21 important, 10 advisory (five lenses) plus the adversarial lens: 9 important, 5 advisory, 1 product decision | The adversarial lens timed out at 900 s and was rerun twice on unchanged artifacts: the first rerun was rejected by the validator (verdict / product-decision mismatch, prompt rule added in `2d41b181`), the second completed. Every blocking and important finding was fixed before campaign 2 (`73f9934`, `f58b3a4`, `5c4221e`). |
| `014-campaign-2` | `3a57b74194ea5293…` | `technical-changes-required` | 1 blocking, 20 important, 16 advisory (six lenses), 0 product decisions | The adversarial lens timed out again at 900 s; the runner cap was raised to 1800 s (`2055759`) and the lens completed in 13 minutes on unchanged artifacts. Every finding, advisory ones included, was fixed after the campaign (`4123025`, `0eb032c`, `772a66f`, `84b8dd8`, `ef453e8`). |

ADR-0011 rule 7 caps the loop at two campaigns; after campaign 2 the options
are to land the fixes, defer residue into explicit open lanes, or close by
founder acceptance with the full record. All findings were landed and none
were deferred, and the product owner closed the gate by founder acceptance on
2026-09-04.

## Product decisions answered by the product owner

Recorded in `spec.md` → Clarifications (session 2026-09-03) and in
`design.md`:

1. **Card metadata retention** (privacy, campaign 1): the live connection's
   discovered card summary and fingerprint are connection configuration
   retained for the connection's lifetime and erased on disconnect together
   with the credential; only audit rows that name the card follow the 90-day
   bound. FR-016 amended.
2. **Agent-reported result links** (ux, campaign 1): inert text the user can
   copy, exactly as the shipped 007 relay renders them; the 007 helper
   `interactive_result_link` stays unchanged. AC-016, D-03-S11 and M-03-S10
   amended.

Design amendments after both campaigns (task succession states, Check again,
Queued variant, inert links, M-01 sheet order, focus rules, rate-limited
connection-test states D-01-S25 / M-01-S22, restarted-before-send variant,
disconnect copy, mobile accessibility parity) were re-acknowledged by the
product owner on 2026-09-04; `design.md` records both amendment tables.

## Founder acceptance record

Written to `.specify/workflows/runs/014-campaign-2/founder-acceptance.json`
and embedded as `founder_acceptance` in that run's
`planning-review-summary.json` (the automated summary is preserved beside it
as `planning-review-summary.automated.json`).

```json
{
  "accepted_by": "Max (maksim.v.kravchuk@gmail.com), product owner and founder",
  "accepted_on": "2026-09-04",
  "expires_on": "2026-12-31",
  "rationale": "Feature 014 reached the ADR-0011 hard cap of two review campaigns without an automated approved verdict. Campaign 014-campaign-1 (six lenses; the adversarial lens rerun after a 900 s timeout) returned product-decision-required with four blocking and twenty-one important findings; both product decisions were answered by the product owner on 2026-09-04 and every blocking and important finding was fixed in the planning artifacts before campaign 2. Campaign 014-campaign-2 (six lenses; the adversarial lens rerun after a second timeout under a 1800 s cap) returned technical-changes-required with one blocking, twenty important and sixteen advisory findings and no product decision. Every campaign-2 finding, advisory ones included, was fixed in the artifacts after the campaign, so no reviewed defect is carried into implementation. The residual risk accepted is that the fixed artifacts were not re-reviewed by a third automated campaign, which ADR-0011 forbids, and that two lenses ran degraded on claude/sonnet because the codex CLI is unavailable in this environment, so the panel is a single-provider panel.",
  "compensating_measures": [
    "Every blocking, important and advisory finding from both campaigns is fixed in the planning artifacts and traceable through the campaign summaries kept under .specify/workflows/runs/014-campaign-1 and .specify/workflows/runs/014-campaign-2, with the fix commits recorded in specs/014-a2a-relay-wire-contract/review.md.",
    "The feature ships behind the external_agent_relay flag, OFF by default, with the release-runbook gate that forbids turning it ON for any user before the refreshed iOS build is the only distributed build.",
    "The acceptance-auditor stage must trace every FR, SC and AC of spec.md to a named executable test before the feature is reported, and the delivery-verifier chain must be green on the implementation worktree.",
    "The attended Hermes live run in docs/external-agent-relay-release.md remains a mandatory, human-run release step before rollout; it is never run in CI or by a subagent.",
    "The ASK review of PR #192 by the repository owner remains the landing gate; this acceptance authorises implementation, not landing."
  ],
  "campaign_history": [
    {"run_id": "014-campaign-1", "status": "product-decision-required"},
    {"run_id": "014-campaign-2", "status": "technical-changes-required"}
  ]
}
```

The acceptance was given by the product owner in the orchestrating session
on 2026-09-04 in answer to an explicit question that named the cap, the
counts, the fixes and the compensating measures; it was not asserted by an
agent. It expires on 2026-12-31: after that date it no longer closes the
review and a fresh decision is required.
