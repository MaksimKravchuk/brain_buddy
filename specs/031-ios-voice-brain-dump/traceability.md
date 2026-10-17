# Traceability: iPhone voice brain dump (031)

**Graded**: 2026-10-17 · **Implementation SHA**: `9a09fd2355d561953644a1cdf7f2f28129fa54f2` (main), plus one
uncommitted test (`031-SC-001 …`) in the working tree of `claude/project-thread-l3oml8`
**Auditor**: `acceptance-auditor` (did not write the code under grade)

Abbreviations:

- `VBDM` = `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/VoiceBrainDumpModelTests.swift` (suite "Voice brain dump model (spec 031)")
- `ST` = `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/SpeechTranscriptTests.swift` (suite "SpeechTranscript")
- **kit-run** = Linux Swift 6.2 docker run on 2026-10-17, `--filter "VoiceBrainDumpModelTests|SpeechTranscriptTests"`: 26 tests in 2 suites passed (log `/tmp/claude-0/-home-user-brain-buddy/435227cc-2c97-5d91-abe3-dae2adf2a86e/scratchpad/t3.log`)
- **ci-build** = CI on main for `9a09fd23` green, including the `ios-app` lane (app compiles) and the TestFlight upload. A build proves the code compiles, not how it behaves.
- **device-check** = Max (product owner) on TestFlight build `9a09fd23`, 2026-10-17: the voice button and sheet appear and work; several tasks said in a row become separate steps and are added; English works; **Russian speech is not recognised**. A manual check with no recorded steps, not an automated test.

Layer: `kit-model` = the platform-neutral `VoiceBrainDumpModel` with fakes; `kit-integration` = the model against a real
`Workspace` (in-memory store, no sync); `app` = SwiftUI / Apple-framework code under
`ios/BrainBuddy/Screens/Capture/Voice/`, `CaptureSheet.swift` and `ios/project.yml`, which has **no automated test**.
`docs/e2e-acceptance-charter.md` governs browser journeys only and sets no layer for native iOS claims.

