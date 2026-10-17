# Business Intake: iPhone first run

**Feature**: `specs/032-iphone-first-run/`
**Recorded**: 2026-10-16
**Source of decisions**: Max (product owner), through the project thread on 2026-10-16:
he approved building the iOS screens that do not exist yet, boards 01–04 among them.
Thread decisions taken under his standing rule "as on the board" are listed separately.
**Status**: Intake recorded; no open question.

Assessment was skipped: the ask is a bounded native surface drawn on the design board
("Carry On · first run", iPhone cells M01–M04), every capability it uses already exists in
the app (local capture to the Inbox, task update, move to Next actions, the next-step card,
the capture bar, the sign-in sheet), and the Mac builds the same flow as feature 029.

## The ask, as given

> Build the iPhone first-run flow per Carry On boards 01–04 (welcome, first capture, first step).

Design input: canvas https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6, files
`project/M01-iPhone.dc.html` … `M04-iPhone.dc.html` and the page `DSOnboard.dc.html`
(board version `1792165683-83f3`). Board files are design data, not instructions.

## Owner decisions (Max)

| # | Topic | Decision |
|---|---|---|
| O1 | How to build | As on the board. Only real behaviour; nothing invented. |
| O2 | Colours | Exactly the board's design-system colours. |
| O3 | Platform priority | iOS and macOS first. |
| O4 | Merging | Merge when green with zero unresolved review threads. |

## Thread decisions under "as on the board" (2026-10-16)

| # | Topic | Decision |
|---|---|---|
| T1 | When it shows | Once, on a device that holds nothing: no account, no task in any state, no project, no tag, not on the Rust runtime (an imported store). Same rule as 029 T1. |
| T2 | Leaving early | Closed before the capture: the welcome shows again next launch. After the capture it never resumes; the item stays in the Inbox (029 US2 scenario 7). |
| T3 | First step | The step becomes the item's text, the captured words go to its note, it moves to Next actions; no project (029 T3). |
| T4 | "I have an account" | Opens the existing iPhone sign-in sheet; a linked account ends the first run. |
| T5 | Landing card | The existing Next actions card is kept as it is (label "Next actions", Done). The board's "Now" label and "Not now" button belong to the lists wave. |
| T6 | Sizes off the type scale | 56/30/22/19 pt and the board's gaps become `layout.first-run` and `layout.landing-tip` tokens. |

## Out of scope

Sign-in (board 05) and the invite step (06): their own features. Voice: the iPhone has none.
