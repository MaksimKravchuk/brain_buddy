# Planning review campaign 1 — dispositions

**Run**: `020-weekly-review-c1` (`.specify/workflows/runs/020-weekly-review-c1/`), status
`product-decision-required`, 75 technical findings (2 blocking, 41 important, 32
advisory) and 3 product decisions. **Dispositioned**: 2026-10-06.

Every finding was checked against the repository before it was acted on (file and line
evidence re-read; for example `backend/app/ai/title_completion.py:241-259`,
`ios/BrainBuddyKit/Sources/BrainBuddyCore/Compaction.swift:3-28`,
`backend/app/modules/tasks/repository.py:66-87`, `backend/app/main.py:26-51`,
`frontend/tests/e2e/mobile.spec.ts`, `frontend/src/pages/PrivacyPolicyPage.tsx:176`,
`backend/pyproject.toml:131-148`, `scripts/check_requirement_coverage.py:44`,
`.specify/memory/constitution.md:30,59,61`). No finding was found to be factually wrong,
so none is rejected. Where a reviewer offered alternatives, the choice and its reason
are stated. No owner decision was reversed; the owner's earlier decisions (spec
Clarifications 2026-10-05, research NC-1 – NC-4, design Sign-off 1–6) are intact.

**Totals**: fixed 75 · rejected 0 · needs owner 0 (three owner notes at the end are
for information, not blockers). Product decisions PD-1 – PD-3: applied as answered by the
owner on 2026-10-06.

Abbreviations: FC = contracts/formulation-clock.md, HTTP = contracts/http.md, IOS =
contracts/ios-commands.md, NAV = contracts/navigator.md, DM = data-model.md, QS =
quickstart.md.

## Product decisions (owner answers, 2026-10-06)

| id | question | disposition |
|---|---|---|
| PD-1 | Summary counts for keep waiting / follow-up / return to Next / keep in Someday | Applied: two new counters "Kept as is" and "Moved to Next" (ten in all). spec Clarifications 2026-10-06, FR-033, US4-9; DM E3 `counts`, E4 `review_counts_as` mapping table; HTTP §3 table column and §6; design M-22 (and M-22, D-03 mockups); research "Owner decisions of 2026-10-06" |
| PD-2 | Does skip-everything-then-Done count? | Applied: shown as "Review done" without shame; status `completed_empty`; not counted for SC-001, FR-017, FR-036. FR-029 now defines completed / completed without activity / partial / abandoned and "counted reviews"; US4-8b; SC-001; FR-036, FR-038; DM E3 transitions and regularity instant; HTTP §6 status list; design M-22 "done without any step"; QS 5.4. Planning derivation for consistency: "Last review" (FR-038) uses the same counted-review instant (owner note 1) |
| PD-3 | May auto-park run before the person saw an explanation; when does the grace start? | Applied: new FR-051 one-time auto-park explainer at first app or web open, independent of onboarding; grace from that moment; first acknowledgement on any device wins, stored server-side; account-less on device; no auto-park and no markers before it. FR-014, FR-016, FR-018, FR-035, FR-004, US2-8, edge case "Huge backlog"; Key Entities; design M-26 / D-05 (new HTML), M-01/D-01/M-24 "not activated", M-12 copy and mockups, entry order; HTTP §5 `POST /review/explainer/acknowledge`, `explainer_seen`, `grace_until`; FC §2–§3 activation; DM E2 `activated_at`, E10; IOS §2–§3, §7; R4; plan US2 and slices PR-02 / PR-04 / PR-05 (increment 1); QS Scenario 7 |

## requirements-consistency (18)

