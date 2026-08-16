# Tasks: RTM task-management parity

**Feature**: `specs/011-rtm-task-parity/` | **Plan**: `plan.md` | **Design**: `design.md`
**Current behavior**: `capability-matrix.md` (`C-nn` ids)
**Planning status**: Task-0 repair only; implementation prohibited pending campaign 2 + HD-10

Rules for every implementation task:

- Strict RED→GREEN: observe the feature-qualified test fail before implementation.
- Backend contract/repository/service work precedes clients that consume it.
- Test names use `011_FR_nnn`; Allure emits epic/feature/story/title/named step.
- Every implementation slice is high-risk/ASK-class and never lands automatically.
- `[P after T-nnn]` means parallel only after the named dependency is complete and only
  across disjoint files. An unqualified `[P]` marker is not used.
- Local tests, campaign review, CI, landing and deploy are separate evidence classes.

## P0 gap evidence map

SC-002 requires an automated test on each tier for every canonical gap. Mobile evidence
includes Jest and the real-backend task named in the final column; another tier cannot
substitute.

| canonical gap | requirement | backend | web | mobile unit | mobile real backend |
|---|---|---|---|---|---|
| C-09 due time | FR-004, FR-007 | T-023 | T-026 | T-027 | T-028 |
| C-10 start date | FR-005, FR-007 | T-023 | T-026 | T-027 | T-028 |
| C-11 start time | FR-005, FR-007 | T-023 | T-026 | T-027 | T-028 |
| C-12 priority vocabulary | FR-006 | T-017, T-021, T-022 | T-018 | T-019 | T-020, T-028 |
| C-14/C-47 incremental tags | FR-009 | T-008 | T-011, T-012 | T-013, T-014 | T-015 |
| C-25 Trash | FR-011, FR-012 | T-009, T-024 | T-026 | T-027 | T-028 |
| C-26 restore | FR-013 | T-024 | T-026 | T-027 | T-028 |
| C-36 archive retains membership | FR-018 | T-003, T-004 | T-011, T-012 | T-013, T-014 | T-015 |
| C-38 unarchive | FR-017, FR-019 | T-003, T-004 | T-011, T-012 | T-013, T-014 | T-015 |
| C-39 List delete | FR-020 | T-005…T-007 | T-011, T-012 | T-013, T-014 | T-015 |
| C-55 no-due + strict unknown filters | FR-025, FR-027 | T-030, T-031 | T-033 | T-034 | T-035 |
| C-56 start windows | FR-025 | T-030 | T-033 | T-034 | T-035 |

## Full P0 outcome ownership

The gap map is not the FR-030 evidence map. These groups cover every user-facing and
cross-cutting outcome, including already-working behavior and campaign-1 omissions.

| outcome group | requirements | owning tasks/evidence |
|---|---|---|
| Task create/read/detail/title/notes/List | FR-001, FR-002, FR-008 | T-000, T-010, T-026…T-028 |
| date/start/priority fields | FR-003…FR-007 | T-017…T-023, T-026…T-028 |
| tag incremental + explicit replace | FR-009, FR-010 | T-008, T-010…T-015 |
| lifecycle/Trash/restore/erasure/trashed guards | FR-011…FR-016, FR-038, FR-039 | T-009, T-024…T-028 |
| List management and archived resolution | FR-017…FR-021 | T-003…T-007, T-010…T-015 |
| Tag management and global deletion | FR-022, FR-023 | T-005, T-006, T-008, T-010…T-015 |
| search/filter/order/pagination/history | FR-024…FR-029 | T-030…T-035 |
| cross-tier/owner/Run/regression | FR-030…FR-033 | T-000, T-010, T-015, T-025, T-028, T-035, slice gates |
| docs/export/cache/audit | FR-034…FR-037 | T-005, T-006, T-010…T-015, T-024…T-028, T-036 |
| rendered acceptance evidence | SC-015 | T-039 |

## Task-0 and foundations

