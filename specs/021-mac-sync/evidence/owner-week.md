# Feature 021 — the owner's week (021-SC-007, quickstart Scenario 9)

**Status: PENDING. No day has been recorded.** This file is a template. It never counts as
evidence while it holds only the template below, and 021-SC-007 is met only when it holds
**seven dated entries** (one per day of one week of normal work).

> **021-SC-007:** The owner uses Mac, iPhone and web on one account for one week of normal work.
> They never need "Sync now", and they report no moment where the Mac and iPhone disagreed after
> both were open and online for a minute.

- **Who fills it in:** the owner, once a day, after the Mac sync build (slice PR-09) is landed and
  installed. This is post-release acceptance, not a slice gate.
- **Content-free:** answer yes/no and give a count. Do not write task titles, project names,
  emails other than `@example.com`, paths, tokens or command output. See
  [README.md](README.md) for the rule.
- **A "yes" is a finding, not a failure to hide.** If a day has "needed Sync now: yes" or "saw
  Mac and iPhone disagree: yes", say which day, and the fix lands in a separate PR; the week is
  then run again from day 1 on the fixed build.
- **Sync issues** are the "N changes couldn't sync" or "Couldn't sync" lines the Mac showed that
  day (count of distinct occurrences; `0` when none).

## Entries

Copy the block for each day, replace the date, and delete the unused template rows when the week
is done. The template row (`YYYY-MM-DD`) is not an entry.

| Day | Date | Needed Sync now: yes/no | Saw Mac and iPhone disagree after a minute online: yes/no | Sync issues seen (count) |
|---|---|---|---|---|
| 1 | YYYY-MM-DD | | | |
| 2 | YYYY-MM-DD | | | |
| 3 | YYYY-MM-DD | | | |
| 4 | YYYY-MM-DD | | | |
| 5 | YYYY-MM-DD | | | |
| 6 | YYYY-MM-DD | | | |
| 7 | YYYY-MM-DD | | | |

## Read-out

| Field | Value |
|---|---|
| Week from / to | |
| Build (candidate SHA) the Mac ran | |
| Days with "needed Sync now: yes" | |
| Days with "saw Mac and iPhone disagree: yes" | |
| Total sync issues seen | |
| Verdict (021-SC-007 met: yes/no) | |
