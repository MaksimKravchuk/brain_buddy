# Voice-only Brain Dump founder-review prototype

Status: Founder review proposal — not an implementation specification

Primary surface: **Operate**. The growing voice-derived draft list and inline review editor are the whole experience.

## Locked flow

1. Start an active voice recording session.
2. Each understood item appears in one flat chronological draft list.
3. Open Review. Existing wording can be keyboard-edited inline or deleted.
4. Return to voice capture to continue speaking, or Save session.
5. Save exports every remaining draft as a plain item to RTM Inbox and closes the session.

## Screen states

### Active voice capture

- The flat list is the dominant surface.
- Every draft keeps a stable `#N`, `Wording still changing`, and `Provisional`.
- A compact listening cue sits in the bottom dock without transcript, timer, pipeline, or analysis panel.
- **Cancel**, **Stop**, and **Review** remain visible.
- Stop and Review enter the same editor.

### Review

- The same flat list becomes inline wording fields.
- Existing drafts can be edited or deleted. There is no control for creating a draft here.
- The dock exposes exactly two outcomes: **Return to voice capture** and **Save session**.
- Returning resumes the same voice session and preserves edits.

### Saved result

- The session closes with a simple count.
- Every remaining draft is exported as a plain RTM Inbox item.
- The only next action starts a new voice session.

## Scope guardrail

This prototype contains no keyboard capture path, separate text-entry state, item type labels, Current Reality, CRT, planning, analysis, recommendation, hierarchy, subtasks, or API contract. Keyboard input exists only for correcting wording already captured by voice.

## Responsive and accessibility rules

- One readable column at 375px, 430px, and larger widths.
- Controls have at least 44px hit targets, visible focus treatment, and safe-area padding.
- List and editor semantics are explicit; long wording wraps and fields grow vertically.
- Recording state is communicated in text, not only by animation or color.
- Reduced-motion preference disables the audio-bar animation.
- No horizontal page overflow at either required phone width.

## Prototype routes

`prototype.html` is self-contained and does not change production behavior.

- `?screen=recording`
- `?screen=review`
- `?screen=saved`

The state selector exists only for founder review and deterministic screenshots.
