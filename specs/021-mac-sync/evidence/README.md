# Feature 021 — evidence

This folder holds the records that code and CI cannot produce: what a person (or the owner's
agent) saw on a real Mac, and the owner's week of real use. Everything here is Markdown and
**content-free** (see below). Slice PR-10 of [tasks.md](../tasks.md) wrote this index; the plan's
[Evidence protocol](../plan.md#evidence-protocol) is the rule it summarises.

## Index

| File | What it records | Task | Requirements | Status |
|---|---|---|---|---|
| [manual-macos-upgrade.md](manual-macos-upgrade.md) | The upgrade from a pre-021 Mac build: CI lane and build on the exact SHA, the dry run on a copy of the real folder, the import, the corrupt and newer files, the unreadable `store.json`, the second copy. | T113, T114 | 021-FR-020, 021-FR-021, 021-FR-022, 021-FR-033, 021-SC-003 | PENDING |
| [manual-macos-archive.md](manual-macos-archive.md) | Archived projects on the Mac (X-06): the sidebar section, read-only rows, unarchive, rename, and the on-screen words. | T114 | 021-FR-024 – 021-FR-028 | PENDING |
| [manual-macos-status.md](manual-macos-status.md) | The Mac sync UI on the landed build: sign-in, the status line and popover, sign-out, VoiceOver, keyboard, Reduce Motion, large text, the Keychain item, sleep and wake, the account-switch refusal. | T132, T133 | 021-SC-004, 021-FR-009, 021-FR-006 (and the on-screen halves of 021-FR-001, 021-FR-004, 021-FR-005, 021-FR-012 – 021-FR-018) | PENDING |
| [owner-week.md](owner-week.md) | The owner's week on Mac, iPhone and web with one account: one dated entry per day. | T137 | 021-SC-007 | PENDING |

PENDING means nobody has filled the file in yet. A plan that has not been run is not evidence,
and nothing in this folder is counted as coverage until its Results table (or its seven dated
entries) is filled in from a real run.

## When these checks run (owner's decision, 2026-10-08)

Manual checks **follow the merge**. A slice merges once its automated lanes are green; the
owner's agent then runs the host plans on the owner's Mac, on the landed build or on a candidate
whose tree hashes are identical, and commits the records afterwards in a docs-only commit under
this folder. **A failure is fixed in a separate PR**: the record is set to `FAIL (<check>)` and
names the check, the fix is not folded into the evidence commit, and the check is run again on
the new build.

The macOS lanes (`macos-app` in CI, `cd macos && swift test`) run only in CI or on a Mac; the
Linux worktree cannot build the Mac app target. The owner's week (021-SC-007, quickstart
Scenario 9) is post-release acceptance and is not a slice gate.

## The content-free rule

Evidence is committed to the repository, so it carries **counts, durations and yes/no only**.
A record never contains:

- a path into a home folder (`/Users/…`, `~/Library…`) or into a keychain (`…Keychains/…`);
- a session token, a password, an invite code, or a run of 32 or more hexadecimal characters
  (a digest of user data, a token, a key) anywhere except the places listed under "Where a
  long hexadecimal string is allowed" below;
- an email address other than one ending in `@example.com` (`alex@example.com`-style test
  addresses);
- a task, project or tag title, a note, or any other text of a real account; use the design's
  example data ("Garden", "Old flat");
- command output such as `security find-generic-password` (it prints the keychain path), a
  log excerpt, or a screenshot of a real account;
- a file that is not Markdown.

A byte comparison is written as `bytes identical: yes/no`; a count as `adjusted: N`,
`not carried: N`; a time rounded to seconds. Use a seeded synthetic account on a test server
or a scratch folder (`BRAINBUDDY_MAC_DATA_DIR`), never the owner's real data.

The planned `scripts/check_manual_evidence.py` (tasks T134 and T135, deferred by the owner on
2026-10-07) would enforce these rules mechanically; until it exists they are checked by
reading, so check a record against this list before committing it.

## The header format

Each `manual-*.md` record starts with a header that names the evidenced build **by content**,
not by commit. A squash landing changes the commit and not the tree, so a record made on the
slice's candidate stays valid after landing, and any later change to the evidenced code makes
it stale.

| Field | Value |
|---|---|
| Date of run | `YYYY-MM-DD` |
| Run by | the owner, or the owner's agent |
| Build | the candidate commit SHA and the CI `macos-app` job result for it |
| OS | macOS version (and chip family) of the run |
| Tree hashes | `git rev-parse <commit>:macos` and `git rev-parse <commit>:ios/BrainBuddyKit` for a Mac record; `git rev-parse <commit>:ios/BrainBuddy` and `git rev-parse <commit>:ios/BrainBuddyKit` for an iPhone record |

Then, one checklist line per state or check, each answered yes/no (or pass/fail) with a count
where a count is asked for. The status line at the top is one of `PENDING`, `PASS (owner run,
<date>, <SHA>)` or `FAIL (<check>)`.

### Where a long hexadecimal string is allowed

A completed record has to name the build, so a hexadecimal string of 32 or more characters may
appear in these places and nowhere else:

- the header's **tree-hash** fields;
- a **full commit SHA** in the header's **Build** field and in the status line
  `PASS (owner run, <date>, <SHA>)`;
- a **full commit SHA** in the owner-week read-out's "Build (candidate SHA) the Mac ran" field.

Only a commit SHA or a tree hash fits there. A token, a key or a digest of user data stays
forbidden even in these fields. If the evidenced trees change after a record was made,
re-record it on the new build.

## Owner's week

[owner-week.md](owner-week.md) is a template. It never counts as evidence while it holds only
the template. 021-SC-007 is met when it holds seven dated entries, each answering the three
questions of quickstart Scenario 9.
