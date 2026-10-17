# Acceptance: iPhone voice brain dump

**VERDICT**: reject
**Feature**: `specs/031-ios-voice-brain-dump/`
**Graded**: 2026-10-17  **Implementation SHA**: `9a09fd2355d561953644a1cdf7f2f28129fa54f2` (plus one uncommitted test, `031-SC-001 …`, in `VoiceBrainDumpModelTests.swift` on `claude/project-thread-l3oml8`)
**Auditor**: `acceptance-auditor` (did not write the code under grade)

Writer-owned pre-freeze evidence is a separate artifact validated by
`scripts/validate_pre_freeze_receipt.py`; this post-freeze acceptance verdict
must not substitute for it. Review, QA, CI, landing, deploy, and smoke are
post-freeze obligations under ADR-0008.
<!-- BrainBuddy pre-freeze receipt contract: acceptance. Preserve this section. -->

## Tally

| | count |
|---|---|
| criteria total | 30 (13 FR, 4 SC, 8 acceptance scenarios, 5 edge cases) |
| covered | 23 |
| weak (a test exists but does not exercise the claim) | 2 (031-FR-003, 031-SC-001) |
| missing | 5 (031-FR-001, 031-FR-002, 031-FR-013, 031-SC-002, US1-AS1) |
| hollow tests found | 0 |

Full matrix: `traceability.md`

## Why reject

The skill's rule is to reject when any criterion is `missing`. Five are missing, and
`check_requirement_coverage.py` fails on four of them. Everything the kit model decides is well tested: the
debounced re-reads, edits and removals, the fallback, project matching, partial saves and every phase. Everything the
**app layer** does has no automated test: the voice button, the sheet's layout and tokens, the Apple speech and
Foundation Models adapters, the privacy claims and the usage descriptions. For FR-001, FR-002 and US1-AS1, the only
evidence is Max's device check on TestFlight build `9a09fd23`. For FR-013 and SC-002 there is no evidence at all
beyond compilation and reading the code.

**Owner decision, reported and not recorded as a waiver.** The caller reports that on 2026-10-17 Max decided to
accept the interface now and to tune voice-input quality, Russian included, as separate follow-up work. That is a
product decision this audit can record. It is not a waiver. It reached the auditor through another agent, not from
Max. A waiver needs a human, and an auditor cannot waive its own finding. If Max signs the waivers below in this file
himself, the missing UI criteria can rest on his device check. The requirement-coverage gate will still fail until
tests name the four ids.

## Blockers

1. **031-FR-001** (and **US1-AS1**): no test shows the voice button in the capture glass bar's leading slot, or that
   tapping it opens the sheet already listening.
   - would satisfy it: an XCUITest or app-target Swift Testing test named `031-FR-001 …` that opens capture, finds
     the "Talk" button on the bar's leading side, taps it, and asserts the voice sheet with the status "Listening"
     (fake speech injected). Or a waiver signed by Max in the Waivers table, resting on a recorded device check.
2. **031-FR-002**: no test of the sheet's layout against cell M11, of the caret, of the step rows, or that it uses
   Carry On tokens only. `sc003_copy` checks the copy strings, nothing more.
   - would satisfy it: a snapshot test of `VoiceCaptureSheet` in listening, review and empty states, named
     `031-FR-002 …`, using `BrainBuddyDesignTestSupport.assertSnapshot` with a reference approved against M11 (the
     same mechanism as `CarryOnCatalogSnapshotTests`, run in the `ios-app` lane).
3. **031-FR-013**: no test that no audio file is written, that no heard text or step is logged or sent, or that the
   usage descriptions are declared.
   - would satisfy it: a test named `031-FR-013 …` asserting `NSMicrophoneUsageDescription` and
     `NSSpeechRecognitionUsageDescription` in `ios/project.yml` (for example a `scripts/` pytest), plus a test or
     static check that the `Voice/` and `VoiceBrainDump/` sources write no file (`AVAudioFile`, `write(to:)`) and
     log no transcript (`Logger`, `print`, `os_log`).
