# Research and campaign-1 carry-forward: RTM task-management parity

**Feature**: `specs/011-rtm-task-parity/` | **Captured**: 2026-08-15
**Purpose**: portable source provenance plus the complete campaign-1 finding disposition

This artifact is included in the repository review digest. It replaces dependencies on
unversioned machine-local inputs and carries campaign 1 into campaign 2 as ADR-0011
requires. It is evidence, not a second normative requirements source: `intake.md` owns the
founder intent, `spec.md` owns observable behavior, `design.md` owns states/copy, and
`plan.md`/`tasks.md` own implementation intent.

## Portable founder-brief provenance

The original written brief was supplied by Max on 2026-08-15 before feature 011 was
authored. Its machine/worktree paths and original delivery instruction are intentionally
not reproduced: they were environmental, and the later Task-0-only instruction supersedes
the original request to implement. The portable business content was:

- outcome: a single-owner BrainBuddy user can create, organize, find, edit, complete,
  reopen, trash and restore Tasks; manage regular Lists and Tags; and observe equivalent
  supported semantics across backend, web and Expo mobile;
- invariant: Task lifecycle never derives from agent Execution/Run state;
- frozen P0: task CRUD/detail and selected-List create; due/start date plus optional time;
  priority; incremental Tags; List membership; complete/reopen/trash/restore with retry and
  explicit invalid transitions; List CRUD/archive/unarchive/delete plus virtual Inbox; Tag
  CRUD/count/global delete; search, typed filters, history, stable order/pagination; owner
  isolation and preservation of Voice Brain Dump/Smart Add/idempotency recovery;
- frozen P1: estimate/URL, recurrence, RTM-like subtasks, notes, postpone/count, batch,
  Smart Lists, reminders and locations;
- frozen P2: Calendar, attachments, collaboration, MilkScript-like automation, external
  RTM sync and global settings decisions;
- initial defaults: six commitment states; orthogonal Trash; unchanged Run state; numeric
  priority; floating local times; retained archive membership and separate List deletion;
  global Tag deletion plus incremental membership; AND across filter fields/OR within a
  repeated field; P1 batch-limit recommendation 20.

Campaign 1 correctly held ADR-conflicting or newly surfaced choices open. Max's later named
HD-01…HD-09 answers are recorded with date/rationale in `intake.md`; they are not silently
projected back into the original brief.

## Portable RTM reference provenance

The supplied RTM capability map was researched on 2026-08-15 from the public sources below.
The feature uses it only as a reference model—never as an integration target or claim that
BrainBuddy implements all RTM behavior.

| ref | source | relevant evidence |
|---|---|---|
| R-01 | `https://www.rememberthemilk.com/services/mcp/tools` | official MCP tools: Tasks, batch, Lists, Tags, notes, locations, reminders, contacts, MilkScript, settings, undo |
| R-02 | `https://www.rememberthemilk.com/services/mcp` | MCP product/authorization overview |
| R-03 | `https://www.rememberthemilk.com/services/mcp/faq` | MCP client/RTM Pro and undo context |
| R-04 | `https://www.rememberthemilk.com/services/api/methods` | REST method inventory, timelines, push and transactions |
| R-05 | `https://www.rememberthemilk.com/services/api/tasks.rtm` | task/list/series IDs, incremental sync and UTC REST time |
| R-06 | `https://www.rememberthemilk.com/services/api/methods/rtm.tasks.add.rtm` | task add and external ID |
| R-07 | `https://www.rememberthemilk.com/help/answer/basics-search-advanced` | advanced search operators and grouping |
| R-08 | `https://www.rememberthemilk.com/help/answer/basics-smartadd-howdoiuse` | Smart Add token behavior |
| R-09 | `https://www.rememberthemilk.com/services/milkscript` | server-side scripting model |

The reference map grouped capabilities as create; read/search; update fields; lifecycle;
batch; subtasks; Lists/Smart Lists; Tags; notes; locations/reminders;
assignment/sharing; sync/undo/automation. Its implementation-relevant conclusions are
captured row-by-row in `capability-matrix.md`: RTM's priority is numeric; Trash is distinct
from completion; archive/unarchive and global Tag deletion are explicit; batch caps at 20;
search supports rich composition; and RTM has no BrainBuddy agent Run, blocker, approval,
artifact or progress-event model. Those conclusions justify comparison only; the frozen
scope determines adoption.

## Campaign 1 identity

