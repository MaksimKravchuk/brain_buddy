# Manual iOS evidence — weekly review increment 3 (slice PR-12)

**Status: PENDING (owner run).** Nothing below has been run yet. This file was
written by the implementer of slice PR-12 in a Linux session, which can neither
build the app target nor run a simulator or device. Every result cell says
`PENDING` until the owner (or a session with Xcode) runs the steps and replaces it
with what was observed. Do not mark a row passed without running it.

- **Kind**: manual (tasks.md T159)
- **Data**: synthetic only (a fresh install or the `-BBUsePreviewData` launch
  argument, plus tasks created for the run; no real account data)
- **Build under test**: `<commit SHA>` (fill in) — Debug configuration, so
  `BBWeeklyReviewLocal` is `YES` for the account-less checks
- **Device / simulator**: `<model, iOS version>` (fill in)
- **Run by / date**: `<name>`, `<date>` (fill in)

## 0. Xcode-lane build of the app target

| check | how | result |
|---|---|---|
| App and widget targets compile | `(cd ios && xcodegen generate) && xcodebuild -project ios/BrainBuddy.xcodeproj -scheme BrainBuddy -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build`, or the `ios-app` lane of `.github/workflows/ci.yml` on the slice's SHA | PENDING |
| Previews render | open each `#Preview` in `Screens/Review/*.swift` (M-10 – M-22, including each "accessibility size" preview) | PENDING |

## Setup

Debug build, account-less, fresh install. Capture a mix of tasks: some in Inbox
(16 or more for the M-15 choices), tasks in Next that are 4+ weeks old (move the
simulator clock forward, or seed a signed-in test backend with
`review-seed-aged-task`), a Waiting task older than 7 days, Someday tasks, a
project with no next action, tasks due in the next 14 days, and a few completed
this week.

## 1. One decision per screen, the Lists row and focus

| id | what to check | steps | result |
|---|---|---|---|
| `020-FR-034` | One decision per screen in the Inbox, decision, Waiting and Someday steps | Run a Full review: in each of these four steps only one item is on screen, its title is the heading, and after a decision the next item's title is read by VoiceOver | PENDING |
| `020-FR-042` | The Lists row replaces `DeferredRow` when the review is exposed | Debug build: Lists shows a working "Weekly review" row with "Set up in a minute" before the first review and "Last review: N days ago" after one. Release build account-less: the "coming later" row, not interactive | PENDING |
| 44 pt targets | Leave, Skip, Next, Done, the choice rows, Undo, the clear-start answers | Accessibility Inspector hit-test on M-10 – M-22: every target ≥ 44 × 44 pt | PENDING |
| VoiceOver focus M-10 | The restart screen moves focus to its heading when it appears | Restart mode (no counted review for 21+ days, onboarded): open the review with VoiceOver on; the heading is read first | PENDING |
| VoiceOver focus M-11 | The entry moves focus to its heading | Lists › Weekly review with VoiceOver on | PENDING |
| VoiceOver focus M-12 | Onboarding moves focus to "A weekly reset" | First review on a fresh install with VoiceOver on | PENDING |
| Step change focus | Focus goes to the step title at every step change | Next through a Full review with VoiceOver on | PENDING |
| Reduce Motion | Step changes are instant | Settings › Accessibility › Motion › Reduce Motion on; Next through the steps | PENDING |
| Leave and resume | Leave keeps everything; the entry offers Continue | Leave mid-review (confirm "Take a break?"); Lists › Weekly review shows the resume card with the step and decisions so far | PENDING |
| Unsaved text | Leave, Skip and Next ask before losing typed text; it comes back after an app kill | Mind sweep: type a line without adding it, tap Next: the question names the line; "Keep editing" is the default; kill the app and reopen the step: the line is back | PENDING |

## 2. Dynamic Type at AX5 (design "Mobile viability")

Settings › Accessibility › Display & Text Size › Larger Text › the largest size
(AX5). For each screen: no control is clipped or truncated, the body scrolls above
the bottom bar, and the primary action stays reachable.

| screen | state(s) to open | result |
|---|---|---|
| M-10 Restart | default, released (with Undo), undone, nothing older than 4 weeks | PENDING |
| M-11 Entry | mode picker, resume card, closed-after-a-week line | PENDING |
| M-12 Onboarding | default, threshold changed | PENDING |
| Step bar | "N of M" and the segments scroll sideways; Leave and Skip keep 44 pt targets | PENDING |
| M-13 Wins, M-14 Mind sweep | with and without items | PENDING |
| M-15 Inbox | the three choices, an item, done with release | PENDING |
| M-16 Decisions | a card, all decided, some left | PENDING |
| M-17 Rest of Next, M-21 Dates | with items and empty | PENDING |
| M-18 Waiting, M-19 Projects, M-20 Someday | an item with its choices, a title being typed, empty | PENDING |
| M-22 Summary | the ten counts are **one column**; the calm line; the clear-start question | PENDING |
