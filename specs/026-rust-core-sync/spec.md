# Feature Specification: shared Rust core and custom synchronization

**Feature Branch**: `026-rust-core-sync`

**Created**: 2026-10-08

**Status**: Complete proposal for owner review, updated 2026-10-09. Rust and custom sync are selected; the specific design, governance amendments, and PR boundaries remain subject to the explicit decisions in [approval.md](approval.md). This is a specification, not implementation acceptance.

**Input** (translated): “Rust and custom sync look promising. We need a specification for this solution.” Basis: [intake.md](intake.md). Technical design: [plan.md](plan.md), [sync-v1.md](contracts/sync-v1.md). This document defines the behavior and outcome boundary.

## User Scenarios & Testing *(mandatory)*

The primary capture → clarify/approve → organise → review → evidence cycle is preserved. Task capture and organization become consistent across native devices, and synchronization no longer depends on separate client implementations. AI proposals and agent results still do not change tasks without the required confirmation. The first rollout covers iOS, macOS, and the server; Android, Windows, and Linux use the same contract in later stages.

### User Story 1 — Capture a task offline and continue on another device (Priority: P1)

The user captures a task, changes its list, and adds a note even without a connection. The app immediately displays the result and saves it before the process exits. When connectivity returns, the second device receives these changes without manual export.

**Why this priority**: a lost capture undermines trust in the task system; a network request must not stand in the way of capture.

**Independent Test**: disconnect an iPhone, create and edit tasks, terminate the process, reopen the app, then reconnect and compare the Mac and server state.

**Acceptance Scenarios**:

1. **Given** loaded local data, **When** there is no network, **Then** viewing, creation, editing, and existing GTD commands work; a confirmed local write survives a restart.
2. **Given** the server accepted a change but the response was lost, **When** the client retries submission after a restart, **Then** the task and related effects are created in the system once.
3. **Given** several actions on a new task, **When** they reach the server, **Then** dependencies are preserved: edits are neither lost nor executed before creation.
4. **Given** the user has not signed in, **When** they work locally, **Then** no network or server is required; subsequent sign-in offers an explicit merge with the account and does not automatically erase local records.

### User Story 2 — Resolve a conflict without losing personal text (Priority: P1)

If the iPhone and Mac independently change the same task, the system either applies a safe rule or shows the user both versions and preserves their work until they choose. The latest time on a device clock does not determine the winner.

**Independent Test**: change the same title on two disconnected devices, reconnect in both orders, and choose the final version.

**Acceptance Scenarios**:

1. **Given** two different titles derived from the same base version, **When** the first change has already been accepted, **Then** the second becomes an explicit conflict; the original and local text remain available until resolution.
2. **Given** a task was completed on one device and intentionally reopened on another, **When** an old offline completion command arrives, **Then** it does not automatically undo the reopening.
3. **Given** a record was deleted on the server by a valid existing command, **When** an offline edit to that record arrives, **Then** the record is not resurrected; the local text can be saved as a separate new record only through an explicit action.
4. **Given** a conflict on one task, **When** the user works on another, **Then** the app remains usable and independent changes can synchronize.

### User Story 3 — Survive an update, extended offline use, and session expiry (Priority: P1)

A client update or restoration of a full copy from the server must not destroy changes that have not yet been sent. The user understands what is saved locally, what the server has confirmed, and what requires their action.

**Independent Test**: update a client with a populated store and queue, including a change with an unknown outcome; verify recovery after an expired cursor and sign-in to a different account.

**Acceptance Scenarios**:

1. **Given** a very old cursor, **When** a fresh data download is required, **Then** the queue and drafts are preserved separately, confirmed commands are not applied again, and disputed changes are visible.
2. **Given** the session has expired, **When** submission is rejected, **Then** the queue is preserved and sign-in is available again; the queue is not sent as another user.
3. **Given** insufficient space or a corrupted import, **When** migration runs, **Then** the old file remains intact, the new store does not become active, and a specific error is shown.
4. **Given** an old submitted command has no provable outcome, **When** migration runs, **Then** the system does not create a new copy based on matching title and time.

### User Story 4 — Receive consistent rules and background results (Priority: P2)

Action availability, project behavior, and Weekly Review rules are consistent across devices. The server executes jobs assigned to it regardless of whether the phone app is open and returns the result through normal synchronization.

**Independent Test**: run normative GTD and review examples through the server and both Apple clients; stop a worker after a job is accepted and verify a safe retry.

**Acceptance Scenarios**:

1. **Given** identical domain inputs, execution inputs, and rule version, **When** Apple and server adapters evaluate a command, **Then** validity and domain result match the same normative example.
2. **Given** a project with member tasks, **When** it is archived and restored, **Then** membership and historical markers follow ADR-0020 on every device.
3. **Given** an automatic park and a valid earlier offline human decision, **When** the decision arrives, **Then** ADR-0027's yield rule takes precedence without undoing an intervening manual action.
4. **Given** a job whose worker lost its lease after submission, **When** another worker retries, **Then** an internal effect occurs once and an unprovable external outcome remains explicitly uncertain.

