# Design: A2A relay wire contract

**Feature**: `specs/014-a2a-relay-wire-contract/`
**Spec**: `spec.md` (Clarifications settled: 2026-09-03, session 2026-09-03, zero open markers)
**Screens**: `design/*.html` — six self-contained static files, no script, no external font, no CDN
**Human sign-off**: pending

<!--
  Produced by /speckit-design via the design-architect subagent, after
  /speckit-clarify. Screen ids (D-01…, M-01…) and state ids (D-01-S01…) are
  stable forever: the acceptance traceability matrix keys off them.

  ADR-0006: the term is Tag. "Context" and "@context" are forbidden strings and
  the design CI validator hard-fails on them. See "Vocabulary" below for how the
  spec's wire-level nouns are rendered in the UI.
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
additional run conditions.

### Vocabulary

ADR-0006 makes `Tag` canonical and forbids the retired noun the spec still uses at the
wire level. Two substitutions apply to every surface and every string in `design/`:

| Spec concept | UI label everywhere | Why |
|---|---|---|
| FR-005's optional user-selected extra payload items | **Supporting items** | The forbidden noun cannot appear in product copy. 007's design already used "supporting items". |
| FR-006's third identifier, defined as equal to the run's stable correlation ID | **Correlation ID** | It *is* the correlation ID (007 FR-017), so this is the accurate name, not a euphemism. |

The wire field names stay internal. The plan stage must not surface either spec noun in
API responses that reach the clients, or the validator fails in CI.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| D-01 | desktop | Connected agents | Add by agent address, test, read the discovery result and guarantee tier, rotate, disconnect | FR-001, FR-002, FR-003, FR-004, FR-012, FR-014, FR-016 |
| D-02 | desktop | Hand-off review | The consent boundary: the exact text that leaves, the destination, both disclosures, one confirmation | FR-003, FR-004, FR-005, FR-006, FR-010, FR-014, FR-016 |
| D-03 | desktop | Task agent panel and compact Task rows | Monitor, answer, request cancellation, read the result; every run condition from one projection | FR-006, FR-007, FR-008, FR-009, FR-010, FR-013, FR-014, FR-015, FR-016 |
| M-01 | mobile | Connected agents | The same connection contract at iPhone width, forms as sheets | FR-001, FR-002, FR-003, FR-004, FR-012, FR-014, FR-016 |
| M-02 | mobile | Hand to agent review sheet | The same manifest and both disclosures in a bottom sheet | FR-003, FR-004, FR-005, FR-006, FR-010, FR-014, FR-016 |
| M-03 | mobile | Task agent section and compact Task rows | The same run projection on iOS, label-for-label | FR-006 – FR-010, FR-013 – FR-016 |

Files:

- `design/D-01-connected-agents-desktop.html`
- `design/D-02-handoff-review-desktop.html`
- `design/D-03-task-agent-panel-desktop.html`
- `design/M-01-connected-agents-mobile.html`
- `design/M-02-handoff-review-mobile.html`
- `design/M-03-task-agent-panel-mobile.html`

## State inventory

