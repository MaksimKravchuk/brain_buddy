---
name: "speckit-design"
description: "Produce the UX/UI design stage for a feature: static HTML screens plus the numbered screen and state inventory the plan and acceptance auditor both cite."
argument-hint: "Optional design direction or constraints"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 3"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Design stage

The front door to the design leg. Runs after `/speckit-clarify` and before
`/speckit-plan`, wired by `hooks.after_clarify` in `.specify/extensions.yml`.

Design is load-bearing here, not decoration: the plan must cite `design.md`,
and `acceptance-auditor` keys its traceability matrix off the `D-`/`M-` screen
ids this stage assigns.

## Preconditions

`spec.md` exists and its `## Clarifications` section is settled. Designing
against an ambiguous spec produces screens that have to be thrown away.

If the feature has **no** user-visible surface, write a two-line `design.md`
recording that and why, and stop. Do not invent screens to satisfy the
pipeline.

## Authority order

1. Accepted ADRs under `docs/decisions/`. **ADR-0006 makes `Tag` canonical.**
   `Context` and `@context` are forbidden strings and
   `scripts/validate_brain_buddy_design_skill.py` hard-fails on them in CI.
2. The `brain-buddy-design` skill — the design authority for colors, type,
   fonts, assets and UI kit.
3. `.specify/memory/constitution.md` Principle V for the mobile-first loop.
4. `docs/vnext-cloud-design-build-contract.md` **last**. It still carries the
   pre-ADR-0006 `Context`/`@context` vocabulary in §6.2–6.3. Reading it
   without the ADR will break the build.

## Procedure

1. Delegate the generation to the `design-architect` subagent. It has the
   `brain-buddy-design` skill attached and an isolated context, which keeps
   the markup out of this session.
2. Require it to produce:
   - `specs/NNN-<slug>/design/*.html` — self-contained static screens, inline
     CSS, no CDN, no external fonts.
   - `specs/NNN-<slug>/design.md` from
     `.specify/templates/design-template.md`.
3. Verify the handoff yourself; do not take the subagent's word for it:
   ```bash
   python3 -m unittest scripts/test_validate_brain_buddy_design_skill.py
   grep -rn "@context\|\bContext\b" specs/NNN-<slug>/design.md specs/NNN-<slug>/design/
   ```
   Any hit on the forbidden vocabulary is a hard stop — fix the design.
4. Check every screen has all its states: default, loading, empty (first-run
   and filtered-to-nothing are different), error, partial failure, and
   offline/interrupted on the mobile capture path. A missing state here
   becomes an `important` finding from `ux-a11y-reviewer` two stages later.
5. Check the affordance → `FR-###` map is complete in both directions.

## Human sign-off — required

Show the human the screens and get explicit approval before planning starts.
This gate is cheap and the alternative is discovering the wrong UI at
acceptance, after it has been built and tested.

Surface: the screen inventory, the states, and the two or three decisions the
`design-architect` flagged as needing a person. Use `AskUserQuestion` for the
decisions.

## Optional: mirror to Miro

Only when the human asks. Push the static screens to the existing board via
`prototype_get_upload_url` → PUT → `prototype_create`.

- Never call `board_create`.
- Never push the React workspace kit: `prototype_create` strips every
  `<script>` and it would render blank.
- Miro is a review surface, never the source of truth. `design.md` and the
  HTML in `specs/` are authoritative.

## Completion report

```
DESIGN COMPLETE
feature:   specs/NNN-<slug>
screens:   <n>   states: <n>
ids:       D-01..D-0n, M-01..M-0n
validator: pass
vocabulary check (ADR-0006): pass
human sign-off: yes | pending

UNMAPPED
- requirements with no affordance: <ids or none>
- affordances with no requirement: <list or none>

NEXT: /speckit-plan  (the plan MUST cite design.md)
```
