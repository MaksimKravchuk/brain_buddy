# Feature Specification: Expo mobile first slice

**Feature Branch**: `wt/t_d081befc`

**Created**: 2026-07-20

**Status**: Ready for implementation handoff

**Input**: Create the first BrainBuddy Expo/React Native mobile application slice with secure session establishment, native GTD task access, and explicit-confirmation Voice Brain Dump integration while preserving accepted design classifications and non-goals.

## Clarifications

### Session 2026-07-20

- Q: Which user journeys make the smallest useful mobile slice? → A: Existing-account sign-in, truthful GTD projections/actions, and foreground Voice Brain Dump through explicit confirmation.
- Q: Must the first slice record while the app is backgrounded? → A: No; foreground recording only, with interruption recovery for the last durable local/server checkpoint.
- Q: Which CloudDesign mobile frames are first-slice commitments? → A: M-01/M-02/M-03/M-05/M-06 plus bounded M-04/M-07/M-08 projections; M-09 and unsupported controls remain deferred.
- Q: Does the mobile client introduce a new identity/token ownership model? → A: No; Identity keeps server-owned opaque revocable sessions and mobile receives no JWT or self-contained ownership claims.
- Q: Is mobile account creation part of this slice? → A: No; users sign in with an existing invite-created or seeded account.
- Q: Does post-stop Expo upload replace ADR-0002's live-proposal primary UX? → A: No; it is a first-mobile-slice capture-timing refinement only. ADR-0002 still governs the shared substrate, canonical batch confirmation, consent/retention, and long-term live target.
- Q: May a recovered recording rely on a stored consent boolean? → A: No; resume compares an unexpired decision's policy version/provider categories with fresh server state and requires re-consent on expiry, withdrawal, or configuration change.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Establish and restore a secure mobile session (Priority: P1)

A user with an existing BrainBuddy account signs in on an iOS or Android device, closes and reopens the app, and returns to their owner-scoped task workspace without re-entering credentials until the server session expires or is revoked.

**Why this priority**: Every task and voice operation is owner-scoped. A mobile client cannot safely use any product capability until it establishes the existing server-owned identity without exposing a reusable credential to ordinary app storage or logs.

**Independent Test**: Sign in on a clean device installation, restart the app, load the same user's task list, sign out, and prove the previously issued credential can no longer read `/me` or any task.

**Acceptance Scenarios**:

1. **Given** a valid existing account, **When** the user signs in, **Then** the app enters the task workspace and stores only the opaque revocable session credential in device-protected credential storage.
2. **Given** a valid stored session, **When** the app restarts, **Then** it validates the session with the server and restores the owner-scoped workspace without displaying or logging the credential.
3. **Given** an expired, revoked, missing, or undecryptable credential, **When** the app starts or receives an authentication failure, **Then** it removes local credential state and returns to sign-in without exposing cached user content; any durable unconfirmed recording is quarantined until the same owner reauthenticates or explicitly discards it.
4. **Given** a signed-in user, **When** they sign out, **Then** an active unconfirmed recording requires an explicit cancel-sign-out or discard-and-sign-out choice, the server session is revoked when reachable, the local credential and visible owner state are removed even if the network response fails, and subsequent protected requests require sign-in.
5. **Given** invalid credentials or a rate limit, **When** sign-in fails, **Then** the app shows a generic actionable error and correlation reference without revealing whether the account exists.

---

### User Story 2 - Use the canonical GTD workspace from mobile (Priority: P1)

A signed-in user can move through the four open GTD lists, Project and Tag task projections, inspect a bounded task detail, capture a plain Inbox task, complete an open task, and explicitly choose a destination when reopening terminal history.

**Why this priority**: The mobile application must be a client of BrainBuddy's canonical Tasks module, not a voice-only silo or a second local task store.

**Independent Test**: Create an Inbox task on mobile, find it in Inbox after restart, complete it, reopen it to a named open list, and observe the same owner-scoped state from the existing web client.

**Acceptance Scenarios**:

1. **Given** a signed-in user, **When** the workspace loads, **Then** Next actions appears first and the drawer exposes exactly Inbox, Next actions, Waiting for, Someday / maybe, Projects, Tags, truthful open counts, Voice Brain Dump, and a non-interactive Weekly Review deferral.
2. **Given** more than one page of matching tasks, **When** the user continues the list, **Then** the app uses server pagination and never presents the first page as the complete result.
3. **Given** a list, Project, or Tag projection, **When** the user selects a task, **Then** a bounded mobile detail shows canonical title, details, lifecycle, Project, Tags, due date, Priority, and Waiting metadata that the server returned.
4. **Given** a plain title, **When** the user captures it from mobile, **Then** exactly one canonical Inbox task is created; Smart Add syntax is treated literally in this slice.
5. **Given** an open task, **When** the user completes it, **Then** the server result replaces the visible projection and survives app restart and web reload.
6. **Given** a Completed or Cancelled task, **When** the user reopens it, **Then** they must select Inbox, Next, Waiting, or Someday; Waiting additionally requires non-blank `waiting_for`.
7. **Given** a stale revision or lost connection during a mutation, **When** the request fails, **Then** the app preserves the user's intent, refetches canonical state where safe, and never reports optimistic success.

---

### User Story 3 - Record, review, and confirm a Voice Brain Dump (Priority: P1)

A signed-in user records a foreground voice dump, consents separately to microphone access and current provider-category-bound external processing, safely stops and uploads the durable local recording, observes persisted processing/recovery and raw-audio retention state, reviews proposals, edits or removes them, freezes the selected proposal revision, and explicitly confirms that batch of additions to Inbox.

**Why this priority**: Voice capture and review are the primary mobile-first value loop. The slice is useful only if interruptions and retries cannot lose the recording silently or create tasks before the user confirms them.

**Independent Test**: Record a deterministic short utterance on a device, stop, resume after an app restart during upload or processing, revalidate current consent, remove one proposal, edit another, freeze and confirm, delete retained raw audio, and prove exactly the confirmed title-only Inbox tasks exist after retry and web reload.

**Acceptance Scenarios**:

1. **Given** no microphone permission, **When** the user starts Brain Dump, **Then** the app requests permission before recording and explains denial without creating a server operation or uploading audio.
2. **Given** microphone permission but no unexpired external-processing grant matching the server's current policy version and required provider categories, **When** no local provider is configured, **Then** recording may not upload or invoke a provider and the limitation/re-consent action is visible.
3. **Given** granted permission and consent, **When** recording starts, **Then** local duration and waveform feedback appear promptly, the recording is written to durable app storage, and no canonical Task is created.
4. **Given** the foreground app is interrupted, **When** the user returns, **Then** the app either resumes from the last durable local/server checkpoint or presents an explicit salvage/discard choice; closing the UI never implies confirmation or cancellation.
5. **Given** a stopped recording, **When** upload begins, **Then** numbered chunks are hash-identified, acknowledged chunks are not duplicated, conflicts are visible, and sealing occurs only after the complete manifest is accepted.
6. **Given** a recovered operation, expired grant, consent withdrawal, or changed processing policy/provider category, **When** the app restarts or reconnects, **Then** it refetches server policy/operation state before upload/seal/retry, fails closed when mismatched, and schedules uncommitted local/server artifacts for honest pending/deleted cleanup after withdrawal.
7. **Given** sealing or provider processing, **When** the user waits or restarts the app, **Then** truthful stage, retry, cancellation, correlation, raw-audio state, and `retained_until` information is restored from the persisted operation projection.
8. **Given** proposals ready for review, **When** the user edits or removes items, **Then** append-only user decisions survive refresh/reconciliation, supersede any previously frozen batch, and open conflicts block a new freeze.
9. **Given** an eligible selected proposal revision, **When** the user freezes and confirms it, **Then** only that immutable batch's title-only Inbox actions are created, no due date/Project/Tag/Priority is inferred, and deterministic child receipts prevent duplicate Tasks.
10. **Given** processing has reached Review or a terminal/cancelled state, **When** raw audio is retained, **Then** the user sees its retention deadline and can request idempotent delete-now without deleting confirmed Tasks or required non-audio provenance.
11. **Given** partial confirmation or cancellation, **When** some action already succeeded, **Then** the app reports the actual per-action result and does not promise an atomic rollback.
12. **Given** an active v1 operation with no original audio, **When** it is first loaded by the v2 backend, **Then** it is imported exactly once with preserved IDs, title locks, and remove tombstones, remains visibly `provisional_only`, cannot claim accurate reconciliation, and requires explicit provisional review before a separate freeze and confirmation.

## Edge Cases