### D-01 — Connected agents (desktop)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-01-S01 default | one or more saved connections | Name, address, status pill, tier disclosure, credential scheme, last contact, last tested, stale threshold, four actions | "The last test reached this agent and it authenticated." | FR-001, FR-002, FR-003 |
| D-01-S02 loading | first server fetch | Settings frame intact, skeleton rows, "Loading connections…"; never the empty state | "Loading connections…" | 007 FR-017 |
| D-01-S03 empty (first run) | no connection has ever been saved | Display heading, one-line hint, single primary action | "Connect an agent you operate" | FR-001 |
| D-01-S04 empty (filtered to nothing) | — | Deliberately absent: the list has no filter, search or sort. The real case lives on D-02-S05 | "No filter, no search, no sort on this list" | scope boundary, FR-001 |
| D-01-S05 error | list fetch fails | Category, correlation ID, retry; no partial rows invented | "We couldn't load your connections" | SC-009, 007 FR-017 |
| D-01-S06 partial failure | cached list exists, refresh fails | Cached rows stay, each stamped with the time it was read, all labelled potentially stale | "Showing potentially stale saved data." | 007 FR-018 |
| D-01-S07 offline / interrupted | browser reports offline | Saved status visible and stamped; every secret-bearing action disabled; nothing queued | "Offline — reconnect to manage agents." | 007 FR-018 |
| D-01-S08 add agent (bearer) | user opens the add form | Agent name, agent address, scheme radio, credential, password; egress rule stated on the address field | "BrainBuddy fetches the agent card from this address's standard well-known location…" | FR-001, FR-004 |
| D-01-S09 add agent (API key) | user picks the API-key scheme | Read-only header name sourced from the card; before discovery it reads "Read from the agent card when you test" | "Read from the agent card after discovery. You do not type it." | FR-001 |
| D-01-S10 test: ready, guaranteed | test succeeds, card declares the extension | Agent name, version, description, skills, streaming, push, protocol version, interface, then the tier | "**Guaranteed single start.** …a retry cannot start a second run." | AC-001, FR-002, FR-003, FR-011 |
| D-01-S11 test: ready, best-effort | test succeeds, card does not declare it | Same discovery result, best-effort tier, plus the push-not-supported note | "**Best-effort single start.** …A duplicate remains possible if the agent forgets its tasks." | AC-005, FR-003 |
| D-01-S12 test: invalid credentials | agent rejects the credential | Rose pill, corrective action, correlation ID; the submitted secret is never echoed | "The agent answered and rejected the credential. Rotate it below, then test again." | AC-003, FR-002, SC-009 |
| D-01-S13 test: unreachable | transport failure or test timeout | Rose pill, "Nothing was sent", correlation ID | "BrainBuddy could not reach this address before the test timeout." | AC-002, FR-002 |
| D-01-S14 unsupported: not an A2A agent | address answers, no card at the well-known location | Its own sentence and its own corrective action | "There is no agent card at its well-known location." | AC-002, FR-002, SC-009 |
| D-01-S15 unsupported: protocol version | card declares a version outside 1.0.x | Names the version found and the version required | "The card declares A2A 0.9.4. BrainBuddy speaks protocol version 1.0.x only." | AC-002, FR-001 |
| D-01-S16 unsupported: no supported interface | no usable JSON-RPC interface over HTTPS | Also covers a JSON-RPC interface pointing at a refused destination | "No JSON-RPC interface BrainBuddy can use over HTTPS." | AC-002, FR-001, edge case |
| D-01-S17 unsupported: authentication scheme | card offers only OAuth2 or mutual TLS | Names the unsupported scheme, names the two supported ones | "This card requires **OAuth2**. BrainBuddy supports a bearer token or an API key…" | AC-004, FR-001 |
| D-01-S18 private destination refused | loopback, link-local, metadata or private address | Refusal before any credential or content leaves | "Nothing left BrainBuddy." | AC-006, FR-004, 007 FR-004 |
| D-01-S19 stale | last contact older than the threshold | Amber pill overriding an earlier ready; hand-off blocked | "Test it again before a hand-off." | FR-002 |
| D-01-S20 agent changed | card fingerprint drift on interface address or authentication | Tested interface and current card interface shown side by side; new test plus reauthentication demanded | "BrainBuddy will not send task content to a destination you have not tested." | AC-012, FR-004 |
| D-01-S21 disconnected: superseded wire | a pre-existing bespoke connection record | Neutral disconnected pill with the reason; no path to reuse it | "Superseded wire contract." | FR-012, SC-010 |
| D-01-S22 rollout OFF | deployment flag off | Add, edit, test and rotate unavailable; disconnect still available; runs keep reporting | "The external-agent relay rollout is off." | FR-016, 007 FR-019 |
| D-01-S23 disconnect confirmation | user chooses Disconnect | Names what is destroyed, what stops, and what is *not* cancelled; password required | "Disconnecting does not cancel work the agent already accepted." | AC-022, FR-016 |
| D-01-S24 rotate credential | user chooses Rotate credential | No current value shown; new credential plus password | "BrainBuddy cannot show you the current one." | FR-001, AC-023 |

