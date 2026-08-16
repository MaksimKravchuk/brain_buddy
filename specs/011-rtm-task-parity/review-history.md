# Review history: RTM task-management parity

## Campaign metadata

| field | value |
|---|---|
| Feature | `011-rtm-task-parity` |
| Review date | 2026-08-15 |
| Reviewer | Independent Codex terminal review using the repository-pinned `speckit-review` gate |
| Original planning author | Claude (nine untracked artifacts supplied for review) |
| Branch | `feat/011-rtm-task-parity` |
| Base / HEAD reviewed | `origin/main` / `87a93739573679f56f495e8722c620f0ec97ae22` |
| Campaign | 1 of the hard maximum of 2 |
| Run id | `011-terminal-20260815` |
| Reviewed artifact digest | `97c9d0737af637bfb8a14b38b8919df83cfc29a5518823d0ce4015e26606b6dd` |
| Risk | `high`, raised by the path classifier from the default `medium` |
| Human sign-off | absent |
| Founder acceptance | absent |
| Lenses | 6/6: five mandatory lenses plus `adversarial-high-risk` |
| Missing / stale / degraded lenses | none / none / none |
| Panel provenance | Codex `gpt-5.6-sol` ×2; Claude `opus` ×2, `sonnet` ×1, `fable` ×1 |
| Panel correlation | `false`; two providers represented |
| Aggregated findings | 15 blocking, 18 important, 6 advisory before cross-lens deduplication |
| Aggregated product-decision entries | 21 before consolidation into the decision packet below |
| Terminal verdict | `product-decision-required` |

The deterministic preflight passed after the feature directory was supplied explicitly.
The campaign reviewed the five artifacts supported by the harness (`spec.md`, `plan.md`,
`design.md`, `tasks.md`, and `checklists/requirements.md`). The independent terminal
reviewer additionally read `intake.md`, `capability-matrix.md`, `analysis.md`, and
`p2-decisions.md`, all governing review ADRs and rubrics, the relevant architecture,
privacy and UX authorities, and the source files cited below.

The persisted machine summary for this working session was
`.specify/workflows/runs/011-terminal-20260815/planning-review-summary.json`. Run-directory
artifacts are ignored working evidence; this file is the versioned campaign record.

## Single consolidated repair record

One objective-consistency correction was applied before the model campaign and no product
choice was made. This is the sole consolidated correction permitted in this review.

- Reconciled the requirement range to FR-001…FR-036 and the canonical P0 denominator to 12
  across `plan.md`, `tasks.md`, `analysis.md`, and the requirements checklist.
- Recomputed the row-level capability totals in `capability-matrix.md`: 39 PASS, 5 PARTIAL,
  2 DIVERGENT, and 24 ABSENT. Removed the false claim that a prior review-history campaign
  had already caught the defect.
- Added the missing forward ownership for FR-035 export evidence and FR-036 cache
  invalidation, plus the 12-gap per-tier evidence map promised by SC-002.
- Made `spec.md` FR-030 agree with `design.md` that FR-010 is a contract-only operation with
  no standalone client affordance.
- Reconciled the open-decision inventories so OD-1, OD-2, Trash retention, deleted-name
  export disposition, priority labels, and absent rendered designs are no longer presented
  as settled in one artifact and open in another.
- Filled objective state-inventory gaps for loading, interruption, partial refresh, unsaved
  navigation, and modal focus, while leaving rendered-design acceptance to the human.
- Made the plan state its existing Principle I audit gap and the prohibition on starting
  T-001 before human decisions, rather than certifying either as complete.

No production code, tests, configuration, workflow, ADR, runtime state, secret, auth
surface, or infrastructure was changed. The correction deliberately did not answer any
decision in the packet below. Findings surfaced by the subsequent campaign remain open and
are recorded rather than silently consuming a second repair round.

## Five-lens findings

### 1. Requirements consistency

Verdict: `product-decision-required`.