- [ ] **T-000 — Preserved-capability regression baseline.** Pin current P0 PASS behavior
      across backend, web and mobile: FR-001/FR-002 create-read-detail-update,
      FR-003 date-only due, FR-008 List assignment/clear, FR-010 whole-tag replacement,
      FR-014 complete/reopen with explicit destination, FR-021 Inbox virtuality,
      FR-022 Tag create/list-count/rename, FR-024 search, FR-029 completed/cancelled history,
      FR-032 Run separation, and FR-033 Voice Brain Dump/Smart Add/idempotency recovery.
      **Acceptance**: named feature-qualified tests exist per tier and fail if a later slice
      removes a preserved path.
- [x] **T-001 — Ratify founder decisions.** Add
      `docs/decisions/0020-rtm-parity-priority-and-archive-semantics.md`, recording Max's
      HD-01/HD-03 decisions and narrowly superseding ADR-0006. Update `AGENTS.md` because its
      architecture summary otherwise points readers to the superseded rules.
      **Evidence**: Task-0 campaign-1 repair commit; no product implementation.
- [ ] **T-002 — Shared contract and crash-fixture foundation.** Add reusable legacy/numeric
      priority fixtures, JSON-payload/mirror fixtures, deterministic interruption points,
      redacted audit assertions and a cross-tier contract vector. **Acceptance**: fixtures
      contain no real data, local paths, content hashes usable as fingerprints, or secrets;
      backend/web/mobile consumers all read the same vectors.

## Slice 1 — organization, audit and Trash substrate

Depends on T-000 and T-002. Closes C-14/C-47, C-36, C-38, C-39 and C-68.

### Backend contract and persistence

- [ ] **T-003 — RED: archived-membership contract.** Tests cover open/completed/cancelled/
      trashed members, active/archived/all List order, archived-name filtering/render
      resolution, assignment rejection, and PATCH rules: omitted/same archived ID retained;
      clear/active move allowed; new archived assignment rejected. **Acceptance**: FR-017…
      FR-019, FR-028, FR-031, SC-004, with owner/correlation cases.
- [ ] **T-004 — GREEN: archive/unarchive and reference validation.** Change archive to retain
      membership, add unarchive and archived query, and make active-reference validation
      compare old/new assignment rather than rejecting a carried archived ID.
      **Depends on**: T-003. **Acceptance**: T-003 passes; no historical backfill.
- [ ] **T-005 — RED: audit/export/purge and mirror-failure matrix.** Tests require the exact
      IDs/action/time-only audit schema, life-of-account export, account purge, no deleted
      name/content, impact counts including trashed/terminal tasks, crash recovery before/
      after SQLite commit, and no replay resurrection. **Acceptance**: FR-020, FR-023,
      FR-035, FR-037, SC-005, SC-012.
- [ ] **T-006 — GREEN: redacted audit + content-free mirror outbox.** Add the SQLite tables,
      repository methods, account export/purge ownership, content-free recovery ledger and
      `DeletionReceipt`. Delete paths erase the name-bearing mirror before commit, repair
      from canonical SQLite on rollback, drain committed intent on restart/retry, and do not
      log content/hashes. **Depends on**: T-005.
- [ ] **T-007 — RED→GREEN: List hard delete.** In one owner-locked command clear every open/
      completed/cancelled/trashed member payload/index, delete the List row/name/mirror,
      append audit and return the redacted receipt. Replay resolves from receipt and bypasses
      `_project_result`. **Depends on**: T-004, T-006. **Acceptance**: FR-015, FR-020,
      FR-031, FR-037; task count/lifecycle/Trash values unchanged.
- [ ] **T-008 — RED→GREEN: incremental tags and Tag hard delete.** Add/remove one tag without
      clobbering concurrent unrelated tags; retain explicit whole-set replace; convert global
      Tag delete from a name-bearing deleted row to hard erase plus redacted receipt, clearing
      all lifecycle/Trash members and bypassing `_tag_result` on replay. **Depends on**:
      T-006. **Acceptance**: FR-009, FR-010, FR-015, FR-022, FR-023, FR-037, SC-006.
- [ ] **T-009 — RED→GREEN: JSON-payload Trash substrate.** Add nullable `trashed_at` through
      the domain/schema and write-through task mirrors; no invented task `ALTER TABLE`
      column. Add exact exclusion helpers shared by list/search/count/Project/Tag paths and
      prove export/internal owner reads remain unfiltered. **Acceptance**: FR-011, FR-012,
      FR-035; old payloads load null and existing query results remain unchanged.