### D-02 — Hand-off review (desktop)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-02-S01 default (guaranteed) | user picks a ready connection | Agent chooser, Task title, optional details toggle, removable supporting items, Task ID, run ID, correlation ID, destination, tier, cancellation disclosure, external-copy notice | "What will be sent" | AC-007, FR-005, SC-005 |
| D-02-S02 review (best-effort) | the chosen agent lacks the extension | Same manifest, amber tier block restating the duplicate risk and the mitigation | "**Best-effort single start.**" | FR-003, AC-005 |
| D-02-S03 loading | preview being built server-side | Skeleton manifest, explicit "no task content has been sent" | "Building the hand-off preview…" | FR-005 |
| D-02-S04 empty (first run) | account has no connection | Explanation plus a route to Connected agents | "No agents connected yet" | FR-001 |
| D-02-S05 empty (filtered to nothing) | connections exist, none eligible | Every ineligible connection listed with *why* and its corrective action | "None of your agents can take this hand-off" | AC-011, FR-002 |
| D-02-S06 error | preview request fails | Category, correlation ID, retry; nothing was sent | "We couldn't build this hand-off" | SC-009 |
| D-02-S07 partial failure | one connection's status could not be refreshed | That row is shown, marked "Status unknown", and is **not** selectable | "Could not be refreshed just now, so it is not offered." | FR-002 (fail closed) |
| D-02-S08 re-review required | manifest token no longer matches | Warning above a rebuilt manifest; the earlier confirmation was not used | "What would be sent has changed. Review it again before confirming." | FR-005 |
| D-02-S09 refused: agent changed | card drift detected at confirm time | Refusal before content leaves, with the reauthentication warning | "Its card now advertises a different interface address…" | AC-012, FR-004 |
| D-02-S10 offline / interrupted | no network | Manifest stays readable, send disabled, nothing queued; reopening rebuilds from the server | "Sending is unavailable and nothing is queued." | 007 FR-018 |
| D-02-S11 reauthentication required | first content-bearing send to this destination | Password field with the reason stated | "…so BrainBuddy re-checks your password." | FR-004, 007 FR-003 |
| D-02-S12 sending | confirmation in flight | Disabled primary, replay explanation | "Confirming again while this is in flight returns the same run." | AC-010, SC-002, SC-008 |

### D-03 — Task agent panel and compact Task rows (desktop)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| D-03-S01 default | Task has never been handed over | Only "Hand to agent". No empty run heading | "Hand to agent" | FR-005 |
| D-03-S02 loading | runs being fetched | Heading plus skeleton run card | "Loading runs…" | 007 FR-017 |
| D-03-S03 Not sent (rate limited) | agent rate-limits before creating a task | Rose card, actionable category, retry that reuses the same run and message IDs | "The agent is rate limiting." | FR-006, edge case |
| D-03-S04 Sent | dispatch accepted, no agent state yet | Sky pill, waiting explained, no fabricated progress | "Some agents answer only when the work is finished." | AC-014, FR-006, FR-007, SC-006 |
| D-03-S05 Delivery unconfirmed | ambiguous or timed-out dispatch | Amber pill, no resend, lookup-before-resend explained | "**Delivery unconfirmed** … It was not re-sent." | FR-006, edge case |
| D-03-S06 Accepted | submitted observed | Sky pill, timeline entry | "Accepted" | FR-009 |
| D-03-S07 Running | working observed | Sky pill plus the agent's own status text, attributed | "Running" | AC-013, FR-009 |
| D-03-S08 blocked with a question | input-required observed | Amber card, the agent's question, a reply box and Send answer | "Needs you" | FR-009, FR-010 |
| D-03-S09 reply unconfirmed | reply sent, not acknowledged | The answer shown as sent-not-acknowledged; state does not advance | "Your answer was sent but the agent has not acknowledged it yet." | AC-015, FR-010 |
| D-03-S10 blocked, needs authentication | auth-required observed | Amber card, no reply control at all | "Agent needs additional authentication." | FR-009 |
| D-03-S11 Agent reported complete | completed observed, or a direct message answer | Inert text, non-text artifacts as placeholders naming the content type, safe HTTPS link clickable, unsafe link left as plain text, Task still open | "**Agent reported complete**" · "This is what the agent said it did. The task is still open — completing it is your call." | AC-016, FR-009, 007 FR-012, FR-014 |
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

### M-01 — Connected agents (iOS, 390×851)

