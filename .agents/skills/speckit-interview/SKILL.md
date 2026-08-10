---
name: "speckit-interview"
description: "Elicit business requirements from the human for an abstract feature ask, then write intake.md and hand the agreed description to $speckit-specify."
argument-hint: "The abstract ask, e.g. 'add account management'"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 1 (Codex twin)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Business requirements interview (Codex)

Codex twin of `.claude/skills/speckit-interview/SKILL.md`. Front door of the
delivery pipeline: an abstract ask in, agreed business requirements out, before
a line of specification is written.

Ask the human directly in conversation, one topic at a time. Claude Code uses
its `AskUserQuestion` tool for this; Codex simply asks.

## Recursion guard

`.specify/extensions.yml` registers this under `hooks.before_specify` as
**optional** on purpose: this skill calls `$speckit-specify` at the end, and a
mandatory hook would make specify call interview call specify without end.
Never change that hook to `optional: false`.

## Before you start

Read `.specify/memory/constitution.md`, `AGENTS.md`, `CLAUDE.md` and the
accepted records under `docs/decisions/` — ADR-0006 fixes the GTD vocabulary
(the term is **Tag**). Skim `specs/` for an overlapping feature; if the ask
duplicates shipped work, say so before interviewing.

## How to interview

One decision per question. **No five-question cap** — this is not
`$speckit-clarify`, which disambiguates an existing spec; you are building
requirements from nothing, and stopping early is the most expensive mistake
available at this stage.

- Always offer a recommended option first, with the trade-off stated. A human
  reacting to a concrete proposal answers far better than one facing an open
  field.
- Never ask what you can read. `docs/auth.md` and `docs/data-retention.md`
  already answer a lot.
- Never ask a technical question. Database, framework, module boundary, API
  shape, migration mechanics and testing strategy are Architect decisions.
- Write answers back incrementally. An interview that dies at question nine
  must not lose one through eight.
- When an answer contradicts an earlier one, say so and ask which wins.

## The taxonomy — cover every heading

Never drop a heading; when one does not apply, record why.

1. **Problem** — whose, how it shows up, what it costs, what happens if we
   build nothing.
2. **Customer and persona** — including deployment shape (single-user changes
   the compliance answers).
3. **Business objective and KPI** — metric, baseline, target, date. These
   become the `SC-###` criteria; no number means an ungradeable spec.
4. **Scope boundary** — in, and explicitly **out**. Non-goals are the
   highest-value answers here and the ones humans skip unless pushed.
5. **Constraints** — deadline, platform, offline, contracts that must not
   break.
6. **Compliance obligation** — `AccountService` already ships self-serve GDPR
   account management (profile/email/password, ZIP export, 14-day-grace
   deletion and purge) and is never feature-flagged. Ask what this feature
   *adds*.
7. **Existing-system dependencies** — surfaces touched, mobile impact, effect
   on the primary loop.
8. **Definition of done** — observable, not "it works".

## Confirm before proceeding

Play it back as a numbered summary and get explicit confirmation of the
**scope boundary** and the **non-goals**. Do not proceed on silence.

## Write intake.md

`$speckit-specify` creates the feature directory, so stage first, then adopt:

1. Write to `.specify/intake/<slug>.md` from
   `.specify/templates/intake-template.md`.
2. Invoke `$speckit-specify` with a description synthesized from the intake —
   what and why, never how.
3. `bash .specify/scripts/bash/check-prerequisites.sh --json --paths-only`
4. Move the staged file to `<FEATURE_DIR>/intake.md` and delete the staging
   copy. `scripts/check_spec_kit_specs.py` requires `intake.md` inside the
   feature directory.

## Completion report

```
INTERVIEW COMPLETE
topics covered: <n>/8   questions asked: <n>
feature: specs/NNN-<slug>   intake.md: <path>

SCOPE IN / SCOPE OUT (confirmed explicitly) / KPI

DEFERRED TO CLARIFY
- <what the human could not answer yet>

NEXT: $speckit-clarify
```
