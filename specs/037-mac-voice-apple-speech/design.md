# Design: Mac voice on Apple speech, Whisper on request

Built only from components the Mac app already has (Carry On design system, boards M11-Mac and
M25–M27 Settings). No new colour, font or component. The voice sheet keeps board 11's layout.

## Screens and states

### V-01 Voice sheet (board 11, Mac) — changed only where noted

| # | State | What is shown |
|---|---|---|
| V-01a | Idle, chosen language recognised by Apple | As today. Language chips: preferred languages (≤3, plus English). |
| V-01b | Idle, Whisper downloaded | As V-01a plus an "Auto" chip at the end. |
| V-01c | Idle, chosen language needs Whisper, none downloaded | Under the chips, a secondary note (`MacSheetStatus`, secondary tone): "Russian needs Whisper, a free speech model you can download (about 145 MB)." with a `.macText` button "Download in Settings…". The voice button is disabled. |
| V-01d | Recording | As today. |
| V-01e | Transcribing | As today; status "Transcribing on this Mac…". With Whisper the first run still shows "Loading local speech model…". |
| V-01f | Speech recognition not allowed | Error line (danger tone, as today's errors): "Speech recognition is off for Brain Buddy. Turn it on in System Settings › Privacy & Security › Speech Recognition." |
| V-01g | Error from the recogniser | Error line with the system's message, as today. |

### S-05 Settings › Voice (new tab after Sync)

Tab button: the board mic glyph (`MacMicGlyph`, as on the toolbar mic) and "Voice", same as the
other tabs. Content uses `SettingsRow` like the Account tab, 40 pt side padding.

| # | State | Rows |
|---|---|---|
| S-05a | Not downloaded | **Speech** — "Apple speech recognition, on this Mac". **Whisper** — "Not downloaded" · secondary line "For languages Apple doesn't recognise on this Mac, and Auto. About 145 MB from Hugging Face. What you say never leaves this Mac." · trailing `.carryOnSecondary` "Download". |
| S-05b | Downloading | **Whisper** — "Downloading… 42%" with a small determinate `ProgressView` · trailing "Cancel". |
| S-05c | Downloaded | **Whisper** — "Downloaded" · same secondary line · trailing "Remove". |
| S-05d | Failed | **Whisper** — `MacSheetStatus` danger: "Couldn't download Whisper: <reason>" · trailing "Try again". |

Keyboard: every button is reachable with Tab; VoiceOver reads each row label and value together
(`SettingsRow` already combines them).

## Copy

All new strings are English, plain, and live in `VoiceSettingsCopy` (BrainBuddyMacCore) so
tests read them without rendering.
