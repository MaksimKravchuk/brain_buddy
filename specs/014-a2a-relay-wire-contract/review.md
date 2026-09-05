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

## Post-acceptance amendments (analyze stage, 2026-09-04)

`/speckit-analyze` ran on the accepted artifacts after `tasks.md` was written
(0 CRITICAL, 2 HIGH, 17 MEDIUM, 15 LOW) and its remediations were applied on
2026-09-04. They are consistency fixes — the spec's MUST and AC text was
brought into line with what the contracts, data model, design and tasks
already said, or given the one value those artifacts had left open — and no
requirement, success criterion, acceptance scenario, state or task changed
its number or meaning. The founder acceptance above stands unchanged. Every
change to spec MUST/AC text, by finding id:

- **I1 + U2** — FR-006, AC-030 and AC-036 now carry the contract's complete
  resend-refusal reason list with one reason per condition
  (`connection_not_ready`, `agent_card_changed`, `run_content_expired`,
  `reauthentication_required`, `connection_disconnected`, `run_terminal`,
  `agent_task_missing`) plus the new `rollout_disabled`, returned after the
  lookup ran; `contracts/api-deltas.md`, `data-model.md` §2 and tasks
  T055/T068 carry the same eight.
- **U1** — FR-004 and FR-006 (with AC-030, AC-032) fix when
  `first_dispatch_at` is stamped: at exchange start, never at reservation, so
  a queued hand-off that never left keeps the reauthentication trigger
  unspent; `data-model.md` §1/§2 and tasks T053/T054/T065/T066/T067 say the
  same.
- **I4** — FR-008 and SC-003 ratify the push route's per-run 429 for known,
  dispatched, non-terminal runs as the one deliberate existence signal and
  keep every rejection class byte-identical, as `contracts/push-callback.md`
  and the plan already stated.
- **I7** — FR-002 lists "private destination" (007 FR-004) as the sixth
  connection-test outcome, matching the plan, SC-009 and T034.
- **D4** — FR-016 places the run's observation event rows in the 90-day tier
  and reply drafts in the 30-day content tier, so SC-007 tests an FR clause.
- **A1** — FR-002 and AC-037 name the rate-limit trigger as HTTP 429 or an
  agent-specific code from the allowlist (Hermes `-32051`), no longer "the
  protocol's rate-limit error", which A2A 1.0 does not define.
- **A3** — FR-007 separates the default (300 s) from the floor (MUST NOT be
  configured below 300 s); `data-model.md` §9 bounds `reply_window_seconds`
  accordingly.
- **I6** — FR-006 derives the message ID from the reserved run ID, which the
  idempotency key pins (`{run_id}:start`), as the contracts already did.
- **I8** — the header reads `Status: Accepted (founder-accepted 2026-09-04)`.
- **U4** — FR-005 (with AC-032 and the rate-limit edge case) states when
  **Try this hand-off again** reuses the reserved run, message ID and
  idempotency key (only while the rebuilt manifest token equals the frozen
  one) and that otherwise a new run is reserved and the old one stays
  **Not sent**.
- **U6** — FR-002 and AC-037 carry the null-retry-after copy ("Test again
  shortly."), closing CHK051 in `checklists/a2a-wire.md`.

The remaining findings (A2, A4, U3, U5, C1, C2, G1–G5, I2, I3, I5, I9–I13)
touched only the plan, design, data model, contracts, checklist and tasks.
D1–D3 (duplication) were left as they are: the restated text is consistent.


## Implementation deviations (recorded by the implementer)

The planning artifacts were reviewed and accepted before any code existed. Six
places where the implementation departed from them are recorded here, with the
reason, so the reviewers grade what was built rather than what was drawn. Where
a contract stated the superseded shape, the contract has been corrected in the
same commit as this entry — a deviation that lives only in a review note is a
document that will be trusted and be wrong.

**(a) The per-run push token is derived, not random.**
`contracts/push-callback.md` requires the *same* token to go out again with
every reply, so a successor task keeps push acceleration, while `data-model.md`
§7 allows a run to store only `push_token_fingerprint`. Those two are
satisfiable together only if the token is recomputable, so `derive_push_token`
computes it as a keyed HMAC over the run id under the relay key ring rather
than drawing it from `secrets.token_urlsafe`. Storing the plaintext to achieve
the same thing would put a live route credential in the database; minting a
fresh one per reply would silently invalidate a push the agent is already
preparing. The value is indistinguishable from random without the key and
unguessable with it, because the run id it derives from is itself unguessable.

**(b) A reply runs on the calling request's thread.**
The plan put start *and* reply exchanges on the bounded exchange pool. A reply
is issued from a request the user is waiting on, and the pool it would wait for
is the one saturated by starts — so a reply could block behind the very
exchanges a reply often resolves, and a deadlock there would be indistinguish-
able from a slow agent. The reply therefore runs on the calling thread while
still being recorded as a durable `reply` exchange (state, kind, deadline), so
restart recovery, the observation suspension and the succession rules all see
exactly the exchange the plan described. Cancel keeps its dedicated control
pool for the same reason, unchanged.

**(c) iOS "Copy link" uses React Native's core `Clipboard`.**
`expo-clipboard` is not a dependency of this app and adding one for a single
call is a supply-chain cost with no benefit here. The call is isolated behind
`mobile/src/utils/clipboard.ts`, so migrating to `expo-clipboard` later is one
edit in one file.

**(d) Two feature-007 link tests were re-targeted, not deleted.**
They asserted the pre-014 behaviour that a reported link could be interactive
under some conditions. The 2026-09-04 product decision is that every reported
link is inert, without exception, so the two cases now assert that instead.

**(e) Two names differ from the data model.**
`observation_interval` lives on `ExchangePolicy` rather than standing alone,
because it is one of the exchange lane's bounds and a second home for it would
be a second thing to keep in step. `AgentPrimaryStateLabel` is declared in
`domain.py` and re-exported by `schemas/agents.py`, so the label set has one
definition and the schema module still reads as its owner.

**(f) Two removal tasks and two contract details, found by the reference runtimes.**
T110 (the service's ingest path) and T114 (the routes and schemas) landed in one
commit: the route needs the service method, the service method needs the request
schema, and removing any one alone leaves a tree that cannot import. T115 landed
before T111–T113 for the same reason — `connector.py` imports the domain
constants T111 removes.

The two conformance suites then found two things no fake had: A2A 1.0 returns
the Task *as* the JSON-RPC result for `GetTask` (only `SendMessage` wraps it in
`{"task": …}`), and a card that declares no security scheme is an agent asking
for no authentication rather than one refusing yours. Both were product bugs
against the unmodified reference runtimes, and both are fixed with their own
unit tests beside the conformance cases. Two smaller ones are asserted as
observed rather than as planned and say so in the tests: the helloworld sample
refuses cancel with `-32002 TASK_NOT_CANCELABLE`, not `-32004`; and a
token-secured Hermes refuses to POST a push notification to a private address,
so the loopback conformance stack proves the fallback (push is an optimisation,
the schedule is the guarantee) instead of the push leg.
