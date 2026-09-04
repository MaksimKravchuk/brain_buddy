# Design: A2A relay wire contract

**Feature**: `specs/014-a2a-relay-wire-contract/`
**Spec**: `spec.md` (Clarifications settled: 2026-09-03, session 2026-09-03, zero open markers)
**Screens**: `design/*.html` — six self-contained static files, no script, no external font, no CDN
**States**: **129 total** — D-01 25, D-02 15, D-03 27, M-01 22, M-02 14, M-03 26
**Human sign-off**: Max, 2026-09-03 (decisions recorded in spec.md Clarifications).
Amended after review campaign 1 (2026-09-03): D-03-S27, M-03-S26 added; Check again
affordance on D-03-S05/M-03-S04; M-01 sheet order; focus rules; result links inert
(D-03-S11/M-03-S10). Re-acknowledged by Max, 2026-09-04.
Amended after review campaign 2 (2026-09-04): D-01-S25, M-01-S22 added; restart variant
of Not sent; disconnect copy names the card erasure; loading citations; aria-disabled
parity. Re-acknowledged by Max, 2026-09-04.

<!--
  Produced by /speckit-design via the design-architect subagent, after
  /speckit-clarify. Screen ids (D-01…, M-01…) and state ids (D-01-S01…) are
  stable forever: the acceptance traceability matrix keys off them.

  ADR-0006: the term is Tag. The retired taxonomy noun it replaced, and that noun's
  at-prefixed form, are forbidden strings anywhere in this file or design/. The sweep
  that proves it is a recorded, case-insensitive manual grep (see "Design authority"),
  run alongside the unit-tested design-skill contract
  (scripts/test_validate_brain_buddy_design_skill.py). No CI job scans this feature
  directory for the retired noun, so the grep is the evidence, not a green build.
  See "Vocabulary" below for how this feature's wire-level nouns are rendered in the UI.
-->

## Applicability

This feature has user-visible surfaces on web and iOS, designed below. It replaces
**only the wire contract** of feature 007. The two surfaces per platform are the same
ones 007 named — a "Connected agents" settings surface and a Task-attached hand-off and
run surface — but their content changes materially, so this design supersedes
`specs/007-external-agent-relay/design.md` for everything it covers. 007's numbering is
not reused; overlap in the digits is coincidence.

What is gone from 007: the endpoint-plus-custom-header connection form, the connector
capability probe as a user-visible thing, and both signing-secret sheets. There is no
bespoke inbound secret any more. Push notifications use a per-run token BrainBuddy
registers with the agent automatically and the user never sees, so no screen mints,
displays, copies or replaces a secret the agent must configure.

What is new: connection by agent address plus one of exactly two credential schemes, a
discovery result read from the agent's published card, four unsupported categories that
are four different sentences, the guarantee-tier disclosure in two places, and eleven
additional run conditions — plus a task-succession timeline row (D-03-S27, M-03-S26) that
adds no run condition of its own, and the push-notification callback registration disclosed
in the hand-off manifest.

### Vocabulary

ADR-0006 makes `Tag` canonical and forbids the retired taxonomy noun. Two substitutions
apply to every surface and every string in `design/`. **Both were accepted at the
2026-09-03 sign-off**, and `spec.md` now uses the same two terms:

| Spec concept | UI label everywhere | Why |
|---|---|---|
| FR-005's optional user-selected extra payload items | **Supporting items** | The forbidden noun cannot appear in product copy. 007's design already used "supporting items". |
| FR-006's conversation identifier, defined as equal to the run's stable correlation ID | **Correlation ID** | It *is* the correlation ID (007 FR-017), so this is the accurate name, not a euphemism. |

The two A2A wire field names these map onto — the per-message identifier and the
conversation identifier, named verbatim in spec.md Assumptions — appear only in technical
artifacts and are never returned in a client-facing response. What enforces the ADR-0006
substitution over this file and `design/` is the recorded case-insensitive grep in
**Design authority** below, plus `scripts/test_validate_brain_buddy_design_skill.py`
for the design-skill contract itself — not a CI validator, because no CI job reads this
feature directory.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop | Connected agents | Add by agent address, test, read the discovery result and guarantee tier, rotate, disconnect | FR-001, FR-002, FR-003, FR-004, FR-011, FR-012, FR-014, FR-016 |
| D-02 | desktop | Hand-off review | The consent boundary: the exact text that leaves, the destination, both disclosures, one confirmation | FR-003, FR-004, FR-005, FR-006, FR-010, FR-011, FR-014, FR-016 |
| D-03 | desktop | Task agent panel and compact Task rows | Monitor, answer, request cancellation, read the result; every run condition from one projection | FR-006, FR-007, FR-008, FR-009, FR-010, FR-013, FR-014, FR-015, FR-016 |
| M-01 | mobile | Connected agents | The same connection contract at iPhone width, forms as sheets | FR-001, FR-002, FR-003, FR-004, FR-011, FR-012, FR-014, FR-016 |
| M-02 | mobile | Hand to agent review sheet | The same manifest and both disclosures in a bottom sheet | FR-003, FR-004, FR-005, FR-006, FR-010, FR-011, FR-014, FR-016 |
| M-03 | mobile | Task agent section and compact Task rows | The same run projection on iOS, label-for-label | FR-006 – FR-010, FR-013 – FR-016 |

Files:

- `design/D-01-connected-agents-desktop.html`
- `design/D-02-handoff-review-desktop.html`
- `design/D-03-task-agent-panel-desktop.html`
- `design/M-01-connected-agents-mobile.html`
- `design/M-02-handoff-review-mobile.html`
- `design/M-03-task-agent-panel-mobile.html`

## State inventory

**Shared loading treatment.** Every loading row below (`D-01-S02`, `D-02-S03`, `D-03-S02`,
`M-01-S02`, `M-02-S05`, `M-03-S20`) shows its skeleton only after about 250 ms, so a fast
response never flickers a skeleton on and off; until then the surface holds the frame it
already has. The skeleton never stands in for the empty state, and it carries no
correlation ID, because nothing has failed.

