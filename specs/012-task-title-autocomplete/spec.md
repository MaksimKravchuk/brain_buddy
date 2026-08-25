# Feature Specification: Web Task Title Autocomplete

**Feature Branch**: `wt/t_6fca39aa`
**Created**: 2026-08-25
**Status**: Ready for implementation
**Input**: Bounded web-only AI completion experiment behind a default-OFF runtime flag

## User Scenarios & Testing

### User Story 1 - Complete a new Task title without leaving capture (Priority: P1)

An authenticated web user types in the existing new-Task title input, sees exactly three compact full-title completions below it, and accepts one as editable draft text before deciding whether to submit normally.

**Why this priority**: Faster capture is the feature's only user value; it must not change the authority boundary between drafting and creating a Task.

**Independent Test**: With the flag effective, provider configured, and current consent granted, type an eligible draft, wait for the menu, choose with ArrowDown/Enter, and verify the input changes while the Task list and backend store remain unchanged until a separate ordinary submit.

**Acceptance Scenarios**:

1. **Given** no Project context and a draft of at least three non-blank words, **When** typing pauses for 350 ms, **Then** exactly three distinct full-title candidates appear below the existing input.
2. **Given** an active Project context and at least one non-blank word, **When** typing pauses for 350 ms, **Then** exactly three Project-informed candidates appear.
3. **Given** the menu is open, **When** ArrowUp/ArrowDown is pressed, **Then** selection wraps through the three candidates without changing the input.
4. **Given** a selected candidate, **When** Enter or mouse is used, **Then** the candidate replaces the input, focus remains there, and no Task create/Smart Add submit call or durable Task write occurs.
5. **Given** acceptance has closed the menu, **When** the user later uses the ordinary submit control or a subsequent Enter, **Then** the existing Task/Smart Add submission contract applies normally.
6. **Given** the menu is open, **When** Escape is pressed, **Then** it closes with the draft unchanged and does not reopen for that unchanged draft/context.

---

### User Story 2 - Keep Smart Add and ordinary capture deterministic (Priority: P1)

A user can keep using `#`/`@` Smart Add and plain capture without two menus, stolen keystrokes, generated classifications, or changed submit behavior.

**Why this priority**: The same input already owns a keyboard-driven Smart Add listbox; ambiguous ownership could create the wrong Task or classification.

**Independent Test**: Open Smart Add from an eligible autocomplete draft and prove autocomplete cancels/dismisses, only Smart Add handles keys, and no autocomplete candidate can introduce a completed Smart Add token.

**Acceptance Scenarios**:

1. **Given** a caret-local Smart Add token/menu, **When** it becomes active, **Then** any autocomplete request/menu is cancelled/dismissed and Smart Add alone owns Arrow/Enter/Escape.
2. **Given** no Smart Add token/menu and autocomplete is open, **When** keyboard controls are used, **Then** autocomplete alone owns them.
3. **Given** provider output contains a completed `#` or `@` token, rewrites the draft prefix, duplicates another candidate, or yields fewer than three valid candidates, **When** validation runs, **Then** the entire response is unavailable and none is rendered.
4. **Given** the feature flag is OFF, **When** the composer is used, **Then** provider discovery, consent UI, requests, menus, metrics, and status are absent and current Smart Add/plain behavior remains unchanged.

---

### User Story 3 - Make remote AI use explicit, owner-isolated, and safely unavailable (Priority: P1)

A user sees which provider would receive content, grants current session-local consent, and can always keep capturing when consent, provider, network, rate, or model output is unavailable.

**Why this priority**: The feature sends Task text outside BrainBuddy; consent and owner isolation are release-blocking, not optional polish.

**Independent Test**: Exercise flag, provider, consent, other-owner Project, timeout, rate-limit, invalid-output, cancellation, and stale-response cases while asserting zero unauthorized provider calls, zero leaked text in records, and an unchanged usable draft.

**Acceptance Scenarios**:

