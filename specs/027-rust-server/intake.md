# Business Intake: Rust server

**Feature**: `specs/027-rust-server/`
**Interviewed**: 2026-10-14
**Interviewee**: Max (product owner)

Stage 0 assessment skipped: the owner made the go decision explicitly in the
session after reviewing spec 026's status ("Давай сервер на раст").

## The ask, as given

> Давай сервер на раст. Похуй, потому что реальных пользователей пока нет

Context: earlier in the same session the owner said "Мне кажется, что бэк мы
отложили, а не полностью отказались переносить", i.e. the backend move to Rust
was deferred by spec 026 (`intake.md:21`, `plan.md:13`), not rejected.

## 1. Problem

- **Whose problem**: the owner/maintainer (the only developer).
- **How it shows up today**: task rules live in Rust (spec 026) but the server
  is Python/FastAPI calling Rust through PyO3, while legacy Python rule paths
  remain behind the `rust_core_sync` flag. Two languages and two
  implementations on the server side must be maintained.
- **Primary objective (owner's choice)**: one core language: remove the
  Python↔Rust bridge and the second implementation; simpler maintenance.
  Performance and type-safety are side benefits, not the goal.
- **If we build nothing**: the dual-language server and the PyO3 bridge stay
  indefinitely.

## 2. Customer and persona

- **Primary**: the owner as maintainer of the server.
- **Secondary**: future end users of iPhone, Mac, web, CLI and MCP; they see no
  behavior change.
- **Deployment shape**: multi-tenant invite-only service on Fly.io with no real
  users yet (owner, 2026-10-14).

## 3. Business objective and KPI

| metric | baseline today | target | by when |
|---|---|---|---|
| Python in the production server | ~59k lines app code (+ ~123k lines pytest), FastAPI image | 0; image runs no Python | no deadline |
| Server-side implementations of task rules | 2 (Python legacy + Rust via PyO3) | 1 (Rust) | no deadline |
| Native runtimes per Apple app | 2 (legacy Swift + Rust, ~210 selection sites) | 1 (Rust) | no deadline |
| Existing web E2E scenarios passing against the new server | n/a | 100% | no deadline |
| 026 pilot latency (SC-003 p95 ≤ 50 ms local op; SC-004 p95 ≤ 2 s convergence) | 32 ms p95 on M4 against the Python server | still met on reference devices against the Rust server | no deadline |

## 4. Scope boundary

**In scope**

- [ ] The whole server moves to Rust, every product surface 1:1 — owner:
  "Все надо перенести". Nothing is dropped: tasks/GTD, Weekly Review, sync,
  sign-in and accounts (incl. GDPR), CRT canvas and AI validation, agents and
  A2A relay, admin portal and live feature flags, MCP and agent CLI sign-in,
  voice brain dump.
- [ ] Spec 026's open tail is absorbed: the reference-device Apple pilot runs
  against the Rust server; PostgreSQL is the store of the new server from day
  one with no data migration; draft PR #377 (Python PostgreSQL adapter) and
  026's PR-55…57 are superseded. 026 is closed as superseded by this feature.
- [ ] Legacy client code is removed in the same work: the Swift reducer, the
  legacy data engine and the legacy/Rust runtime selection in the iPhone and
  Mac apps; the apps run only on the Rust runtime.

**Out of scope — explicitly confirmed by the human**

- [ ] The web frontend stays React/TypeScript; no offline web, no WASM.
- [ ] No new user-facing functionality: a 1:1 port. API redesign is allowed,
  new user behavior is not.
- [ ] No new platforms: Android, Windows and Linux stay separate specs.
- [ ] Same AI/STT providers, cost caps and Fly.io hosting.

**Confirmed by**: Max on 2026-10-14 (numbered read-back of scope, non-goals,
data/compatibility stance and definition of done; answer "Подтверждаю").

## 5. Constraints

- **Real users**: none yet (owner, 2026-10-14). The owner treats backward
  compatibility with existing data and clients as a low concern on that basis.
- **Deadline**: none (owner, 2026-10-14); delivered as parallel slices as in 026.
- **Existing production data**: may be erased. The new server starts from an
  empty database; no data migration (owner, 2026-10-14).
- **Existing client versions**: no backward compatibility. iPhone, Mac, web,
  CLI and MCP are updated together with the server; older builds (including
  TestFlight) may break. No legacy API and no compatibility window
  (owner, 2026-10-14).

## 6. Compliance obligation

The feature adds no new kind of user data. It must carry over unchanged:

- **New durable records**: none beyond what the Python server stores today.
- **Consent**: AI consent gating behaves exactly as today.
- **Retention**: the policies in `docs/data-retention.md` and ADR-0031's
  command-metadata retention carry over unchanged.
- **Export / Purge**: `AccountService` behavior (ZIP export, 14-day-grace
  deletion and purge) is ported 1:1 and stays never feature-flagged.
- **Erasing current production data** at cutover is an irreversible ASK-class
  action and needs its own explicit authorization at that moment; this intake
  records only that the owner permits it in principle.

## 7. Existing-system dependencies

- **Backend surfaces**: all of `backend/` (API, services, repositories,
  tasks and agents modules, sync, jobs, admin, MCP, auth, voice/STT, CRT).
- **Frontend surfaces**: the web app keeps its UI; it is updated to whatever
  API the new server exposes.
- **Mobile**: must change: the iPhone and Mac apps drop the legacy runtime and
  talk only to the new server.
- **AI providers**: used, unchanged.
- **Primary loop impact**: no behavior change to capture → atomic items →
  clarify/approve → route or CRT candidate → Weekly Review → evidence; the loop
  must work end to end on the new server.

## 8. Definition of done

All four chosen by the owner as mandatory:

- [ ] Zero Python in the server: the production image runs no Python and the
  Python backend is removed or replaced. Repository tooling in `scripts/` may
  stay Python.
- [ ] The web app and the existing Playwright E2E scenarios are green against
  the Rust server with no lost functionality.
- [ ] The spec 026 pilot (quickstart Q01–Q12) passes on the reference iPhone 11
  and MacBook Air M1 against the Rust server and is recorded.
- [ ] Production on Fly.io serves the Rust server; the Python server is shut
  down.

## Deferred to /speckit-clarify

- [x] Local/unsynced device data at cutover — answered during specify on
  2026-10-14: erased; apps start clean; legacy import removed (spec FR-021).

## Contradictions surfaced during the interview

| earlier answer | later answer | resolution | decided by |
|---|---|---|---|
| No new user-facing functionality; 1:1 port | Every signup method requires an invite (planning review, 2026-10-14) | Invite gating is an owner-approved behavior change and amends ADR-0028; spec FR-005/FR-007 | Max |
| Silent local reset (design sign-off) | Confirmation screen before deletion (planning review) | Confirmation wins; spec FR-021 | Max |
| Rollback copy implied by "rollback procedure" | Erase old data immediately after smoke | Erase wins; rollback only until erase; spec FR-019 | Max |
| 026 forbids destructive pilot steps in production | Run the whole pilot in production | Production wins for this feature; each destructive step authorized at run time; spec SC-004 | Max |
| Account purge "complete" at day 14 | Restore points may hold the owner up to 7 more days | Deletion shows pending until the last restore point expires; disclosed; spec FR-009 | Max |
| Old clients get the actionable update wording | Pre-cutover CLI cannot render it | Old CLI shows its generic refusal, nothing written; spec FR-018 | Max |
| CRT validation consent via the inspector toggle | Inspector removed on 2026-09-25 (#236) | Per-request consent at the API, no UI; spec FR-011 | Max |
| — | Cutover record retention | Kept indefinitely, non-personal fields only, outside export/purge; data-model | Max |
