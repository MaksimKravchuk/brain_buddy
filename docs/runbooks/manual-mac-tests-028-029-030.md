# Manual Mac test plan: Settings (028), first run (029) and agents (030)

**Status: PENDING. Nothing below has been run on a Mac yet.**

**Audience:** an AI agent (for example Codex) or a person on the owner's Mac. CI already
builds the Mac app and runs its unit and scene tests. This plan covers what CI cannot see:
the real app on screen, keyboard and VoiceOver, the real server, and real test agents.

**What is on `main` and in scope:**

| Feature | In scope | Not built yet (skip, do not report as FAIL) |
|---|---|---|
| 028 Settings and account | Account tab view, Export…, Sign out…, Sync tab, flag-off Agents tab | Change name/email/password, connect Apple/Google, delete account (backlog) |
| 029 First run | Welcome on a clean Mac, first capture, first step, landing tip | The new sign-in sheet (Google, email code, invite step): 029 PR-03 – PR-08. Sign-in is still the 021 password sheet |
| 030 Agents | Hand off, All runs, per-agent canvas, Waiting for › Agents, run section (reply, stop, result, Mark step done), Settings › Agents (add, test, replace, edit, delete) | The one-time inspector line (G-04.10); Sync now does not refresh runs yet |

Specs with the full wording: `specs/028-mac-settings-account/`, `specs/029-mac-first-run-sign-in/`,
`specs/030-mac-agents/` (spec.md for the stories, design.md for screen ids). When the app and
the spec disagree, record what the app shows; do not decide which one is right.

## 0. Ground rules

1. **Synthetic data only.** Use a scratch data folder (`BRAINBUDDY_MAC_DATA_DIR`), a local
   test server and throwaway accounts (`alex@example.com` style). Never sign in with the
   owner's real account, never touch `~/Library/Application Support` data of the real app.
2. **Do not change product code.** A failed check is recorded as FAIL and fixed later in a
   separate PR.
3. **Never run `/verify-live`** and make no paid provider calls. The test agents below are
   local and free.
4. **Record results content-free:** PASS / FAIL / N/A / NEEDS HUMAN, the words the app shows
   for the synthetic data, counts, SHAs and versions. No tokens, no keychain output, no home
   paths, no real emails.
5. **Mark `NEEDS HUMAN`** where a check needs a person's judgement (VoiceOver speech
   quality, how a colour looks against the board). Do not guess.
6. **Do not stop at the first failure.** Record it and continue with the next check.

## 1. Setup

### 1.1 Repository and toolchain

```sh
cd <brain_buddy clone>
git fetch origin && git switch --detach origin/main
git rev-parse HEAD; sw_vers; xcodebuild -version; swift --version
```

Use this SHA for the whole session. Needs macOS 26 and Xcode 26, plus the Whisper model and
tokenizer that `macos/build_app.sh` needs (see `macos/README.md`).

### 1.2 Build and unit tests

```sh
cd macos
swift build --only-use-versions-from-resolved-file
swift test --only-use-versions-from-resolved-file 2>&1 | tail -20
sh build_app.sh
```

Record the `Executed N tests, with M failures` line. Then launch the app against a scratch
folder, never the real one:

```sh
rm -rf /tmp/bb-manual && mkdir -p /tmp/bb-manual
BRAINBUDDY_MAC_DATA_DIR=/tmp/bb-manual .build/BrainBuddyMac.app/Contents/MacOS/BrainBuddyMac
```

"Fresh launch" below means: quit the app, `rm -rf /tmp/bb-manual && mkdir -p /tmp/bb-manual`,
launch again with the command above.

### 1.3 Local test server (needed for 028, 030)

Run the backend natively (not in Docker), so it can reach the test agents on `127.0.0.1`.
**Never overwrite an existing `.env`**; use a separate clone for testing if one exists.

```sh
make install-backend
export BRAIN_BUDDY_ENV=development
export BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS=1
export BRAIN_BUDDY_PUBLIC_BASE_URL=http://localhost:8000
export BRAIN_BUDDY_AGENT_OBSERVATION_INTERVAL_SECONDS=5
make dev-backend        # API on http://localhost:8000
make dev-frontend       # web app on http://localhost:5173 (second terminal)
```