1. **Given** the flag is effective and provider discovery names a provider, **When** consent is unchecked, **Then** the UI explains that draft, selected Project name, and prior Task titles would be sent, and makes no generation call.
2. **Given** current consent names the configured provider, **When** generation runs, **Then** context contains only the draft, same-owner selected active Project, and at most 50 same-owner prior Task titles.
3. **Given** another owner's/absent Project, false/mismatched consent, ineffective flag, missing provider credentials, or degraded flag store, **When** generation is attempted, **Then** it fails before remote egress.
4. **Given** a superseding edit, Project change, consent withdrawal, Smart Add activation, flag/provider change, or unmount, **When** a request is active, **Then** it is aborted best-effort and any late response is discarded.
5. **Given** timeout, 429, offline/transport failure, malformed output, or fewer than three valid candidates, **When** generation fails, **Then** the menu stays closed, the draft and ordinary submit remain usable, and a compact actionable status appears.
6. **Given** any request or acceptance observation, **When** logs/metrics/evidence are inspected, **Then** they contain only IDs, timing, provider category, outcome/error band, token counts, and accepted rank—never Task/Project text, prompt/result, or content-derived hashes.

## Edge Cases

- Unicode whitespace defines words; trim and collapse only for eligibility/comparison, not by mutating the user's draft.
- Drafts over 500 characters or containing line breaks are rejected locally and by the server.
- Project context disappears or archives between discovery and generation: server authority returns safe unavailable; no fallback to unscoped history occurs for that request.
- Prior titles may include open or terminal Tasks, but never details, tags, comments, subtasks, due dates, priorities, account data, tree data, or another owner.
- Duplicate prior titles are normalized/deduplicated before the 50-title cap. Project-matching titles precede other owner titles, then `updated_at` descending.
- Old candidates clear immediately when a new eligible edit starts; they are never shown during a new request.
- An HTTP abort may not stop an upstream call already accepted by the provider; no retries and a 3-second timeout bound residual work.
- Acceptance telemetry failure is ignored and cannot change input, submit, or Task persistence.
- Flag OFF while a menu is open clears the menu/consent state and aborts work; existing Tasks and the current input text stay untouched.

## Requirements

### Functional Requirements

- **FR-001**: The existing web new-Task title `<input>` MUST remain the only composer; autocomplete MUST use one compact listbox below it with exactly three full-title candidates and MUST NOT use inline ghost text.
- **FR-002**: Unscoped generation MUST require at least three non-blank Unicode-whitespace-delimited words; Project-scoped generation MUST require a valid selected Project and at least one non-blank word.
- **FR-003**: The browser MUST debounce eligible changes by 350 ms, keep one current request, abort on eligibility/context/ownership changes, clear old results immediately, and discard every response not matching the latest sequence plus exact draft/Project snapshot.
- **FR-004**: ArrowUp/ArrowDown MUST wrap selection, Enter MUST accept only into the input, Escape MUST dismiss unchanged, mouse MUST equal Enter, and acceptance MUST never submit/create; ordinary explicit submission remains a separate subsequent action.
- **FR-005**: Smart Add and autocomplete MUST have one keyboard owner and no stacked menus: active Smart Add suppresses autocomplete; otherwise an open autocomplete menu owns Arrow/Enter/Escape.
- **FR-006**: Server generation context MUST be limited to current draft, same-owner selected active Project, and at most 50 distinct same-owner prior Task titles ordered as specified; no new entity/store/cache/history MUST persist prompts or candidates.
- **FR-007**: Remote generation MUST require an authenticated owner, effective `task_title_autocomplete`, current request-scoped consent naming the discovered configured provider, and available credentials before egress; any failure MUST fail closed.
- **FR-008**: The provider response MUST pass every invariant in `contracts/title-completions.md`; exactly three valid candidates render or none render.
- **FR-009**: `task_title_autocomplete` MUST be server-owned, allow-listed, SQLite runtime-managed, default OFF, present in member effective flags and existing operator controls, and used only for exposure—not authentication, owner access, consent, or provider capability.
- **FR-010**: Generation MUST be limited to 20 requests per owner per rolling 60 seconds, use a 3-second provider timeout with no retry, and preserve ordinary capture with actionable `400/404/429/503` behavior and `X-Correlation-ID`.
- **FR-011**: Logs, metrics, fixtures, snapshots, and evidence MUST NOT contain drafts, Project names, prior titles, prompts, candidates, provider bodies, or content-derived hashes; allowed observations are IDs, route/stage, provider category, outcome band, duration, token counts, and candidate rank.
- **FR-012**: The only pre-submit observation beyond the remote request MAY be a best-effort content-free acceptance event (`request_id`, rank); it MUST NOT persist domain data, block input, or create/update a Task.
- **FR-013**: The feature MUST be web new-task-only and MUST NOT alter mobile, Voice Brain Dump, task title editing, Task lifecycle, Smart Add parsing/submission, Project/Tag persistence, CRT, or normal Task storage.
- **FR-014**: Flag OFF rollback MUST stop discovery/generation/menu/acceptance observation for new work without deleting or changing Tasks, Projects, submitted titles, or the current unsaved draft.

