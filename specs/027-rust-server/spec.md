# Feature Specification: Rust server

> **Superseded in part (2026-10-15)**: [ADR-0033](../../docs/decisions/0033-remove-task-priority.md) removes task priority. Every
> task-priority field, value, filter, sort and control in this document is withdrawn.

**Feature Branch**: `027-rust-server`

**Created**: 2026-10-14

**Status**: Draft

**Input**: User description: "Давай сервер на раст. Похуй, потому что реальных пользователей пока нет" (move the whole server to Rust; there are no real users yet). Agreed requirements: [intake.md](intake.md).

## Context

Spec 026 moved the task and Weekly Review rules and the native client runtime
into one shared Rust core, and kept the server on FastAPI calling that core
through PyO3. A full server move was left outside 026's first stage, not
rejected (026 `intake.md`, `plan.md`). The server therefore runs two languages,
and while `rust_core_sync` is OFF it still carries a second, Python
implementation of the task rules; the iPhone and Mac apps likewise carry both a
legacy and a shared runtime.

This feature finishes the move. The language is the owner's business decision,
not an implementation detail: the objective is **one core language** across the
server and the native runtime, removing the bridge and every second
implementation. There are no real users, so existing production data may be
erased and older client builds may break.

This feature absorbs 026's unfinished tail: the reference-device Apple pilot
runs against the new server, the new server keeps its data in the target
production store from day one with no data migration, and 026's separate
PostgreSQL stage (PR-55…57, draft PR #377) is superseded.

**Primary-loop impact**: no behavior change. Capture → atomic items →
clarify/approve → route or CRT candidate → Weekly Review → evidence must work
end to end, on every client, against the new server.

## Clarifications

### Session 2026-10-14

- Q: When production starts empty, what happens to tasks stored locally on the
  owner's iPhone/Mac, including unsynced ones? → A: They are erased; the
  updated apps start clean, and the legacy import paths are removed (FR-021).
- Q: Does the new server reach production in one switch once everything is
  ported, or surface by surface? → A: One switch. The new server is built and
  verified alongside; production never runs both servers, and no proxy splits
  traffic between them (FR-019).
- Q: May the current Python server change behavior while the port runs? → A:
  No. It is frozen to bug fixes until cutover; new server-side features land
  only in the new server after cutover (FR-022).
- Q: Does the reference-device pilot gate the production switch, or run after
  it? → A: After, in production. Cutover is gated by the automated suites; the
  pilot then runs against production (SC-004), and pilot failures are fixed
  forward on the new server.

### Session 2026-10-14 (planning review, campaign 1)

- Q: Who may create an account — today only password signup needs an invite,
  while a verified email code, Apple or Google identity creates an account
  without one (ADR-0028)? → A: Every account-creation method requires an
  invite. This is a deliberate behavior change and amends ADR-0028 (FR-007).
- Q: Is the local-data reset silent, or visible and confirmed? → A: A one-time
  confirmation screen before deletion; nothing is deleted until the owner
  confirms (FR-021). Supersedes the earlier "silent" design decision.
- Q: How long is the old server's data volume kept for rollback after
  cutover? → A: It is erased immediately after the production smoke passes;
  after that, recovery is fix-forward only (FR-019).
- Q: Where do the 026 pilot's destructive scenarios (Q03 faults, Q08 restore,
  Q10 retention/purge) run? → A: In production, like the rest of the pilot;
  each destructive step is still authorized at the moment it runs (SC-004).

### Session 2026-10-14 (planning review, campaign 2)

- Q: When is account deletion complete, given restore points that still hold
  the owner for up to seven days? → A: Data is erased at day 14; the deletion
  shows as pending until the last restore point holding the owner expires (at
  most seven more days), as ADR-0031 already states; the retention policy
  discloses it (FR-009).
- Q: What consent governs CRT node validation? → A: Explicit consent carried
  with every validation request; the server refuses without it. (Design
  check: the inspector and its toggle were removed from the web app on
  2026-09-25, #236, and no shipped client calls the route today, so this is
  an API-level rule with no UI; restoring a validation UI is out of scope.)
  (FR-011)
