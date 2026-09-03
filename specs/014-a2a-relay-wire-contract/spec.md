# Feature Specification: A2A Relay Wire Contract

**Feature Branch**: `014-a2a-relay-wire-contract`

**Created**: 2026-09-03

**Status**: Draft

**Input**: User description: "Hand off a BrainBuddy task to any user-operated agent that speaks the open Agent2Agent (A2A) v1.0 protocol, replacing the bespoke relay envelope no agent implements, while keeping every consent, security, honesty and retention guarantee of feature 007"

## Relationship to feature 007

Feature 007 (`specs/007-external-agent-relay/`) ratified a bring-your-own-agent relay whose connector envelope is BrainBuddy-specific. No agent implements that envelope, so the provider-agnostic promise of 007 is unfulfilled and zero agents are reachable. This feature replaces **only the wire contract** between BrainBuddy and the agent with the Linux Foundation Agent2Agent protocol, version 1.0.x, and removes the bespoke envelope entirely.

Everything in 007 that does not describe the bespoke wire remains binding and is referenced here rather than restated: the product boundary (BrainBuddy owns faithful dispatch and honest display, never execution), the hand-off consent review (007 FR-005), server-verified reauthentication for sensitive operations (007 FR-003), egress safety (007 FR-004), honest copy (007 FR-011), no mutation of the canonical Task (007 FR-012), the silence rule (007 FR-013), inert rendering of agent content (007 FR-014), retention (007 FR-015), disconnect (007 FR-016), correlation IDs (007 FR-017), interruption and offline behavior (007 FR-018) and rollout-OFF semantics (007 FR-019). Where this specification names a 007 requirement, that requirement applies unchanged unless a clause here narrows it.

The 007 requirements that described the bespoke wire — the connector adapter allowlist and capability probe (007 FR-001, FR-002), the `start`/`reply`/`cancel` command envelope (007 FR-006, FR-007), the state mapping and versioned event envelope (007 FR-008, FR-009) and the reporting-instructions manifest fields (007 FR-005 in part) — are superseded by FR-001 through FR-012 below. The 007 ratified baseline stays as history and is not re-ratified.

This feature does not touch voice capture, capture review, native Task ownership, Weekly Review or the CRT canvas. It has no impact on the primary loop; an external run remains an optional evidence lane after a canonical Task exists.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Connect an A2A agent by its card (Priority: P1)

A signed-in user adds an agent they operate by entering its address and a credential. BrainBuddy discovers the agent through its published card, verifies the credential and shows what the agent supports, including which guarantee tier the hand-off will run under, before any task can be handed off.

**Why this priority**: No task can be handed off safely or truthfully until BrainBuddy has a valid, owner-scoped connection to an agent whose protocol, interface, authentication scheme and guarantees are known.

**Independent Test**: Add the official a2a-sdk sample agent and the Hermes A2A plugin as connections, complete recent reauthentication, test each connection and inspect the saved connection without dispatching a task.

**Acceptance Scenarios**:

1. **AC-001**: **Given** a signed-in user who completed server-verified reauthentication within the previous 15 minutes, **when** they save an agent address whose card advertises protocol version 1.0.x with a JSON-RPC interface over HTTPS and a supported authentication scheme, and the connection test succeeds, **then** BrainBuddy shows the agent name, version, description, skills, streaming and push-notification support, the guarantee tier, tested status and last contact.
2. **AC-002**: **Given** an address that is unreachable, does not serve an agent card, or serves a card without a usable protocol version or interface, **when** the user tests it, **then** BrainBuddy shows a distinct actionable category (unreachable, not an A2A agent, unsupported protocol version, no supported interface) and does not mark the connection ready.
3. **AC-003**: **Given** a reachable agent that rejects the supplied credential, **when** the user tests it, **then** BrainBuddy reports invalid credentials without displaying the submitted secret and does not mark the connection ready.
4. **AC-004**: **Given** a card that requires only authentication schemes this feature does not support (for example OAuth2 or mutual TLS), **when** the user tests it, **then** BrainBuddy names the unsupported scheme, explains that bearer tokens and API keys are supported, and does not mark the connection ready.
5. **AC-005**: **Given** a card that does not declare the BrainBuddy single-start extension, **when** the test succeeds, **then** the connection is ready under the best-effort tier and the disclosure explains that BrainBuddy checks for an existing task before any retry but a duplicate remains possible if the agent forgets its tasks.
6. **AC-006**: **Given** an agent address on a loopback, link-local, metadata or private network, **when** BrainBuddy validates it, **then** the destination is refused exactly as 007 FR-004 requires unless the deployment separately governs that network class.

