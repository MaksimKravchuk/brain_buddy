# Brain Dump UX decision log

Status: Proposed for founder review

Scope: static Brain Dump prototype only; no production feature code

## Founder scope reset — 2026-07-12

The earlier broad mobile-product proposal is superseded for this tranche. Brain Dump is one focused capture session, not a gateway to planning or problem-solving features.

## Decisions

1. **One session, one flat list.** Voice and text append provisional drafts in chronological order.
2. **Draft authority stays explicit.** Stable `#N`, `Wording still changing`, and `Provisional` remain visible during capture. Review retains `#N` and `Provisional` while wording is directly editable.
3. **Manual correction only.** A user can edit wording or delete a draft. There is no hierarchy, reordering, merge/split, decomposition, classification, advice, or suggested action.
4. **Three review outcomes only.** The review dock contains Add voice, Add text, and Save session.
5. **One fixed export.** Save session sends every remaining draft as a plain task to RTM Inbox. There is no per-item destination control or additional confirmation screen.
6. **Compact recording utility.** The task list remains dominant while a small audio cue and Cancel / Stop / Review controls stay available.
7. **No secondary product experience.** The prototype contains only capture, edit/review, add-text, and saved-session states.
8. **Mobile-first verification.** Every state is rendered and checked at 375×812 and 430×932.

## Removed from the prototype

- Current Reality and tree views
- problem/task type labels
- coaching, analysis, recommendations, insights, and suggested next actions
- hierarchy, subtasks, decomposition, and complex-task handling
- routing choices, promotion, per-task destinations, and destination settings
- processing pipelines, reconciliation stages, confirmation batches, and partial-action results
- Weekly Review and whole-product navigation
- desktop multi-pane planning workspace

## Deliberately not specified

- Production React components, APIs, persistence, or RTM integration
- Voice transcription technology and recording lifecycle implementation
- Error recovery, offline guarantees, permissions, retention, analytics, or localization
- Final brand copy beyond the founder-approved control and draft-state language

## Approval gate

This remains a static proposal in draft PR #62. Do not implement or deploy product changes until the founder approves this narrow Brain Dump flow.
