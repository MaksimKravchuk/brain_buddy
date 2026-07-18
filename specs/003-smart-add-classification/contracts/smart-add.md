# Smart Add grammar and API contract

Status: Normative for `specs/003-smart-add-classification`

## 1. Inline grammar

Smart Add is parsed only by the desktop/web new-task composer.

```text
sigil          = "#" | "@"
left-boundary  = start-of-input | Unicode whitespace | "(" | "[" | "{"
unquoted-name  = name-char (name-char | internal-punctuation)*
name-char      = Unicode Letter | Number | Mark | "_"
internal-punctuation = "-" | "." when followed by name-char
quoted-name    = '"' quoted-char+ '"'
quoted-char    = any Unicode scalar except unescaped '"' or line break
escape         = '\\"' | '\\\\'
token          = left-boundary sigil (unquoted-name | quoted-name) right-boundary
right-boundary = end-of-input | Unicode whitespace | punctuation/delimiter
```

`#` produces kind `tag`; `@` produces kind `project`. The left boundary is not part of the
token span. A matching right bracket may become part of the removal span only under the
empty-wrapper cleanup rule below.

For an unquoted token, comma, semicolon, colon, exclamation, question mark, closing bracket,
and a period not followed by a name character terminate the token and remain title text.
Unsupported punctuation also terminates the token. An unquoted body must start with a
`name-char`; `#-foo` is incomplete/literal.

Quoted form supports existing names with spaces or delimiter punctuation:

```text
#"deep work"
@"Onboarding drop-off"
#"client:alpha"
```

Inside quoted form, `\"` represents `"` and `\\` represents `\`. An unclosed quote is
incomplete and remains literal at submission.

At a valid left boundary, `\#` and `\@` escape a sigil. The escape backslash is removed
from the clean literal title; the following text is not classified. Backslashes elsewhere
are ordinary title text.

### Recognition examples

| Input fragment | Result |
|---|---|
| `Plan launch #work` | completed Tag `work` |
| `Plan @"Launch v2"` | completed Project `Launch v2` |
| `Plan (#work)` | completed Tag; wrapper eligible for removal |
| `Plan #work, tomorrow` | Tag `work`; comma remains title punctuation |
| `Email max@example.com` | no token |
| `Read C# notes` | no token |
| `word,#tag` | no token; no valid left boundary |
| `word, #tag` | completed Tag `tag` |
| `\#literal title` | literal `#literal title` |
| `Plan #` | incomplete; literal `#` |
| `Plan @"Launch v2` | incomplete; literal text |

## 2. Active token and suggestions

The active token is the single token candidate whose body contains the input caret. Bare
sigils and unclosed quoted bodies may be active for suggestions even though they are not
committed at submission.

The query is the decoded body text from the sigil to the caret, trimmed only for matching.
Suggestions use the already-loaded active `ProjectResponse[]` or `TagResponse[]`; typing
MUST NOT issue a network request. Normalize query and names with Unicode NFKC and
case-insensitive comparison. The backend remains authoritative where JavaScript lowercasing
and Python casefold differ.

Rank deterministically:

1. exact normalized name;
2. normalized prefix;
3. prefix of any whitespace/hyphen-delimited word;
4. normalized substring;
5. tie-break by normalized display name, then opaque ID.

Show at most eight entities. With an empty query, show the first eight in deterministic
name order. When the non-blank query has no exact normalized match, append one non-durable
`Create #<name>` or `Create @<name>` option; choosing it only commits the token draft and
MUST NOT call the API.

Selecting an existing suggestion replaces the active span with the canonical display name.
Use unquoted form only when the complete display name satisfies `unquoted-name`; otherwise
serialize as quoted form with escapes. Move the caret after the token and insert one space
only when no whitespace or terminating delimiter already follows.

Keyboard contract:

- ArrowDown/ArrowUp moves the active option and wraps within the popup.
- Enter or Tab accepts the active option while the popup is open.
- Escape closes the popup without changing text.
- Enter submits only when the popup is closed; after acceptance a second Enter submits.
- Ctrl+Enter or Cmd+Enter submits directly with the current parsed draft.
- Mouse selection performs the same replacement and returns focus to the title input.

The popup is a labelled listbox anchored to the existing input. The input uses
`aria-expanded`, `aria-controls`, and `aria-activedescendant`; options use `role=option`.

## 3. Parse, merge, and clean algorithm

On every input/caret change, parse the entire value into ordered spans. Submission applies
these deterministic steps:

1. Keep only syntactically completed tokens. Bare sigils, invalid bodies, escaped sigils,
   and unclosed quoted forms remain literal.
2. Decode and display-normalize each name with NFKC, trim, and internal whitespace collapse.
3. Seed classifications from context: Project-view `project_id` is the initial Project;
   Tag-view `tag_id` is the first Tag. Other views seed neither.
4. Process completed tokens left-to-right.
   - Tags: append by first occurrence, deduplicating selected IDs and canonical normalized
     names. A name resolving to the same ID as a contextual Tag is a duplicate.
   - Projects: replace the current Project candidate. Only the final candidate is sent;
     superseded unknown names MUST NOT be created.
5. Remove every completed token span, including duplicate Tags and superseded Projects.
6. If a token is the only non-whitespace content inside an immediately matching `(...)`,
   `[...]`, or `{...}` wrapper, remove that wrapper too. Do not remove non-empty wrappers.
7. Replace each escaped `\#`/`\@` at a valid boundary with its literal sigil.
8. Collapse all Unicode whitespace runs to one ASCII space, trim ends, and remove whitespace
   immediately before `,.;:!?)]}`. Preserve all other punctuation and original title casing.
