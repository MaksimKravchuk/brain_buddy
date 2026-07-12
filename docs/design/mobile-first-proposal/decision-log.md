# Mobile-first UX decision log

Status: Proposed for founder review

Scope: static UX direction only; no production feature code

## Deliberately included

1. **Brain Dump and Weekly Review as equal first-class destinations.** They are the vNext wedge, not secondary tools hidden behind the CRT canvas.
2. **A mobile bottom bar and desktop left rail with the same four destinations.** Information architecture stays stable while composition changes by viewport.
3. **A persistent, thumb-reachable action dock.** The active workflow’s primary action remains visible above browser and device safe areas.
4. **Live transcript and provisional candidates in one recording screen.** This demonstrates responsiveness without implying that provisional output is committed.
5. **Explicit proposal provenance and authority.** Provisional, reconciled, low-confidence, user-edited, route/promotion, and conflict states are distinguishable.
6. **Confirmation before canonical writes.** Safe additions can be selected together; destructive/external/existing-item/CRT actions remain individually visible.
7. **Resumable async, offline, retry, partial-commit, and terminal-error states.** These are core product behavior, not edge-case polish.
8. **Weekly Review as a bounded queue with one-item phone focus.** Every item receives an outcome or explicit defer before completion.
9. **CRT as focused mobile inspect/edit plus full desktop canvas.** Mobile supports meaningful thinking work but does not pretend a 375px canvas equals desktop.
10. **Privacy and retention in the product shell.** Microphone permission, external-processing consent, audio retention/deletion, and “safe to leave” are visible at the relevant moment.

## Intentionally excluded or deferred

- Production React components, API integration, responsive Tailwind changes, migrations, or backend state-machine work.
- Native iOS/Android patterns, push notifications, background audio guarantees, or app-store packaging.
- A proprietary task list, calendar, reminders, recurrence, priorities, or multiple tracker connectors.
- Fully editable external task-tracker objects; external references remain route/result context.
- Automatic approval, deletion, routing, or CRT promotion by either model stage.
- Exact waveform/transcription technology and provider branding.
- Final copy, onboarding education, localization, analytics instrumentation, and formal usability research.
- A full mobile graph-layout algorithm. The proposal uses a focused subtree plus node sheet; implementation needs a dedicated CRT interaction spike.
- Cross-system atomic undo. The UI communicates bounded undo and explicit follow-up after irreversible external actions.
- Visual-theme variants or dark mode until the interaction model is approved.

## Founder questions

1. **Default landing:** Should signed-in phone users land directly on Brain Dump, or on a small Home/activity screen that also exposes “Resume Weekly Review” and completed background work?
2. **Recording density:** During speech, should provisional candidate cards appear below the live transcript (more reassurance, more motion), or should the recording view stay calm and show only a candidate count until the user stops?
3. **Confirmation speed:** Is “Select all safe additions” acceptable as the default, while route/delete/existing-item/CRT actions always require individual review, or should every candidate start unselected?
4. **Destination timing:** Should destination/route be chosen while editing each candidate, or only after wording is confirmed in a second lightweight routing step?
5. **Weekly Review action model:** On phone, do you prefer the explicit action dock shown here, or swipe gestures as optional accelerators after the explicit controls are learned?
6. **Voice-led review:** Should the microphone remain available throughout item-by-item Weekly Review, or should voice be an opt-in mode launched separately from the tap-first review?
7. **CRT promotion threshold:** Should “Promote to CRT” appear as a normal review action on every problem candidate, or only when BrainBuddy explains a repeated/complex signal?
8. **Mobile CRT ambition:** Is focused subtree + node sheet enough for MVP, with full graph manipulation positioned as desktop-first, or is phone graph creation a launch requirement?
9. **Privacy posture:** Is 24-hour raw-audio retention after successful reconciliation acceptable as the default, or should “delete audio immediately” be the default toggle?
10. **Tone and branding:** Should BrainBuddy feel calm and editorial (the restrained proposal direction), or more energetic during capture to reinforce momentum?

## Review outcome template

Record founder feedback here before implementation begins:

- Keep:
- Add:
- Remove:
- Change:
- Answers to questions:
- Approved direction and date:
