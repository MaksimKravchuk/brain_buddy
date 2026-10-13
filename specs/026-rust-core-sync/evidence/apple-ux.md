# Apple UX evidence: sync status, conflicts and recovery (T045)

Status: **pending device run**. Nothing below has been executed on a real iPhone. Each row is a
journey for a human to run on a device build (iOS 26) and record against. Do not fill in a result
that was not observed.

Design reference: `specs/026-rust-core-sync/design.md` (M-01, M-02, M-03, D-02.11-12), accepted
2026-10-09 (`approval.md`). Code: `ios/BrainBuddy/Components/SyncStatusLabel.swift`,
`ios/BrainBuddy/Screens/Settings/SyncIssuesScreen.swift`,
`ios/BrainBuddy/Screens/Settings/SyncRuntimeIssueViews.swift`,
`ios/BrainBuddy/Screens/Settings/SettingsScreen.swift`; logic in
`ios/BrainBuddyKit/Sources/BrainBuddyCore/RuntimeIssuePresentation.swift`.

Device / OS / build: _pending_  Run date: _pending_  Tester: _pending_

| # | State | Journey | Expected | Result |
|---|---|---|---|---|
| 1 | M-01.01 | Fully synced, queue empty: open the task list and Settings > Sync | "Synced just now"; no pending count | pending device run |
| 2 | M-01.03 | Account-less use | "On this iPhone · Sign in to sync" | pending device run |
| 3 | M-01.05 | Airplane mode, edit three tasks, relaunch | "Offline · 3 changes waiting" and "Your changes are saved on this device."; Sync now explained as off | pending device run |
| 4 | M-01.06 | Online with changes not yet acknowledged | "Synced N min ago · 3 changes waiting" | pending device run |
| 5 | M-01.08 | One change rejected, others synced | "1 change couldn't sync", Open sync issues reachable | pending device run |
| 6 | M-01.09 | Expire the session | "Sign in again to sync"; waiting changes stay with the account | pending device run |
| 7 | M-01.10 | Store written by a newer app (`syncRecovery.storeNeedsUpdate` feeds the status line and the Settings recovery card). A newer *protocol* has no signal yet (PR-40) and stays unreachable | "Update needed to sync" / "Update needed to open tasks" | pending device run |
| 8 | M-02.01 | Edit the same title on two devices offline, reconnect, open the issue; choose a version, Apply choice (wired to `Workspace.resolveIssue`) | Both versions shown (the account side read from `accountVersion(ofIssue:)`), no default selected, saved text verbatim; Apply stores once and the issue leaves the list | pending device run |
| 9 | M-02.08 | Change the task again on the other device while the issue is open | "This task changed again. Review both versions."; draft kept; choice cleared | pending device run |
| 10 | M-02.09 | Delete a tag elsewhere, edit it here | "This item was deleted on another device. Your edit is saved in this issue."; Copy saved edit | pending device run |
| 11 | M-02.11 | Conflict with later actions | "2 later actions need your decision"; each defaults to Keep for later; retry needs approval | pending device run |
| 12 | M-02.12 | Select Discard action, tap Discard | Named confirmation "Discard these 2 saved actions?"; Cancel keeps the selection | pending device run |
| 13 | M-02.07 | Force-quit with an unsent decision draft, relaunch | Nothing submitted; originals kept; choices restored from the per-issue file (`ConflictDraftStore`), a selected discard must be confirmed again; cleared after a successful resolve | pending device run |
| 14 | A11y | VoiceOver, largest Dynamic Type, Reduce Motion, 44 pt targets across rows 1-12 | Labels read the state and reference ID; no colour-only status | pending device run |
| 15 | M-03 | Settings > Sync recovery row (Update app, Try again on a failed rebuild; Try again runs `rebuildSyncedCopy()`, which says "nothing was rebuilt" while no transport is installed) | Honest result; waiting changes and saved issues named as kept | pending device run |
