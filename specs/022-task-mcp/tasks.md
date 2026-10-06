# Task MCP tasks

- [x] T001 Freeze the four-tool scope and deferred-review boundary in this directory.
- [x] T002 Cover the MCP wire contract in `backend/tests/test_task_mcp.py`.
- [x] T003 Add the MCP adapter/configuration/mount in `backend/app/api/mcp.py`,
  `backend/app/core/config.py`, `backend/app/main.py`, `backend/pyproject.toml`.
- [x] T004 Document enablement, credentials, deletion/retry semantics and GPT
  connection in `docs/mcp.md`, `.env.example`, `README.md`.
- [x] T005 Complete candidate checks and record actual results in `acceptance.md`.
- [x] T007 Correct PR findings: frozen lock, staged task_mcp audience and narrowly
  pinned synthetic password exception; rerun applicable checks before publishing.
- [ ] T006 Independent review and authorized production release: explicitly
  deferred by the owner; no automatic promotion of this ASK-class candidate.