- [ ] **T-010 — Slice-1 cross-cutting matrix.** Cover every Slice-1 mutation's same-key replay,
      key/body conflict, stale revision, owner/absent `404`, correlation header, audit
      uniqueness, stable List/Tag ordering, and cache-invalidation response facts.
      **Depends on**: T-004, T-007…T-009. **Acceptance**: FR-015, FR-016, FR-028, FR-031,
      SC-009, SC-013.

### Web and mobile (after backend contract)

- [ ] **T-011 [P after T-010] — Web API/hooks/cache.** Add archived/all List queries,
      unarchive, redacted delete receipt, incremental tags and precise React Query
      invalidation from FR-036. **Acceptance**: typed contract and invalidation tests cover
      active/archived selectors, name resolution, rows, filters and counts.
- [ ] **T-012 [P after T-010] — Web D-03/D-04.** Implement every numbered state and exact
      copy/focus behavior, including impact counts that include terminal/trashed tasks.
      **Acceptance**: FR-017…FR-023, FR-030, `design.md` D-03/D-04.
- [ ] **T-013 [P after T-010] — Mobile API/hooks/cache.** Add the missing management hooks,
      archived/all name resolution, redacted receipts, resume-before-retry and FR-036
      invalidation. **Acceptance**: typed/Jest evidence; no periodic-sweep-only path.
- [ ] **T-014 [P after T-010] — Mobile M-03/M-04 organization states.** Implement exact copy,
      44 pt controls, Cancel-first confirmation focus, accessibility announcements and focus
      restoration. **Acceptance**: FR-017…FR-023, FR-030, `design.md` M-03/M-04.
- [ ] **T-015 — Slice-1 real-backend journeys.** After T-011…T-014, run web cross-surface and
      `mobile/integration/` journeys for archive→PATCH→unarchive, archived-name rendering,
      List/Tag delete across open/terminal/trashed tasks, no resurrection, owner isolation,
      correlation IDs, offline resume and cache read-back. **Acceptance**: SC-004…SC-006,
      SC-009, SC-012, SC-013.
- [ ] **T-016 — Slice-1 regression gate.** Re-run T-000 Voice Brain Dump, Smart Add and
      idempotency-recovery suites. A failure blocks Slice 1. **Acceptance**: SC-011.

## Slice 2 — fields, lifecycle and staged priority

Depends on Slice 1, especially T-006/T-009. Closes C-09…C-12, C-25 and C-26.

### Priority compatibility (ordered, never parallel)

- [ ] **T-017 — RED→GREEN stage 1 backend.** Dual request reader, legacy canonical storage/
      default response, explicit numeric-capability response, exact mapping/order, unknown
      rejection, and legacy fallback. Tests cover SQLite payload and JSON mirror values.
      **Acceptance**: FR-006; no default response change.
- [ ] **T-018 — Web dual reader/writer.** After T-017, accept both vocabularies, advertise
      numeric capability, render exact labels, and show `Priority unavailable` without
      coercion/save for an unknown value. **Acceptance**: FR-006, D-02.
- [ ] **T-019 — Mobile dual reader/writer.** After T-017, same contract and fallback in Jest,
      including interrupted cache hydration and no undefined color/label lookup.
      **Acceptance**: FR-006, M-02.
- [ ] **T-020 — Operational gate evidence (owner: Max, release operator).** After T-018/T-019,
      create the dated implementation evidence record listing backend SHA/build, web build,
      every active installed mobile build/device slot, verifier and read/edit/filter/sort
      outcome. A merely released, unknown, omitted or unverified build fails closed.
      **Acceptance**: HD-08, SC-014. This task cannot be satisfied by unit tests.
- [ ] **T-021 — RED→GREEN stage 2 migration/default switch.** Only after T-020 is green,
      rewrite every SQLite payload, regenerate/verify every task mirror through the ledger,
      switch the default response to numeric, retain legacy request/no-capability response,
      and test crash resume plus inverse rollback-before-old-image. **Acceptance**: FR-006,
      SC-014; mapping round-trips all four values.
- [ ] **T-022 — Stage 3 compatibility close.** Only after a second complete T-020 inventory,
      reject legacy requests and remove legacy response fallback. **Acceptance**: FR-006;
      the evidence records distinct stage-2/stage-3 decisions.

