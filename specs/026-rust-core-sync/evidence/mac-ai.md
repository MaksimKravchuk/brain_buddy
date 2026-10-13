# 026 Mac AI suggestion evidence (T060, PR-60)

Status: **pending real-Mac run**. Nothing below has been observed on a real Mac; every row is open.
The model wiring and the phase-to-screen mapping are covered by
`swift test --package-path macos --filter ReviewSuggestionTests` (a fake on-device executor, the
real Rust policy through the bridge, no provider, no real model); that is not a substitute for this
run. `VoiceCapture` is transcription and does not count as this journey.

Run on: ______ (macOS version) · build: ______ · Apple Intelligence: on / off / not eligible · signed in: yes / no · tester: ______

The entry needs the Weekly Review exposed (signed in: the `weekly_review` flag; account-less: the
release switch) and a task in Next actions. Cloud rows need a configured provider and a signed-in account.

| # | Design state | Check | Result |
|---|---|---|---|
| 1 | D-04 entry | Task detail of a Next action shows "Suggest with AI…" with the note that nothing changes until applied; absent on Waiting, Someday, Inbox, completed tasks and while the review is not exposed | pending |
| 2 | D-04.01 | Choosing "Suggest clearer wording" / "Suggest a first step" opens the sheet; nothing is requested until "Request suggestions" | pending |
| 3 | D-04.01 / .02 | Apple Intelligence available: "Preparing suggestions…", then "Review suggestion" with an editable field; network trace shows no request | pending |
| 4 | D-04.08 | Apple Intelligence off, device not eligible, model not ready, unsupported language: the unavailable copy with the reason and "Continue without AI"; no remote request | pending |
| 5 | D-04.05 | Local error with a signed-in account: no silent cloud fallback; "Try cloud suggestions instead" only after the person chooses it | pending |
| 6 | D-04.03 | First cloud run: configured provider name, the exact field list, "Notes are sent as written, including any names in them."; "Continue without AI" sends nothing | pending |
| 7 | D-04.03 / .09 | "Allow cloud suggestions" records consent once per owner and provider; consent text change asks again; revoke while in flight: late result not shown, "Cloud suggestions are off" | pending |
| 8 | D-04.10 | Proposals: pick one, edit it, "Apply suggestion" changes the task title through the ordinary command; "Keep current wording" leaves it; nothing changes before Apply | pending |
| 9 | D-04.06 | Notes over the limit: "Part of the notes was not considered." shown before Apply | pending |
| 10 | D-04.11 | Edit the task in the detail while the sheet is open, then Apply: "This task changed…", proposal and edit kept, "Review the task" then Apply again | pending |
| 11 | D-04.12 | Applied: "Suggestion applied", announced by VoiceOver; Done closes and a reopened sheet starts clean | pending |
| 12 | D-04.13 / .14 | Cancel before transmission: "Nothing was sent"; after transmission: provider-may-still-process copy; repeated Cancel disabled while stopping; late result ignored | pending |
| 13 | D-04.15 | Close the sheet during a request and reopen: the same live request. Quit the app during a request and relaunch: "Suggestions were interrupted…", no automatic resend | pending |
| 14 | D-04.16 | Clarifying question: question as heading, "Your answer" field focused, draft kept on close and reopen; not shown as an error or a proposal | pending |
| 15 | D-04.17 | "Add to notes and suggest again": answer appended to the notes once, "Saving…" only after 300 ms, saved revision adopted, suggestions rerun with current consent | pending |
| 16 | D-04.18 | Notes save fails or conflicts: "Couldn't add your answer…", answer kept, reference shown for a server failure, Retry; no inference started | pending |
| 17 | D-04.19 | Save succeeds, inference fails: "Your answer was saved. Suggestions aren't available."; "Try suggestions again" never appends the answer again (check the notes) | pending |
| 18 | D-04.20 | Close (button and Esc) with a typed answer: "Discard your answer?", "Keep editing" focused first and on Esc; only "Discard" removes the draft | pending |
| 19 | Focus | Each screen starts on its outcome heading (answer field for .16/.18, Keep editing for .20); sync state changes never open the sheet or move focus | pending |
| 20 | VoiceOver | Headings, "Your answer" label, proposal choices with Selected value, polite announcements for stopping / cancelled / interrupted / applied, Reference Copy; Tab order; sheet height scrolls | pending |

Known gaps to confirm or close before this can pass:

- Focus on each new screen relies on `defaultFocus` with a fresh view identity per screen; whether
  AppKit honours it on every transition (for example into the outcome heading after Cancel) is only
  knowable on a real Mac.
- The sheet closes to the task detail; whether focus returns to "Suggest with AI…" after Discard is
  system behaviour to observe (no `@FocusState` is assigned outside the router).
- The Foundation Models executor reports availability, languages and memory as the system exposes them
  (memory is not exposed, so no requirement is stated); how the policy treats a real "ready" Mac is
  unobserved.
- Entry blocked with a message ("Save or discard your changes to this task to ask for suggestions.")
  while the task editor has unsaved changes: confirm on a real Mac, including that the entry returns
  after Save or Discard.
- Journal, consent-change and failed-revoke copy ("couldn't save its local record", "Your consent is
  still on") is covered at the mapping level only; the failure paths themselves need a real run.
