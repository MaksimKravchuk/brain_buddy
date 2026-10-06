# Planning review campaign 2 — dispositions

**Run**: `020-weekly-review-c2` (`.specify/workflows/runs/020-weekly-review-c2/`), the
last allowed campaign; status `technical-changes-required`, 65 technical findings
(0 blocking, 29 important, 36 advisory) and 0 product decisions. **Dispositioned**:
2026-10-06.

Every finding was checked against the repository before it was acted on. Evidence
re-read for this campaign includes `docs/decisions/0001-vnext-modular-monolith-and-workflow-contracts.md:85-86`
(rule 9), `backend/app/ai/title_completion.py`, `backend/app/api/tasks.py:141-208, 956-973, 1183`,
`backend/app/api/dependencies.py:361-385` (voice "exposure control is not
authorization"), `backend/app/schemas/tasks.py:49, 99-122`, `backend/app/schemas/common.py:20`
(`extra="ignore"`), `backend/app/modules/tasks/service.py:64-79` (`_serialized_write`
bound to `TaskService`), `backend/app/modules/tasks/repository.py:39, 67-87`
(`IDEMPOTENCY_RETENTION`, process-wide `RLock`), `backend/app/services/feature_flag_service.py:145`
(`is_effective(name, user)`), `backend/app/utils/identifiers.py:11-14`,
`ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine+Push.swift:124-171, 270-291`
(404 → set aside; refetch + replay), `ios/BrainBuddyKit/Sources/BrainBuddySync/PushPlanner.swift:131-140`,
`ios/BrainBuddyKit/Sources/BrainBuddyAPI/WireModels.swift:227-248` (hand-written
`init(from:)`), `ios/README.md:340-341`, `docs/test-allure-taxonomy.md` (no Swift
lane), `scripts/check_spec_kit_specs.py:217-235`, `scripts/check_requirement_coverage.py:181-192`,
`frontend/package.json:31` (`@axe-core/playwright`), `frontend/src/App.tsx:24`
(declarative `BrowserRouter`, so no `useBlocker`), `frontend/src/pages/PrivacyPolicyPage.tsx:180`,
`docs/e2e-acceptance-charter.md:331-343`, `.specify/memory/constitution.md:51`. Every
finding's facts held, so **none is rejected**. Where a reviewer offered alternatives,
the choice and its reason are stated. **No owner decision was reversed**: spec
Clarifications 2026-10-05 and 2026-10-06, research "Owner decisions" (NC-1 – NC-4,
PD-1 – PD-3) and design Sign-off 1–6 are intact. **No new requirement** was needed (no
FR-053+); every spec change sharpens an existing requirement.

**Totals**: fixed 65 · rejected 0 · needs owner 0 · already resolved in c1 0. Six
owner notes at the end are for information or confirmation at the already scheduled
`/speckit-tasks` gate; none blocks.

**Campaign 1 cross-check**: seven c2 findings touch something c1 dispositioned. In each
case the c1 fix was verified in the artifacts; none was fully in place, so each is
counted as fixed now, not as "already resolved":

| c2 | c1 | what c1 landed | what was missing, now fixed |
|---|---|---|---|
| RC-02 | RC-17(e) | spec FR-019 "including open tasks beyond the 20 titles sent" | no contract mechanism (validator and server see ≤ 20 titles) |
| RC-09 | RC-14 | design note under M-08, plan US3 | spec Out of Scope |
| RC-15 (1) | UX-16 | design M-09 / D-01 once-a-day rule | spec FR-015 |
| TE-08 | TE-04 | `check-specs` byte check in PR-14 (FC §6) | R19 still said "when increment 1 lands" for the coverage line |
| PC-01 | RC-02 | client-supplied ids in the contracts | unconstrained shape; wrong precedent citation (`schemas/tasks.py:122` is `SmartAddClassificationRef.id`) |
| AH-05 | AC-01 | startup raise without the key | blast radius on a serving restart: runbook added, the raise kept |
| UX-13 | UX-14 | Undo for the Inbox-remainder release | interruption rule (restart had it, the Inbox step did not) |

Abbreviations: FC = contracts/formulation-clock.md, HTTP = contracts/http.md, IOS =
contracts/ios-commands.md, NAV = contracts/navigator.md, DM = data-model.md, QS =
quickstart.md, ADR = adr-draft.md.

## requirements-consistency (16)

| id | sev. | finding | disposition |
|---|---|---|---|
| RC-01 | important | FR-029 / US4-8/8a say leaving makes a review partial or abandoned; design and E3 make "Leave" a pause | Fixed by aligning the spec with the signed-off design (M-13 "Leave for now" pauses): FR-029 "leaving only pauses; partial / abandoned only by replacement or the 7-day idle close; an open review with qualifying activity already counts"; US4-8, US4-8a. The unused `finish {outcome: left}` is removed: HTTP §6 finish = Done only; DM E3 transitions; IOS §2. QS 5.4; plan US4 and flow test row |
| RC-02 | important | FR-019 "no duplicates beyond the 20 titles sent" has no mechanism | Fixed (c1 RC-17(e) had changed only the spec): NAV §2 rule 5 — every client drops proposals matching **any** open task of the project it holds (iOS local store, `NavigatorProposalFilter`; web `GET /tasks?project_id=…`, all pages); HTTP §7; IOS §6; shared vector with the duplicate as the 21st title; QS 4.10. No project id added to the request, so the FR-019 data list and the consent text are unchanged |
| RC-03 | important | FR-005 vs the extension-aware close rule resets the stalled count | Fixed with the literal reading: FR-005 now defines "reached" as asking at close or having been extended (only possible while asking); FC §3 "Closing a formulation"; FC §6 vector "extend then reformulate before the extended ask"; QS 1.6. Owner note 3 |
| RC-04 | important | SC-007 "summary visible on web" has no web surface | Fixed by adding the surface (not by narrowing SC-007): design D-03 "entry: last review summary"; HTTP §5 `last_counted_review`; plan US4 web, Playwright case naming `020-SC-007`; QS 3.3 |
| RC-05 | important | Restart anchor for a never-reviewed person undefined | Fixed as recommended: FR-017 and US2-7 (21 days from onboarding when there is no counted review; no restart before onboarding); DM E3; HTTP §5 `restart_mode` formula; flow vectors; plan flow test; QS 5.6 |
| RC-06 | important | SC-002 vs a cosmetic "Save anyway" | Fixed: FR-002 — a cosmetic save is a recorded reformulate decision, the card moves on, the task keeps asking; SC-002 counts a recorded decision on the current formulation; HTTP §3 `reformulate` row; design M-16 "all decided, one kept its wording" (the "Nothing … waiting" line only when none still asks); plan SC-002 test reworded |
| RC-07 | important | Account-less Release exposure not in the spec | Fixed: spec edge case "Account-less iOS use" records the staged exposure (own release switch, off in released builds until the owner turns it on at PR-14; acceptance in development builds and package tests meanwhile); FR-042 keeps the deferred entry until then; IOS §8; plan rollback. Owner note 1 (confirm at `/speckit-tasks`) |
| RC-08 | advisory | US2 independence vs delivery order; unconditional Mac wording | Fixed: US2 Independent Test names scenarios 3 (review part) and 7 as verified with US4; FR-022 and US3 qualified "once Mac sync exists (FR-041)"; plan increment note |
| RC-09 | advisory | Web limitation of US3-8 not in the spec | Fixed (c1 RC-14 landed in design and plan only): spec Out of Scope; plan US3 and PR-13 (web US3-8 verifies at PR-13) |
| RC-10 | advisory | Plan cites M-01 – M-25, D-01 – D-04, 29 screens | Fixed: plan header (M-01 – M-26, D-01 – D-06, 32 screens; what was signed off on 2026-10-05 vs amended on 2026-10-06) and Scale/Scope |
| RC-11 | advisory | Marker table "≥ T+7 after extension" contradicts NC-1 | Fixed: design marker table "after an extension, from 7 days after the extension day" |
| RC-12 | advisory | "Oldest first" vs earliest-asking order | Fixed: US4-3, design M-16 (inventory and row), FC §5 label, and the M-16, D-03 and M-24 mockups now say "earliest-asking first" |
| RC-13 | advisory | FR-025 "existing cost caps" vs new navigator caps | Fixed: FR-025 and Assumptions ("cost caps following the existing admission pattern, with navigator-specific limits"); ADR §5 |
| RC-14 | advisory | Person-released tasks reappear in the Someday step | Fixed with exclusion by analogy to the auto-park rule: FR-032 and the Review receipt entity; every person release writes a 30-day `source: release` Someday receipt (DM E5; HTTP §3 `someday`, §6 bulk release and undo; FC §3); QS 5.9. Owner note 2 |
| RC-15 | advisory | FR-015 lacks the once-a-day rule; parked-decision copy says "still in Next" | Fixed: FR-015 (c1 UX-16 had it in design only); IOS §4 copy names the task's current list, with a "moved to Someday automatically" variant; design M-03 "error" and new "parked before the decision synced" rows; M-03 mockup copy |
| RC-16 | advisory | Model clarifying question on a project has no destination | Fixed by reusing the signed-off M-08 empty-project pattern: FR-021 (for a project the answer field is the next action itself; nothing stored, no re-run); NAV §2 rule 4; design M-08 "model question"; plan US3 |

## architecture-consistency (8)

| id | sev. | finding | disposition |
|---|---|---|---|
| AC-01 | important | OpenAI adapter inside the Tasks module against ADR-0001 rule 9 | Fixed with the reviewer's first option (no ADR-0001 amendment needed): adapter `backend/app/ai/review_navigator.py` beside `title_completion.py`, built by `container.py`, injected through a `NavigatorProvider` port; `modules/tasks/navigator.py` keeps schema, `reduce_notes`, validation and consent rules; import-linter forbids HTTP clients in `app.modules.tasks`. HTTP §7, NAV §3, R13, ADR §5 and Consequences, plan trace / structure / US3 / PR-07 paths / tests |
| AC-02 | important | Navigator cost admission vs the process-wide lock unstated | Fixed: HTTP §7 "Cost admission and the task lock" (reserve under the lock → call with no lock → settle or release), DM E9 `reserved_cost_usd`, R13; plan failure row; pytest case with a provider stub that takes the lock for another owner; QS 4.8 |
| AC-03 | important | Session wire shape and `acknowledgeExplainer` wording disagree | Fixed: HTTP §6 lists the exact `SessionResponse` fields and the server-internal ones (`set_aside_task_ids` → `set_aside_count`, `decision_queue`, `finished_empty`); DM E3 "Wire subset"; IOS §2 (the command writes only the activation instant; clocks change in the post-replay activation step) |
| AC-04 | advisory | Layer for derived instants and the response mapper unstated | Fixed: pure `formulation.derive_instants`, one settings read per request in `TaskService.formulation_views`, public mapper `backend/app/api/task_mapping.py` shared by both routers (HTTP §2, DM E1, plan trace, structure, US1, PR-02 paths) |
| AC-05 | advisory | `_serialized_write` is bound to `TaskService` | Fixed: generalised `SerializedWriter` protocol; `ReviewService` composes `TaskService` (undecorated helpers inside its own write) and owns its reconciler for the new prefixes; layers `review_service → service → repository` (HTTP §9, R7) |
| AC-06 | advisory | Sweep "one indexed query" overstated | Fixed: HTTP §9 "Scan cost, stated honestly" (O(Next tasks) per minute; optional per-owner watermark), R10, plan Performance Goals |
| AC-07 | advisory | Code rollback suspends the 7-day bound | Fixed: HTTP §8 "Retention pauses", R15 "Limit", plan rollback; data-retention wording specified |
| AC-08 | advisory | Three factual nits | Fixed all three: HTTP §1 (hand-written `init(from:)`, `WireModels.swift:227-248`); plan Testing cites `ios/README.md:340-341` and says the taxonomy doc covers only the three runners; R10 and HTTP §9 resolve a `User` per owner for `is_effective(name, user)` |

## testability-evidence (12)

| id | sev. | finding | disposition |
|---|---|---|---|
| TE-01 | important | SC-004 client accumulator untested | Fixed: Core `ActiveTimeAccumulator` and web `activeTime.ts` with injected clocks, checked against the shared `active_time` vectors (IOS §6, DM E3, plan structure and Swift/Vitest rows naming `020-SC-004`) |
| TE-02 | important | SC-005 real-use denominator missing | Fixed: denominator = server requests that showed proposals (`navigator_usage.shown`, DM E9); numerator from `ai_use` with a server `request_id`; on-device reported separately as an upper bound (NAV §5); read-out test with an abandoned request; plan Observability |
| TE-03 | important | FR-007 / US1-6 mapping untested | Fixed: one table — Core `StallReasonRecommendation` and web `stallRecommendation.ts` — checked against the `stall_recommendation` vectors; tests for each reason, all decisions enabled, clearing the reason (IOS §6, plan US1 and tests). The mapping is the owner-accepted M-03 one |
| TE-04 | important | US5-6 guarded only on the web | Fixed: Core `ReviewCopy` catalog (restart, summary, notification, widget, M-02, WYWA, explainer) with a Linux banned-term test (IOS §6, plan US5 and Swift row); QS 5.8 corrected |
| TE-05 | important | Offline / two-device parity proven only against the fake server | Fixed: golden operation traces (`backend/tests/fixtures/review_traces/`) verified by pytest against the real API and replayed against `BrainBuddyFakeServer` (plan structure, `test_review_traces.py` row, Swift row, slice notes); QS 3a. Chosen over a live-backend CI job because it needs no compose-stack lane and drift fails in both runners |
| TE-06 | important | Shared-fixture ownership incoherent | Fixed with option (b): PR-02 executes every flow-vector section against the pure `review_rules.py`, which PR-11 then builds on; change protocol for later vector edits (FC §6 "Changing a vector after PR-02", plan Test strategy) |
| TE-07 | important | Slice vs post-release acceptance not separated | Fixed: plan "Slice acceptance vs post-release acceptance" (owner, window, weekly read-out procedure, numbers-only record, minimum samples, flag stages); QS "Real-use read-out". Owner note 4 (numbers proposed) |
| TE-08 | advisory | Coverage gate gives no per-slice assurance; R19 vs PR-14 | Fixed: one landing point (PR-14) in R19, plan and QS; PR-01 adds a `--requirements` filter used per slice; FR-041 needs the recorded macOS-host run file too |
| TE-09 | advisory | WYWA once-a-day rule has no storage or test | Fixed: FR-015; DM E10 `wywaLastShownDay`, E11 web key; Core `WhileAwayPresentation` and web `wywaPresentation.ts` with tests; QS 2.4 |
| TE-10 | advisory | No axe scan; app-target items without evidence | Fixed: Playwright axe scans of D-01 (with WYWA), D-02 – D-06 at desktop and 390 px; Core `UndoWindowPolicy`; manual iOS evidence list extended (FR-048 announcement, FR-034, 44 pt targets, FR-042, VoiceOver focus) |
| TE-11 | advisory | PR-02 is one large serial root | Fixed as a binding rule for `/speckit-tasks` (tasks.md does not exist yet): split PR-02 into a behaviour-neutral seam / rules / vectors slice and the behaviour slice (plan Delivery slices) |
| TE-12 | advisory | Slice path hygiene | Fixed as binding rules for `/speckit-tasks`: file-level paths only, own test files per slice, single owners for the Allure taxonomy files and coverage floors (floors only in PR-14, now in its paths), `Package.swift` in PR-03 (plan Delivery slices, structure) |

## privacy-consent-security (6)

| id | sev. | finding | disposition |
|---|---|---|---|
| PC-01 | important | Free-form 500-char client ids logged and exported; wrong precedent | Fixed: fixed-shape ids `<prefix>_<uuid>` ≤ 64 chars (422 otherwise), references accept that or a server-minted id; `navigator_request_id` exactly the server's 36-char UUID; ids are labels only — the Idempotency-Key is the only replay input, a reused id under another key → 409 `id_conflict` (constitution IV, line 51); session "replay by id" removed; precedent citation corrected (HTTP "Client-supplied ids" and §6, DM E4, IOS §1–§2, R7); pytest sentinel-id case; QS privacy read-back |
| PC-02 | important | Flag gate makes stored consent unrevocable while off | Fixed with the voice precedent: `GET /review/navigator` and `DELETE /review/navigator/consent` are never gated (HTTP "Gate"); FR-024 "also while the feature is switched off"; design M-23 / D-04 "feature switched off, consent stored"; ADR §5; pytest case (flag-off revoke → 204, then flag-on suggestion → 400); QS 4.9 |
| PC-03 | advisory | Idempotency rule for the suggestions endpoint unstated | Fixed: no Idempotency-Key, no `_serialized_write`, no idempotency record or `task-commands/` entry; only usage counters and one log line (HTTP "Mutations" and §7, NAV §6); test |
| PC-04 | advisory | Exception text in sweep logs | Fixed: `type(exc).__name__` + reason code only, never `str(exc)` / `errors()` (HTTP "Logs" and §9, R14, plan failure row); log-capture test over an invalid payload with a sentinel |
| PC-05 | advisory | Processor-side retention and time zone not disclosed | Fixed: DM "Export and purge" row for provider-held navigator input (survives purge by design; 30 days for OpenAI) and the time-zone note; NAV §6; PR-07 and PR-02 rows. The consent copy may add one line (left to PR-07; no signed-off copy changed) |
| PC-06 | advisory | Query-parameter `session_id` not covered by the ownership rule | Fixed: HTTP "Ownership" and §6 queues (same 404 for unknown and foreign); `second_api_client` case; QS privacy read-back |

## ux-accessibility-mobile (15)

| id | sev. | finding | disposition |
|---|---|---|---|
| UX-01 | important | Web restart / Inbox-release / WYWA-in-review requests lack pending and failure states | Fixed: D-03 "restart: releasing / release failed / undoing / undo failed", "Inbox step: releasing / release failed / undo of the release failed", D-01 WYWA rows declared to apply inside D-03; D-01 and D-03 "WYWA: continue not saved" |
| UX-02 | important | No per-step loading / error on the web | Fixed: D-03 "step loading" and "step load failed"; the D-03 "empty / partial" row updated; Vitest cases |
| UX-03 | important | Cloud clarifying question undesigned | Fixed: M-07 "clarifying question (cloud)"; D-02 "clarifying question", "adding answer", "answer not saved", "answer saved, suggestion failed", "answer saved, card current" (the card adopts its own notes edit's revision) |
| UX-04 | important | Model download lifecycle after leaving the card | Fixed: M-06 "download resumed after reopen", "download finished while away", "download cancelled"; M-23 "model downloading", "download interrupted"; DM E10 `interrupted` state; PR-09 and `ModelDownloadMachineTests` cases |
| UX-05 | important | Browser Back / in-app navigation not covered | Fixed: D-02 and D-03 "browser Back / route change", Keyboard section; plan web history guard (`popstate`; `useBlocker` is unavailable with the declarative `BrowserRouter`, `frontend/src/App.tsx:24`); Vitest and Playwright cases; QS 5.11 |
| UX-06 | important | Web "This wording" block has no D- id | Fixed: new **D-06** with inventory row, state table, keyboard rules and affordance-map rows; no separate mockup (M-02 content), stated in the Files table; plan US1 and PR-05 (`FormulationBlock.tsx`) |
| UX-07 | important | iOS VoiceOver focus for screens shown without a tap | Fixed: design "Keyboard and focus" (M-26, M-09, M-10, M-11, M-12 headings; focus after dismissal; after M-06 / M-07); plan US2–US4; manual evidence item |
| UX-08 | advisory | Controls missing from the affordance map | Fixed: "Open the review", the Next note "1 decision couldn't be saved", Retry rows (D-02, D-05 and the new failure rows), "Suggest again", the M-23 download controls, D-06 rows |
| UX-09 | advisory | Plan screen citation stale | Fixed (same edit as RC-10) |
| UX-10 | advisory | Disabled offline markers drop out of the tab order; sidebar recap states | Fixed: D-01 offline row (`aria-disabled`, focusable, opens D-02 offline); D-01 "sidebar recap: loading / failed" and "never reviewed" |
| UX-11 | advisory | 390 px reflow and Playwright scope | Fixed: D-03 narrow row (stacked Waiting buttons, 2-column summary grid); Mobile viability and the Playwright row extended to `/tasks/next`, settings and D-05 |
| UX-12 | advisory | No keyboard-only Playwright story | Fixed: plan Playwright row (E2E-A11Y-01 story as recommended) |
| UX-13 | advisory | Inbox-release Undo after an interruption | Fixed: FR-030 (as FR-017); design M-15 "done (with release), resumed after interruption"; D-03 Inbox row |
| UX-14 | advisory | No state for a review closed after 7 idle days | Fixed: M-11 "earlier review closed after a week", M-13 "review closed after a week", D-03 rows; plan failure row |
| UX-15 | advisory | Conflicting Esc rules on the inline card | Fixed: D-03 "step with rail" and Keyboard "Escape" (unsaved-text confirmation first, then return to the card; Esc on the card itself does nothing; never closes the review) |

## adversarial-high-risk (8)

| id | sev. | finding | disposition |
|---|---|---|---|
| AH-01 | important | Yield precondition defeated by queued plain edits | Fixed with the formulation-based precondition (`parked.from_revision ≤ expected_revision ≤ task.revision`, same formulation, decided before `parked.at`): HTTP §3, R9, IOS §4, ADR §3, plan US2 and failure rows; pytest and `ReviewSyncTests` case (notes kept, decision applied, 0 sync issues); QS 2.6. M-03 error copy now names the current list |
| AH-02 | important | Flag-OFF rollback sets aside queued iOS review commands | Fixed with the reviewer's preferred rule: the flag gates exposure only; writes that finish started work are accepted (auto-park answers `applied: false`), privacy routes never gated (HTTP "Gate"); defence in depth: iOS maps 404 `weekly_review_disabled` to a back-off kind (IOS §4); plan rollback and failure rows, ADR §6; tests; QS rollout read-back |
| AH-03 | important | Deterministic auto-park key collides with 24 h idempotency retention | Fixed: key `auto-park:<task>:<formulation>:<from_revision>`; FR-013 kept as a state rule; reconstructor re-applies only while the task is still in Next at `from_revision` (HTTP §4 / §9, R9, ADR §3); FC §6 vectors (yield + cosmetic save; yield + decision + Undo); sweep test; QS 2.6a |
| AH-04 | advisory | `parked` lost on a code rollback | Fixed in part: the E6 row is written at park time (`parked_at`, `from_revision`, `source`), so the park survives in export and metrics (DM E1, E6; HTTP §8, §9); the residual limit (such a task no longer shows on While you were away) is stated in HTTP §8 and the plan rollback. Not adopted: deriving "unseen parks" from E6 — old code moving a task out of and back into Someday cannot be detected, so it would show false parks; the stated limit is the honest bound |
| AH-05 | advisory | Startup raise takes the whole backend down | Fixed by bounding the operational risk while keeping the campaign-1 decision (constitution I; c1 AC-01): runbook "set the provider to `disabled` before rotating or removing the key" in HTTP §7, R13, ADR §5, plan rollback and the PR-07 `.env.example` row. Owner note 6 |
| AH-06 | advisory | Bulk release trusts the client's item list | Fixed: server computes eligibility per kind at request time (restart: in Next and `restart_eligible`; Inbox remainder: in Inbox and not processed in the session); everything else `not_eligible` (HTTP §6); test with a 20-day Next task; QS 5.6 |
| AH-07 | advisory | UTC zone between activation and onboarding | Fixed: optional `time_zone` on the explainer acknowledgement and a zone update whenever the device zone differs (HTTP §5, DM E2, R11, IOS §2); `Pacific/Honolulu` vector (FC §6); QS 7.1 |
| AH-08 | advisory | Optimistic device park under clock skew | Fixed: `server_now` consumer defined — signed-in devices evaluate due parks with the last observed offset (DM E10 `serverClockOffset`) and, online, apply a park only after `applied: true`; offline stays optimistic (IOS §5, HTTP §5, R9, plan); `ReviewSyncTests` case; QS 3b |

## Owner notes (information or confirmation, not blockers)

1. **Account-less staged exposure (RC-07).** The spec now records that account-less
   iOS gets the feature only when its release switch is turned on (after one clean
   threshold cycle of the synced path; plan PR-14). This narrows "the whole feature
   works locally" in time, not in scope. Please confirm it when approving the slice map
   at `/speckit-tasks` (already a scheduled owner gate).
2. **Person-released tasks in the Someday step (RC-14).** Planning extended the
   owner's 30-day "keep in Someday" rule to tasks the person released themselves
   (decision, restart release, Inbox-remainder release), so a review never asks about
   tasks just released in it. If the owner prefers them eligible, it is a one-line
   change to FR-032 and DM E5.
3. **What "reached asks for a decision" means (RC-03).** FR-005 now counts a
   formulation as stalled if it was asking when it closed or had been kept 7 more
   days. A formulation that asked, then got a future due date (which pauses it) and was
   reworded before that date is not counted. This is the literal reading; tell us if
   the paused case should count too.
4. **Post-release read-out numbers (TE-07).** The minimum samples (SC-003 ≥ 6 answered
   reviews, SC-004 ≥ 4 reviews per mode, SC-005 ≥ 20 shown cloud requests) and the rule
   that widening beyond the owner waits for the 8-week read-out are proposals for
   confirmation with the slice map.
5. **Leaving a review (RC-01).** The spec now matches the signed-off design: "Leave
   for now" pauses; a left review with activity counts at once and becomes "partial"
   only when replaced or after 7 idle days. No behaviour the owner chose changed; the
   recorded status name is what moved.
6. **Navigator key rotation (AH-05).** The backend still refuses to start when the
   cloud navigator is configured without its key (campaign-1 choice). Operators must set
   the provider to `disabled` before rotating the key; otherwise a machine restart
   during the rotation takes the whole service down.