### D-01 — Connected agents (desktop)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-01-S01 default | one or more saved connections | Name, address, status pill, tier disclosure (best-effort rows carry the extension link), credential scheme, last contact, last tested, stale threshold, four actions | "The last test reached this agent and it authenticated." | FR-001, FR-002, FR-003, FR-011 |
| D-01-S02 loading | first server fetch | Settings frame intact, skeleton rows after ~250 ms, "Loading connections…"; never the empty state | "Loading connections…" | 007 FR-018 |
| D-01-S03 empty (first run) | no connection has ever been saved | Display heading, one-line hint, single primary action | "Connect an agent you operate" | FR-001 |
| D-01-S04 empty (filtered to nothing) | — | Deliberately absent: the list has no filter, search or sort. The real case lives on D-02-S05 | "No filter, no search, no sort on this list" | scope boundary, FR-001 |
| D-01-S05 error | list fetch fails | Category, correlation ID, retry; no partial rows invented | "We couldn't load your connections" | SC-009, 007 FR-017 |
| D-01-S06 partial failure | cached list exists, refresh fails | Cached rows stay, each stamped with the time it was read, all labelled potentially stale | "Showing potentially stale saved data." | 007 FR-018 |
| D-01-S07 offline / interrupted | browser reports offline | Saved status visible and stamped; every secret-bearing action disabled; nothing queued | "Offline — reconnect to manage agents." | 007 FR-018 |
| D-01-S08 add agent (bearer) | user opens the add form | Agent name, agent address, scheme radio, credential, password; egress rule stated on the address field. Navigating away or closing the form discards it silently: nothing was stored, no credential was sent, and the four fields are cheap to re-enter, so no warning is shown | "BrainBuddy fetches the agent card from this address's standard well-known location…" | FR-001, FR-004 |
| D-01-S09 add agent (API key) | user picks the API-key scheme | Read-only header name sourced from the card; before discovery it reads "Read from the agent card when you test" | "Read from the agent card after discovery. You do not type it." | FR-001 |
| D-01-S10 test: ready, guaranteed | test succeeds, card declares the extension | Agent name, version, description, skills, streaming, push, protocol version, interface, then the tier | "**Guaranteed single start.** …a retry cannot start a second run." | AC-001, FR-002, FR-003, FR-011 |
| D-01-S11 test: ready, best-effort | test succeeds, card does not declare it | Same discovery result, best-effort tier, the link to the published extension specification, plus the push-not-supported note | "**Best-effort single start.** …A duplicate remains possible if the agent forgets its tasks." · "Read the single-start extension specification" | AC-005, FR-003, FR-011 |
| D-01-S12 test: invalid credentials | agent rejects the credential | Rose pill, corrective action, correlation ID; the submitted secret is never echoed | "The agent answered and rejected the credential. Rotate it below, then test again." | AC-003, FR-002, SC-009 |
| D-01-S13 test: unreachable | transport failure or test timeout | Rose pill, "Nothing was sent", correlation ID | "BrainBuddy could not reach this address before the test timeout." | AC-002, FR-002 |
| D-01-S14 unsupported: not an A2A agent | address answers, no card at the well-known location | Its own sentence and its own corrective action | "There is no agent card at its well-known location." | AC-002, FR-002, SC-009 |
| D-01-S15 unsupported: protocol version | card declares a version outside 1.0.x | Names the version found and the version required | "The card declares A2A 0.9.4. BrainBuddy speaks protocol version 1.0.x only." | AC-002, FR-001 |
| D-01-S16 unsupported: no supported interface | no usable JSON-RPC interface over HTTPS | Also covers a JSON-RPC interface pointing at a refused destination | "No JSON-RPC interface BrainBuddy can use over HTTPS." | AC-002, FR-001, edge case |
| D-01-S17 unsupported: authentication scheme | card offers only OAuth2 or mutual TLS | Names the unsupported scheme, names the two supported ones | "This card requires **OAuth2**. BrainBuddy supports a bearer token or an API key…" | AC-004, FR-001 |
| D-01-S18 private destination refused | loopback, link-local, metadata or private address | Refusal before any credential or content leaves | "Nothing left BrainBuddy." | AC-006, FR-004, 007 FR-004 |
| D-01-S19 stale | last contact older than the threshold | Amber pill overriding an earlier ready; hand-off blocked | "Test it again before a hand-off." | FR-002 |
| D-01-S20 **Agent changed** | card fingerprint drift on interface address or authentication | Tested interface and current card interface shown side by side; the connection behaves as untested until a new successful test; reauthentication demanded | "**Agent changed**" · "BrainBuddy will not send task content to a destination you have not tested." | FR-002, FR-014, AC-012, FR-004 |
| D-01-S21 disconnected: superseded wire | a pre-existing bespoke connection record | Neutral disconnected pill with the reason; no path to reuse it | "Superseded wire contract." | FR-012, SC-010 |
| D-01-S22 rollout OFF | deployment flag off | Add, edit, test and rotate unavailable; disconnect still available; runs keep reporting | "The external-agent relay rollout is off." | FR-016, 007 FR-019 |
| D-01-S23 disconnect confirmation | user chooses Disconnect | Names what is destroyed — the credential **and the discovered agent-card summary with its fingerprint** — what stops, and what is *not* cancelled; password required | "The stored credential and the agent-card summary BrainBuddy discovered — its name, version, description, skills and interface — are erased together, along with the card fingerprint." · "Disconnecting does not cancel work the agent already accepted." | AC-022, FR-016 |
| D-01-S24 rotate credential | user chooses Rotate credential | No current value shown; new credential plus password | "BrainBuddy cannot show you the current one." | FR-001, AC-023 |
| D-01-S25 rate limited | the connection test is answered by the agent's own rate limit (`last_test_error_code = a2a_rate_limited`) | Rose category pill, the retry-after hint when the agent gave one, correlation ID. The connection stays **untested** — never ready — so it still cannot take a hand-off; **Test connection** stays available and re-uses the sealed credential, echoing nothing secret and asking for nothing to be retyped | "**Rate limited**" · "The agent is rate limiting. It answered the test by refusing it, so BrainBuddy learned nothing about the connection and nothing was sent." · "Test again in about 60 seconds." | FR-002, SC-009, AC-037 |

