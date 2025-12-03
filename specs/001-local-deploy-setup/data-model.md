# Data Model: Local Deployment Setup

## Entities

### Local Deployment Configuration
- **Purpose**: Defines inputs to run backend/frontend locally via compose or dev servers.
- **Attributes**: service ports (frontend, backend, db), env variables (API keys optional, storage paths), volume names/paths (`backend/data`), host prerequisites (Docker, Node, Python), branch reference (current checkout).
- **Validation Rules**: All required env variables must be present; ports must be available or remapped; volume paths must be writable; secrets use placeholders only.
- **State**: Prepared (env ready) → Running (services up) → Updated (after refresh) → Faulted (failed health) → Recovered (post-troubleshoot).

### Health Checks
- **Purpose**: Signals that stack is ready and serving current code.
- **Attributes**: Backend health endpoint or smoke script results; frontend reachability at documented URL; logs showing successful service start; timestamps of last refresh.
- **Validation Rules**: All checks must pass after initial setup and after refresh; failures must include actionable message/log reference.

### Refresh Workflow
- **Purpose**: Procedure to apply new code to running stack.
- **Attributes**: Steps for pulling changes, rebuilding/restarting services, clearing stale volumes/caches when needed; expected timing (<5 minutes).
- **Validation Rules**: Must complete without manual file copy; must re-run health checks; must avoid data loss beyond expected cache clears.