| criterion | statement | test (file::name) | layer | evidence | status |
|---|---|---|---|---|---|
| 031-FR-001 | Capture glass bar shows the voice button on its leading side; tapping it opens the voice sheet, already listening | none | app (untested) | ci-build; device-check ("voice button and sheet appear and work"). The owner's device check is the only evidence. `check_requirement_coverage.py`: MISS | missing |
| 031-FR-002 | Voice sheet follows canvas cell M11 (layout, title, heard text with caret, step rows, footer, glass bar, Carry On tokens only) | none names 031-FR-002. `VBDM::sc003_copy` checks the copy constants only, not layout, caret, rows or tokens | app (untested) | ci-build; device-check (sheet appears, no layout or token comparison recorded). No snapshot test of the sheet. `check_requirement_coverage.py`: MISS | missing |
| 031-FR-003 | On-device recognition only; offers Russian and English, starting with the device language when it is one of them, else English | `VBDM::fr003_language_choice_and_locale` | kit-model | kit-run. The test proves `VoiceLanguage.preferred(_:)` maps codes and the model passes `ru-RU` / `en-US`. It does not test the app's input: `VoiceCaptureSheet.swift:31` feeds `Locale.current.language.languageCode`, which in an English-only app most likely resolves to `en`, not the device's Russian (inferred from code, not verified on device). device-check: Russian speech not recognised. `requiresOnDeviceRecognition = true` (`AppleSpeechCapture.swift:60`) is untested | weak |
| 031-FR-004 | Steps re-read from the whole heard text after each pause (debounced), replacing unedited steps, in the order said | `VBDM::fr004_debounced_live_reads`, `VBDM::fr004_restart_keeps_earlier_text`, `ST::` 6 tests named "031-FR-004 …" | kit-model | kit-run; asserts the 700 ms debounce, one extractor call for two quick results, the order, and stable step ids | covered |
| 031-FR-005 | Steps from the on-device model when available; one step per sentence otherwise or when the model fails | `VBDM::fr005_fallback_to_sentences`, `VBDM::fr005_sentence_extractor_rules` | kit-model | kit-run. The fallback when the extractor throws is tested. `AppleStepExtractor` throwing for an unsupported language (Russian) is app code and untested; reviewed by reading `AppleStepExtractor.swift:28` | covered |
| 031-FR-006 | Project shown and used only when it matches an existing active project (case-insensitive); day only when the model gives one | `VBDM::fr006_project_match_and_day`, `VBDM::fr009_workspace_port` (archived project excluded) | kit-model, kit-integration | kit-run | covered |
| 031-FR-007 | An edited step keeps its words; a removed step does not reappear (normalised match) | `VBDM::fr007_edited_step_is_kept`, `VBDM::fr007_removed_step_never_reappears` | kit-model | kit-run | covered |
| 031-FR-008 | "Add {n} to Inbox" for n listed steps; enabled when n > 0 and not saving; stops listening first | `VBDM::fr008_add_button` | kit-model | kit-run; asserts the title, `canAdd`, one `stop()` before capture, and the final words captured | covered |
| 031-FR-009 | Each step captured as its own task (Inbox, project, day), in order, stable editor id; on success sheet closes and toast "Added {n} to Inbox" | `VBDM::fr009_capture_each_step`, `VBDM::fr009_workspace_port` | kit-model, kit-integration | kit-run. Closing the sheet and showing the toast are app code and untested; the model reaches `.saved(count:)` and the toast copy is checked | covered |
| 031-FR-010 | On a failed capture, captured steps leave the list, the rest stay with the error | `VBDM::fr010_partial_failure` | kit-model | kit-run; includes a retry that reuses the editor ids | covered |
| 031-FR-011 | Tapping the live voice button stops and reads once more; with no step "Nothing to add yet." and the add button disabled | `VBDM::fr011_stop_reads_again`, `VBDM::fr011_nothing_to_add` | kit-model | kit-run | covered |
| 031-FR-012 | Closing with unadded words or steps asks "Discard what you said?"; the safe choice keeps everything | `VBDM::fr012_close_confirmation` | kit-model | kit-run. Tests the `needsCloseConfirmation` predicate and the copy. The dialog (`VoiceCaptureSheet.swift:52,59,72`) is app code and untested | covered |
| 031-FR-013 | No audio file written; no heard text or step logged or sent off the device; mic and speech usage descriptions declared | none | app (untested) | ci-build (TestFlight upload accepted, which needs the usage descriptions); `ios/project.yml:119-120` declare both keys (read, not tested). The no-file, no-log and no-send claims are untested. `check_requirement_coverage.py`: MISS | missing |
| 031-SC-001 | Three distinct actions become three Inbox tasks with one tap and no edit, offline and signed out | `VBDM::sc001_three_actions_one_tap` (**uncommitted**, not in `9a09fd23`) | kit-integration | kit-run (the uncommitted test passed). The test uses fake speech and the sentence extractor against an in-memory workspace with no sync. It calls `stop()` and then `add()`, which is two taps, not one. device-check: several English tasks became separate steps and were added; the check does not record offline or signed-out conditions, and Russian failed. No app-layer test | weak |
| 031-SC-002 | No network request is made by the voice sheet | none | app (untested) | Nothing measures network traffic. By reading: no `URLSession` or `http` in `Screens/Capture/Voice/` or `VoiceBrainDump/`, but the captures go through `Workspace`, whose sync is out of scope of this claim. `check_requirement_coverage.py`: MISS | missing |
| 031-SC-003 | Every sheet state (listening, review, empty, saving, saved, permission denied, unavailable) reached in the model's tests with fakes | `VBDM::sc003_main_phases`, `VBDM::sc003_speech_errors`, `VBDM::sc003_copy`, `VBDM::fr011_nothing_to_add` (empty) | kit-model | kit-run; each phase is asserted while it is held by a gate | covered |
| 031-SC-004 | An edited or removed step is never overwritten or revived by later speech | `VBDM::sc004_edits_and_removals_survive` | kit-model | kit-run | covered |
| US1-AS1 | Capture sheet open → glass bar shows voice button on its leading side; tapping it opens the voice sheet already listening | none | app (untested) | device-check only | missing |
| US1-AS2 | While talking, the heard words appear, the bar says "Listening", steps appear and update | `VBDM::fr004_debounced_live_reads`, `VBDM::sc003_copy` (status copy) | kit-model | kit-run (`heardText`, `.listening`, steps). Rendering untested; device-check | covered |
| US1-AS3 | "Add 3 to Inbox" → listening stops, each kept step captured, sheet closes, toast "Added 3 to Inbox" | `VBDM::fr008_add_button`, `VBDM::fr009_capture_each_step` | kit-model | kit-run. The sheet closing and the toast are untested app code; device-check | covered |
| US2-AS1 | Edited step keeps its words; later speech never overwrites it | `VBDM::fr007_edited_step_is_kept`, `VBDM::sc004_edits_and_removals_survive` | kit-model | kit-run | covered |
| US2-AS2 | × removes a step, it does not return, the add count drops | `VBDM::fr007_removed_step_never_reappears`, `VBDM::sc004_edits_and_removals_survive` | kit-model | kit-run. The count follows `steps.count`; no direct `addTitle` assertion after a removal | covered |
| US3-AS1 | Tapping the live voice button stops, re-reads everything, sheet stays open for review | `VBDM::fr011_stop_reads_again` | kit-model | kit-run | covered |
| US3-AS2 | Nothing actionable heard → sheet says so, add disabled | `VBDM::fr011_nothing_to_add` | kit-model | kit-run | covered |
| US4-AS1 | Words heard and not added → closing asks first; the safe choice keeps everything | `VBDM::fr012_close_confirmation` | kit-model | kit-run (predicate); dialog untested | covered |
| EC-1 | Permission denied: nothing recorded; sheet says how to allow it in Settings | `VBDM::sc003_speech_errors` | kit-model | kit-run (phase and copy). "Nothing recorded" falls under 031-FR-013 (missing) | covered |
| EC-2 | Recognition unavailable for the chosen language: sheet says so and offers the other language | `VBDM::sc003_speech_errors` | kit-model | kit-run; asserts "Try English" restarts listening | covered |
| EC-3 | Model fails or unavailable: steps from sentences, sheet keeps working | `VBDM::fr005_fallback_to_sentences` | kit-model | kit-run | covered |
| EC-4 | A step names a project that does not exist: no project | `VBDM::fr006_project_match_and_day` ("Kitchen" → nil) | kit-model | kit-run | covered |
| EC-5 | A save fails part way: saved steps leave, rest stay with the error | `VBDM::fr010_partial_failure` | kit-model | kit-run | covered |

**Totals**: 30 criteria (13 FR, 4 SC, 8 acceptance scenarios, 5 edge cases). 23 covered, 2 weak, 5 missing.