| severity | finding | evidence |
|---|---|---|
| blocking | Readiness is certified while implementation-blocking decisions remain open. | `spec.md:7,20-28`; `design.md:6,200-213`; `plan.md:187-190`; `checklists/requirements.md:11-15,20-28,69-78` |
| blocking | Story 2 forbids legacy priority responses while FR-006 requires legacy-only responses in rollout stage 1. | `spec.md:126-129,216-229`; `tasks.md:139-144`; `plan.md:206-215` |
| blocking | “Exact pre-trash restoration” conflicts with List/Tag deletion changing a task while it is trashed. | `spec.md:180-181,246-247,273-275,283-284`; `tasks.md:156-157` |
| blocking | Constitution-mandated destructive-action auditability has no FR, SC, task, or durable record. | `.specify/memory/constitution.md:37-42`; `plan.md:43,51-54`; `tasks.md:41-212` |
| important | Idempotency scope differs among the lifecycle scenario, FR-015, and SC-009. | `spec.md:135-137,250-252,372-373`; `tasks.md:101-104,158-160`; ADR-0006 transition rules |
| important | FR-018's query, count, search, filter, and archived-List-name consequences do not reach acceptance tasks. | `spec.md:261-270`; `tasks.md:76-81,112-126` |
| important | Correlation-ID and owner-isolation coverage is narrower than the cross-cutting contract. | `spec.md:253-255,309-310`; `design.md:60-68,81-127`; `tasks.md:82-104,150-163,184-199` |
| important | FR-028 requires a published total order, but the documentation task omits order and pagination. | `spec.md:297-299`; `plan.md:151-159`; `tasks.md:194-197,206-208` |

### 2. Architecture consistency

Verdict: `product-decision-required`.

| severity | finding | evidence |
|---|---|---|
| blocking | Retaining archived membership makes ordinary task PATCH fail because `_assert_active_references` rejects the carried archived `project_id`. | `backend/app/modules/tasks/service.py:645-651,1346-1351,978-1001`; `tasks.md:76-80`; `spec.md:261-270` |
| blocking | Hard List delete plus the shared replay helper resurrects the deleted List. | `backend/app/modules/tasks/service.py:1175-1188`; `backend/app/modules/tasks/domain.py:16-17`; `backend/app/modules/tasks/repository.py:121,164-176,641-677`; `plan.md:32-34,117-118` |
| blocking | The plan describes additive task columns, but tasks are JSON payloads and the repository has no task-schema `ALTER TABLE` path. | `plan.md:25-27`; `backend/app/modules/tasks/repository.py:145-231`; `tasks.md:97-100`; agents repository migration precedent at `backend/app/modules/agents/repository.py:303-307` |
| blocking | SQLite and per-record JSON mirrors are dual live stores; List deletion and priority rewrite leave mirrors stale and re-importable. | `backend/app/modules/tasks/repository.py:233-284,336,352,385,641-677`; `backend/app/repositories/base.py:29-43`; `plan.md:25,200-215` |
| important | Active-only List queries make archived memberships render as “No project” or an unmatched selector value. | `backend/app/modules/tasks/service.py:859-866`; `frontend/src/features/tasks/TaskListPage.tsx:108,126,557-570`; `TaskDetailPanel.tsx:203,291-297`; `spec.md:261-270` |
| important | Project and Tag usage-count predicates also need trashed exclusion but are absent from the plan. | `backend/app/modules/tasks/service.py:885-896`; `design.md:108-109`; `tasks.md:150-155`; `spec.md:243-245` |
| important | FR-006 stages 2/3 have no task owner, and T-017 is sequenced before the client build that gates stage 2. | `spec.md:216-229`; `plan.md:200-215`; `tasks.md:8-10,139-144,167-169` |
| advisory | Several `[P]` markers hide direct hook/client dependencies. | `tasks.md:18,108-116,120-126` |

### 3. Testability and evidence

Verdict: `product-decision-required`.

| severity | finding | evidence |
|---|---|---|
| blocking | The evidence map covers only the 12 gaps, while FR-030 covers all user-facing FR-001…FR-029 outcomes. | `spec.md:305-308,357-359`; `tasks.md:20-39,47-57,262-267`; `mobile/AGENTS.md:20-27` |
| blocking | Universal replay and owner-isolation outcomes are tested on only a subset of commands/surfaces. | `spec.md:309-310,372-373`; `tasks.md:85-86,101-104,150-163,198-199`; `capability-matrix.md:146` |
| blocking | No operational evidence owner defines when the installed-mobile-build gate authorizes priority stage 2. | `spec.md:222-229`; `tasks.md:139-144`; `plan.md:206-218` |
| important | Tag deletion, cross-field AND composition, and repeated-request ordering lack proportionate named evidence. | `spec.md:281-294,364,369-371`; `tasks.md:47-55,184-185,194-197,206-208`; `backend/tests/test_task_tag_project_mvp_api.py:52-85` |
| important | `[P]` marks dependent web, mobile, and Playwright work as independent lanes. | `tasks.md:18,108-126,167-171`; `plan.md:100-101` |
| important | The plan falsely claims the entire task module is in the enforced mutation tier. | `plan.md:182-183`; ADR-0016; `backend/pyproject.toml:169-186`; `backend/mutation-enforced-scope.txt:66-71` |

### 4. Privacy, consent, and security

Verdict: `product-decision-required`.