Same semantics as D-01, state for state. Frames in `design/M-01-connected-agents-mobile.html`.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-01-S01 default | saved connections exist | Cards at 14px radius; tier under the status line; actions wrap two-up at 44pt | as D-01-S01 | FR-001 – FR-003 |
| M-01-S02 loading | first fetch | Skeleton cards | "Loading connections…" | 007 FR-017 |
| M-01-S03 empty (first run) | none saved | 24px display heading, hint, one primary action | "Connect an agent you operate" | FR-001 |
| M-01-S04 empty (filtered to nothing) | — | Deliberately absent, points at M-02-S03 | "No filter, no search, no sort" | scope boundary |
| M-01-S05 error | fetch fails | Category, correlation ID, 44pt retry | "We couldn't load your connections" | SC-009 |
| M-01-S06 partial failure | refresh fails over cache | "As of 21:58" stamp on every row | "Showing potentially stale saved data." | 007 FR-018 |
| M-01-S07 offline / interrupted | device offline, app resumed | Stamped cache, disabled actions, nothing queued; resume loads the server projection | "Reopening the app loads the server projection…" | 007 FR-018 |
| M-01-S08 add agent sheet | user taps Add an agent | Sheet with address, scheme radios, credential, password; egress rule inline | as D-01-S08 | FR-001, FR-004 |
| M-01-S09 discovery result | test succeeds | Card metadata as a two-column list plus skill pills plus tier | as D-01-S10 | AC-001, FR-003 |
| M-01-S10 invalid credentials | credential rejected | One sentence, correlation ID stub | as D-01-S12 | AC-003 |
| M-01-S11 unreachable | transport failure or timeout | One sentence, correlation ID stub | as D-01-S13 | AC-002 |
| M-01-S12 not an A2A agent | no card at the well-known location | One sentence | as D-01-S14 | AC-002 |
| M-01-S13 unsupported protocol version | version outside 1.0.x | One sentence naming both versions | as D-01-S15 | AC-002 |
| M-01-S14 no supported interface | no usable JSON-RPC over HTTPS | One sentence | as D-01-S16 | AC-002 |
| M-01-S15 unsupported authentication scheme | OAuth2 or mutual TLS only | Names both | as D-01-S17 | AC-004 |
| M-01-S16 private destination refused | refused network class | "Nothing left BrainBuddy." | as D-01-S18 | AC-006 |
| M-01-S17 stale | threshold exceeded | Amber pill | as D-01-S19 | FR-002 |
| M-01-S18 agent changed | card drift | New test plus password demanded | as D-01-S20 | AC-012 |
| M-01-S19 superseded wire contract | pre-existing bespoke record | Neutral disconnected pill with the reason | as D-01-S21 | FR-012, SC-010 |
| M-01-S20 rollout OFF | flag off | Amber notice; disconnect still available | as D-01-S22 | FR-016 |
| M-01-S21 disconnect sheet | user taps Disconnect | Destructive sheet, password, destructive action *below* the safe one | as D-01-S23 | AC-022 |

### M-02 — Hand to agent review sheet (iOS, 390×851)

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-02-S01 default (guaranteed) | ready connection chosen | Scrolling sheet; Send and Cancel pinned at the bottom in thumb reach | as D-02-S01 | AC-007, FR-005, SC-005 |
| M-02-S02 review (best-effort) | agent lacks the extension | Amber tier block | "**Best-effort single start.**" | FR-003 |
| M-02-S03 empty (filtered to nothing) | connections exist, none eligible | Each ineligible connection with its reason | "None of your agents can take this hand-off" | AC-011 |
| M-02-S04 empty (first run) | no connection at all | Route to Connected agents | "No agents connected yet" | FR-001 |
| M-02-S05 loading | preview being built | Skeleton, "No task content has been sent." | "Building the hand-off preview…" | FR-005 |
| M-02-S06 error | preview fails | Category, correlation ID, retry | "We couldn't build this hand-off" | SC-009 |
| M-02-S07 re-review required | manifest token stale | Warning above a rebuilt sheet | "What would be sent changed since you reviewed it." | FR-005 |
| M-02-S08 partial failure | one connection unrefreshable | Marked "Status unknown", not selectable | as D-02-S07 | FR-002 |
| M-02-S09 reauthentication required | first send to this destination | Password field with the reason | as D-02-S11 | FR-004 |
| M-02-S10 offline / interrupted | no network, or the app is closed mid-review | Send disabled, nothing queued; resume rebuilds from the server | "…reopening loads the server projection and rebuilds this review before anything can leave." | 007 FR-018 |
| M-02-S11 sending | confirmation in flight | Sheet not swipe-dismissible while in flight; replay explained | "Confirming again while this is in flight returns the same run." | AC-010, SC-008 |