### D-02 — Hand-off review (desktop)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-02-S01 default (guaranteed) | user picks a ready connection | Agent chooser, Task title, optional details toggle, removable supporting items, Task ID, run ID, correlation ID, destination, **the push callback address with its token masked**, tier, cancellation disclosure, external-copy notice | "What will be sent" · "This agent advertises push notifications, so BrainBuddy also registers the callback address above with it. It is private to this one run, its secret part is never shown to anyone, and the agent holds it until the run ends. The agent can only use it to ask BrainBuddy to check on the run — no task content ever comes back through it." | AC-007, FR-005, SC-005 |
| D-02-S02 review (best-effort) | the chosen agent lacks the extension | Same manifest, amber tier block restating the duplicate risk and the mitigation, plus the link to the published extension specification. This block appears in *every* best-effort review; S13–S15 are its three acknowledgement states | "**Best-effort single start.**" · "Read the single-start extension specification" | FR-003, FR-011, AC-005 |
| D-02-S03 loading | preview being built server-side | Skeleton manifest, explicit "no task content has been sent" | "Building the hand-off preview…" | FR-005 |
| D-02-S04 empty (first run) | account has no connection | Explanation plus a route to Connected agents | "No agents connected yet" | FR-001 |
| D-02-S05 empty (filtered to nothing) | connections exist, none eligible (stale, unsupported, disconnected or **Agent changed**) | Every ineligible connection listed with *why* and its corrective action | "None of your agents can take this hand-off" | AC-011, FR-002 |
| D-02-S06 error | preview request fails | Category, correlation ID, retry; nothing was sent | "We couldn't build this hand-off" | SC-009 |
| D-02-S07 partial failure | one connection's status could not be refreshed | That row is shown, marked "Status unknown", and is **not** selectable | "Could not be refreshed just now, so it is not offered." | FR-002 (fail closed) |
| D-02-S08 re-review required | manifest token no longer matches | Warning above a rebuilt manifest; the earlier confirmation was not used | "What would be sent has changed. Review it again before confirming." | FR-005 |
| D-02-S09 refused: agent changed | card drift detected at confirm time | Refusal before content leaves, with the reauthentication warning | "Its card now advertises a different interface address…" | AC-012, FR-004 |
| D-02-S10 offline / interrupted | no network | Manifest stays readable, send disabled, nothing queued; reopening rebuilds from the server | "Sending is unavailable and nothing is queued." | 007 FR-018 |
| D-02-S11 reauthentication required | first content-bearing send to this destination | Password field with the reason stated | "…so BrainBuddy re-checks your password." | FR-004, 007 FR-003 |
| D-02-S12 sending | confirmation in flight | Disabled primary, replay explanation | "Confirming again while this is in flight returns the same run." | AC-010, SC-002, SC-008 |
| D-02-S13 best-effort, first hand-off, not acknowledged | first hand-off on a best-effort connection | Disclosure, extension link, and an unticked acknowledgement; **Send to agent is disabled** | "I understand that a duplicate task is possible with this agent" · "Asked once, on your first hand-off to this agent." | FR-003, AC-026 |
| D-02-S14 best-effort, first hand-off, acknowledged | user ticks the acknowledgement | Same review with the box ticked; Send to agent enabled | "Acknowledged. BrainBuddy will not ask again for this agent…" | FR-003, AC-026 |
| D-02-S15 best-effort, later hand-off | a hand-off after the acknowledgement was recorded for that connection | Disclosure and extension link unchanged; no acknowledgement control; Send enabled | "You acknowledged the duplicate risk for this agent on your first hand-off…" | FR-003, AC-026 |

### D-03 — Task agent panel and compact Task rows (desktop)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-03-S01 default = empty (first run) | Task has never been handed over | Only "Hand to agent". No run section, no empty run heading — for this screen the first-run empty state *is* the default state, because an empty "Agent runs" heading would imply the feature had been used | "Hand to agent" | FR-005 |
| D-03-S02 loading | runs being fetched | Heading plus a skeleton run card after ~250 ms | "Loading runs…" | 007 FR-018 |
| D-03-S03 Not sent (rate limited) | agent rate-limits before creating a task | Rose card, actionable category, retry that reuses the same run and message IDs. **Restart variant**: a hand-off still queued when BrainBuddy restarted was provably never sent, so it is settled as **Not sent** with its own sentence and the same retry — never as **Delivery unconfirmed** | "The agent is rate limiting." · "BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy." · "Try this hand-off again" | FR-006, edge case |
| D-03-S04 Sent | dispatch accepted, no agent state yet | Sky pill, waiting explained, no fabricated progress. **Queued variant**: while no connection slot is free the same state reads **Queued** on a neutral pill, because nothing has left BrainBuddy yet; the identifiers are already reserved and it becomes **Sent** only once the message actually goes out | "Some agents answer only when the work is finished." · "Waiting for a free connection slot; nothing has been sent yet" | AC-014, FR-006, FR-007, SC-006 |
| D-03-S05 Delivery unconfirmed | ambiguous or timed-out dispatch | Amber pill, nothing re-sent on its own, lookup-before-resend explained, and a **Check again** action. Check again replays the *same* confirmation — same correlation ID, same message ID — so it looks the run up at the agent first and adopts an existing task; only an empty lookup sends the identical message again. It is never a new send and never mints a second run | "**Delivery unconfirmed** … It was not re-sent." · "Runs the same check again with the same correlation ID and the same message ID. It is never a new send." | FR-006, edge case |
| D-03-S06 Accepted | submitted observed | Sky pill, timeline entry | "Accepted" | FR-009 |
| D-03-S07 Running | working observed | Sky pill plus the agent's own status text, attributed | "Running" | AC-013, FR-009 |
| D-03-S08 blocked with a question | input-required observed | Amber card, the agent's question, a reply box and Send answer | "Needs you" | FR-009, FR-010 |
| D-03-S09 reply unconfirmed | reply sent, not acknowledged | The answer shown as sent-not-acknowledged; state does not advance | "Your answer was sent but the agent has not acknowledged it yet." | AC-015, FR-010 |
| D-03-S10 blocked, needs authentication | auth-required observed | Amber card, no reply control at all | "Agent needs additional authentication." | FR-009 |
| D-03-S11 Agent reported complete | completed observed, or a direct message answer | Inert text, non-text artifacts as placeholders naming the content type, Task still open. **Every address the agent reports is inert text beside a Copy link control** — no anchor, no new tab, nothing opened or fetched, whatever the scheme. **Too-large variant**: when the agent's result exceeded the size BrainBuddy stores, the observed state stands and carries a **Result too large to store** marker saying the text and attachment list were not kept; it is never rendered as **Stopped reporting** | "**Agent reported complete**" · "This is what the agent said it did. The task is still open — completing it is your call." · "Every address the agent reports stays inert text, whatever its scheme. BrainBuddy does not make one clickable and never opens or fetches one — copy it if you want to go there yourself." · "**Result too large to store.**" | AC-016, FR-009, 007 FR-012, FR-014 |
| D-03-S12 Failed with reason | failed observed | Rose card, the agent's reason, no retry of the work | "Failed" | AC-017, FR-009 |
| D-03-S13 Failed — rejected | rejected observed | Rose card with the fixed reason | "**Rejected by agent**." | AC-017, FR-009 |
| D-03-S14 Cancellation requested | user requests cancellation, agent accepts the request | Amber pill; the work may still be running | "**Cancellation requested**" | AC-018, FR-010 |
| D-03-S15 Cancelled | canceled observed | Neutral terminal pill, timeline preserved | "Cancelled" | AC-017, FR-009 |
| D-03-S16 cancellation unsupported | agent answers that cancel is unsupported or the task is not cancelable | Last observed state kept, the refusal stated as its own line | "**Cancellation not supported by this agent.**" | AC-018, FR-010, FR-013 |
| D-03-S17 Stopped reporting | reporting window elapses with no successful observation | Amber overlay on the last agent-reported state, last contact preserved | "**Stopped reporting**" · "BrainBuddy does not know whether the agent is still working." | AC-019, FR-015, 007 FR-013 |
| D-03-S18 Agent no longer reports this run | agent answers that the task does not exist | Neutral pill, timeline and last contact kept, reply and cancel withdrawn, no failure claimed | "**Agent no longer reports this run**" | AC-020, FR-013, FR-015 |
| D-03-S19 content expired | 30-day content retention passes | State label survives, relayed text and artifacts replaced by the marker | "**Content expired under retention policy**" | 007 FR-015, SC-007 |
| D-03-S20 Connection disconnected | the connection is disconnected while the run is live | Last observed state frozen, observation stopped, commands withdrawn, no cancellation claimed | "**Connection disconnected**" · "Disconnecting did not cancel work it had already accepted." | AC-022, FR-016 |
| D-03-S21 compact Task rows | task list rendering | Agent avatar, projected state, **guarantee tier in full**, cancellation-unsupported when it applies, needs-you tint, project and Tag columns unchanged | "Running · Guaranteed single start" | SC-004, FR-013, FR-014 |
| D-03-S22 empty (filtered to nothing) | a Tag view whose tasks have no runs | No chips, no heading, no placeholder | — | FR-013 |
| D-03-S23 error | run list fetch fails | Category, correlation ID, retry; the Task itself unaffected | "We couldn't load the runs for this task." | SC-009 |
| D-03-S24 partial failure | cached runs shown, refresh fails | Cached run stamped with the time it was read | "Showing cached agent data because the refresh failed." | 007 FR-018 |
| D-03-S25 offline / interrupted | no network | Cached state stamped, reply and cancel disabled, nothing queued | "Replies and cancellation are unavailable and nothing is queued." | 007 FR-018 |
| D-03-S26 two runs on one Task | a later hand-off after a terminal run | Both runs listed, each with its own frozen sent content | "Editing or completing the task after a dispatch never rewrites what was already sent." | edge case, 007 FR-012 |
| D-03-S27 Task succession | the agent answers a reply with a different task identifier inside the same conversation | One timeline row and nothing else: the projected state is not changed by the succession itself, both task identifiers are kept in the timeline, the run keeps its single correlation ID, and the reply is never refused because the identifier moved | "The agent continued this run in a new task" | FR-010, edge case |

