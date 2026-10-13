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
| 7 | M-01.10 | Unsupported protocol/store (needs a runtime signal; not wired yet) | "Update needed to sync" | pending device run (blocked: no Workspace signal) |
| 8 | M-02.01 | Edit the same title on two devices offline, reconnect, open the issue | Both versions shown, no default selected, saved text verbatim | pending device run |
| 9 | M-02.08 | Change the task again on the other device while the issue is open | "This task changed again. Review both versions."; draft kept; choice cleared | pending device run |
| 10 | M-02.09 | Delete a tag elsewhere, edit it here | "This item was deleted on another device. Your edit is saved in this issue."; Copy saved edit | pending device run |
| 11 | M-02.11 | Conflict with later actions | "2 later actions need your decision"; each defaults to Keep for later; retry needs approval | pending device run |
| 12 | M-02.12 | Select Discard action, tap Discard | Named confirmation "Discard these 2 saved actions?"; Cancel keeps the selection | pending device run |
| 13 | M-02.07 | Force-quit with an unsent decision draft, relaunch | Nothing submitted; originals kept (draft restore needs a Workspace store; not wired yet) | pending device run |
| 14 | A11y | VoiceOver, largest Dynamic Type, Reduce Motion, 44 pt targets across rows 1-12 | Labels read the state and reference ID; no colour-only status | pending device run |
| 15 | M-03 | Recovery entry (Rebuild synced copy, Update app) | Not wired in this slice | pending device run (blocked: no recovery API) |
