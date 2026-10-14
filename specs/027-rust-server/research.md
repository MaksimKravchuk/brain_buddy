# Research: Rust server (027)

Facts about the current system are cited from the repository at `3764dfc6`.
Every decision below resolves a Technical Context unknown in [plan.md](plan.md).

## Current system in numbers

| Area | Today | Source |
| --- | --- | --- |
| Server code | ~59k lines Python: `modules/tasks` 26k, `modules/agents` 12k, `services` 9k, `api` 6.5k, repositories/core 5k, `workflows/voice_brain_dump` 8k | `backend/app/` |
| Server tests | 123k lines pytest, 177 files, 3,455 tests; 78% import internals, 8% mixed, 14% HTTP-only — and even those run in-process via `create_app()` | `backend/tests/` |
| Web E2E | 19 Playwright specs against the Compose stack; Python hooks: `docker compose exec backend python -m app.cli create-invite` (`frontend/tests/e2e/gtdHelpers.ts:40`), inline `python -c` (`admin-users.spec.ts:13`), `review-seed-aged-task`/`review-run-sweep` (`weekly-review.spec.ts:27`); modern-auth/account run on a Python TLS fixture (`scripts/run_modern_auth_e2e.py`) | `frontend/tests/` |
| Storage | raw `sqlite3`, 7 SQLite files (`tasks`, `agents`, `auth`, `crt_commands`, `voice_operations`, `feature_flags`, `sync_control_ledger`) + JSON tree files with file locks; ad-hoc startup migrations | `backend/app/repositories/`, `modules/*/repository.py` |
| Rust | workspace `rust/` (edition 2024, toolchain 1.99.0, `unsafe_code = forbid`, clippy `all = deny`, exact-pinned deps): `bb-domain`, `bb-protocol`, `bb-client`, bindings `python` (PyO3 0.29.3) and `swift` (UniFFI 0.32.2); separate `cli/` crate (reqwest 0.12, clap) | `rust/Cargo.toml`, `cli/Cargo.toml` |
| Deploy | Fly app `brain-buddy-backend` (ams, 1 GB, volume `brain_buddy_data` → `/app/data`, `/health`, no release command); frontend nginx proxies `/api` to `BACKEND_ORIGIN`; no PostgreSQL anywhere | `fly.backend.toml`, `deploy/nginx/default.conf`, `compose.yaml` |
| Gates | coverage floor line 0.987 / branch 0.959; mutmut 95% on 6 enforced Python modules (gate-integrity invariant); import-linter 6 contracts; ruff complexity ceilings (mccabe 23, args 16, branches 20, statements 92, returns 8); Allure taxonomy only for pytest/Vitest/Playwright — Rust tests emit no Allure | `Makefile:23-36`, `backend/coverage-floor.json`, `scripts/mutation_gate.py`, `scripts/check_gate_integrity.py:282-293` |
| Client identity | `X-Client` only from iOS/macOS (`brainbuddy-ios|macos/<v>`); web, CLI (`User-Agent: BrainBuddyCLI/<v>`), MCP send none; logged only | `backend/app/api/middleware.py:24-40` |
| Apple legacy | ~215 `isRustSelected` sites in 19 files; legacy `BrainBuddyCore` reducer/outbox/replay, `BrainBuddySync` engine (~4k), `BrainBuddyPersistence` document store, 026 importers (`RustStoreImporter`, `RustOutboxImporter`, macOS `LegacyStoreImporter` etc.) | `ios/BrainBuddyKit/Sources/`, `macos/Sources/` |

The full externally reachable surface is enumerated in
[contracts/capability-inventory.md](contracts/capability-inventory.md).

## R1. HTTP framework

- **Decision**: `axum` on `tokio` + `tower`/`tower-http` (tracing, timeouts,
  request IDs, compression), `hyper` underneath.
- **Rationale**: the de-facto Tokio-ecosystem server; extractor model maps
  directly onto FastAPI's `Depends()` (state + typed extractors), so the
  "services via dependency injection, never constructed in handlers" rule
  survives as `State<AppServices>`; first-class SSE (sync hints) and
  streaming bodies (snapshot transfer, export ZIP).
