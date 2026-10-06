# Task MCP implementation plan

References: [spec.md](spec.md), [design.md](design.md), ADR-0001 service ownership,
ADR-0006 task lifecycle, `docs/auth.md`, ADR-0008 and ADR-0023 delivery boundaries.

Use official Python MCP SDK `mcp>=1.30,<2` in `backend/app/api/mcp.py`.
FastMCP owns protocol/schema handling and a stateless JSON Streamable HTTP
transport. Mount below the configured API prefix and compose the session manager
lifespan with the existing application lifespan, preserving shutdown hooks.

SDK bearer middleware verifies an existing opaque BrainBuddy session through
AuthService; request-local auth context supplies identity. Recheck the token
immediately before running each task operation on AnyIO's existing worker pool.
No tool takes an owner ID. Authentication is required even for discovery.

Reuse TaskService and the existing API task projection. Create and cancel retain
the same locks, revision checks, receipt persistence and reference validation.
No task enum, database schema, repository or frontend change. Configure default-OFF
exposure and an explicit Host allowlist; browser Origins remain disallowed.

Bounded acceptance covers design states D-01–D-09 in `test_task_mcp.py`, including
an official SDK client and cross-owner behavior. Run existing backend/frontend
quality gates and applicable repository checks; document any environment blockers.

Risk classification: **ASK**, because MCP adds a bearer-authenticated access path.
The owner explicitly deferred review in this session. Prepare and verify the
candidate on an isolated branch; do not automatically promote it through verified
trunk or claim production acceptance. Review, explicit landing authorization,
exact-SHA release and authenticated production smoke remain release work.

Production acceptance must enable MCP for the intended environment/Host, complete
the authenticated create/read/cancel journey with temporary data and verify active
list cleanup. OFF is the rollback; task state survives it. No additional production
metric is required: existing request/correlation logs plus tool outcome events
provide the bounded operational signal.
