# Task management through MCP

Status: implementation candidate; independent review and production release pending.

## User stories and acceptance

1. As an authenticated GPT user, I discover the task tools and create an Inbox task.
   The task appears in the ordinary BrainBuddy task API with the same ID and fields.
2. I find an existing task and remove it from my active lists. Its latest revision
   is checked, cancellation is recoverable, and replay does not apply a second change.
3. My session scopes every tool to my own tasks. A second user's ID cannot be read
   or mutated, and logout/expiry remove MCP access.

## Requirements

- **FR-001**: Implement Streamable HTTP at `<api_prefix>/mcp/` with standard
  initialization/discovery and `list_tasks`, `get_task`, `create_task`, `delete_task`.
- **FR-002**: Creation uses the existing task command and caller-supplied mutation
  key; identical retries return the stored response and conflicting reuse fails.
- **FR-003**: Deletion is the existing reversible `cancel` transition. Require
  `expected_revision` and mutation key; stale revisions cannot change a task.
- **FR-004**: Require a valid session bearer on every request; reject cookies-only,
  missing/invalid/expired/revoked sessions and cross-owner access. Derive ownership
  from authentication, never from tool input.
- **FR-005**: Preserve native field validation, search, pagination, response fields,
  and owner validation of project/tag references; return MCP tool errors.
- **FR-006**: Enforce configured Host checks and reject browser Origins. Produce
  operation/result logs with correlation context without credentials, titles or
  details. Unexpected failures expose only a safe retry instruction.
- **FR-007**: Default MCP OFF and require explicit opt-in. Disabling removes the
  endpoint without altering tasks. Document enablement and a GPT Responses API client.

## Edge cases and privacy

Task IDs may be absent or belong to another owner; both follow native not-found
semantics. Completed tasks cannot be cancelled. Waiting needs a waiting-for value.
Lost responses are retried with the original key/arguments. Empty lists and opaque
cursors preserve the native list contract. Each HTTP request is stateless, so no
MCP session carries user identity across callers.

The client intentionally sends task data to its chosen GPT provider. The dedicated
session is an account credential and follows existing expiry/revocation; it must
not enter prompts, logs or version control. No new persistent data is introduced.

## Success criteria

- **SC-001**: The official SDK completes discovery/create/read/delete/list and the
  ordinary task API observes those same mutations.
- **SC-002**: Cross-owner access, replay conflicts, stale revisions and revoked
  sessions cannot apply the forbidden mutation.
- **SC-003**: OFF, validation and transport failures are covered without changing
  existing task behavior. Backend quality gates pass on the candidate.

No rendered UI changes. Weekly Review, voice, agent relay, CRT, hard erasure and
OAuth onboarding are outside this iteration. Review/release evidence remains
pending rather than being recorded as passing.