Consent/provider configuration is not implicated, owner-scoping semantics are correctly
stated, and account purge reaches task-module data. The following gaps remain.

| severity | finding | evidence |
|---|---|---|
| blocking | Irreversible List/Tag delete has no durable redacted audit record; the only current trace expires after 24 hours. | Constitution Principle I; `plan.md:43,51-54`; `spec.md:273-284`; `tasks.md:87-90`; `backend/app/modules/tasks/repository.py:585-596` |
| blocking | Three feature artifacts expose absolute local paths and rely on non-portable inputs. | `spec.md:10`; `capability-matrix.md:6`; `intake.md:13`; Constitution Principle I |
| important | Trash retention/erasure is intentionally unanswered. | `spec.md:63-66,240-247`; `design.md:209`; `intake.md:126`; `docs/data-retention.md:16` |
| important | Archived Lists lack FR-035-equivalent protection against being hidden from GDPR export. | `spec.md:262-270,320-323`; `backend/app/services/account_service.py:243-251`; `backend/app/modules/tasks/repository.py:417-418`; `tasks.md:85-86` |
| important | Owner-isolation evidence omits archived-list, trash, restore, and trashed-history surfaces and has no measurable SC. | `spec.md:309-310,346-377`; `tasks.md:85-86,101-104,150-160,198-199`; `docs/auth.md:23` |
| important | Deleted List/Tag name export disposition is unresolved. | `spec.md:63-66,273-284`; `design.md:210-211`; `intake.md:127-128`; `docs/data-retention.md:114-133` |
| advisory | No task keeps data-retention documentation and the privacy policy synchronized with new retention, audit, and cache invalidation facts. | `tasks.md:206-208`; `spec.md:325-328`; `docs/data-retention.md:1-8,24-32` |
| advisory | Unknown-filter errors do not forbid echoing user-supplied values in the response body. | `design.md:65-66`; `backend/app/api/tasks.py:809`; `tasks.md:191-193`; Constitution Principle IV |

### 5. UX, accessibility, and mobile

Verdict: `product-decision-required`.

| severity | finding | evidence |
|---|---|---|
| important | No safe rendering fallback exists for an unrecognized priority value on a stale mobile build. | `spec.md:190,216-229`; `design.md:84-99`; `plan.md:198-208`; `mobile/src/app/task/[id].tsx:90-95,673,1003`; `mobile/src/features/tasks/taskScreenState.ts:62-67` |
| important | Required copy is still `—` for several new empty, partial-failure, and error states. | `design.md:81,97,106,111,113,127`; `checklists/requirements.md:12` |
| advisory | Mobile confirmation sheets lack VoiceOver/TalkBack focus placement, restoration, and announcement behavior. | `design.md:49,165-190` |

The lens also confirms a genuine human UX decision: if OD-1 is accepted, the clients still
need an authoritative choice among bare digits, digit-plus-word labels, or word-only labels.

### High-risk adversarial review

Verdict: `product-decision-required`.

| severity | finding | evidence |
|---|---|---|
| blocking | The priority inverse mapping is not reversible over the actual SQLite-plus-JSON-mirror topology. | `plan.md` Technical Context/Rollback; `backend/app/modules/tasks/repository.py:164-176,233-272,312-314,336-385`; `tasks.md` T-017 |
| blocking | The plan declares Principle I unsatisfied but gives the mandatory audit gap no owner. | `plan.md` Constitution Check/Open compliance work; Constitution Principle I and review rule; `tasks.md`; `backend/app/modules/tasks/repository.py:39` |
| important | Mutating commands other than restore have no defined contract while a task is trashed. | `spec.md` FR-011…FR-016, FR-030, SC-003 and Edge Cases; `design.md:93`; `tasks.md` T-022 |
| important | Trashed exclusion is absent from project member and Tag usage counts, including destructive-confirmation counts. | `backend/app/modules/tasks/service.py:885-896`; `backend/app/schemas/tasks.py:57`; `tasks.md` T-020; `design.md` D-03 |
| advisory | The priority stage-2 installation gate has no recorded build/person evidence. | `spec.md` FR-006; `plan.md` stage 2; `mobile/src/api/client.ts` |
| advisory | Strict unknown-parameter rejection lacks an inventory of parameters sent by released web/mobile clients. | `tasks.md` T-031; `capability-matrix.md` C-55/C-56; `plan.md` Slice 3 |

## Consolidated human decision packet

No automated reviewer or terminal agent may answer these. Record the decision-maker's
name, date, selected option, and rationale in the amended artifacts.