- **Accounts.** Create invites with `cd backend && python -m app.cli create-invite` and sign
  up on the web app:
  - **Account A**: name "Alex", with a password. Used for most checks.
  - **Account B**: a second throwaway account, for the account-switch checks S-12 and S-15.
- **Flag.** Turn `external_agent_relay` ON for Account A only (SELECTED_USERS) in the Admin
  Portal at `/admin`. The operator account setup is in
  `docs/runbooks/manual-device-tests-020-021.md` § 1.3 ("separate seeded operator").
  Keep the flag OFF for Account B.
- **Mac sign-in.** In the Mac app choose Sign in… (sidebar footer or app menu), open
  Advanced, set the server address to `http://localhost:8000/api` (the `/api` suffix is required; sign-out resets this field, so re-check it before every sign-in), then sign in with Account A.

### 1.4 Local test agents (needed for 030)

Two terminals, both from the repo root:

```sh
# Agent 1: helloworld sample, completes at once ("Agent reported complete")
cd backend/vendor/a2a_helloworld && HOME=$(mktemp -d) python __main__.py      # 127.0.0.1:9999

# Agent 2: Hermes stub, slow, asks a question when the title contains "ask me"
cd backend/vendor/hermes_a2a && HOME=$(mktemp -d) A2A_PORT=9900 A2A_BEARER_TOKEN=devtoken \
  A2A_HOST=127.0.0.1 A2A_PUSH_SECRET=unused STUB_REPLY_DELAY_SECONDS=90 python run_stub.py
```

Background: `specs/014-a2a-relay-wire-contract/quickstart.md` §§ 1–2.

### 1.5 Test steps

In the Mac app, signed in as Account A, create these steps in Next actions and wait until
the sidebar footer says it synced:

- "Book the plumber" with the note "Kitchen sink leaks" in a project "Flat";
- "Compare quotes, ask me which one";
- "Plan the garden" (no note, no project).

## 2. Checks

Do the sections in order. Each check has an id; record it in the Results table (section 3).

### 2.1 General (G)

| Id | Do | Expect |
|---|---|---|
| G-01 | Build, test and launch as in 1.2. | Build succeeds, 0 test failures, the app opens with the Carry On look. |
| G-02 | Switch macOS to dark appearance and back while the app is open. | Every screen in this plan follows; no unreadable text, no white panels in dark. |
| G-03 | Turn on Reduce Motion (System Settings › Accessibility › Display) and open the sheets in this plan. | Sheets and tips appear without sliding or bouncing. |
| G-04 | Turn on Increase Contrast and look at Settings, the hand-off sheet and All runs. | Everything stays readable. NEEDS HUMAN for "matches the board". |

### 2.2 First run (F), feature 029

Start with a fresh launch, signed out, with no data.

| Id | Do | Expect |
|---|---|---|
| F-01 | Fresh launch. | The window opens on Inbox with the welcome: logo, "Carry On", "What feels heaviest?", a line saying where things go, a capture field with keyboard focus, the ⌃⌥⇧B hint, the mic hint (only if speech is available), "No account needed. Your tasks stay on this Mac until you sign in." |
| F-02 | Type a few letters. | "Goes to Inbox, as you wrote it" and "Return to add · Esc to skip" appear under the field. |
| F-03 | Type "the garage is a mess and Sam needs the van back", press Return. | One Inbox item with exactly that text. The Inbox reads "1 thing to sort", the item is selected, the inspector shows "Inbox · 1 of 1", the text, "What is the first step you could take?", a focused empty field, "Small enough to start today. Not sure yet? Leave it in the Inbox.", "Make it my next step" and "Not yet". |
| F-04 | Leave the step field empty, then type only spaces. | "Make it my next step" stays unavailable. |
| F-05 | Type "Call Sam about the van", press Return. | The window shows Next actions with "Call Sam about the van" on top labelled "Now" (no project), with Done and Not now, and one tip mentioning Done, ⌘N, ⌃⌥⇧B and ⌘O with "Got it". The item's note holds the original sentence. No project was created. |
| F-06 | Choose "Got it". Quit and relaunch with the same folder. | The tip is gone and never returns; no welcome. |
| F-07 | Fresh launch, press Esc on the welcome. | Nothing is added, the Inbox stays without the welcome. Relaunch: no welcome. |
| F-08 | Fresh launch, capture "Test item", then on the question press Esc (or "Not yet"). | The item stays in the Inbox unchanged, no tip appears. |
| F-09 | Fresh launch, capture "Test item", quit before answering, relaunch. | The item is in the Inbox, the first run does not resume. |
| F-10 | With the app already holding tasks (the folder from F-05), relaunch. | No welcome; the app opens as usual. |
| F-11 | With another app holding ⌃⌥⇧B (if you can arrange it), fresh launch. | The hint reads "⌃⌥⇧B is unavailable. Use Quick Capture in the toolbar." Otherwise N/A. |
| F-12 | VoiceOver (⌘F5) on F-01, F-03 and F-05. | The capture field, the question, the step field, both buttons and "Got it" are announced by name and reachable with Tab / VO keys. NEEDS HUMAN for speech quality. |

