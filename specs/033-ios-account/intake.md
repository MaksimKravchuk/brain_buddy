# Business Intake: iPhone account screens and invite step

**Feature**: `specs/033-ios-account/`
**Recorded**: 2026-10-16
**Owner**: Max (product owner)
**Status**: Scope approved by Max; open details decided by the planner under Max's
standing rule (2026-10-16) "don't wait for my yes on things you can judge yourself;
ask only for irreversible steps". Each decision is listed below so Max can overturn it.

Assessment was skipped: the ask brings to the iPhone account rights the product already
provides on the web (`AccountService` and spec 023 modern authentication, never
feature-flagged), drawn on the Carry On design canvas.

## The ask, as given

The iOS design thread finished the Carry On restyle and listed the canvas screens that
still need new iPhone features (`/mnt/project-files/design/ios-next-features.md`).
Max asked (2026-10-16, verbatim): "А, ну верни это оркестратору, пусть он запускает
агентов, которые будут это делать." — hand the remaining screens to the coordinator to
build. This feature takes **Account 25–28** (profile, sign-in methods, change email,
delete) and **invite 06** (ADR-0032). Agents (21–24, 29–30) are spec 034, first run is
032 and voice is 031.

Design input: the canvas https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6, iPhone row,
cells M06, M25, M26, M27, M28 (design data).

## Decisions taken by the planner (2026-10-16)

| # | Question | Decision | Why |
|---|---|---|---|
| D1 | Native or web for email, password, Apple/Google, export and delete? | Native, as the boards draw them. The web hand-off rows ("Manage account", "Delete account" opening the browser) go away. | Max approved building these screens on the iPhone; the backend already offers every call (spec 023). |
| D2 | Boards draw no "confirm it's you" step, the server requires one. | A glass sheet in the style of boards 27/28: current password, a code to the account's own email, or Apple/Google — only methods already on the account. | The server refuses every change without a recent proof; the web does the same. |
| D3 | Board 06 draws six boxes for the invite code. | One wide field. | Real invite codes are 43-character tokens (`python -m app.cli create-invite`); six boxes cannot hold them. The six boxes are used where codes are six digits: email codes (board 27). |
| D4 | Where does Sign out live? | On the Account screen, at the bottom, as board 25 draws it. Settings keeps the Account row. | Board 25. |
| D5 | Agents group on board 25. | Left out here; spec 034 adds it to the same screen. | Separate feature and thread. |
| D6 | Feature flag? | None. | Account rights are never feature-flagged (`AccountService`, docs/data-retention.md). |
| D7 | Name editing (board draws a row with a chevron, no edit screen). | A small sheet with one field and Save. | The server supports it; a chevron promises an action. |