---

### User Story 2 - Review and hand one task to the agent (Priority: P1)

From an existing Task, a user chooses **Hand to agent**, selects one tested connection, reviews exactly what will leave BrainBuddy together with the guarantee tier, and confirms one dispatch.

**Why this priority**: This is the constitutional consent boundary before task content leaves BrainBuddy, and the point where the single-start promise is either kept or honestly qualified.

**Independent Test**: Open one Task, select a tested connection, remove one context item, confirm, and verify that exactly one task exists at the agent with the reviewed content and that replaying the confirmation creates no second task.

**Acceptance Scenarios**:

1. **AC-007**: **Given** a tested, non-stale connection and an existing Task, **when** the user opens the hand-off review, **then** BrainBuddy lists every value that will be sent: the Task title, the Task details when selected, each selected context item, the stable Task ID and the new run ID that travel with the message, the destination agent, the guarantee tier disclosure, the cancellation-support disclosure and the external-copy notice.
2. **AC-008**: **Given** the hand-off review, **when** the user removes a context item or cancels, **then** removed context is not sent and cancellation creates no task at the agent and no visible run.
3. **AC-009**: **Given** a confirmed hand-off, **when** dispatch succeeds, **then** exactly one task exists at the agent, exactly one Execution run is linked to the Task, and the timeline shows **Sent** followed by agent-reported state.
4. **AC-010**: **Given** the same confirmation or dispatch request is replayed, **when** BrainBuddy handles it again, **then** the same run and outcome are returned and no second task is created at the agent, under both guarantee tiers.
5. **AC-011**: **Given** a stale, failed-test, disconnected or wrong-owner connection, **when** a hand-off is attempted, **then** BrainBuddy refuses before sending task content and explains the corrective action.
6. **AC-012**: **Given** a tested connection whose agent card has since changed its interface address or authentication requirements, **when** a hand-off is attempted, **then** BrainBuddy refuses, reports that the agent changed, and requires a new successful test before dispatch.

---

### User Story 3 - Monitor and respond without false claims (Priority: P1)

The user watches the run from the Task. They can see the agent-reported state, answer a question when the agent asks one, request cancellation, inspect the result, and distinguish agent-reported completion, failure, cancellation and silence.

**Why this priority**: The relay is useful only if the user understands what the agent reported without BrainBuddy inventing progress, success or failure, including against agents that answer slowly or forget their tasks.

**Independent Test**: Drive one run against a reference agent through working, input-required, completed, failed and canceled states, and against an agent that answers only after a long delay, and inspect both responsive Task surfaces.

**Acceptance Scenarios**:

