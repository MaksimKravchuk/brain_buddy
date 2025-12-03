# Contract: Local Deployment Workflows

## Setup Workflow (Initial Deploy)
- **Trigger**: Developer needs first-time local stack.
- **Inputs**: Cloned repo on target branch; `.env.example` copied to `.env` with local values; Docker/Compose, Node, Python installed.
- **Process (sequential)**:
  1) Install prerequisites (Docker/Compose, Node, Python tools per docs).
  2) Copy `.env.example` → `.env`, fill required values (safe defaults provided).
  3) Run documented compose/deployment command (to be finalized in quickstart).
  4) Run health checks: backend endpoint/smoke script, frontend URL reachability.
- **Outputs**: Running local stack on documented ports; health checks passing.

## Refresh Workflow (After Code Change)
- **Trigger**: New commits pulled or local code modified.
- **Process**:
  1) Pull latest changes or apply local modifications.
  2) Run refresh command(s): compose rebuild/restart or dev server restart per quickstart.
  3) Verify logs for successful start; rerun health checks/smoke script.
- **Expectation**: Completes within 5 minutes; uses current branch code without manual file copy.

## Troubleshooting/Recovery Workflow
- **Trigger**: Setup or refresh fails (missing env, port conflicts, stale volumes/caches).
- **Process**:
  1) Inspect documented logs/health endpoints to identify failure.
  2) Apply targeted fixes: free ports, reset volumes/caches, correct env values.
  3) Re-run setup or refresh workflow; confirm health checks.
- **Output**: Restored running stack without manual clean-room rebuild unless instructed.

## Health Check Contract
- **Backend**: Smoke script must return success status; service responds at documented endpoint.
- **Frontend**: HTTP request to documented URL returns 200 and serves current branch assets.
- **Timing**: Health checks run after initial setup and after every refresh.

_No new external API contracts introduced; workflows operate on existing project tooling and scripts._