- Q: Must a pre-cutover CLI show the actionable update wording? → A: No. An
  old CLI gets a generic refusal and writes nothing; only updated CLIs show
  the wording (FR-018).
- Q: How long is the cutover record kept? → A: Indefinitely in the
  repository, with non-personal operational fields only; it is not part of
  any account's export or purge.

### Session 2026-10-14 (tasks)

- Q: What happens to the inventory rows that have no meaning in the Rust
  server? → A: Remove CAP-CFG-004, CAP-CFG-011, CAP-CFG-012, CAP-CLI-006,
  CAP-CLI-007 and CAP-JOB-008; port CAP-STORE-013 and CAP-CFG-092 (FR-001).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The primary loop works end to end on the new server (Priority: P1)

The owner signs in on the web, captures items, clarifies and approves them,
organizes them into projects and Tags, completes and parks tasks, and runs a
Weekly Review — all served by the new server, with no Python running in
production, and with the same results as before.

**Why this priority**: it is the product. A server that cannot run the loop is
not a replacement, whatever else it can do.

**Independent Test**: run the existing web end-to-end suite and the
primary-loop scenarios against a deployment of the new server alone, and
confirm that the production image contains no Python runtime.

**Acceptance Scenarios**:

1. **Given** an invited owner and the new server, **When** they sign up with
   the invite code by any supported method and later sign in, **Then** they get a
   session cookie with the same security properties as today and land in the
   app.
2. **Given** a signed-in owner, **When** they capture, clarify, approve, move
   to Next, tag, complete, park and review tasks on the web, **Then** every
   step behaves exactly as the current web end-to-end suite expects.
3. **Given** two owners, **When** one requests any of the other's resources by
   identifier through any interface, **Then** the response is indistinguishable
   from a resource that does not exist.
4. **Given** any request, **When** it succeeds or fails, **Then** the response
   carries a correlation ID, and an error shown to the owner exposes that ID.

---

### User Story 2 - iPhone and Mac run one runtime against the new server (Priority: P1)

The owner uses the iPhone and Mac apps offline and online. Both apps run only
the shared runtime, sync with the new server, show explicit conflicts and
recovery, and meet spec 026's responsiveness and convergence targets on the
reference devices.

**Why this priority**: native offline capture with convergent sync is what
spec 026 built; this feature must deliver it on the new server, and its
reference-device pilot is the acceptance gate 026 never closed.

**Independent Test**: after cutover, install fresh builds on the reference
iPhone 11 (iOS 26) and MacBook Air M1 (8 GB, macOS 26), sign in to production,
and run 026 quickstart Q01–Q12 plus the 026 SC-003/SC-004 measurements.
Before cutover the same flows run in automated form against a non-production
deployment.

**Acceptance Scenarios**:

1. **Given** a fresh install, **When** the owner signs in by any supported
   method, **Then** the app works on the shared runtime with no option or code
   path to select another runtime.
2. **Given** both devices offline with edits to the same task, **When** they
   reconnect, **Then** both converge and the conflict is explicit with no text
   lost (026 Q02).
3. **Given** a lost response, a killed app or a server restart mid-sync,
   **When** the client retries, **Then** no command is applied twice and none is
   lost (026 Q03).
4. **Given** the reference devices, **When** the 026 measurements run, **Then**
   026 SC-003 and SC-004 are met.

---

### User Story 3 - Cutover: production runs only the new server (Priority: P1)

The owner switches production on Fly.io to the new server, starting from an
empty store, after giving explicit authorization to erase the current data. The
old server is shut down and nothing in production depends on it.

**Why this priority**: until production runs the new server, the move has not
happened; two live servers would be worse than one.

**Independent Test**: after cutover, read back the production deployment and
confirm only the new server serves `/api`, the old app is stopped, and a smoke
run of the primary loop passes.