1. **AC-013**: **Given** a dispatched run, **when** BrainBuddy's own authenticated observation of the agent's task shows a new state, **then** the Task shows the agent name, the reported state, the agent's latest status text when present, last contact and a chronological timeline, without fabricated percentages, stages or ETA.
2. **AC-014**: **Given** an agent that answers a hand-off only after a long delay (up to the deployment-configured reply window, at least 300 seconds), **when** the user watches the run, **then** BrainBuddy shows **Sent** and then agent-reported state without inventing a failure, and shows the true terminal state within one observation interval after the agent finishes.
3. **AC-015**: **Given** an observation in the agent's input-required state and an agent that accepts follow-up messages, **when** the user answers from the Task, **then** BrainBuddy sends the answer once, records it in the timeline, shows the reply as unconfirmed until the agent acknowledges it, and returns the run to a later agent-reported state only after a subsequent authenticated observation.
4. **AC-016**: **Given** an authenticated observation of completion with text or artifacts, **when** it is displayed, **then** the Task says **Agent reported complete**, renders text inertly, exposes safe HTTPS links per 007 FR-014, and leaves Task completion under user control.
5. **AC-017**: **Given** an authenticated observation of failed, rejected or canceled, **when** it is displayed, **then** BrainBuddy shows **Failed** with the reason (including "Rejected by agent"), or **Cancelled**, preserves the timeline and does not retry the work.
6. **AC-018**: **Given** the user requests cancellation, **when** the agent accepts the request, **then** BrainBuddy shows **Cancellation requested** until an observation shows the task canceled; **when** the agent answers that cancellation is not supported or the task is no longer cancelable, **then** BrainBuddy says so and keeps the last observed state.
7. **AC-019**: **Given** a non-terminal run with no successful authenticated observation within the configured reporting window, **when** the window expires, **then** BrainBuddy shows **Stopped reporting** with last contact, without claiming the agent stopped or failed.
8. **AC-020**: **Given** an agent that no longer knows the run's task (it answers that the task does not exist), **when** BrainBuddy observes this, **then** the run shows **Agent no longer reports this run** with last contact, keeps the timeline, and offers no reply or cancel control.
9. **AC-021**: **Given** a push notification arrives from the agent, **when** it carries the per-run verification token BrainBuddy registered, **then** BrainBuddy performs an immediate observation and changes state only from that observation; **when** the token is missing or wrong, **then** nothing changes and the rejection is recorded with bounded cardinality.

---

### User Story 4 - Disconnect and retain only bounded evidence (Priority: P2)

The user can disconnect an agent without exposing its secret or erasing the honest history of runs already attached to Tasks.

**Why this priority**: Credentials and relayed content are sensitive, while past task evidence must remain understandable for a bounded period. This story is unchanged from 007 apart from the identifiers this feature adds.

**Independent Test**: Disconnect a connection after recent reauthentication, inspect existing run history, advance retention cleanup clocks, and run the account-purge flow.

**Acceptance Scenarios**:

1. **AC-022**: **Given** a connected agent and reauthentication no older than 15 minutes, **when** the user confirms disconnect, **then** BrainBuddy destroys the credential, stops observing and registering push notifications for that connection's runs, prevents new hand-offs and replies, and preserves bounded redacted history per 007 FR-016.
2. **AC-023**: **Given** saved credentials, **when** any connection, Task, audit, export, log or error view is rendered, **then** the secret is never returned or displayed after save (007 FR-003).
3. **AC-024**: **Given** relayed content reaches 30 days, **when** retention cleanup runs, **then** content is deleted and only coarse metadata, including agent task and context identifiers, may remain for at most 90 days (007 FR-015).
4. **AC-025**: **Given** the user invokes account deletion, **when** purge completes, **then** connections, credentials, card metadata, runs, observations and audit data are removed under the existing purge contract.

### Edge Cases