1. **HD-01 — OD-1 priority contract.** Choose either public `1|2|3|none` (superseding
   ADR-0006) or retain ADR-0006's `none|low|medium|high`. If numeric is declined, remove
   C-12 from the parity denominator and remove the migration honestly.
2. **HD-02 — Priority labels, conditional on numeric OD-1.** Choose bare digits,
   digit-plus-word labels, or word-only labels over the numeric wire contract.
3. **HD-03 — OD-2 archive membership.** Choose lossless retained membership (superseding
   ADR-0006 B-29) or keep ADR-0006's clearing behavior and re-scope unarchive/design.
4. **HD-04 — Restore after intervening classification changes.** Choose whether restore
   only clears the trash marker and preserves legitimate later List/Tag changes, restores
   the complete pre-trash snapshot, or prevents List/Tag deletion from affecting trashed
   tasks.
5. **HD-05 — Trash retention and permanent erasure.** Choose life-of-account-only,
   bounded automatic purge, user-triggered permanent delete/empty-trash, or both bounded
   purge and user-triggered erasure. State the period if bounded.
6. **HD-06 — Deleted List/Tag name disposition.** Choose immediate erasure, a bounded
   export-visible tombstone (state the period), or a life-of-account tombstone. This choice
   also constrains the content of the mandatory audit record.
7. **HD-07 — Idempotency acceptance scope.** Choose every P0 mutation, all Task lifecycle
   plus List/Tag archive/unarchive/delete, or only the newly introduced trash/restore/
   unarchive/delete commands. Make the scenario, FR-015, SC-009, and test matrix identical.
8. **HD-08 — Priority stage-2 authorization, conditional on numeric OD-1.** Define the
   installation population that must be confirmed (all active installs, a named internal
   cohort, or another explicit population) and the dated build/person evidence that proves
   the gate before stored values and responses switch.
9. **HD-09 — Rendered design authority.** Explicitly accept the numbered state inventory
   as sufficient, or require rendered mockups for D-04, D-05, M-03, and M-04 before review
   approval. The current `Human sign-off: pending` is not acceptance.
10. **HD-10 — High-risk residual-risk sign-off.** After the decisions above and technical
    repairs below change the artifact digest, a named human must decide whether to sign the
    fresh campaign's ADR-0012 `human-signoff.json`. This campaign has no valid sign-off and
    this terminal reviewer cannot supply one.

## Required technical repair after the human decisions

The product decisions are not the only blockers. Before campaign 2, the artifacts must also
resolve every blocking finding above and either resolve or explicitly disposition every
important finding. At minimum:

- make readiness/checklist claims truthful and phase-qualify the priority scenario;
- define restore and trashed-task mutation semantics consistently;
- add the durable, redacted destructive-action audit contract, retention/export
  disposition, FR/SC, task, and evidence;
- remove absolute local paths or commit portable source evidence;
- model the actual SQLite payload plus JSON-mirror storage topology and make delete/
  migration rollback cover both;
- prevent archived-member PATCH rejection and deleted-List resurrection on replay;
- provide archived-List name resolution and complete trashed-exclusion predicates;
- split and own all priority rollout stages and their operational gate;
- enumerate owner isolation, correlation ids, replay, archive visibility, ordering,
  cross-tier evidence, and real-backend mobile evidence;
- correct the mutation-tier claim and dependent `[P]` lanes; and
- add stale-priority UI fallback, literal state copy, and mobile screen-reader behavior.

## Terminal verdict and implementation prohibition

**REVIEW VERDICT: `product-decision-required`.**

Aggregation is decisive: all six reviewers returned `product-decision-required`, product
decisions take precedence over technical changes and unsigned-high-risk escalation, and the
campaign has no missing evidence that would supersede the decision verdict. Risk remains
`high`; no valid human sign-off or founder acceptance exists.

**IMPLEMENTATION IS PROHIBITED. Do not start T-001 or any downstream task. Do not change
production code, tests, configuration, workflows, runtime state, auth, secrets, or
infrastructure from these artifacts.** The task list is planning input, not authorization.
Only a later terminal verdict of `approved` or valid `founder-accepted` may open
implementation.

## Rerun instructions

1. Obtain named human answers to HD-01 through HD-09. Record them in `intake.md`, `spec.md`,
   `design.md`, `plan.md`, and `tasks.md`; write the superseding ADR only for decisions the
   human actually made. Never convert silence into acceptance.
2. Complete the technical repair list and update the requirements checklist truthfully.
   If HD-09 requires renderings, produce and sign off the four named surfaces before review.
3. Run `python3 scripts/check_spec_kit_specs.py` and the feature-qualified requirement/
   traceability checks. Resolve planning-validator failures; production-test coverage is
   expected to remain open until implementation and must not be mislabeled green.