### Other fields and Task lifecycle

- [ ] **T-023 [P after T-017] — Due/start fields.** RED→GREEN JSON-payload date/time fields,
      floating semantics, validation of time-without-date, clear/reload, start-after-due and
      mirror compatibility. **Acceptance**: FR-003…FR-005, FR-007.
- [ ] **T-024 — RED→GREEN Trash/restore/permanent erase/Empty Trash.** After T-006/T-009,
      implement Trash without commitment transition, restore that clears only Trash,
      trashed-task mutation guards, explicit erasure of task/subtasks/comments/mirrors,
      audit receipts and exact count/export predicates. **Acceptance**: FR-011…FR-016,
      FR-035, FR-037…FR-039, SC-003, SC-012.
- [ ] **T-025 — Slice-2 cross-cutting matrix.** Cover every field/lifecycle/Priority-stage
      mutation for replay/key conflict/stale/owner/absent/correlation; prove agent Run
      separation and all classification changes while trashed. **Depends on**: T-021,
      T-023, T-024. **Acceptance**: FR-015, FR-016, FR-031, FR-032, SC-009, SC-010, SC-013.
- [ ] **T-026 [P after T-025] — Web D-02/D-05.** Field editors, exact priority labels/fallback,
      Trash/restore/permanent delete/Empty Trash, exact copy/focus/live-region behavior and
      complete cache invalidation. **Acceptance**: FR-003…FR-016, FR-030, FR-036…FR-039.
- [ ] **T-027 [P after T-025] — Mobile M-02/M-04.** Equivalent fields/actions, 44 pt targets,
      Cancel-first VoiceOver/TalkBack focus, interruption/refetch and cache behavior.
      **Acceptance**: same FR set as T-026.
- [ ] **T-028 — Cross-tier lifecycle evidence.** After T-026/T-027, Playwright and mobile
      real-backend journeys cover field reload, stage-2 numeric values, complete→reopen→
      trash→classification delete→restore, permanent delete/Empty Trash, owner isolation,
      replay, correlation ID and interrupted read-back. **Acceptance**: SC-002, SC-003,
      SC-009…SC-014.
- [ ] **T-029 — Slice-2 regression gate.** Re-run T-000 suites. **Acceptance**: SC-011.

## Slice 3 — search, history, ordering and pagination

Depends on Slice 2 fields/Trash. Closes C-51, C-54, C-55 and C-56 without changing P1.

- [ ] **T-030 — RED→GREEN exact predicates.** Implement multi-Tag OR, cross-field AND,
      closed due range/today/overdue/no-due, start available/future, explicit terminal/Trash
      visibility, archived List filtering, and shared exclusion/count helpers. Tests assert
      every row of `plan.md` §Exact query/count predicates. **Acceptance**: FR-012,
      FR-024…FR-026, FR-029.
- [ ] **T-031 — RED→GREEN strict query inventory.** Inventory parameters emitted by every
      released/current web/mobile client, accept only the supported set, and return a
      sanitized `400` listing allowed parameters without reflecting raw unknown input.
      **Acceptance**: FR-016, FR-027, SC-007; commit notes the breaking change.
- [ ] **T-032 — RED→GREEN total order/cursor binding.** Implement every FR-028 order and bind
      owner, normalized repeated filters, archived/Trash/terminal visibility, sort and last
      tuple. Tests cover repeated identical requests, duplicate tie values, all pages,
      changed-filter cursor rejection and counts beyond page one. **Acceptance**: FR-028,
      SC-008.
- [ ] **T-033 [P after T-032] — Web D-01 query surface.** All filters/history/Trash/
      continuation states, exact copy, correlation errors and cursor restart; invalidate per
      FR-036. **Acceptance**: FR-024…FR-030.
- [ ] **T-034 [P after T-032] — Mobile M-01 query surface.** Equivalent states with offline
      saved-result labeling and page-one refetch on resume. **Acceptance**: FR-024…FR-030.
