# Thinking-assistant pivot design brief

Status: founder-review proposal; not a production specification

Primary surface: **Operate**. Task/GTD work is the default workspace. Brain Dump is a focused capture utility, and Thinking/CRT is opened only from one selected task.

## Product posture

BrainBuddy opens on actionable work, not a canvas. The desktop shell uses the handoff’s GTD navigation and compact task rows; the phone shell keeps the same information hierarchy in one column with bottom navigation. The current React/Tailwind palette, spacing, borders, and focus treatment anchor the visual language.

This prototype does not redefine the production information model. “Inbox,” “Next actions,” “Waiting for,” “Someday / maybe,” and “Projects” are review labels from the supplied handoff. The existing single configured task-tracker adapter remains the canonical destination boundary from ADR-0001.

## Founder-review path

1. Start in **Next actions**, the primary task workspace.
2. Open **Brain Dump** from the workspace header.
3. Capture into a growing chronological list of provisional task wording.
4. Stop into a separate review state; edit or remove proposals.
5. Explicitly confirm the frozen set before anything can become canonical Inbox work.
6. Return to the task workspace after a confirmation-safe completion state.

Secondary review paths:

- Select “Fix onboarding drop-off” to see that **Open Thinking / CRT** belongs to that task’s detail, never to the default workspace.
- Open **Weekly review** to see only a lightweight entry point. Its copy states that voice input creates proposals under the same persisted async-operation and explicit-confirmation contract as Brain Dump.

## Screen rules

### Task workspace

- Tasks dominate the main region; no default tree/canvas.
- Desktop uses a restrained GTD sidebar. Phone uses one-column task rows plus bottom navigation.
- Brain Dump remains directly available without becoming the whole product.
- Thinking/CRT is discoverable only after selecting a specific task.

### Brain Dump capture

- The task list is the only substantive content.
- Four chronological cards use stable `#N`, `Wording still changing`, and `Provisional` language.
- Recording controls are compact and persistent: Cancel and Stop & review.
- No transcript, timer, pipeline, analysis, coaching, recommendations, destination control, or tree UI appears.
- Nothing is saved while recording.

### Review and confirmation

- Review is separate from capture and permits direct wording edits or removal.
- The action names the fixed effect: **Confirm 4 to Inbox**.
- Confirmation is the authority boundary; model output remains proposal-only.
- The completion state reports only what was confirmed and offers a return to the workspace.

### Weekly Review overview

- The screen is intentionally a placeholder, not a designed review workflow.
- It states that Brain Dump and voice-led Weekly Review share one resumable async-operation substrate.
- It states that voice and model stages create proposals only, with canonical changes after explicit confirmation.
- It does not invent item-by-item interactions, progress metrics, scripts, or coaching.

## Responsive and accessibility rules

- Verified viewports: desktop 1440×900, phone 375×812, and phone 430×932.
- Every interactive target is at least 44px high/wide.
- Keyboard focus is visible; landmarks, labels, headings, list semantics, and button names are explicit.
- State changes are announced through an `aria-live` region.
- Safe-area padding protects phone headers, bottom navigation, and capture/review controls.
- Long task text wraps; no viewport has horizontal page overflow.
- Motion is limited to a recording-status cue and is disabled under `prefers-reduced-motion`.

## Prototype routes

`prototype.html` is self-contained. Stable query states are:

- `?screen=workspace`
- `?screen=task`
- `?screen=thinking`
- `?screen=capture`
- `?screen=review`
- `?screen=confirmed`
- `?screen=weekly`

The state switcher is a review/testing utility, not a proposed product control.