- A card fetch that redirects, serves multiple interfaces, or lists a JSON-RPC interface on a different host than the card: redirects are refused per 007 FR-004; the first JSON-RPC interface with protocol version 1.0.x is used; an interface whose destination fails 007 FR-004 validation makes the connection unsupported.
- An agent that returns a direct message instead of a task when the hand-off is sent: the run records **Agent reported complete** with that message text as the result, since the agent chose to answer without creating a task.
- An agent that reaches a terminal state within the dispatch itself (the reference sample agent does): the run shows **Sent** and the terminal state in the same timeline without a fabricated intermediate state.
- An agent that rate-limits the dispatch before creating a task: the run is **Not sent** with an actionable "agent is rate limiting" category; no task exists, so a later confirmation may retry with the same run ID and message ID.
- A dispatch that times out or fails ambiguously: **Delivery unconfirmed**; before any resend BrainBuddy looks the run up at the agent by its context ID; if a task exists it is adopted, otherwise the identical message is resent.
- An agent that refuses push-notification registration: the run continues by observation only; nothing is shown as an error to the user.
- Artifacts that are not text (files, structured data): shown as non-interactive placeholders naming the content type; an HTTPS link inside them follows 007 FR-014; nothing is fetched server-side to render a run.
- Text that exceeds the configured result, question or status limits: truncated with a visible marker; the observation is still accepted.
- Barrier-concurrent duplicate `start`, `reply` and `cancel` submissions converge on one durable winner and at most one agent-side action, exactly as 007 requires.
- Editing or completing the Task after dispatch does not rewrite the frozen sent content; a later hand-off creates a distinct run.
- Mobile interruption, app closure and offline windows behave as 007 FR-018: reopening loads the server projection, offline clients label cached state as potentially stale and disable reply and cancel rather than queue them.
- Rollout OFF blocks new connections, tests, credential changes, hand-off previews and fresh dispatches; observation of already-dispatched runs, verified push handling, safe reply and cancel for existing runs, purge and retention continue (007 FR-019).

## Clarifications

### Session 2026-09-03

