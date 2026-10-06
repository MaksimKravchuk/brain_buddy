# Feature Specification: Agent-friendly BrainBuddy CLI

**Feature Branch**: feat/agent-cli
**Created**: 2026-10-06
**Status**: Distribution and convenient authentication in scope; revised terminal design approval pending
**Input**: Universal BrainBuddy CLI optimized for AI agents and tokens, including prebuilt binaries, one-command installation and convenient login integrated with the shared Google/Apple authentication work.

## Clarifications

### Session 2026-10-06

- Q: Confirm the initial client scope and non-goals? → A: The owner selected “Нужны также готовые сборки и установка одной командой”. Client scope is retained; distribution is added.
- Owner steering: convenient CLI authentication must integrate with the Google/Apple and other shared-login work in a parallel session. Manual session provisioning and excluding authentication are superseded. The owner did not choose a protocol; browser-based device authorization below is an agent recommendation awaiting design approval.
- No further business questions are needed. Technical choices belong to the implementing agent. Platform architecture limits below are explicit first-release assumptions.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Work on tasks from a terminal (Priority: P1)

An authorized agent captures, finds, edits and completes a task without a browser.

**Why this priority**: Directly serves capture → clarify → act → inspect.

**Independent Test**: Execute the journey with a disposable backend account and read back final task state.

**Acceptance Scenarios**:

1. **Given** a valid existing session, **When** the agent creates a task with a reusable key, **Then** exactly one task is created and identical replay returns it.
2. **Given** that task, **When** it is searched and retrieved, **Then** identifier, title, state, revision and paging information are machine-readable.
3. **Given** a known revision, **When** the task is edited or completed, **Then** existing transition rules apply and the next revision is returned.
4. **Given** a stale revision, **When** an edit is attempted, **Then** newer work is preserved and a structured conflict/correlation reference is returned.

### User Story 2 - Discover and use operations efficiently (Priority: P1)

An agent discovers commands, requests only needed fields and accesses existing member JSON operations beyond shortcuts.

**Why this priority**: Avoid repeated API research and token-heavy results.

**Independent Test**: Offline command discovery and request preview; scoped server schema; project/tag/tree commands; generic member JSON read.

**Acceptance Scenarios**:

1. **Given** no connection, **When** discovery or dry-run is requested, **Then** concise metadata or a redacted request is returned without network work.
2. **Given** a verbose task response, **When** default/selected/full output is requested, **Then** the documented projection or complete response is returned.
3. **Given** paginated tasks, **When** a bounded page is requested, **Then** continuation metadata survives and later pages are not fetched implicitly.
4. **Given** a deployed member JSON operation, **When** method/path/query/input are supplied explicitly, **Then** existing ownership, flag, consent and revision rules remain enforced.
5. **Given** session/input/rate-limit/transport failure, **When** execution fails, **Then** exit status and structured errors support deliberate recovery without secret disclosure or automatic mutation replay.

### User Story 3 - Install a released binary (Priority: P1)

The owner installs the correct native binary with one command, without a compiler.

**Why this priority**: Explicit follow-up requirement.

**Independent Test**: Native platform build smoke; installer fixtures; actual published-release installation smoke.

**Acceptance Scenarios**:

1. **Given** a supported machine, **When** the installer is run, **Then** a matching verified binary is placed in a user-owned directory and version/PATH information is shown.
2. **Given** a corrupted archive or unsupported machine, **When** installation runs, **Then** it fails before replacing a working binary.
3. **Given** a requested fixed version, **When** installation runs, **Then** that release is installed without silently selecting another.

### User Story 4 - Sign in once and let agents work (Priority: P1)

The owner connects a CLI installation to the same BrainBuddy account used by the web/native clients. Later agent commands reuse that connection without handling the owner's password or provider credentials.

**Why this priority**: Convenient authentication is an explicit follow-up requirement, and unattended business commands need prior account authorization.

**Independent Test**: Exercise login with a disposable shared-auth identity, then run an authenticated task command; inspect identity, revoke only the CLI session and verify subsequent access fails.

**Acceptance Scenarios**:

1. **Given** the shared authentication and CLI authorization capability are deployed, **When** the owner runs `bb auth login`, **Then** BrainBuddy opens in a browser, offers the configured login methods, shows the account and CLI connection to approve, and issues a separate expiring/revocable CLI credential only after approval.
2. **Given** the CLI runs over SSH or cannot open a browser, **When** the owner uses `bb auth login --no-browser`, **Then** a verification link and short one-time code allow approval on another device, with the same bounded expiry and no local browser callback requirement.
3. **Given** successful approval, **When** credential storage succeeds, **Then** the secret is stored in the OS credential store, the CLI reports identity without printing the secret, and ordinary business commands run without authentication prompts.
4. **Given** no OS credential store on a headless host, **When** login is attempted, **Then** it reports the storage limitation explicitly; a protected-file fallback requires explicit selection, and unattended jobs may use an externally supplied secret.
5. **Given** denial, expiry, interruption, an unsupported server or a failed credential save, **When** login ends, **Then** it reports the actual result without replacing a working session or fabricating success.
6. **Given** an existing connection, **When** the owner invokes `bb auth status` or `bb auth logout`, **Then** status identifies the server/account without secrets, logout removes the local credential and attempts server revocation, and a failed remote revocation is reported explicitly.

### Edge Cases