### M-03 — Task agent section and compact Task rows (iOS, 390×851)

Every D-03 run condition, label for label, from the same server projection.

| state | trigger | what the user sees | copy | FR/SC refs |
|---|---|---|---|---|
| M-03-S01 default | Task with no run | Only "Hand to agent"; no run section | "Hand to agent" | FR-005 |
| M-03-S02 Not sent (rate limited) | agent rate-limits | Rose card, category, same-IDs retry note | as D-03-S03 | FR-006 |
| M-03-S03 Sent | dispatch accepted | Sky pill, waiting explained | as D-03-S04 | AC-014, SC-006 |
| M-03-S04 Delivery unconfirmed | ambiguous dispatch | Amber pill, lookup-before-resend | "**Delivery unconfirmed**" | FR-006 |
| M-03-S05 Accepted | submitted observed | Sky pill | as D-03-S06 | FR-009 |
| M-03-S06 Running | working observed | Sky pill plus attributed status text; 44pt cancel | as D-03-S07 | AC-013 |
| M-03-S07 blocked with a question | input-required | Question, 56px answer field, 44pt Send answer | "Needs you" | FR-010 |
| M-03-S08 reply unconfirmed | reply not acknowledged | Sent-not-acknowledged line | as D-03-S09 | AC-015 |
| M-03-S09 blocked, needs authentication | auth-required | No reply box at all | "Agent needs additional authentication." | FR-009 |
| M-03-S10 Agent reported complete | completed observed | Inert text, artifact placeholders naming the content type, safe HTTPS link, Task still open | "**Agent reported complete**" | AC-016, FR-014 |
| M-03-S11 Failed with reason | failed observed | Rose card, the agent's reason | as D-03-S12 | AC-017 |
| M-03-S12 Failed — rejected | rejected observed | "**Rejected by agent.**" | as D-03-S13 | AC-017 |
| M-03-S13 Cancellation requested | request accepted | "**Cancellation requested**" | as D-03-S14 | AC-018 |
| M-03-S14 Cancelled | canceled observed | Neutral terminal pill | as D-03-S15 | AC-017 |
| M-03-S15 cancellation unsupported | agent refuses cancel | Last observed state kept | "**Cancellation not supported by this agent.**" | AC-018, FR-013 |
| M-03-S16 Stopped reporting | reporting window elapses | Amber overlay, last contact kept | "**Stopped reporting**" | AC-019, FR-015 |
| M-03-S17 Agent no longer reports this run | task does not exist at the agent | Timeline kept, commands withdrawn | "**Agent no longer reports this run**" | AC-020, FR-013 |
| M-03-S18 content expired | 30-day retention | Marker replaces relayed content | "**Content expired under retention policy**" | SC-007 |
| M-03-S19 Connection disconnected | connection disconnected | Frozen last state, commands withdrawn | "**Connection disconnected**" | AC-022, FR-016 |
| M-03-S20 loading | runs being fetched | Skeleton card | "Loading runs…" | 007 FR-017 |
| M-03-S21 error | run fetch fails | Category, correlation ID, 44pt retry | "We couldn't load the runs for this task." | SC-009 |
| M-03-S22 offline / interrupted | offline, or app resumed | Cached state stamped "as of", reply and cancel disabled, nothing queued | "Reopening online loads the server projection first." | 007 FR-018 |
| M-03-S23 partial failure | refresh fails over cache | Cached-data banner with correlation ID | as D-03-S24 | 007 FR-018 |
| M-03-S24 compact Task rows | task list rendering | State, guarantee tier in full, cancellation-unsupported, needs-you tint, Tag pill | "Running · Guaranteed single start" | SC-004, FR-013 |
| M-03-S25 empty (filtered to nothing) | Tag view with no runs | No chips, no placeholder | — | FR-013 |

## Affordance → requirement map