- Q: Which agent runtimes and authentication schemes are in scope? → A: Any A2A v1.0.x agent reachable over public HTTPS with bearer-token or API-key authentication, whether self-hosted or cloud-hosted; OAuth2 and mutual TLS are deferred (product owner).
- Q: Are agents without the BrainBuddy extension admitted? → A: Yes, under a best-effort tier with BrainBuddy-side deduplication and an honest disclosure; extension-capable agents get the strong guarantee (product owner).
- Q: Does the bespoke wire survive alongside A2A? → A: No; it is removed entirely (product owner).
- Q: Must the relay work with the unmodified Hermes A2A plugin? → A: Yes; an upstream patch may be proposed but nothing depends on it (product owner).
- Q: What is the definition of done? → A: End-to-end hand-off to the unmodified Hermes A2A plugin and to an official a2a-sdk sample agent, three replays produce one task, the 007 security suite passes on the new wire, web and iOS show one projection (product owner).
- Q: Appetite and deadline? → A: Medium, weeks, no calendar deadline; release through exact-SHA review, CI and ASK authority as for 007 (product owner).
- Q: Where is the best-effort single-start disclosure shown? → A: On the connection after every successful test and again in every hand-off review before confirmation (product owner).
- Q: Is the BrainBuddy single-start extension published? → A: Yes, under a public, stable identifier with a short public specification in the repository documentation (product owner).
- Q: How is the unmodified Hermes plugin verified? → A: In CI against the unmodified plugin code with a stub agent handler and no model, plus one attended live run against a real Hermes as release evidence before rollout (product owner).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: BrainBuddy MUST let a signed-in owner create, test, inspect, update, rotate credentials for and disconnect an owner-scoped connection to an A2A agent given the agent's address and a credential. BrainBuddy MUST discover the agent through its published agent card at the standard well-known location, MUST require protocol version 1.0.x on a JSON-RPC interface, MUST record the agent's name, version, description, skills, streaming and push-notification support, authentication requirements and interface address, and MUST support exactly two credential schemes: a bearer token and an API key sent in a header named by the card. A card that offers only other schemes MUST leave the connection unsupported with the scheme named. No other connector kind exists after this feature.
- **FR-002**: A connection test MUST return **ready** only after an authenticated response from the agent's task interface, **invalid credentials** after an explicit authentication rejection, **unreachable** after transport failure or expiry of the configured test timeout, and **unsupported** when the card, protocol version, interface or authentication scheme cannot be used. Last authenticated contact, the stale threshold and the stale rule apply exactly as 007 FR-002. A stale or untested connection MUST NOT accept a new hand-off.
- **FR-003**: Every connection MUST carry a guarantee tier. **Guaranteed** applies when the agent's card declares the BrainBuddy single-start extension (FR-011); **best-effort** applies otherwise. The tier MUST be disclosed to the owner in plain language on the connection after every successful test and again in every hand-off review before confirmation. The best-effort disclosure MUST state that BrainBuddy checks the agent for an existing task before any retry and that a duplicate remains possible if the agent forgets its tasks. Nothing MUST present best-effort as guaranteed.
- **FR-004**: Secret material, reauthentication triggers and egress rules apply exactly as 007 FR-003 and FR-004 to every card fetch, every task operation and every push-notification registration. A change of the agent's interface address counts as a destination change for the purposes of 007 FR-003 and MUST require a new successful test and recent reauthentication before the next content-bearing dispatch.
- **FR-005**: The hand-off review MUST expose an immutable, versioned manifest containing the exact text that will leave BrainBuddy (Task title, optional Task details, each selected context item), the stable Task ID and the new run ID that travel with the message, the destination agent, the guarantee tier disclosure, the cancellation-support disclosure and the external-copy notice of 007 FR-005. Confirmation MUST identify the manifest token; any change to a value, the destination or the run ID invalidates confirmation and requires review again.
- **FR-006**: Before dispatch BrainBuddy MUST durably reserve the run ID, a message ID derived from the run's idempotency key, and a context ID equal to the run's stable correlation ID. A confirmed start MUST send exactly one message carrying those identifiers and the Task and run IDs as metadata, and MUST record the agent's task ID when one is returned. Dispatch MUST distinguish **Not sent**, **Sent** and **Delivery unconfirmed** as 007 FR-006. Before any resend BrainBuddy MUST look the run up at the agent by its context ID: a found task MUST be adopted and never resent; only when no task exists MAY the identical message be resent with the same message ID. A guaranteed-tier agent MUST additionally deduplicate by message ID; a best-effort agent's residual duplicate risk is disclosed, not hidden.
- **FR-007**: Dispatch MUST NOT depend on the agent answering within the user's request. BrainBuddy MUST keep the exchange alive in the background for at least the deployment-configured reply window (default at least 300 seconds) so that an agent which answers only at the end of its work is handled without a fabricated failure, and MUST treat the task returned at the end of that exchange as an authenticated observation.
- **FR-008**: Run state MUST come only from BrainBuddy's own authenticated observations of the agent's task. Each observation MUST receive a BrainBuddy-assigned strictly increasing version; an observation older than the current version MUST change nothing. BrainBuddy MUST observe every non-terminal run at a deployment-configured interval, on every reply or cancel acknowledgement, and immediately when a verified push notification arrives. A push notification MAY accelerate observation and MUST NOT change state by itself. Push notifications MUST be verified against a per-run token that BrainBuddy registered with the agent; unverified, unknown-run, wrong-owner, malformed or oversized notifications MUST change nothing and MUST NOT create unbounded durable records, as the 007 post-ratification clarification requires.
- **FR-009**: BrainBuddy MUST map agent task states to the 007 projection as follows: submitted → **accepted**; working → **running** with the agent's latest status text as optional progress; input-required → **blocked** with the agent's message as the question; auth-required → **blocked** with the reason "Agent needs additional authentication" and no reply control; completed → **completed** with the result assembled from text artifacts and the final status message; failed → **failed** with the reason; rejected → **failed** with the reason "Rejected by agent"; canceled → **cancelled**; a direct message answer → **completed** with that text. Completed, failed and cancelled are terminal; later non-identical state changes MUST be rejected. Compact and detail surfaces MUST derive labels from this one projection. **Sent**, **Stopped reporting**, reply-pending and cancel-requested overlays apply exactly as 007 FR-008.
- **FR-010**: When the run is blocked and the agent's task is still open, the user MUST be able to send one reply as a follow-up message in the same context and task, carrying a stable command ID as its message ID. Duplicate submissions MUST return the same command and cause at most one message. The reply MUST be shown as unconfirmed until the agent acknowledges that message, and the run MUST return to an agent-reported state only after a subsequent observation. Cancellation MUST send one cancel request with a stable command ID, show **Cancellation requested** until an observation shows the task canceled, and when the agent answers that cancellation is unsupported or the task is not cancelable, say so and keep the last observed state. Because agent cards do not advertise cancellation support, the hand-off review MUST disclose that cancellation depends on the agent and can only be confirmed when requested.
- **FR-011**: BrainBuddy MUST define a single-start extension whose entire contract is: an agent that declares it deduplicates messages by message ID within a context and returns the original task on replay. Agents declaring the extension in their card are guaranteed tier; the extension MUST NOT carry any other capability. BrainBuddy MUST publish the extension under a public, stable identifier with a short public specification in the repository documentation, so that any third-party agent can declare it in its card.
- **FR-012**: The bespoke connector envelope, its capability probe and its signed inbound event route MUST be removed. Any pre-existing connection record that cannot be expressed as an A2A connection MUST be marked disconnected with the reason "superseded wire contract" rather than migrated; its runs keep their bounded history.
- **FR-013**: Task detail and compact surfaces MUST show, in addition to everything 007 FR-010 requires, the guarantee tier, the **Agent no longer reports this run** condition when the agent answers that the task does not exist, and the cancellation-unsupported outcome. Web and iOS MUST derive their labels from the same server projection.
- **FR-014**: User-visible copy MUST distinguish BrainBuddy facts from agent reports exactly as 007 FR-011, and MUST additionally use **Best-effort single start**, **Guaranteed single start**, **Cancellation depends on the agent** and **Agent no longer reports this run** for the conditions this feature introduces.
- **FR-015**: For a non-terminal run, last authenticated contact is the latest server receipt time of an accepted dispatch, a successful authenticated observation (including one that shows no change) or an acknowledged reply or cancel. **Stopped reporting** applies exactly as 007 FR-013. An observation answering that the task does not exist MUST set the **Agent no longer reports this run** condition, preserve last contact, and stop further reply and cancel controls without claiming failure.
- **FR-016**: Agent content rendering, retention, disconnect, correlation IDs, logs, interruption and offline behavior, and rollout-OFF semantics apply exactly as 007 FR-014 through FR-019. Agent task IDs, context IDs and card metadata are coarse metadata under 007 FR-015 and MUST follow its 90-day audit bound; logs MAY additionally carry the agent's protocol version and allowlisted A2A error codes and MUST NOT carry card secrets, task text or artifacts. Disconnect MUST also stop observation and push registration for the connection's runs. While rollout is OFF, observation of already-dispatched runs and verified push handling MUST continue.
- **FR-017**: BrainBuddy MUST ship deterministic reference conformance checks against two unmodified third-party runtimes: an official a2a-sdk sample agent and the Hermes A2A plugin's inbound server. The Hermes check MUST run in continuous integration against the unmodified plugin code driven by a stub agent handler without a model, and a separate attended live run against a real Hermes installation MUST be recorded as release evidence before rollout; that live run spends provider money and requires explicit human approval, exactly like the existing live verification skill. Neither runtime may require any BrainBuddy-specific code.