**Acceptance Scenarios**:

1. **Given** a release candidate that passed every gate, **When** the owner
   authorizes erasing production data and the switch, **Then** the new server
   starts on an empty store and the old server stops accepting writes before the
   new one accepts any.
2. **Given** an older client build, **When** it calls the new server, **Then**
   it receives a clear "update required" refusal and no data is written or
   corrupted.
3. **Given** a failed cutover smoke check before the old data is erased,
   **When** the owner rolls back, **Then** the new server stops accepting
   writes first and the old server then serves the pre-cutover state.
4. **Given** a passed production smoke, **When** the owner authorizes the
   erase, **Then** the old server's data is erased and later failures are
   fixed forward.

---

### User Story 4 - Account, privacy and consent carry over unchanged (Priority: P2)

The owner edits their profile, email and password, exports a ZIP of their
data, requests deletion with a 14-day grace period, and their data is purged;
AI features run only with consent; retention limits apply as documented.

**Why this priority**: these are obligations, not features. They are always on
and must never be feature-flagged, so they cannot be left behind.

**Independent Test**: run the account export, deletion, cancel-deletion and
purge flows and the retention sweeps against the new server and compare the
outcomes with `docs/data-retention.md`.

**Acceptance Scenarios**:

1. **Given** an owner with tasks, Review history, canvas data and voice
   operations, **When** they export, **Then** the ZIP contains every category
   the current export contains.
2. **Given** a deletion request, **When** the 14-day grace period ends, **Then**
   every owner-linked live record is purged, including sync receipts, feed,
   jobs and stored audio, and the deletion shows as pending until the last
   restore point holding the owner expires (at most seven days later), as 026
   and ADR-0031 require; only then is it reported complete.
3. **Given** AI consent is declined, **When** the owner requests an AI
   validation or suggestion, **Then** the request is refused without calling a
   provider.

---

### User Story 5 - Canvas, voice and AI work as before (Priority: P2)

The owner edits a CRT canvas, runs AI validation with consent, and records a
voice brain dump that is transcribed and split into items, with the same
providers and cost caps as today.

**Why this priority**: these surfaces are in the product and must be ported
1:1, but the loop survives a short gap in them better than in tasks or sync.

**Independent Test**: run the existing canvas and voice end-to-end scenarios
and the CRT revision/idempotency tests against the new server.

**Acceptance Scenarios**:

1. **Given** a canvas of about 200 nodes, **When** the owner edits nodes and
   relations, **Then** revisions and idempotency follow ADR-0026 and the canvas
   stays as responsive as today.
2. **Given** a voice recording, **When** the owner submits it, **Then** it is
   transcribed by the configured provider within the configured cost caps and
   produces capture items as today.

---

### User Story 6 - Agents, MCP and the agent CLI keep working (Priority: P2)

External agents exchange work through the A2A relay; the owner's tools use the
task MCP server; the agent CLI signs in with the device grant.

**Why this priority**: these integrations exist and the owner chose to port
everything; they depend on the task core landing first.

**Independent Test**: run the existing A2A contract tests, the MCP tool tests
and the CLI device sign-in flow against the new server.

**Acceptance Scenarios**:

1. **Given** a registered agent, **When** it exchanges messages through the
   relay, **Then** the spec 014 wire contract, egress limits and secret
   handling hold, and agent results never change tasks without the required
   confirmation.
2. **Given** an MCP client authorized for an owner, **When** it lists and
   changes tasks, **Then** it sees only that owner's tasks and every write goes
   through the same command boundary as other clients.

---

### User Story 7 - The operator can run the service (Priority: P3)

The operator mints invites, manages users in the admin portal, toggles live
feature flags, and diagnoses problems from logs keyed by correlation ID.

**Why this priority**: needed to run a real service, but the owner is the only
operator and can tolerate a brief gap.

**Independent Test**: mint an invite, use the admin portal's user CRUD and
flag toggles, and trace a failed request from its correlation ID to its log
lines.

