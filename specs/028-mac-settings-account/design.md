# Design: Mac Account and Settings window (⌘,)

**Feature**: `specs/028-mac-settings-account/`
**Spec**: [spec.md](spec.md) (Clarifications settled with Max: 2026-10-16)
**Screen source**: Mac design board, version `1792138611-15e1` — cell **M25** ("Settings
(⌘,), Account tab.") for the window, the tab bar and the Account tab. Cells M26–M28
belong to the follow-up feature and are not designed here. No separate HTML mockup is
produced: M25 is the approved render, and every deviation from it is listed in
[Deviations from M25](#deviations-from-m25).
**Human sign-off**: pending — Max to confirm this state inventory before
`/speckit-review`.

<!-- Ids are stable once written; never renumber. ADR-0006: the term is Tag. -->

## Applicability

One new macOS window with three tabs. It reuses the existing Mac surfaces for
everything that already exists: the sign-in sheet (021 X-03), the sign-out
confirmation (021 X-04) and the sync status popover content (021 X-02). New UI is
limited to the window, its tab bar, the Account tab rows, the export progress and
error states, and the Agents tab's empty state.

S- ids are this feature's Mac Settings surfaces. State keys combine screen id and
suffix, for example `S-02.05`.

## Screen inventory

| id | surface | screen | purpose | FR refs |
|---|---|---|---|---|
| S-01 | Mac, the app's Settings window (⌘,, app menu › Settings…) | Settings window and tab bar | One window with the board's tabs Account, Agents, Sync | 028-FR-001, 028-FR-002, 028-FR-021, 028-FR-022, 028-FR-023 |
| S-02 | S-01 › Account | Account tab | Account state, Export…, sync words and Sign out… | 028-FR-003 – 028-FR-018 |
| S-03 | S-01 › Agents | Agents tab | Say agents are managed on the web for now; open the web agents page | 028-FR-019 |
| S-04 | S-01 › Sync | Sync tab | The existing sync status popover content (021 X-02), unchanged | 028-FR-020 |

Reused, unchanged: 021 X-03 sign-in sheet (opened by S-02 "Sign in…" and "Sign in
again…", on the main window), 021 X-04 sign-out confirmation (opened by S-02 "Sign
out…" and S-04 "Sign out…", on the main window), the macOS save panel.

## Layout (from M25)

- **Window**: the authoritative M25/M29 PNG shows a standard macOS Settings window
  opening at 820 × 620 pt outer size. The content retains its 420 pt minimum height;
  native title/toolbar chrome adds to that minimum, and tabs scroll when shortened.
  Background `bg-ground`. Title = the selected tab's name ("Account", "Agents", "Sync").
- **Tab bar** (S-01): the window's toolbar, centred, three items of glyph (20 pt,
  stroke 1.8, round caps, from the board's SVGs: a person; a rounded robot head with an
  antenna; two circling arrows) over a 12 pt label. Selected item: label semibold and a
  `control-quiet` rounded rectangle, 70 × 50 pt with the existing 8 pt radius; others
  `text-secondary`. The small native title stays above the tabs. The shared glass
  capsule is hidden; native regular material over `bg-ground` gives the warm header.
  The toolbar remains native, with its existing keyboard and accessibility behavior.
- **Content** (S-02): padding 22 pt top/bottom, 40 pt sides, 14 pt type. Each row is a
  three-column grid: a 150 pt right-aligned `text-secondary` label, the value in
  `text-primary`, and an optional trailing control. Row padding 6 pt; groups separated
  by a 1 pt `control-quiet` rule with 8 pt margins.
- **Trailing control**: the secondary button (`button-secondary-bg` / `-fg`, pressed
  `button-secondary-bg-pressed`), 28 pt tall, 13 pt label, 12 pt side padding.
- **Name value**: read-only text in a `surface-card` box, 6 pt corner radius, 5 × 8 pt
  padding, 220 pt wide, as drawn. It is static text, not a text field.
- **Error and attention words**: `status-danger` for an error line, always with words;
  never color alone.
- Colors are design-system roles only (`CarryOnColorStyle`), light and dark.

## State inventory

### S-01 — Settings window and tab bar

| key | state | what shows | FR |
|---|---|---|---|
| S-01.01 | Opened the first time in an app session | Window on the Account tab (S-02) | 028-FR-001, 028-FR-002 |
| S-01.02 | Opened again | Window forward on the tab last chosen in this app session | 028-FR-001, 028-FR-002 |
| S-01.03 | Tab chosen | That tab's content; window title becomes the tab name | 028-FR-002 |
| S-01.04 | Closed (⌘W, close button) | Window closes; an export in progress is cancelled (S-02.12) | 028-FR-001, 028-FR-013 |

### S-02 — Account tab

Rows in board order. "—" means the row has no trailing control.

**S-02.02 Loaded (signed in, everything read)** — M25 without the follow-up controls:

| label | value | trailing control |
|---|---|---|
| Name | display name, or "Not set" (read-only box) | — |
| Steps taken | completed-step count, e.g. "214" | — |
| *(rule)* | | |
| Email | "max@example.com · Verified" or "max@example.com · Unverified" | — |
| Apple | "Connected", "Connected · unavailable" or "Not connected" | — |
| Google | same as Apple | — |
| Password | "Set · also used for Mac sign-in" or "Not set" | — |
| *(rule)* | | |
| Your data | "A ZIP of everything, without secrets" | Export… |
| *(rule)* | | |
| *(no label)* | sync status words from the existing status line (e.g. "Synced a minute ago") | Sign out… |

| key | state | what shows | FR |
|---|---|---|---|
| S-02.01 | Loading | Each value cell shows a small progress indicator and "Loading…" (static under Reduce Motion); Export… disabled; footer as S-02.02 | 028-FR-004 |
| S-02.02 | Loaded | Table above | 028-FR-006 – 028-FR-010, 028-FR-012, 028-FR-014 |
| S-02.03 | Methods unavailable (account read ok, methods read failed or 404/503) | Name, Steps, Email address show; "· Unavailable" after the email; Apple, Google, Password read "Unavailable"; one line under the Password row: "Sign-in methods couldn't be loaded." with Try again | 028-FR-008, 028-FR-009, 028-FR-010, 028-FR-017 |
| S-02.04 | Offline | Rows replaced by "Your account details need a connection." and Try again; footer (sync words, Sign out…) stays | 028-FR-016 |
| S-02.05 | Session ended (401, or the sync line reports the session ended) | Rows replaced by "Your session ended." / "Unsent changes stay on this Mac." and Sign in again…; footer stays | 028-FR-016, 028-FR-005 |
| S-02.06 | Not signed in | Rows replaced by "Not signed in" and Sign in…; no footer Sign out… | 028-FR-015 |
| S-02.07 | Server error / rate-limited | Rows replaced by "Your account details couldn't be loaded." with Try again and, when present, "Reference: <correlation id>"; 429 adds "Try again in a few minutes." and no automatic retry | 028-FR-017 |
| S-02.09 | Exporting (first step after Export…) | "Your data" value becomes "Exporting…" with an indeterminate progress indicator (static under Reduce Motion); Export… is replaced by Cancel | 028-FR-012 |
| S-02.08 | Save panel open (after S-02.09 completes) | macOS save panel, file name prefilled with the server's suggested name; Cancel in the panel → S-02.12 | 028-FR-012 |
| S-02.10 | Exported | "Your data" value reads "Saved." for 5 s, then returns to S-02.02; Export… available again | 028-FR-012 |
| S-02.11 | Export failed | "Your data" value reads the failure in words — "Couldn't export. Check your connection." (offline), "Couldn't save the file there." (not writable / disk full), "Couldn't export." (server) — plus "Reference: <id>" when present; trailing control Try again | 028-FR-013, 028-FR-017 |
| S-02.12 | Export cancelled (Cancel or window closed) | Back to S-02.02; nothing written | 028-FR-013 |
| S-02.13 | Sign out… chosen | Main window comes forward; its unsaved-edit guard runs, then 021 X-04; Settings unchanged until the outcome | 028-FR-014 |
| S-02.14 | Signed out (from Settings, menu or popover) | S-02.06; previous account details gone | 028-FR-005, 028-FR-015 |
| S-02.15 | Account changed while open | Back to S-02.01 for the new account; a late response for the previous account is discarded | 028-FR-005 |

Settings never shows in any S-02 state: Change…, Connect…, Remove…, Delete account…,
the deletion row, or a "Manage on the web…" button (028-FR-011, 028-SC-008).

### S-03 — Agents tab

| key | state | what shows | FR |
|---|---|---|---|
| S-03.01 | Ready | Centred: "Agents are managed on the web for now." and the secondary button "Open agents on the web…" | 028-FR-019 |
| S-03.02 | Reading the web origin | Same text; button disabled until the origin arrives | 028-FR-019 |
| S-03.03 | Origin unavailable or not https (or http on localhost) | Same text; button disabled; "The agents page can't be opened right now." with Try again | 028-FR-019 |
| S-03.04 | Button pressed | Default browser opens `<origin>/settings/agents`; Settings stays open | 028-FR-019 |

### S-04 — Sync tab

| key | state | what shows | FR |
|---|---|---|---|
| S-04.01 | Any sync state | The 021 X-02 popover content for the current state — last sync, what waits, notices, issues with their actions, "Sync now", the account email and "Sign out…" (or "Sign in…") — laid out in the tab at the popover's width, with its own scroll; every action behaves as in the popover | 028-FR-020 |

## Copy

| key | text |
|---|---|
| Tab names | Account · Agents · Sync |
| Row labels | Name · Steps taken · Email · Apple · Google · Password · Your data |
| Email verified | `<email> · Verified` / `<email> · Unverified` / `<email> · Unavailable` |
| Provider state | Connected · Connected · unavailable · Not connected · Unavailable |
| Password | Set · also used for Mac sign-in · Not set · Unavailable |
| Name empty | Not set |
| Your data | A ZIP of everything, without secrets · Export… · Exporting… · Cancel · Saved. |
| Export errors | Couldn't export. Check your connection. · Couldn't save the file there. · Couldn't export. · Try again |
| Methods failed | Sign-in methods couldn't be loaded. |
| Account load failed | Your account details couldn't be loaded. · Try again in a few minutes. |
| Offline | Your account details need a connection. |
| Session ended | Your session ended. · Unsent changes stay on this Mac. · Sign in again… |
| Signed out | Not signed in · Sign in… |
| Reference | Reference: `<correlation id>` |
| Footer | existing status line words · Sign out… |
| Agents | Agents are managed on the web for now. · Open agents on the web… · The agents page can't be opened right now. |

## Deviations from M25

| board element | 028 | reason |
|---|---|---|
| Email "Change…" | not shown | Follow-up feature (Max, Q2) |
| Apple "Remove…", Google "Connect…" | not shown | Follow-up feature (Max, Q2, Q4) |
| Password "Change…" | not shown | Follow-up feature (Max, Q2) |
| Deletion row and "Delete account…" | not shown | Follow-up feature (Max, Q2, Q3) |
| Agents and Sync tab content | not drawn on the board | S-03 and S-04 as decided by Max (Q1) |
| Loading, error, signed-out, offline, session-ended and export states | not drawn | S-02.01, S-02.03 – S-02.15 |

## Affordance → requirement map

| affordance | state | requirement |
|---|---|---|
| ⌘, / Settings… | S-01.01, S-01.02 | 028-FR-001 |
| Tab bar items | S-01.03 | 028-FR-002, 028-FR-023 |
| Export… / Cancel / Try again | S-02.08 – S-02.12 | 028-FR-012, 028-FR-013, 028-FR-017 |
| Sign out… | S-02.13 | 028-FR-014 |
| Sign in… / Sign in again… | S-02.05, S-02.06 | 028-FR-015, 028-FR-016 |
| Try again (account, methods) | S-02.03, S-02.04, S-02.07 | 028-FR-016, 028-FR-017 |
| Open agents on the web… / Try again | S-03.01 – S-03.04 | 028-FR-019 |
| Sync tab actions | S-04.01 | 028-FR-020 |

Requirements with no affordance: 028-FR-003 (no invented values), 028-FR-005
(in-memory only), 028-FR-011 (absence of follow-up controls), 028-FR-018 (logs),
028-FR-021 (no flag), 028-FR-024 (nothing else changes).

## Keyboard and focus

- ⌘, opens or focuses Settings; ⌘W closes it; Esc closes the save panel only.
- Tab order: tab bar items, then the Account tab's controls top to bottom (Export… or
  Cancel or Try again, Try again lines, Sign in… / Sign in again…, Sign out…). Read-only
  values are not in the Tab order but are read by VoiceOver as label + value (e.g.
  "Email, max@example.com, Verified").
- When the Account tab opens, focus rests on the tab bar; no row steals focus when
  data arrives. Errors are announced once, politely.
- Sign out… and Sign in… move the person to the main window; focus there follows 021
  X-03/X-04 rules.
- Focus ring: `focus-ring` role, visible in both appearances.

## Primary loop impact

None. Capture → atomic items → clarify/approve → route or CRT candidate → Weekly
Review → evidence are unchanged.

## Mobile viability

Not applicable: macOS-only surface. The iPhone keeps its existing Settings screen.