### M-01 — Connected agents (iOS, 390×851)

Same semantics as D-01, state for state. Frames in `design/M-01-connected-agents-mobile.html`.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-01-S01 default | saved connections exist | Cards at 14px radius; tier under the status line, best-effort carrying the extension link; actions wrap two-up at 44pt | as D-01-S01 | FR-001 – FR-003, FR-011 |
| M-01-S02 loading | first fetch | Skeleton cards after ~250 ms | "Loading connections…" | 007 FR-018 |
| M-01-S03 empty (first run) | none saved | 24px display heading, hint, one primary action | "Connect an agent you operate" | FR-001 |
| M-01-S04 empty (filtered to nothing) | — | Deliberately absent, points at M-02-S03 | "No filter, no search, no sort" | scope boundary |
| M-01-S05 error | fetch fails | Category, correlation ID, 44pt retry | "We couldn't load your connections" | SC-009 |
| M-01-S06 partial failure | refresh fails over cache | "As of 21:58" stamp on every row | "Showing potentially stale saved data." | 007 FR-018 |
| M-01-S07 offline / interrupted | device offline, app resumed | Stamped cache, disabled actions, nothing queued; resume loads the server projection | "Reopening the app loads the server projection…" | 007 FR-018 |
| M-01-S08 add agent sheet | user taps Add an agent | Sheet with address, scheme radios, credential, password; egress rule inline. Swiping the sheet away or leaving the screen discards it silently, as on D-01-S08 — nothing stored, nothing sent, fields cheap to re-enter, so no warning | as D-01-S08 | FR-001, FR-004 |
| M-01-S09 discovery result | test succeeds | Card metadata as a two-column list plus skill pills plus tier | as D-01-S10 | AC-001, FR-003 |
| M-01-S10 invalid credentials | credential rejected | One sentence, correlation ID stub | as D-01-S12 | AC-003 |
| M-01-S11 unreachable | transport failure or timeout | One sentence, correlation ID stub | as D-01-S13 | AC-002 |
| M-01-S12 not an A2A agent | no card at the well-known location | One sentence | as D-01-S14 | AC-002 |
| M-01-S13 unsupported protocol version | version outside 1.0.x | One sentence naming both versions | as D-01-S15 | AC-002 |
| M-01-S14 no supported interface | no usable JSON-RPC over HTTPS | One sentence | as D-01-S16 | AC-002 |
| M-01-S15 unsupported authentication scheme | OAuth2 or mutual TLS only | Names both | as D-01-S17 | AC-004 |
| M-01-S16 private destination refused | refused network class | "Nothing left BrainBuddy." | as D-01-S18 | AC-006 |
| M-01-S17 stale | threshold exceeded | Amber pill | as D-01-S19 | FR-002 |
| M-01-S18 **Agent changed** | card drift | Behaves as untested; new test plus password demanded | as D-01-S20 | FR-002, FR-014, AC-012, FR-004 |
| M-01-S19 superseded wire contract | pre-existing bespoke record | Neutral disconnected pill with the reason | as D-01-S21 | FR-012, SC-010 |
| M-01-S20 rollout OFF | flag off | Amber notice; disconnect still available | as D-01-S22 | FR-016 |
| M-01-S21 disconnect sheet | user taps Disconnect | Destructive sheet, password, destructive action *below* the safe one; the same erasure sentence as D-01-S23 — credential, discovered card summary and card fingerprint go together | as D-01-S23 | AC-022 |
| M-01-S22 rate limited | connection test answered by the agent's rate limit (`last_test_error_code = a2a_rate_limited`) | Rose category pill in the outcomes list, the retry-after hint when the agent gave one; connection stays untested, 44pt **Test connection** still offered and re-uses the sealed credential | as D-01-S25 | FR-002, SC-009, AC-037 |

### M-02 — Hand to agent review sheet (iOS, 390×851)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-02-S01 default (guaranteed) | ready connection chosen | Scrolling sheet; Send and Cancel pinned at the bottom in thumb reach; the manifest carries the same masked push callback address and its disclosure | as D-02-S01 | AC-007, FR-005, SC-005 |
| M-02-S02 review (best-effort) | agent lacks the extension | Amber tier block plus the extension link; M-02-S12 – S14 are its three acknowledgement states | "**Best-effort single start.**" · "Read the single-start extension specification" | FR-003, FR-011 |
| M-02-S03 empty (filtered to nothing) | connections exist, none eligible (stale, unsupported, disconnected or **Agent changed**) | Each ineligible connection with its reason | "None of your agents can take this hand-off" | AC-011, FR-002 |
| M-02-S04 empty (first run) | no connection at all | Route to Connected agents | "No agents connected yet" | FR-001 |
| M-02-S05 loading | preview being built | Skeleton, "No task content has been sent." | "Building the hand-off preview…" | FR-005 |
| M-02-S06 error | preview fails | Category, correlation ID, retry | "We couldn't build this hand-off" | SC-009 |
| M-02-S07 re-review required | manifest token stale | Warning above a rebuilt sheet | "What would be sent changed since you reviewed it." | FR-005 |
| M-02-S08 partial failure | one connection unrefreshable | Marked "Status unknown", not selectable | as D-02-S07 | FR-002 |
| M-02-S09 reauthentication required | first send to this destination | Password field with the reason | as D-02-S11 | FR-004 |
| M-02-S10 offline / interrupted | no network, or the app is closed mid-review | Send disabled, nothing queued; resume rebuilds from the server | "…reopening loads the server projection and rebuilds this review before anything can leave." | 007 FR-018 |
| M-02-S11 sending | confirmation in flight | Sheet not swipe-dismissible while in flight; replay explained | "Confirming again while this is in flight returns the same run." | AC-010, SC-008 |
| M-02-S12 best-effort, first hand-off, not acknowledged | first hand-off on a best-effort connection | Unticked 44pt acknowledgement row; **Send to agent disabled** | "I understand that a duplicate task is possible with this agent" | FR-003, AC-026 |
| M-02-S13 best-effort, first hand-off, acknowledged | user taps the acknowledgement | Ticked; Send enabled | "Acknowledged. BrainBuddy will not ask again for this agent." | FR-003, AC-026 |
| M-02-S14 best-effort, later hand-off | acknowledgement already recorded | Disclosure and link stay; no acknowledgement control | "…so there is no acknowledgement step here." | FR-003, AC-026 |

