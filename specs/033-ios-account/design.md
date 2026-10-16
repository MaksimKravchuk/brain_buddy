# Design: iPhone account screens and invite step

**Feature**: [spec.md](spec.md) · **Source**: Carry On canvas
https://claude.ai/artifact/1bwKiw15U2jpZqwu5pTMg6, iPhone row, cells M06, M25–M28.

## Applicability

UI feature on the iPhone app. The boards are the design; this file lists the screens,
their states, and where the build departs from a board and why. Colours, type, spacing
and radii come only from `carry-on.tokens.json`; one token is added (`layout.code-box`,
the six-box code field of boards 06 and 27: height 58, gap 6, radius 12).

## Screen inventory

| ID | Screen | Board | Reached from |
|---|---|---|---|
| S-01 | Account | M25 (without Agents) | Settings → Account row |
| S-02 | Name sheet | none (chevron on M25) | S-01 Name row |
| S-03 | Sign in | M26 | S-01 "Sign in" group |
| S-04 | Change email sheet | M27 | S-03 email row |
| S-05 | Password sheet | M26 password row style | S-03 password row |
| S-06 | Confirm it's you sheet | none (style of M27/M28) | before every change except the name |
| S-07 | Delete account sheet | M28 | S-01 "Delete account…" |
| S-08 | Invite step | M06 | sign-in, when the server asks for an invite |

## State inventory

- **S-01**: loading (the last known name and email stay visible), ready, failed (words +
  reference ID + Try again), offline (rows read-only, note under the header).
- **S-03**: each method row shows one state ("Verified", "Not verified", "Connected",
  "Not connected", "Set", "Not set") and its one action; a provider the server does not
  offer and the account never connected is hidden.
- **S-04**: enter new address → code sent (six boxes, "Send again in Ns") → changed;
  wrong code / expired code / too many tries show the server's words.
- **S-06**: choices (password field, "Send a code to …", "Confirm with Apple/Google",
  only for methods on the account) → code step → closes with the proof. Nothing on the
  account can confirm → a note, Cancel only.
- **S-07**: "Keep account" is the default button; Delete runs S-06, then shows the
  purge date and that signing in before it cancels the deletion.
- **S-08**: code entry, submitting, wrong / used / throttled message, expired → "Back to
  sign in" only.

## Deviations from the boards

| Board | Drawn | Built | Why |
|---|---|---|---|
| M25 | Agents group | omitted | spec 034 |
| M06 | six code boxes | one wide monospaced field | invite codes are 43-character tokens |
| — | no confirm step | S-06 glass sheet | the server requires a recent proof |
| M25 | Name row chevron, no screen | S-02 one-field sheet | the row promises an action |
| M06 | — | offline note under the field when offline | the old sheet showed it; keeps FR-013 |

## Affordance → requirement map

| Affordance | Requirement |
|---|---|
| S-01 header, groups, Sign out | 033-FR-001 |
| S-02 Save | 033-FR-002 |
| S-03 rows | 033-FR-003, 033-FR-006, 033-FR-007 |
| S-06 | 033-FR-004, 033-SC-002 |
| S-04 | 033-FR-005 |
| S-05 | 033-FR-008 |
| S-01 Export a copy | 033-FR-009 |
| S-07 | 033-FR-010 |
| S-08 | 033-FR-011 |
| Failure words, reference ID | 033-FR-012 |
| Offline note | 033-FR-013 |

## Accessibility

44 pt targets; headers carry the header trait; the code boxes are one accessible field
("Email code", value read digit by digit); failures are announced; Reduce Motion is
respected by using system sheet transitions only.