4. Start campaign 2 with a fresh run id (for example
   `011-terminal-20260815-c2`). Carry every campaign-1 finding and its resolution from this
   file into the reviewer prompts so resolved defects are not re-litigated. Do not reuse or
   hand-edit campaign-1 review JSON.
5. Run preflight from the repository root:

   ```bash
   rtk env SPECIFY_FEATURE_DIRECTORY=specs/011-rtm-task-parity \
     python3 scripts/spec_kit_planning_review.py preflight \
     --run-id 011-terminal-20260815-c2
   ```

6. If the repaired package still derives `high`, obtain a real named human sign-off bound
   to campaign 2's run id and freshly computed artifact digest. The record must include
   `approved_by`, `approved_on`, `run_id`, `artifacts_digest`, and substantive `rationale`.
   An agent must not create it on a human's behalf.
7. Through the repository-pinned `speckit-review` skill, fan out all five mandatory lenses
   plus `adversarial-high-risk`, then summarize the same run id. Verify 6/6 ran, no reviews
   are stale/missing/degraded without explanation, and the digest did not drift.
8. Implementation may begin only if campaign 2 ends `approved` or carries a complete,
   unexpired `founder-accepted` record. The hard campaign cap is two; do not invent a third
   clean campaign or fabricate acceptance to escape remaining findings.

---

# Campaign 2: repaired-packet hard-final review

## Campaign metadata

| field | value |
|---|---|
| Review date | 2026-08-15 |
| Campaign | 2 of 2; hard-final campaign |
| Run id | `011-terminal-20260815-c2` |
| Starting commit | `606d13118a52239d45dd142bb9178e9ba0cd9fc4` plus the uncommitted Task-0 repair |
| Reviewed artifacts | `spec.md`, `plan.md`, `design.md`, `tasks.md`, `research.md`, `checklists/requirements.md` |
| Reviewed artifact digest | `cfd324af3ab94ba3648555996c18c0ddb02bc393db22f2abf765902ffba1721e` |
| Declared / derived risk | `medium` / `high` (classifier escalation) |
| Named founder answers carried in | Max, 2026-08-15, HD-01 through HD-09 only |
| Exact-digest human sign-off | absent; no `human-signoff.json` was created |
| Lenses | 6/6: five mandatory lenses plus `adversarial-high-risk` |
| Missing / stale / degraded / unknown-oracle lenses | none / none / none / none |
| Artifact drift after preflight | `false` |
| Panel provenance | Codex `gpt-5.6-sol` ×2; Claude `opus` ×2, `sonnet` ×1, `fable` ×1 |
| Panel correlation | `false`; two providers represented |
| Findings | 8 blocking, 17 important, 7 advisory (32 total) |
| Product decisions | 4 |
| Terminal verdict | `product-decision-required` |

The Task-0 repair recorded Max's HD-01…HD-09 answers and dispositioned every
campaign-1 finding in `research.md`. It also added accepted ADR-0020, corrected the
SQLite-payload/compatibility-mirror plan, made readiness conditional, and supplied the
audit, lifecycle, rollout, evidence, copy, accessibility, export, cache and documentation
ownership requested by campaign 1. This is not HD-10 acceptance: the founder did not
inspect or sign campaign 2's exact run/digest.

The deterministic preflight passed, and the repository aggregator found no artifact drift
or panel-integrity failure. Campaign 2 nevertheless found new blockers. Because this is
the hard-final campaign, every finding below remains open; no reviewed artifact was edited
after preflight and no third campaign is authorized.

## Lens outcomes and complete finding inventory

### 1. Requirements consistency

Verdict: `product-decision-required`; oracle: Codex `gpt-5.6-sol`; 2 blocking,
5 important, 0 advisory; 3 product decisions.

1. **Blocking — Empty Trash audit cardinality.** `spec.md` FR-037 describes one
   Trash-batch receipt, `plan.md` requires a receipt per erased Task, `design.md` promises
   plural receipts, and FR-015/SC-012 do not establish one replay subject and uniqueness
   rule. Decide batch versus per-Task versus both, then align FR-015/037/038, SC-012,
   Story 2 scenario 9, copy, export, T-005 and T-024. Evidence: `spec.md` FR-015,
   FR-037, FR-038 and SC-012; `plan.md` “Trash, restore and classification cleanup”;
   `design.md` D-04/M-04 empty-trash confirmation.
2. **Blocking — start-window behavior.** “Available now” and “starts in the future” do
   not classify undated Tasks, optional floating times, or a later time today. Define a
   complete local-date/time partition and matching cross-tier evidence. Evidence:
   `spec.md` FR-005/FR-025 and Story 3; `plan.md` “Exact query/count predicates”;
   `tasks.md` T-030/T-035.
