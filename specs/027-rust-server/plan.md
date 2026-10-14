# Implementation Plan: Rust server

**Branch**: `027-rust-server` | **Date**: 2026-10-14 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/027-rust-server/spec.md`; agreed
requirements in [intake.md](intake.md); approved design in [design.md](design.md).

## Summary

Replace the Python/FastAPI server with a Rust server built on the existing
`bb-domain`/`bb-protocol` crates, with PostgreSQL as the only store, then
remove the Python server, the PyO3 bridge and the Apple apps' legacy runtime,
and switch production once (spec Clarifications, 2026-10-14).

Behavior is held to 1:1 by a **differential conformance suite**: a black-box
Rust test suite keyed to the [capability inventory](contracts/capability-inventory.md),
run first against the current Python server (which proves each test encodes
today's behavior) and then against the Rust server. Black-box suites seed and
control time only through a [test control API](contracts/test-control.md),
which also removes every Python hook from the E2E and rehearsal suites. The
Python server is frozen to bug fixes (FR-022), so the inventory is a fixed
target.

## Technical Context

**Language/Version**: Rust 1.99.0 (pinned in `rust/rust-toolchain.toml`), edition 2024, `unsafe_code = forbid`. Swift (iOS 26 / macOS 26) and TypeScript unchanged as languages.

**Primary Dependencies**: axum + tokio + tower-http; sqlx (PostgreSQL, offline query metadata); serde (existing exact pins); reqwest (rustls) for outbound providers and A2A; rmcp (MCP streamable HTTP); argon2, jsonwebtoken, lettre, aes-gcm; symphonia for audio probing; utoipa for OpenAPI; tracing. Exact versions are pinned in the first slice that introduces each and recorded in `rust/Cargo.lock` (research R1–R8).

**Storage**: PostgreSQL (Fly Managed Postgres, `ams`), one database, one schema per owning module ([data-model.md](data-model.md)); S3-compatible object storage (Fly Tigris; MinIO locally) for voice audio and the restore control ledger (research R11). Device: bb-client SQLite only.

**Testing**: cargo test (+ `#[sqlx::test]` per-test databases), conformance suite `bb-conformance` against a base URL, Playwright E2E on the Compose stack, XCTest/Swift package tests for the Apple apps, cargo-llvm-cov coverage floor, cargo-mutants on the enforced scope, Allure results from Rust tests via `bb-allure` (research R5).

**Target Platform**: Linux container on Fly.io (server and worker roles from one binary); iOS 26, macOS 26; web unchanged.

**Project Type**: web service (modular monolith) + native apps + web frontend.

**Performance Goals**: primary-loop web flows p95 ≤ 110% of today's server (SC-005); 026 SC-003/SC-004 on reference devices (SC-004); ~200-node canvas as responsive as today.

**Constraints**: no Python in the server image (SC-001); no data migration; single cutover; old builds refused with 426 (FR-018); privacy and retention unchanged (FR-009/010).

**Scale/Scope**: ~59k lines of Python server and its surface (see inventory) ported; ~215 legacy selection sites and the legacy runtime removed from the Apple apps; invite-only, no real users.

## Constitution Check

*Pre-research: pass with one tracked governance change (see Complexity Tracking). Re-checked after Phase 1: pass.*