### Key Entities

- **Completion draft**: Ephemeral current title text plus optional selected Project ID and current consent; never persisted by this feature.
- **Completion context**: Ephemeral server-built owner-scoped draft, optional Project, and bounded prior-title list sent to the provider.
- **Completion candidate set**: Exactly three validated full titles plus random request ID, held only in current UI memory.
- **Runtime flag row**: Existing feature-flag store shape extended with one default-OFF `task_title_autocomplete` row; it contains rollout mode/account IDs, never Task content.
- **Task / Project**: Existing owner-scoped records, read for context and unchanged until ordinary Task commands run.

## Success, Stop, and Rollback Criteria

### Measurable Outcomes

- **SC-001**: Automated browser/API evidence proves every displayed set has exactly three valid candidates and accepting each rank causes zero Task/Project/Tag write and zero Task-create request before separate ordinary submit.
- **SC-002**: Automated owner-isolation/consent tests cover flag OFF, degraded store, missing provider, false/mismatched consent, absent/other-owner/inactive Project, and mixed-owner history with zero prohibited remote call or text-bearing log.
- **SC-003**: At 390×851 and 1280×780 web viewports, all A-01…A-12 states remain usable without horizontal overflow; keyboard and screen-reader contracts pass, and existing Smart Add tests stay green.
- **SC-004**: In an internal pilot of at least 100 eligible generation attempts, at least 90% return a valid three-candidate set and p95 successful response time is at most 2.5 seconds; no request exceeds the 3-second provider timeout plus local transport overhead.
- **SC-005**: In that pilot, at least 20% of displayed candidate sets produce a content-free acceptance event, measured without storing or reconstructing Task text.
- **SC-006**: Flag OFF takes effect through the existing runtime refresh contract, removes all autocomplete affordances on refresh, and leaves every existing/submitted Task plus current unsaved input unchanged.

### Stop triggers

Immediately set the runtime flag OFF and stop the pilot on any unconsented/cross-owner egress, Task text in logs/evidence, pre-submit Task write, generated Smart Add classification, or acceptance-caused submit. Also stop after the 100-attempt minimum if valid-set rate is below 80%, p95 successful latency exceeds 3 seconds, or acceptance is below 10% in two consecutive review windows. Values between the success and stop bars keep the experiment INTERNAL for investigation; they do not justify ON.

Rollback is flag OFF first. Code/image rollback removes the endpoint/UI only; it does not revert, delete, or rewrite Tasks created through ordinary submission. The additional OFF rollout row may remain inert in SQLite.

## Assumptions and Non-Goals

- Production remains a single backend process/machine for the in-memory limiter and existing runtime-flag topology.
- The configured v0 provider is OpenAI at its fixed official API origin and is disabled by default; tests use injected deterministic fakes and never paid/live calls.
- Session-local consent is unchecked on page load and cleared on flag/provider change or unmount; no durable consent preference is introduced.
- No mobile app, voice, title-edit, suffix-only/ghost completion, streaming tokens, local fallback model, vector/embedding store, generalized AI memory, provider selector, arbitrary provider endpoint, percentage rollout, prompt history, or candidate history is included.
- A Hermes-like memory entity/store is a future experiment only and cannot be inferred from this package.