### M-03 — Task agent section and compact Task rows (iOS, 390×851)

Every D-03 run condition, label for label, from the same server projection.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-03-S01 default = empty (first run) | Task with no run | Only "Hand to agent"; no run section at all. As on D-03, the first-run empty state and the default state are the same state | "Hand to agent" | FR-005 |
| M-03-S02 Not sent (rate limited) | agent rate-limits | Rose card, category, same-IDs retry note, 44pt **Try this hand-off again**. **Restart variant**: a queued hand-off interrupted by a restart is settled as **Not sent** with its own sentence and the same retry, never as **Delivery unconfirmed**; drawn in the variants frame | as D-03-S03 · "BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy." | FR-006 |
| M-03-S03 Sent | dispatch accepted | Sky pill, waiting explained. **Queued variant**: while no connection slot is free the same state reads **Queued** on a neutral pill, because nothing has left BrainBuddy yet | as D-03-S04 · "Waiting for a free connection slot; nothing has been sent yet" | AC-014, SC-006 |
| M-03-S04 Delivery unconfirmed | ambiguous dispatch | Amber pill, lookup-before-resend, and a 44pt **Check again** row that replays the same confirmation with the same correlation ID and the same message ID — lookup first, adopt if a task is there, resend the identical message only on an empty lookup. Never a new send | "**Delivery unconfirmed**" · "Check again runs the same check with the same correlation ID and the same message ID. It is never a new send." | FR-006 |
| M-03-S05 Accepted | submitted observed | Sky pill | as D-03-S06 | FR-009 |
| M-03-S06 Running | working observed | Sky pill plus attributed status text; 44pt cancel | as D-03-S07 | AC-013 |
| M-03-S07 blocked with a question | input-required | Question, 56px answer field, 44pt Send answer | "Needs you" | FR-010 |
| M-03-S08 reply unconfirmed | reply not acknowledged | Sent-not-acknowledged line | as D-03-S09 | AC-015 |
| M-03-S09 blocked, needs authentication | auth-required | No reply box at all | "Agent needs additional authentication." | FR-009 |
| M-03-S10 Agent reported complete | completed observed | Inert text, artifact placeholders naming the content type, Task still open. **Every reported address is inert text beside a 44pt Copy link control** — nothing is tappable, opened or fetched. **Too-large variant**: the observed state stands with a **Result too large to store** marker; never **Stopped reporting** | "**Agent reported complete**" · "Addresses the agent reports stay inert text. BrainBuddy does not make one tappable and never opens or fetches one — copy it if you want to go there yourself." · "**Result too large to store.**" | AC-016, FR-014 |
| M-03-S11 Failed with reason | failed observed | Rose card, the agent's reason | as D-03-S12 | AC-017 |
| M-03-S12 Failed — rejected | rejected observed | "**Rejected by agent.**" | as D-03-S13 | AC-017 |
| M-03-S13 Cancellation requested | request accepted | "**Cancellation requested**" | as D-03-S14 | AC-018 |
| M-03-S14 Cancelled | canceled observed | Neutral terminal pill | as D-03-S15 | AC-017 |
| M-03-S15 cancellation unsupported | agent refuses cancel | Last observed state kept | "**Cancellation not supported by this agent.**" | AC-018, FR-013 |
| M-03-S16 Stopped reporting | reporting window elapses | Amber overlay, last contact kept | "**Stopped reporting**" | AC-019, FR-015 |
| M-03-S17 Agent no longer reports this run | task does not exist at the agent | Timeline kept, commands withdrawn | "**Agent no longer reports this run**" | AC-020, FR-013 |
| M-03-S18 content expired | 30-day retention | Marker replaces relayed content | "**Content expired under retention policy**" | SC-007 |
| M-03-S19 Connection disconnected | connection disconnected | Frozen last state, commands withdrawn | "**Connection disconnected**" | AC-022, FR-016 |
| M-03-S20 loading | runs being fetched | Skeleton card after ~250 ms | "Loading runs…" | 007 FR-018 |
| M-03-S21 error | run fetch fails | Category, correlation ID, 44pt retry | "We couldn't load the runs for this task." | SC-009 |
| M-03-S22 offline / interrupted | offline, or app resumed | Cached state stamped "as of", reply and cancel disabled, nothing queued | "Reopening online loads the server projection first." | 007 FR-018 |
| M-03-S23 partial failure | refresh fails over cache | Cached-data banner with correlation ID | as D-03-S24 | 007 FR-018 |
| M-03-S24 compact Task rows | task list rendering | State, guarantee tier in full, cancellation-unsupported, needs-you tint, Tag pill | "Running · Guaranteed single start" | SC-004, FR-013 |
| M-03-S25 empty (filtered to nothing) | Tag view with no runs | No chips, no placeholder | — | FR-013 |
| M-03-S26 Task succession | the agent answers a reply with a different task identifier inside the same conversation | One timeline row, as D-03-S27: the projected state is unchanged by the succession, both task identifiers are kept, the run keeps its single correlation ID, and the reply is never refused | "The agent continued this run in a new task" | FR-010, edge case |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 / M-01 | Add agent | Creates one owner-scoped connection from an agent address plus one credential, after server-verified reauthentication | FR-001, FR-004 |
| D-01 / M-01 | Credential scheme radio (bearer token / API key) | Selects one of exactly two supported schemes; the API-key header name is read from the card, never typed | FR-001 |
| D-01 / M-01 | Test connection | Authenticated call to the agent's task interface; produces ready, invalid credentials, unreachable, rate limited (D-01-S25 / M-01-S22, leaving the connection untested) or one of four unsupported categories, and refreshes the discovery result and the tier | FR-001, FR-002, FR-003 |
| D-01 / M-01 | Edit connection | Renames, or changes the agent address; an address change demands a new successful test and reauthentication before the next content-bearing dispatch | FR-001, FR-004 |
| D-01 / M-01 | Rotate credential | Replaces the sealed credential after reauthentication; the stored value is never displayed | FR-001, AC-023 |
| D-01 / M-01 | Disconnect | Destroys the credential **and, with it, the discovered agent-card summary and its card fingerprint** — the confirmation says so before it happens; stops observation and push registration for that connection's runs, blocks new hand-offs and replies, preserves bounded redacted history | FR-016, AC-022 |
| D-01 / D-02 / D-03 (and M-) | Retry | Re-issues the failed read; every failure carries a category and a correlation ID | SC-009, 007 FR-017 |
| D-02 / M-02 / D-03 / M-03 | Hand to agent | Opens the immutable, versioned review | FR-005 |
| D-02 / M-02 | Agent chooser | Selects one eligible destination; ineligible connections are shown with their reason and cannot be chosen | FR-002, AC-011 |
| D-02 / M-02 | Include task details toggle | Includes or excludes Task details from what leaves | FR-005, AC-008 |
| D-02 / M-02 | Remove (supporting item) | Removes one item from what leaves; rebuilds the manifest so confirmation always matches what was read | FR-005, AC-008 |
| D-02 / M-02 | Cancel | Abandons the review; no task is created at the agent and no run becomes visible | FR-005, AC-008 |
| D-02 / M-02 | Current password | Server-verified reauthentication before the first content-bearing send to a destination, and again after an interface-address change | FR-004, 007 FR-003 |
| D-02 / M-02 | Acknowledge duplicate risk (best-effort, first hand-off only) | One-time per connection. Until it is ticked, **Send to agent** is disabled; once recorded, later hand-offs on that connection show the disclosure without the control | FR-003, AC-026 |
| D-01 / M-01 / D-02 / M-02 | Read the single-start extension specification | Opens the published extension specification, on explicit user action only, marked as leaving BrainBuddy, so the owner knows what to ask their agent operator to declare | FR-003, FR-011 |
| D-02 / M-02 | Send to agent | Confirms the manifest by token; reserves run ID, message ID and correlation ID before anything is sent; a replay returns the same run. Disabled on a best-effort connection until the one-time acknowledgement is recorded | FR-005, FR-006, AC-026 |
| D-03 / M-03 | Send answer | One follow-up message in the same conversation and task with a stable command ID; shown unconfirmed until acknowledged | FR-010, AC-015 |
| D-03 / M-03 | Request cancellation | One cancel request with a stable command ID; shows **Cancellation requested** until an observation says cancelled, or states the refusal | FR-010, AC-018 |
| D-03 / M-03 | Try this hand-off again (on **Not sent**, both variants) | Reopens the review (never dispatches directly) so the same run ID and message ID can be retried after a rate limit, or after a restart settled a still-queued hand-off as not sent | FR-005, FR-006, rate-limit and restart edge cases |
| D-03 / M-03 | Check again (on **Delivery unconfirmed**) | Replays the same confirmation with the same correlation ID and the same message ID: look the run up at the agent, adopt an existing task, and send the identical message again only when the lookup comes back empty. It cannot become a second hand-off and cannot mint a new run | FR-006, ambiguous-dispatch edge case |
| D-03 / M-03 | Copy link (on an agent-reported address) | Copies the address to the clipboard. The address itself is inert text — not an anchor, never opened, never fetched, whatever its scheme — so nothing leaves BrainBuddy on render | 007 FR-014, AC-016 |
| D-03 / M-03 | Mark this task complete | Host-product Task command, drawn only to show that an agent report never completes the Task | AC-016, 007 FR-012 |

