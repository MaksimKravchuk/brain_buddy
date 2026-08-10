---
name: "speckit-design"
description: "Produce the UX/UI design stage for a feature: static HTML screens plus the numbered screen and state inventory the plan and acceptance auditor both cite."
argument-hint: "Optional design direction or constraints"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 3 (Codex twin)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Design stage (Codex)

Codex twin of `.claude/skills/speckit-design/SKILL.md`. `.specify/extensions.yml`
registers this as a **mandatory** `after_clarify` hook, and that file is shared
by both agent trees — so this skill must exist here or a Codex run stops dead
after clarification.

Codex has no subagent runtime. Where the Claude twin delegates generation to
the `design-architect` subagent, apply that agent's contract
(`.claude/agents/design-architect.md`) directly in this session. That file is
the single source of truth for the design procedure; do not restate it here and
do not improvise around it.

## Preconditions

`spec.md` exists and its `## Clarifications` section is settled.

If the feature has **no** user-visible surface, write a two-line `design.md`
recording that and why, and stop. Do not invent screens to satisfy the
pipeline.

## Authority order

1. Accepted ADRs under `docs/decisions/`. **ADR-0006 makes `Tag` canonical.**
   `Context` and `@context` are forbidden strings and
   `scripts/validate_brain_buddy_design_skill.py` hard-fails on them in CI.
2. `.claude/skills/brain-buddy-design/` — the design authority for colors,
   type, fonts, assets and UI kit. Read it directly; it is plain markdown and
   is not Claude-specific.
3. `.specify/memory/constitution.md` Principle V.
4. `docs/vnext-cloud-design-build-contract.md` **last** — it still carries the
   pre-ADR-0006 `Context`/`@context` vocabulary in §6.2–6.3.

## Output

- `specs/NNN-<slug>/design/*.html` — self-contained static screens, inline CSS,
  no CDN, no external fonts.
- `specs/NNN-<slug>/design.md` from `.specify/templates/design-template.md`,
  with stable `D-NN`/`M-NN` ids that are never renumbered.

Every screen needs every applicable state: default, loading, empty (first-run
and filtered-to-nothing are different), error, partial failure, and
offline/interrupted on the mobile capture path.

## Verify before handoff

```bash
python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py
grep -rn "@context\|\bContext\b" specs/NNN-<slug>/design.md specs/NNN-<slug>/design/
```

Any hit on the forbidden vocabulary is a hard stop.

## Human sign-off — required

Show the human the screens and get explicit approval before planning starts.
This gate is cheap; discovering the wrong UI at acceptance is not.

## Completion report

```
DESIGN COMPLETE
feature:   specs/NNN-<slug>
screens:   <n>   states: <n>
ids:       D-01..D-0n, M-01..M-0n
validator: pass       vocabulary check (ADR-0006): pass
human sign-off: yes | pending

UNMAPPED
- requirements with no affordance: <ids or none>
- affordances with no requirement: <list or none>

NEXT: $speckit-plan  (the plan MUST cite design.md)
```
