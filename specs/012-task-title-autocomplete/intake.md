# Intake: Web task-title autocomplete

**Date**: 2026-08-25
**Decision**: GO — bounded default-OFF experiment
**Source**: Kanban task `t_6fca39aa`

## Outcome

Help an authenticated web user finish a new Task title faster without replacing the existing title input or creating any record before the ordinary Task submit.

## Frozen slice

- The existing new-Task title input remains the only composer.
- When eligible, one compact menu below it contains exactly three full-title completion candidates. There is no inline ghost text.
- ArrowUp/ArrowDown selects, Enter accepts into the input, and Escape dismisses. Acceptance never submits or creates a Task; the ordinary submit action remains separate.
- Eligibility begins at three non-blank words without a Project and one non-blank word when the composer is scoped to a selected Project.
- Context sent to the configured provider is limited to the current draft, the selected Project, and prior Task titles owned by the current user.
- Remote processing requires current explicit consent and a configured provider. Task text never enters logs, metrics, fixtures, or evidence.
- `task_title_autocomplete` is server-owned, allow-listed, runtime-managed, default OFF, and controls exposure only.
- Web new-task capture only. Mobile, voice, title editing, a durable suggestion/memory store, and writes before ordinary submit are excluded.
- Smart Add and autocomplete must never show stacked menus or compete for the same keystroke.

## Product boundaries

This feature assists the existing capture step. It does not change Task lifecycle, Task submit semantics, Smart Add classification, Voice Brain Dump confirmation, Project ownership, or the CRT. A candidate is untrusted draft text until the user accepts it; accepted text is still only a draft until ordinary Task submission succeeds.

## Success and stop decision

Continue beyond the internal cohort only when the pilot meets all criteria in `spec.md` without a privacy incident, title-write regression, or unacceptable latency. Any stop trigger turns the runtime flag OFF; rollback must leave every Task and draft created through normal submission untouched.