Campaign 1 is preserved verbatim in `review-history.md` and its ignored run evidence under
`.specify/workflows/runs/011-terminal-20260815/`. It reviewed digest
`97c9d0737af637bfb8a14b38b8919df83cfc29a5518823d0ce4015e26606b6dd`, ran 6/6 lenses,
reported 15 blocking / 18 important / 6 advisory findings, and ended
`product-decision-required`. It had no human sign-off or founder acceptance.

## Blocking findings — all resolved before campaign 2

| id | campaign-1 finding | repair/disposition |
|---|---|---|
| C1-B01 | Readiness was certified while product decisions remained open. | `intake.md` records Max/date/rationale for HD-01…HD-09; `spec.md`/`plan.md`/checklist state that HD-10 and implementation remain gated. |
| C1-B02 | Story 2 forbade legacy priority responses while rollout stage 1 required them. | Story 2 and FR-006 are phase-qualified; stage 1 has explicit legacy default/capability negotiation and safe unknown fallback. |
| C1-B03 | Exact pre-trash restoration conflicted with later List/Tag deletion. | FR-013/FR-039 and `plan.md` define restore as clearing only Trash and preserving legitimate later classification cleanup. |
| C1-B04 | Destructive action auditability had no FR/SC/task/durable record. | FR-037, SC-012, design deletion receipts, `plan.md` audit schema/export/purge, and T-005/T-006/T-036 own it. |
| C1-B05 | An archived member's ordinary PATCH would fail active-reference validation. | ADR-0020, FR-018, `plan.md` archived-reference rules, T-003/T-004 distinguish carried/same ID from new assignment. |
| C1-B06 | Hard List delete plus replay helper would resurrect the List. | FR-015/FR-020 and `plan.md` require redacted `DeletionReceipt`; T-007 bypasses `_project_result` and resolves replay from receipt/audit. |
| C1-B07 | Plan invented additive task columns although task records are JSON payloads. | `plan.md` models `tasks.payload`, scalar index columns and model defaults accurately; T-009/T-023 use payloads, not invented task ALTERs. |
| C1-B08 | SQLite and JSON mirrors could diverge/re-import after delete/migration. | `plan.md` declares SQLite canonical post-ledger, specifies content-free recovery intent, mirror read-back, no post-ledger import, crash recovery and inverse rebuild; T-005/T-006/T-021 prove it. |
| C1-B09 | Evidence map covered only 12 gaps, not all user-facing FRs. | `tasks.md` now has separate 12-gap and full P0 outcome maps plus T-038 full audit and mobile real-backend ownership. |
| C1-B10 | Universal replay/owner isolation had subset-only tests. | FR-015/FR-031, SC-009/SC-013 and T-010/T-025/T-035 enumerate every P0 command/read surface. |
| C1-B11 | No operational owner/evidence authorized priority stage 2. | `plan.md` and T-020 name Max as release-evidence owner, define the complete active-build inventory and fail-closed stage-2/stage-3 records. |
| C1-B12 | List/Tag delete had no durable redacted audit; 24-hour idempotency was insufficient. | Same repair as C1-B04 plus durable same-subject no-op semantics after transient expiry; audit contains IDs/action/time only. |
| C1-B13 | Absolute local paths made provenance non-portable. | `research.md` embeds the business/reference provenance; `intake.md`, `spec.md` and `capability-matrix.md` use repository-relative citations only. |
| C1-B14 | Priority inverse mapping ignored SQLite payload plus JSON mirrors. | FR-006 and `plan.md` stage 2/rollback rewrite and verify both representations before image eligibility; T-021 tests every value/crash boundary. |
| C1-B15 | Principle I was declared unsatisfied with no audit owner. | Constitution check is now satisfied in planning by FR-037/SC-012 and owned T-005/T-006/T-036 evidence; implementation remains gated, not falsely complete. |

## Important findings — explicit disposition