| id | sev. | finding | disposition |
|---|---|---|---|
| RC-01 | important | `extend` refused at `park_due` although FR-013/US2-5 rely on it | Fixed: `extend` allowed while in Next at `asks`/`moves_tomorrow`/`park_due` (not applied). FC §3, HTTP §3, FR-009, vectors (FC §6), QS 1.6 |
| RC-02 | important | No client ids in HTTP bodies; offline session/decision mapping undefined; "contracts agree" claim false | Fixed: client-supplied ids (`id`, `decision_id`, `follow_up_task_id`, `new_formulation_id`) adopted by the server (HTTP "Client-supplied ids", §1, §3, §6); offline sessions push with `replace_open: true`; unknown session → session-less decision. IOS §2, §4; DM E3/E4/E7; R7, R16; plan post-design "Contracts" corrected |
| RC-03 | important | Bulk-release undo cannot restore clocks | Fixed: E7 `released[]` keeps `previous_state` and `clock_before`; undo restores exactly; 7-day snapshot purge. DM E7, FC §3, HTTP §6, design M-10, FR-017 |
| RC-04 | important | Prompt "last 4 000 chars" contradicts FR-019; per-model budgets break "same reduced input" | Fixed: one shared `reduce_notes` with a fixed character budget for every model; tokens only a guard; prompt line removed. NAV §1/§3, FR-019, HTTP §7, NC-3 planning refinement note (owner decision unchanged) |
| RC-05 | important | "Asks for a decision" needs the union for queue, widget, SC-002; order undefined | Fixed: `asks_for_decision` aggregate and queue order in FC §5; FR-004 "Counting"; HTTP §5 `counts.asks_for_decision`; IOS §6; design M-16 |
| RC-06 | important | Inbox Undo undefined (web, counts, remainder release) | Fixed: FR-048 rewritten; Inbox Undo = inverse command + `inbox_processed_delta: -1`; web Inbox step designed (D-03); remainder release undo until the step is left (FR-030, M-15). R8, HTTP §3/§6 |
| RC-07 | important | Extension reason not retained in history, contradicting FR-043 | Fixed by keeping the reason in history (the reviewer's alternative; it keeps intake §6 "decisions and reasons stored"): DM E4 `reason_text` for `extend`, exported and purged; FR-043 and Key Entity reworded |
| RC-08 | important | No iOS activation step; pre-activation server clocks make tasks ask on day one | Fixed: activation = explainer acknowledgement (PD-3) with the activation clamp; iOS post-replay activation step keyed on the activation instant. FC §3, IOS §3/§7, R4, DM E2/E10; edge case reworded |
| RC-09 | important | Someday eligibility and order undefined | Fixed: no current receipt, excluding tasks auto-parked in the last 30 days; never-reviewed first, then oldest review. FR-032, HTTP §6 "Queues", IOS §6, design M-20, QS 5.9 |
| RC-10 | advisory | `parked.by = person` contradicts the `someday` row | Fixed: `parked` is written only by auto-park; `by` and `bulk_release_id` dropped; bulk undo uses E7. FC §2–§3, DM E1/E6, HTTP §2, Key Entity, QS 2.2 / 5.6 |
| RC-11 | advisory | Stale lettered-id text; "Two" owner questions | Fixed: R19 rewritten; plan Test strategy and Constitution Check corrected ("Four"; NC-1 changed the contract) |
| RC-12 | advisory | iOS M-03 still offers "Think it through" | Fixed: design M-03 row, affordance map, primary-loop note, M-03 mockup; D-02 gated by `crt_canvas`; plan Inconsistencies item 5 |
| RC-13 | advisory | Restart-mode candidate set mostly empty because auto-park runs first | Fixed (documented): FC §5 note, plan US4, QS 5.6 seeds. Owner note 3 |
| RC-14 | advisory | Web scope of US3-8 (M-08) unstated | Fixed: web offers it only in the full review's projects step; note under design M-08; plan US3 |
| RC-15 | advisory | FR-031 vs M-17 first-run (< 4 weeks) | Fixed: FR-031 defines the < 4-weeks rule; HTTP §6 meta nulls; IOS §6 |
| RC-16 | advisory | SC-004 and supporting metrics have no stored source | Fixed: E3 `active_seconds_by_step`; E6 `returned_at`; due-date moves as a content-free log event; SC-004 wording. R14, plan Observability, `review-metrics` read-out |
| RC-17 | advisory | Spec wording (a)–(e) | Fixed: (a) US4-10; (b) US4-2; (c) US6-2; (d) FR-037 Today widget; (e) FR-019 names `kind`, the detected language is no longer sent (HTTP §7, NAV §1), duplicates checked against all open tasks |
| RC-18 | advisory | Russian non-support stated as fact | Fixed: "not listed; unverified; treated as unsupported" in plan US3, ADR draft §5, R13, Complexity Tracking |

## architecture-consistency (12)

| id | sev. | finding | disposition |
|---|---|---|---|
| AC-01 | **blocking** | Plan/R13 claim title completion fails loudly without a key; it degrades to a disabled provider | Verified (`title_completion.py:241-259`, `container.py:384-392`, no validator at `config.py:475`). Fixed: text corrected; the navigator deliberately differs — `_build_review_navigator_provider` **raises** at container build for `openai` without the key, `deterministic` outside TEST or an unknown provider; only `disabled` yields `available: false` / 503 shown visibly. Reason: constitution I ("fail visibly instead of silently … degrading"); a failed health check never reaches users. R13, HTTP §7, NAV §6, ADR draft §5, plan Consent & Safety / US3 / failure table / Test strategy (first failing test of PR-07), QS 4.0 |
| AC-02 | important | No conflict rules for session/settings review commands; decisions can be set aside | Fixed: `.review` conflict target and a rule per ReviewCommand (merged progress never 409, settings field-level retry, `replace_open`, idempotent finish, session-less decisions). IOS §4, HTTP §5/§6, ReviewSyncTests cases |
| AC-03 | important | Revision semantics of activation/repair writes unstated | Fixed: clock bookkeeping does not bump `revision`/`updated_at`. FC §2, DM E1, ADR draft §3, QS 2.7 |
| AC-04 | important | `client_occurred_at` on PATCH/transitions has no rule | Fixed: removed; only card decisions yield; plain edits replay onto the parked task. HTTP §1, R9, spec edge case, plan failure table |
| AC-05 | important | R4 vs R5: old clocks ask on day one | Fixed: activation clamp. FC §3, R4, R5 |
| AC-06 | important | Stale "FR-046..050 not gate-enforced" text | Fixed: R19, plan Test strategy (same as RC-11, TE-10) |
| AC-07 | advisory | Process-wide lock; sweep wiring must keep the 3-tuple | Fixed: HTTP §9 and R10 (select outside the lock, ≤ 50-task transactions, no I/O under the lock, own try/except, return shape unchanged); plan repo trace and test row |
| AC-08 | advisory | One vs three routers | Fixed: three routers, all mounted by PR-02. HTTP header, R1, plan structure and slices |
| AC-09 | advisory | Import-linter does not cover the review modules | Fixed: PR-02 extends the forbidden and layers contracts (`backend/pyproject.toml` in PR-02 paths; plan repo trace) |
| AC-10 | advisory | Drifted citations | Fixed: `_to_response` l.1183, limiter l.257, `research-on-device-model.md` exists, Swift switch list replaced by "the compiler enumerates them" (IOS §2), ADR-0021 cited by file name (R12) |
| AC-11 | advisory | Russian wording | Fixed (as RC-18) |
| AC-12 | advisory | Account-less device lacks the sweep's retention duties | Fixed: `runLocalReviewMaintenance()` (IOS §5); DM E10; R15 |

## testability-evidence (10)

| id | sev. | finding | disposition |
|---|---|---|---|
| TE-01 | important | SC-001/003/004 have no read-out; SC-004 unmeasurable; SC-002/006 cases missing | Fixed: `python -m app.cli review-metrics` with `test_review_metrics_readout.py`; E3 active time; explicit SC-002 (flow) and SC-006 (sweep) cases; PR-14 records the read-out. Plan Test strategy, DM E3 |
| TE-02 | important | App/widget-target outcomes only "compile" | Fixed: Core pure functions (`ReviewReminderPlanner`, `ReviewRoute`/`ReviewEntryPlanner`, `ModelDownloadMachine`, `MarkerStyle`) with Swift tests; remaining glue as recorded manual evidence labelled manual. IOS §6, plan Test strategy |
| TE-03 | important | Playwright relies on an undefined sweep endpoint; no clock seam | Fixed: injected clock + `frozen_clock`; TEST-only `app.cli` seed and sweep commands; no test HTTP route. R21, plan Test strategy and PR-02 paths, QS prerequisites |
| TE-04 | important | Vector guard not live at PR-02; transitions placeholder; web "ageing" unruled | Fixed: PR-02 lands copies; drift test fails on missing copies; `check-specs` byte check in PR-14; transitions schema defined; `ageing_at` in the response and `classifyFromInstants` run against vectors. FC header, §6; HTTP §2 |
| TE-05 | important | Review-flow rules and wire shapes duplicated without shared evidence | Fixed: `review_flow_vectors.json` and golden wire fixtures, copied with the same guard. Plan Test strategy and PR-02 paths |
| TE-06 | important | Slice graph over-serialised (PR-11 behind PR-07) | Fixed: router mounts/wiring in PR-02; PR-07 and PR-11 siblings; lanes stated. PR-03 keeps a merge dependency on PR-02 only for the fixture copies (can be developed in parallel). Plan Delivery slices and write-path notes |
| TE-07 | important | SC-005 evaluation only in late PR-09; no PR-09 test row | Fixed: eval fixture, runner and format in PR-07; evaluation matrix by source/language; flag stages gated per source in PR-14; PR-09 `ModelDownloadMachineTests` row. NAV §5, plan |
| TE-08 | advisory | Mac tests have no CI lane | Fixed: PR-06 evidence is a recorded macOS-host run; FR-041 test scoped to the row; US6-1 unverified until Mac sync. Plan Test strategy, QS Scenario 6 |
| TE-09 | advisory | "Never" requirements checked only by eye | Fixed: Vitest string/token guard; Core `MarkerStyle` test. Plan Test strategy, IOS §6, QS 5.8 |
| TE-10 | advisory | Stale id text; PR-01 misses `test_check_requirement_coverage.py` | Fixed: R19, plan; added to PR-01 paths with a Swift-naming test |

## privacy-consent-security (10)

| id | sev. | finding | disposition |
|---|---|---|---|
| PC-01 | important | Retention steps stop when the flag is off | Fixed: sweep split; retention runs for every owner with review rows. HTTP §9, R15, DM E4/E7/E9, FR-043, plan rollback, QS 2.9 |
| PC-02 | important | No content-free rule for rollout evidence | Fixed: plan "Evidence rule", PR-14 `evidence/README.md`, numbers-only real-use results, QS prerequisites |
| PC-03 | important | Batch endpoints may leak existence across owners | Fixed: body task ids never 404; unknown and foreign are identical (`not_eligible` / ignored). HTTP "Ownership", §6; `second_api_client` test; QS privacy read-back |
| PC-04 | important | Privacy policy / data-retention not in navigator and model slices | Fixed: PR-07 and PR-09 paths (PR-07 class adds privacy disclosure); iOS store and web-draft rows in PR-02 (avoids sibling write-path overlap). Plan slices, DM E10/E11 |
| PC-05 | advisory | `language_hint` not in the consent list | Fixed by dropping it from the cloud request (FR-019, HTTP §7, NAV §1/§3); consent copy stays accurate |
| PC-06 | advisory | Stall reason in per-request logs | Fixed: never logged; distribution from `review_decisions`; sentinel test asserts it. HTTP Logs, R14, plan Observability |
| PC-07 | advisory | Device-local snapshots unbounded | Fixed: local 7-day maintenance; iOS store row extended in PR-02. IOS §5, DM E10, R15 |
| PC-08 | advisory | Consent version not enforced; cross-device revoke window unstated | Fixed: older `consent_text_version` counts as absent; `consent_text_outdated`; offline copy names the window; web switch pending until DELETE. HTTP §7, DM E8, R13, FR-024, design M-07/M-23/D-04 |
| PC-09 | advisory | Due-date-move counter storage unstated | Fixed: content-free log event, no persisted counter. R14, plan Observability |
| PC-10 | advisory | Cloud route visible only after the request starts | Fixed: route caption on Suggest before the tap. NAV §4, design M-04/M-08 rows and affordance map |

## ux-accessibility-mobile (16)

| id | sev. | finding | disposition |
|---|---|---|---|
| UX-01 | **blocking** | Unsaved typed text discarded without warning (Principle V) | Verified (design M-04/D-02/plan rows; constitution lines 59, 61). Fixed: new **FR-052**; design "unsaved text — leave?" (Keep editing default / Discard), "draft restored", M-13 "leave with unsaved text", M-05 answer, M-14 line, M-18/M-20 titles, D-02/D-03 rows; iOS blocks interactive dismissal (`interactiveDismissDisabled`), web `beforeunload`; local drafts on iOS (`local.formDrafts`) and web (`localStorage`, E11) keyed by task and formulation, 7-day expiry. IOS §7, DM E10/E11, R18, R22, plan US1/failure table/PR-04/PR-05, QS 1.10 |
| UX-02 | important | Restart Undo lost on app kill | Fixed: interruption is not leaving; M-10 "released, resumed after interruption"; FR-017; design Resolved 4 clarified (owner default kept). Owner note 2 |
| UX-03 | important | No 390 px web layouts | Fixed: "narrow (390 px)" states for D-01 – D-05; Playwright overflow checks; E2E-MOBILE-02 plan. Design Applicability, Mobile viability, plan US5 / Test strategy, QS 5.10 |
| UX-04 | important | Web step actions lack saving/error states | Fixed: D-03 "step action saving / failed", "skip not saved", inline-card rows |
| UX-05 | important | Web Inbox step undesigned | Fixed: D-03 "Inbox step" rows (over 15, one at a time, Undo, saving/failed, partial, done/empty) |
| UX-06 | important | Web WYWA dialog at app open undesigned | Fixed: D-01 "While you were away (dialog at app open)" and its returning/failed/partial/offline rows |
| UX-07 | important | Missing focus targets, traps and Esc rules | Fixed: design "Keyboard and focus" (traps, onboarding, Leave confirm, consent focus return, inline card Esc, VoiceOver step/item focus) |
| UX-08 | important | Undo unreachable in time by keyboard/VoiceOver | Fixed: Ctrl/Cmd+Z while visible, named in the accessible description; iOS announcement and ≥ 10 s under VoiceOver/Switch Control. Design M-03/M-16/D-02/D-03 and Keyboard section; FR-048 |
| UX-09 | important | No "review ended / moved on elsewhere" states | Fixed: M-13 and D-03 rows; M-11 "offline review replaced another"; HTTP §6 merge rules; spec edge case |
| UX-10 | important | No "notes shortened" state; generic error copy | Fixed: M-05/M-07/D-02 "notes shortened", "input too large", M-03/D-02 "decision not allowed"; copy in HTTP §3/§7 |
| UX-11 | important | Undo failures have no copy | Fixed: "undo didn't apply" on M-03, M-16, M-18, M-20, D-02, D-03; M-10 "undone, some skipped"; M-03 error routed to Sync issues |
| UX-12 | important | Navigator interruption unspecified | Fixed: "interrupted" rows on M-05, M-07, M-08; NAV §4 |
| UX-13 | advisory | Widget deep link skips the entry order | Fixed: M-24 in the entry order; "chip tapped" lists M-26, M-12, M-09, M-10 before M-16; `ReviewEntryPlanner` |
| UX-14 | advisory | No Undo for the Inbox-remainder release | Fixed: M-15 "done (with release)" Undo until the step is left; FR-030 |
| UX-15 | advisory | Keys 1–7 undefined in text fields / with six decisions | Fixed: inactive in text fields; numerals shown. Design D-02 and Keyboard section |
| UX-16 | advisory | M-09 swipe-down meaning | Fixed: not acknowledged; shown again at most once a day; same rule on the web dialog |

## adversarial-high-risk (9)

| id | sev. | finding | disposition |
|---|---|---|---|
| AH-01 | important | Account-less compaction folds title/moves into creation → early parks | Verified (`Compaction.swift:3-28`). Fixed: clock-aware compaction (no fold of title changes or moves into an unsent create once exposed); post-replay activation step; compacted-vs-uncompacted test. IOS §3, plan tests, QS 3.5–3.6 |
| AH-02 | important | No clock snapshot for yield and bulk undo; yield rejects pre-park `extend` | Fixed: `parked.clock_before`; yield restores it without re-closing; `extend` allowed at `park_due`; E7 snapshots; vectors. FC §2–§3, HTTP §3, DM E1/E7, QS 2.6 |
| AH-03 | important | Yield via `client_occurred_at` would un-park on a notes edit | Fixed (as AC-04) |
| AH-04 | important | Flag re-enable with no grace; retention stops while off | Fixed: sweep-gap floor (now + 7 d after a gap ≥ 24 h, `last_effective_sweep_at`); retention part for all owners. FC §3, HTTP §9, DM E2, ADR draft §3, QS 2.9 |
| AH-05 | important | Offline sessions and locally started formulations lose decisions | Fixed (as RC-02 / AC-02): client ids incl. `new_formulation_id` on create/PATCH/transition/decision; `replace_open`; session-less decisions |
| AH-06 | advisory | Undo deletes an edited follow-up | Fixed: `created_task_revision` precondition. DM E4, HTTP §3, R8, QS 1.8 |
| AH-07 | advisory | No kill switch for account-less parks | Fixed: `BBWeeklyReviewLocal` NO in Release until the synced path is clean (owner records the switch at PR-14); ≤ 10 device parks per call, then M-09. IOS §5/§8, plan rollback, ADR draft risks |
| AH-08 | advisory | Prefix spelling; plan tree note; consent version | Fixed: one prefix list with reconstructors (HTTP §9, R7); tree note; consent version (as PC-08) |
| AH-09 | advisory | Time-zone change shortens the 24 h marker | Fixed: zone change applies the FR-046 7-day floor to due-dated Next tasks. FC §3, R11, HTTP §5, QS 2.10 |

## Owner notes (information, not blockers)

1. **"Last review" after a skip-everything review (PD-2).** The owner's answer named
   regularity, restart mode and notifications. For one consistent rule, planning also
   bases "Last review" (FR-038) on counted reviews, so it does not move after a
   `completed_empty` review. The owner may prefer "Last review" to move; that would be a
   one-line change to FR-038 and DM E3.
2. **Restart Undo after an interruption (UX-02).** Design Resolved 4 (owner default) says
   Undo lasts "until the person leaves the restart screen". Planning reads an app kill,
   backgrounding or a tab reload as not leaving, so Undo survives them. This is within
   the owner's wording; flagged in case the owner meant otherwise.
3. **What restart mode is for in practice (RC-13).** With auto-park at T + 7 ≤ 35 days,
   the 4-week release mostly finds tasks held in Next by an extension, a floor or an
   ended due-date pause. Documented in FC §5; the owner may want to confirm this is the
   intended scope.
