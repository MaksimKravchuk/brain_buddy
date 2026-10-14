# Contract: client release epoch and "update required" (027)

Realizes spec FR-018 and design ids M-01, D-01, D-02 (+ CLI/MCP wording in
[design.md](../design.md)). Revised after planning review campaign 1: the
signal is a dedicated integer, not the marketing version (all clients report
`0.1.0` today and iOS CI bumps only the build number).

## Client header

Every first-party client sends on every `/api/*` request:

```
X-Client-Epoch: <integer>
X-Client: brainbuddy-<surface>/<version>   # unchanged meaning: logging only
```

- `X-Client-Epoch` is a constant compiled into the client
  (`CLIENT_EPOCH = 1` for the first build made for the Rust server) and bumped
  only when the server raises the minimum. Old builds do not send it.
- `X-Client` is added for `web` (build version) and `cli` (crate version);
  `ios`/`macos` already send it (`BrainBuddyAPIClient.swift:328`,
  `WorkspaceHost.swift:127`). It is not used for admission.

## Server-to-client signal

- `GET /api/meta` — unauthenticated, exempt from the gate, no owner data:
  `{ "server_epoch": 1, "min_client_epoch": 1 }`. The old server has no such
  route (404), which clients read as "old server" (`server_epoch` 0).
- Every response from the new server carries `X-Server-Epoch: <n>`.
- Native apps call `/api/meta` **before any sign-in, session use or sync
  push**: on launch, on reconnect, on return to the foreground and before
  each sync cycle (design M-02/D-03). It drives the fresh-start transition
  (.00 → .01); an `X-Server-Epoch ≥ 1` seen on any response also stops sync
  immediately. A pending change from before cutover is therefore never pushed
  to the new server; as a second barrier, the old session is unknown to the
  new server (accounts are not migrated), so such a push would get 401.

## Server rule

- Config `BRAIN_BUDDY_MIN_CLIENT_EPOCH` (integer, default 1).
- On a **gated** route: missing, non-integer or lower `X-Client-Epoch` →
  **426 Upgrade Required**, error envelope code `UPGRADE_REQUIRED`, message
  from design.md (web/native/CLI variants chosen by `X-Client` surface, web
  wording when absent), `X-Correlation-ID` set. The request is rejected in
  middleware **before** authentication and before any handler: nothing is read
  or written.
- **Gated**: every `/api/*` route listed in
  [capability-inventory.md](capability-inventory.md) §1 except the exempt set.
- **Exempt** (callers are not first-party builds):
  - `/health`, `/api/health`
  - identity-provider redirects/callbacks and Apple server-to-server
    notifications (inventory rows for the Google/Apple/browser-grant callback
    and notification routes)
  - A2A peer callbacks (authenticated per agent, spec 014)
  - OpenAPI/docs routes
  - `/api/meta`
  - the MCP endpoint (rule below)
  - `/api/__test__/*` (test environments only)
- The exempt set is a single constant in `bb-api` with a conformance test per
  entry; adding a route requires choosing gated/exempt explicitly.
- Production smoke and reachability checks in
  `.github/workflows/deploy-fly-production.yml` send the current epoch on
  gated routes.

## MCP

- New endpoint path: `/api/mcp/v2/`. The old `/api/mcp/` path stays mounted on
  the new server only to refuse: every MCP request there (initialize, list,
  call) gets an MCP error carrying the design.md MCP refusal text; no tool
  executes.

## Client behavior

- Show the refusal only on an explicit `426`/`UPGRADE_REQUIRED`, never on
  offline, timeout, 5xx or unreadable responses (design M-01.03/.08).
- Native: the refusal state clears when the app is updated **or** a later
  request succeeds (so a corrected server minimum unblocks without a release).
  Web: a persistent alert toast with a Reload button (design D-02). Updated
  CLI: prints the design.md text and exits with code **12** (0, 2–11 and 130
  are taken — `cli/README.md` exit table; 11 is authorization
  denied/expired/consumed), mapped before the generic 4xx arm; `cli/README.md`
  and `specs/024-agent-cli/contracts/cli.md` gain the row.
- Pre-cutover CLI builds (no epoch header) receive the 426 and, by owner
  decision, show their generic "Server rejected the request." and exit 2;
  nothing is written.
