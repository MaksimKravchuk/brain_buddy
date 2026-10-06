# Existing PR review findings

PR: https://github.com/MaksimKravchuk/brain_buddy/pull/268
Initial reviewed commit: `9f0d992381033a6a00f1d1bae226aae5d768ca63`.

This is finding triage, not an independent planning approval.

- Staged rollout: accepted. Add the server-owned `task_mcp` flag to the existing
  SQLite inventory with OFF/selected-users/ON modes, fresh/upgrade default OFF,
  per-request admission including discovery, and a worker recheck before commands.
- Frozen dependency lock: accepted. Regenerate `backend/uv.lock` for MCP and verify
  installation/startup in a clean Python 3.11 environment with `uv sync --frozen`.
- Deferred planning review: the repository's pre-implementation review requirement
  was intentionally overridden by the owner's explicit session instruction:
  «Сейчас пока мы только GPT-функционал добавляем, ревью и всё такое мы сделаем
  позже». This was recorded in `intake.md` before implementation. No `approved`
  or `founder-accepted` verdict is invented; independent review and ASK release
  approval remain pending. Handling existing automated findings does not request
  a new review or authorize production landing.

The required CI secret scan reported only the never-issued owner-isolation fixture
password on two complete known lines. The exception pins the email, field names
and literal value; replacing the password or adding another credential remains
subject to scanning. The existing guardrail suite checks these constraints.