### User Story 5 — Use AI with a clear data boundary (Priority: P2)

The app uses a suitable local model when it is available and capable of the task. If no model is available, the user can authorize a specific remote path or continue manually.

**Independent Test**: exercise one feature with an available and unavailable local model, prohibited and authorized remote execution, an invalid response, and cancellation.

**Acceptance Scenarios**:

1. **Given** “on-device only” mode, **When** a model is absent, memory is insufficient, or inference fails, **Then** no content is transmitted for inference and manual task work remains available.
2. **Given** a remote suggestion request, **When** consent is requested, **Then** its recipient and fields are shown; revocation prevents requests that have not started and further transmission.
3. **Given** a model response, **When** it is presented, **Then** it remains a proposal; only explicit confirmation of valid actions submits ordinary commands, and invalid output changes no task.
4. **Given** an AgentRun success, **When** its result arrives, **Then** the linked task remains unchanged until an independently authorized Tasks command is confirmed.

### Edge Cases

Verify: duplicate delivery; reordered responses; a crash between a write and its response; offline creation and edits; dependency on a rejected command; access revocation; different accounts; an incompatible client version; a schema change while offline; an expired snapshot; a device clock ahead of the server; a DST transition; a full disk; concurrent app/widget/intents; an old device backup; account deletion with a queue; a disabled feature flag; AI cancellation after remote processing begins; an unknown external-call outcome. A state with an unresolved error or incomplete bootstrap must not be labeled “synchronized”.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Existing local task commands MUST save the result and synchronization intent atomically; local success is acknowledged after a durable write.
- **FR-002**: All native clients and the server MUST use one normative implementation of task, project, Tag, and native-task review rules. Presentation, server permissions, and integrations remain separate responsibilities.
- **FR-003**: Account-less operation MUST be preserved. Signing in with local data requires a clear merge choice; signing out warns about losing the local copy and does not transfer the queue between accounts.
- **FR-004**: Connected active devices MUST automatically converge to the state accepted by the server, including related records and deletions, when there are no new commands and conflicts have been resolved.
- **FR-005**: Retrying the same command with the same content MUST return the known outcome without repeating the mutation. An unknown outcome does not permit automatically changing the command identifier.
- **FR-006**: All related changes from one domain operation MUST become visible atomically on the server and client; synchronization progress is saved together with them.
- **FR-007**: A concurrent incompatible edit MUST be preserved as a resolvable conflict, with the local intent and current available data. The first version may conservatively conflict the entire edited entity.
- **FR-008**: Deletion MUST prevent automatic resurrection by a late edit. This requirement protects existing deletable entities; a new task-deletion interface is outside the first phase.
- **FR-009**: Task ordering and existing move operations MUST preserve accepted semantics. This migration does not add a new manual reorder API or change completed-placement behavior.
- **FR-010**: Reset/bootstrap/restore MUST preserve pending commands and drafts until a provable resolution, prevent regression to old responses, and allow recovery after interruption.
- **FR-011**: The server MUST check current authority on reads and writes; the client MUST separate data by account and session generation. A late response from an old session does not change the new workspace.
- **FR-012**: An incompatible version MUST result in an explicit update requirement while preserving data. Commands of unknown types are neither partially executed nor removed from the queue.
- **FR-013**: Migration MUST account for all existing fields, identifiers, relationships, review state, local-only data, and the outbox. Uncertain old submissions require reconciliation rather than heuristic recreation.
- **FR-014**: Older supported clients, web, CLI, MCP, workflows, and background writers MUST pass through the same write boundary and publish changes for the new sync; hidden parallel writers are prohibited.
- **FR-015**: Server jobs MUST have durable status, a lease, bounded retries, and protection against a stale executor. External effects have a separate retry policy and are not given a false exactly-once guarantee.
- **FR-016**: Formulations, review decisions, receipts, auto-park, undo, and clock bookkeeping MUST preserve accepted ADR-0027 semantics, including the special resolution of offline decisions.
- **FR-017**: Dates MUST distinguish a calendar day from an instant; rules dependent on local time use the specified time zone. Migration preserves current semantics without introducing a new recurrence product.
- **FR-018**: AI policy MUST prefer a suitable local executor, considering language, capabilities, memory, and availability. Basic task functionality MUST work without AI.
- **FR-019**: Remote AI MUST have current consent for the selected recipient, the minimum data set, and configured credentials. Network task synchronization does not imply consent to AI processing.
- **FR-020**: AI output MUST pass structural and domain-rule validation and remain a proposal until the required confirmation. The ADR-0002 confirmation/operation contract is preserved.
- **FR-021**: AgentRun MUST remain separate from Task. Existing A2A/MCP authority, uncertainty, and lookup contracts are preserved; permissions come from the granted capability rather than model text.
- **FR-022**: New local and server records MUST be covered by export, deletion, retention, and recovery policies. User text, audio, credentials, and fingerprints must not appear in diagnostics.
- **FR-023**: The UI MUST distinguish locally saved, pending submission, synchronized, conflict, authorization, unsupported version, and recovery states; messages provide an action and a safe reference ID.
- **FR-024**: The web MUST preserve existing workflows through the server contract. Fully offline web support and moving CRT into this sync are outside the first phase.
- **FR-025**: Concurrent app/widget/intents MUST not corrupt the store or queue. The widget does not receive a separate sync engine or its own copy of the rules.
- **FR-026**: Local operations and background change application MUST meet measurable budgets, avoid blocking the UI, and preserve current CRT responsiveness at 200 nodes.