3. **Important — repeated-filter families.** The universal within-field OR rule is not
   reconciled with T-030's explicit multi-Tag-only work. Enumerate repeatable fields and
   invalid combinations and require field-by-field evidence. Evidence: `spec.md` Story 3,
   FR-025/026; `plan.md` cursor fingerprint; `tasks.md` T-030/T-035.
4. **Important — D-05 traceability.** Web Trash is a separate D-05 screen but is folded
   into the D-04/M-04 state table, making SC-015 evidence ambiguous. Split D-05 or label
   shared D-04/D-05/M-04 rows explicitly. Evidence: `design.md` screen and state
   inventories; `plan.md` summary; `spec.md` SC-015; `tasks.md` T-039.
5. **Important — state copy.** “In Trash · was Next” and “Restored to Next” hard-code
   one of six preserved commitment states and incorrectly imply Trash changed state. Use
   state-aware templates and avoid “was.” Evidence: `spec.md` FR-011/013; `plan.md`
   Trash semantics; `design.md` D-02/M-02 and D-04/M-04.
6. **Important — HTTP classification.** `design.md` classifies a time-without-date
   semantic invariant as 422, while ADR-0006 and FR-016 require sanitized 400; reserve
   422 for malformed shape/type/enum/unknown-field errors. Evidence: `design.md`
   B-01…B-04; `spec.md` FR-016; ADR-0006 error handling; ADR-0020 scope; T-023.
7. **Important — priority verification traffic.** T-018/T-019 can advertise numeric
   capability unconditionally during stage 1 even though FR-006 permits numeric output
   only for an explicitly activated gate journey. Name the verification-only activation
   condition and prove ordinary stage-1 traffic remains legacy. Evidence: `spec.md`
   FR-006; `plan.md` priority stages; `tasks.md` T-017…T-019.

### 2. Architecture consistency

Verdict: `changes-required`; oracle: Claude `opus`; 2 blocking, 5 important,
2 advisory; no product decisions.

1. **Blocking — shipped Tag-delete contract break.** Current
   `DELETE /api/tags/{tag_id}` returns `TagResponse` and both clients type it that way;
   switching directly to `DeletionReceipt` has no version/window/capability strategy.
   Name the break and retain a compatible route/response until installed clients are
   verified. Evidence: `backend/app/api/tasks.py`, task service, both API clients,
   `plan.md` Contracts, T-008/T-011/T-013, Constitution III and
   `docs/api-compatibility.md`.
2. **Blocking — additive payload rollback.** A pre-011 image ignores and then drops new
   JSON keys on write, potentially untrashing Tasks and losing date/time values; only
   priority has a rollback-order rule. Prohibit old-image writes while new keys exist or
   define/test a downgrade rewrite. Evidence: `StorageBaseModel(extra="ignore")`, task
   repository `_payload`/`_upsert_task`, current `TaskDocument`, `plan.md` additive fields
   and priority rollback, T-024.
3. **Important — reconciliation entry point.** Avoiding `_project_result`/`_tag_result`
   inside delete is insufficient: `_serialized_write` reaches `_apply_idempotent_record`
   before command dispatch; `delete_tag:` reconstructs and a new `delete_project:` would
   fall through to Task validation. Route destructive commands to receipt resolution in
   reconciliation and test no recreation/validation error. Evidence: task service
   `_serialized_write`, `_reconcile_idempotent_result`, `_apply_idempotent_record` and
   result helpers; `plan.md`; T-007/T-008.
4. **Important — stale contract documentation.** ADR-0020 reverses the archive clause in
   `docs/projectless-inbox-contract.md`, while `spec.md` still cites that document as an
   authority and T-036 does not own its update. Preserve the Inbox predicate but amend the
   archive clause and explicitly invert the two existing archive-clears-assignment tests.
5. **Important — stale archived-name clients.** Existing mobile resolves names from the
   active-only List query, so archived membership renders unnamed between backend and
   installed-client rollout. Choose a rollout gate, a compatible default response, or an
   explicitly bounded degraded window. Evidence: `plan.md` archived membership and
   priority inventory; mobile `useClassificationNames`; backend `list_projects`;
   T-004/T-013/T-014.
6. **Important — absent exposure control.** The package names no server-owned OFF →
   INTERNAL → ON feature flag despite irreversible erase and breaking query behavior.
   Register and task a managed flag, or document why the repository rule does not apply
   and what replaces it. Evidence: `AGENTS.md`, `.env.example`, ADR-0018, `plan.md` Risk,
   and the absence of a flag task.