- **Spec workflow**: spec.md is current; three clarification outcomes (single cutover, Python freeze, pilot after cutover) and the device-data answer are reflected in spec FR-019, FR-021, FR-022 and SC-004. Intake confirmed by the owner.
- **Consent & Safety (I)**: AI consent gate, provider credentials and cost caps are ported (FR-011/012); the gate is enforced server-side on every provider path, including CRT node validation (a `change` disposition proven on the Rust server; the frozen Python server keeps today's behavior). Conformance asserts refusal with zero calls in the provider call ledger, and late results after revocation are discarded (provider hold/release seam). The fresh-start deletion is visible and confirmed (FR-021, design M-02/D-03 .01). Evidence hygiene: research R13. Database and object-store secrets: research R13. No real data: conformance and E2E use synthetic owners via the test control API; the test control API does not exist in production builds (`cfg(feature = "test-control")`, CI check). Logs keep IDs only; a log-redaction test runs over the server's structured log output in conformance runs.
- **Tests (II)**: reused checks — the 19 Playwright specs, 026 JSON vectors (`backend/tests/fixtures/*`, `specs/026-rust-core-sync/contracts/*.json`), `bb-domain` parity and property tests, `bb-client` protocol fault tests, Swift package tests, CLI journey. Necessary additions — the conformance suite (the only way to prove FR-001 1:1 on a new implementation); module-level Rust tests at the cheapest reliable level; test-first for the predefined critical invariants that are new code here: owner isolation, session/cookie properties, idempotent command receipts, job fencing, consent refusal, purge completeness, 426 no-write. The pytest suite is not ported test-by-test (research R4).
- **Contracts (III)**: wire contracts are unchanged by default — sync v1 (frozen in 026), web DTOs, MCP tools, A2A spec 014. The additions are listed contracts: the client epoch (`X-Client-Epoch`, `X-Client` for web/CLI), `GET /api/meta`, `X-Server-Epoch`, the 426 refusal and the MCP path `/api/mcp/v2/` ([contracts/release-epoch.md](contracts/release-epoch.md)); the `INVITE_REQUIRED` handoff ([contracts/invite-handoff.md](contracts/invite-handoff.md)); and the test-only control API ([contracts/test-control.md](contracts/test-control.md)). OpenAPI is generated from the Rust server and committed as `contracts/openapi.yaml`; CI diffs it against the conformance expectations. All clients change in the same release (FR-005).
- **Observability (IV)**: `X-Correlation-ID` middleware on every response including 426 and 404; tracing spans keyed by correlation ID; error envelope identical to today's; no user content in logs.
- **Mobile/resilience/performance (V)**: sync semantics are 026's and unchanged; the Apple apps lose only the legacy path; first-launch reset is resumable (design M-02.06). Canvas responsiveness: conformance includes a 200-node tree latency check; SC-005 bench compares both servers.
- **Delivery boundary**: tasks.md will be portable planning input; isolated worktrees, Principle II, independent review, ADR-0008 landing, CI and Fly release gates remain authoritative. Cutover, Postgres provisioning, CI changes, gate changes and the volume erase are ASK-class and authorized separately.
- **Design citation**: [design.md](design.md). Phase B realizes **D-04, M-03** (invite step for new provider/email identities; D-05 is reserved and not applicable because the Mac app offers only password sign-in, which never creates an account). Phase E realizes the CRT consent refusal at the API only (no shipped UI calls the route since #236). Phase D realizes **M-01, D-01, D-02** (update required) and **M-02, D-03** (fresh start: confirmation .01 before deletion, failure .05 "Try again"; the only new copy). All other requirements have no user-visible surface (design.md "Requirements with no affordance").

## Architecture

```mermaid
flowchart TB
  Web[Web app (TS)] -->|/api same-origin via nginx| API
  IOS[iPhone/Mac apps<br/>shared runtime only] -->|sync v1, REST| API
  CLI[bb CLI] --> API
  MCPc[MCP clients] --> MCP
  subgraph bb-server binary
    API[bb-api: axum routers<br/>middleware: correlation ID, X-Client epoch, auth]
    MCP[MCP endpoint (rmcp)]
    APP[bb-app: services per module]
    DOM[bb-domain + bb-protocol<br/>existing crates]
    STORE[bb-store: sqlx repositories]
    PROV[bb-providers: AI, STT, SMTP,<br/>Apple/Google, A2A egress]
    WORK[worker role: job ledger,<br/>sweeps, agent observer]
  end
  API --> APP
  MCP --> APP
  APP --> DOM
  APP --> STORE
  APP --> PROV
  WORK --> APP
  STORE --> PG[(PostgreSQL<br/>schema per module)]
  PG -. LISTEN/NOTIFY .-> API
```

Layering is compiler-enforced by crate dependencies and asserted by
`scripts/check_crate_graph.py` (replaces import-linter, research R3):
`bb-api → bb-app → {bb-store, bb-providers, bb-domain, bb-protocol}`;
`bb-domain` and `bb-protocol` depend on no I/O crate; `bb-api` never depends
on `bb-store`. Handlers receive services through axum `State` — the Rust form
of "routes receive services via `Depends()`; never instantiate services in
handlers".

## Delivery phases

Phases are dependency groups, not barriers; slices inside a phase run in
parallel once their prerequisites merge. `/speckit-tasks` turns this into the
slice map with budgets.

### Phase A — Foundation and oracle (blocks everything)

1. **ADR-0032** "Server in Rust": supersedes ADR-0031's "FastAPI stays" and
   026's separate PostgreSQL stage; records the conformance-oracle approach,
   the gate equivalents (research R5) and the FR-022 freeze. Constitution
   PATCH for the `backend/data` guardrail. 026 marked superseded
   (`specs/026-rust-core-sync/README.md`), PR #377 closed.
2. **Capability inventory** frozen ([contracts/capability-inventory.md](contracts/capability-inventory.md))
   plus a machine-readable disposition file `contracts/capability-dispositions.json`
   (one entry per inventory id: `port` | `change` | `remove`, evidence kind —
   `conformance`, `integration`, `config-test`, `job-test`, `deploy-check` —
   and evidence id). `scripts/check_capability_inventory.py` fails on a missing
   row, a missing evidence id, or a `change`/`remove` without the spec FR-001
   approval reference. Configuration, store, external-integration and job rows
   use the non-HTTP evidence kinds; only HTTP/MCP/middleware rows need a
   conformance test.
3. **Test control API in the Python server** (test env only; allowed by
   FR-022) and switch Playwright helpers, rehearsal scripts, `bb-client`
   backend tests and the CLI journey to it — removes every
   `python -m app.cli`/`python -c` hook.
4. **`bb-conformance` crate** + `bb-allure` + `make conformance`; first
   conformance tests green against Python.
5. **Server skeleton**: `bb-server` (config from `.env.example` names,
   `/health` + `/api/health`, correlation-ID middleware, error envelope,
   release-epoch gate with the exempt set from
   [contracts/release-epoch.md](contracts/release-epoch.md), test control
   feature, startup refusal without `DATABASE_URL`/object store), `bb-store`
   with migrations, Compose `postgres` and `minio` services, `bb-providers`
   traits + mocks with the call ledger and hold/release seam.
6. **CI lanes** (ASK: CI change): Postgres + MinIO services; conformance vs
   Python and vs Rust; llvm-cov floor; cargo-mutants report; crate-graph and
   module-boundary check; clippy ceilings; Allure upload of Rust results into
   `allure-report`; `migration-compat` (research R12, active after cutover);
   cargo-mutants on the Rust critical-invariant modules as an **observed**
   nightly scope from the start, so promotion under ADR-0016 (two consecutive
   scheduled runs ≥ 95%) can happen before the Python scope is retired.
7. **Fixture audit and move** (research R15): synthetic replacements, hashes
   removed, `contracts/fixtures/`, `scripts/check_evidence_hygiene.py`.

### Phase B — Identity and operator (parallel after A)

Sign-up/sign-in/sessions/invites/rate limits; modern auth (email code, Apple,
Google, browser grant) with **invite required for every account creation**
(spec FR-007 `change` disposition — proven on Rust only; the Python oracle
keeps today's behavior); CLI device grant (ADR-0029); account (profile, email,
password, export ZIP, 14-day deletion, purge port); feature flags; admin
portal API and operator subcommands (`create-invite`, `reconcile`). Each slice
lands with its dispositions met (conformance green on both servers for
`port` rows; Rust-only for `change` rows such as invite gating). Provider-token
verification lands test-first with the invariant set in research R14. The
`INVITE_REQUIRED` handoff for new provider/email identities realizes design
D-04 and M-03.

Account export and purge are built as a **port with per-module
contributors**: Phase B delivers the orchestration (grace period, job,
completion rule including restore-point expiry and object-store cleanup) and
the Identity/flags contributors; each later module slice (C, E) registers its
own export and purge contributor with its tests; end-to-end export/purge
acceptance (spec User Story 4) runs in Phase F.1 once every contributor
exists.

### Phase C — Tasks, Review, sync and jobs (after B's session layer)

Task/project/Tag/children/archive routes and Smart Add on `bb-domain`
directly; Review flow, navigator, formulation; sync v1 (commands, receipts,
feed, delta, snapshots/transfers, SSE hints over LISTEN/NOTIFY); control
ledger in the object store and the restore protocol (research R11); job
ledger, fencing, scheduler; retention sweeps; the SC-007 reconciliation
(`bb-server reconcile`, also exposed through test control). 026's invariants
are the acceptance bar (spec FR-006/017).

### Phase D — Clients (parallel with C once A.5 lands)

- Web: send `X-Client-Epoch` and `X-Client: brainbuddy-web/<build>`; handle
  426 in a new persistent alert variant of the shell toast with Reload
  (**D-02**); the invite step for new provider/email identities (**D-04**).
- CLI: send `X-Client-Epoch` and `X-Client: brainbuddy-cli/<v>`; map 426 →
  exit 12 with design wording; MCP docs point to `/api/mcp/v2/`.
- iPhone: the invite step for new provider/email identities (**M-03**).
- iPhone/Mac: send `X-Client-Epoch`; remove the legacy runtime,
  `BrainBuddySync` legacy engine, `BrainBuddyPersistence` document store, 026
  importers and the pilot switch; collapse `Workspace` to the Rust path;
  confirmation-then-reset (**M-02, D-03** .01–.08) that activates **only when
  the server reports the new epoch**, so a TestFlight build landing before
  cutover deletes nothing; 426 handling in the existing sync row/alert
  (**M-01, D-01**), including the new M-01.01 body copy in
  `RuntimeIssuePresentation.swift`. XCTest covers each deleted artifact, the confirm/decline
  paths, interruption after confirmation, and "no network until done".
- Swift rehearsal and UI tests retargeted to the test control API.

### Phase E — CRT, voice, agents, MCP

- CRT (after B): trees/nodes/relations/versions/import-export, AI validation
  with a **server-side consent check** (`change` disposition, Rust-only
  evidence; spec FR-011), CRT command receipts and exposure (ADR-0026).
- Voice (after C's job ledger): operations, audio in the object store with
  the crash/retry contract and the two-process durability test (research
  R11), audio
  probing (symphonia; WebM/Opus risk in research R8), STT providers and cost
  caps, capture items through the task core.
- Agents and MCP (after C's task core and job ledger): agents, A2A relay
  (spec 014), egress, sealed secrets, observer; MCP server (rmcp) at
  `/api/mcp/v2/` with the old path refusing.
- All AI/STT paths re-check consent and owner generation after the provider
  returns and discard late results (spec FR-011); tested with the provider
  hold/release seam.

### Phase F — Switch and removal

1. Full Playwright E2E on the Rust Compose stack; conformance 100% on Rust;
   dispositions complete; SC-005 bench.
2. Fly: new app `brain-buddy-api` (`fly.api.toml`, `release_command =
   "bb-server migrate"`, serve + worker process groups), Managed Postgres and
   Tigris buckets (ASK). Cutover runs **inside the default-branch release
   authority, with no manual trigger**: a committed state file
   `deploy/production-backend.toml` (`target = "python" | "rust"`,
   `erase_old = false | true`) is classified ASK by
   `scripts/classify_path_risk.py`; the release workflow
   `.github/workflows/deploy-fly-production.yml`, running as today for the
   exact landed `main` SHA in the `production` environment and concurrency
   group, reads the file and executes research R10's steps when the target
   changes. Cutover, rollback and erase are each one ASK commit to that file,
   landed with the owner's recorded approval for that exact SHA (the erase
   commit is the owner's authorization at that moment). A failed smoke rolls
   back automatically inside the same run, stop-first (research R10 step 6). Per-step evidence is
   uploaded. Production smoke checks send the client epoch. The staging
   rehearsal uses a separate `.github/workflows/cutover-rehearsal.yml` bound
   to a `staging` environment and Fly org, never to `production`.
3. Cutover rehearsal on staging (quickstart V8), then production cutover
   (ASK, FR-019): stop Python → start Rust → switch origin → smoke → rollback
   or (owner authorizes) erase immediately: the `brain_buddy_data` volume,
   **every snapshot of it** (`fly volumes snapshots list`), any volume forked
   or copied from it, and the `brain-buddy-backend` app; the evidence lists
   each identifier destroyed and a final listing showing none remain.
4. After the erase: remove the Python server and bridge (research R16),
   Python CI lanes, the six-module Python enforced mutation scope (replaced
   under ADR-0032 via the guarded `--update` path), maturin,
   `rust/bindings/python`; delete the inactive old-path code paths kept only
   for rollback.
5. Production pilot on reference devices, including destructive Q03/Q08/Q10
   with per-step authorization (SC-004), and the seven-day reconciliation
   watch (SC-007). Evidence binds to artifacts: server SHA and image digest,
   iPhone/Mac build numbers, daily `fly status` for both app names (only
   `brain-buddy-api` exists), and for each destructive step an authorization
   receipt (step id, authorizer role, timestamp, target app and SHA, outcome,
   correlation IDs).

Client outcome evidence (Phase D, not only server middleware): Vitest for the
D-02 persistent toast and Reload; CLI tests for exit 12 and the wording;
XCTest for M-01/D-01 (refusal shown only on 426, cleared on update or later
success) and M-02/D-03 (.00 against an old server, .01 confirm/decline/.11,
.06 resume, .05 failure, no network until done), plus D-04 (Vitest) and M-03
(XCTest) invite step tests.

## Inventory quirks policy

The inventory ([contracts/capability-inventory.md](contracts/capability-inventory.md):
153 HTTP, 7 MCP, 26 job, 8 CLI, 21 middleware, 13 external, 92 config,
17 store rows) lists 17 ambiguities. Rule: the Rust server reproduces observed
behavior unless it is a defect. A defect is fixed on the Python server first
(allowed by FR-022) with a conformance test, so both servers agree before the
port. Decisions for the listed items:

- Port as observed: `DELETE /api/tags/{id}` 200-with-body (#14), 400 vs 422
  split (#15), both `/health` and `/api/health` (#17), deterministic
  `/trees/{id}/ai-feedback` (#13), OpenAPI/docs exposure (#5, now generated by
  utoipa), `cli_auth` as an optional managed flag (#10).
- Owner-approved `change` (Rust-only evidence): CRT node validation's
  server-side consent check (spec FR-011).
- Fix on Python first as defects: account privacy headers missing on
  `GET /api/account` (#1); sync flag check ordering (#3) becomes moot once
  `rust_core_sync` is always effective, so the conformance test asserts the
  always-on behavior on the Rust server only; durable vs legacy privacy-step
  mismatch (#9) — the Rust worker runs the full step set, including the
  control-ledger prune.
- Not ported: legacy JSON import at startup (#8; no data migration),
  unused `BRAIN_BUDDY_API_KEY_HEADER` (#6), the `bb_core` in-process bridge
  (#12; the Rust server links `bb-domain` directly).
- Clarified in config: `BRAIN_BUDDY_AGENT_RELAY_KEYS` and
  `BRAIN_BUDDY_ACCOUNT_PURGE_GRACE_SECONDS` are added to `.env.example` (#7).
- Kept per process: in-memory rate limits (#11) — production runs one machine;
  moving them to PostgreSQL is out of scope (no new behavior).
- MCP edge cases (#4) and CRT correlation-ID strictness (#2) are pinned by
  conformance tests against the Python server's observed responses.
- Shutdown (#16): one ordered graceful shutdown in `bb-server` (stop accepting,
  drain requests, stop worker leases, close MCP sessions, flush logs).

## Project Structure

### Documentation (this feature)

```text
specs/027-rust-server/
├── intake.md  spec.md  design.md  design/  checklists/requirements.md
├── plan.md  research.md  data-model.md  quickstart.md
├── contracts/
│   ├── capability-inventory.md   # FR-001 porting contract
│   ├── test-control.md           # test-only seeding/clock API
│   ├── release-epoch.md          # X-Client + 426
│   └── openapi.yaml              # generated from the Rust server (Phase A.5+)
├── evidence/                     # cutover rehearsal, cutover, apple-pilot
└── tasks.md                      # /speckit-tasks
```

### Source Code (repository root)

```text
rust/
├── Cargo.toml                    # workspace: add new members, drop bindings/python
├── crates/
│   ├── bb-domain/  bb-protocol/  bb-client/   # existing, reused
│   ├── bb-server/                # NEW binary: config, wiring, router, serve|worker|migrate|create-invite
│   ├── bb-api/                   # NEW handlers + DTOs per surface
│   ├── bb-app/                   # NEW services per module
│   ├── bb-store/                 # NEW sqlx repositories, migrations/
│   ├── bb-providers/             # NEW AI/STT/SMTP/identity/A2A adapters + mocks
│   ├── bb-conformance/           # NEW black-box suite (base URL)
│   └── bb-allure/                # NEW dev-only Allure writer for Rust tests
└── bindings/
    ├── swift/                    # kept
    └── python/                   # REMOVED in Phase F
backend/                          # frozen (FR-022), gains test control API (A.3), REMOVED in Phase F
cli/src/request.rs                # X-Client-Epoch, X-Client, 426 → exit 12
frontend/src/api/                 # X-Client header, 426 handling
frontend/tests/e2e/gtdHelpers.ts  # test control API instead of docker exec python
ios/BrainBuddyKit/Sources/        # legacy runtime removal, reset (BrainBuddyCore, BrainBuddySync, BrainBuddyPersistence, BrainBuddyWorkspace)
ios/BrainBuddy/                   # entry point, Settings pilot row removal
macos/Sources/                    # WorkspaceHost, legacy importers removal
contracts/fixtures/               # NEW home of shared JSON vectors (moved from backend/tests/fixtures)
scripts/                          # check_crate_graph.py, check_capability_inventory.py (new); mutation_gate.py (cargo-mutants parser); rehearsal/ retargeted
compose.yaml  fly.api.toml  deploy/nginx/default.conf
.github/workflows/ci.yml  deploy-fly-production.yml
docs/decisions/0032-server-in-rust.md
```

**Structure Decision**: the server joins the existing `rust/` workspace so the
toolchain, lints, exact pins and `check_requirement_coverage.py`'s Rust scan
apply unchanged; per-layer crates give compile-time layering. `backend/` stays
until Phase F only as the oracle for conformance. `cli/` stays a separate
crate as today.

## Risks

| Risk | Mitigation |
| --- | --- |
| The inventory misses a behavior | Inventory derived from code with file:line; conformance must pass on Python first; Playwright E2E as a second net; Python frozen (FR-022) |
| Conformance suite becomes a second huge codebase | One test per inventory row plus invariant tests; reuse JSON vectors; no porting of internal pytest |
| WebM/Opus duration probing in pure Rust | Validate early in the voice slice against generated synthetic WebM/Opus, Ogg, MP4/AAC and WAV fixtures (research R15); fallback EBML reader |
| A2A has no Rust SDK | Spec 014 wire contract is explicit; reference peers in Compose verify it |
| Gate regressions while switching languages | Gate equivalents land in Phase A before product slices; enforced scope moved only through ADR-0032 |
| Cutover failure | Rehearsed stop-first rollback, available until the erase; after it, fix-forward (owner decision) |

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
| --- | --- | --- |
| Changing a gate-integrity invariant (the six-module Python enforced mutation scope) | The Python modules it names are deleted | Keeping Python modules alive only to satisfy the invariant contradicts SC-001; the change is made through ADR-0032 and the guarded `--update`, never by lowering thresholds |
| Frozen Python server gains a test control API | Black-box oracle needs seeding/clock without container access | Porting pytest internals cannot prove 1:1 on a new implementation; the API is test-env only and absent from production builds |
| Two servers in CI until Phase F | Differential conformance | Testing only the Rust server leaves "1:1" unprovable |

## Planning review campaign 1 — resolutions (run `027-plan-20261014-1`)

Carried forward so campaign 2 judges the fixes rather than re-raising them.

| Finding (lens) | Resolution |
| --- | --- |
| Control ledger inside the database a restore rolls back (adversarial) | Ledger moved to append-only object storage; restore protocol and ≤ 7-day PITR horizon: research R11, data-model |
| Voice audio has no durable shared store (adversarial, architecture) | Object storage bucket `voice`, retention/purge delete objects: research R11, spec FR-012 |
| Epoch gate blocks callbacks, notifications, health, docs, smoke (adversarial, architecture, requirements) | Gated/exempt split, smoke sends epoch: contracts/release-epoch.md |
| Marketing version cannot identify builds (adversarial) | Integer `X-Client-Epoch`: contracts/release-epoch.md, research R9 |
| Cutover/rollback order allowed overlapping writers (adversarial, architecture, requirements, testability) | Stop-first both directions, dedicated workflow, overlap timestamps in the drill: spec FR-019, research R10, quickstart V8 |
| Forward-only migrations vs automatic image rollback (adversarial) | Expand/contract rule + `migration-compat` CI: research R12 |
| Late provider results after consent revocation (adversarial, testability) | Spec FR-011; provider hold/release + call ledger in contracts/test-control.md; Phase E |
| Module ownership not enforced by crate layers (architecture) | Per-module `bb-store` namespaces + `use`-path check: research R3 |
| Rate-limit state ownership contradiction (architecture) | In-memory only, removed from identity schema: data-model |
| Invite-only vs ADR-0028 (architecture, requirements) | **Owner decision**: invite required for every signup; `change` disposition; amends ADR-0028 in ADR-0032: spec FR-007 |
| Silent destructive reset (privacy, UX) | **Owner decision**: confirmation before deletion: spec FR-021, design M-02/D-03 .01/.11 |
| CRT validation without server-side consent (privacy) | Owner-approved `change`, Rust-only evidence (superseded campaign-1 "fix on Python first"): spec FR-011, quirks policy |
| Disconnected old volume outlives retention (privacy) | **Owner decision**: erased immediately after smoke: spec FR-019 |
| Stored flag audit undefined (privacy) | No stored audit; stdout only as today: data-model |
| PII/secrets in evidence; database credential handling (privacy) | research R13 + `check_evidence_hygiene.py` |
| Native reset could fire before cutover via TestFlight (requirements) | Reset activates only on the new server epoch: spec FR-021, design .00, data-model |
| No disposition model for removed capabilities (requirements, testability) | `capability-dispositions.json` + checker with evidence kinds: Phase A.2, spec FR-001/SC-003 |
| Test control API vs Python freeze (requirements) | FR-022 allows test-only seams |
| Refusal recovery rule mismatch (requirements) | Clears on update or later success: contract + design aligned |
| Quickstart Python check false-fails on tooling (requirements) | quickstart V3 scoped |
| Destructive pilot steps in production (testability) | **Owner decision**: all in production, per-step authorization: spec SC-004, quickstart V9 |
| Seven-day watch not decidable (testability) | Daily `bb-server reconcile` counters, failure rule: spec SC-007, quickstart V9 |
| Fresh-start failure coverage (testability) | quickstart V6 steps 1–4, Phase D XCTest list |
| Phase E lanes not independent (testability) | CRT after B; voice after C's jobs; agents/MCP after C: Phase E |
| D-02 spinner onset; native focus rules (UX) | design D-02.02 (300 ms), "Keyboard and focus" section |

## Planning review campaign 2 — resolutions (run `027-plan-20261014-2`)

| Finding (lens) | Resolution |
| --- | --- |
| No server-to-client epoch signal before auth (adversarial, architecture, requirements, testability) | `GET /api/meta` + `X-Server-Epoch`: contracts/release-epoch.md; data-model trigger |
| Reset inventory incomplete; all-or-nothing unachievable (adversarial) | Full legacy artifact inventory + committed list with coverage test; ordered idempotent steps with confirmed/done markers: data-model |
| Invite for every method has no surface (adversarial, UX) | `INVITE_REQUIRED` handoff (research R6) and design D-04/M-03 (D-05 not applicable) |
| Control-ledger completeness protocol missing; PITR rewinds every module (adversarial, architecture) | ULID write-ahead, applied high-water, boot reconciliation, closed-access restore over all modules, credential-epoch replay: research R11 |
| Provider-token verification invariants (adversarial) | Named invariant set, test-first, mutation observed scope: research R14 |
| MCP path change not an approved disposition (adversarial) | Added to FR-001/FR-005 approved changes |
| CLI exit 11 already used (architecture) | Exit 12; README and 024 contract rows: contracts/release-epoch.md |
| Cutover not bound to release authority (architecture) | ASK-classified state file executed by the default-branch release workflow for the exact SHA; no manual dispatch; staging rehearsal workflow separate: Phase F.2, research R10 |
| Old CLI cannot show actionable wording (architecture, requirements) | **Owner decision**: generic refusal accepted, nothing written: spec FR-018 |
| Module check vs Tasks unit of work (architecture) | Tasks owner group shares `bb_store::tasks`: data-model, research R3 |
| Object-store partial failure (architecture) | Upload/read/delete contract + orphan sweep: research R11 |
| Evidence model contradictions in V1 (architecture, requirements, testability) | quickstart V1 rewritten per disposition and evidence kind |
| Old volume snapshots/copies survive erase (privacy) | Erase covers volume, snapshots, forks, app; listing evidence: Phase F.3, research R10 |
| Purge vs restore horizon (privacy) | **Owner decision**: pending until last restore point expires: spec FR-009, data-model |
| CRT consent model (privacy, requirements) | **Owner decision**: explicit consent carried per request, server refuses; API-level rule, no UI (inspector removed in #236): spec FR-011, FR-005 |
| Fixtures with transcript-like text, WAV, hashes (privacy) | Audit and synthetic replacement before move: research R15, Phase A.7 |
| Cutover record disposition (privacy) | **Owner decision**: indefinite, non-personal, outside export/purge: data-model |
| "All ported" wording vs dispositions (requirements) | FR-019 and Phase B reworded to dispositions |
| FR-021 vs design skip rule (requirements) | FR-021 aligned: confirm only when tasks/changes/drafts exist |
| CRT 30-day receipt retention (requirements) | Per-module retention list: data-model |
| Lexical V3/V4 false positives (requirements, testability) | Scoped to server crates and code paths |
| Phase B export/purge before other stores exist (testability) | Port with per-module contributors; end-to-end acceptance in F.1 |
| Client outcome evidence (testability) | Vitest/CLI/XCTest list in Phase F |
| Object-store durability evidence (testability) | Two-process restart + purge integration test: research R11, Phase E |
| SC-005 bench not reproducible (testability) | Dataset, mix, warm-up, concurrency, limits, comparison: quickstart V7 |
| Mutation promotion rule (testability) | ADR-0016 observed → enforced after two runs ≥ 95%: research R5, Phase A.6 |
| Pilot/watch evidence binding (testability) | SHA/digest, build numbers, daily `fly status`, authorization receipts: Phase F.5, quickstart V9 |
| D-02 toast role and Reload; native focus (UX) | Persistent alert toast with Reload: design D-02 |
