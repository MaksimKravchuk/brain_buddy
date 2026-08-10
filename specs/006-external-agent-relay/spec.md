# Feature Specification: Lean External-Agent Relay

**Feature Branch**: `006-external-agent-relay-lean-v1`

**Created**: 2026-08-09

**Status**: Ratified

**Ratification receipt**: Max approved the exact pre-ratification specification bytes on 2026-08-09, SHA-256 `f3cf461ffa0340738b8d599d2c643a3979b7bea30fc08fabf90fa4c01299e384`, including the Design Acceptance Gate. This metadata records that approval; it does not retroactively change the reviewed hash.

**Input**: A BrainBuddy user connects an agent they operate, hands one existing task plus explicitly selected context to it, and honestly monitors the external run from that task.

## Product Boundary

BrainBuddy v1 provides a bring-your-own-agent relay. It is provider-agnostic and task-agnostic at the product boundary. Hermes is the first reference connector, not a required runtime or permanent dependency.

The user owns the external agent's hosting, configuration, tools, network access, provider credentials, permissions, cost, reliability, safety, and output quality. BrainBuddy owns faithful dispatch, explicit disclosure of sent content, task/run correlation, authenticated and idempotent event ingestion, honest status display, optional reply and cancel routing when the connector supports them, bounded retention, and a minimal audit timeline.

An external run is evidence attached to a canonical BrainBuddy Task. It never changes the Task lifecycle or completes the Task. A completion event is displayed as **Agent reported complete** because BrainBuddy does not verify the work or result.

This feature affects the existing task-to-result loop after a Task already exists. It does not change voice capture, capture review, native Task ownership, Weekly Review, or CRT graph ownership.

## User Scenarios & Testing

### User Story 1 - Connect an agent honestly (Priority: P1)

A signed-in user adds an agent they operate by entering a name, endpoint or connector reference, and required authentication material. They test it and see what the connection can actually report or accept before using it.

**Why this priority**: No task can be handed off safely or truthfully until BrainBuddy has a valid, owner-scoped connection and discloses its capabilities.

**Independent Test**: Add a test connector, complete recent reauthentication, test the connection, and inspect the saved connection without dispatching a task.

**Acceptance Scenarios**:

1. **AC-001**: **Given** a signed-in user who completed server-verified reauthentication within the previous 15 minutes, **when** they save a valid reachable connection and its connection test succeeds, **then** BrainBuddy shows the saved agent name, tested status, last contact, and supported capabilities for progress, questions/replies, and cancellation.
2. **AC-002**: **Given** invalid authentication material, **when** the user tests the connection, **then** BrainBuddy does not mark it ready and shows an actionable invalid-credentials error without displaying the submitted secret.
3. **AC-003**: **Given** an unreachable endpoint or connector, **when** the user tests it, **then** BrainBuddy distinguishes unreachable from invalid credentials and offers a safe retry without claiming the connection works.
4. **AC-004**: **Given** a saved connection, **when** its last authenticated contact exceeds the configured stale-connection threshold, **then** BrainBuddy labels the connection stale, shows the last contact, and requires a successful test before a new hand-off.
5. **AC-005**: **Given** an ordinary user supplies a loopback, link-local, metadata-service, or private-network destination, **when** BrainBuddy validates the destination, **then** it refuses the destination unless that network class is separately enabled by governed deployment policy.

---

### User Story 2 - Review and hand one task to the agent (Priority: P1)

From an existing BrainBuddy Task, a user chooses **Hand to agent**, selects one connected agent, reviews the exact Task fields and optional context that will leave BrainBuddy, and confirms one dispatch.

**Why this priority**: This is the smallest useful BYOA outcome and the constitutional consent boundary before task content leaves BrainBuddy.

**Independent Test**: Open one Task, select a tested agent and context, confirm the preview, and verify one correlated start request with no unrelated data.

**Acceptance Scenarios**:

1. **AC-006**: **Given** a tested non-stale connection and an existing Task, **when** the user opens the hand-off review, **then** BrainBuddy lists every field that will be sent: Task title, Task details when selected, each selected context item, the stable Task ID, the new run ID, and minimal reporting instructions.
2. **AC-007**: **Given** the hand-off review, **when** the user removes a context item or cancels, **then** removed context is not sent and cancellation creates no external run.
3. **AC-008**: **Given** the user confirms the reviewed hand-off after any required recent reauthentication, **when** dispatch succeeds, **then** exactly one Execution run is linked to the Task and the timeline shows **Sent** followed by connector-reported state.
4. **AC-009**: **Given** the same confirmation or dispatch request is replayed, **when** BrainBuddy handles it again, **then** the same run and dispatch outcome are returned and no second external start is created.
5. **AC-010**: **Given** a stale, failed-test, disconnected, or wrong-owner connection, **when** a hand-off is attempted, **then** BrainBuddy refuses before sending task content and explains the corrective action.

---

### User Story 3 - Monitor and respond without false claims (Priority: P1)

The user watches the run from the Task. They can see accepted/running progress, answer a question when supported, inspect the result, and distinguish agent-reported completion, failure, cancellation, and silence.

**Why this priority**: The relay is useful only if the user can understand what the external agent reported without BrainBuddy inventing progress or guarantees.

**Independent Test**: Feed an authenticated sequence of accepted, running, blocked, reply, and completed events for one run and inspect both responsive Task surfaces.

**Acceptance Scenarios**:

1. **AC-011**: **Given** authenticated events for a run, **when** accepted and running events arrive, **then** the Task shows the agent name, current reported state, optional plain-language progress, last contact, and chronological timeline without fabricated percentages, stages, or ETA.
2. **AC-012**: **Given** a blocked event containing a question and a connector that supports replies, **when** the user answers from the Task, **then** BrainBuddy routes the answer once, records it in the timeline, and returns the run to its latest connector-reported state only after an authenticated later event.
3. **AC-013**: **Given** a blocked event but a connector that does not support replies, **when** the user views it, **then** BrainBuddy shows the question or reason and states that replies are unsupported rather than presenting a non-working reply control.
4. **AC-014**: **Given** an authenticated completed event with inline result text or an HTTPS result link, **when** it is displayed, **then** the Task says **Agent reported complete**, renders text inertly, exposes the result, and leaves Task completion under user control.
5. **AC-015**: **Given** an authenticated failed or cancelled event, **when** it is displayed, **then** BrainBuddy shows **Failed** with the reported reason or **Cancelled**, preserves the timeline, and does not silently retry the accepted external work.
6. **AC-016**: **Given** a non-terminal run with no authenticated event or successful poll within the configured reporting window, **when** the window expires, **then** BrainBuddy shows **Stopped reporting** and last contact without claiming the external agent stopped or failed.
7. **AC-017**: **Given** cancellation is supported, **when** the user requests it, **then** BrainBuddy shows that cancellation was requested and does not show **Cancelled** until the connector confirms it; when cancellation is unsupported, BrainBuddy discloses that before hand-off and omits the control.

---

### User Story 4 - Disconnect and retain only bounded evidence (Priority: P2)

The user can disconnect an agent without exposing its secret or erasing the honest history of runs already attached to Tasks.

**Why this priority**: BYOA credentials and relayed content are sensitive, while past task evidence must remain understandable for a bounded period.

**Independent Test**: Disconnect a connection after recent reauthentication, inspect existing run history, and advance retention cleanup clocks.

**Acceptance Scenarios**:

1. **AC-018**: **Given** a connected agent and server-verified reauthentication no older than 15 minutes, **when** the user confirms disconnect, **then** BrainBuddy destroys the active credential material, prevents new hand-offs and replies through that connection, and preserves bounded redacted run/audit history.
2. **AC-019**: **Given** saved authentication material, **when** any connection, Task, audit, export, log, or error view is rendered, **then** the stored secret value is never returned or displayed after save.
3. **AC-020**: **Given** relayed content or local device cache reaches 30 days, **when** retention cleanup runs, **then** that content is deleted; audit metadata and cleanup receipts may remain for at most 90 days, and encrypted backups containing feature data expire within 30 days.
4. **AC-021**: **Given** the user invokes the existing account-deletion flow, **when** account purge completes, **then** connections, credentials, relayed content, runs, and feature audit data are removed under the existing account-purge contract.

