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

The planning artifacts were reviewed and accepted before any code existed. The
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

**(g) `revision` is the owner's edit token and does not move on a quiet
observation.**
The plan gave a run two counters without saying which one an owner's answer
names back. The implementation advanced both on every accepted write, and the
Compose E2E run found what that costs: the observer polls on a schedule the
owner cannot see, so a reply carrying the revision the page last read was
refused as **This run changed elsewhere** whenever any observation — including
one that learned nothing at all — had run in between. On the E2E stack that is
five seconds; in production it is sixty, so anyone who takes a minute to answer
is guaranteed to hit it.

The two counters are now separated by what they are for. `run_version` remains
BrainBuddy's observation version and the compare-and-set every background write
is serialised on — unchanged, and still what `data-model.md` ("Write rule for
background threads") describes. `revision` is the *user-edit* concurrency token
and advances only when the write moves something the owner could have read and
been answering; a pass that only records that the agent was asked again still
refreshes `last_contact_at`/`last_observed_at`/`updated_at` and leaves the token
alone. Materiality is decided by comparing values rather than by reusing the
timeline's "did this append a row?" test, because the two sets are not the same:
an observation carrying different artifacts, or clearing a cancellation request,
is not a new timeline row but is a change every surface renders.

Nothing in storage keys on `revision` — every conditional write on `agent_runs`
matches `json_extract(payload, '$.run_version')` (`repository.py` lines 1078 and
1186) and `save_run` is an unconditional upsert under the process-wide
`command_lock` — so a write that does not bump it is safe. No request or
response shape changed, so `contracts/api-deltas.md` line 246 ("unchanged
requests") stays true.

**(h) A delivery-check lookup has three outcomes, and only one of them
licenses a resend.**
The plan and `contracts/api-deltas.md` said "an ambiguous answer leaves the run
`delivery_unconfirmed`"; the implementation could not tell an ambiguous answer
from an empty one, because `_lookup_task` returned `None` both when the agent
answered "no task in this conversation" and when there was no answer at all — a
timeout, a JSON-RPC error, an unusable payload. **Check again** then resent on
the strength of a lookup that had established nothing, which is precisely the
duplicate the lookup exists to prevent (SC-008).

The lookup now returns an explicit outcome — adopted task, confirmed empty, or
unanswered — and only a *confirmed* empty answer reaches the resend branch. An
unanswered lookup leaves the run byte-for-byte as it was (`dispatch_state`,
`exchange_state` and `revision` all unchanged), answers 200 with the same
**Delivery unconfirmed** projection and the **Check again** control still
offered, and writes one audit row. No new refusal `reason` was invented: the
eight in FR-006 are conditions on the *send*, and this is the absence of the
evidence a send needs, not a ninth condition — so the "complete list" in FR-006
and in `contracts/api-deltas.md` still holds exactly as ratified.

`data-model.md` §6 gains one audit action, `delivery_lookup_failed`, whose
outcome is the allowlisted transport code (`a2a_timeout`, `a2a_response_invalid`
…) and never agent text. It is written per user-triggered check rather than
bounded per day, like the `task_adopted` row beside it: a check is a tap, not a
poll.

**(i) `check-delivery` takes an `expected_revision`.**
The plan gave the request body nothing but `current_password`, on the reasoning
that every identifier the check needs is already on the run. That is true of
*identifiers* and false of *concurrency*: the check can end in a message on the
wire, which makes it a mutation, and `mobile/AGENTS.md` requires every mobile
mutation to send `Idempotency-Key` **and** `expected_revision`. Without it a
**Check again** tapped on a cached run that had moved underneath — a run the
observer had already settled, or that a parallel check had resent for — was
carried out against a state the user was no longer being shown.

`AgentCheckDeliveryRequest` therefore gains `expected_revision: int | None`
(`ge=1`, default `None`). When it is sent and differs from `run.revision` the
call raises the same `ConflictError` the reply path raises, before the lookup
and so before any resend; a stale client cannot even spend a request at the
agent. It is optional because the guard is the client's to adopt and a body
that suddenly *required* it would break a client mid-rollout; both shipped
clients send it, web for parity with iOS. The body stays `extra="forbid"` and
gains no other key. `contracts/api-deltas.md` §check-delivery is corrected in
the same commit.

**(j) `check-delivery` reserves its `Idempotency-Key` rather than only
requiring one.**
The route demanded the header from the start and passed it to the service,
which never spent it. That is worse than not asking: the client is told its
retry is deduplicated and it is not. The dangerous case is the one the key
exists for — the resend goes out, its own answer is ambiguous, and the HTTP
response is lost. The run is still **Delivery unconfirmed**, the agent's new
task is not visible yet, so the retry's lookup comes back empty and licenses a
second copy of the same message.

The key now goes through the same `AgentIdempotencyRecord` machinery the
connection commands use: the call is serialised per key on `operation_lock`,
the first outcome is stored as the response body, a retry replays it verbatim
with no lookup and no send, and the same key against a different run is refused
with the `ConflictError` every other keyed path raises. Refusals are
deliberately not stored — each one names something the owner can put right, and
a retry after they have is a different world, not a replay. The record is
ordinary internal storage under the shape `data-model.md` §5 already describes;
only the `command` value (`check_delivery`) is new.

**(k) The send invariant is about who *initiates* a send, not who executes it.**
The plan's Consent & Safety check promised that "no background thread ever
emits a content-bearing message", and `research.md`, `data-model.md` §3 and
`contracts/a2a-wire.md` said the same thing in their own words —
`data-model.md` even listed the exchange pool among the threads that emit none.
Read literally every one of them is false, and false in a way that reads as a
bug report against the design the rest of the plan asks for: `dispatch_run`
returns after its courtesy wait while an exchange worker still holds the
`SendMessage`, precisely because an agent may hold that call open for the whole
reply window and a send that long may not sit on the request thread.

The invariant the code and the tests actually hold is that **no send is ever
initiated without a user action**. A worker executes a user-confirmed hand-off,
its user-triggered replay or a user reply; the observation scheduler, the
observation and control pools, restart recovery and the retention sweep only
ever look a run up. The four documents now say that, and the two halves are
pinned separately —
`test_agent_observer.py::TestExchangePool::test_014_FR_006_the_confirmed_send_is_executed_on_an_exchange_worker`
(the request thread returns having sent nothing; the pool's worker is what puts
the message on the wire) and the existing
`::test_no_background_thread_ever_sends_content` (four background entry points,
zero content-bearing sends), whose docstring now says which half it is.
`test_014_FR_006_the_send_invariant_is_written_as_initiation_not_execution`
keeps the prose from drifting back. No behaviour changed, no requirement moved,
and every task tick stands; `tasks.md` T015, T077 and T128 name that test by
the name `traceability.md` and `acceptance.md` already cite, so it keeps it.

**(l) `card.interface_url` is the dispatch target, so it is never card prose.**
T035 and `test_card_text_is_returned_verbatim_and_bounded` asserted that a card
whose `interface_url` is `javascript:alert(3)` comes back in
`AgentConnectionResponse.card.interface_url` verbatim, alongside the name and
description. The AC-031 half of that is right and stays: prose is returned
exactly as the agent wrote it, because escaping it here would hide what the
agent claims and the clients are the layer that renders it inertly. The
`interface_url` half was wrong twice over. `data-model.md` §1 defines that field
as the validated interface, and `service.py::_a2a_target` dispatches to it, so
the test asserted that a refused address is a legitimate value of the field
BrainBuddy sends the owner's task to.

It is also a state real discovery cannot produce: `_select_interface` puts every
candidate through `validate_interface_host` → `validate_destination`, whose
allowed schemes are `http` and `https`, so a `javascript:` interface or a
link-local metadata host is refused as `a2a_no_supported_interface` before a
summary exists. Only `FakeCardFetcher`, which hands the service a
`CardDiscovery` directly, could reach it. The test now offers a valid `https://`
interface and keeps the verbatim-and-bounded assertions for `name`,
`description` and skill text, and two new tests prove the refusal instead of
assuming it:
`test_agent_a2a_card.py::TestInterfaceSelection::test_014_FR_002_a_rejected_interface_never_reaches_the_card_summary`
(both addresses, through the production `validate_destination` rather than a
stub: no summary, no interface, no fingerprint, and the address in no failure
detail) and
`test_agent_relay_service.py::TestConnectByAgentCard::test_014_FR_002_a_rejected_interface_leaves_the_stored_card_alone`
(a card that starts naming one drops the connection to **unsupported** and
leaves the last successfully tested card, with its validated interface, exactly
as it was).

`data-model.md` §1 now says so in one sentence, and T035's text describes the
corrected assertion. No production code changed: the refusal was already there
and it is the tests that had described an impossible state. T035's tick stands.

**(m) A restart caught mid-*reply* must not take the start's delivery back.**
`recover_open_exchange` treated every interrupted exchange the same and set
`dispatch_state: delivery_unconfirmed` on all of them. For a `reply` that is
false and dangerous: the start of such a run was delivered — `dispatch_state ==
"sent"` is the record of it — and only the owner's answer is in doubt. Marking
it `delivery_unconfirmed` made the run eligible for **Check again**, whose
resend path sends `_start_message`. One restart during one reply was enough to
put a second copy of the hand-off at an agent that already had it, which is
exactly the duplicate SC-008 exists to prevent.

Recovery now branches on `exchange_kind`. A start is unchanged. A reply is
marked `interrupted` and nothing else; the lookup runs, an adopted task is
applied, and the reply command is reconciled. Two things had to become durable
for that to be possible at all: the reply's command row and the run's
`reply_pending_command_id` are now written when the exchange *opens*, as
`unconfirmed`, the way `dispatch_run` has always written its `start` row at
reservation. Writing them only after the send meant a restart mid-reply left no
record that the owner had answered — no `reply_pending`, nothing for a later
observation to confirm, and the answer gone from a page that had shown it.
`_close_reply_exchange` rewrites the row with the outcome and now also aligns
the run's marker directly, because an observation write is refused outright for
a run whose connection was disconnected or whose identifiers expired, and a
marker left behind there would claim an answer is outstanding that the agent
had already acknowledged.

**Contract correction.** `data-model.md` §4 and `contracts/a2a-wire.md` said a
restart-interrupted reply is confirmed "by succession evidence — a task in the
run's conversation created after the reply command — because Hermes serves no
history". That rule was never implemented, and it should not be: a task created
after the command is not evidence that the agent read the *answer*, and any
successor the agent created from the start message alone would be read as an
acknowledgement the user never got. Recovery therefore confirms only on the
agent's own record — the reply's `messageId` in the task's `history[]`, the same
correlation `_settle_reply_by_history` already uses for the observation path —
and otherwise leaves the command `unconfirmed`, which is the state the run
already knows how to show and which keeps the reply control offered. Both
documents now say that. `data-model.md` §6 gains one audit action,
`exchange_interrupted`, written once per interrupted reply recovery could not
settle, whose outcome is the lookup's allowlisted transport code or
`reply_unacknowledged`.

Two existing crash-simulation tests
(`TestRelayFailureRecoveryEdges::test_retry_after_a_post_send_save_failure_reconciles_the_reserved_command_id`
and `::test_reply_retry_after_post_delivery_failure_reconciles_without_redelivery_after_terminal_callback`)
broke a `save_command` fake on its *first* call to simulate an outage after the
send. A reply now saves that row twice, so the fakes name the second one; the
scenario they assert is unchanged.

**(n) Restart recovery is two steps, and only the first may run before the app
serves.**
`main.py` called `agent_observer.recover_interrupted_exchanges()` synchronously
at startup, and that call performs one `ListTasks` per open exchange under the
short-call deadline (15 s by default). Eight unreachable exchanges therefore
delayed the first request by about two minutes, while `fly.backend.toml`'s
health check gives up after five seconds — so the deployment most in need of
recovery is the one the platform restarts before it can finish, over and over.

Recovery is now split by what it needs. `mark_interrupted_exchanges()` is pure
state and no network: a queued exchange is settled **Not sent** and re-offered,
an open one is marked `interrupted` (and only a start also becomes **Delivery
unconfirmed**, per (m)), and it returns the runs still owing a lookup. That runs
at boot, because it is what makes every run honest and it cannot block.
`resolve_interrupted_exchanges()` submits the lookups to the control lane — the
one that is never held open — immediately after `agent_observer.start()`, so
they happen once the app is serving. `recover_interrupted_exchanges()` remains
as both halves in one synchronous call for callers that want it, which is what
the observer suite uses.

Nothing about the send invariant changes: the resolver only looks a run up.
`test_014_SC_007_the_boot_time_mark_asks_the_agent_nothing` pins that the boot
step makes no client call at all,
`test_014_FR_006_the_lookups_run_on_the_pool_and_settle_the_runs` that the
second step is ordinary pool work,
`test_014_FR_006_a_run_purged_between_the_two_steps_is_left_alone` that the gap
the split introduces is survivable, and
`test_014_SC_007_health_answers_before_the_boot_lookups_come_back` drives a real
`TestClient(app)` whose resolver is held on an event and gets a 200 from
`/health` before it is released. `research.md` Decision C, `tasks.md` T054, T066
and T070 and the comment block in `main.py` describe the two steps; the same
paragraph of `research.md` carried the (k) overclaim in a fourth phrasing and
the (m) succession-evidence rule, and both are corrected there in this commit.

**(o) The card's `securityRequirements` decide whether the credential may be
sent, not just its `securitySchemes`.**
`contracts/a2a-wire.md` has always said the owner's `auth_scheme` must satisfy
at least one requirement. `_select_scheme` never read them: it accepted any
`securitySchemes` entry whose kind matched and stopped there. `securitySchemes`
is the catalogue of what an agent *understands*, and `securityRequirements`
(legacy `security[]`) is what it will accept on a call — so an agent that
declares bearer for another audience while requiring an API key from this one
was matched, and BrainBuddy disclosed the owner's bearer token to an endpoint
certain to reject every request it made.

The requirements are now consulted first. The names inside one alternative are
conjoined and a connection holds exactly one credential under exactly one
`auth_scheme`, so an alternative is satisfiable only when every scheme it names
is of that kind — two of the same kind are met by the same header, two of
different kinds by neither. A name the card never declared has no scheme behind
it, states nothing BrainBuddy could check, and is dropped from the alternative
rather than refused; an alternative left empty by that, or empty to begin with,
requires nothing and is satisfiable. When no alternative is satisfiable the
result is `a2a_auth_scheme_unsupported` naming the first scheme of the first
alternative, which is the one the owner would have to change to. An empty
requirement list is unchanged: the contract reads it as an agent needing no
credential and the credential is still sent.

Nothing about the fingerprint moved — `security_requirements` is copied into the
summary exactly as before, so drift is still measured against what the card
declared. Five tests in `test_agent_a2a_card.py::TestSecuritySchemes` cover the
refusal, the conjunction, the satisfiable alternative, the undeclared name and
the empty list; the `a2a-wire.md` row now states the conjunction and
undeclared-name rules it left implicit.