### Requirements with no affordance

- **FR-007 (background reply window), FR-008 (observation scheduling, version
  monotonicity, push verification), FR-015 (last-contact definition)** — server contracts
  with no control of their own. Their effects are visible as D-03-S04 (including its
  queued variant), D-03-S17 and D-03-S18; the user never invokes the rule. Push
  acceleration adds no state of its own: it makes the ordinary observation row arrive
  sooner.
- **FR-006** — mostly a server contract (identifier reservation, lookup before resend),
  and it *is* what D-03-S03/S04/S05 render. Since review campaign 1 it has one affordance:
  **Check again** on D-03-S05 / M-03-S04 makes the lookup-before-resend path reachable from
  the run view with the original identifiers, so the documented replay is something a user
  can actually trigger instead of a mechanism only the client ever fired.
- **FR-009** — a projection, not a control. Every label on D-03 and M-03 derives from it.
- **FR-011** — the extension itself is a published specification, not a screen. It now
  has one affordance: the best-effort disclosure links to it (D-01-S11, M-01-S01,
  D-02-S02, M-02-S02). Its other user-visible consequence remains the guarantee tier.
- **FR-012** — removal of the bespoke wire is invisible except as D-01-S21 / M-01-S19.
- **FR-014** — a copy rule, satisfied by the strings in every table above.
- **FR-016** — rendering, retention, correlation IDs, logs, interruption and rollout-OFF
  are cross-cutting rules; they constrain the affordances above rather than adding any.
- **FR-010's task-succession clause** — D-03-S27 / M-03-S26 are a timeline row, not a
  control. Adoption of a successor task is automatic; the user neither approves nor
  refuses it, and the reply control is not withdrawn because of it.
- **FR-017** — conformance checks against the a2a-sdk sample agent and the Hermes A2A
  plugin run in CI, plus one approval-gated attended live run. No UI, by design.

**Resolved at the 2026-09-03 sign-off.** The earlier finding — that a best-effort user
had no route from the product to the published extension specification — is closed:
FR-003 now requires the link, it opens only on explicit user action, and it is marked as
an external destination. The plan stage owns the destination itself; the design shows it
as the repository documentation path and must not be shipped pointing at a placeholder.

### Affordances with no requirement

- None. Navigation, back, close and the Task checkbox are host-product behavior, not
  feature scope; the checkbox is drawn only to make AC-016's "leaves Task completion
  under user control" legible.

## Primary loop impact

**No impact.** This feature does not touch capture → atomic items → clarify/approve →
route or CRT candidate → smart Weekly Review → evidence/results. It begins only after a
canonical Task already exists, and it adds one optional evidence lane beside that Task.
Nothing here creates, clarifies, approves, routes or completes a Task; the four open GTD
primary lists are unchanged, Weekly Review stays visibly deferred, and an agent report is
never authoritative Task completion (D-03-S11, M-03-S10 both say so on the surface). This
matches `spec.md` line 19, which declares the same thing.

## Mobile viability

- **Viewport**: verified at 390×851 across `M-01`, `M-02`, `M-03`. No horizontal scroll:
  yes. Long values that could force one — the agent address, the interface address, the
  Task and run IDs — wrap on word boundaries or break inside the token.
