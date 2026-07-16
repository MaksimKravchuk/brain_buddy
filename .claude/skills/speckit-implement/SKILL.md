---
name: "speckit-implement"
description: "DISABLED in BrainBuddy: implementation must be routed through Hermes Kanban instead of Spec Kit."
argument-hint: "Do not use; create or claim a Hermes Kanban implementation card."
compatibility: "Requires BrainBuddy Hermes Kanban delivery workflow"
metadata:
  author: "github-spec-kit + brainbuddy"
  source: "templates/commands/implement.md (disabled locally)"
user-invocable: false
disable-model-invocation: true
---

# BrainBuddy disables `/speckit-implement`

BrainBuddy uses GitHub Spec Kit for specification, clarification, technical
planning, requirements-quality checklists, and task breakdowns only. It must not
execute implementation work through this skill.

If this command is invoked, stop without editing product code or marking any
`tasks.md` item complete. Use this handoff path instead:

1. Confirm `spec.md`, `plan.md`, `checklists/requirements.md`, and `tasks.md`
   exist and reflect the intended implementation.
2. Create or update Hermes Kanban implementation cards from `tasks.md`.
3. Ensure those cards name the owning specialist profile, assigned worktree,
   review gate, and required local/CI checks.
4. Implementation agents consume the Spec Kit artifacts and implement only from
   their Kanban card, branch/worktree, TDD, PR, CI, and review gates.

This disabled command must not run hooks, create commits, modify source files,
run implementation tasks, or bypass Hermes Kanban/PR review.