- Device credential storage is unavailable, rejects the token, survives an iOS reinstall unexpectedly, or becomes unreadable after device-security settings change.
- A request contains both browser-cookie and mobile authorization credentials, a malformed credential scheme, or a credential for another owner.
- The installed client contract is older than the server's supported compatibility window.
- Project or Tag references disappear while a list/detail projection is open; wrong-owner references remain indistinguishable from missing records.
- Task pagination, counts, and local cache disagree after a mutation or an interrupted refresh.
- Recording is interrupted by an incoming call, audio-route loss, OS pressure, app termination, permission withdrawal, low storage, or network loss.
- The app is offline before an operation exists, after a local recording exists, midway through chunk upload, after seal, during processing, during proposal edit, or after a confirmation timeout.
- The same chunk number is retried with identical or different content; the manifest is incomplete or has the wrong hash.
- The provider exhausts retry budget, returns an empty transcript, produces no proposals, or leaves a provisional-only result.
- A proposal is edited/deleted while reconciliation changes its lineage; an open conflict or stale revision prevents freeze/confirm.
- Consent expires, is withdrawn offline, or the configured policy/provider categories change between recording, restart, upload, seal, retry, and provider claim.
- A frozen batch is superseded by an edit/reconciliation, canonical confirm races a deprecated compatibility alias, or the process dies after one child action succeeds.
- Raw-audio deletion is requested locally while offline, the server reports deletion pending after restart, or a user requests accurate retry after raw media is gone.
- Logout cannot reach the server; local secrets and cached owner data are still cleared while remote revocation remains visibly unresolved.
- Crash, analytics, screenshot, test, and build artifacts must not include credentials, email, raw audio, transcript text, task titles, local file paths, or content hashes usable as fingerprints.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: BrainBuddy MUST add exactly one native mobile application boundary for iOS and Android while the existing web client and FastAPI modular monolith remain authoritative for their current responsibilities.
- **FR-002**: The mobile application MUST use the existing Identity owner resolution and server-owned opaque revocable session model; it MUST NOT introduce JWT claims, client-owned user IDs, or a second identity store.
- **FR-003**: Mobile sign-in MUST return a credential only through an explicit mobile-safe session-establishment response that is non-cacheable, rate-limited like existing login, and never returned to the browser login flow.
- **FR-004**: The reusable mobile credential MUST be stored only in device-protected credential storage. Passwords, session credentials, and provider secrets MUST NOT be stored in ordinary key/value storage, query caches, files, state snapshots, logs, or analytics.
- **FR-005**: Protected requests MUST accept exactly one credential source. Ambiguous or malformed credential input MUST fail without choosing one credential silently.
- **FR-006**: Sign-out MUST revoke the current server session when reachable and always clear local credentials, owner-scoped query caches, operation pointers, and unsent sensitive UI state. An active unconfirmed recording MUST require an explicit discard decision before voluntary sign-out; involuntary `401` recovery MUST quarantine rather than silently delete it and MUST reveal it only after the same owner reauthenticates.
- **FR-007**: The `/api` contract MUST gain an independently owned semantic API version and a documented mobile compatibility window; storage schema version MUST remain a separate operational value.
- **FR-008**: Mobile request/response types MUST be validated from the backend's published contract rather than copied from persisted JSON or redefined as a second domain model.
- **FR-009**: The task workspace MUST expose exactly the four accepted open GTD lists; date views and terminal history MUST remain projections, not new Task states.
- **FR-010**: Task, Project, Tag, count, filter, pagination, detail, create, and transition behavior MUST reuse existing owner-scoped Tasks APIs and accepted lifecycle semantics.
- **FR-011**: Mobile task creation in this slice MUST create one plain Inbox task only; it MUST NOT parse Smart Add sigils or infer metadata.
- **FR-012**: Mobile mutations MUST carry unique idempotency keys, accepted expected revisions where required, actionable errors, and correlation IDs. Retry MUST preserve the original command identity.
- **FR-013**: The mobile Voice Brain Dump flow MUST use the existing persisted `voice_brain_dump` operation and its Task application port; the client MUST NOT orchestrate direct task creation from model output.
- **FR-014**: Microphone permission and external-processing consent MUST be separate, current, visible decisions. A grant MUST be time-bounded and bound to the server's current consent-policy version and required provider categories; restart/configuration change MUST revalidate it, and withdrawal MUST stop future local/server upload or provider work and schedule uncommitted artifacts for cleanup. Audio MUST NOT leave the device when current external processing is not permitted and no local provider exists.
- **FR-015**: Foreground recording MUST write to durable app-owned storage rather than an evictable cache before depending on later upload or recovery.
- **FR-016**: Stopped audio MUST use resumable numbered chunk upload with content identity and a complete manifest before seal. Successful chunk retries MUST not duplicate data; conflicting content MUST fail visibly.
- **FR-017**: The app MUST persist only the minimum local operation recovery metadata needed to bind the recording to its opaque owner ID, find the durable file, acknowledge chunks, preserve command keys/manifest, retain non-secret consent policy/category/time/expiry fields, locate the server operation/frozen batch, and remember last observed revisions; raw content MUST not enter analytics or crash evidence.
- **FR-018**: Closing or backgrounding the UI MUST NOT cancel, commit, or create tasks. Reopen MUST reconcile local recovery metadata with the owner-scoped server projection.
- **FR-019**: Review MUST use canonical append-only user proposal patches, visibly distinguish provisional/reconciled/conflicted states, preserve user edits/removals, exclude tombstoned or superseded proposals, and block freeze while conflicts remain. Any accepted post-freeze proposal change MUST supersede the frozen batch and require a new freeze.
- **FR-020**: Confirmation MUST target a persisted immutable `ProposalBatch` frozen at the selected proposal revision. Every frozen action MUST preserve its target, before/after summaries, source cue, confidence/warnings, and destination without mutable execution-result fields; per-action outcomes MUST be projected from append-only immutable `H(operation_id,batch_id,action_id)` receipts. Confirmation creates only title-only Inbox actions. Mobile MUST NOT consume deprecated direct proposal `PATCH` or `/commit` aliases, and no Task may exist before canonical confirmation.
- **FR-021**: The app MUST provide loading, empty, offline, retryable error, terminal error, stale-conflict, cancellation, upload, processing, commit, and partial-result states without fake percentages or optimistic success.
- **FR-022**: The first slice MUST use the authoritative BrainBuddy mobile design vocabulary, colors, typography, spacing, icons, 44-point minimum touch targets, reduced-motion behavior, and authority copy; exploratory Execution cards cannot enable product behavior.
- **FR-023**: Unsupported CloudDesign controls MUST be omitted or explicitly non-interactive. A disabled-looking promise MUST NOT be presented as a shipped capability.
- **FR-024**: Every automated mobile test MUST emit non-empty Allure epic, feature, story, human-readable title, and at least one named product step through a central mobile helper.
- **FR-025**: Production build, signing, provider, API, and store credentials MUST remain outside source control and client bundles; client configuration may contain only public environment values such as the API origin and contract version.
- **FR-026**: The operation projection MUST expose raw-audio deletion state and `retained_until`; after processing, mobile MUST offer an idempotent delete-now action that distinguishes local from server cleanup and preserves confirmed Tasks/action receipts/non-audio provenance.
- **FR-027**: The backend MUST import each active v1 operation once as `legacy_preview_only`, preserve its operation/segment/proposal IDs, title locks, and remove tombstones through deterministic synthetic patches, expose a visible `provisional_only` warning, prohibit accurate-reconciliation claims or retry without original audio, and require explicit provisional review before a separate immutable freeze and confirmation. Completed/cancelled v1 records MUST remain immutable and MUST NOT create Tasks during migration.

