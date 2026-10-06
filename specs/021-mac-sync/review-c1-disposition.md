# Planning review campaign 1 — dispositions

**Run**: `021-mac-sync-c1` (`.specify/workflows/runs/021-mac-sync-c1/`), status
`technical-changes-required`, risk high, 63 technical findings (2 blocking, 37
important, 24 advisory) and 0 product decisions. **Dispositioned**: 2026-10-06.

Every finding was checked against the repository before it was acted on. Evidence
re-read for this campaign includes `scripts/classify_path_risk.py` (run with `--null`
over every slice's full path list), `macos/Sources/BrainBuddyMac/LocalGTDStore.swift:194-264`
(`init` never writes; `mutate` creates `local-gtd.json` when missing and the in-memory
generation is 0), `macos/Sources/BrainBuddyMac/APIClient.swift:431-432` (shared cookie
storage), `macos/Sources/BrainBuddyMac/ContentView.swift:1983-1989` (archive guard),
`ios/BrainBuddyKit/Sources/BrainBuddyCore/Replay.swift:84-159` (`rewritingAfterMerge` →
`withdrawing`), `ios/BrainBuddyKit/Sources/BrainBuddyCore/Compaction.swift:24-28, 100-112`
(`foldMove`), `ios/BrainBuddyKit/Sources/BrainBuddySync/SyncEngine.swift:235-250, 320-345`
(every non-`localChange` trigger sets `pullRequested`; `kick()` cancels a scheduled retry),
`SyncEngine+Cycle.swift:16` (`setStatus(.syncing)` on every cycle),
`SyncConfiguration.swift:76-80` (`retryDelay` 2, 4, 8 s … ±20 %),
`ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift:168, 224`
(`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`),
`ios/BrainBuddyKit/Sources/BrainBuddyWorkspace/Workspace.swift:390-430` (sign-out counts
only the outbox; `sync.signOut()` before `store.destroy`),
`ios/BrainBuddy/App/BrainBuddyApp.swift:124-135` (`WidgetReloadAfterSync`),
`ios/BrainBuddyKit/Sources/BrainBuddyPersistence/DocumentFile.swift:52, 147-155` (0700 /
0600), `backend/app/api/middleware.py:38-41, 65` (incoming correlation id accepted
verbatim), `backend/app/api/tasks.py:562, 691, 766, 1183-1208` (`GET /projects`
`error_responses(401)`; the only DELETE is tags; list items without subtasks or
comments), `backend/tests/test_api_contract.py:247`, `frontend/src/api/taskHooks.ts:35-83`
(no polling; `useTags` and `useTaskDetail` separate), `scripts/check_requirement_coverage.py:54-63, 141`,
`.github/workflows/ci.yml:160-190` (the landing path exercises every stack),
`.github/workflows/ios.yml:86` (`^ios/` → TestFlight) and `docs/data-retention.md:34-60, 169-215`.
`git diff --stat e50b144..0b9fffe -- . ':!specs'` is empty, so the plan's code facts
still hold. Every finding's facts held, so **none is rejected**. Where a reviewer offered
alternatives, the choice and its reason are stated. **No owner decision was changed**:
intake, the spec Clarifications and design Sign-off are untouched apart from one blank
line inserted before a Clarifications heading (F41e).

**Totals**: fixed 63 · rejected 0 · owner questions 2 (OQ-1, OQ-2, below; each has a
recommended default the plan already follows, and neither blocks).

Abbreviations: DM = data-model.md, HTTP = contracts/http.md, KIT = contracts/kit-commands.md,
STATUS = contracts/sync-status.md, IMPORT = contracts/mac-legacy-import.md, HOST =
contracts/mac-app-host.md, QS = quickstart.md, R = research.md section, D = design.md.

## Blocking findings

### F01 — landing class of PR-05 (and every slice)

`printf '%s\0' <paths> | python3 scripts/classify_path_risk.py --null` was run over every
slice's full path list (after this campaign's path changes). Result: PR-01 ASK (5/5
paths), PR-02 ASK (`api/tasks.py`, `api/middleware.py`), PR-03, PR-04, PR-06 – PR-09
SHIP, PR-10 ASK (`Makefile`, `scripts/check_manual_evidence.py` and its test), and
**PR-05 ASK**: `ios/BrainBuddyKit/Tests/BrainBuddySyncTests/SyncEngineSessionTests.swift`
camel-splits to `session` (it already did with the first plan's paths), and PR-05 now also
writes `ios/BrainBuddyKit/Sources/BrainBuddyAPI/SessionTokenStore.swift` (token `session`)
for F25/F39. PR-05 is reclassified **ASK** rather than kept SHIP by moving the edits into a
file without the token: its content (session end, account-switch refusal, sign-out order,
the macOS token store) is a session surface, and the plan's own rule forbids hiding a
class by naming. Where: plan "Delivery slices" (new mechanical-classification table,
PR-05 row), "Migration, deploy order and rollback" (deploy order with classes; ASK
landing mechanics per ADR-0008: PR as evidence vehicle, recorded approval, green exact-SHA
CI, audited temporary ruleset intervention; PR-07 and PR-08 wait for PR-05's approved
landing; TestFlight builds per kit/iPhone slice), "Lanes inside 021", "ASK-class surfaces",
"Structure Decision" ("No renaming around the gate"), the Risk header and the post-design
Constitution Check (ASK set PR-01, PR-02, **PR-05**, PR-08, PR-09, PR-10).

### F02 — the legacy import could overwrite a store in use

Verified: `LocalGTDStore.mutate` recreates `local-gtd.json` (l.214-262), and R5's table
re-ran the import whenever no `completed` record existed, replacing a leftover
`store.json`; a fresh install recorded nothing. Fix:

- **Explicit, durable state** in `mac-local.json` (`legacyImport.state`: `none`,
  `inProgress`, `completed`, `unreadable`, `laterFileKept`), with the legacy file's
  digest, the attempt id and the backup name. `none` is recorded at a fresh install;
  `inProgress` is fsynced before anything is written; every first 021 launch ends in a
  terminal state before the workspace opens.
- **The importer never writes `store.json` in place.** It builds a staging file
  `store.import-<attemptID>.json`, verifies it, records `completed`, and only then moves it
  to `store.json` with an exclusive rename that fails if `store.json` exists. So
  `store.json` never holds an unverified import, and the importer can never replace a
  workspace — even when `mac-local.json` is deleted, because "in use" is read from the
  folder (`store.json` exists), not from the record.
- **A `local-gtd.json` that appears after the workspace exists** (an older copy run after
  the update, a Time Machine restore, a moved file, a deleted sidecar, a file written after
  the rename) is never imported, merged, overwritten, renamed or deleted. The person is
  told once (new X-05 "later file"), and X-02 keeps a quiet line with "Show in Finder".
- Normative launch decision table: DM E7.1. Spec: new **FR-033** and the edge case "The
  previous Mac store appears again after the update"; FR-017 lists the notice.
- Tests (IMPORT §6, `021-FR-033`, each asserting unchanged `store.json`, backup and found
  file bytes and exactly one notice): legacy file after a fresh install; `mac-local.json`
  removed; old build writes a new file after the rename; `inProgress` with a `store.json`
  the attempt did not create; an older copy that keeps writing; plus crash points at every
  step, explicit-state recording, and the crash between record and rename. Host check: QS
  Scenario 6 steps 5 – 6.

Where: spec FR-017, FR-033, edge case; DM E7, E7.1; IMPORT §1, §5, §6; R5; HOST §1; plan
US4, failure table, Constitution Check, Risks, Complexity Tracking; D X-05 "later file",
X-02 "earlier-version file kept"; QS Scenario 6.

## requirements-consistency (11)

| id | sev. | finding | disposition |
|---|---|---|---|
| F03 | important | Merge-by-name `withdrawing` strips memberships of an archived local project under lossless archive | Fixed: new merge table — an archived local project merged into an active survivor keeps every membership in the survivor; the local archive is not applied to the account's project and becomes a sync issue (`.archiveNotMerged`); `withdrawing` stays for tags only; stale doc comments rewritten in PR-04. Tests in `ReplayTests`, `FirstSignInMergeTests` (archived "Old flat" with three tasks vs active "Old flat", also via 409), IMPORT §6 output shape. KIT §3, §5; plan US4, failure table; QS 4.1; D X-02 "archive not applied at merge" |
| F04 | important | The kept-outcome issue loses the Mac's outcome text | Fixed: account wins; the issue carries the full local outcome (never clipped), shown selectable with "Copy outcome". One sentence added to FR-003. KIT §3, §5; STATUS catalogue; D X-02 "outcome kept on account"; QS 4.1 "both sides have an outcome" |
| F05 | important | Web polls only the list and projects; subtasks, comments and tags would not refresh | Fixed: `useTags` and the open task's `useTaskDetail` also refetch every 45 s while visible; the detail refetch goes through the existing autosave conflict handling. Tests: `taskHooks.test.ts`, `TaskDetailAutosaveUI.contract.test.tsx` (typed text kept), Playwright `cross-client-refresh.spec.ts` with a fake clock (subtask, comment, tag rename), named `021-FR-032` / `021-SC-001`. R8; plan US1, trace, Test strategy, PR-06; QS Scenario 7 |
| F06 | important | Sign-out silently discards open sync issues | Fixed: FR-018 sentence — every sign-out confirmation names open issues, on Mac and iPhone; catalogue `signOutIssues(n)`; X-04 "open sync issues"; M-01 "sign-out with open issues"; PR-07 uses the same catalogue. STATUS §3; HOST §7; plan US1; QS 5.3 |
| F07 | important | Cadence can exceed the absolute 60 s | Fixed by tightening: pull age 30 s with the 15 s tick, worst case ≈ 50 s (R8). Clarifications Q1 not edited: its decision (at least every 60 s) holds, and "the iPhone's 60 s pull age" describes the pre-021 kit default (R8 note). STATUS §1; KIT §4; HOST §5; plan Technical Context, Complexity Tracking |
| F08 | important | Second-copy alert copy and button contradict design X-08 | Fixed: X-08 copy and "OK" everywhere. R6; HOST §1; QS Scenario 8; plan inconsistency 4 (resolved), US1, failure table |
| F09 | important | FR-032 missing from plan, tests and design | Fixed: coverage sentence FR-001 … FR-033; `021-FR-032` named by `PeriodicSyncTickerTests`, the convergence test, `taskHooks.test.ts`, Playwright and the iPhone manual line; US1 iPhone and web bullets cite it; D "Requirements with no affordance" lists FR-032. Plan Test strategy, US1; D |
| F40 | advisory | Stale plan text after the spec amendment; design.md Sync now note; G-8 missing; no Clarifications line for FR-019 | Fixed: plan inconsistencies 1 – 5 marked resolved with references; the owner question marked answered; post-design check updated; design "Notes for the plan" corrected and G-8 added to the gaps table. The Clarifications line was **not** added: Clarifications record owner answers, and the FR-019 amendment's provenance is already recorded in design.md Sign-off ("Review fixes after sign-off") and commit `b83d367`, which the plan header cites |
| F41 | advisory | Spec errors (a)–(e) | Fixed: (a) "delete" dropped from US1's independent test; (b) cross-reference → FR-001, FR-018; (c) the deleted-task copy kept and labelled a defensive path (KIT §5, D X-02 note); (d) FR-017 names the "Couldn't sign out" error; (e) blank line before the "after /speckit-plan" heading |
| F42 | advisory | FR-021's no-sign-out outcome unstated; "never account data" wording | Fixed: FR-021 "If the person never signs out, the backup is kept"; Assumptions wording corrected; data-retention row text in DM E8. An outer cap or a delete control is owner question OQ-1 |
| F43 | advisory | "Every record / 100 %" vs intentional exclusions | Fixed: spec Assumptions name what is not carried (deleted tags, retry receipts, a comment's edited time); the import report counts each. IMPORT §2 step 6, §3 |

## architecture-consistency (9)

| id | sev. | finding | disposition |
|---|---|---|---|
| F01 | **blocking** | PR-05 lands as SHIP but its paths classify ASK | Fixed (see "Blocking findings") |
| F10 | important | Plan predates X-08 | Fixed: design authority X-01 – X-08, 11 screens, US1 header cites X-08, "adds G-8" removed, inconsistency 4 resolved; HOST §1 and R6 carry the signed-off copy and "OK". Plan header, Technical Context; D affordance map ("OK") |
| F11 | important | Plan not re-synced after `0b9fffe` | Fixed: coverage to FR-033; FR-032 tests named; inconsistencies 1 – 3 and the owner question resolved; trace header re-checked at `0b9fffe` (only `specs/` changed since `e50b144`). Plan |
| F12 | important | A 15 s tick would flip status every 15 s and reload widgets | Fixed: `.periodic` never sets `pullRequested` and is a no-op (no cycle, no `.status`, no `.documentChanged`) unless the pull is due or changes wait, and always while a retry is scheduled; `WidgetReloadAfterSync` therefore fires only on real cycles. Test: idle ticks for 29 s → zero transitions and requests. KIT §4; R8; plan US1 (iPhone), Test strategy; QS 5.2 |
| F13 | important | Failing outranks offline while offline | Fixed: STATUS row 4 requires `isOnline`; `failingSince` kept offline so the clock does not restart; X-02 offline keeps the last failure's reference id; precedence-pair test. STATUS §3, §5; KIT §4; DM E5; D X-01 "error, then offline", X-02 offline row |
| F14 | important | Repeat archive could clear the FR-027 marker | Fixed: repeat archive changes only `revision` and `updated_at`, under PR-02 and PR-03; kit `alreadySatisfied`; fake server mirrors it; golden trace and `test_021_FR_027_repeat_archive_keeps_marker`. HTTP §4; DM E1; KIT §3, §7; QS 1.9 |
| F15 | important | Archived vs archived same name creates two archived projects | Fixed as a documented limit (ADR-0020 leaves no alternative): merge joins active projects only; spec edge case "Same-named archived projects"; SC-003 duplicate check scoped to active names with the archived case asserted explicitly. KIT §3; plan US4, failure table; QS 4.1 |
| F44 | advisory | "Byte-identical" default; missing 422 for `GET /projects` | Fixed: HTTP §1 reworded (same set and order, new fields); route `error_responses(401, 422)` and the contract-map entry `{"401", "422"}` in PR-02; pytest row. HTTP §1; plan trace, Test strategy; QS 1.10 |
| F45 | advisory | PR-02/PR-03 write the kit trace copy under `ios/` | Fixed: the kit copy and its `resources:` declaration move to PR-04, with a pytest asserting byte equality; PR-02/PR-03 write nothing under `ios/`. KIT §7; R19; plan Delivery slices, write-path notes |

## testability-evidence (13)

| id | sev. | finding | disposition |
|---|---|---|---|
| F16 | important | SC-005 test cannot pass with the real backoff | Fixed: the engine keeps the backoff but schedules one attempt at exactly `failingSince + 60 s`; "Couldn't sync" shows only if that attempt fails (`lastFailedAttemptAt`, DM E5); `.periodic` ignores a pending retry, `.manual` runs at once. Test with `ManualSyncScheduler`, the real `retryDelay` at both jitter extremes: recovery at 59 s → nothing, at 61 s → failing. KIT §4; STATUS §1, §3, §5; QS 5.2 |
| F17 | important | SC-001 proven only at its best phase; Mac ↔ web unmeasured | Fixed: pass criterion defined (start at the sender's local apply, end when the receiver holds it; every logic case must pass, the 95 % allowance is for host checks); worst tick phase with a 1.5 s pull; pull age lowered to 30 s; Mac ↔ web by composition plus the Playwright fake-clock check. R8; QS 4.2; plan Test strategy, Observability |
| F18 | important | iPhone tick has no automated test | Fixed: the repeating timer moves into the kit (`PeriodicSyncTicker`, injectable `SyncScheduler`), used by both apps; Linux tests for FR-006 / FR-032; the iPhone only toggles it; manual line for "fires while open, not in the background". KIT §4; plan US1, PR-05, PR-07; QS 5.5 |
| F19 | important | FR-009 / US1-3 / US1-5 have no named test | Fixed: `TaskEditDraft` and `SelectionAnchor` as kit pure helpers with tests; Workspace test (field A edited while a pull changes A and B → only A sent; `EntityID`s stable); manual-macos-status line for scroll, selection and focus. KIT §8; plan US1, Test strategy; QS 4.9, 5.4 |
| F20 | important | Review marks invalidated by the first upload | Fixed: the stamp is `RecordContentStamp`, a salted HMAC of user-visible fields (no ids, no server times), so upload, re-keying and sign-out → sign-in keep marks valid; Workspace test against the fake server. DM E7.2; KIT §8; IMPORT §4, §6; QS 4.1 |
| F21 | important | No equality check for the trace copy; backend lane writes `ios/` | Fixed: byte-equality pytest (runs on every landing, which exercises every stack); copy and `resources:` in PR-04; traces enumerated. KIT §7; R19; plan PR-02 – PR-04 |
| F22 | important | SC-004 / FR-016 / FR-017 manual-only behind `test -f` | Fixed: `MacPresentationRouter` is the only presenter and takes only user intents; `MacPresentationRouterTests` sweeps every state and transition (no presentation, no focus request); `scripts/check_manual_evidence.py` validates headers, per-state checklists and SHA ancestry instead of `test -f`; SC-007 reported manual-pending, never covered by the template. HOST §6, §8; plan Test strategy, PR-09, PR-10; QS prerequisites |
| F23 | important | Mac X-06 and the FR-027 rule lack evidence | Fixed: `GTDQueries.projectDisplay` (FR-027 line, "accepts no new task", label) in the kit with `ProjectDisplayTests`, rendered by Mac and iPhone; `manual-macos-archive.md` for X-06 states, remembered disclosure, strings, focus. KIT §8; HOST §4; plan US5, PR-08 |
| F24 | important | FR-029 / FR-030 / FR-005 thinly proven on the Mac | Fixed: `MacSyncFlowTests` with a counting transport (account-less: zero requests; after sign-out only the queued logout), sync-log privacy with sentinels, service-name check; host step for the Keychain item and "token found in files: no"; `MacPrivacyGuardTests` for the voice sources; iPhone and kit have no logger (checked). HOST §5, §8; R21; plan Observability, Test strategy |
| F46 | advisory | Catalogue, tooltips, formatter and reference ids untested | Fixed: verbatim catalogue and tooltip tests for both devices, age-formatter boundaries, non-empty reference id on the failing tooltip and every issue. STATUS §5; KIT §5 |
| F47 | advisory | PR-08 bundling; PR-04/05 serialization; `AGENTS.md` owner | Fixed: PR-08 split into two task lanes with the importer wired last; PR-05's pure status files may be developed beside PR-04 (landing still after PR-04); `AGENTS.md` owned by PR-09 (R22 corrected). Plan Delivery slices, deploy order |
| F48 | advisory | Swift ids invisible to the coverage script until 020 PR-01 | Fixed: interim rule — each Swift slice records its requirement → test-name list and `swift test` output in its PR body or landing record; open question already resolved. R19; plan Requirement coverage; QS fast checks |
| F49 | advisory | Comment `editedAt` not carried, against "no loss" | Fixed: spec Assumptions state it; verification table says `editedAt` is not compared; the report counts skipped markers. IMPORT §2, §3 |

## privacy-consent-security (5)

| id | sev. | finding | disposition |
|---|---|---|---|
| F25 | important | Mac credential at-rest disposition unstated | Fixed: DM E9 states it (login keychain; login password and FileVault; carried by Time Machine and Migration Assistant; never synchronizable; removed on sign-out and first 401; pending-logout copy until delivered) with the data-retention row text; the store stops claiming "this device only" on macOS; macOS-lane round trip. R17; KIT §4; HOST §8 |
| F26 | important | Four new device records without row text | Fixed: row text for `store.json` (DM E5), `mac-local.json` (E7.2), backup, kept files and legacy cookie (E8), keychain (E9), each with contents, protection, deletion trigger and life after the app is deleted; the Mac export sentence; sidecar 30-day pruning at every launch |
| F27 | important | "Your tasks are removed" while the backup stays | Fixed without changing the owner-accepted retention: X-04 appends "A copy of your tasks from before the update stays on this Mac until <date>." while the backup exists; X-02 line with "Show in Finder"; data-retention row; tests in STATUS §5. The optional "remove it now" control is owner question OQ-1 |
| F50 | advisory | Correlation id accepted verbatim | Fixed: PR-02 accepts an incoming id only matching `^[0-9A-Za-z._-]{1,64}$`, else mints a UUID; newline-injection case. HTTP §6; plan Observability, Test strategy; QS Scenario 3 |
| F51 | advisory | Paths, file names and digests in logs and evidence | Fixed: sentinel-home test over every import path asserting no `/Users/`, `local-gtd`, file names or 32+ hex runs, `unreadableReason` as enum; evidence rule (counts, durations, yes/no; "bytes identical: yes/no"). IMPORT §3, §6; R21; QS prerequisites, 6.2 |

## ux-accessibility-mobile (13)

| id | sev. | finding | disposition |
|---|---|---|---|
| F28 | important | Signing in locks the window with no way out | Fixed: Cancel and Esc enabled while loading (request aborted, values kept, focus to Password; a late reply's session ended); new "error: no answer"; wording "other windows and the quick-capture panel stay usable". D X-03 rows and the loading mockup (`design/X-03-sign-in-sheet.html`); HOST §7 |
| F29 | important | X-03 focus return to a vanished opener | Fixed: fallback to the X-01 status words; on Cancel to the trailing action when present; QS 5.4 host line. D "Keyboard and focus"; X-03 mockup note; HOST §7 |
| F30 | important | Focus after Dismiss unstated | Fixed: next issue's Copy, else previous; after the last, Sync now or Sign out…. D X-02 rows and "Keyboard and focus"; HOST §6 |
| F31 | important | No keyboard path to archive; focus after archiving | Fixed: File › "Archive project" / "Unarchive project"; disclosure in the tab order with its state; X-06 and D-01 "archived (just now)"; the dirty-draft guard is kept. D X-06, D-01, "Keyboard and focus", affordance map; HOST §4; plan US5 |
| F32 | important | Unarchive name clash has no state | Fixed: "unarchive refused: name in use" on X-06, M-02 and D-01 with the given copy, "Rename…", no Retry, focus on Unarchive; local refusal immediate, X-02 issue only for an offline clash. D; HOST §4; plan US5; QS Scenario 7 |
| F33 | important | First upload reads as days of failure | Fixed: waiting age from `max(issuedAt, accountLinkedAt)`; "Not synced yet" until the first upload drains; X-02 "Adding your tasks to your account · N left"; X-04 uses the unsent variant with the count. DM E5, E6; STATUS §3, §5; KIT §4; D X-01, X-02, X-04 |
| F34 | important | Kept-outcome issue: text lost, missing from X-02 | Fixed: as F04, with "Copy outcome" and the Dismiss name "Dismiss and discard the outcome for <project>". D X-02, "Keyboard and focus"; HOST §6 |
| F35 | important | X-08 traceability | Fixed: as F08/F10; X-08 in D's FR-017 bullet and the affordance map ("OK") |
| F52 | advisory | Sync now hidden vs disabled when the session ended | Fixed: shown disabled, as offline and in X-07. D X-02 row and mockup (`design/X-02-status-popover.html`); HOST §6 |
| F53 | advisory | A fast failing Retry shows nothing | Fixed: "Last tried 14:35" in the X-02 error notice and the X-01 failing tooltip, updated after every attempt. STATUS §2, §3; D X-01, X-02 |
| F54 | advisory | X-04 has no open-issues variant | Fixed: as F06 |
| F55 | advisory | iPhone row has no reference id path | Fixed: long-press "Copy reference ID" on the row; Settings › Sync shows the id from the first failure. D M-01; plan US3, PR-07; QS 5.5 |
| F56 | advisory | Stale design note on iPhone Sync now | Fixed: note corrected; M-01 "Settings › Sync, sync running". D |

## adversarial-high-risk (12)

| id | sev. | finding | disposition |
|---|---|---|---|
| F02 | **blocking** | Legacy import can overwrite a populated `store.json` | Fixed (see "Blocking findings") |
| F36 | important | Pre-021 session cookie left on disk, session alive | Fixed: `LegacyCookieCleanup` at the first 021 launch hands the cookie to the kit's pending-logout list and deletes it from shared cookie storage; test; data-retention row. HOST §1, §8; DM E8; plan US4, PR-08 |
| F37 | important | Merge rewrite drops archived project memberships silently | Fixed: as F03, with a visible sync issue |
| F38 | important | Compaction breaks verification; stranding | Fixed: the import outbox is not compacted; fixture rows with `waitingSince ≠ createdAt` and an edited comment; `verificationFailed` gets its own X-05 copy; recovery: the file is kept for a later build. A person-started append-import into a used workspace is owner question OQ-2 (FR-033 forbids a silent one). IMPORT §2, §3, §5, §6; R5; D X-05 |
| F39 | important | Keychain store never ran on macOS | Fixed: as F25; a write failure is X-03 "couldn't save sign-in" with Ref and the new session ended; a read failure is logged as `keychain_read_failed`. KIT §4; HOST §7, §8; D X-03 |
| F57 | advisory | Correlation id log injection | Fixed: as F50 (bounded pattern instead of UUID-only, because it also accepts the server's and other tools' ids; the kit's UUID matches) |
| F58 | advisory | Import reorders lists by project | Fixed: one global `(list, orderKey, createdAt, id)` creation order after the projects exist, archiving at the end; only a name-clashing archived project's tasks lead their lists, and verification expects exactly that. IMPORT §2, §3, §6 |
| F59 | advisory | X-04 error copy untrue after a removal failure | Fixed by reordering the kit sign-out (engine paused → store destroyed → only then session ended and token removed; resume on failure), so the approved copy stays true; test. KIT §4; HOST §7; plan US1, failure table; QS 5.3 |
| F60 | advisory | Refused unarchive fans out into many 400s | Fixed: on the 409 the engine reverts to archived at once and rewrites queued captures to no project under one issue that counts them; test. KIT §4, §5; plan failure table; QS 4.8 |
| F61 | advisory | Backend slices trigger TestFlight builds | Fixed: as F21/F45; the TestFlight sequencing statement is now true. Plan deploy order |
| F62 | advisory | Backup not mentioned where the person decides | Fixed: as F27 (X-04 sentence, X-02 line with "Show in Finder", data-retention row) |
| F63 | advisory | Spec assumes a project delete route | Fixed: plan inconsistency 1 records that no project delete route exists (`tasks.py:691` is tags); US2-5's example changed; the deleted-elsewhere copy labelled defensive. KIT §5; D X-02 note |

## Owner questions (non-blocking; defaults applied)

1. **OQ-1 — Removing the pre-upgrade backup on request** (F27, F42, F62). Should the Mac
   offer "Also remove that backup now" in X-04 (or a button in X-02), or cap the backup's
   life when nobody signs out? **Recommended default (applied)**: no deletion control and
   no cap in 021; the X-04 sentence gives the date, X-02 shows the file with "Show in
   Finder", and `docs/data-retention.md` lists it. A control would be a new irreversible
   action that needs its own design.
2. **OQ-2 — A person-started import of a kept previous-version file into a workspace in
   use** (F02, F38). FR-033 keeps such a file untouched. Should a later feature offer
   "Add these tasks" that appends its records and merges projects and tags by name?
   **Recommended default (applied)**: not in 021; the file is kept and surfaced, nothing
   is lost.

## Owner notes (information, not blockers)

1. **New copy in approved surfaces.** This campaign appended conditional sentences to the
   approved X-04 dialog (open sync issues; backup kept), and added copy for X-03 ("no
   answer", "couldn't save sign-in"), X-05 ("couldn't carry over", "later file"), X-02
   ("first upload", "outcome kept on account", "archive not applied at merge", backup and
   earlier-version lines) and the "unarchive refused" states. The approved "Sign out?"
   text itself is unchanged. The design owner may reword any of them; design.md lists them
   under "Planning review c1 additions".
2. **Clarifications Q1** still says the cadence "matches the iPhone's 60 s pull age". The
   decision (at least every 60 s) holds with margin; the clause describes the kit default
   before 021, so it was left as the owner's record (R8).