- [ ] **T-035 — Cross-tier query evidence.** After T-033/T-034, Playwright and mobile
      real-backend tests cover details-only search, AND/repeated OR, Tag deletion, archived
      List name/filter, every due/start mode, exact order, full pagination, owner isolation,
      correlation IDs and interrupted resume. **Acceptance**: FR-024…FR-031, SC-002,
      SC-007, SC-008, SC-013.
- [ ] **T-036 [P after T-032] — API, retention and privacy docs owner.** Update
      `docs/api-compatibility.md` with exact filters/order/pagination/priority stages and RTM
      divergences; update `docs/data-retention.md` with no automatic Trash purge, explicit
      erasure, audit/mirror retention/export/purge; update
      `frontend/src/pages/PrivacyPolicyPage.tsx` and its test in the same slice so user-facing
      copy stays synchronized. **Acceptance**: FR-026, FR-028, FR-034, FR-035, FR-037,
      FR-038; owner is the Slice-3 docs implementer, reviewed by the privacy lens.
- [ ] **T-037 — Slice-3 regression gate.** Re-run T-000 suites. **Acceptance**: SC-011.

## Closeout

- [ ] **T-038 — Full parity/evidence audit.** Re-walk all 70 matrix rows; name one backend,
      web, mobile-unit and mobile-real-backend test for each of the 12 canonical gaps, and
      prove every user-facing FR-001…FR-039 outcome has proportionate evidence. No row may be
      reclassified out of scope to make the denominator pass. **Acceptance**: SC-001,
      SC-002.
- [ ] **T-039 — Rendered acceptance evidence.** Capture required desktop/mobile screenshots
      for D-01…D-05 and M-01…M-04 plus keyboard and VoiceOver/TalkBack video proving modal
      entry, announcements, cancel, success and focus restoration. **Acceptance**: HD-09,
      SC-015; missing evidence rejects `/speckit-accept`.
- [ ] **T-040 — Final local verification.** Run `make verify-all`, the requirement coverage
      validator and affected observed mutation report; distinguish local results from CI,
      landing and deploy. **Acceptance**: zero unexplained failures; no claim that task files
      are in the ADR-0016 enforced mutation tier.

## P1 backlog package

Frozen; not implemented in this tranche. Subtasks, notes and batch may parallelize only
after Slices 1–3 land. Recurrence, reminders and locations remain separate tasks.

- [ ] **P1-01 — Estimate and URL** (C-16). Depends on Slice 2.
      **Acceptance**: estimate accepts a duration and round-trips; URL is validated and
      clearable; both filterable; all three tiers.
- [ ] **P1-02 — Recurrence** (C-17). Depends on Slice 2 and P1-05.
      **Acceptance**: `every` and `after completion` remain distinguishable; completion
      creates the next instance without mutating history; trashing offers to stop future
      instances; date arithmetic is explicit.
- [ ] **P1-03 — RTM-like subtasks** (C-18). Depends on Slice 2.
      **Acceptance**: `parent_task_id` nesting to three levels with recurrence restrictions;
      existing flat subtasks migrate or are explicitly retained alongside.
- [ ] **P1-04 — Batch operations** (C-63). Depends on Slices 1–3.
      **Acceptance**: complete/move/tag/update/trash across a bounded set; explicitly atomic
      or partial-result; partial results name every failed ID/reason. Recommended limit: 20.
- [ ] **P1-05 — Postpone with count** (C-28). Depends on Slice 2.
      **Acceptance**: shifts due one day, increments a filterable visible count, and defines
      behavior for an undated task.
- [ ] **P1-06 — Smart Lists and advanced search** (C-41, C-62). Depends on Slice 3.
      **Acceptance**: negation/grouping over Slice-3 filters; saved query is a filter set,
      never a second task container.
- [ ] **P1-07 — Notes distinct from comments** (C-64). Depends on Slice 2.
      **Acceptance**: separate CRUD container and explicit product distinction.
- [ ] **P1-08 — Locations** (C-19). Depends on Slice 1.
      **Acceptance**: location CRUD/assignment; no background geofencing implied.
- [ ] **P1-09 — Reminders** (C-65). Depends on P1-01…P1-05 and a timezone/DST decision.
      **Acceptance**: relative to due/start with explicit timezone and DST semantics.

## P2

Frozen product decisions only — see `p2-decisions.md`. Nothing there becomes a task until
a later named decision is made.