### Design Classification and First-Slice Scope

| Frame | First-slice classification | Required disposition |
|---|---|---|
| M-01 Next actions | **Build** | Paginated canonical Next projection, truthful metadata, complete/open detail, drawer, and Brain Dump entry. Omit Execution chips/actions. |
| M-02 Drawer | **Build** | Four open lists, Projects, Tags, counts, Brain Dump, and `Weekly Review · coming later`; no fifth state or fake due cadence. |
| M-03 Inbox | **Build** | Paginated Inbox, plain fast capture, task detail/completion, and Brain Dump entry. |
| M-04 Task details | **Bounded build** | Read canonical fields and allow lifecycle actions. Metadata editing, Subtasks, Comments, run log, artifacts, and agent actions are not first-slice commitments. |
| M-05 Brain Dump recording | **Bounded build** | Foreground local recording, honest waveform/duration, interruption salvage, post-stop resumable upload, processing state. Live transcript/proposal streaming while speaking remains deferred until supported without weakening audio durability. |
| M-06 Brain Dump review | **Build** | Edit/remove proposals, visible quality/conflicts, discard/cancel, and explicit `Confirm N additions`. `Add date` and inferred metadata are omitted. |
| M-07 Project | **Bounded build** | Read-only paginated Project task projection and back navigation. Project management, `Think`, and project task metadata editing are deferred. |
| M-08 Tag (historical Context frame) | **Bounded build** | Read-only paginated Tag task projection using current Tag vocabulary. Tag management is deferred. |
| M-09 Weekly Review | **Deferred** | Non-interactive `coming later`; no cadence, due state, voice review, or outcome workflow is invented. |

