# Feature 021 — macOS archived projects (X-06), host run (slice PR-08, T114)

**Status: PENDING. Nothing below has been run on a Mac yet.** Written by the implementing
agent on 2026-10-08 on Linux, where the Mac app cannot be built or launched.

- **Who runs it:** the owner, or the owner's agent on the owner's Mac, after step 1 of
  `manual-macos-upgrade.md` (the build) passed.
- **Data:** test data only (a scratch folder through `BRAINBUDDY_MAC_DATA_DIR`). Do not commit
  screenshots that show real tasks.
- **If a check fails:** set the status to `FAIL (<check>)`; the fix lands in a separate PR.
- **Acceptance:** 021-FR-024 – 021-FR-028 are not accepted on the Mac until the Results
  table is filled in from that run. The rules themselves are covered in CI by the kit
  (`ReducerArchiveTests`, `ProjectDisplayTests`) and `OfflineWorkspaceTests`.

## What changed (the run is checking this)

- Archiving keeps every task's project. An archived project stays browsable, its tasks stay
  editable, capture into it is refused, and "Restore" is now "Unarchive" everywhere.
- The sidebar section "Archived projects · N" is a collapsible disclosure (a tab stop), starts
  collapsed, and remembers its state in `mac-local.json`.
- File › "Archive project" / "Unarchive project" act on the open project (no shortcut).
- Unarchive is refused at once while another active project has the same name, with
  "Rename…" for the archived one.

## Setup

```sh
DIR="$(mktemp -d /tmp/bb-archive.XXXXXX)"
BRAINBUDDY_MAC_DATA_DIR="$DIR" macos/.build/BrainBuddyMac.app/Contents/MacOS/BrainBuddyMac
```

Create: projects "Old flat" (outcome "Keys handed back", three open tasks: one Next, one
Waiting "landlord", one Someday) and "Garden"; a Next task "Call the bank" with no project;
the tag "calls" on one "Old flat" task.

## Checks

| # | State (design X-06) | Steps | Expected |
|---|---|---|---|
| A1 | sidebar section | Right-click "Old flat" › "Archive project". | No confirmation. "Old flat" leaves Projects; "Archived projects · 1" appears, **expanded**, with "Old flat" (archive icon). |
| A2 | disclosure remembered | Collapse the disclosure, quit, relaunch. | "Archived projects · 1" is collapsed. Expand it, relaunch: expanded. |
| A3 | disclosure keyboard and VoiceOver | Tab to the disclosure; press Space. VoiceOver on. | It is a tab stop; Space toggles it; VoiceOver reads "Archived projects, 1, collapsed" / "…, expanded". |
| A4 | archived project open | Select "Old flat". | Title, "Archived" chip and "Unarchive" button; caption "Archived project · 3 open tasks" and "Unarchive this project to add tasks to it."; outcome shown, no "Edit outcome"; the three tasks listed and editable; no "Add a task" row. Tab order: title → Unarchive → task rows. |
| A5 | task elsewhere | Open Next actions (grouped by project) and Waiting for. | The group header and the row label read "Old flat · archived". |
| A6 | picker | Open the editor of an "Old flat" task; open the Project picker. | "Old flat · archived" selected, then the active projects; "No project". |
| A7 | capture into archived | In Inbox type "Buy tape @Old flat". | The preview says "Unarchive “Old flat” before adding a task to it." and "Add task" is disabled. |
| A8 | archived (just now) | With "Old flat" unarchived and open, choose File › "Archive project". | Selection stays on "Old flat"; the view becomes the archived view; the Archived section expands to show its row; focus is on the title (VoiceOver reads the title). |
| A9 | unarchived | Press "Unarchive". | Chip and button go; "Add a task" and "Edit outcome" return; "Old flat" back under Projects; focus on the title; no toast. |
| A10 | File menu guard | Type text in "Add a task" (do not save); open the File menu on an active project. | "Archive project" is disabled (its help text: "Add or clear the current task draft before archiving"). Same with an unsaved task edit open. Clearing the draft enables it. "Unarchive project" is enabled only on an archived project. |
| A11 | unarchive refused | Archive "Old flat"; create an active project "Old flat"; open the archived one; press "Unarchive". | Inline under the title: "Another active project is already called “Old flat”. Rename one first." with "Rename…"; no Retry; focus stays on "Unarchive". |
| A12 | rename archived project | Press "Rename…". | The "Rename project" sheet with the current name selected. Enter "Old flat 2" and save: the sheet closes, the refusal clears, focus returns to "Unarchive"; nothing is unarchived until "Unarchive" is pressed again, which then succeeds. **Known gap:** design X-06 expects the duplicate-name error when the new name is another active project's ("Garden"), but the kit renames an archived project without a uniqueness check, so "Garden" is saved and the next "Unarchive" is refused naming "Garden". Record what you see. |
| A13 | empty: archived before this change | Only reachable with a store that has a project archived before lossless archives with no tasks (e.g. the upgrade data of `manual-macos-upgrade.md` step 3, if it had one). | "No tasks in this project" / "Unarchive this project to add tasks to it." and the grey line "Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists." Mark n/a if no such project exists. |
| A14 | empty (filtered) | On the archived project, search a word that matches none of its tasks. | "No matching tasks" / "Clear the search or priority filter to see this project's tasks." |
| A15 | project review archive | Review projects › a project with no open actions › "Archive completed project…". | "Archive this completed project?" / "The project and its tasks remain available in Archived projects." |
| A16 | reviews | Waiting review on the "landlord" item, Someday review on its Someday item. | "Create follow-up…" and "Make it a Next action…" are disabled with "Unarchive the project to add a follow-up there." / "Unarchive the project to activate this task."; no string says "Restore". |
| A17 | error (local write failed) | Optional: `chmod 500 "$DIR"`, unarchive a project, `chmod 700 "$DIR"`. | Red line "Couldn't unarchive “Old flat”. Try again." with "Retry"; focus moves to Retry and VoiceOver announces the message; "Retry" clears it. |
| A18 | appearance | Light and Dark mode. | Both legible; the chip and the refusal readable. |

## Results (owner fills in; leave blank until the run is done)

| Field | Value |
|---|---|
| Date of run | |
| Run by | |
| Commit SHA under test | |
| Mac model / chip, macOS, Xcode | |
| A1 sidebar section | |
| A2 disclosure remembered | |
| A3 disclosure keyboard and VoiceOver | |
| A4 archived project open | |
| A5 task elsewhere | |
| A6 picker | |
| A7 capture into archived | |
| A8 archived (just now), focus | |
| A9 unarchived, focus | |
| A10 File menu guard | |
| A11 unarchive refused | |
| A12 rename archived project | |
| A13 empty: archived before this change | |
| A14 empty (filtered) | |
| A15 project review archive | |
| A16 reviews | |
| A17 error | |
| A18 appearance | |
| Notes / deviations | |

When every row is filled in and everything passes, change the status line at the top to
`PASS (owner run, <date>, <SHA>)`.