- **Scrolling**: `M-01-S01`, `M-01-S10 – S16`, `M-02-S01/S02/S07/S10` and every `M-03`
  run frame scroll vertically, including the new `M-03-S26` succession frame, whose
  timeline is the longest on the screen. `M-01-S22` needs no scroll: one card, its
  retry-after line and the three 44pt actions fit the 390×851 frame with room left,
  verified by rendering. In `M-02` the sheet is bounded by the frame: the
  manifest and the disclosures scroll in a body between a fixed header and a pinned
  actions footer, so **Send to agent** and **Cancel** are on screen at every scroll
  position and the consent action can never be scrolled off. The push callback address is
  one more line inside the scrolling body and displaces nothing. Verified by rendering at
  390×851 — before this was structured, the manifest overran the frame and the actions
  were not reachable at all. In the static mockup a frame whose defining content sits
  further down (`M-02-S02`, `M-02-S12 – S14`) is drawn part-scrolled, faded at both edges,
  so the tier block and the acknowledgement row are visible; the header and footer are
  fixed in every frame.
- **Tap targets**: 44pt minimum honored. Every action in a sheet is a 44pt-tall row;
  connection-card actions wrap two-up rather than shrinking; the answer field is 56px.
  **Check again** on `M-03-S04` and **Copy link** on `M-03-S10` are both full 44pt rows.
  The one exception to review: the inline **Remove** control on a supporting item is a
  text button inside a list row — it meets 44pt only because its row is padded to 44pt.
- **One-handed reach**: primary actions sit at the bottom of every sheet. Destructive
  **Disconnect** is placed below the safe "Keep it connected" option so the thumb rests
  on the safe one. `M-01-S21`'s mockup was reordered in the campaign-1 amendment to match
  this sentence; the desktop dialog `D-01-S23` already reads safe-then-destructive
  left-to-right, so both surfaces now put the safe choice first.
- **Destructive actions**: the disconnect sheet says the stored credential is destroyed
  together with the discovered agent-card summary and its fingerprint, observation and
  push registration stop, new hand-offs and replies are refused, active runs become
  **Connection disconnected**, and — explicitly — that work the agent already accepted is
  *not* cancelled. Redacted history survives until it expires.
- **Interruption**: `M-02-S10` and `M-03-S22` state the ADR-0002-style rule this feature
  inherits from 007 FR-018 — reopening loads the server projection, offline clients label
  cached state as potentially stale and disable reply and cancel rather than queue them.

## Keyboard and focus

- **Tab order**: heading → connection or run content → primary action → secondary →
  destructive. In `D-02`, the agent chooser precedes the manifest, which precedes the
  disclosures, which precede Cancel and Send to agent.
- **Focus on open**: the dialog or sheet heading, or the first required field.
  **Focus restored on close to**: the control that opened it (Hand to agent, Disconnect…,
  Rotate credential) — on every close path, including Escape, the cancel action and a
  completed submission.
- **Focus containment**: every dialog and every sheet traps focus. Tab and Shift+Tab
  cycle only among the controls inside the open surface and wrap at its boundary — the
  page behind it is never reachable while it is open. The two controls that form the wrap
  boundary are the first focusable control in the surface (the close control on `D-02`;
  the sheet's own heading-adjacent close on `M-02`) and its last action (**Send to agent**
  on `D-02`/`M-02`; **Disconnect** on the `D-01`/`M-01` disconnect confirmation; **Rotate
  credential** on `D-01-S24`). Nothing outside the surface takes focus until it closes.
- **Escape**: closes a non-destructive dialog or sheet without submitting and without
  minting a new intent key, and focus returns to the control that invoked it. A
  destructive confirmation (`D-01-S23`, `M-01-S21`) is dismissed by its own **Keep it
  connected** action rather than by Escape alone, so a stray key cannot be read as a
  decision. While a confirmation is in flight (`D-02-S12`, `M-02-S11`) the surface is not
  dismissible at all, so an interrupted confirmation cannot silently become a second one.
- **Accessible names**: each **Remove** control is named for its item
  (`Remove Staging rehearsal notes`); the close control is `Close the review`; the answer
  field is labelled `Your answer`. There are no icon-only controls without a text label.
- **State communicated by color alone**: none. Every state carries its own words —
  `Tested ready`, `Stale`, `Needs you`, `Stopped reporting`, `Agent no longer reports
  this run`, `Best-effort single start`. The amber row tint on a needs-you Task row
  duplicates a chip that already says "Needs you".
- **Disabled controls**: never dimming alone, and never dimming alone on one platform
  only. Every disabled control in the mockups carries `aria-disabled="true"`, which is
  what drives the 45% opacity; the dimming is the consequence, not the signal. Web ships
  it as a real disabled `<button>`, iOS as a `Pressable` carrying the equivalent disabled
  accessibility state. The controls this covers are the offline actions on `D-01-S07` /
  `M-01-S07`, rollout-OFF on `D-01-S22`, the acknowledgement gate on `D-02-S13` /
  `M-02-S12`, the in-flight confirmation on `D-02-S12` / `M-02-S11`, the offline send on
  `D-02-S10` / `M-02-S10`, and offline reply and cancel on `D-03-S25` / `M-03-S22`.
  `M-01-S20` states the rollout-OFF restriction in copy and draws no control to disable.

## Design authority

- Tokens, colors, type, radii, shadows and easing come from the `brain-buddy-design`
  skill (`colors_and_type.css`): sky-500 brand, slate neutrals, flat `#F8FAFC` surface,
  emerald for agent-run frames, amber for needs-you, rose for failures and destructive
  actions, 10px uppercase section labels as the only uppercase, sentence case everywhere,
  no emoji, no gradients, no imagery.
- GTD contract preserved in every shell: exactly four open primary lists — Inbox (sky
  pill count), Next actions, Waiting for, Someday / maybe — with Projects and Tags as
  secondary organization and `Weekly Review · coming later` non-interactive.
- Tags render as neutral pills with plain names (`deep-work`, `calls`, `errands`), no
  retired prefixes.
- Vocabulary check (ADR-0006, `Tag`): **pass** — a case-insensitive grep for the
  retired taxonomy noun and its at-prefixed form over `design.md` and `design/`
  returns nothing. This grep is a **recorded manual check, not a CI gate**: no job in
  `.github/workflows` and no script in `scripts/` reads this feature directory, so the
  guarantee is only as fresh as the last time someone ran it. Re-run after the
  campaign-2 amendment: still nothing.
- Self-contained check: **pass** — no `<script>`, no `@import`, no `<link>`, no CDN and
  no external font in any of the six files.
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: **pass**
  (6 tests, OK), re-run after the campaign-2 amendment. This design changes no skill
  artifact. That module is the only mechanical check in play, and it asserts the
  **design-skill contract** — it reads `.claude/skills/brain-buddy-design/` and takes no
  feature directory. There is no `scripts/validate_brain_buddy_design_skill.py` in the
  repository. So: unit-tested skill contract, plus the recorded grep above for this
  feature's own vocabulary. Nothing here hard-fails a build.

## Open decisions for the human

