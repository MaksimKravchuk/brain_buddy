# Feature Specification: Smart Add task classification

**Feature Branch**: `wt/t_fe52d630`
**Created**: 2026-07-18
**Status**: Ready for implementation
**Input**: RTM-style desktop/web task capture where `#` means Tag and `@` means Project

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Classify a task while typing it (Priority: P1)

A user captures a task in the existing desktop/web composer and types `#` or `@` to find
an existing Tag or Project without leaving the title field.

**Why this priority**: Classification must be faster than the current post-create dropdown
flow while preserving the existing one-step composer.

**Independent Test**: With existing `deep-work` and `Onboarding drop-off` classifications,
type `Draft experiment #deep @"Onboarding drop-off"`, choose the suggestions, submit, and
observe a Task titled `Draft experiment` with the expected Tag and Project.

**Acceptance Scenarios**:

1. **Given** active Tags and Projects are loaded, **When** the caret is in a `#partial`
   token, **Then** the composer offers ranked matching Tags and no Projects.
2. **Given** active Tags and Projects are loaded, **When** the caret is in an `@partial`
   token, **Then** the composer offers ranked matching Projects and no Tags.
3. **Given** a selected suggestion, **When** the user submits, **Then** the clean title and
   selected classification are persisted and the recognized token is absent from the title.
4. **Given** several Tag tokens, **When** the user submits, **Then** all distinct Tags are
   assigned in stable first-occurrence order.
5. **Given** several Project tokens, **When** the user submits, **Then** only the final
   Project is assigned, every Project token is removed from the title, and no superseded
   unknown Project is created.

---

### User Story 2 - Create unknown classifications as part of capture (Priority: P1)

A user can submit a syntactically complete unknown `#name` or `@name`; BrainBuddy creates
that active classification and assigns it to the same new Task.

**Why this priority**: Requiring prior Project/Tag setup would defeat Smart Add's capture
speed and the stated product outcome.

**Independent Test**: Type `Call supplier #calls @"Vendor launch"`, where neither name
exists, submit once, and verify one Task, one Tag, and one Project are created and linked;
replay the command and verify no duplicates.

**Acceptance Scenarios**:

1. **Given** no active exact normalized Tag match, **When** a completed unknown Tag token is
   submitted, **Then** one Tag is created and assigned atomically with the Task.
2. **Given** no active exact normalized Project match, **When** the final completed unknown
   Project token is submitted, **Then** one Project is created and assigned atomically.
3. **Given** a concurrent or differently-cased active exact match, **When** the command
   resolves the name, **Then** it assigns that existing record rather than creating a
   duplicate.
4. **Given** validation or persistence fails, **When** the command returns an error, **Then**
   neither the Task nor any command-created classification remains committed.
5. **Given** the same idempotency key and body are replayed, **When** the request is retried,
   **Then** the original composite result is returned without duplicate records.

---

### User Story 3 - Keep literal capture and existing organization controls compatible (Priority: P1)

A user who types an ordinary title sees no semantic change, and existing task-edit and
Project/Tag controls remain available after creation.

**Why this priority**: Smart Add must not turn every hash, email address, code term, or title
edit into an unintended durable side effect.

**Independent Test**: Submit `Email max@example.com about C# notes` and verify the exact
trimmed title is stored with no classification creation; then edit Project/Tags through the
existing controls.

**Acceptance Scenarios**:

1. **Given** a title with no committed Smart Add token, **When** it is submitted, **Then**
   the existing literal `POST /tasks` path and contextual defaults are used unchanged.
2. **Given** `C#`, `name@example.com`, escaped `\#literal`, or escaped `\@literal`, **When**
   the title is submitted, **Then** no unintended classification is created.
3. **Given** a Task is edited through row or detail title editing, **When** its title contains
   `#` or `@`, **Then** the edit remains literal and does not invoke Smart Add.
4. **Given** an existing classified Task, **When** it renders, **Then** Tags display as
   `#tag` and its Project displays as `@project` while stable IDs remain canonical.
5. **Given** current Project/Tag selects and detail checkboxes, **When** Smart Add ships,
   **Then** those post-create editing controls keep their existing API behavior.

## Edge Cases

- A bare `#` or `@`, a sigil followed by an unsupported first character, or an unclosed
  quoted token is incomplete: it may open suggestions while typing but remains literal on
  submit and creates nothing.
- Token recognition requires start-of-input, Unicode whitespace, or `(`, `[`, or `{` on
  the left. `C#`, email addresses, URLs, and punctuation-adjacent `word,#tag` are literal;
  users may type `word, #tag` or `word (#tag)` to classify.
- Unquoted names contain Unicode letters/numbers/marks plus internal `_`, `-`, and `.`.
  Sentence-final punctuation terminates the token. Names with spaces or other punctuation
  use quoted form such as `@"Onboarding drop-off"`; `\"` and `\\` are supported escapes.
- Tag identity is deduplicated by canonical normalized name/ID, not raw spelling. `#Calls`,
  `#calls`, and a selected `Calls` suggestion assign one Tag.
- A contextual Tag is unioned with inline Tags. A contextual Project is the initial default
  and is replaced by the final inline Project token.
- All recognized Tag and Project spans are removed even when duplicated or superseded.
  Empty wrappers containing only a token are removed; remaining whitespace collapses;
  non-wrapper punctuation is preserved.
- If cleanup leaves no non-whitespace task title, submission is blocked and no
  classification is created.