| id | campaign-1 finding | repair/disposition |
|---|---|---|
| C1-I01 | Idempotency scope differed across scenario/FR/SC. | **Resolved:** HD-07, Story 2, FR-015 and SC-009 all say every P0 mutation; `plan.md`/tasks enumerate the same commands and the 24-hour retry boundary. |
| C1-I02 | Archive query/count/search/name consequences lacked task ownership. | **Resolved:** FR-012/FR-018, query predicate table, T-003/T-010/T-030/T-035 cover name resolution, filters, all count kinds and Trash exclusions. |
| C1-I03 | Correlation/owner coverage was too narrow. | **Resolved:** FR-016/FR-031, SC-013 and per-slice matrices cover all reads/writes, 404 equivalence and success/replay/error headers. |
| C1-I04 | Stable order/public pagination documentation had no owner. | **Resolved:** FR-028 defines every total order/cursor component; T-032 tests it and T-036 publishes it. |
| C1-I05 | Active-only List queries made archived members render unassigned. | **Resolved:** explicit active/archived/all List contract and separate all-name map vs active selector in FR-018/plan/T-003/T-011/T-013. |
| C1-I06 | Project/Tag usage counts omitted Trash predicates. | **Resolved:** FR-012 and the plan predicate table distinguish open counts from all-member destructive impact counts; T-005/T-009/T-030 own evidence. |
| C1-I07 | Priority stages 2/3 had no owner and wrong sequencing. | **Resolved:** T-017→T-018/T-019→T-020→T-021→second T-020→T-022 is explicit and non-parallel. |
| C1-I08 | Tag delete, AND/OR and repeated ordering lacked named evidence. | **Resolved:** T-008, T-030, T-032 and T-035 name backend, web, mobile and real-backend evidence. |
| C1-I09 | `[P]` markers hid client/hook/journey dependencies. | **Resolved:** only qualified `[P after T-nnn]` markers remain; journeys wait for backend and both clients. |
| C1-I10 | Plan falsely called the whole task module mutation-enforced. | **Resolved:** plan records only `repository.py` in the observed tier and no task file in the enforced list; T-040 forbids a stronger claim. |
| C1-I11 | Trash retention was unanswered. | **Resolved by Max HD-05:** no automatic purge; explicit confirmed permanent deletion/Empty Trash or account purge only; FR-038/T-024/T-036. |
| C1-I12 | Archived Lists could disappear from GDPR export. | **Resolved:** FR-035 explicitly includes archived Lists; T-005/T-006 and T-036 own export/retention tests/docs. |
| C1-I13 | Owner-isolation evidence omitted archived/Trash/history and lacked an SC. | **Resolved:** SC-013 plus T-010/T-015/T-025/T-028/T-035 cover those surfaces and mobile real backend. |
| C1-I14 | Deleted List/Tag name export disposition was unresolved. | **Resolved by Max HD-06:** immediate erase; durable IDs/action/time-only audit, life-of-account/exported/account-purged; FR-020/FR-023/FR-037. |
| C1-I15 | Stale mobile had no safe rendering fallback for unknown priority. | **Resolved:** FR-006/design D-02/M-02 require `Priority unavailable`, no coercion/rank/color/save; T-018/T-019/T-028. |
| C1-I16 | New state copy remained unspecified. | **Resolved:** every copy cell in `design.md` contains literal text/template; T-012/T-014/T-026/T-027/T-033/T-034 assert it. |
| C1-I17 | Mutations other than restore were undefined while trashed. | **Resolved:** FR-039 and plan Trash rules reject direct writes and allow only restore/permanent erase/global cleanup; T-024/T-025. |
| C1-I18 | Trashed tasks were missing from count/delete-impact semantics. | **Resolved:** FR-012/FR-020/FR-023 and predicate table enumerate default/open exclusion and all-member destructive counts; T-005/T-030. |

## Advisory findings — carried and dispositioned

| id | campaign-1 finding | disposition |
|---|---|---|
| C1-A01 | Several `[P]` markers hid direct dependencies. | Repaired with qualified dependency markers only. |
| C1-A02 | Data-retention/privacy documentation had no synchronized owner. | T-036 owns `docs/data-retention.md`, API compatibility and the in-app privacy policy/test in one slice. |
| C1-A03 | Unknown-filter errors could reflect raw input. | FR-027/T-031 require a sanitized supported-parameter list without raw reflection. |
| C1-A04 | Mobile sheets omitted screen-reader focus/restore/announcement behavior. | `design.md` specifies Cancel-first VoiceOver/TalkBack behavior, accessibility escape, announcements and detached-trigger fallback; SC-015/T-039 capture it. |
| C1-A05 | Priority gate lacked dated build/person evidence. | Raised from advisory to required SC-014/T-020 operational evidence owned by Max. |
| C1-A06 | Strict unknown-query rejection lacked a released-client parameter inventory. | T-031 inventories parameters emitted by current/released web/mobile clients before strict rejection lands. |

## Product decisions and residual gate

HD-01…HD-09 are resolved by Max on 2026-08-15 and recorded in `intake.md`. ADR-0020
records the two decisions that supersede ADR-0006. HD-10 is intentionally unresolved:
campaign 2 must first compute its own run ID and artifact digest. No agent may create
`human-signoff.json`, reuse the campaign-1 digest, or describe the package decisions as a
fresh-digest high-risk approval.