### Key Entities

| Entity | Purpose |
| --- | --- |
| Task, Project, Tag, and child records | Existing domain data; the owner and identifiers are preserved |
| Review state | Settings, formulation clock, decisions, acknowledgements, and receipts of the existing review |
| Command | Immutable intent for one action, with dependencies and preconditions |
| Command receipt | Durable outcome of command adjudication, independent of response delivery |
| Change transaction and cursor | An atomic set of accepted changes and the client's position in the stream |
| Confirmed base, pending, and draft | The last accepted copy, durable local actions, and the editor's unsaved content |
| Sync issue | A persisted problem applying a specific intent and a way to resolve it |
| Job, Proposal, AgentRun | Background work, a model proposal, and agent execution; not Task states |

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All normative examples of the selected existing rules produce identical results on the server, iOS, and macOS; coverage includes the four GTD lists, lifecycle, archive, Smart Add, and review.
- **SC-002**: Offline, crash, duplicate, and lost-response scenarios have no lost confirmed local changes or repeated accepted mutations; every rejection is accessible to the user.
- **SC-003**: For 10,000 tasks and 100 pending changes, local writes complete at p95 ≤ 50 ms and the list remains responsive. The reference phone is iPhone 11 on iOS 26; the reference Mac is MacBook Air M1 with 8 GB on macOS 26. The release-build workload, sampling, and UI-blocking threshold are defined in [quickstart.md](quickstart.md); a faster device or simulator cannot replace the phone measurement.
- **SC-004**: For two active clients, RTT ≤ 100 ms, no throttling, and ≤ 100 pending commands, convergence after the last accepted command takes p95 ≤ 2 s with the notification channel enabled. If a hint is lost under the same conditions, the update is applied and visible in each active client's projection within ≤ 60 s of the server commit. Active fallback polls start at most 30 s apart, including jitter, leaving up to 30 s for requests, catch-up and local application. Mobile OS background restrictions are outside this promise.
- **SC-005**: Import and restoration of the reference dataset preserve all data and relationships or stop before switching stores; uncertain submissions do not create duplicates.
- **SC-006**: AI-consent refusal scenarios send no requests containing user content to a prohibited recipient; an invalid model response does not change tasks.
- **SC-007**: Loss of a worker lease, job retries, and backup restoration do not result in repeated internal effects or access by another account; uncertain external effects remain visible.
- **SC-008**: On both Apple clients, a representative user completes the status, conflict, and interrupted-recovery journeys in [quickstart.md](quickstart.md) without editing files or coaching. Every in-scope action is reachable with keyboard/VoiceOver, all displayed states match [design.md](design.md), and existing Mac status thresholds are preserved.

## Assumptions

The user has accepted the choice of Rust and custom sync. The iOS/macOS/backend first phase is a technical proposal that uses the already shared Apple foundation. New platforms are a required architectural direction, but not an implicit requirement for simultaneous launch.

In the first version, the scope is the existing owner's private workspace. A device is not an owner. Sharing/assignee, a separate billing model, and E2EE are not considered agreed requirements. The current trusted-server model is preserved; if E2EE is needed, sync validation and server AI must be reconsidered before implementation.

The SC-003/004 budgets, reference devices, and retention in the technical contract are concrete proposed acceptance conditions, not measured results. They do not drop any currently supported platform. There is no promise of precise background cron on a phone or of a local model on every device/language. The first AI integration uses the existing Weekly Review suggestion capability; it adds no new model download product or general autonomous agent.

## Clarifications

### Session 2026-10-09

- The owner requested completion of the specification under Spec Kit and repository rules. This authorizes completing and reviewing the documents, not implementing or deploying the migration.
- First acceptance boundary: iOS ↔ server ↔ macOS, compatible existing web/CLI/MCP/Capture/Review writers, and the separate post-pilot PostgreSQL migration. Android, Windows, and Linux remain architectural consumers requiring subsequent platform specifications and acceptance; no new shell is required to pass this package.
- Concrete recommendations replace technical placeholders. [approval.md](approval.md) separates those recommendations from actual owner answers and names the remaining human decisions. No approval has been invented.
