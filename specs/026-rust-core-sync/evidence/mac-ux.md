# 026 Mac UX evidence (PR-46)

Status: **pending real-Mac run**. Nothing below has been observed on a real Mac; every row is open.
Model-level behavior is covered by `swift test --package-path macos --filter RustSyncRecoveryTests`
(not a substitute for this run).

Run on: ______ (macOS version) · build: ______ · tester: ______

| # | Design state | Check | Result |
|---|---|---|---|
| 1 | D-01.01-.06 | Quiet row unchanged: indicator after 1 s, waiting suffix after 10 s, no layout shift | pending |
| 2 | D-01.07 | After 60 s of failure: "Couldn't sync · Retry", reference ID shown and Copy works | pending |
| 3 | D-01.08 | One rejected change: "1 change couldn't sync"; others stay synced; Review opens detail | pending |
| 4 | D-01.09 | Session ended: "Sign in again to sync"; focus on "Sign in again"; editing continues | pending |
| 5 | D-01.10 / D-03.08 | Unknown protocol: "Update needed to sync", announced once, Sync now disabled, Update app works | pending |
| 6 | D-02.01 | Conflict: two versions, no default radio, Apply choice disabled until selected | pending |
| 7 | D-02.02/.05/.07 | Saving, failed save (versions and selection kept), offline choice shown as waiting | pending |
| 8 | D-02.08 | Account side changes while open: message shown, draft kept, approvals cleared, apply again | pending |
| 9 | D-02.09 | Deleted elsewhere: Copy saved edit, Keep item deleted; nothing is recreated | pending |
| 10 | D-02.11 | "2 later actions need your decision": Keep for later default; Review and retry needs approval | pending |
| 11 | D-02.12 | Discard: named list, Cancel focused first, "Discard 2 actions"; Cancel keeps all choices | pending |
| 12 | D-02.11-.12 | Quit/relaunch mid-decision: draft restored, nothing submitted, no silent loss | pending |
| 13 | D-03.01-.10 | Rebuild, failed rebuild with reference, import failed, migration uncertain, interrupted | pending |
| 14 | Accessibility | Tab order, VoiceOver labels and announcements, Esc closes, bounded height (<= 480 pt) with scroll | pending |

Known gaps to confirm or close before this can pass: applying a conflict resolution, recovery
status feed and draft persistence need Workspace APIs that do not exist yet (see PR-46 report).