### Key Entities

- **Mobile session credential**: One-time response value for a server-owned opaque Session. The server stores only its digest; the client stores the raw value only in device-protected credential storage.
- **Mobile installation state**: Non-authoritative local marker used to clear unexpectedly persisted credential material after reinstall. It is not identity, ownership, authorization, or a device fingerprint.
- **Mobile operation recovery record**: Owner-local pointer to a server operation and durable audio/manifests/checkpoints; it contains no canonical Task and is cleared according to operation completion/cancellation/privacy policy.
- **Task / Project / Tag**: Existing Tasks-owned records. Mobile holds replaceable query projections only.
- **Voice Brain Dump operation / proposal**: Existing workflow-owned persisted operation and provisional review projection. Canonical Tasks are created only by confirmed operation actions.

## Assumptions & Dependencies

- Initial users already have invite-created or seeded accounts; signup, password reset, and email verification remain web/operations concerns.
- iOS and Android are both supported. First release evidence may use internal distribution; public store submission is a later release decision.
- Recording is foreground-only. Background recording, lock-screen controls, widgets, push notifications, and sustained provider work on-device are out of scope.
- The server remains the network-visible FastAPI deployment and sole canonical owner of identity, Tasks, and operation state.
- Before mobile Voice implementation, the existing bounded Brain Dump backend must close the ADR-0002 canonical proposal-batch/freeze/confirm, current-consent, and raw-audio retention/delete-now gaps. Event-stream, undo, and live-streaming conformance remain outside this mobile slice.
- General offline task editing/synchronization is out of scope. Task reads may cache for transient continuity; writes require a server result. Voice recovery is the only durable offline queue in this slice.
- The feature has no effect on CRT graph semantics or approximately 200-node web canvas responsiveness because the mobile app does not render or mutate CRT in this slice.

## Out of Scope

- A second mobile app, Expo web replacement, shared universal UI shell, or rewrite of the Vite web client.
- JWT access/refresh tokens, OAuth/social login, mobile signup, password reset, biometric sign-in, remote session list, or device trust/attestation.
- Background recording, continuous encoded-audio upload while the recorder is active, authoritative on-device speech recognition, or live proposals while speaking.
- General offline-first task mutation queues, conflict-merging task edits, background sync, or cross-device local-draft synchronization.
- Task metadata editing, Smart Add, Project/Tag management, Subtasks, Comments, search/date views/sort controls, reminders, recurrence, or notifications.
- Weekly Review, voice-led Weekly Review, CRT/Think navigation, AI agents, Execution runs, external task trackers, routes, evidence/result cards, or autonomous actions.
- Public store submission, automatic production release, over-the-air update rollout, billing, analytics expansion, or marketing surfaces.
- Checking generated native iOS/Android projects into source control unless a later accepted escape decision proves configuration generation insufficient.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On both supported platforms, a user can sign in, restart, restore their session, sign out, and prove revoked access in one automated or device-assisted acceptance run with no credential in captured artifacts.
- **SC-002**: The four open lists, Project and Tag projections, counts, continuation, basic detail, plain Inbox capture, completion, and explicit reopen produce the same canonical state in mobile and web for 100% of acceptance fixtures.
- **SC-003**: A Voice Brain Dump interrupted once during local recording, upload, processing, and confirmation can resume or provide an explicit salvage/discard outcome in every tested checkpoint without silent audio loss or unintended Task creation.
- **SC-004**: Repeating every task command, chunk upload, seal, proposal edit, and confirmation fixture produces zero duplicate canonical Tasks and zero duplicated accepted chunks.
- **SC-005**: No tested denial, cancellation, provider failure, stale revision, offline window, app restart, or partial commit creates a Task before explicit confirmation.
- **SC-006**: Local recording feedback appears within 100 ms of captured input on supported test devices; list interactions remain perceptually responsive and do not block on full-dataset loading.
- **SC-007**: All focused backend contract, mobile unit/component, generated-contract drift, simulator/device journey, privacy scan, and internal build gates pass for both iOS and Android before release review.
- **SC-008**: A requirements review can map every enabled mobile control to an accepted server command or client-local action and finds zero unsupported button-shaped promises.
- **SC-009**: Restart, consent expiry/withdrawal, policy/provider-category change, frozen-batch invalidation, canonical/legacy overlap, partial confirmation, and raw-audio delete-now fixtures produce zero stale-consent provider calls, zero duplicate Tasks, and truthful retained/pending/deleted state.
