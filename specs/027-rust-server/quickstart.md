# Quickstart: validating the Rust server (027)

Run guide for proving the spec's success criteria. Commands name targets the
plan adds; exact flags live in the `Makefile` once they land.

## Prerequisites

- Rust toolchain from `rust/rust-toolchain.toml` (1.99.0), `cargo-llvm-cov`,
  `cargo-mutants`, `sqlx-cli` (versions pinned in CI).
- Docker for the Compose stack (adds a `postgres` service).
- `.env` from `.env.example` with `BRAIN_BUDDY_ENV=test` and
  `BRAIN_BUDDY_TEST_CONTROL_TOKEN` for local black-box runs.

## V1 — Capability dispositions (SC-003, FR-001)

1. Start the Python server with the test control API:
   `make dev-backend` (env `BRAIN_BUDDY_ENV=test`).
2. `make conformance BASE_URL=http://localhost:8000` — every conformance test
   attached to a `port` row must pass. This proves the test encodes today's
   behavior.
3. Start the Rust server: `make dev-server` (PostgreSQL + MinIO from Compose).
4. `make conformance BASE_URL=http://localhost:8001` — every `port` and
   `change` conformance test must pass.
5. `scripts/check_capability_inventory.py` reads
   `contracts/capability-dispositions.json` and fails when any inventory row
   lacks a disposition; when a `port` row's evidence (conformance,
   integration, config-test, job-test or deploy-check, by kind) is missing or
   not green on Rust; when a `port` row with conformance evidence differs
   between the Python and Rust runs; when a `change` row lacks its Rust
   evidence or the FR approval reference; or when a `remove` row lacks the
   FR-001 approval reference. Non-HTTP rows never need a conformance test.

## V2 — Web E2E on the Rust stack (SC-002)

`make test-e2e` with `compose.yaml` using the Rust image. All 19 Playwright
specs pass; no spec shells into a container or runs Python (they use
[contracts/test-control.md](contracts/test-control.md)).

## V3 — No Python in the server (SC-001)

- `docker run --rm --entrypoint sh <server-image> -c 'command -v python3 python || true'`
  prints nothing; the image's package list contains no Python package.
- `git ls-files backend rust/bindings/python rust/crates/bb-server rust/crates/bb-api rust/crates/bb-app rust/crates/bb-store rust/crates/bb-providers | grep '\.py$'`
  prints nothing after the removal slice. Python elsewhere (repository
  tooling, installer tests, test support) is allowed by FR-002 and not
  checked here.

## V4 — One implementation, one runtime (SC-006)

- `cargo metadata` lists no `pyo3`/`bb-python` package, and
  `rg -n "bb_core|rust_core_sync" rust cli frontend/src ios macos .github`
  returns nothing (historical ADRs and specs are not searched).
- `rg -n "isRustSelected|RustRuntimePilot|LegacyStoreImporter" ios macos`
  returns nothing.

## V5 — Release epoch (FR-018, design M-01/D-01/D-02)

- `curl -i $BASE/api/tasks` without `X-Client-Epoch` → `426`, code
  `UPGRADE_REQUIRED`, `X-Correlation-ID` present, no row written (check via
  test control read-back).
- `X-Client-Epoch: 0` → `426`; the current epoch → normal.
- `GET /api/meta` without headers → `200 {"server_epoch":1,...}`; every
  response carries `X-Server-Epoch`.
- Every exempt route in [contracts/release-epoch.md](contracts/release-epoch.md)
  answers normally without the header; the old `/api/mcp/` path refuses every
  MCP call with the design.md text and runs no tool.

## V6 — Fresh start (FR-021, design M-02/D-03)

1. Install the pre-cutover build, create local tasks, waiting changes and a
   draft offline; install the new build while the server is still the old one:
   nothing is deleted, the app works normally (.00).
2. Point it at the Rust server: the confirmation (.01) names the counts;
   "Not now" leaves every file untouched and makes no network request; the
   screen returns on relaunch.
3. "Delete and continue": every artifact in the data-model legacy inventory
   is gone (the XCTest iterates `LegacyArtifacts` and asserts each); then
   sign-in, then the empty Inbox; the test control read-back shows nothing
   from the old store reached the server.
4. Kill the app during deletion and inject a disk error: next launch resumes
   without asking (.06) or shows .05 with Try again; no network request until
   the reset is done.
5. Keep an app running across cutover with pending changes: before its next
   sync cycle it calls `/api/meta`, sees epoch 1, stops syncing and moves to
   .01; nothing from the old store reaches the new server.
6. Steps 1–5 run in XCTest/UI tests in CI; after cutover, steps 2–3 are
   repeated once on the reference iPhone 11 and MacBook Air M1 and recorded
   in `evidence/apple-pilot.md`.

## V7 — Performance parity (SC-005)

`make bench-web-flows BASE_URL=…` against each server on the same machine,
same container limits (2 vCPU, 1 GB like production), release builds, test
control seeding:

- Dataset: 1 owner with 10,000 tasks (mixed states), 200 projects, 50 Tags,
  one 200-node CRT tree; seeded identically for both servers.
- Mix per run (sequential, concurrency 1, then concurrency 8): list Inbox,
  list Next, task detail, create, edit title, move to Next, complete, Review
  session open, Review decision, CRT tree load, CRT node edit — 50 requests
  of each per run after a 20-request warm-up.
- 10 runs; any non-2xx except expected 409 fails the run.
- Per flow, compare the pooled p95 of all runs: Rust ≤ 110% of Python.
- Report in `evidence/bench.md` with SHAs and machine description.

## V8 — Cutover drill (FR-019)

On a staging Fly org, run `.github/workflows/cutover-rehearsal.yml` (staging environment only; research R10): deploy Python
with synthetic data; **stop Python** (0 machines, verified); deploy Rust app +
Postgres + buckets; switch `BACKEND_ORIGIN`; smoke. Then rollback: **stop
Rust** (verified), origin back, start Python, verify the pre-cutover data.
Then repeat the cutover and run the erase step. Record per step the
timestamps of the last write accepted by one server and the first by the
other (from correlation-ID logs) in `evidence/cutover-rehearsal.md`; any
overlap fails the drill.

## V9 — Production pilot (SC-004, SC-007)

After cutover and erase: 026 quickstart Q01–Q12 (except Q06) on iPhone 11 /
iOS 26 and MacBook Air M1 / macOS 26 against production, including Q03, Q08
and Q10, each destructive step authorized when it runs, with synthetic pilot
accounts; recorded in `evidence/apple-pilot.md`. Seven-day watch: run
`fly ssh console -a brain-buddy-api -C "bb-server reconcile"` once a day;
record its counters (accepted commands, outcomes, feed entries, orphans,
duplicates), the deployed SHA and image digest, `fly status` for both app
names (only `brain-buddy-api` exists after the erase) and the reference
devices' pending-queue sizes in `evidence/production-watch.md`. A redeploy
during the watch is recorded with its SHA; it does not reset the count unless
a check fails. Any orphan or duplicate fails SC-007 and
restarts the seven days after the fix.
