# Planning review campaign 2 — dispositions

**Run**: `021-mac-sync-c2` (`.specify/workflows/runs/021-mac-sync-c2/`), the last campaign
allowed (cap 2), 65 technical findings (2 blocking, 32 important, 31 advisory) and 0
product decisions. **Dispositioned**: 2026-10-06. After this the feature goes to founder
acceptance; the residual risks are listed in plan.md "Risks" → "Residual risks".

Every finding was checked against the repository before it was acted on. Evidence re-read
for this campaign includes `ios/BrainBuddyKit/Sources/BrainBuddyCore/NameNormalizer.swift`
(NFKC, Python-`isspace` whitespace, one leading "@" dropped from tags, casefold key),
`Reducer+Validation.swift:1-64` and `Vocabulary.swift:84-91` (`FieldRules` lengths in
Unicode scalars: title, name and waiting-for 500, details and comments 20,000, colour 64),
`Reducer.swift:24`, `Reducer+Replay.swift:32`, `Compaction.swift:42-328`,
`Replay.swift:108-253`, `GTDCommand+Sync.swift:17-140`, `PushPlanner.swift:97`,
`SyncEngine+Push.swift:352`, `SyncEngine+Pull.swift:180`, `StoreDocument+Merge.swift:263`
(exhaustive switches over `GTDCommand`), `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift:104-142`
(exhaustive switch, no `default`; a `grep` for kit-enum switches over `ios/BrainBuddy`,
`ios/BrainBuddyWidgets`, `ios/Shared` and `macos/` finds no other), `SyncEngine.swift:254-275`
(single-flight `syncNow` already exists), `SyncEngine+Session.swift:10-20`
(`discardStaleSessions` removes tokens without logging out when no account is linked),
`BrainBuddyAPIClient.swift:167-183` (`listAllTasks` gathers every page, then the pull
applies once) and `346-356` (`exchange` throws `.tokenStorage` without a reference id and
loses the new token), `Workspace.swift` (`loadError`, `resetUnreadableStore`),
`LinkedAccount.linkedAt`, `Tests/BrainBuddyWorkspaceTests/Support/FakeSyncService.swift`,
`ios/BrainBuddy/App/RootView.swift:142-190` (the iPhone's load-error view),
`macos/Sources/BrainBuddyMac/LocalGTDStore.swift:268-274, 526-550, 628-631` (grapheme
counts, `localizedCaseInsensitiveCompare`, unlimited notes, colours never set),
`frontend/src/api/__tests__/clientParity.test.ts:96-103` (exactly 42 operations, keys equal
to the manifest), `backend/app/api/tasks.py:1238-1250` with
`backend/app/modules/tasks/service.py:896-900` (per-project open counts) and `962-981`
(`archive_project` checks the revision first), `frontend/src/pages/PrivacyPolicyPage.tsx:6, 85-93, 207-210`,
and the three web pages that pass `useProjects` data to `AppShell`. Every slice's path list
was re-run through `printf '%s\0' <paths> | python3 scripts/classify_path_risk.py --null`
at `a2f4827`. Every finding's facts held except where a row says otherwise, so **none is
rejected**. **No owner decision was changed**: intake, the spec Clarifications (including
the delegated OQ-1 / OQ-2 decisions of `95ce8de`) and the design Sign-off are untouched.

**Totals**: fixed 65 · rejected 0 · owner questions 0.

Abbreviations: DM = data-model.md, HTTP = contracts/http.md, KIT = contracts/kit-commands.md,
STATUS = contracts/sync-status.md, IMPORT = contracts/mac-legacy-import.md, HOST =
contracts/mac-app-host.md, QS = quickstart.md, R = research.md section, D = design.md.

## Blocking findings

### G01 — new `GTDCommand` cases break exhaustive switches outside PR-04's paths

Verified: `GTDCommand` is switched over exhaustively in the reducer dispatch
(`Reducer.swift:24`), replay (`Reducer+Replay.swift:32`, `Replay.swift`), every compaction
fold and barrier (`Compaction.swift`), the sync layer (`GTDCommand+Sync`, `PushPlanner`,
`SyncEngine+Push`, `SyncEngine+Pull`, `StoreDocument+Merge`), the fake server and the test
command generator (`Support/RandomCommands.swift`), and in one app file: the iPhone's
`SyncIssuesScreen.describe` (l.104-142, no `default`). No file under `ios/BrainBuddyWidgets`,
`ios/Shared` or `macos/` switches over a kit enum that 021 extends. `RequestBodies.swift`
needs no case (bodies are built per command in `GTDCommand+Sync`), and `RequestBody.swift`
already has nullable `string()` / `has()` readers for the fake server. Fix:

- The plan's Summary no longer says "optional `Codable` fields only": the document changes
  are additive for `Codable`, but the new enum cases (`setProjectOutcome`,
  `unarchiveProject`, three `GTDValidationError` cases, `SyncTrigger.periodic`) are
  **source-breaking**. KIT §2 and DM E4 say so; R20's serialization row is corrected.
- **Plan rule** ("Enum-case rule", Delivery slices): a slice that adds a public enum case
  carries every file that switches exhaustively over that enum, found by a search for
  `switch` over the type in `ios/BrainBuddyKit`, `ios/BrainBuddy`, `ios/BrainBuddyWidgets`,
  `ios/Shared` and `macos/`; `/speckit-tasks` and implementers re-run it.
- KIT §9 lists every consumer per enum with the slice that carries it (`GTDValidationError`:
  `Commands.swift` message only; `SyncTrigger.periodic`: `SyncEngine.swift:241`;
  `APIError.Kind` and `SyncStatus`: no new case).
- **PR-04 paths** gain `Reducer.swift`, `Compaction.swift`, `FakeServer+Tasks.swift`,
  `FakeServerRecords.swift` (the three project fields), `Support/RandomCommands.swift`,
  `CompactionTests` and `ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift`, whose
  delegation to `SyncIssueDescriber` moves from PR-07 into PR-04. PR-07 no longer writes it,
  so the PR-04 ↔ PR-07 write paths stay disjoint.
- Classifier re-run: PR-04 55 paths, SHIP mechanically, SHOW semantically (unchanged).

Where: plan Summary, Project Structure, trace, Delivery slices (rule, classification table,
PR-04 and PR-07 rows, PR-04 lanes), Risks; KIT §2, §9; DM E4; R20 row.

### G02 — the legacy import fails on realistic data and strands it

Verified: the kit stores names in NFKC with Python-whitespace collapsing and one leading
"@" removed from tags, counts lengths in Unicode scalars, limits notes to 20,000 and
colours to 64, and keys uniqueness by casefold + NFKC + whitespace; the old store trims
Foundation whitespace, counts graphemes, has unlimited notes and uses
`localizedCaseInsensitiveCompare`. Applying raw values through the reducer, and verifying
by raw equality, failed on "Квартира №5", "™", "Home  Repair", "@home" beside "home", long
emoji titles and long notes, and the empty workspace the person then used made the file
unimportable (FR-033). Fix:

- **`ImportCanonicalizer`** (new, `BrainBuddyCore`, Linux-tested; IMPORT §2a): a
  deterministic, documented, total transform from every value the old store accepted to a
  valid kit value. Names take `NameNormalizer.display` / `tagDisplay`
  ("Квартира №5" → "Квартира No5", "™ Ideas" → "TM Ideas", "Home  Repair" → "Home Repair");
  names that collide only under the kit key keep both records with a deterministic
  " (2)", " (3)" suffix (both projects and their memberships stay apart; merging the
  person's own records would be a silent reorganisation); over-long titles, names and
  waiting-for are cut at the scalar limit with the full text kept in the task's notes
  ("Full title: …") or the report; notes over 20,000 continue in "Notes, continued"
  comments; long comments are split; an outcome over 1,000 is cut; an over-long colour,
  an unparseable date, an unknown state and a missing reference are dropped or defaulted
  with a report entry. Task text that only looks odd ("Call  mom") is unchanged.
- **Import report** `local-gtd.import-report-<UTC>.txt` beside the backup lists every
  adjustment with the original, the result and the rule; logs get counts only. With
  adjustments only the upgrade stays silent and X-02 shows "Some details changed during the
  update" with "Show in Finder". A record that still cannot be carried (none is known) is
  listed as "not carried", X-05 "partly carried over" is shown once, and the backup — the
  untouched original — is never deleted by the app (DM E8 condition 3). Nothing is dropped
  silently.
- **Verification** compares against the canonical expectation, never the raw value
  (IMPORT §3; R5 step 5). A reducer rejection is an importer defect (`verificationFailed`),
  never "corrupt"; `corrupt` is kept for files that do not decode (IMPORT §5).
- The plan's earlier "partial read = unreadable" was the plan's interpretation, not a
  sign-off decision; it is revised (D "Planning review c2 additions"; X-05 mockup note; R5).
- **Spec**: FR-020 says values are carried in the account's stored form, adjusted by a
  fixed rule that keeps the full text, and listed in a report; nothing is dropped silently.
- **Tests** (IMPORT §6; plan Test strategy): `ImportCanonicalizerTests` with the reviewer's
  examples and more ("Квартира №5", "™", double spaces, "@home" + "home" → "home",
  "home (2)", "Home  Repair" + "Home Repair", a 500-emoji title, 25,000-character notes, a
  30,000-character comment, a 1,200-character outcome, a 100-character colour, a missing
  project); a 500-seed property test that any snapshot the old store's own validation
  accepts imports and verifies; the `legacy-awkward.json` fixture end to end; a golden
  artifact signed in by the kit (G21).
- **Compensating measure**: a dry run of the 021 build on a copy of the owner's real
  folder (`BRAINBUDDY_MAC_DATA_DIR`, HOST §1) before the owner's own upgrade (QS Scenario 6,
  step 0).

Where: spec FR-020; IMPORT §2a, §2, §3, §5, §6; DM E7.1 "Recovery, stated honestly", E8;
KIT §8 (`ImportCanonicalizer`); R5, R24; HOST §1; STATUS (`popoverImportAdjusted`); D X-05
"partly carried over", X-02 line; plan US4, failure table, Test strategy, PR-04 and PR-08
rows, Risks; QS Scenario 6.

## requirements-consistency (13)

| id | sev. | finding | disposition |
|---|---|---|---|
| G03 | important | FR-007 lists tag colour and task order as synced | Fixed: FR-007 now "tags: name, deletion (tags have no colour on any client)" and "a task's position in a list is assigned by the account when it is created or moved; the Mac never sends an order". SC-001's convergence test covers the record types of the corrected list. Spec FR-007; plan Test strategy |
| G04 | important | FR-009's pointer clause has no mechanism | Fixed: the kit's `ListPresentationHold` keeps the row under the pointer, or being edited, in place while other rows take an incoming re-sort, and applies it when the pointer leaves or the edit ends; Linux tests; host-check line. R18's stale drag sentence replaced. KIT §8; HOST §4; R18; plan US1; QS |
| G05 | important | "Couldn't carry over" copy promises a later version | Fixed: copy now "Keep the file: it still has all your earlier tasks." DM E7.1 "Recovery, stated honestly" says a later build retries only while the workspace is not in use, and why the importer is made total instead (G02). IMPORT §5; D X-05 |
| G06 | important | No row for `completed` + legacy file + no `store.json` | Fixed: row 10 covers `completed` with any other legacy file whether `store.json` exists or was removed by a sign-out → later file, never import; invariant 2 keeps a signed-out workspace "in use" (`workspaceFirstWrittenAt`, the record, backup or set-aside files); test "sign out, then an older copy writes local-gtd.json". Spec FR-033 edge case; DM E7.1; IMPORT §6 |
| G07 | important | FR-006 "while active" vs plan "while running" | Fixed: FR-006 "periodically while the app is running, at least once every 60 s, also when its window is not frontmost"; an App Nap activity while signed in (G64); host line with the window covered. Spec FR-006; R8; HOST §5; QS |
| G08 | important | Import reorders tasks of same-named archived projects | Fixed: the spec edge case "Same-named archived projects" states this one accepted change to manual order and points to FR-020; IMPORT §2 and §3 say exactly that sequence is expected. Spec edge case; IMPORT §2, §3 |
| G35 | advisory | FR-015 / SC-004 absolute about reference ids | Fixed: both scoped to failures of a request to the server and to sync issues; a purely local or offline failure carries none. Spec FR-015, SC-004 |
| G36 | advisory | First-load indicator vs FR-013's 1 s | Fixed: US1-1 adds "when it lasts longer than 1 s (FR-013)"; design X-01/X-03 and plan say the indicator follows FR-013 per cycle during a multi-cycle first upload. Spec US1-1; D X-03; plan US1 |
| G37 | advisory | Stale "open questions", "four fields", Clarifications Q1 | Fixed: plan section renamed "Decided product choices (delegated)", recording OQ-1/OQ-2 as decided (`95ce8de`); the Constitution Check lines updated; "three new project fields". Clarifications Q1's "60 s pull age" clause is left as the owner's record, with R8's note as the explanation (the reviewer's second option), because Clarifications are owner decisions. Plan |
| G38 | advisory | FR-029 vs the legacy logout | Fixed: FR-029 names the one exception (ending a session opened earlier on this Mac, no user data); an Assumption mentions the pre-021 hidden online mode. Spec FR-029, Assumptions; HOST §1 |
| G39 | advisory | Sign-out silently deletes the backup after day 30 | Fixed: `signOutBackupRemoved` ("The copy of your tasks from before the update will also be removed from this Mac."), appended last whenever this sign-out deletes the backup; verbatim test. STATUS; DM E8; D X-04 "backup removed"; HOST §7 |
| G40 | advisory | US4-5 has no UI path | Fixed: US4-5 reworded to the reachable trigger (a sign-in such as "Sign in again" resolving to a different account, for example one deleted and re-created with the same email); a stub-transport case in `MacSyncFlowTests` and a host-check line. Spec US4-5; HOST §8; plan US4; QS |
| G41 | advisory | Assumption names only completion dates | Fixed: the Assumption names creation, completion, cancellation and waiting-since times, says a Waiting age restarts, and that review marks (keyed by content) stay valid. Spec Assumptions; plan US4 |