9. Reject submission when the clean title is empty or exceeds the existing 500-character
   Task limit, or a normalized classification name is empty/exceeds 500 characters.

Examples:

| Raw input | Clean title | Tags | Project |
|---|---|---|---|
| `Draft update #work @launch` | `Draft update` | `work` | `launch` |
| `Draft #work #WORK` | `Draft` | one normalized Tag | none |
| `Draft @old @new` | `Draft` | none | `new`; `old` not created |
| `Draft (#work) today` | `Draft today` | `work` | none |
| `Draft #work, today` | `Draft, today` | `work` | none |
| `Discuss C# and max@example.com` | unchanged | none | none |
| `Use \#literal marker` | `Use #literal marker` | none | none |
| `#work @launch` | invalid empty title | no writes | no writes |

## 4. Context compatibility

The current creator state and Waiting rules remain authoritative:

- Inbox/Next/Someday create in that state.
- Waiting still requires a non-blank `waiting_for` before submit.
- Project/Tag views default to Inbox, as they do now.
- Project view sends its current Project ID unless a completed inline Project replaces it.
- Tag view sends its current Tag ID unioned with completed inline Tags.

A submission with no completed classification token MUST continue to use the existing
`POST /tasks` request. A submission with one or more completed tokens uses the compound
endpoint below, including contextual ID references. This preserves byte-for-byte literal
behavior and minimizes the new contract surface.

Smart Add does not run in row title edit, Task detail title edit, Voice Brain Dump, import,
or other API clients. Existing row/detail Project selects, Tag select/removal, and Tag
checkboxes remain post-create editing controls.

## 5. Compound API

### Request

```http
POST /api/tasks/smart-add
Idempotency-Key: <required>
Content-Type: application/json
```

```json
{
  "title": "Call supplier",
  "details": null,
  "state": "next",
  "waiting_for": null,
  "due_date": null,
  "priority": "none",
  "project": { "name": "Vendor launch" },
  "tags": [
    { "id": "tag_existing" },
    { "name": "calls" }
  ]
}
```

`SmartAddClassificationRef` is a strict XOR:

```text
{id: opaque string, name absent}
OR
{id absent, name: non-blank display name up to 500 characters}
```

`project` is nullable/omittable. `tags` defaults to `[]`. Duplicate refs are accepted and
canonicalized to one Tag; malformed refs are `422`. The remaining Task fields have the same
shape/defaults and Waiting invariants as `TaskCreateRequest`. `source_capture_ids` is not
accepted: capture provenance continues through the dedicated confirmation workflow.

The browser sends only the final Project reference. The server MUST NOT receive or create
superseded Project candidates.

### Response

```http
201 Created
```

```json
{
  "task": { "id": "task_...", "title": "Call supplier", "project_id": "project_...", "tag_ids": ["tag_existing", "tag_..."], "revision": 1 },
  "project": { "id": "project_...", "name": "Vendor launch", "state": "active", "revision": 1, "open_task_count": 1 },
  "tags": [
    { "id": "tag_existing", "name": "existing", "state": "active", "revision": 1, "open_task_count": 1 },
    { "id": "tag_...", "name": "calls", "state": "active", "revision": 1, "open_task_count": 1 }
  ],
  "created": {
    "project_id": "project_...",
    "tag_ids": ["tag_..."]
  }
}
```

The actual nested `task`, `project`, and `tags` values use the complete existing response
schemas; fields are abbreviated above. `created.project_id` is null when no Project was
created. `created.tag_ids` preserves resolved Tag order filtered to records created by this
command.

### Resolution and transaction rules

Within one owner-scoped serialized SQLite transaction:

1. Validate the complete request before durable writes.
2. Resolve ID refs as same-owner active records; absent/other-owner is `404`, inactive is
   `400`.
3. Normalize every name ref with existing Project/Tag rules (NFKC, whitespace collapse,
   casefold). Resolve an active exact match; otherwise create an active record preserving
   normalized display spelling.
4. Canonicalize duplicate Tags while preserving input order.
5. Create one Task with resolved IDs and existing state/Waiting/order invariants.
6. Persist one composite idempotency result and return all resolved projections.

Same key + same body returns the original composite response. Same key + another body is
`409`. A failed command commits none of its Task/Project/Tag database writes. Composite
idempotency reconciliation repairs the Task and every returned Project/Tag compatibility
sidecar when needed.

### Error mapping

- `400`: inactive classification, semantic state/Waiting/title invariant failure.
- `401`: unauthenticated.
- `404`: absent or other-owner ID reference.
- `409`: conflicting idempotency-key reuse or normalized-name conflict that cannot be
  resolved safely.
- `422`: malformed strict request/XOR, invalid enum/date, or field length.

Existing error envelope and `X-Correlation-ID` behavior are unchanged. Errors MUST NOT echo
raw title/classification content into logs.

## 6. Rendering contract

- Task row Tag chips: `#${stripLegacySigil(tag.name)}`.
- Task row Project chip: `@${stripLegacyProjectSigil(project.name)}`.
- Tag navigation, Tag view heading, Tag detail checkboxes, and available-Tag options use
  `#`, not the historical Context-style `@`.
- Project navigation headings remain ordinary project names; `@` is required on task
  classification chips and Smart Add tokens, not every Project heading.
- `stripLegacySigil` removes one leading `#` or historical `@` for presentation only. IDs
  and stored display names remain canonical; do not mutate Tasks to rewrite labels.
- Current selects/checkboxes remain wired assignment controls. A new chip must be a truthful
  link/button or a non-interactive `<span>`; do not add dead button styling.