7. **Important — incomplete breaking-change procedure.** Strict unknown-query rejection
   and stage-3 legacy-priority rejection lack the required migration date, support window,
   and versioned OpenAPI snapshot before enablement. Evidence:
   `docs/api-compatibility.md`; matrix C-55/C-56; T-022/T-031/T-036.
8. **Advisory — SC-001 bookkeeping.** SC-001 lists C-51/C-54/C-68 as improved PARTIAL
   rows but omits C-35/C-46, which T-004/T-008 also change. Extend the list or state an
   exclusion rule.
9. **Advisory — D-05 label.** Retitle the combined state section D-04/D-05/M-04 or split
   it so the D-05 references in `plan.md`, T-026 and SC-015 resolve.

### 3. Testability and evidence

Verdict: `changes-required`; oracle: Codex `gpt-5.6-sol`; 1 blocking, 1 important,
1 advisory; no product decisions.

1. **Blocking — impossible green baseline.** T-000 asks for current green mobile
   screen-level evidence for Tag management, search, and history that mobile does not yet
   expose and later tasks add. Split current reachable baseline from RED reachability tests
   owned by T-013/T-014/T-034; do not treat low-level transport tests as product evidence.
   Evidence: T-000 and slice dependencies; matrix C-68; mobile `TaskListScreen`, hooks and
   inline-create path.
2. **Important — false parallel lanes.** T-012 consumes T-011, T-014 consumes T-013, and
   T-033/T-034 consume T-030/T-031 as well as T-032. Correct these dependencies or merge
   dependent tasks; retain only independent web/mobile lanes.
3. **Advisory — second priority gate identity.** Stage 3 reuses “a second T-020” rather
   than a separately identifiable, dated evidence task. Give the post-T-021 inventory its
   own checklist/task id and prerequisite.

### 4. Privacy, consent, and security

Verdict: `product-decision-required`; oracle: Claude `opus`; 2 blocking, 1 important,
1 advisory; 1 product decision.

1. **Blocking — earlier-key resurrection.** The plan protects only the delete key, but
   replaying an earlier create/rename/update key after deletion passes through the global
   reconcile hook and recreates the erased row/name/content. Make no-resurrection a
   subject-level rule, consult the durable receipt before every repair, and test earlier-key
   replay for List, Tag, Task and Empty Trash. Evidence: task service `_serialized_write`,
   `_apply_idempotent_record`, result helpers; existing idempotency-repair test; FR-015/020;
   T-005/T-007/T-008/T-024.
2. **Blocking — erased content remains in dedup stores.** Prior idempotency rows and
   `task-commands` mirrors retain full responses for 24 hours, and voice-created Task
   records can be unbounded. This contradicts immediate erasure and SC-012. Decide the
   retention promise; for immediate erasure, redact subject-linked responses atomically
   while preserving dedup identity and scan SQLite/mirrors for zero content occurrences.
   Evidence: task service `_store_idempotency`; repository idempotency schema/save/purge;
   FR-020/023/038, SC-012; D-02/D-05 copy; account export description; `plan.md`
   irreversible-delete sequence.
3. **Important — correlation ID can contain PII.** FR-037 durably exports the inbound
   correlation ID, but middleware accepts arbitrary caller text. Persist only a bounded,
   validated value or a server-generated replacement; test invalid input and document it.
   Evidence: FR-037; API middleware; `plan.md` audit schema; T-005; Constitution I.
4. **Advisory — rollout-evidence hygiene.** The priority evidence path/schema does not
   forbid UDIDs, tokens, account IDs, email, content or personal verifier data. Name a
   repository-relative path and constrain it to build ids, opaque slots, verifier role,
   timestamp and results; extend T-002's fixture hygiene check.

### 5. UX, accessibility, and mobile

Verdict: `changes-required`; oracle: Claude `sonnet`; 0 blocking, 2 important,
1 advisory; no product decisions.

1. **Important — D-05 and unarchive success.** D-05 has no independent state group and
   the combined table lacks List-unarchive success copy/focus behavior. Split or slice-tag
   shared states and add explicit unarchive success copy and focus target. Evidence:
   `design.md` screen/state inventories and restore rows; T-012/T-026.
2. **Important — unbounded Trash states.** Trash is retained indefinitely and paginated,
   yet its state table has no paging/continuation state and Empty Trash has no progress or
   partial-failure/resume state. Add them, or define an explicit size limit. Evidence:
   HD-05, FR-028/038; `design.md` D-01, D-03 and combined Trash table.
3. **Advisory — history-row actions.** State whether trashed rows in the D-01/M-01 history
   filter are read-only links to Trash or expose inline Restore/Delete actions.

