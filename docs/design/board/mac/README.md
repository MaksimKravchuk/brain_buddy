# Carry On board: Mac screens

PNG renders of the Mac cells of the Carry On design board, so an agent that cannot open
claude.ai can compare the running app with the design. The board itself stays the source of
truth (https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6); these files are a snapshot of it.

- **Board version:** `1792165683-83f3`, rendered 2026-10-17 at 2x in Chromium with the
  board's own fonts (Instrument Sans / Instrument Serif). Colours are quantized to 256 per
  image to keep the files small, so read exact colour values from the token pages, not by
  sampling a screen render.
- Each screen shows a 1280×800 Mac window with the number, title and a one-line caption.
  Where a cell shows a dark window too (M09, M20), both are in the same PNG.
- If the board changes, ask for a re-render; do not edit these files by hand.

## Screens

| File | Screen | Feature |
|---|---|---|
| `M01-Mac.png` | 01 Welcome | 029 first run |
| `M02-Mac.png` | 02 First capture | 029 first run |
| `M03-Mac.png` | 03 First step | 029 first run |
| `M04-Mac.png` | 04 Landing | 029 first run |
| `M05-Mac.png` | 05 Sign in | 029 first run |
| `M06-Mac.png` | 06 Invite | 029 first run |
| `M07-Mac.png` | 07 Inbox | core |
| `M08-Mac.png` | 08 Next actions | core |
| `M09-Mac.png` | 09 Project (light and dark) | core |
| `M10-Mac.png` | 10 Create task | core |
| `M11-Mac.png` | 11 Voice capture | core |
| `M12-Mac.png` | 12 Quick capture | core |
| `M13-Mac.png` | 13 Next action (inspector) | core |
| `M14-Mac.png` | 14 Date picker | core |
| `M15-Mac.png` | 15 Not now | core |
| `M16-Mac.png` | 16 Inbox item | core |
| `M17-Mac.png` | 17 Clarify with AI | core |
| `M18-Mac.png` | 18 Waiting | core |
| `M19-Mac.png` | 19 Someday | core |
| `M20-Mac.png` | 20 Done (light and dark) | core |
| `M21-Mac.png` | 21 Hand off | 030 agents |
| `M22-Mac.png` | 22 Agent runs | 030 agents |
| `M23-Mac.png` | 23 Needs you | 030 agents |
| `M24-Mac.png` | 24 Result | 030 agents |
| `M25-Mac.png` | 25 Account | 028 settings |
| `M26-Mac.png` | 26 Sign-in methods | 028 settings |
| `M27-Mac.png` | 27 Change email | 028 settings |
| `M28-Mac.png` | 28 Delete account | 028 settings |
| `M29-Mac.png` | 29 Agent details | 030 agents |
| `M30-Mac.png` | 30 Add agent | 030 agents |

## Design-system pages

| File | Page |
|---|---|
| `DSFoundations.png` | Foundations: colour tokens (light and dark), type, spacing |
| `DSComponents.png` | Components |
| `DSMac.png` | Mac specifics: window, sidebar, toolbar, sheets |
| `DSCard.png` | The task card |
| `DSOnboard.png` | First run |
| `DSAccount.png` | Account and agents in Settings |
| `DSAgents.png` | Agents: hand-off, runs, states |

The colour tokens in code come from `ios/BrainBuddyKit/DesignTokens/carry-on.tokens.json`
(generated into `BrainBuddyDesign/Generated/`). Use only those tokens; never add a new colour
to match a render.
