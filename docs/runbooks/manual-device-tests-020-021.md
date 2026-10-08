# Manual device test runbook: features 020 (weekly review) and 021 (Mac sync)

**Audience:** an AI agent, or a person, running on the owner's Mac. It needs Xcode 26 and
macOS 26 or later, and can use the iOS Simulator or an iPhone. It will run every check that
CI cannot run.

**Why this exists:**
- **The owner's decision of 2026-10-08:** slices whose only remaining checks are manual merge
  once CI is green. Each one carries its manual test plan as a PENDING evidence file. The plans
  are run later on the owner's hardware, and a failed check is fixed in a separate PR.
- **What this runbook adds:** it is the single entry point to those plans. It says what to run,
  in what order, under which rules, and how to report back. It does not repeat the checks: each
  plan file holds the exact steps, the expected results and a blank Results table.

## 0. Ground rules (read before anything else)

1. **Synthetic data only.**
   - Use a fresh install, the `-BBUsePreviewData` launch argument, a scratch folder through
     `BRAINBUDDY_MAC_DATA_DIR`, or a test account on a local test server.
   - Never sign in with the owner's real account.
   - Never commit screenshots, logs or reports that show real tasks, titles, emails or hosts.
     Results are content-free: pass/fail, counts, SHAs and versions.
2. **The owner's real Mac data is upgraded only by the owner.**
   - Feature 021's first launch imports the old `local-gtd.json` and renames it to a backup.
   - Run the **dry run on a copy (D1–D8)** first, and stop there for the real folder.
   - Upgrading the owner's real folder (`$REAL` in the upgrade plan) needs the owner's explicit
     go-ahead after D1–D8 pass.
3. **Do not change product code** while testing. If a check fails:
   - record FAIL with what you saw;
   - leave the rest of the plan running;
   - report the failure (section 4). The fix happens in a separate PR.
4. **Never run `/verify-live`**, and never make paid provider calls (voice/STT, AI). None of
   these checks need them.
5. **When a check genuinely needs a human, record it as such.** VoiceOver speech, haptics,
   the feel of a gesture, or a real device are examples. Write `NEEDS HUMAN` with the reason,
   rather than guessing a result.

## 1. Setup

1. **Repository:** clone or update it, `git switch main && git pull`, and record `git rev-parse HEAD`.
   Every Results table asks for the SHA under test. Use the same SHA throughout one session.
2. **Mac toolchain:**
   - `xcode-select -p` points at Xcode 26;
   - record `sw_vers`, `xcodebuild -version` and `swift --version`;
   - `brew install xcodegen` for the iOS project;
   - the Whisper model and tokenizer that `macos/build_app.sh` needs (see `macos/README.md`).
3. **Test backend.** This is needed for the 021 sign-in and sync checks, and for any signed-in
   iOS check.
   - **Never overwrite an existing `.env`.** It is gitignored and may be the only copy of the
     owner's keys and settings.
     - If `.env` already exists, leave it as it is, or run the stack from a separate clone made
       for testing.
     - Only when no `.env` exists: `cp .env.example .env`.
   - Then run `docker compose up --build`. The API runs on the compose stack and the web app on
     `http://localhost:8080`. `.env.example` documents every variable.
   - Create a test account: `docker compose exec backend python -m app.cli create-invite`, then
     sign up on the web app with that invite code and a throwaway email.
   - The `weekly_review` flag is off by default. Turn it on for the test account where a check
     needs it, through the Admin Portal flag page (SELECTED_USERS), as
     `specs/020-weekly-review/quickstart.md` "Prerequisites" says.
     - `/admin` admits only operators listed in `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`, which is
       empty in `.env.example`, so set it before `docker compose up` (see `docs/auth.md`). In
       a testing clone's `.env`, set it to the test account's email; in an existing `.env`,
       only with the owner's OK.
     - Then sign in to `/admin` as that account and set `weekly_review` to that account.
   - Seed a stalled task instead of moving clocks, where a plan allows either:
     `docker compose exec -e BRAIN_BUDDY_ENV=test backend python -m app.cli
     review-seed-aged-task --email <test email> --days <N>`.
     - The helper refuses to run unless `BRAIN_BUDDY_ENV=test` (it exits with code 2), hence
       the `-e` for this one command.
     - Never point it at production.
4. **iOS:**
   - Run `(cd ios && xcodegen generate)`, then open `ios/BrainBuddy.xcodeproj`.
   - Use the Debug configuration with `BBWeeklyReviewLocal = YES` for the account-less weekly
     review checks, as the iOS plans say. The value comes from the `BB_WEEKLY_REVIEW_LOCAL`
     build setting in `ios/project.yml`.
   - Use the Simulator unless a check needs a device.
5. **Mac app:** run `cd macos && sh build_app.sh`. Launch it against a scratch folder with
   `BRAINBUDDY_MAC_DATA_DIR="<absolute scratch folder>"`, exactly as each plan shows.

## 2. Which plans, in which order

Run them in this order. Before starting each one, check its file exists on `main`: two plans
arrive with PRs that may still be open (see "Arrives with"). Skip a missing plan and say so in
the report.