| screen | affordance | what it does | FR ref |
|---|---|---|---|
| D-01 / M-01 | Add agent | Creates one owner-scoped connection from an agent address plus one credential, after server-verified reauthentication | FR-001, FR-004 |
| D-01 / M-01 | Credential scheme radio (bearer token / API key) | Selects one of exactly two supported schemes; the API-key header name is read from the card, never typed | FR-001 |
| D-01 / M-01 | Test connection | Authenticated call to the agent's task interface; produces ready, invalid credentials, unreachable or one of four unsupported categories, and refreshes the discovery result and the tier | FR-001, FR-002, FR-003 |
| D-01 / M-01 | Edit connection | Renames, or changes the agent address; an address change demands a new successful test and reauthentication before the next content-bearing dispatch | FR-001, FR-004 |
| D-01 / M-01 | Rotate credential | Replaces the sealed credential after reauthentication; the stored value is never displayed | FR-001, AC-023 |
| D-01 / M-01 | Disconnect | Destroys the credential, stops observation and push registration for that connection's runs, blocks new hand-offs and replies, preserves bounded redacted history | FR-016, AC-022 |
| D-01 / D-02 / D-03 (and M-) | Retry | Re-issues the failed read; every failure carries a category and a correlation ID | SC-009, 007 FR-017 |
| D-02 / M-02 / D-03 / M-03 | Hand to agent | Opens the immutable, versioned review | FR-005 |
| D-02 / M-02 | Agent chooser | Selects one eligible destination; ineligible connections are shown with their reason and cannot be chosen | FR-002, AC-011 |
| D-02 / M-02 | Include task details toggle | Includes or excludes Task details from what leaves | FR-005, AC-008 |
| D-02 / M-02 | Remove (supporting item) | Removes one item from what leaves; rebuilds the manifest so confirmation always matches what was read | FR-005, AC-008 |
| D-02 / M-02 | Cancel | Abandons the review; no task is created at the agent and no run becomes visible | FR-005, AC-008 |
| D-02 / M-02 | Current password | Server-verified reauthentication before the first content-bearing send to a destination, and again after an interface-address change | FR-004, 007 FR-003 |
| D-02 / M-02 | Send to agent | Confirms the manifest by token; reserves run ID, message ID and correlation ID before anything is sent; a replay returns the same run | FR-005, FR-006 |
| D-03 / M-03 | Send answer | One follow-up message in the same conversation and task with a stable command ID; shown unconfirmed until acknowledged | FR-010, AC-015 |
| D-03 / M-03 | Request cancellation | One cancel request with a stable command ID; shows **Cancellation requested** until an observation says cancelled, or states the refusal | FR-010, AC-018 |
| D-03 / M-03 | Try this hand-off again (on **Not sent**) | Reopens the review (never dispatches directly) so the same run ID and message ID can be retried after a rate limit | FR-005, FR-006, rate-limit edge case |
| D-03 / M-03 | Result HTTPS link | Opens a safe HTTPS destination in a new tab, labelled as leaving BrainBuddy; an unsafe destination stays plain text | 007 FR-014 |
| D-03 / M-03 | Mark this task complete | Host-product Task command, drawn only to show that an agent report never completes the Task | AC-016, 007 FR-012 |

### Requirements with no affordance

- **FR-006 (identifier reservation), FR-007 (background reply window), FR-008
  (observation scheduling, version monotonicity, push verification), FR-015 (last-contact
  definition)** — server contracts with no control of their own. Their effects are
  visible as D-03-S03/S04/S05, D-03-S17 and D-03-S18; the user never invokes the rule.
- **FR-009** — a projection, not a control. Every label on D-03 and M-03 derives from it.
- **FR-011** — the extension is a published specification, not a screen. Its only
  user-visible consequence is the guarantee tier. **See the gap below.**
- **FR-012** — removal of the bespoke wire is invisible except as D-01-S21 / M-01-S19.
- **FR-014** — a copy rule, satisfied by the strings in every table above.
- **FR-016** — rendering, retention, correlation IDs, logs, interruption and rollout-OFF
  are cross-cutting rules; they constrain the affordances above rather than adding any.
- **FR-017** — conformance checks against the a2a-sdk sample agent and the Hermes A2A
  plugin run in CI, plus one approval-gated attended live run. No UI, by design.

