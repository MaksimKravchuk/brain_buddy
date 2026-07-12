# Brain Dump mobile-first UX proposal

Status: Founder review proposal — not an implementation specification

Primary surface: **Operate**. This tranche contains one Brain Dump session and nothing else.

## Product flow

1. Open one Brain Dump session.
2. Dictate or type. Each understood item is appended as a provisional draft in one flat list.
3. Review the list. Edit wording directly or delete an unwanted draft.
4. Choose only **Add voice**, **Add text**, or **Save session**.
5. Save every remaining draft as a plain task in RTM Inbox and close the session.

There is no hierarchy, decomposition, advice, task classification, suggestion, per-item destination, or secondary planning step.

## Screen states

### Capture by voice

- The growing chronological list is the dominant surface.
- Every draft has a stable `#N`, `Wording still changing`, and `Provisional`.
- A compact recording cue sits in the bottom dock without a transcript, timer, pipeline, or analysis panel.
- Founder-required **Cancel**, **Stop**, and **Review** controls remain visible.
- Stop and Review both enter the same plain editor; there is no processing or confirmation detour.

### Edit and review

- The same flat list becomes a set of text areas.
- Each draft can be edited or deleted. No other per-item action exists.
- The sticky dock exposes exactly three outcomes: **Add voice**, **Add text**, **Save session**.
- Add voice returns to capture and appends to the same session.
- Add text opens a single-task form and appends to the same session.

### Add by text

- One labelled text area accepts one draft.
- Cancel returns to the unchanged review list.
- Add to session appends the draft and returns to review.

### Session saved

- The session closes with a simple count.
- Copy states that every remaining draft was saved as a plain task to RTM Inbox.
- The only next action is starting a new Brain Dump session.

## Responsive and accessibility rules

- The task list and editor use one readable column at 375px, 430px, and larger widths.
- Controls have at least 44px hit targets, visible focus treatment, and safe-area padding.
- List and form semantics are explicit; incremental drafts use `aria-live`.
- Long wording wraps naturally and editor text areas can grow vertically.
- Recording state is communicated in text, not only through animated bars or color.
- Reduced-motion preference disables the audio-bar animation.
- There is no horizontal page overflow at the two required phone widths.

## Scope guardrail

This prototype intentionally omits all Current Reality, tree, coaching, problem-analysis, recommendation, decomposition, complex-work, suggestion, task-type, routing, promotion, confirmation-batch, and per-task destination concepts. Those do not belong inside Brain Dump.

## Prototype notes

`prototype.html` is self-contained and does not change production behavior. Stable routes are:

- `?screen=recording`
- `?screen=review`
- `?screen=add-text`
- `?screen=saved`

The state selector exists only for founder review and deterministic screenshots.
