# M01/M07 main-window chrome board parity

Accepted outcome: match the shared window chrome in [M01](../../board/mac/M01-Mac.png)
and [M07](../../board/mac/M07-Mac.png), preserving existing commands, data,
keyboard shortcuts and unsaved-edit protection. PNG appearance is the owner-approved
authority, including the visible command differences.

| Surface | Before | After |
| --- | --- | --- |
| Welcome | ![M01 before](m01-before.png) | ![M01 after](m01-after.png) |
| Inbox chrome | ![M07 before](m07-before.png) | ![M07 after](m07-after.png) |

These are actual app captures from disposable profiles at 1470x833 points. Counts,
projects, tags and Agents follow the existing profile/account/flag state; the board's
fixture data is not imposed on the app. [Fresh 960x640 Welcome](m01-after-default.png)
confirms the default window has no left clipping. The native full-window regression
also checks the board's 1280x800 viewport.

The sidebar plate defaults to 240pt with its native 8pt outer inset, 29pt navigation
rows and the existing selection binding. Native resizing retains the original 400pt
maximum. Projects precedes History; the visible labels are Someday / maybe and Done.
The inactive Weekly review placeholder is absent. Populated/loading/failed Tags stays
available as shown in DSMac; only the empty ready section is hidden. Existing Agents
visibility and collapsed-sidebar sync attention remain. The calm footer uses the
refresh glyph and separate On this Mac / Sign in to sync actions.

M01 keeps native window controls and a 52pt toolbar container with only a flexible
spacer. The welcome brand's first ink is about 64pt below the real window top, against
about 65pt in the PNG. M07 has trailing, untinted glass New step, microphone and Quick
Open controls, with primary ink specified inside their labels and secondary shortcuts.
The inspector wrapper accepts the available width so its sidebar safe area is not
counted twice in the split minimum; the detail keeps its existing 560pt minimum.
Task canvas and inspector contents are outside this correction.

Owner-approved command relocation: File retains New step (Command-N), Quick Open
(Command-O), Quick Capture (Control-Option-Shift-B), Voice to task draft, New tag,
New project and Review projects. Edit > Find > Search tasks (Command-F) retains full
task filtering separately from Quick Open. View and Control-Command-S retain native
sidebar visibility. Quick Capture fallback copy now points to File. Creation menus
are disabled while a collection draft is open, and stale callbacks recheck current
presentation/write state before clearing a name.

Native checks passed: fresh default layout, native window zoom, sidebar hide/restore,
three distinct toolbar accessible names, Quick Open and Search focus plus Escape,
Quick Capture open/close, and collection-command disabled/re-enabled behavior.
A unit regression verifies that stale project/tag creation callbacks preserve an
unsaved name and that creation resumes after dismissal. Manual sidebar arrow-key
movement was not verified; native List selection and its existing binding remain.

Validation: 463 Mac tests in 50 suites pass after 76.057 seconds. The shared kit
passes 1,508 tests in 154 suites. The chrome suite includes actual native split/item
placement assertions and light/dark hosted snapshots. Hosted button snapshots cover
visible label ink and inherited app tint; these live app captures are the glass
compositor authority. Actual native1x baselines remain a first-CI record/review/replay
gate; no simulated 1x raster or snapshot tolerance was added.

This record accepts only the bounded local chrome correction. Exact-SHA independent
QA, CI, rebase, release and production evidence remain separate parent-owned gates.