4. **031-SC-002**: nothing measures network traffic from the voice sheet.
   - would satisfy it: a test named `031-SC-002 …` that runs a full voice session (start, say, stop, add) against a
     `Workspace` whose transport is a counting stub (for example `BrainBuddyFakeServer`'s `StubServer` / URLProtocol)
     and asserts zero requests from the voice path, or a static import check over `Voice/` and `VoiceBrainDump/`
     that rejects networking APIs. State which one it is.
5. **031-FR-003 (weak)**: the test covers the language-code mapping, not the device language the app passes in.
   `VoiceCaptureSheet.swift:31` uses `Locale.current.language.languageCode`. In an English-only app that most likely
   resolves to `en` for a Russian-speaking user, which fits Max's report that Russian speech is not recognised
   (inferred from code, not verified on device).
   - would satisfy it: take the language from a source that reflects the device language (for example the first of
     `Locale.preferredLanguages`) through an injectable seam, with a test named `031-FR-003 …` asserting that a
     Russian-first device starts in Russian. Plus a device re-check of Russian recognition via the language menu, so
     a wrong default can be told apart from recognition failing.
6. **031-SC-001 (weak)**: the only test is **uncommitted**, so it is not part of the graded SHA. It uses fake speech
   and calls `stop()` and then `add()`, which is two taps, where the criterion says one. The device check confirms the
   English journey but does not record offline or signed-out conditions.
   - would satisfy it: commit the test, change it to reach the saved state with `add()` alone (no `stop()`) and assert
     three Inbox tasks. Then either an app-layer test of the same journey, or a device check signed by Max that records
     airplane mode and signed out.

## Evidence

| check | command | result |
|---|---|---|
| product-e2e stories | `validate_ci_artifacts.py product-e2e-results --path frontend/allure-results/playwright` | not applicable: iOS-only feature, no web product story. Not run, and not counted as a pass |
| result freshness | Linux kit run on 2026-10-17 vs impl commit `9a09fd23` (2026-10-16T23:08:48Z) | pass for the kit tests (26/26, log `/tmp/claude-0/-home-user-brain-buddy/435227cc-2c97-5d91-abe3-dae2adf2a86e/scratchpad/t3.log`). The `031-SC-001` test ran from the uncommitted working tree, not from a committed SHA. The Allure `--since-file` check does not apply: Swift Testing emits no Allure results |
| allure taxonomy | `validate_allure_taxonomy.py` | not applicable: the Swift kit tests produce no Allure store. Not counted as a pass |
| requirement coverage | `python3 scripts/check_requirement_coverage.py specs/031-ios-voice-brain-dump` | **fail**: 4 of 17 unmapped (031-FR-001, 031-FR-002, 031-FR-013, 031-SC-002) |
| backend coverage | — | not applicable (no backend change) |
| frontend coverage | — | not applicable (no frontend change) |
| app build | CI on main for `9a09fd23`, `ios-app` lane plus TestFlight upload | pass (compiles only; not behavioural evidence) |
| device check | Max, TestFlight `9a09fd23`, 2026-10-17 | button and sheet work; English steps split and added; Russian not recognised |

## Measured criteria

| criterion | target | measured | source | tier |
|---|---|---|---|---|
| 031-SC-001 | 3 actions → 3 Inbox tasks, one tap, offline, signed out | 3 → 3 in a kit-integration test with fake speech, two taps (`stop` then `add`); English on device, conditions not recorded | `VBDM::sc001_three_actions_one_tap` (uncommitted); device-check | n/a: on-device feature, no INTERNAL/PUBLIC-ON tier and no `voice_evidence_report.py` run (that report measures the server voice path, which this feature does not use) |
| 031-SC-002 | 0 network requests | not measured | — | n/a (see SC-001) |
| 031-SC-003 | every state reached with fakes | all 7 phases asserted | `VBDM::sc003_main_phases`, `VBDM::sc003_speech_errors` | n/a (see SC-001) |
| 031-SC-004 | 0 overwrites or revivals | 0 across two later reads and a stop | `VBDM::sc004_edits_and_removals_survive` | n/a (see SC-001) |

No `voice_evidence_report.py` run exists whose SHA equals `9a09fd23`. None of these criteria is a provider-quality
measurement, so I do not list a missing report as a blocker. Voice-quality tuning, including Russian, is the owner's
declared follow-up.

## Design state coverage

| design state id | tested by | status |
|---|---|---|
| V-01 voice button in capture bar | none | missing (device-check only) |
| V-02.1 Starting | `VBDM::fr008_add_button`, `VBDM::sc003_main_phases` | covered (model phase; rendering untested) |
| V-02.2 Listening | `VBDM::sc003_main_phases`, `VBDM::fr004_debounced_live_reads` | covered (model; caret untested) |
| V-02.3 Finishing | `VBDM::sc003_main_phases` (held by a gate) | covered (model) |
| V-02.4 Review | `VBDM::fr011_stop_reads_again` | covered (model) |
| V-02.5 Nothing heard | `VBDM::fr011_nothing_to_add` | covered (model) |
| V-02.6 Saving | `VBDM::sc003_main_phases` (held by a gate; edits ignored) | covered (model; dimming untested) |
| V-02.7 Permission denied | `VBDM::sc003_speech_errors` | covered (model and copy; "Open Settings" untested) |
| V-02.8 Unavailable | `VBDM::sc003_speech_errors` | covered (model, copy and "Try English" restart) |
| V-02.9 Save failed | `VBDM::fr010_partial_failure` | covered (model) |

No sheet state has a rendering test. The states are proved where the model decides them.

## Spot-checked for hollowness

| test | would it still pass with the feature deleted? |
|---|---|
| `VBDM::sc003_copy` | No: it would not compile, and it pins the design copy. But it only proves constants. It says nothing about the sheet showing them, so it gives FR-002 no support |
| `VBDM::fr012_close_confirmation` | No: it asserts the predicate flips only once words exist, that `cancel()` keeps the text and steps, and that later speech is ignored. The dialog itself is untested |
| `VBDM::sc001_three_actions_one_tap` (uncommitted) | No: it drives the real `SpeechTranscript`, `SentenceStepExtractor` and `Workspace`, and asserts three Inbox tasks with the exact titles. It does not prove "one tap" (it calls `stop()` first) or anything on the device |
| `VBDM::fr003_language_choice_and_locale` | No for the mapping. But it would still pass if the app passed the wrong locale source, which is the suspected Russian defect |

## Waivers

| criterion | why it is not tested | approved by |
|---|---|---|
| — | No waiver is recorded. Max's reported decision (accept the interface now; voice quality and Russian as follow-up) belongs here only if Max enters it himself, per criterion (031-FR-001, 031-FR-002, US1-AS1 resting on his device check). 031-FR-013 and 031-SC-002 have no device evidence to rest on | — |

<!-- A waiver needs a human. An auditor cannot waive its own finding. -->