### Key Entities

- **Agent Connection**: Owner-scoped saved agent identity: address, discovered card metadata (name, version, description, skills, streaming and push support, authentication requirements, interface address, protocol version), a card fingerprint used to detect drift, the credential scheme and non-readable credential reference, guarantee tier, tested state, last authenticated contact and stale or disconnected status.
- **Execution Run**: Owner-scoped external attempt linked to one Task: stable run ID, message ID, context ID, the agent's task ID once known, frozen sent-content manifest, dispatch state, latest observed state and observation version, last contact, push-registration state and the conditions this feature adds. It is separate from the Task lifecycle.
- **Observation**: One authenticated retrieval of the agent's task by BrainBuddy: version, observed state, status text, artifacts summary, server receipt time, and whether it was triggered by schedule, by a command acknowledgement or by a verified push notification.
- **Run Command**: Idempotent owner request to start, reply or cancel, with its stable message or command ID and an explicitly unconfirmed or confirmed outcome.
- **Audit Entry**: Minimal owner-visible timeline fact with IDs, coarse state or action, timestamps and safe error metadata, never credentials or relayed content beyond its retention window.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An automated end-to-end hand-off from a Task completes through **Agent reported complete** against two unmodified third-party runtimes, an official a2a-sdk sample agent and the Hermes A2A plugin, with zero BrainBuddy-specific code on the agent side.
- **SC-002**: Three identical confirmation and dispatch replays produce exactly one task at the agent and one Task-linked run for each reference runtime, and the same holds against a reference agent that declares the single-start extension.
- **SC-003**: Every 007 security rejection case (unauthenticated, cross-owner, malformed, oversized, unknown-run, unsafe-destination, stale) plus forged, replayed and wrong-token push notifications and agent-card drift are rejected with zero accepted state changes and zero secret disclosure.
- **SC-004**: Every required user-visible state — sent, accepted or running, needs-user, agent-reported-complete, failed, cancelled, cancellation-unsupported, stopped-reporting, agent-no-longer-reports-this-run, and the best-effort disclosure — is distinguishable on both the responsive Task detail and compact Task surfaces on web and iOS from one projection, without fabricated progress or Task completion.
- **SC-005**: A user can identify exactly what will be sent, the guarantee tier and the cancellation disclosure, and remove optional context before confirming, on desktop-width and iPhone-width review surfaces.
- **SC-006**: Against an agent that answers only after a delay of up to 300 seconds, the run shows **Sent** and no fabricated failure while waiting, and the true terminal state within one observation interval (at most 60 seconds) after the agent finishes.
- **SC-007**: Retention tests prove relayed content and drafts do not exceed 30 days, coarse metadata including agent task and context identifiers does not exceed 90 days, and account purge removes all owner feature data.
- **SC-008**: Deterministic barrier tests for concurrent duplicate start, reply and cancel submissions prove one durable winner and at most one agent-side action for each command family.
- **SC-009**: A connection test or dispatch failure always shows an actionable category (unreachable, not an A2A agent, unsupported protocol version or interface, unsupported authentication scheme, invalid credentials, private destination, rate limited) and a correlation ID, while automated log checks find no stored secret, task text or artifact content.
- **SC-010**: No code path, test or fixture for the bespoke envelope remains, and a pre-existing bespoke connection record is shown as disconnected with the superseded-wire reason rather than as ready.

## Assumptions

- The existing session authentication, owner scoping, correlation-ID envelope, account purge, Admin Portal rollout flag, responsive Task surfaces and the Expo iOS application remain the host product contracts.
- A deployment chooses its observation interval, reply window, test timeout, reporting window and any governed private-network allowance; the UI reports their effects rather than promising a universal interval.
- Only protocol version 1.0.x of A2A is in scope; agents serving other versions are unsupported and later protocol revisions are handled as follow-up features.
- Cloud-hosted agents are in scope only insofar as they accept a bearer token or an API key; an agent that requires OAuth2, mutual TLS or platform-specific signed requests is unsupported until the deferred schemes are delivered.
- No production connection records exist on the bespoke wire (rollout has been OFF since ratification); pre-existing records in non-production data are invalidated, not migrated.
- The official a2a-sdk sample agent serves plain HTTP on a loopback address, so automated end-to-end runs use the existing governed private-destination allowance in the test environment only; production keeps HTTPS and public destinations.
- The Hermes A2A plugin is MIT-licensed and its inbound server can be driven by a stub agent handler without a model, which is how its own test suite exercises it.
- The user owns the agent's hosting, model provider, tools, cost and output quality; BrainBuddy neither hosts nor verifies agents.
