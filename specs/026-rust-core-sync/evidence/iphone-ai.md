# iPhone Weekly Review suggestions evidence (T059, PR-59)

Status: **pending**. Nothing below has been observed on a real iPhone yet. The sheet
(`ios/BrainBuddy/Screens/Review/ReviewSuggestionSheet.swift`, opened from the decision card) renders PR-49's
shared `ReviewSuggestionModel`; the package tests prove the model, not the screen. Each line is filled in only
from a real run, with build, device, iOS version and date. Companion to `ai-consent.md` (model-level checklist).

Scope: M-04 states .01-.20, first Weekly Review suggestion path (026-FR-018, 026-FR-019, 026-FR-020,
026-FR-023, 026-SC-006). Entry: decision card, "Need an idea?" -> "Suggest new wording" / "Suggest a first step".

Run record: build ____  device ____  iOS ____  Apple Intelligence on/off ____  date ____

## Local availability (.01, .02, .08)

- [ ] Apple Intelligence available: Request suggestions shows proposals; network trace shows no request
- [ ] Apple Intelligence off / device not eligible / model not ready: "On-device suggestions aren't available for this task" with the reason; signed out: no cloud route; Continue without AI works
- [ ] Task language unsupported by the on-device model: same state, reason named
- [ ] Signed in with local unavailable: cloud is reached only through the consent prompt (no silent fallback)
- [ ] Local executor error while signed in: "Try cloud suggestions instead" is an explicit button; nothing sent before it

## Consent denial and revocation (.03, .09)

- [ ] First cloud use: provider name comes from server configuration; the six listed fields are exact; Continue without AI sends nothing
- [ ] Allow cloud suggestions records consent once; second request does not ask again
- [ ] Consent text version change: prompt says what is sent changed, asks again
- [ ] Revoke consent (Settings) while a request is live, reopen: "Cloud suggestions are off"; late result not shown

## Request lifecycle (.02, .04-.07, .13-.15)

- [ ] No suggestion: "No suggestion this time", manual path intact
- [ ] Provider error / rate limit / cost cap: "Suggestions aren't available", reference ID shown and copied by "Copy reference ID"
- [ ] Notes reduced: "Part of the notes was not considered" shown before Apply
- [ ] Offline signed in: "Offline - connect to request cloud suggestions"
- [ ] Cancel before send: "Stopping suggestions..." then "Nothing was sent."; repeat Cancel is disabled
- [ ] Cancel after send: "provider may still finish processing data already sent"; no result applied
- [ ] VoiceOver: stopping / cancelled / interrupted announced once, focus on the outcome heading
- [ ] Close the sheet during a request, reopen: same live request or its proposal
- [ ] Kill the app during a request, relaunch, reopen: "Suggestions were interrupted", no automatic resend, Request again is explicit
- [ ] Current task payload and manual decision unchanged after every outcome above

## Proposal, edit and apply (.10-.12)

- [ ] Nothing in the task changes before Apply suggestion (check Today/list and the card)
- [ ] Edited proposal applies the edited text
- [ ] Task changed elsewhere after the sheet opened: "This task changed", edit kept; Review the task then Apply again works
- [ ] Applied: sheet and card close, "Wording updated.", task shows the new wording; no completion, no AgentRun badge
- [ ] Inside a review run: after Apply the card shows the existing stale view (known limit, see PR notes)

## Clarifying question and answer (.16-.20)

- [ ] Question state is shown (not error/empty); answer field focused
- [ ] Add to notes and suggest again: "Saving..." only after ~300 ms; answer appended once; rerun uses new notes
- [ ] Answer-save failure: "Couldn't add your answer to the notes", answer kept, Retry; reference ID for server failure
- [ ] Lost acknowledgement (airplane mode mid-save): retry does not append twice
- [ ] Saved answer, inference failure: "Your answer was saved", Try suggestions again reruns inference only
- [ ] Revision adoption: Apply after the answer save succeeds without a false stale
- [ ] Close with typed unsent answer: "Discard your answer?" with Keep editing / Discard; swipe-down blocked while editing
- [ ] Backgrounding / process kill with typed answer: draft returns on reopen; only Discard removes it

## Accessibility

- [ ] Dynamic Type at AX5: no clipped copy, all buttons >= 44 pt
- [ ] VoiceOver reads each state's heading first; Apply disabled state announced
- [ ] Reduce Motion: no custom animation introduced
- [ ] Keep editing is the initially focused choice in the discard alert (iOS alert default: confirm on device)
