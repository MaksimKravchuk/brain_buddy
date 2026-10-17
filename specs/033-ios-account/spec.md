# Feature Specification: iPhone account screens and invite step

**Feature Branch**: `033-ios-account`

**Created**: 2026-10-16

**Status**: Approved scope (Max, 2026-10-16). Business intake: [intake.md](intake.md).
Design: [design.md](design.md). Plan: [plan.md](plan.md). Tasks: [tasks.md](tasks.md).

**Input**: Carry On canvas, iPhone cells M06 (invite), M25 (account), M26 (sign-in
methods), M27 (change email), M28 (delete account).

## Context

The iPhone app shows the signed-in account in Settings and sends the person to the web
for everything else ("Manage account", "Delete account"). The server already offers
every account right natively (spec 023): profile, recent-proof confirmation, email
change and verification by code, linking and unlinking Apple and Google, setting a
password, ZIP export and deletion with a 14-day grace period. The invite step (ADR-0032)
exists in the sign-in sheet but predates the Carry On boards.

## Clarifications

### Session 2026-10-16

- Q: Native or web hand-off? → A: Native, as drawn (intake D1).
- Q: How does the person confirm it is them? → A: A confirmation sheet with the
  methods already on the account (intake D2).
- Q: Six boxes for the invite code? → A: One field; invite codes are long tokens (D3).
- Q: Where is Sign out? → A: Account screen bottom (D4). Agents: spec 034 (D5).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See and edit my account on the iPhone (Priority: P1)

From Settings the person opens Account and sees who they are (name, email, steps
taken), how they sign in, and their data actions, then edits their name.

**Independent Test**: sign in, open Settings → Account, change the name, see it in the header.

**Acceptance Scenarios**:

1. **Given** a signed-in iPhone, **When** Account opens, **Then** it shows the name (or
   the email when there is none), "email · N steps taken", the Profile, Sign in and Your
   data groups and Sign out.
2. **Given** the Name row, **When** the person saves an empty name, **Then** the account
   goes by its email.

### User Story 2 - Change how I sign in (Priority: P1)

The person changes their email with a code to the new address, verifies an unverified
address, connects or removes Apple and Google, and adds or changes the password; every
change first asks them to confirm it is them.

**Independent Test**: change the email end to end; remove a provider; set a password.

**Acceptance Scenarios**:

1. **Given** the Sign in screen, **When** the person changes the email, **Then** a code
   goes to the new address and the old address keeps working until the code is accepted.
2. **Given** any change, **When** the person has not confirmed recently, **Then** the
   confirmation sheet offers only methods already on the account.
3. **Given** removing the method this session used, **When** it succeeds, **Then** the
   app says to sign in again and keeps every local task.

### User Story 3 - Take my data or delete my account (Priority: P1)

**Acceptance Scenarios**:

1. **Given** Export a copy, **When** confirmed, **Then** a ZIP is offered to save or share.
2. **Given** Delete account…, **When** the person keeps the default, **Then** nothing
   happens; **When** they confirm Delete, **Then** the account is scheduled for deletion
   in 14 days and the app says that signing in before then cancels it, keeping unsent
   changes on the iPhone until sign-out.

### User Story 4 - Enter an invite code (Priority: P2)

**Acceptance Scenarios**:

1. **Given** a new sign-in with no account, **When** the server asks for an invite,
   **Then** the board 06 step appears; a wrong, used or throttled code shows its message
   and an expired step sends the person back to sign in.

### Edge Cases

- Offline: changes are disabled with a note; nothing local changes.
- A response about a different account is never shown or acted on.
- A lost response: the screen says it could not confirm whether the change finished and
  reloads.
- An expired confirmation is refused before anything is sent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Settings MUST open an Account screen (board 25 without Agents) showing the
  linked account's name or email, "email · N steps taken", Profile, Sign in, Your data
  and Sign out, read from the server for the linked account only.
- **FR-002**: The person MUST be able to set or clear their display name.
- **FR-003**: A Sign in screen (board 26) MUST list the email with its verified state and
  Apple, Google and Password with their state and the one action each allows; a provider
  the server does not offer and the account never connected is not shown.
- **FR-004**: Every change except the name MUST first obtain a recent proof for that
  change through a method already on the account (password, a code to its own email,
  Apple or Google); an expired proof MUST be refused before any request.
- **FR-005**: Changing the email (board 27) MUST send a six-digit code to the new address
  and keep the current address until the code is accepted; "Send again" follows the
  server's resend time.
- **FR-006**: An unverified email MUST offer Verify with a code to that address.
- **FR-007**: The person MUST be able to connect and remove Apple and Google; when the
  removal ends this session the app asks to sign in again and keeps local work.
- **FR-008**: The person MUST be able to add or change the password (12 characters or
  more, typed twice).
- **FR-009**: Export a copy MUST produce the account ZIP and offer it to save or share.
- **FR-010**: Delete account (board 28) MUST default to Keep account; Delete schedules
  deletion in 14 days, ends the sessions, and keeps unsent changes on the device until
  sign-out.
- **FR-011**: The invite step MUST follow board 06 with one code field and keep its
  existing failure states.
- **FR-012**: Failures MUST be shown in words with the reference ID when there is one; an
  uncertain outcome says so and reloads; another account's response is never shown.
- **FR-013**: Offline, every change MUST be disabled with a note; local tasks never change.

### Key Entities

- **Recent proof**: short-lived permission for one action on one account.
- **Sign-in method row**: a method, its state words and its one action.

## Success Criteria *(mandatory)*

- **SC-001**: Boards 06, 25, 26, 27 and 28 are matched in light and dark with board colours.
- **SC-002**: No change request leaves the device without a fresh proof for that action.

## Assumptions

- The backend contracts of spec 023 and `GET/PATCH /account` are used unchanged.
- The Agents group of board 25 is added by spec 034.
