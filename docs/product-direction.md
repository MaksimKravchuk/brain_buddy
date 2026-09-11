# Product direction: executable next actions

- Date: 2026-09-11
- Decision owner: Max, BrainBuddy product owner
- Status: Owner-confirmed product direction; implementation and user outcomes are not asserted by this document.

## Purpose and authority

This document preserves the product focus agreed with Max in the 2026-09-11
product-value discussion. README summarizes it; future discovery and feature specs
should use it as their product rationale. It records the chosen direction, not a
market-validation result or an implementation-ready feature specification.

It elaborates the capture → organize → review loop in
[ADR-0001](decisions/0001-vnext-modular-monolith-and-workflow-contracts.md).
Existing domain, consent, confirmation, and delivery contracts remain authoritative.
Behavior changes still need the [Spec Kit workflow](spec-kit-workflow.md); this
document does not amend frozen specs or authorize automatic task mutations.

## Who and what problem

Build first for Max's own everyday use, then test whether the same benefit holds
for people with similar working habits. Broader demand is not yet established.

An inbox entry often names an intention or a project rather than something the
person can actually start. Project names may leave the desired outcome unclear.
Even a task that sounds concrete can hide a prerequisite, an unanswered question,
or a decision. The person meets that unresolved thinking again whenever they see
the task, and the work can remain stuck.

BrainBuddy's central job is to help transform these entries into executable next
actions while preserving the intended result and its relationship to those actions.
This applies to both voice brain dumps and other inbox entries.

Max's words, from this discussion:

> «чтобы задачи из брейндампа и вообще из инбокса попадали в твой лист задач
> таким образом, чтобы они были исполнимы. То есть трансформирование в
> исполнимость должно произойти.»

## What executable means

For this product direction, an executable next action is clear enough for this
person, in the relevant circumstances, to start without another planning session:

- The action and its object are understandable.
- Known prerequisites have been resolved; a dependency on another person is
  represented honestly as waiting rather than presented as ready to do.
- The person can recognize when the action itself is finished.
- Its size and detail fit the person and situation.

Clarification can involve defining a recognizable project outcome, uncovering a
prerequisite, choosing an approach, or identifying information to obtain. A clearer
title alone does not establish executability. Nor does generating a long checklist.

The AI should use known context and ask focused questions where material facts are
missing. It must distinguish suggestions from facts: the user's people, possessions,
constraints, and preferred approach cannot be invented to fill out a plausible plan.
Stop clarifying when the next action is usable; a complete project plan is not
always needed. Already executable entries should not require needless questioning.

## Owner's example: the garage

The starting entry is “Put the garage in order.” In Max's example, a refrigerator
is in the way; he wants to sell it and first ask his friend Vasya whether he wants it.
These are facts supplied in the example, not things the AI should infer from “garage.”

| Level | Clarified content |
|---|---|
| Intended outcome | Put the garage in order; clarify what finished looks like |
| Obstacle | The refrigerator is in the way |
| Chosen approach | Sell the refrigerator |
| Next action | Call Vasya and ask whether he wants the refrigerator |

The call is the actionable item, connected to the garage outcome. Asking the
question finishes that action; a reply, sale, or collection may require further
actions or an explicit waiting state. The exact UI and representation belong in
future specs.

## Weekly review keeps work executable

Weekly review is a central part of this same product loop. Once a week, AI helps
the person work through stalled items, understand what prevented progress, and
choose an appropriate next step. It is not evidence that every unfinished item
was badly written: priorities, availability, and circumstances also change.

Max's explanation of why detail should be revisited:

> «поэтому нам и надо ревью раз в неделю. чтобы ии помогал разгребать зависшее»

Illustrative responses to different reasons for being stuck:

| Reason found during review | Useful response to agree with the person |
|---|---|
| The action is unclear or too large | Clarify it or find a smaller starting action |
| Information or a decision is missing | Identify how to obtain it or make the decision |
| Progress depends on someone else | Record waiting and decide whether follow-up is needed |
| Time or priorities changed | Reconsider the commitment, timing, or deferral |
| The intended outcome no longer matters | Agree to remove or cancel the work |

These are examples, not a frozen taxonomy or an automatic decision policy.
Granularity is adjusted through this feedback: one person can start from “List the
refrigerator for sale”; another needs to establish the price or take photos first.
The product should avoid both under-specified tasks and unnecessary microtasks.
This direction does not prescribe a learning model or a persistent user-profile system.

## Roles of the other capabilities

- **Voice capture** lowers the effort of getting thoughts into the system.
- **Tasks, projects/lists, and tags** preserve actionable commitments and their context.
- **Weekly review** revisits stalled work and restores clarity about what happens next.
- **Thinking / CRT** can support deeper examination of a complex or recurring problem.
- **External agents** can carry out suitable, understood actions; delegation still
  needs a clear intended result and user review of the returned work.

Capture quality, task management, CRT, and agent connectivity support this focus.
Their presence alone is not evidence that intentions became executable or that
the user made progress.

## Evidence to seek and decisions still open

The primary value question is: after inbox clarification or weekly review, can the
person begin the next action without having to work out what to do all over again?
Then observe whether the work actually moves, or is consciously deferred or dropped,
and how much clarification and system-maintenance effort this required.

Real stalled entries from Max are the starting evidence. The number of tasks
created, subtasks generated, or dates moved is insufficient on its own. No numeric
success target, retention result, or broader willingness to pay has been established.

Future discovery and specs must resolve the interaction, how project context and
dependencies are represented, how review selects items, and what the user confirms.
They must also test whether the benefit repeats for people beyond the owner.
No implementation status, delivery date, or automatic weekly reminder is promised here.