### 2.3 Settings (S), feature 028

Signed in as Account A unless a check says otherwise.

| Id | Do | Expect |
|---|---|---|
| S-01 | Press ⌘,; press ⌘, again. | One Settings window on the Account tab, tabs Account, Agents, Sync. The second ⌘, brings the same window forward (no second window). |
| S-02 | Read the Account tab and compare with the web account page for Account A. | Name "Alex" (read-only), steps taken equals the web count, email followed by "Verified" (or the web's state), Apple and Google rows say "Connected" / "Not connected" as on the web, the password row reads "Set · also used for Mac sign-in". No Change…, Connect…, Remove… or Delete account… control anywhere. |
| S-03 | Stop the backend (Ctrl-C), close and reopen Settings. | The account rows are replaced by "Your account details need a connection." with Try again. Sign out… is still there. Start the backend again and choose Try again: the rows return. |
| S-04 | Choose Export… on "Your data". | The row shows "Exporting…" with progress and Cancel; then a save panel opens with the server's file name. Save to `/tmp/bb-manual-export/`. The ZIP opens and holds account data; it contains no password hash, session token or API key. |
| S-05 | Export… again, then Cancel in the save panel. Repeat and close Settings while "Exporting…" shows. | No file is written in either case. |
| S-06 | Stop the backend, choose Export…. | No file; an actionable message with Try again (and a support reference if the server returned one). Restart the backend. |
| S-07 | Open the Sync tab and the sidebar footer's sync popover in the same state. | Same words, same issues, same enabled actions. "Sync now" in the tab syncs. |
| S-08 | Make a local change while the backend is stopped, then choose Sign out… in Settings › Account. | The main window comes forward with the existing sign-out confirmation, "Cancel" is the default button, and it says what would be removed exactly as the menu's Sign out… does. Choose Cancel. |
| S-09 | Restart the backend, let it sync, choose Sign out… in Settings and confirm. | The Mac signs out; the Account tab switches to "Not signed in" with Sign in…. |
| S-10 | Signed out, choose Sign in… in the Account tab. | The existing sign-in sheet opens on the main window. Sign in as Account A again. |
| S-11 | On the web, change Account A's password (this ends other sessions). Back on the Mac, reopen Settings or press Try again. | "Your session ended." with Sign in again…; local tasks and unsent changes are still there; no account details from before stay on screen. Sign in again with the new password. |
| S-12 | Sign in as Account B (flag off) and open Settings › Agents. | "Agents are managed on the web for now." and "Open agents on the web…". The button opens `<web origin>/settings/agents` in the default browser; the URL carries no token. |
| S-13 | While Settings is open, sign out from the app menu. | The Account tab follows to the signed-out state; no second confirmation. |
| S-14 | VoiceOver through the Account tab and the export row. | Each row reads its label and value; buttons are reachable. NEEDS HUMAN for speech quality. |
| S-15 | Signed in as B, then sign out and sign in as A with Settings open. | The tab never shows B's details after the switch. |

### 2.4 Agents (A), feature 030

Signed in as Account A (flag ON), both test agents running, steps from 1.5 synced.

**Settings › Agents**

| Id | Do | Expect |
|---|---|---|
| A-01 | Open Settings › Agents with no agents. | An empty list ("No agents yet.") with + and the Add action. |
| A-02 | Choose +. Fill Name "Helloworld", Address `http://127.0.0.1:9999`, Credential Bearer token "any", Current password; choose "Add and test". | The sheet asks for exactly these fields. The agent is created, tested and selected; its status reads "Tested ready" (or the server's word) with address, credential, last contact, agent card, skills (Echo Bot), updates and "Best-effort single start". |
| A-03 | Add "Hermes" at `http://127.0.0.1:9900`, Bearer token `devtoken`. | Tested ready, skills listed, push supported. |
| A-04 | Choose Test again on Hermes. | Status and details refresh; no password is asked. |
| A-05 | Replace credential… on Hermes with a wrong password. | The sheet stays open with "That password isn't right."; nothing changes. |
| A-06 | Replace credential… on Hermes with `wrong` and the right password, then Test again. | The test fails as invalid credentials; the secret is never shown. Replace it back with `devtoken`, Test again: Tested ready. |
| A-07 | Edit… Hermes, change only the name to "Hermes stub". | Saved without asking for a password. |
| A-08 | Edit… and change the address. | The sheet asks for the current password ("Confirm your password to change this agent's destination."). Cancel. |
| A-09 | Compare the Mac list with the web Settings › Connected agents. | Same agents, same states. |

**Hand off**

| Id | Do | Expect |
|---|---|---|
| A-10 | Select "Plan the garden" and choose Hand off… on its card. | Sheet "Hand to an agent" with "It works on its own and comes back with a result. The step stays yours." and one row per ready agent with skills and guarantee. |
| A-11 | Choose Helloworld. | "What it will get" shows the title and the agent's cancellation disclosure; the button reads "Send to Helloworld". Because Helloworld is best-effort, "I understand that a duplicate task is possible with this agent" must be ticked before Send is enabled (first hand-off only). If the server asks for re-authentication, a Current password field appears and Send waits for it. |
| A-12 | Send. | The sheet closes; the step's card shows the run; soon "Agent reported complete". The step is still in Next actions with the same status. |
| A-13 | Hand off "Book the plumber" to Hermes. | "What it will get" shows the title, "Note: Kitchen sink leaks" and "Project: Flat". After Send the run shows "Sent" or "Queued", then Running (the stub waits 90 s). |
| A-14 | Hand off "Compare quotes, ask me which one" to Hermes. | Within about 90 seconds (the stub delay) the run is "Needs you". |
| A-15 | Make a new step while the backend is stopped, then choose Hand off… on it. | Hand off… is disabled with "This step hasn't reached your account yet." Restart the backend. |
| A-16 | Stop the backend and choose Hand off… on a synced step. | "Handing off needs a connection." Nothing is sent. Restart the backend. |
| A-17 | Stop both agents, then open Hand off…. | The sheet says no agent is ready and offers Open Settings…, which opens Settings › Agents. Start both agents again and Test again each. |

**Runs**

| Id | Do | Expect |
|---|---|---|
| A-18 | Look at the sidebar. | "Agents" with "All runs N" and one row per agent with its run count. |
| A-19 | Open All runs. | "All runs", "<N> runs", "Every step you handed off, by what it needs from you.", groups in the order Needs you, Running, Queued, To review, Lost contact (only non-empty ones), each "<group> · <count>"; "Add new agent" at the top right. |
| A-20 | Choose an agent row in the sidebar. | Only that agent's runs, same groups, titled with the agent's name. |
| A-21 | Open Waiting for. | An "Agents" group (one row per run, "<step> / <agent> · <state>") above a "People" group; the header reads "<n> people, <m> agents"; the sidebar count is n + m. |
| A-22 | Select a run row in each of the three places. | The step's inspector opens with its run; the step stays in its own list. |
| A-23 | Choose "Add new agent" on All runs. | Settings › Agents opens with the Add sheet. Cancel. |

**Run section in the inspector**

| Id | Do | Expect |
|---|---|---|
| A-24 | Select the "ask me" step (Needs you). | Agent name, a timeline ("Sent …", "Running …", "Needs you …"), "<agent> asks", the question as plain text, "Your answer", Reply and Stop run. |
| A-25 | Type an answer and choose Reply. | Sent once; the field clears; "Reply sent. Waiting for the agent." until the next observation. Later the timeline may show "The agent continued this run in a new task". |
| A-26 | Stop the backend with the inspector open. | The last run shows "This may be out of date."; Reply and Stop run are disabled with "Needs a connection.". Restart the backend. |
| A-27 | Hand off "Plan the garden" to Hermes again and choose Stop run while it runs. | "Cancellation requested", then "Cancelled". Hand off again is offered. Mark step done is not shown. |
| A-28 | Select "Plan the garden" whose Helloworld run reported complete. | "Agent reported complete · <time>", "Result", the result text ("Hello, World! …"), any link as selectable plain text, "The agent finishing does not finish your step. You decide.", "Then", "Make the next step", Mark step done and Hand off again. The step is still open. |
| A-29 | Type "Water the beds" in "Make the next step", choose Mark step done. | The step is completed and "Water the beds" appears as a Next action (in the same project, if the step had one). |
| A-30 | On another completed run, leave the field empty and choose Mark step done. | Only the step is completed; no new step. |
| A-31 | Choose Hand off again on an ended run. | The hand-off sheet of A-10 opens for the same step. |
| A-32 | Restart the Hermes stub while one of its runs is Running; wait one observation. | The run reads "Agent no longer reports this run"; reply and stop are withdrawn; it is not shown as Failed. |
| A-33 | VoiceOver through the hand-off sheet, All runs and the run section. | Rows, groups and buttons are announced and reachable. NEEDS HUMAN for speech quality. |

**Flag and account changes**

| Id | Do | Expect |
|---|---|---|
| A-34 | In `/admin`, turn `external_agent_relay` OFF for Account A. Bring the Mac window to the front (the Mac re-reads the flag at most every 5 minutes, or at once when a flagged call fails). | Hand off…, Hand off again, Add new agent and + disappear; Settings › Agents shows the 028 web-link content. An open hand-off sheet closes with "Handing off isn't available right now." Turn the flag back ON. |
| A-35 | With the Add agent sheet open and a secret typed, sign out from the menu. | The sheet closes; signing back in shows no typed secret or password. |
| A-36 | Delete "Hermes stub" (−) with the right password. | Asks for the current password and shows "Its credential is destroyed. Runs already sent keep their history."; the agent is gone; its runs keep their history. |

### 2.5 Clean up

Quit the app, `rm -rf /tmp/bb-manual /tmp/bb-manual-export`, stop the agents and the
backend. Do not delete anything else.

## 3. Results

Fill in on a copy of this file named `docs/runbooks/results/manual-mac-028-030-<date>.md`.

- Date:
- Who ran it:
- SHA under test:
- Mac model and chip / macOS / Xcode / Swift:
- `swift test` line:

| Id | Result | Notes (content-free) |
|---|---|---|
| G-01 | | |
| … one row per check id above … | | |

Status line for the top of the results file: `PASS (<runner>, <date>, <SHA>)`, `FAIL [ids]`
or `PARTIAL [NEEDS HUMAN ids]`.

## 4. Reporting back

1. Commit only the results file on a new branch `manual-results/<date>` and open a pull
   request titled `docs(runbooks): manual Mac results 028/029/030 <date>`.
2. Give the owner this summary:

```
Manual Mac results — <date> — main @ <SHA>
Host: <Mac model/chip>, macOS <ver>, Xcode <ver>
G (general):     PASS | FAIL [ids] | PARTIAL [ids]
F (first run):   ...
S (Settings):    ...
A (agents):      ...
Failures (one line each): <id>: <what happened>
NEEDS HUMAN: <id>: <why>
Results PR: <link>
```

3. Each FAIL becomes its own fix PR later. Never patch product code in the results PR.