**Acceptance Scenarios**:

1. **Given** operator access, **When** they mint an invite from the command
   line, **Then** the code works for exactly one signup as today.
2. **Given** the admin portal, **When** the operator toggles a live feature
   flag, **Then** the change takes effect without a redeploy, as today.

---

### Edge Cases

- An older iPhone, Mac, web, CLI or MCP client calls the new server: it is
  refused and nothing is read or written; updated-format wording reaches old
  iPhone/Mac/web builds through the server message, while an old CLI shows
  its generic refusal (owner decision, FR-018).
- A device holds local or unsynced tasks from the old server at cutover: the
  owner sees a confirmation naming what will be deleted; nothing is deleted
  until they confirm, and pre-cutover data never reaches the new server
  (FR-021). An updated app that still reaches the old server deletes nothing.
- The reset is interrupted after confirmation (app killed, disk error): it
  resumes on next launch without asking again; no network request is made
  until it completes.
- A request or background job is in flight when the old server stops: it is
  either completed before the switch or cleanly failed; nothing is written to
  the old store after the new server accepts writes.
- A provider (AI or speech-to-text) key is missing, fails or exceeds its cost
  cap: the owner sees an actionable error with a correlation ID; no item is
  silently dropped.
- AI consent is revoked during a running request: the result is not applied.
- Two server instances start during a deploy: background jobs are not run twice
  and fenced writers stay fenced (026 durable job authority).
- Account deletion begins while sync or a job is running for that owner: job
  writes stop and deletion completes as today.
- A canvas near 200 nodes or a task store of 10,000 tasks: no responsiveness
  regression against the current server.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The new server MUST provide every capability the current server
  provides — every HTTP route, sync endpoint, MCP tool, device/CLI sign-in
  flow, A2A relay operation, background job and operator command line. A
  capability inventory MUST be recorded before porting and every item MUST
  have a disposition: **port** (proven by passing evidence), **change** (an
  owner-approved behavior change, proven on the new server only) or
  **remove** (owner-approved, with the reason). Owner-approved changes: invite
  gating for every signup method (FR-007); the server-side consent check for
  CRT node validation (FR-011); the MCP endpoint moving to a new path with the
  old path refusing (FR-018). Owner-approved removals: the Python
  entry point and runtime, the in-process Python↔Rust bridge, the legacy JSON
  import at startup, the data-directory setting (stores move to PostgreSQL
  and object storage), the durable-scheduler and test-loop switches (one
  durable mode), the two test-only operator commands (replaced by the test
  control API) and the CRT receipt reconciliation step (receipt and write
  commit in one transaction); the provider-key indirection and validation
  provider registry are ported (owner, 2026-10-14).
- **FR-002**: The production server MUST run without a Python runtime, and the
  Python server and the Python↔Rust bridge MUST be removed from the product.
  Repository tooling outside the server (for example `scripts/`) MAY stay
  Python.
- **FR-003**: Task and Weekly Review rules MUST have exactly one implementation
  on the server: the shared core that the native runtime uses. No second
  implementation or runtime switch for those rules MAY remain.
- **FR-004**: The iPhone and Mac apps MUST run only the shared runtime. The
  legacy reducer, the legacy data engine and every legacy/shared runtime
  selection MUST be removed.
- **FR-005**: User-visible behavior MUST be unchanged except for the
  owner-approved changes in FR-007 (invite gating), FR-011 (server-side
  consent for CRT validation), FR-018 (update required, MCP path) and FR-021
  (fresh-start confirmation). The external API MAY be
  redesigned, provided the web app, the iPhone and Mac apps, the CLI and the
  MCP integration are updated in the same release and the existing web
  end-to-end scenarios still pass.
- **FR-006**: Every sync guarantee of spec 026 MUST hold on the new server:
  durable idempotent commands with receipts, atomic changes for every writer,
  explicit conflicts without lost text, snapshot/delta recovery, restore and
  control-ledger replay, and the frozen sync v1 contract unless the contract is
  re-versioned together with every client.
