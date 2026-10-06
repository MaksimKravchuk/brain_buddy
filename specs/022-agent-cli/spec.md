# Feature Specification: Agent-friendly BrainBuddy CLI

**Feature Branch**: feat/agent-cli
**Created**: 2026-10-06
**Status**: Scope clarified; terminal design approval pending
**Input**: Universal BrainBuddy CLI optimized for AI agents and tokens, including prebuilt binaries and one-command installation.

## Clarifications

### Session 2026-10-06

- Q: Confirm the initial client scope and non-goals? → A: The owner selected “Нужны также готовые сборки и установка одной командой”. Client scope is retained; distribution is added.
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

### Edge Cases

Missing sessions; invalid JSON/args/dates/enums; bounded input/response limits; foreign-owner 404; credential-bearing redirects; insecure remote HTTP; timeout after mutation; empty searches; locally truncated unpaginated lists; disabled capabilities; binary responses/raw audio; unsupported architectures; checksum failure; unwritable installation directories. Each fails explicitly or returns documented empty/truncated results. No automatic write retries, inferred consent or fabricated success.

Mobile UI/voice recovery/canvas responsiveness do not change.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Expose task capture, filtered list, retrieval, revision-checked edit and lifecycle transitions through existing server semantics.
- **FR-002**: Expose existing project/tag/CRT-tree shortcuts and generic member JSON operations without bypassing ownership or flags.
- **FR-003**: Return compact JSON, documented minimal task fields, explicit field selection/full output, preserved continuation metadata and disclosed local truncation.
- **FR-004**: Support JSON stdin/files, scoped offline command discovery, scoped live operation schemas and nonexecuting redacted previews.
- **FR-005**: Preserve explicit revisions and reusable idempotency keys where required; never invent revisions, perform implicit read-modify-write or replay writes automatically.
- **FR-006**: Return stable documented nonzero exit codes and structured errors with available status, conflict/validation detail, correlation reference and retry timing; uncertain write delivery is explicit.
- **FR-007**: Reuse existing sessions without credential persistence/disclosure; verify TLS, reject insecure remote transport by default and refuse credential-bearing redirects. Consent remains explicit in operation input.
- **FR-008**: Run noninteractively with bounded request duration, input/response sizes and task-page size; discovery and preview work offline.
- **FR-009**: Provide native release binaries for Linux x86_64/arm64, macOS x86_64/arm64 and Windows x86_64, with versioned archives and SHA-256 checksums.
- **FR-010**: Provide Unix/PowerShell one-command installers with explicit version/destination, platform detection, checksum verification and failure before replacement on integrity/unsupported-platform errors.
- **FR-011**: Keep build jobs read-only and separate from main promotion/production credentials; publish only with reviewed green exact-commit evidence under existing release authority.
- **FR-012**: Document installation, existing-session setup, agent quickstart, discovery, output/paging, conflict/timeout recovery and platform limits.

### Key Entities

Existing owner-scoped Task, Project, Tag and CRT tree; explicit command request with revision/key; projected result with continuation/error metadata; versioned CLI release tied to an exact reviewed commit. No parallel domain storage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Capture → search → edit → complete succeeds with one noninteractive command per business step and zero duplicate tasks on identical create replay.
- **SC-002**: A synthetic 20-task page's default JSON is at least 60% smaller in UTF-8 bytes than full output, preserving identifier/title/state/revision/continuation. Reported token measurements identify their tokenizer.
- **SC-003**: Critical failure evidence covers stale revision, invalid session, malformed input, rate limit and uncertain write delivery with correct exit status and parseable errors.
- **SC-004**: All five native build targets pass version/help/discovery smoke; installer success, unsupported-machine and corrupt-download scenarios pass.
- **SC-005**: Published-version Unix/Windows installer smoke demonstrates correct version/checksum and requires no compiler or administrator rights.

## Assumptions

Rust is preferred. Existing accounts/sessions are supplied via environment or protected input file; signup/password management/new auth are out of scope. JSON API only initially; binary export/raw audio are not claimed. No offline sync, MCP/TUI or server/web/iOS changes. Windows arm64, code signing/notarization, package-manager registries and automatic updates are first-release exclusions. Server flags and deployed contracts govern availability. Byte reduction is a size proxy, not an identical token-reduction claim.