## architecture-consistency (12)

| id | sev. | finding | disposition |
|---|---|---|---|
| G01 | **blocking** | Exhaustive switches outside PR-04's paths | Fixed (see "Blocking findings") |
| G09 | important | PR-02 edits the parity manifest that only a web test reads | Fixed: the manifest change moves to PR-06 with the web adapters and the count; the trace row names `clientParity.test.ts` as the only reader (`TaskListQueryTests.swift` only names it in a title). HTTP §3; plan trace, PR-02 and PR-06 rows |
| G10 | important | Decision table has no fallback and no post-sign-out row | Fixed: as G06, plus row 16 and invariant 7 "fail closed: never import, never rename; a legacy file present is a later file". DM E7.1; IMPORT §1 |
| G11 | important | `pause()`/`resume()` not on `SyncService`; crash window | Fixed: one protocol method `signOut(removingLocalDataWith:)` runs the removal inside the engine: stop, record a pending logout, remove local data, then remove the token and log out; on removal failure the pending logout is withdrawn and sync resumes. A crash after the removal leaves the pending logout for the next launch. `FakeSyncService.swift` added to PR-05; test for the crash window. KIT §4; DM E9; plan PR-05 |
| G12 | important | A separate `setProjectOutcome(old)` re-targets onto the survivor | Fixed: after a merge every `setProjectOutcome` on the merged project is dropped from the rewritten outbox and its last value fed into the outcome rule (re-issued only when the survivor has none, otherwise the full-text sync issue); compaction folds it into an unsent `createProject`; Replay and FirstSignInMerge tests incl. an outcome set after a local archive. KIT §3 |
| G13 | important | HMAC in a Linux-tested Core helper with no crypto | Fixed: Core keeps only `RecordContentForm` (canonical bytes of the user-visible fields, Linux-tested); the Mac target computes HMAC-SHA-256 with CryptoKit keyed by `installSalt`; review marks stay out of shared code (R4). R23 records the decision and which tests run where. KIT §8; DM E7.2; R23 |
| G14 | important | Keychain write failure owned by the wrong slice | Fixed: assigned to PR-05, which gains `BrainBuddyAPIClient.swift` and `APIError.swift`; on a token-store write failure `exchange` ends the session it just opened itself and throws `.tokenStorage` carrying the request's reference id; X-03 copy "Brain Buddy couldn't save your sign-in on this device. Try again."; no new `Kind` case. KIT §4; plan PR-05 |
| G15 | important | No Mac behaviour for an unreadable `store.json` | Fixed: new design screen **X-09** "Tasks couldn't be opened" (mirrors the iPhone's `RootView`): nothing syncs, "Try again", a confirmed "Start fresh…" sets the file aside with `resetUnreadableStore` (kept until sign-out); the import treats the workspace as in use; `UnreadableWorkspaceTests`; retention row for set-aside files. HOST §1, §9; D X-09; DM E5; plan US1, PR-08 |
| G42 | advisory | `open_task_count` scans all tasks per project | Fixed: PR-02 computes open counts for list routes in one pass, keyed by project id (`open_task_counts_by_project`). HTTP §1; plan PR-02 |
| G43 | advisory | Contract statements that do not match code | Fixed: `.unarchiveNameInUse(String)` is a distinct case, so `.duplicateProjectName`'s copy and the iPhone are unchanged; the first-upload age uses `LinkedAccount.linkedAt` (no `accountLinkedAt`); "stays 1" → "unchanged by 021"; single-flight `syncNow` and the timeout reference id are "kept, now tested". KIT §1, §2, §4, §6; DM E3, E5, E6 |
| G44 | advisory | Unarchive check order unstated | Fixed: "already active" is checked before `expected_revision` and returns 200 unchanged; pinned in the golden traces and pytest. HTTP §3; plan Test strategy |
| G45 | advisory | Web "until reload" window is wrong | Fixed: the window is from the PR-03 deploy until PR-06 is deployed; PR-06 deploys right after PR-03 and the gap is accepted (nothing is lost). HTTP §7; plan deploy order |

## testability-evidence (11)

| id | sev. | finding | disposition |
|---|---|---|---|
| G16 | important | SC-004 router sweep cannot fail | Fixed: `MacPresentationGuardTests` scans the Mac sources and fails when a presenting or focus API (`.sheet`, `.alert`, `.confirmationDialog`, `.popover(isPresented:`, `NSAlert`, `NSSound`, `UNUserNotificationCenter`, `NSApp.activate`, `makeFirstResponder`, focus assignment) appears outside the router and the listed user-initiated views; `SyncStatusLineModelTests` cover the 30 s re-describe, announce-once and the stable indicator slot; the router sweep stays as positive control. HOST §6, §8; plan US3, PR-09 |
| G17 | important | FR-009 pointer clause unverifiable | Fixed: as G04 (`ListPresentationHoldTests`, `021-FR-009`; host line) |
| G18 | important | Evidence gate by SHA ancestry | Fixed: evidence names the build by git tree hashes of the code it covers (`macos/` + kit for Mac, `ios/BrainBuddy/` + kit for iPhone), unchanged by a squash; the gate fails when they differ from the release commit; host records land in a docs-only commit after the slice; ASK PRs reference their candidate by tree hashes. Plan "Evidence protocol"; QS prerequisites |
| G19 | important | Agent work and human work not separated | Fixed: PR-07, PR-08 and PR-09 each have an automated lane and a host-evidence lane with the owner (Max), the ordering against ASK approval, and Linux vs macOS runtime marked per task; the PR-10 gate accepts evidence recorded after landing. Plan "Automated and host-evidence lanes" |
| G20 | important | PR-04 has no task lanes | Fixed: lanes (a) rules, (b) API, (c) fake server and traces, (d) pure helpers in parallel, (e) integration after (a) – (c), owning `Workspace.swift`; PR-04 stays one slice because the enum cases and their switches land together (G01). Plan "PR-04 task lanes" |
| G21 | important | Importer → sign-in seam untested | Fixed: the real importer writes a golden artifact `Tests/BrainBuddyWorkspaceTests/Resources/legacy-import-golden.json` (seeded ids, reproducible); the Mac test asserts byte equality; the kit's `FirstSignInMergeTests` signs in with it against overlapping names and asserts SC-003. Both files are in PR-08 (one TestFlight build on landing). IMPORT §6; KIT; plan PR-08; QS 4.10 |
| G22 | important | "Progressive" first load, 2 s import, 300 ms placeholders unverified | Fixed: the plan says the first pull is non-blocking but all at once (`listAllTasks`); a `Workspace` test holds the pull open with `HoldingTransport`; a generated 2,000-task fixture gated at 10 s in CI, the 2 s goal and the 300 ms placeholders are host-check lines. Plan Performance Goals, failure table; IMPORT §6; QS 4.12; D X-03 |
| G46 | advisory | iPhone scene-phase glue untested | Fixed: `Workspace.setForegroundActive(_:)` owns the ticker toggle and the forced foreground pull and is Linux-tested; the iPhone and the Mac call it; the manual line covers only the wiring. KIT §4; plan US1, PR-05, PR-07 |
| G47 | advisory | MacKeychainTests may skip silently | Fixed: the test creates and unlocks a temporary keychain and fails rather than skips; a deliberate disable must be a visible reasoned trait, and then the gate demands the full round-trip line in `manual-macos-status.md`. HOST §8; plan "Evidence protocol" |
| G48 | advisory | Importer only buildable on macOS | Fixed as an allowed implementation choice: the import rules that can fail on data (`ImportCanonicalizer`, `RecordContentForm`) moved into Core and are Linux-tested; a Foundation-only library target for the importer and state machine is permitted and left to the implementer, with the manifest and classifier re-run if taken. Plan "PR-08 task lanes"; R24 |
| G49 | advisory | No ledger for the 71 XCTest cases | Fixed: `tasks.md` must carry a ledger mapping each old test to its successor or a retirement reason, with explicit rows for the rules the reviewer named. Plan "XCTest ledger" |

## privacy-consent-security (9)

| id | sev. | finding | disposition |
|---|---|---|---|
| G23 | important | Privacy policy not updated for device copies | Fixed: PR-08 edits `PrivacyPolicyPage.tsx` and its test (classifier re-run: PR-08 stays SHIP mechanically, ASK semantically): one paragraph under "How long we keep it" (device copies until sign-out incl. after account deletion; deleting the Mac app keeps it; the pre-update copy ≥ 30 days and until sign-out; device and Time Machine copies cannot be erased by the server), an Erasure sentence, `LAST_UPDATED` bumped, both sentences asserted. DM "Privacy policy"; plan PR-08 |
| G24 | important | Backup deletion not visible; deleted during first-upload discard | Fixed: (a) `signOutBackupRemoved`, last, whenever the sign-out deletes the backup; (b) X-02 shows "Backup from before the update · removed when you sign out" once the date has passed, never a past date; (c) the backup is never deleted at a sign-out that discards operations of the first upload, nor while records were not carried (DM E8, four conditions); retention-table rows and verbatim tests. STATUS; DM E8; IMPORT §6; D X-02, X-04 |
| G25 | important | Pre-021 HTTP cache left on disk | Fixed: `LegacyCookieCleanup` also clears `URLCache.shared` and removes `~/Library/Caches/com.brainbuddy.mac.prototype/Cache.db*` and `fsCachedData`, once; test with an injected `URLCache`; retention row. HOST §1, §8; DM E8 |
| G26 | important | Staging and quarantined files without retention | Fixed: after every launch's terminal decision, staging files of any other attempt are deleted, and sign-out deletes all (invariant 5); test with a sidecar deleted mid-attempt; X-09 handles an unreadable `store.json` (G15); rows "macOS import staging file" and "macOS quarantined store files (removed by sign-out)". DM E5, E7.1, export summary; HOST §1 |
| G50 | advisory | Plain SHA-256 digests of the old file kept indefinitely | Fixed: `importedLegacyDigest` and the later-file digest are HMAC-SHA-256 keyed by `installSalt`; the 32-hex log guard stays. DM E7; R23 |
| G51 | advisory | Retention doc gaps | Fixed: `data-retention.md:40` → "(mobile, web, CRT, iOS and macOS)"; the Mac store row adds the display name; the export sentence names the Mac's device-only records. DM E5, export sentence |
| G52 | advisory | Pre-sign-in logout and cookie hosts | Fixed: FR-029's exception (G38); every `brainbuddy_session` cookie in the app's storage is deleted whatever its host, each queued logout bound to its own https host (localhost allowed; others deleted without a logout); `MacSyncFlowTests`: exactly one bodiless logout per cookie and nothing else. HOST §1, §8 |
| G53 | advisory | No owner-scoping test for `?state=` | Fixed: `test_021_FR_026_list_projects_state_is_owner_scoped` (second owner never appears; an owner with none gets 200 `[]`); HTTP §1 states it. HTTP §1; plan Test strategy |
| G54 | advisory | Evidence content-free rule not enforced | Fixed: `check_manual_evidence.py` fails on `/Users/`, `~/Library`, `Keychains/`, 32+ hex runs outside the tree-hash header fields, non-`@example.com` emails, or non-Markdown files; tests. Plan "Evidence protocol"; QS prerequisites |

## ux-accessibility-mobile (11)

| id | sev. | finding | disposition |
|---|---|---|---|
| G27 | important | X-02 Tab order and focus on open incomplete | Fixed: complete order (attention action incl. "Sign in…" and the failing notice's Copy → each issue's Copy → Copy outcome → Dismiss / Discard outcome → Sync now, skipped when disabled → offline last-failure Copy → Sign out… → backup, report, earlier-version "Show in Finder"); focus on open: attention action, else Sync now when enabled, else "Sign in…", else the first enabled control; "Show in Finder" closes the popover and focus returns to the status words. D X-02, "Keyboard and focus"; HOST §6; QS |
| G28 | important | Sign-out skips the unsaved-edit guard; count can change | Fixed: X-04 states "unsaved edit or capture draft" (today's discard confirmation runs first) and "changes arrived while open" (re-presented with the new count if it changed or the kit refuses a plain sign-out; "Sign out and remove" discards only the count shown). D X-04; HOST §7; plan US1; `MacSyncFlowTests`; QS |
| G29 | important | Attention states invisible with the sidebar hidden | Fixed (the reviewer's recommended option): X-01 "sidebar hidden": calm states show nothing; attention states show one compact toolbar item with the same words and glyph that opens X-02 and takes no focus, so "nothing in the toolbar" holds whenever all is well. Recorded under D "Planning review c2 additions" (the Sign-off itself is untouched). D X-01, affordance map; HOST §6; plan US3; router test; QS |
| G30 | important | "Rename…" opens an unspecified surface | Fixed: "rename archived project" rows on X-06 (existing rename sheet), M-02 (existing `ProjectEditorSheet`) and D-01 (the options popover's name field for the archived project): name selected, saving, clash error with focus kept in the field, success clears the refusal and returns focus to Unarchive, no automatic unarchive; Vitest and host lines. D X-06, M-02, D-01; plan US5 |
| G31 | important | Focus lost on D-01 unarchiving; error focus unstated | Fixed: D-01 "unarchiving" keeps the button focusable (`aria-disabled`, busy label in a polite status region); "error" announced (`role=alert`) with focus on Retry; "refused" announced with focus on Unarchive; Escape in the options popover returns focus to its button; X-06 "error" moves focus to Retry, announced; Vitest and axe. D X-06, D-01; plan US5 |
| G32 | important | Dismissing a kept outcome discards text with no warning | Fixed: the kept-outcome issue's button reads "Discard outcome" (named "Discard your outcome for “<project>”"), followed by "Outcome discarded · Undo" for 5 s, announced; listed under Destructive actions; STATUS test. D X-02, Destructive actions; STATUS; KIT §3; HOST |
| G55 | advisory | M-01 misses "first upload" and "error, then offline" | Fixed: both rows added with Settings › Sync equivalents; host lines. D M-01; plan US3; QS |
| G56 | advisory | Celebratory empty copy during first load | Fixed: X-01 "first load, empty list": "Your tasks are still arriving.", static, no spinner over content (`popoverFirstLoadEmpty` in the catalogue). D X-01, X-03; STATUS; plan US1 |
| G57 | advisory | Partial-failure copy says "server", not the project's state | Fixed: unarchive "Brain Buddy couldn't unarchive it, so it's still archived. Try Unarchive again later."; archive "Brain Buddy couldn't archive it, so it's still active. Try again later."; other commands keep the existing message. KIT §5; D X-06, M-02; `SyncIssueDescriberTests` |
| G58 | advisory | iPhone Copy reference ID has no VoiceOver path | Fixed: a VoiceOver custom action on the row; the account-less "Sign in to sync" row is at least 44 pt; host lines. D M-01; plan US3, PR-07; QS |
| G59 | advisory | X-03 "OK" missing from the affordance map | Fixed: row "X-03 · OK (account deletion cancelled) · closes the sheet; sync is already running · FR-017". D affordance map |

## adversarial-high-risk (9)

| id | sev. | finding | disposition |
|---|---|---|---|
| G02 | **blocking** | Import cannot succeed on realistic data and strands it | Fixed (see "Blocking findings") |
| G33 | important | Three mishandled launch states | Fixed: (a) row 10 → later file after a sign-out, never import; (b) the legacy rename runs only when `legacyRenamedAt` is unset (rows 8 – 9), so a restored original whose backup was removed lands in row 10 and is never renamed or deleted; (c) row 2 imports into an unwritten fresh workspace (no `store.json`, no `workspaceFirstWrittenAt`, no backup), consistent with FR-033's "a new workspace that nothing else has written"; tests for all three. DM E7.1; IMPORT §6; QS Scenario 6 |
| G34 | important | Keychain prompt vs FR-017, main-thread hang, no recovery from Deny | Fixed: spec Assumption (the system prompt may appear only at a person-started sign-in); background reads are non-interactive (`kSecUseAuthenticationUI` fail / `interactionNotAllowed`) so a rebuilt binary gets "Sign in again to sync" instead of a prompt; every Keychain call runs off the main actor; at a person-started sign-in, access denied or interaction-not-allowed deletes and re-adds the item; `MacKeychainTests` in a temporary keychain that fails rather than skips. Spec Assumptions; KIT §4; DM E9; R17; HOST §7, §8 |
| G60 | advisory | Pre-sign-in logout deviates from FR-029; logout host | Fixed: as G38 and G52 (FR-029 amended; logouts bound to the cookie's own https host; one-logout test) |
| G61 | advisory | Crash between destroy and session end orphans the session | Fixed: as G11 (pending logout recorded durably before the removal, withdrawn if the removal fails; crash test) |
| G62 | advisory | Rolling PR-03 back after 021 clients ship strips memberships | Fixed: HTTP §8 and the `docs/api-compatibility.md` runbook: once PR-04 has landed, PR-03 rolls forward only; the kit treats an archive reply with `archived_before_lossless: true` or `archived_at: null` as a clearing server and raises one sync issue instead of a silent strip. HTTP §8; KIT §4; plan rollback, failure table |
| G63 | advisory | Backup orphaned without the sidecar; overwriting rename; silent deletion | Fixed: the backup's import date falls back to its timestamped file name when the record is missing, and X-02 keeps surfacing it; the legacy → backup rename is exclusive (`renamex_np` with `RENAME_EXCL`); the deleting sign-out says so (G24). DM E7.1 invariant 3, E8; R5 step 6; STATUS |
| G64 | advisory | App Nap throttles the Mac's ticker | Fixed (decided explicitly): a `ProcessInfo` activity (`.userInitiatedAllowingIdleSystemSleep`) while signed in, ended at sign-out, so SC-001 holds with the window covered; the energy cost is accepted and named as a residual risk; occluded-window host line. R8; HOST §5; plan Complexity Tracking, Risks; QS |
| G65 | advisory | Web picker offers archived projects | Fixed: the task project picker lists active projects plus the task's own archived project, labelled "· archived" and selected, never as a new choice; Vitest in `TaskDetailPanel.test.tsx`; `AppShell` (the only consumer of `useProjects` on the account, agent and admin pages) splits active from archived. D D-01 "task project picker"; plan US5, PR-06 |

## Slice classes and paths

Classifier re-run at `a2f4827` over every slice's full path list: **no class changed**
(PR-01, PR-02, PR-05, PR-10 ASK mechanically; PR-08, PR-09 ASK semantically; PR-03,
PR-04, PR-06, PR-07 SHOW). Path counts: PR-01 5, PR-02 18, PR-03 6, PR-04 55, PR-05 22,
PR-06 19, PR-07 11, PR-08 43, PR-09 22, PR-10 8. Path changes are listed under the
classification table in plan "Delivery slices". PR-08 now writes under `ios/` (the golden
artifact and its kit test), so its landing produces one TestFlight build.

## Owner questions

None. The campaign raised no product decision, and the two c1 questions were decided under
delegation (`95ce8de`).

## Owner notes (for founder acceptance)

1. **New screen and states in approved surfaces**, each decided under delegation and listed
   in design.md "Planning review c2 additions": X-09 "Tasks couldn't be opened" (new id,
   no mockup; mirrors the iPhone's load-error view); X-01 "sidebar hidden" (toolbar item in
   attention states only) and "first load, empty list"; X-02 "Discard outcome" with Undo,
   the complete Tab order, the "removed when you sign out" backup line, "details changed";
   X-04 "backup removed", "unsaved edit or capture draft", "changes arrived while open";
   X-05 "partly carried over" and the softened "couldn't carry over" copy; "rename archived
   project" on X-06, M-02 and D-01; M-01 "first upload" and "error, then offline". The
   approved "Sign out?" text is unchanged.
2. **"Partial read" now imports what decodes.** The c1 plan treated any unconvertible
   record as an unreadable file; that was the plan's interpretation, not a sign-off item,
   and it stranded data (G02).
3. **Spec rewordings** (numbering unchanged, nothing lettered): FR-006, FR-007, FR-015,
   FR-020, FR-029, SC-004, US1-1, US4-5, the "Same-named archived projects" and FR-033 edge
   cases, and three Assumptions (timestamps; the pre-021 online-mode session; the Keychain
   prompt).
4. **Energy**: the App Nap activity keeps the Mac pulling every 30 s at most while it is
   open and signed in, also in the background.
5. **Clarifications Q1** still says the cadence "matches the iPhone's 60 s pull age"; left
   as the owner's record, as in c1 (R8 explains the 30 s age and 15 s tick).