- **FR-007**: Sign-in MUST support the same methods as today (password, email
  code, Sign in with Apple, Google, browser grant, device grant for the CLI).
  **Creating** an account by any method MUST require a valid unused invite;
  signing in to an existing account MUST NOT. This changes ADR-0028's
  provider-signup behavior (owner decision, 2026-10-14). The session cookie
  MUST stay opaque, `HttpOnly`, `SameSite=Lax` and `Secure` in production.
- **FR-008**: Every owner-scoped resource MUST be filtered by owner on every
  interface; another owner's resource MUST be indistinguishable from a missing
  one.
- **FR-009**: Account management MUST be ported 1:1 — profile, email and
  password changes, ZIP export with the same categories, 14-day-grace deletion
  and purge — and MUST never be feature-flagged. Live data is erased when the
  grace period ends; the deletion is reported complete only after the last
  restore point holding the owner has expired (at most seven days later), and
  the retention policy says so.
- **FR-010**: Retention MUST follow `docs/data-retention.md` and ADR-0031's
  command-metadata rules; no record MAY be kept longer than today.
- **FR-011**: Every AI feature that sends content to a provider — including
  CRT node validation, Review suggestions, navigator, title completion and
  voice transcription — MUST require current explicit consent checked on the
  server; declining MUST refuse without calling a provider; a result that
  returns after consent is revoked or the owner's deletion begins MUST be
  discarded, not stored or applied; the same providers and cost caps MUST
  apply.
- **FR-012**: Voice brain dump MUST use the same speech-to-text providers,
  limits and retention, and produce capture items as today. Accepted audio
  MUST stay available to whichever server process handles the operation,
  survive restarts and deploys until its retention ends, and be deleted by
  retention and account purge.
- **FR-013**: The CRT canvas MUST keep the ADR-0026 revision and idempotency
  protocol and AI validation.
- **FR-014**: The A2A relay MUST keep the spec 014 wire contract, egress
  controls and secret handling; agent results MUST NOT change tasks without the
  required confirmation.
- **FR-015**: The admin portal, operator user management, invite minting and
  live feature flags MUST work as today.
- **FR-016**: Every response MUST carry `X-Correlation-ID`; server logs MUST be
  keyed by it; errors MUST be actionable and MUST NOT log user content.
- **FR-017**: Background jobs MUST keep 026's durable, fenced, owner-aware
  execution: no job runs twice across instances, and job writes stop once an
  owner's deletion begins.
- **FR-018**: A first-party client build (web, iPhone, Mac, CLI) from before
  the release MUST be refused with an actionable "update required" error and
  MUST NOT read or write data; an older MCP configuration MUST be refused
  before any tool runs. Endpoints that first-party builds do not call —
  health checks, identity-provider callbacks and notifications, A2A peer
  callbacks, public API documentation — MUST keep working. Updated clients
  MUST show the actionable wording; a pre-cutover CLI MAY show only its
  generic refusal (owner decision), provided nothing is written.
- **FR-019**: Production MUST switch to the new server in a single cutover once
  every capability-inventory item has met its disposition (FR-001); the two servers MUST never serve
  production at the same time. The switch MUST be gated by the automated
  suites (SC-002, SC-003) and a production smoke run of the primary loop.
  Cutover MUST start the new server on an empty production store.
  The old server MUST stop accepting writes before the new one accepts any;
  rolling back MUST likewise stop the new server before the old one accepts
  writes. The rollback procedure MUST be documented and rehearsed before
  cutover; it is available only until the old data is erased. The old server's
  data MUST be erased immediately after the production smoke passes, with the
  owner's explicit authorization at that moment; from then on recovery is
  fix-forward on the new server.
- **FR-020**: The web frontend MUST keep its UI; only its server client MAY
  change. The frontend stays served from the same origin with `/api` proxied,
  as today.