### Edge Cases

- An event with an unknown run ID, wrong owner, failed authentication, unsupported type, invalid shape, or excessive size is rejected without changing visible run state.
- Duplicate or delayed events are idempotent. An older event cannot overwrite a newer accepted state; exact ordering and storage mechanics belong in the plan.
- A completion event arriving after **Stopped reporting** updates the run to **Agent reported complete** and remains visible after the earlier silence marker in the timeline.
- A reply or cancel request that times out remains visibly unconfirmed. BrainBuddy does not infer that the external agent received or acted on it.
- Editing or completing the BrainBuddy Task after dispatch does not rewrite the frozen content already sent. A later hand-off creates a distinct run and review.
- Agent text and links are untrusted. Text is inert, executable markup and commands are never run, and only safe HTTPS result links are interactive.
- Mobile interruption or app closure does not cancel a run; reopening fetches the owner-scoped server projection. Offline clients show cached state as potentially stale and do not claim a reply or cancel was sent until the server confirms receipt.
- A connector may support authenticated polling instead of inbound events. The user-visible state and honesty rules are identical.

## Post-ratification implementation clarifications (2026-08-10)

The release-blocker review after ratification exposed two security details that the
requirements stated only at outcome level. This amendment narrows implementation
choices without changing the approved product intent:

- The FR-005/FR-009 reporting manifest resolves the callback URL and connection ID,
  names `X-BrainBuddy-Connection`, `X-BrainBuddy-Timestamp`, and
  `X-BrainBuddy-Signature`, and specifies canonical unsigned ASCII base-10 Unix
  seconds with no whitespace or leading zeroes. Signatures are
  `v1=<lowercase hex>` HMAC-SHA256 over
  `timestamp_bytes + b'.' + raw_body`; the emitted contract also names the body
  envelope/protocol version.
- FR-015 permits durable semantic-rejection audit after authentication, but
  pre-authentication invalid-signature, stale-timestamp, unreadable-secret, and
  disconnected probes MUST NOT create one 90-day row per request. Their durable
  cardinality must be fixed/bounded independently of attacker request volume;
  dropping per-attempt durable rows is conforming.

## Requirements

### Functional Requirements