Missing sessions; invalid JSON/args/dates/enums; bounded input/response limits; foreign-owner 404; credential-bearing redirects; insecure remote HTTP; timeout after mutation; empty searches; locally truncated unpaginated lists; disabled capabilities; binary responses/raw audio; unsupported architectures; checksum failure; unwritable installation directories. Each fails explicitly or returns documented empty/truncated results. No automatic write retries, inferred consent or fabricated success.

Mobile UI/voice recovery/canvas responsiveness do not change.

Authentication additionally covers code expiry/denial, bounded server-directed polling, keychain unavailable/locked, account/server mismatch, credential-save failure and offline logout. Business commands never initiate browser login implicitly on 401. Existing-account linking, signup/invite policy and Google/Apple identity verification remain owned by the shared-auth work.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Expose task capture, filtered list, retrieval, revision-checked edit and lifecycle transitions through existing server semantics.
- **FR-002**: Expose existing project/tag/CRT-tree shortcuts and generic member JSON operations without bypassing ownership or flags.
- **FR-003**: Return compact JSON, documented minimal task fields, explicit field selection/full output, preserved continuation metadata and disclosed local truncation.
- **FR-004**: Support JSON stdin/files, scoped offline command discovery, scoped live operation schemas and nonexecuting redacted previews.
- **FR-005**: For business commands, preserve explicit revisions and reusable idempotency keys where required; never invent revisions, perform implicit read-modify-write or replay writes automatically. Authentication polls only according to its explicit server-directed grant protocol.
- **FR-006**: Return stable documented nonzero exit codes and structured errors with available status, conflict/validation detail, correlation reference and retry timing; uncertain write delivery is explicit.
- **FR-007**: Use the shared BrainBuddy account authority, storing a CLI credential only in the OS credential store or an explicitly selected protected-file fallback. Never persist passwords/provider tokens or disclose credentials in output/logs/previews; verify TLS, reject insecure remote transport by default and refuse credential-bearing redirects. Consent remains explicit in operation input.
- **FR-008**: Run business commands noninteractively with bounded request duration, input/response sizes and task-page size; discovery and preview work offline. Explicit auth login is the human authorization step; a business command never opens it implicitly.
- **FR-009**: Provide native release binaries for Linux x86_64/arm64, macOS x86_64/arm64 and Windows x86_64, with versioned archives and SHA-256 checksums.
- **FR-010**: Provide Unix/PowerShell one-command installers with explicit version/destination, platform detection, checksum verification and failure before replacement on integrity/unsupported-platform errors.
- **FR-011**: Keep build jobs read-only and separate from main promotion/production credentials; publish only with reviewed green exact-commit evidence under existing release authority.
- **FR-012**: Document installation, browser/headless login, credential-source/storage behavior, agent quickstart, discovery, output/paging, conflict/timeout recovery and platform limits.
- **FR-013**: Expose browser and no-browser login through BrainBuddy's shared authentication, with explicit device approval, bounded lifetime/polling and a separate revocable CLI credential; do not embed provider client secrets or invent account linking.
- **FR-014**: Expose secret-free auth status and logout, preserve server/account isolation, and report unavailable storage, expired access and failed remote revocation explicitly. Explicit unattended credential input remains supported.

### Key Entities

Existing owner-scoped Task, Project, Tag and CRT tree; explicit command request with revision/key; projected result with continuation/error metadata; versioned CLI release tied to an exact reviewed commit. New authentication entities are an expiring device approval and a separate server/account-bound CLI credential; their server ownership and transport depend on the shared-auth contract. No parallel business-data storage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Capture → search → edit → complete succeeds with one noninteractive command per business step and zero duplicate tasks on identical create replay.
- **SC-002**: A synthetic 20-task page's default JSON is at least 60% smaller in UTF-8 bytes than full output, preserving identifier/title/state/revision/continuation. Reported token measurements identify their tokenizer.
- **SC-003**: Critical failure evidence covers stale revision, invalid session, malformed input, rate limit and uncertain write delivery with correct exit status and parseable errors.
- **SC-004**: All five native build targets pass version/help/discovery smoke; installer success, unsupported-machine and corrupt-download scenarios pass.
- **SC-005**: Published-version Unix/Windows installer smoke demonstrates correct version/checksum and requires no compiler or administrator rights.
- **SC-006**: Browser and headless login each authorize an existing shared-auth account, save a protected CLI credential and permit a subsequent prompt-free task command. Denied/expired/unsupported/storage-failed login never reports success; logout prevents subsequent use of the revoked CLI credential without revoking the browser session.

## Assumptions

Rust is preferred. Convenient login is required; externally supplied credentials are an unattended option rather than the primary owner journey. Shared provider login, account linking, signup/invites and password management belong to the parallel authentication work. The CLI-specific server authorization/credential contract must be integrated with that work before authentication implementation; it is not present in the inspected main branch. The recommended device flow is against BrainBuddy, not an assumption that Google or Apple supports device grants directly. No offline sync, MCP/TUI, unrelated server business changes or web/iOS redesign. A narrow shared-auth approval surface and CLI authorization support are now in scope as integration dependencies. JSON API only initially; binary export/raw audio are not claimed. Windows arm64, code signing/notarization, package-manager registries and automatic updates are first-release exclusions. Server flags and deployed contracts govern availability. Byte reduction is a size proxy, not an identical token-reduction claim.