- **FR-021**: When an updated iPhone or Mac app first reaches the new server
  and its earlier local data holds tasks, waiting changes or drafts, it MUST
  show a one-time confirmation that names what will be deleted, and MUST
  delete it only after the owner confirms; earlier data with none of those
  (empty store, caches, the old session) is removed without asking; until then the
  old data stays untouched and the app neither syncs nor signs in. After
  deletion the app starts clean, and no pre-cutover local data MAY reach the
  new server. An app still talking to the old server MUST NOT delete
  anything. The legacy store import paths (026 PR-41/42) MUST be removed.
- **FR-022**: From this specification's acceptance until cutover, the current
  server MUST change only to fix defects or to add test-only seams that exist
  solely when it runs in its test environment (the test control API); it MUST
  NOT gain new product capabilities, so the capability inventory stays fixed. New server-side features land only in
  the new server after cutover.

### Key Entities

- **Capability inventory**: every externally reachable behavior of the current
  server (route, tool, flow, job, operator command), its owning surface, and
  the test that proves it on the new server.
- **Release epoch**: the version line that separates clients compatible with
  the new server from older builds that must be refused.
- **Cutover record**: the authorization to erase, the exact candidate version,
  the stop/start order, smoke results and the rollback outcome.

All product entities (owner, session, task, project, Tag, Review, canvas,
voice operation, agent, job, receipt, feed) are unchanged and defined by their
existing specifications.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The production server image contains 0 Python interpreters or
  Python packages, and the server source contains 0 Python files.
- **SC-002**: 100% of the existing web end-to-end scenarios pass against the
  new server.
- **SC-003**: 100% of capability-inventory items carry a disposition (FR-001);
  every **port** item has passing evidence on both servers, every **change**
  item on the new server, and every **remove** item an owner-approved reason.
- **SC-004**: Spec 026 quickstart Q01–Q12 pass on the reference iPhone 11 and
  MacBook Air M1 against the new server in production after cutover and are
  recorded, including the destructive Q03, Q08 and Q10 (each destructive step
  authorized when it runs), except Q06 (legacy store import), which FR-021
  retires; 026 SC-003 (p95 ≤
  50 ms per local operation) and SC-004 (p95 ≤ 2 s convergence, ≤ 60 s with a
  lost hint) are met.
- **SC-005**: Owners see no slowdown: for the primary-loop web flows, p95
  response time on the same hardware is no worse than 110% of the current
  server's.
- **SC-006**: The server has exactly one implementation of the task and
  Weekly Review rules, and each Apple app has exactly one runtime (0
  runtime-selection sites).
- **SC-007**: For 7 consecutive days after cutover, production is served only
  by the new server, and a daily reconciliation shows 0 lost or duplicated
  task changes: every accepted command has exactly one recorded outcome and
  one change-feed entry, every change-feed entry traces to one accepted
  command, and the reference devices' pending queues drain to zero after
  each day's pilot activity.

## Assumptions

- There are no real users; erasing production data and breaking older client
  builds are acceptable (owner, 2026-10-14). The erase itself is still an
  ASK-class action authorized separately at cutover.
- No deadline; delivery is many small parallel slices, as in spec 026.
- Spec 026's accepted decisions (ADR-0031, the frozen sync v1 contract,
  retention amendments, Constitution IV command-ID exception) remain in force
  except where this feature supersedes 026's server language and its separate
  PostgreSQL stage. 026 is closed as superseded by this feature.
- The production store of the new server is the target store chosen by 026;
  the architecture choice belongs to `/speckit-plan`.
- Repository quality gates (coverage floor, mutation gate, Allure taxonomy and
  quality gate, requirement coverage) apply to the new server in an equivalent
  form; their mechanics are decided in the plan.
- Out of scope (confirmed by the owner): rewriting the web frontend or offline
  web/WASM; any new user-facing functionality beyond the four owner-approved
  changes in FR-005; new platforms (Android,
  Windows, Linux); changing AI/speech providers, cost caps or the Fly.io host.