- **FR-001**: BrainBuddy MUST let a signed-in owner create, test, inspect, update, rotate credentials for, and disconnect an owner-scoped external-agent connection using an agent name, endpoint or connector reference, and secret/authentication material. Hermes MUST be treated as a reference connector rather than a product dependency.
- **FR-002**: A connection test MUST return **ready** only after an authenticated connector response, **invalid credentials** after an explicit authentication rejection, and **unreachable** after transport failure or expiry of the deployment-configured test timeout. Last authenticated contact and the active timeout/stale threshold MUST be server-calculated and observable. A successful test resets last contact; readiness becomes **stale** when server time is greater than or equal to last contact plus the stale threshold. Stale is a time-derived connection condition, not a test response. The test MUST disclose support for progress, questions/replies, and cancellation. A stale or untested connection MUST NOT accept a new hand-off.
- **FR-003**: Secret material MUST never be returned after save, persisted in plaintext, or exposed to ordinary application-data queries, logs, traces, crash reports, analytics, support tooling, queues, or temporary files. It MUST reside in an approved secrets facility or be encrypted with separately controlled keys and be available only to narrowly scoped connector and credential-management operations; access MUST be auditable. Connection registration or destination change, credential creation or replacement, first content-bearing dispatch in a new destination/credential scope, credential destruction, user-initiated early deletion of relayed content, and destructive disconnect MUST require server-verified reauthentication completed no more than 15 minutes earlier using the account's highest enrolled assurance. Session or remembered-device possession alone is insufficient, and recovery-restricted sessions cannot perform these operations until normal assurance is restored. Automatic retention expiry, backup expiry, and execution of the existing account-purge contract proceed as dedicated server operations without a new interactive ceremony.
- **FR-004**: Ordinary users MUST be prevented from configuring loopback, link-local, metadata-service, or private-network destinations unless the deployment separately and explicitly enables that network class. Credential- or content-bearing traffic MUST use HTTPS with valid hostname and certificate verification under deployment policy. Scheme and destination validation MUST run before every resolution, redirect, retry, and subsequent outbound connection; insecure redirects and redirects or address changes into disallowed classes MUST be rejected before forwarding credentials or content.
- **FR-005**: From one existing owner-scoped Task, the user MUST be able to review and confirm one hand-off to one tested connection. Review MUST expose an immutable, versioned logical payload manifest containing the exact Task title, optional Task details, each selected context item, stable Task ID, new run ID, destination agent, and the complete versioned reporting-instructions template and resolved values. The adapter may add only enumerated content-free transport authentication, routing, framing, and encoding. Confirmation MUST identify the manifest token and dispatch exactly its content-bearing values; any included value, destination, instruction, or run-ID change invalidates confirmation and requires review again. The same surface MUST state that the user-operated external agent receives a separate copy that BrainBuddy cleanup, disconnect, and account deletion cannot guarantee to erase.
- **FR-006**: Before dispatch, BrainBuddy MUST durably reserve the owner-scoped run ID and immutable idempotency key. A confirmed start MUST send `start(prompt, task_id, run_id, idempotency_key)` and create one Execution run linked to, but not owned by, the Task. A conforming connector MUST deduplicate that key within the connection scope and return its original outcome on replay; a connector without this guarantee MUST NOT be ready for hand-off. Dispatch MUST distinguish **Not sent**, **Sent**, and **Delivery unconfirmed**. Timeout or ambiguous transport loss produces **Delivery unconfirmed**, preserves the run and correlation ID, and MUST NOT be called failed or retried as a new run. Any retry reuses the original run ID and key unless BrainBuddy has definitive evidence that nothing was sent.
- **FR-007**: Connectors MAY support `reply(run_id, user_message, command_id)` and `cancel(run_id, command_id)`. BrainBuddy MUST disclose unsupported capabilities before hand-off and omit unusable controls. Each command gets one stable command ID reused on replay; duplicate submissions return the same command and cause at most one connector-side action. Delivery becomes confirmed only from an authenticated acknowledgement explicitly correlated to that command ID; an unrelated run event cannot confirm it, and delivery acknowledgement remains distinct from a later run-state change.
- **FR-008**: BrainBuddy MUST map connector reports to `accepted`, `running` with optional progress text, `blocked` with a question or reason, `completed` with a result, `failed` with a reason, and `cancelled` when supported. The owner-facing projection MUST separately expose the latest authenticated connector state and authoritative version, the derived reporting condition, and pending command conditions. **Sent** applies before the first authenticated state; **Stopped reporting** overlays rather than erases a non-terminal state; reply-pending and cancel-requested overlay the current state; submitting a reply does not clear **blocked**. A later authenticated event clears only conditions it explicitly confirms. Completed, failed, and cancelled are terminal; after the first accepted terminal state, later non-identical state changes are rejected. Compact and detail surfaces MUST derive labels from this same projection.
- **FR-009**: Each protocol version MUST define a bounded event envelope containing connection ID, run ID, unique event ID, type, freshness value, authoritative strictly increasing run version, and type-specific payload, with required/forbidden fields, accepted encoding, finite request/text/link limits, and inclusive boundaries. Authentication MUST integrity-protect the complete request and bind those fields to an active connection. Before mutation, BrainBuddy MUST validate credential lifecycle, freshness or nonce, owner/connection/run correlation, schema, size, event ID, version, and FR-008 transition rules; replay identifiers MUST be consumed atomically. Duplicate IDs, equal/lower versions, wrong-owner or unknown runs, revoked/rotated/disconnected credentials, and invalid transitions cause zero projection changes. Authenticated polling MAY provide equivalent confidentiality, identity, correlation, freshness, and authoritative snapshot version; connectors without authoritative ordering cannot provide asynchronous updates.
- **FR-010**: Task detail MUST show each run separately with agent identity, current projection, last contact, optional reported progress, blocked content, user reply, result, commands, and chronological timeline. The compact Task surface MUST show only the latest run's agent, honest primary state, needs-user indicator, and last contact, with a route to all runs. After FR-015 expires content, both surfaces MUST replace deleted task/context/progress/question/reply/result content with **Content expired under retention policy** and may show only permitted coarse metadata; expiry MUST NOT look like loading or connector failure.
- **FR-011**: User-visible copy MUST distinguish BrainBuddy facts from external reports. Completion MUST read **Agent reported complete**; silence MUST read **Stopped reporting**; unconfirmed reply/cancel delivery MUST remain unconfirmed. BrainBuddy MUST NOT fabricate percentages, stages, ETA, success, failure, cancellation, or verification.
- **FR-012**: A connector-reported completion MUST NOT complete or otherwise mutate the canonical BrainBuddy Task. BrainBuddy MUST NOT classify, plan, decompose, optimize, verify, or automatically retry accepted external work in v1.
- **FR-013**: For a non-terminal run, last authenticated contact is the latest server receipt time of dispatch acceptance, an authenticated event, or a successful authenticated poll, including a poll with no new event. When server time is greater than or equal to that contact plus the observable deployment-configured reporting window, BrainBuddy MUST show **Stopped reporting**, preserve last contact, and still accept a later valid higher-version event. This condition is not a claim that the external agent stopped.
- **FR-014**: Agent text and markup MUST render as inert text and never execute. Interactive result links MUST use HTTPS, contain no embedded user information or credentials, pass URL parsing and the same destination-class checks as FR-004, open only after an explicit user action with referrer suppression and external-destination disclosure, and never be fetched server-side merely to render a run. All other schemes or malformed destinations remain non-interactive text.
- **FR-015**: Retention age begins at authoritative server creation/receipt and MUST NOT reset on read, sync, migration, or restore. BrainBuddy-controlled relayed task/context/progress/question/reply/result content and hand-off/reply drafts MUST expire and become inaccessible by 30 days; Task projections then use the FR-010 expiry marker. Online clients MUST enforce server expiry before every read, isolate caches by owner, exclude feature caches from supported device backups, and remove expired data at the next available launch/background opportunity. BrainBuddy-controlled encrypted backups MUST preserve original expiry and expire or cryptographically erase feature data within 30 days; user-controlled device backups are outside the physical-deletion guarantee but MUST NOT yield readable expired data through BrainBuddy. Audit entries for connection/credential changes, tests, dispatches, commands, accepted/rejected events, retention cleanup, disconnect, and purge MAY retain only IDs, coarse outcomes, timestamps, actor, and correlation ID for at most 90 days. Existing account purge MUST remove all owner feature data without logging content or secrets.
- **FR-016**: Disconnect MUST require explicit confirmation and FR-003 reauthentication, destroy active credential material, and prevent new hand-offs and replies. Before confirmation, the user MUST be told that disconnect does not cancel external work; active runs become **Connection disconnected**, polling and commands stop, and later events signed by destroyed connection credentials are rejected. Existing bounded redacted history remains. If the user wants cancellation and the connector supports it, cancellation must be requested and confirmed before disconnect.
- **FR-017**: Every API response MUST include the existing `X-Correlation-ID`; connector operations and owner-visible errors MUST preserve and show that value. Logs and metrics MAY contain owner-safe IDs, timings, coarse states, connector type, and allowlisted error codes, but MUST NOT contain credentials or relayed user/agent content.
- **FR-018**: Closing web or iOS UI MUST NOT cancel a run. Reopening MUST load the owner-scoped server projection. Offline clients MUST label cached state as potentially stale, disable reply/cancel submission rather than queue or auto-send it, and may retain an owner-visible local draft only within FR-015. Cached run content MUST be encrypted with platform facilities, inaccessible after sign-out/session revocation or to another account, deleted on account switch, and made unreadable immediately upon account deletion or purge notice with physical cleanup at the next platform opportunity.