The first four were resolved by Max on 2026-09-03 and encoded in `spec.md` (commit
`9afdcaf`: FR-002, FR-003, FR-014, AC-026 and the Clarifications session); the fifth and
sixth were decided on 2026-09-04. Kept here as the record of what was decided, not as
open questions. **No product decision is outstanding.** The one thing still owed to a
person is inside item 3 and is not a product question: the extension specification's real
published location, which the plan stage must bind before rollout.

1. **Best-effort admission loudness — decided: acknowledge, once.** A warning alone was
   not enough. The first hand-off on a best-effort connection now requires an explicit
   acknowledgement that a duplicate task is possible before confirmation is enabled;
   later hand-offs on that connection show the disclosure without it. Drawn as
   D-02-S13 – S15 and M-02-S12 – S14, per FR-003 and AC-026.
2. **The vocabulary substitution — decided: accepted.** "Supporting items" and
   "Correlation ID" stand, and `spec.md` now uses them too. The two underlying A2A wire
   field names stay in technical artifacts and never reach a client-facing response;
   spec.md Assumptions names them, this design deliberately does not.
3. **FR-011's missing route — decided: add the link.** The best-effort disclosure on
   D-01, M-01, D-02 and M-02 links to the published single-start extension
   specification. It opens only on explicit user action and is marked as leaving
   BrainBuddy. **One thing still needs a person**: the design points the link at the
   repository documentation path; the plan stage must bind it to the real published
   location before rollout, and must not ship the placeholder.
4. **"Agent changed" — decided: it is a named condition.** FR-002 now names it and
   FR-014 fixes its wording. A changed connection behaves as untested and cannot take a
   hand-off until a new successful test. D-01-S20 and M-01-S18 carry the updated refs,
   and the ineligible-connection lists (D-02-S05, M-02-S03) now include it.
5. **Result links — decided 2026-09-04: inert.** An address the agent reports is never a
   link. It is shown as inert text beside a **Copy link** control: no anchor, no new tab,
   nothing opened and nothing fetched, and no "safe link" claim to be wrong about. This
   settles what was the second pending product decision on D-03-S11 / M-03-S10; the
   plan stage owns the matching change to AC-016 and to research Decision E's
   `interactive_result_link`, which this design no longer relies on.
6. **Card-metadata retention — decided 2026-09-04: the connection's lifetime.** The
   product owner settled it: a live connection's discovered card summary and its
   `card_fingerprint` are **connection configuration**, retained for as long as the
   connection exists and erased on disconnect together with the credential — never swept
   on a clock. Only audit rows that name the card follow the 90-day identifier bound.
   Design consequence, and the reason this is recorded here rather than left implicit:
   the disconnect confirmation (`D-01-S23`, `M-01-S21`) must *say* the card summary and
   fingerprint go with the credential, which it now does, and the affordance map's
   **Disconnect** row says the same. This was the last thing this file marked as still
   with the human; it is closed.

### Amended after review campaign 1

Decided by Max; re-acknowledged 2026-09-04. Nothing below renumbers an existing id.

| change | ids | why |
|---|---|---|
| **Check again** on delivery-unconfirmed | D-03-S05, M-03-S04 | The documented lookup-before-resend replay had no control anywhere in the UI, so an undelivered hand-off had no route back. The action reuses the same correlation ID and message ID and can never become a second send. |
| **Task succession** state added | D-03-S27, M-03-S26 | The timeline event was specified, schema'd and exercised end to end but had no design id for the acceptance auditor to cite. Appended at the end of each screen's sequence. |
| **Disconnect sheet reordered** | M-01-S21 | The mockup contradicted this file's own thumb-safety sentence. The sentence won. |
| **Focus containment stated** | Keyboard and focus | Dialogs and sheets trap focus, Tab wraps at the boundary, Escape closes non-destructive surfaces, focus returns to the invoking control. |
| **Result addresses made inert** | D-03-S11, M-03-S10, affordance map | Product decision, 2026-09-04. |
| **Result-too-large variant** | D-03-S11, M-03-S10 | An over-cap result must not be rendered as **Stopped reporting**. Row copy only; no new id. |
| **Queued variant on Sent** | D-03-S04, M-03-S03 | A hand-off still waiting for a connection slot has not been sent, so it must not say **Sent**. Row copy and mockup only; no new id. |
| **Push callback disclosed in the manifest** | D-02 and M-02 "what will be sent" | The per-run callback address is registered with the agent as part of the confirmed send, so the consent boundary has to name it. Text only; no new id. |

### Amended after review campaign 2

Applied 2026-09-04 from the campaign-2 findings. **Re-acknowledgement by Max pending.**
Nothing below renumbers an existing id; the two new ids are appended at the end of their
screens' sequences, exactly as `D-03-S27` / `M-03-S26` were in campaign 1.

| change | ids | why |
|---|---|---|
| **Rate-limited connection test added** | D-01-S25, M-01-S22 | SC-009 and the wire contract both name a rate-limited test outcome (`last_test_error_code = a2a_rate_limited`), and FR-002 now does too, but D-01/M-01 enumerated every other test failure and not this one. Follows the D-03-S03 pattern: actionable category, retry-after hint, connection stays untested, **Test connection** still offered. |
| **Restart variant of Not sent** | D-03-S03, M-03-S02 | A hand-off still queued when BrainBuddy restarted provably never left, so it is settled as **Not sent** — "BrainBuddy restarted before this hand-off was sent. Nothing left BrainBuddy." — with the same **Try this hand-off again**, and never labelled **Delivery unconfirmed**. Row copy and mockup only; no new id. |
| **Disconnect names the card erasure** | D-01-S23, M-01-S21, affordance map | The dialog claimed to say "exactly what is destroyed" while omitting the discovered card summary and its fingerprint, which the 2026-09-04 retention decision erases with the credential. Copy only. |
| **Card-retention decision recorded** | Open decisions 6 | This file still called a settled decision open. Replaced with the outcome. |
| **Vocabulary sweep described honestly** | Vocabulary, Design authority | It was written as a CI validator that hard-fails. It is a recorded manual grep plus the unit-tested design-skill contract; no CI job reads this feature directory. |
| **Loading citations corrected** | D-01-S02, M-01-S02, D-03-S02, M-03-S20 | A skeleton shows no correlation ID, so 007 FR-017 was the wrong trace. They cite 007 FR-018 (the client loads the server projection) instead. |
| **Skeleton delay stated once** | State inventory preamble | ~250 ms before a skeleton appears, so a fast response does not flicker. Shared, not repeated per row. |
| **Add-agent navigation stated** | D-01-S08, M-01-S08 | Leaving the form discards it silently: nothing stored, nothing sent, four cheap fields, so no warning. Closes the Principle V draft-loss question rather than leaving it unanswered. |
| **`aria-disabled` parity on iOS** | M-01-S07, M-02-S10, M-02-S11, M-02-S12, M-03-S22 | Disabled controls carried inline opacity alone on mobile while desktop carried the attribute, so the disabled state was invisible to assistive technology on one platform. |