**Gap — FR-011 has no route from the product to the published specification.** FR-011
requires BrainBuddy to publish the single-start extension under a public, stable
identifier so any third-party agent can declare it. A user on **Best-effort single
start** therefore has no way, from the product, to learn what to ask their agent
operator for. The obvious fix is a link from the best-effort disclosure to the published
specification, but the spec does not require a link and I will not invent an outbound
destination or a doc URL. Recorded for the plan stage to resolve.

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
  run frame scroll vertically. In `M-02` the manifest scrolls inside the sheet while
  **Send to agent** and **Cancel** stay pinned to the bottom, so the consent action is
  never scrolled off.
- **Tap targets**: 44pt minimum honored. Every action in a sheet is a 44pt-tall row;
  connection-card actions wrap two-up rather than shrinking; the answer field is 56px.
  The one exception to review: the inline **Remove** control on a supporting item is a
  text button inside a list row — it meets 44pt only because its row is padded to 44pt.
- **One-handed reach**: primary actions sit at the bottom of every sheet. Destructive
  **Disconnect** is placed below the safe "Keep it connected" option so the thumb rests
  on the safe one.
- **Destructive actions**: the disconnect sheet says the stored credential is destroyed,
  observation and push registration stop, new hand-offs and replies are refused, active
  runs become **Connection disconnected**, and — explicitly — that work the agent already
  accepted is *not* cancelled. Redacted history survives until it expires.
- **Interruption**: `M-02-S10` and `M-03-S22` state the ADR-0002-style rule this feature
  inherits from 007 FR-018 — reopening loads the server projection, offline clients label
  cached state as potentially stale and disable reply and cancel rather than queue them.

## Keyboard and focus

- **Tab order**: heading → connection or run content → primary action → secondary →
  destructive. In `D-02`, the agent chooser precedes the manifest, which precedes the
  disclosures, which precede Cancel and Send to agent.
- **Focus on open**: the dialog or sheet heading, or the first required field.
  **Focus restored on close to**: the control that opened it (Hand to agent, Disconnect…,
  Rotate credential).
- **Escape**: closes a non-pending dialog without submitting and without minting a new
  intent key. While a confirmation is in flight (`D-02-S12`, `M-02-S11`) the surface is
  not dismissible, so an interrupted confirmation cannot silently become a second one.
- **Accessible names**: each **Remove** control is named for its item
  (`Remove Staging rehearsal notes`); the close control is `Close the review`; the answer
  field is labelled `Your answer`. There are no icon-only controls without a text label.
- **State communicated by color alone**: none. Every state carries its own words —
  `Tested ready`, `Stale`, `Needs you`, `Stopped reporting`, `Agent no longer reports
  this run`, `Best-effort single start`. The amber row tint on a needs-you Task row
  duplicates a chip that already says "Needs you".

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
- Vocabulary check (ADR-0006, `Tag`): **pass** —
  `grep -rn -i "context" design.md design/` returns nothing.
- Self-contained check: **pass** — no `<script>`, no `@import`, no `<link>`, no CDN and
  no external font in any of the six files.
- `python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py`: **pass**
  (7 tests, OK). This design changes no skill artifact.

## Open decisions for the human

1. **The best-effort tier is offerable at all, and only warns.** A best-effort agent can
   produce a duplicate task. This design admits it with an amber disclosure in two places
   (D-01-S11, D-02-S02) rather than a blocking confirmation. That follows the
   2026-09-03 clarification, but the loudness is a product call: warn, or make the first
   best-effort hand-off require an explicit "I accept a possible duplicate" checkbox?
2. **The vocabulary substitution.** ADR-0006 forbids the noun `spec.md` uses for the
   optional payload items and for the third wire identifier. The UI says **Supporting
   items** and **Correlation ID** instead. Confirm this, and confirm the plan keeps the
   wire field names off every client-facing response — the CI validator is unforgiving.
3. **FR-011 has no route from a best-effort connection to the published extension
   specification** (see "Requirements with no affordance"). Either add a link and accept
   an outbound destination in settings copy, or accept that upgrading to guaranteed is
   out-of-product knowledge.
4. **"Agent changed" is a fifth connection condition that FR-002 does not name.** FR-002
   defines four test outcomes; AC-012 and FR-004 imply a distinct card-drift condition
   that blocks hand-off without being a failed test. D-01-S20 / M-01-S18 draw it as its
   own amber state. Confirm that reading, or fold drift into `stale`.
