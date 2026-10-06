# Task MCP

BrainBuddy exposes four task tools over **Streamable HTTP** at `/api/mcp/`
(or `<BRAIN_BUDDY_API_PREFIX>/mcp/`). The trailing slash is part of the endpoint.
The server uses the official Python MCP SDK and the existing TaskService, task
response schemas, owner isolation, revision checks and idempotency receipts.

| Tool | Inputs | Result |
| --- | --- | --- |
| `list_tasks` | Optional `q`, `state`, `include_completed`, `include_cancelled`, `cursor`, `limit` (1–200) | Tasks, state counts, `has_more`, `next_cursor` |
| `get_task` | `task_id` | Task with current `revision`, subtasks and comments |
| `create_task` | `title`, `idempotency_key`; optional `details`, `state`, `due_date`, `priority`, `project_id`, `tag_ids`, `waiting_for` | Created task |
| `delete_task` | `task_id`, `expected_revision`, `idempotency_key` | Cancelled task |

New tasks default to Inbox. Supported open states are `inbox`, `next`, `waiting`
and `someday`; Waiting requires `waiting_for`. Dates use `YYYY-MM-DD` and priorities
are `none`, `low`, `medium`, `high`. Project/tag IDs must belong to the caller.

**Deletion is reversible cancellation**, matching BrainBuddy's existing lifecycle.
It removes an open task from the default active lists, retains its data, and returns
`state: cancelled`. To find it again use `include_cancelled: true`. Restore through
the existing task `reopen` command. Cancelling a completed task is rejected.

Find tasks before deleting them and use the returned ID and revision. Each mutation
requires a caller-generated, nonempty `idempotency_key` (up to 200 characters).
Reuse the key and identical arguments after a timeout or lost response. A changed
payload with the same key or a stale revision returns a tool error without applying
the requested change. Existing receipt retention rules still apply.

## Enable

Install the backend normally; `mcp` is a runtime dependency. Set:

```dotenv
BRAIN_BUDDY_MCP_ENABLED=1
BRAIN_BUDDY_MCP_ALLOWED_HOSTS=localhost:*,127.0.0.1:*,[::1]:*,backend:8000
```

Run the backend with `make dev-backend` or the existing Compose stack. The allowlist
must match the **Host header seen by the backend**. The existing nginx proxy sets
Host to its upstream hostname: `backend:8000` in Compose and
`brain-buddy-backend.fly.dev` with the checked-in Fly configuration. For that Fly
deployment set `BRAIN_BUDDY_MCP_ALLOWED_HOSTS=brain-buddy-backend.fly.dev`; add another
host only if a different access path actually forwards it. The `/api` frontend
proxy also carries MCP. Serve external clients over HTTPS. Requests with an `Origin` header are
rejected; this endpoint is for server/client integrations.

MCP defaults **OFF**. Only `BRAIN_BUDDY_MCP_ENABLED=1` enables it; disabling the
setting and restarting removes the endpoint without altering tasks. The switch
controls exposure; it never grants access to data.

## Authenticate

Send `Authorization: Bearer <BrainBuddy session token>` on every MCP request.
Obtain a dedicated session with the existing `/api/auth/login` endpoint. Its
`brainbuddy_session` cookie value is the token (use the configured cookie name if
overridden). The MCP endpoint accepts the bearer header only, so a browser's
ordinary session cookie cannot authorize tool calls.

The token grants access to the signed-in account's tasks. It is a sensitive
credential: keep it in a secret store/environment, never in prompts or source
control. Session expiry, logout, password-change revocation and account deactivation
take effect on subsequent MCP requests. Tokens and task content are not added to
MCP operation logs; requests retain BrainBuddy's correlation ID.

## Use with GPT through the OpenAI Responses API

The server must be reachable over HTTPS from OpenAI. The example below runs in your
own client application; install `openai` and `httpx` there. Set `OPENAI_API_KEY`,
`OPENAI_MODEL`, `BRAIN_BUDDY_BASE_URL` and `BRAIN_BUDDY_EMAIL`. It creates a dedicated
BrainBuddy session without displaying the password or token:

```python
import getpass
import os

import httpx
from openai import OpenAI

base_url = os.environ["BRAIN_BUDDY_BASE_URL"].rstrip("/")
with httpx.Client(base_url=base_url, timeout=30) as brainbuddy:
    login = brainbuddy.post("/api/auth/login", json={
        "email": os.environ["BRAIN_BUDDY_EMAIL"],
        "password": getpass.getpass("BrainBuddy password: "),
    })
    login.raise_for_status()
    token = brainbuddy.cookies["brainbuddy_session"]
    try:
        result = OpenAI().responses.create(
            model=os.environ["OPENAI_MODEL"],
            input="Create an Inbox task: buy milk. Use a fresh idempotency key.",
            tools=[{
                "type": "mcp",
                "server_label": "brainbuddy",
                "server_url": f"{base_url}/api/mcp/",
                "authorization": token,
                "allowed_tools": ["list_tasks", "get_task", "create_task", "delete_task"],
                "require_approval": "never",
            }],
        )
        print(result.output_text)
    finally:
        brainbuddy.post("/api/auth/logout").raise_for_status()
```

The example permits these task tools to run automatically for this request. A
client can restrict `allowed_tools` or use OpenAI's approval flow instead. Reuse
the same dedicated session for a continuing conversation, and revoke it when done.
If your API prefix differs, adjust the login, logout and MCP URLs together.

This iteration supports bearer-capable MCP clients and the Responses API. It does
not implement an OAuth authorization server, dynamic client registration, or the
OAuth connection flow in ChatGPT's app settings. Weekly Review, voice, agent relay
and CRT tools are outside this iteration.

## Verify

```bash
cd backend
pytest tests/test_task_mcp.py --no-cov -q
```

The suite uses the official `ClientSession`/Streamable HTTP client to initialize,
discover tools, create a task, read it, cancel it and verify removal from active
lists. Additional cases exercise owner isolation, session expiry/revocation,
idempotency, stale revisions, validation, pagination, transport security and OFF.

Typical failures:

| Result | Action |
| --- | --- |
| 404 | Verify the exposure setting, API prefix and trailing slash |
| 401 | Obtain a valid dedicated session and send the bearer header |
| 403 / 421 | Check Origin rejection and the exact Host allowlist |
| Tool error: revision conflict | Read the task again and reconcile before a new command |
| Tool error: idempotency conflict | Reuse the original arguments/key for a retry; use a fresh key for a new command |
| Tool error: operation unavailable | Retry with the same mutation key and arguments; inspect correlation-ID logs |

Source: `backend/app/api/mcp.py`; implementation scope: `specs/022-task-mcp/`.
Protocol/SDK references: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
and [OpenAI remote MCP](https://developers.openai.com/api/docs/guides/tools-connectors-mcp).