### Key Entities

- **Agent Connection**: Owner-scoped saved connector identity, endpoint/reference, non-readable credential reference, tested state, capability disclosure, last authenticated contact, and stale/disconnected status.
- **Execution Run**: Owner-scoped external attempt linked to one Task, with a stable run ID, frozen sent-content summary, current reported state, last contact, and result reference. It is separate from Task lifecycle.
- **Run Event**: Authenticated, idempotent connector report for one run: accepted, running, blocked, completed, failed, or cancelled.
- **Run Command**: Idempotent owner request to start, reply, or cancel, with an explicitly unconfirmed/confirmed outcome.
- **Audit Entry**: Minimal owner-visible timeline fact containing IDs, coarse state/action, timestamps, and safe error metadata without credentials or relayed content beyond its shorter retention window.

## Success Criteria

### Measurable Outcomes

- **SC-001**: In an end-to-end reference-connector test, one confirmed hand-off produces exactly one external start and one Task-linked run across at least three identical confirmation/dispatch replays.
- **SC-002**: Every required user-visible state—sent, accepted/running, needs-user, agent-reported-complete, failed, cancelled when supported, and stopped-reporting—is distinguishable on both responsive Task detail and compact Task surfaces without fabricated progress or Task completion.
- **SC-003**: Automated security tests reject all tested unauthenticated, cross-owner, malformed, oversized, unknown-run, unsafe-destination, and stale-regression cases with zero accepted state changes or secret disclosure.
- **SC-004**: A user can identify exactly what will be sent and remove optional context before confirmation in both desktop-width and iPhone-width review surfaces.
- **SC-005**: Capability tests show no reply/cancel/progress control when unsupported, and supported reply/cancel requests remain visibly unconfirmed until connector evidence arrives.
- **SC-006**: Retention tests prove relayed content, drafts, and device caches do not exceed 30 days; audit/cleanup metadata does not exceed 90 days; and account purge removes all owner feature data.
- **SC-007**: A connection test or dispatch failure always shows an actionable category and correlation ID while automated log checks find no stored secret or relayed content.

