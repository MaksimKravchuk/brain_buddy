# Mobile-first UX decision log

Status: Proposed for founder review

Scope: static UX direction only; no production feature code

## Deliberately included

1. **Brain Dump and Weekly Review as equal first-class destinations.** They are the vNext wedge, not secondary tools hidden behind the CRT canvas.
2. **A mobile bottom bar and desktop left rail with the same four destinations.** Information architecture stays stable while composition changes by viewport.
3. **A persistent, thumb-reachable action dock.** The active workflow’s primary action remains visible above browser and device safe areas.
4. **Chronological session task list as the active Brain Dump surface.** The user watches extracted tasks accumulate while speaking; the recorder is a compact utility rather than the page’s focal object.
5. **Explicit proposal authority during capture.** Every extracted draft keeps a stable ordinal plus “Wording still changing” and “Provisional”; full provenance and reconciliation stay out of the active capture view.
6. **Confirmation before canonical writes.** Safe additions can be selected together; destructive/external/existing-item/CRT actions remain individually visible.
7. **Resumable async, offline, retry, partial-commit, and terminal-error states.** These are core product behavior, not edge-case polish.
8. **Weekly Review as a bounded queue with one-item phone focus.** Every item receives an outcome or explicit defer before completion.
9. **CRT as focused mobile inspect/edit plus full desktop canvas.** Mobile supports meaningful thinking work but does not pretend a 375px canvas equals desktop.
10. **Privacy and retention in the product shell, not the active list.** Permission and blocking errors appear when action is required; diagnostics, retention, upload, and routing details stay behind post-Finish or secondary paths.

## Founder feedback incorporated — 2026-07-12

- **Keep:** continuous voice capture, incremental extraction, safe tentative-task contract, mobile accessibility, and post-Finish review.
- **Remove from active capture:** giant record affordance, red live treatment, prominent timer, transcript feed, upload/chunk status, pipeline stages, routing choices, CRT promotion, confirmation flow, and error-state gallery.
- **Change:** the chronological current-session draft list is now the primary content. Session identity and recording state are subtle; Cancel / Stop / Review remain primary in a compact dock, with Pause / Resume subordinate beside a five-bar audio cue and no elapsed timer.
- **Accessibility guardrails:** controls remain at least 44px, state is named in text and shape rather than color alone, paused bars stop moving, reduced-motion is honored, long tasks wrap, focus remains visible, and the empty list explains what will happen.

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
2. **Recording density — answered:** show the growing chronological task-card list while speaking; remove the transcript and operational status from this view.
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