- **Alternatives**: actix-web (own runtime/actor model, weaker tower
  middleware story); poem/salvo (smaller ecosystems); keeping FastAPI
  (rejected by the owner's objective).

## R2. Store and data access

- **Decision**: PostgreSQL (spec 026's target store) for **every** module from
  day one, one database with a schema per module (`identity`, `tasks`, `sync`,
  `jobs`, `crt`, `voice`, `agents`, `flags`, `control`); access via `sqlx`
  (async, compile-time-checked queries with committed offline metadata
  `.sqlx/`, `sqlx::migrate!` versioned migrations). CRT trees move from JSON
  files to rows (`jsonb` for the node payload where the shape is free-form).
  Two things deliberately stay outside PostgreSQL: voice audio bytes and the
  restore control ledger (R11). Login rate limits stay in process memory, as
  today (inventory ambiguity #11).
- **Rationale**: no data migration is needed (spec FR-019), so there is no
  reason to keep seven SQLite files and a JSON file store; one transactional
  store makes 026's "aggregate + receipts + feed + jobs in one unit of work"
  natural, gives `SELECT … FOR UPDATE SKIP LOCKED` for leases and
  `LISTEN/NOTIFY` for cross-instance sync hints. Schema-per-module keeps
  ADR-0001 ownership visible (a module's queries touch only its schema;
  checked by test, see R7).
- **Alternatives**: SQLite via rusqlite (single-writer limits, no
  multi-instance; already rejected by 026 as the server target); diesel
  (sync API, heavier DSL); SeaORM (ORM indirection the codebase never had);
  `tokio-postgres` raw (no compile-time checking).
- **Hosting**: Fly Managed Postgres in `ams`. Provisioning is an
  infrastructure ASK action and is authorized separately.

## R3. Crate layout and layering

- **Decision**: new crates in the existing `rust/` workspace:
  - `bb-server` — binary: config, wiring (`container` equivalent), HTTP
    router, middleware, operator subcommands (`create-invite`, …).
  - `bb-api` — handlers and wire DTOs per surface (no SQL).
  - `bb-app` — application services per module (identity, account, tasks,
    review, sync, jobs, crt, voice, agents, mcp, admin, flags).
  - `bb-store` — PostgreSQL repositories + migrations.
  - `bb-providers` — outbound adapters (AI, STT, SMTP, Apple/Google identity,
    A2A egress) behind traits; fakes for tests.
  - existing `bb-domain`, `bb-protocol` reused unchanged as the rule/wire
    source of truth.
- **Rationale**: crate boundaries are compiler-enforced layering — the Rust
  equivalent of the 6 import-linter contracts (`bb-api` cannot depend on
  `bb-store`; `bb-domain` cannot depend on axum/sqlx). A small
  `scripts/check_crate_graph.py` over `cargo metadata` asserts the allowed
  edges in CI.
- **Module ownership** (ADR-0001), which crate layers alone do not enforce:
  `bb-store` exposes one public module per owning module (`identity`, `tasks`,
  `crt`, …), and `bb-app::<module>` may import only `bb_store::<module>`
  (the Tasks owner group — application modules `tasks`, `review`, `sync`,
  `jobs` — shares `bb_store::tasks`, see data-model);
  cross-module access goes through ports declared in `bb-app::ports`.
  `scripts/check_crate_graph.py` checks both the crate edges and these `use`
  paths, and a `bb-store` test asserts each module's queries touch only its
  own schema.
- **Alternatives**: one crate with modules (layering only by convention —
  loses what import-linter enforces today); a crate per module (too many
  crates for one maintainer; module ownership is instead enforced per schema).

## R4. Proving 1:1 behavior — conformance suite

The existing pytest suite cannot be pointed at another server (78% imports
internals; even HTTP tests use in-process `create_app()` and reach into
`app.state.container` at 288 sites).

- **Decision**: build a black-box **conformance suite** in Rust
  (`rust/crates/bb-conformance`, `reqwest` + `tokio`), parameterized by base
  URL, organized by capability-inventory id. It runs **first against the
  current Python server** (proving each test encodes today's behavior), then
  against the Rust server; a capability counts as ported only when its
  conformance tests pass on both. After cutover it runs against Rust only.
  Seeding and time control go through a **test control API** (contract:
  [contracts/test-control.md](contracts/test-control.md)) available only when
  the server runs with `BRAIN_BUDDY_ENV=test`: mint invite, set flag mode,
  seed admin, advance the server clock, run a named sweep, seed an aged
  Review task. It replaces every Python hook the E2E and rehearsal suites use
  today.
- **Rationale**: a differential oracle is the only way to make "1:1" (FR-001,
  SC-003) checkable; writing it in Rust keeps the end state single-language;
  the same suite also replaces the Python fixtures behind `bb-client`
  `e2e_backend.rs`, `cli/tests/task_journey.rs` and the Swift rehearsal.
- **Cost accepted**: the Python server gains the test control API. That is a
  test seam under `BRAIN_BUDDY_ENV=test`, not a product capability, so it is
  compatible with the FR-022 freeze.
- **Internal tests**: each Rust module gets its own unit/integration tests at
  the cheapest reliable level (Principle II), using `#[sqlx::test]`
  per-test databases. Existing JSON vectors (`backend/tests/fixtures/*`, 026
  `contracts/*.json`) move to `contracts/fixtures/` and stay the oracle for
  rule and wire parity once Python is gone.
- **Alternatives**: keep pytest as an external harness (keeps Python as the
  test language; still has to be rewritten to be black-box); port the pytest
  suite test-by-test (couples tests to the old internals; no oracle).

## R5. Quality gates in Rust

| Gate today | Rust equivalent | Decision |
| --- | --- | --- |
| pytest + coverage floor (`coverage-floor.json`) | `cargo llvm-cov` (line + region) via `scripts/validate_coverage_floor.py` reading lcov/cobertura | New floor file `rust/coverage-floor.json`; start at the first green measurement of each crate, ratchet only upward; target ≥ 95% line on `bb-app`/`bb-store` |
| mutmut 95% on enforced scope | `cargo mutants` → `scripts/mutation_gate.py` gains a cargo-mutants parser (`outcomes.json`) | Follows ADR-0016 promotion: the Rust critical-invariant modules (owner isolation, sessions/auth, provider-token verification, command receipts/idempotency, job fencing, purge, control ledger) run as an **observed** scope in the nightly job from Phase A; a module is promoted to enforced only after two consecutive successful scheduled runs ≥ 95% on an unchanged scope. The six Python modules leave the enforced scope only when the Rust scope has been promoted, through ADR-0032 and the guarded `--update` |
| import-linter | crate graph (R3) | `scripts/check_crate_graph.py` |
| ruff/mypy/black | `cargo fmt`, `clippy -D warnings` (already), plus `clippy.toml` ceilings: `cognitive-complexity-threshold`, `too-many-arguments-threshold = 16`, `too-many-lines-threshold` | mirror today's ratchet values |
| Allure taxonomy for pytest | Allure results from Rust tests | small dev-only crate `bb-allure` (writes `allure-results/*-result.json` with epic/feature/story/title/steps from a test macro); `scripts/validate_allure_taxonomy.py` unchanged |
| requirement coverage | already scans `rust/**/*.rs` (`scripts/check_requirement_coverage.py:84-117`) | tests carry `027_FR_NNN` in names |
| schemathesis vs OpenAPI | `utoipa`-generated OpenAPI + conformance suite | OpenAPI committed as `contracts/openapi.yaml`, diffed in CI |

Thresholds are never lowered for an existing scope; the enforced-scope change
is a governance change and is made through an ADR, not silently.

## R6. Identity and crypto

- Passwords: Argon2id (`argon2` crate) — same algorithm as today
  (`auth_service.py:18`). Hash parameters may differ; no hashes are carried
  over.
- Sessions: opaque random tokens, stored hashed; cookie attributes per
  FR-007.
- Sign in with Apple / Google / browser grant: JOSE verification with
  `jsonwebtoken` + cached JWKS (today `joserfc`), proven by the invariant set
  in R14; a new identity without an account gets `INVITE_REQUIRED` with an
  opaque, single-use, short-lived pending handoff
  ([contracts/invite-handoff.md](contracts/invite-handoff.md)) and nothing is created until a valid
  invite is submitted (spec FR-007); email code via SMTP
  (`lettre`); CLI device grant per ADR-0029.
- Secrets at rest (agent credentials): `aes-gcm`/`chacha20poly1305` sealed
  box with the existing key env vars, replacing `cryptography`.

## R7. Background work

- **Decision**: one binary, two roles (`bb-server serve`, `bb-server worker`),
  same as 026's "separate worker process from the same code". Jobs live in
  the `jobs` schema with leases and fencing tokens (026 PR-20/21 semantics);
  claim with `FOR UPDATE SKIP LOCKED`; generations stop job writes once an
  owner's deletion begins (FR-017).
- **Sync hints**: SSE via axum; fan-out across instances through
  `LISTEN/NOTIFY`.

## R8. Integrations

- **MCP**: official Rust SDK `rmcp` (streamable HTTP transport) with the
  session-token verifier; tool list exactly as the inventory.
- **A2A relay**: implement the spec 014 wire contract directly with
  `reqwest` + `serde` (no dependency on a Python SDK); egress allow-list and
  timeouts as today. The Compose `a2a-helloworld`/`hermes-a2a` fixtures stay
  the black-box peers.
- **AI and STT providers**: `reqwest` adapters with the same providers, model
  pins, cost caps and consent gate; mock providers for tests.
- **Audio inspection**: today PyAV/FFmpeg (`voice_brain_dump/audio_media.py`)
  only verifies container identity and derives duration. Rust: `symphonia`
  (pure Rust) for wav/ogg/mp4/aac/webm probing and duration. **Risk**: WebM
  with Opus — symphonia can probe the Matroska container but duration may
  need the container's own metadata; validate in the voice slice against the
  synthetic generated fixtures (research R15: tones/silence encoded to
  WebM/Opus, Ogg/Opus, MP4/AAC and WAV); fall back to a minimal Matroska/EBML duration reader
  before considering an FFmpeg binding.

## R9. Detecting older clients (design decision 3)

- **Decision**: a dedicated integer header `X-Client-Epoch` compiled into
  every first-party client; a gated/exempt route split so provider callbacks,
  Apple notifications, health, docs and A2A peers keep working; MCP versioned
  by path (`/api/mcp/v2/`, old path refuses). Full rule:
  [contracts/release-epoch.md](contracts/release-epoch.md).
- **Why not the version string**: every client reports `0.1.0` today and iOS
  CI bumps only `CURRENT_PROJECT_VERSION`, so a version comparison cannot tell
  a pre-cutover build from the new one (campaign 1 finding).
- **Alternatives**: user-agent sniffing (fragile); no detection (FR-018
  unenforceable for web/CLI/MCP).

## R10. Cutover and rollback

Writer authority moves in one direction at a time; the two apps are never
both writable (FR-019).

Cutover (driven by the ASK-classified state file `deploy/production-backend.toml`, executed by the default-branch release workflow `deploy-fly-production.yml` for the exact landed `main` SHA in the `production` environment — no manual dispatch, per AGENTS.md; plan Phase F.2):

1. Trigger: an ASK commit sets `target = "rust"` in `deploy/production-backend.toml`; the release workflow run for that exact landed SHA performs the steps below. From then on the workflow deploys only the app the file names.
2. **Stop Python**: scale `brain-buddy-backend` to 0 machines; verify via
   `fly machines list` that none is running; `/health` on its app URL fails.
3. Deploy `brain-buddy-api` (release command `bb-server migrate` on the empty
   Managed Postgres), scale serve + worker to 1 each.
4. Deploy the frontend with `BACKEND_ORIGIN` → `brain-buddy-api`.
5. Production smoke (primary loop, epoch-gated) with a freshly minted invite.
6. On smoke failure — **automatic rollback in the same run** (as the release
   workflow already rolls back on failed smoke): scale `brain-buddy-api` to 0
   (verify), frontend `BACKEND_ORIGIN` back, scale `brain-buddy-backend` to 1;
   the old volume returns the pre-cutover state; the run fails. A follow-up
   commit sets `target = "python"` again so the file matches production. A
   later deliberate rollback (smoke passed, problem found before the erase)
   is an ASK commit setting `target = "python"`, executed with the same
   stop-first order.
7. On smoke success — **erase** (owner authorizes at that moment): destroy
   the `brain_buddy_data` volume, every snapshot of it, any volume forked or
   copied from it, the `brain-buddy-backend` app, and any off-platform copy
   made with `flyctl ssh sftp` per `docs/fly-deployment.md` (the operator
   lists them; none is expected); record each destroyed identifier and a
   final listing showing none remain. From here
   recovery is fix-forward.

The rehearsal (quickstart V8) runs the same steps on a staging Fly org and
records, for each step, the timestamps proving no overlap of writable
machines. The owner's account is recreated after cutover with
`bb-server create-invite`.

## R11. Store-side objects: audio and the control ledger

### Audio

Up to 100 MB per voice operation (`BRAIN_BUDDY_VOICE_AUDIO_MAX_TOTAL_BYTES`)
is too large for Postgres rows and must be reachable from both serve and
worker machines. **Decision**: S3-compatible object storage (Fly Tigris;
MinIO in Compose) via the `object_store` crate, bucket `voice`, keys
`<owner_id>/<operation_id>/<chunk_seq>`; the `voice` schema holds metadata and
keys. A startup check refuses to run without the bucket.

Crash/retry contract across the non-transactional boundary:

- **Upload**: put object → commit metadata row referencing it. Put is
  idempotent per key; a crash before commit leaves an orphan object, which a
  sweep deletes when no row references it and it is older than 24 h.
- **Read**: a row whose object is missing is a hard, visible operation
  failure (`AUDIO_UNAVAILABLE` with correlation ID), never silently skipped.
- **Delete (retention or purge)**: mark rows `deleting` → delete every object
  (idempotent, retried) → delete rows. The purge job resumes from `deleting`
  rows; purge is not reported done while any `deleting` row or orphan object
  for the owner remains.
- Evidence: an integration test with two server processes (upload through
  one, transcribe through the worker), a restart between, and retention/purge
  asserting both objects and rows are gone (Phase E voice slice).

### Control ledger and restore

A point-in-time restore (PITR) of the single PostgreSQL database rewinds
**every** module — Identity, flags, Tasks/sync/jobs, CRT, voice, agents —
not only tasks as today. The ledger therefore lives outside the database
(bucket `control`) and covers every decision a rewind must not undo:

- account deletion requested/cancelled, purge started/completed;
- session revocations and sign-outs; password, email and external-identity
  changes (recorded as a credential-epoch bump, not the secret itself);
  invite consumption; agent credential rotation/revocation;
- feature-flag mode changes (so a rewind cannot re-enable a disabled path).

Completeness protocol (ported from `tasks/sync/control_ledger.py` +
`restore.py`, adapted to an object store):

1. **Gapless sequence**: the ledger head is one object `control/HEAD`
   holding the last sequence number. A writer (serve or worker) reads it with
   its ETag, writes the entry `control/<seq+1>` with conditional create
   (`If-None-Match: *`), then advances `HEAD` with `If-Match: <etag>`; on a
   precondition failure it re-reads and retries. Sequence numbers are
   therefore gapless and totally ordered across processes. A crash after the
   entry write but before `HEAD` advances is repaired by the next writer or by
   boot reconciliation (it finds `control/<HEAD+1>` and advances `HEAD`).
2. **Write-ahead, applied set**: a decision is written to the ledger first,
   then applied in the database; the database records each applied sequence
   number in `control_applied` in the same transaction as the effect. If the
   apply fails, the request fails visibly and a background reconciler (every
   10 s, and at boot) applies every ledger entry missing from
   `control_applied`; session-revocation and deletion entries are also
   checked on the request path (a session whose revocation entry is not yet
   applied is rejected), so a pending apply never leaves a revoked session
   usable. There
   is no single high-water, so concurrent writers applying out of order cannot
   skip an entry.
3. **Boot reconciliation and gap detection**: on every boot, before accepting
   traffic, list `control/1..HEAD` within the retention window; any missing
   sequence number below `HEAD` is a **gap** and keeps the server closed
   (fail closed, operator alert); every listed entry not in `control_applied`
   is applied idempotently. Retention pruning (step 5) deletes entries
   strictly from the oldest end and records the pruned floor in
   `control/FLOOR`, so a gap is distinguishable from pruning.
4. **Restore**: close access (maintenance mode: all routes 503 except
   `/health`) → restore → step 3 replays every decision missing from the
   restored `control_applied` → credential epochs bumped by replay invalidate
   restored sessions and force re-authentication → sync and job generations
   advance so clients re-snapshot and stale leases fence out → per-module
   reconciliation (below) → reopen. If the ledger listing fails or a key is
   unreadable, the server stays closed.
5. **Retention**: entries older than the oldest live restore point are
   pruned from the oldest end, except purge entries, which are pruned only
   after the owner's deletion is reported complete; at that point no
   owner-linked data remains anywhere, so nothing content-bearing is kept.

Per-module reconciliation after a restore (data written after the restore
point is lost by design; these rules keep the survivors consistent):

- **CRT** (ADR-0026): command receipts after the restore point are gone, so a
  client retry with the same idempotency key re-executes against the restored
  tree; the CRT revision counter advances by a restore generation so stale
  `base_revision` writes get the existing revision conflict.
- **A2A / agents**: exchanges whose last state is "sent" or "in flight" at the
  restore point are marked `uncertain_after_restore`; the observer does not
  resend them automatically and surfaces them to the owner as the existing
  "needs attention" state; agent credentials follow the ledger replay.
- **Voice**: rows rewound while objects remain → the orphan sweep deletes the
  objects; rows that reference objects deleted after the restore point →
  marked failed with `AUDIO_UNAVAILABLE` (visible, retry = re-record).
- **Identity, flags, invites**: covered by the ledger replay above.

Managed Postgres PITR retention is configured to 7 days. Account deletion is
reported complete only when the last restore point holding the owner has
expired (spec FR-009).

## R12. Migrations and automatic rollback

The production deploy workflow rolls back to the previous image when
reachability or smoke fails. Rule: every migration after cutover is
**expand/contract** — a release may only add (tables, nullable columns,
indexes) or remove what the previous release already stopped using. CI job
`migration-compat` applies the head migrations, then runs the previous
release image's conformance smoke against that schema; failure blocks the
release. The first release (empty database) is exempt.

## R13. Secrets and evidence hygiene

- `DATABASE_URL`, object-store credentials and the control-ledger bucket
  credentials are Fly secrets, never in `fly.*.toml`, Compose defaults or
  logs (the tracing layer redacts URLs with credentials). Missing or invalid
  values: `bb-server serve|worker|migrate` exit non-zero at startup with a
  named, value-free error; `/health` is never green without a database
  connection.
- Evidence committed under `specs/027-rust-server/evidence/` uses synthetic
  owners only; it may contain correlation IDs, timings, counts, SHAs and
  screenshots of synthetic data, and never emails, invite codes, session or
  provider credentials, task/tree text, local paths or content hashes. A
  `scripts/check_evidence_hygiene.py` pattern check runs in check-specs for
  this feature's evidence directory.

## R14. Provider-token verification invariants

Mock identity providers in conformance cannot catch a verifier that accepts a
bad token. A dedicated Rust test set (test-first, Principle II critical
invariant) with locally signed JWS fixtures proves the verifier rejects: wrong
issuer, wrong audience/client id, missing or mismatched nonce, `alg: none`
and algorithms outside the allow-list, bad signature, unknown `kid`, expired
or not-yet-valid tokens, a replayed browser/device-grant handoff, and a
handoff used by a different session; and accepts only the exact valid case.
It also covers JWKS rotation and fetch failure (fail closed). These rows are
in the mutation observed scope.

## R15. Fixture hygiene

The JSON/WAV fixtures moved from `backend/tests/fixtures/` to
`contracts/fixtures/` are audited before the move: transcript-like text is
replaced with clearly synthetic text, raw WAV fixtures are replaced with
generated tones/silence, and audio/title/corpus hashes that could act as
content fingerprints are removed or replaced by values computed from the
synthetic content at test time. `scripts/check_evidence_hygiene.py` scans both
`contracts/fixtures/` and `specs/027-rust-server/evidence/`.

## R16. Removal

- After the Rust server passes the conformance suite and E2E: delete
  `backend/`, `rust/bindings/python`, `backend/bb_core.pyi`, maturin wiring,
  Python CI lanes, `rust_core_sync` flag (always effective), the Python parity
  tests (vectors stay), `ios/scripts/rehearsal_backend.py`,
  `scripts/rehearsal/rehearsal_backend.py`/`ui_backend.py` Python fixtures
  (replaced by the test control API).
- Apple: delete the legacy runtime and importers, collapse `Workspace` to the
  Rust path, add the first-launch reset (FR-021).
- Docs/governance: ADR-0032 (server in Rust, supersedes ADR-0031's "FastAPI
  stays" and 026's separate PostgreSQL stage); constitution Operational
  Guardrail on `backend/data` + LRU cache (PATCH amendment); `CLAUDE.md` /
  `AGENTS.md` architecture sections; `docs/auth.md`, `docs/data-retention.md`,
  Fly docs.