## Design Acceptance Gate

Before architecture planning, generated tasks, handoff, or implementation:

- Recover and reuse the existing Cloud Design Task card/detail progress patterns, including **Hand to agent**, the run log, and needs-user/result presentation, while replacing speculative or misleading copy with this ratified contract.
- Add a responsive **Connected agents** setup flow to the existing Claude Design project **Brain Buddy Design System** (`ade33f3b-852a-4b58-ae75-256156754f68`).
- Cover setup, connection test, capability disclosure, last contact, disconnect, invalid credentials, unreachable endpoint, stale connection, sent/running/needs-user/reported-complete/failed/stopped-reporting, and honest unsupported-capability fallbacks.
- Provide Max an HTTPS or native-image review surface and obtain explicit approval or rejection bound to the ratified specification hash.

## Assumptions

- The existing session authentication, owner scoping, correlation-ID envelope, account purge, responsive Task surfaces, and Expo iOS application remain the host product contracts.
- A deployment chooses its reporting window and any separately governed private-network allowance; the UI reports their effects rather than promising a universal interval.
- Connector authentication may use signed inbound events or authenticated polling, but the product contract and visible states remain identical.
- The reference connector can be exercised with deterministic fakes until a separately authorized live-provider run.

## Out of Scope

- BrainBuddy-owned agent hosting, runtime, tools, provider credentials, internet access, safety controls, cost controls, or output validation.
- Task classification, planning, decomposition, provider selection/optimization, automatic retry of accepted work, completion verification, or automatic Task completion.
- Marketplace, billing, multi-agent chains, workflow builder, capability certification, tool provisioning, collaboration, or shared connections.
- Exhaustive reducer proofs, generated Cartesian UX catalogues, account-deletion redesign, device-cleanup protocols, saved hand-off draft subsystems, or a generalized enterprise audit platform.
- Architecture, schemas, implementation algorithms, device matrices, and threat-model proof artifacts; those belong in planning and verification after design approval.