| # | Plan file | Feature / slice | Arrives with | What it covers | Approx. time |
|---|---|---|---|---|---|
| 1 | `specs/020-weekly-review/evidence/macos-host-run.md` | 020 PR-06 | on main | Mac sidebar "Weekly review · coming later" row: build, tests, V1–V11 (position, copy, click, keyboard, context menu, VoiceOver, Accessibility Inspector, narrow sidebar, light/dark, regression, no local review) | 15 min |
| 2 | `specs/020-weekly-review/evidence/manual-ios-increment1.md` | 020 PR-04 | on main | iPhone weekly review increment 1 (T094): app build, Release flag off, previews, decision card, unsaved-text guard, Undo toast timing with VoiceOver, 44 pt targets, AA contrast, explainer focus | 45 min |
| 3 | `specs/020-weekly-review/evidence/manual-ios-increment3.md` | 020 PR-12 | on main | iPhone full weekly review (T159): one decision per screen, the Lists row, VoiceOver focus on each screen, Reduce Motion, leave and resume, unsaved text across an app kill | 45 min |
| 4 | `specs/021-mac-sync/evidence/manual-macos-upgrade.md` | 021 PR-08 | on main | Mac upgrade (T113–T114): CI lane and build, **dry run on a copy D1–D8** (do this before anything touches real data), upgrade U1–U7 on test data, corrupt or newer files, later files L1–L5, failed-import panel I1–I5, X-09, single instance | 60 min |
| 5 | `specs/021-mac-sync/evidence/manual-macos-archive.md` | 021 PR-08 | on main | Mac archived projects (X-06) A1–A18 | 20 min |
| 6 | `specs/021-mac-sync/evidence/manual-macos-status.md` | 021 PR-09 | PR #298 | Mac sync UI (T132–T133): sign-in S1–S11, status line L1–L9, accessibility A1–A10, incoming changes, cadence and menus C1–C7, sign-out O1–O5, account switch, Keychain and X-09 K1–K3. Needs the test backend from 1.3 and the web app open on the same test account | 90 min |

**Not for the agent:**
- **021 `specs/021-mac-sync/evidence/owner-week.md`** (arrives with 021 PR-10) is the owner's
  own week of real use. The agent may prepare it but does not fill it in.
- **020 T169, the rollout decisions** in `specs/020-weekly-review/evidence/rollout-decisions.md`
  (020 PR-14), are the owner's decisions.
- **020 T171, the full verification on the frozen candidate**, is listed in 020 PR-14. Run its
  local commands only if the owner asks.

## 3. How to run one plan

1. Read the whole plan file before starting. Each one has a "What changed" section and its own
   prerequisites.
2. Follow its steps in order. Where a plan says "on the exact SHA", use the SHA from 1.1, and
   note in Notes if `main` moved during the session.
3. Fill in the plan's **Results** table in place:
   - one row per check: PASS, FAIL (what you saw, content-free), N/A (why) or NEEDS HUMAN (why);
   - the header fields: date, who ran it (agent name or person), SHA, Mac model and chip, and
     the OS, Xcode and Swift versions.
4. Change the plan's status line at the top:
   - **`PASS (<runner>, <date>, <SHA>)`** when every row passes or is N/A;
   - **`FAIL`** naming the failing checks;
   - **`PARTIAL`** naming the NEEDS HUMAN rows.
5. Clean up the scratch folders and test data as the plan says.

## 4. Reporting back

1. **Commit the filled-in plans** on a new branch, for example `manual-results/<date>`, and only
   the evidence files. Open a pull request titled
   `docs(spec): manual device results 020/021 <date>`.
   - The PR body is the summary below.
   - Spec Kit checks run on it (`make check-specs`).
2. **Give the owner this summary to paste into the next session:**

```
Manual device results — <date> — main @ <SHA>
Host: <Mac model/chip>, macOS <ver>, Xcode <ver>; iOS <Simulator|device model>, iOS <ver>
1 macos-host-run (020 PR-06):       PASS | FAIL [V..] | PARTIAL [V..]
2 manual-ios-increment1 (020 PR-04): ...
3 manual-ios-increment3 (020 PR-12): ...
4 manual-macos-upgrade (021 PR-08):  ... (dry run D1–D8: PASS/FAIL; real folder upgraded: no/yes-with-owner-OK)
5 manual-macos-archive (021 PR-08):  ...
6 manual-macos-status (021 PR-09):   ... | not on main yet
Failures (one line each, content-free): <plan> <check id>: <what happened>
NEEDS HUMAN: <plan> <check id>: <why>
Results PR: <link>
```

3. **Each FAIL becomes its own fix PR** in a later session. Never patch product code inside the
   results PR.

## 5. Reference

- **Specs:**
  - `specs/020-weekly-review/` and `specs/021-mac-sync/`: spec.md, design.md (screens D-*, M-*,
    X-*), quickstart.md and tasks.md (see Notes: "Manual checks follow the merge").
- **App notes:**
  - `ios/AGENTS.md` and `docs/native-ios-app.md` for the iPhone app;
  - `macos/README.md` for the Mac app;
  - `docs/native-macos-app.md`, which arrives with 021 PR-09.
- **Auth and invites:** `docs/auth.md`.