### 6. Adversarial high-risk

Verdict: `changes-required`; oracle: Claude `fable`; 1 blocking, 3 important,
2 advisory; no product decisions.

1. **Blocking — erasure/replay conflict.** FR-015's original-response replay guarantee
   conflicts with immediate erasure: older subject-linked dedup records preserve content
   and can resurrect a deleted subject. Scrub/tombstone those rows and mirrors at hard
   delete, define later replay as redacted receipt or 404, carve the exception into FR-015,
   and test earlier-key replay/reconciliation. Evidence: FR-015/020/023/037, SC-012;
   task service reconciliation/result helpers; repository idempotency stores; `plan.md`;
   `analysis.md`; T-005/T-007/T-008/T-010.
2. **Important — durable arbitrary correlation text.** The audit's life-of-account
   correlation field can be unvalidated client content. Require server generation or a
   strict charset/length bound and test it. Evidence: middleware, FR-037, plan audit schema.
3. **Important — non-priority rollback.** Pre-011 images silently drop Trash/date/time
   JSON keys on write. Add a rollback-eligibility prohibition or a tested downgrade step,
   and correct the constitution-check claim. Evidence: `StorageBaseModel`, `TaskDocument`,
   plan additive-field and priority sections.
4. **Important — subtask/comment writes while trashed.** FR-039's write guard and FR-015's
   “exhaustive” mutation inventory omit live subtask/comment commands. Explicitly reject
   them with 400 and cover them in T-024/T-025. Evidence: FR-015/038/039; service command
   routing; matrix C-18.
5. **Advisory — Empty Trash replay subject.** Batch versus per-Task receipts and an
   expired Empty Trash key's behavior against newly trashed Tasks are ambiguous. Define
   receipt shape and whether later reuse is a fresh, re-confirmed execution.
6. **Advisory — representation rewrite exception.** FR-039 says only three operations may
   alter a trashed Task, while FR-006 rewrites every payload. Allow value-preserving
   representation migrations without observable field change.

## Consolidated campaign-2 product decision packet

These questions were produced by the independent panel after Max's HD-01…HD-09 answers.
They are not answered by those earlier choices and no agent may select an option.

1. **C2-HD-01 — Empty Trash durable audit granularity.** Choose one batch receipt per
   Empty Trash operation (reviewer recommendation), one receipt per erased Task, or both.
   This controls retained identifiers, export contents, uniqueness and replay identity.
2. **C2-HD-02 — start-window partition.** Choose: undated or local datetime ≤ now is
   available and later is future (reviewer recommendation); exclude undated Tasks and split
   dated Tasks at local now; or ignore time of day and classify undated/start-date ≤ today
   as available.
3. **C2-HD-03 — repeatable filter families.** Choose: List, Tag, status and priority
   repeat while temporal modes remain singular (reviewer recommendation); every family
   repeats including temporal modes; or only Tag and priority repeat.
4. **C2-HD-04 — content in request-dedup storage after permanent deletion.** Choose:
   immediate erasure by neutralizing all subject-linked dedup copies, with later earlier-key
   replay returning a redacted receipt; a disclosed up-to-24-hour window (and potentially
   longer for frozen voice batches); or immediate erasure for Task/Empty Trash with a
   disclosed bounded window for List/Tag names. This choice changes FR-015/020/023/038,
   SC-012, confirmation copy, export and `docs/data-retention.md`.

## Aggregation, terminal verdict, and residual action

The repository aggregator returned:

- status: `product-decision-required`;
- risk: `high`, classifier-escalated from declared `medium`;
- findings: 8 blocking, 17 important, 7 advisory;
- product decisions: 4;
- panel integrity: 6/6 present, no stale/degraded/unknown-oracle reviews, no artifact
  drift, no single-provider or correlated-panel condition; and
- human sign-off: absent.

The aggregator's architect action is: “Hold implementation and put this decision packet
to the human. These are product decisions; no agent may answer them for them.” The absent
HD-10 exact-digest sign-off is real, but it is not yet the controlling residual: campaign 2
is technically blocked and contains four unresolved product decisions.

**CAMPAIGN-2 TERMINAL VERDICT: `product-decision-required`. IMPLEMENTATION REMAINS
PROHIBITED.** Max must answer C2-HD-01…C2-HD-04 with name, date, selected option and
rationale. The 32 findings must then be resolved or explicitly accepted through a newly
authorized governance path. The ordinary review workflow is exhausted at two campaigns;
there must be no invented campaign 3, no hand-edited review JSON, and no fabricated
`human-signoff.json` or digest-bound founder acceptance. An exact-digest HD-10 sign-off
alone would not override this technical/product-decision verdict.
