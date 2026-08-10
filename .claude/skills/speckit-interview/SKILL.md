---
name: "speckit-interview"
description: "Elicit business requirements from the human for an abstract feature ask, then write intake.md and hand the agreed description to /speckit-specify."
argument-hint: "The abstract ask, e.g. 'add account management'"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 1"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Business requirements interview

This is the front door of the delivery pipeline. It takes an abstract ask —
"add account management" — and turns it into agreed business requirements
before a single line of specification is written.

## Why this is a skill and not a subagent

`AskUserQuestion` is stripped from every subagent. Human elicitation is
structurally impossible in a delegated context, so this stage **must** run in
the main session. Do not try to delegate it.

## Recursion guard

`.specify/extensions.yml` registers this skill under `hooks.before_specify` as
**optional**. That is deliberate: this skill calls `/speckit-specify` at the
end. If the hook were mandatory, specify would call interview which would call
specify, without end. Never change that hook to `optional: false`.

## Stage 0 gate — check the assessment first

The `assess` extension (`spec-kit-core`, installed) runs *upstream* of this
skill: intake → research → define → shape → decide, writing
`.specify/assessments/<slug>/decision.md` with a **go / needs-clarification /
kill** verdict. It answers a question this skill does not: *should this be
built at all?*

Before asking the human anything:

1. Look for `.specify/assessments/<slug>/decision.md` matching the ask.
2. If it exists, read the `**Verdict**` line and obey it:
   - **kill** — **stop.** Do not interview, do not create a feature directory.
     Tell the human the idea was assessed and killed, quote the decisive
     reason from `decision.md`, and ask whether they are deliberately
     reopening it. Only an explicit human override restarts the pipeline; a
     killed idea silently re-entering delivery defeats the entire stage.
   - **needs-clarification** — say so and point at the stage that needs
     rework (`/speckit-assess-research` or `/speckit-assess-shape`). Do not
     launder it into a go by interviewing past it.
   - **go** — proceed, and use the handoff summary in `decision.md` as your
     starting context. Do not re-ask what the assessment already settled.
3. If no assessment exists, judge the size of the ask. For anything
   substantial or speculative, offer `/speckit-assess-intake` first — killing
   an idea here costs one conversation, killing it at acceptance costs the
   whole pipeline. For a small, obviously-wanted change, proceed and note in
   `intake.md` that assessment was skipped and why.

The assess skills are Claude-only; there are no `.agents/skills/` twins. That
is why `assess` is not registered as a hook in `.specify/extensions.yml` — a
hooked command with no Codex twin breaks Codex runs. This gate is enforced
here in prose instead.

## Before you start

Read, in this order:

1. `.specify/memory/constitution.md` — the five principles constrain what can
   be asked for, and Principle V requires every feature to state its impact on
   the primary loop.
2. `CLAUDE.md` and `AGENTS.md` for the existing architecture.
3. `docs/decisions/` — accepted ADRs bound the solution space. ADR-0006 fixes
   the GTD vocabulary: the term is **Tag**, never Context or @context.
4. Skim `specs/` for an existing feature that overlaps. If the ask duplicates
   shipped work, say so before interviewing.

## How to interview

Use `AskUserQuestion`. One topic at a time. **There is no five-question cap** —
this is not `/speckit-clarify`, which disambiguates an existing spec. You are
building the requirements from nothing, and stopping early is the single most
expensive mistake available at this stage.

Rules that make the interview worth the human's time:

- Ask about **one** decision per question. A compound question gets a compound
  answer that resolves neither half.
- Always offer a recommended option first, labelled `(Recommended)`, with the
  trade-off stated. A human who can react to a concrete proposal answers far
  better than one facing an open field.
- Never ask what you can read. Check the codebase, the ADRs and the existing
  specs first. Asking "do you have authentication?" when `docs/auth.md` exists
  wastes the one resource this stage spends.
- Never ask a technical question. Database choice, framework, module boundary,
  API shape, migration mechanics and testing strategy are Architect decisions.
  Escalating them here trains the human to stop reading your questions.
- Write answers back incrementally, after each topic. An interview that
  crashes at question nine must not lose questions one through eight.
- When an answer contradicts an earlier one, say so plainly and ask which
  wins. Do not silently keep the later answer.

## The taxonomy — cover every heading

Do not skip a heading. When a heading genuinely does not apply, record *why*
in `intake.md` rather than dropping it.

1. **Problem.** Whose problem, how it shows up today, what it costs. What
   happens if we build nothing.
2. **Customer and persona.** Who specifically. For a single-user deployment,
   say so — it changes the compliance and scale answers.
3. **Business objective and KPI.** What measurable thing improves, from what
   baseline, by when. This becomes the `SC-###` criteria; an objective with no
   number produces an unacceptable spec later.
4. **Scope boundary.** What is in. Then, explicitly, **what is out** —
   non-goals are the highest-value answers in this whole interview and the
   ones humans skip unless pushed.
5. **Constraints.** Deadline, budget, platform, offline behavior, existing
   contracts that must not break.
6. **Compliance obligation.** Consent, retention, deletion, export,
   residency. Note that `AccountService` already provides self-serve GDPR
   account management — profile/email/password, ZIP export, 14-day-grace
   deletion and purge — and is never feature-flagged. Ask what this feature
   adds to that, not whether it is needed.
7. **Existing-system dependencies.** Which surfaces this touches: backend
   services, canvas, tasks module, mobile, AI providers. Whether the mobile
   client must change.
8. **Definition of done.** What the human wants to see to believe it works.
   This is the seed of the acceptance criteria — press for something
   observable, not "it works".

## Confirm before proceeding

Play the whole thing back as a numbered summary and ask for explicit
confirmation of two things specifically: the **scope boundary** and the
**non-goals**. Do not proceed on silence.

## Write intake.md

`/speckit-specify` creates the feature directory, so it does not exist yet.
Stage the intake first, then adopt it:

1. Write the interview result to `.specify/intake/<slug>.md` using
   `.specify/templates/intake-template.md`.
2. Invoke `/speckit-specify` with a description synthesized from the intake —
   the what and why, never the how.
3. Resolve the created feature directory:
   `bash .specify/scripts/bash/check-prerequisites.sh --json --paths-only`
4. Move the staged file to `<FEATURE_DIR>/intake.md` and delete the staging
   copy. `scripts/check_spec_kit_specs.py` requires `intake.md` inside the
   feature directory; a file left in staging fails the spec gate.

## Completion report

```
INTERVIEW COMPLETE
topics covered: <n>/8      questions asked: <n>
feature:        specs/NNN-<slug>
intake.md:      <path>

SCOPE IN:      <bullets>
SCOPE OUT:     <bullets — confirmed explicitly by the human>
KPI:           <metric, baseline, target>

DEFERRED TO CLARIFY
- <anything the human could not answer yet>

NEXT: /speckit-clarify
```