- Existing display casing wins for a match. A newly created name preserves the first
  surviving token's display spelling after NFKC and whitespace normalization.
- Archived Projects and deleted Tags are not suggestions or active matches. The same
  normalized display name may create a new active record under current organization rules.
- Editing text after choosing a suggestion reparses the field. If the chosen token is
  changed, its prior selection is discarded; no side effect occurs until Task submission.
- A stale Project/Tag list may cause the suggestion menu to differ from server resolution;
  the atomic command is authoritative and cache invalidation refreshes the visible result.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The existing `TaskCreator` title input MUST remain the only composition
  surface; Smart Add may add an anchored suggestion popup but MUST NOT introduce a parallel
  composer or mobile-first redesign.
- **FR-002**: `#` MUST represent Tag and `@` MUST represent Project everywhere in new task
  classification copy and chips.
- **FR-003**: Parsing MUST follow the normative grammar and cleanup algorithm in
  `contracts/smart-add.md`.
- **FR-004**: Suggestions MUST be caret-local, type-specific, drawn from already-loaded
  active owner-scoped Project/Tag queries, case-insensitive after NFKC normalization, ranked
  exact/prefix/word-prefix/substring, deterministic, and capped at eight visible results.
- **FR-005**: Keyboard behavior MUST support ArrowUp/ArrowDown, Enter/Tab acceptance,
  Escape dismissal, a second Enter or Ctrl/Cmd+Enter submission, and mouse selection without
  losing the draft.
- **FR-006**: Completed unknown names MUST resolve-or-create only when the Task is submitted;
  merely typing or selecting a suggestion MUST have no durable side effect.
- **FR-007**: A Task MUST have zero or one Project and zero or more unique Tags. Project
  tokens are processed left-to-right with last-token-wins; Tags use set-union semantics.
- **FR-008**: Every committed classification token, including duplicate Tags and superseded
  Projects, MUST be absent from the persisted/displayed clean Task title.
- **FR-009**: Classified submission MUST use one owner-scoped idempotent atomic command;
  validation failure MUST leave no command-created Project, Tag, or Task.
- **FR-010**: Existing `POST /tasks`, `PATCH /tasks/{id}`, voice Task creation, and literal
  title-edit behavior MUST NOT parse Smart Add syntax.
- **FR-011**: Existing contextual create MUST compose with Smart Add: active Tag view adds
  its Tag unless duplicated; active Project view supplies the Project unless an inline
  Project replaces it; current state and Waiting requirements remain unchanged.
- **FR-012**: Existing row/detail Project and Tag assignment controls MUST continue to work
  as post-create editing controls in this slice.
- **FR-013**: Task classification display MUST render Tags as `#<display name>` and Project
  as `@<display name>` without storing sigils in Task references or duplicating a legacy
  stored prefix.
- **FR-014**: Success MUST invalidate task lists/details/counts plus Project and Tag query
  caches; an error MUST preserve the raw draft and expose the existing actionable API error.
- **FR-015**: Smart Add MUST remain desktop/web scoped. Responsive regressions are forbidden,
  but no mobile-specific new composition is required.

### Key Entities

- **Smart Add token**: Ephemeral parsed span with kind, raw/display name, completion state,
  and source offsets. It is never persisted.
- **Classification reference**: API input containing exactly one active record ID or one
  display name to resolve-or-create.
- **Smart Add result**: Composite Task, resolved Project/Tags, and IDs created by this
  command, persisted under one idempotency key.
- **Task / Project / Tag**: Existing Tasks-module records; their ownership, lifecycle,
  revisions, and stable ID relationships remain unchanged.

## Assumptions & Dependencies

- The active Project and Tag sets are small enough to filter client-side because the current
  APIs already return complete active lists and the shell loads both before rendering.
- Existing owner command serialization and SQLite transaction boundaries are the atomicity
  mechanism; no broker, service extraction, or new persistence store is required.
- Project/Tag canonical name normalization remains NFKC + trim/collapse whitespace +
  casefold as implemented by the Tasks module.
- This feature has no effect on voice provisional capture, confirmation, privacy, remote AI,
  CRT, Weekly Review, due date, Priority, or lifecycle semantics.

## Out of Scope

- Parsing Smart Add syntax during task title edits, task detail edits, voice Brain Dump,
  mobile capture, API clients using `POST /tasks`, or bulk import.
- Fuzzy/AI classification, synonyms, typo correction, remote suggestion search, or ranking
  by usage frequency.
- Removing the existing post-create assignment controls or redesigning the shell.
- Project/Tag lifecycle changes, CRT linking, recurrence, reminders, or additional sigils.

## Success Criteria *(mandatory)*

- **SC-001**: Focused parser fixtures cover 100% of the grammar/edge-case table and produce
  byte-for-byte expected clean titles and classification order.
- **SC-002**: Automated API tests prove one submit creates exactly one Task and only the
  required missing classifications, with zero partial database writes on forced failure.
- **SC-003**: Existing-name, unknown-name, duplicate-Tag, contextual-default, and repeated-
  Project browser scenarios all persist the expected IDs and clean title.
- **SC-004**: Plain-title, email, `C#`, escaped-sigil, row-title-edit, task-detail, and Voice
  Brain Dump regression tests retain literal behavior.
- **SC-005**: Desktop keyboard and mouse flows expose the correct suggestion type and allow
  completion without pointer-only interaction; the existing 1280x780 shell remains within
  its accepted visual regression tolerance.
