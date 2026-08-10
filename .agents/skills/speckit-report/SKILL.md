---
name: "speckit-report"
description: "Render the end-to-end delivery report for the human: intake, spec, design, every reviewer verdict, implementation, verification, acceptance and landing evidence in one place."
argument-hint: "Optional feature slug; defaults to the current feature branch"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 11 (Codex twin)"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Delivery report (Codex)

Codex twin of `.claude/skills/speckit-report/SKILL.md`. The terminal stage: the
human handed over an abstract ask and has not watched the ten stages since.

```bash
python3 scripts/render_feature_report.py specs/NNN-<slug>
```

The script aggregates what exists on disk and never invents a value. It picks
the review campaign whose `planning-context.json` names **this** feature, not
the newest run globally.

## Fill in what the script cannot read

The script has no access to a subagent or session transcript. Complete these
sections by hand:

- **7-8. Built and verified** — commit SHAs, files touched, tasks completed vs
  planned, deviations from the plan, coverage against the 95% floors, and which
  suites were skipped and why.
- **10. How it landed** — trunk candidate SHA and CI run URL, or the PR link
  for an ASK-class change. On the mainline SHIP/SHOW path there is no PR
  object: write **"No PR object exists (SHIP/SHOW verified-trunk landing)"**. A
  blank field reads as an oversight; the sentence reads as the fact it is.
- **11. Still open** — deferred lanes, advisory findings not acted on, known
  gaps. This is the section the human will act on. Do not soften it and do not
  omit it when it is uncomfortable.

## Honesty rules

These are the point of the stage:

- A stage that did not run is reported **not run**, never omitted.
- A reviewer lens that could not run is named, with the reason.
- `founder-accepted` is never rendered as `approved`; print the full record.
- Coverage below a floor is stated as a failure even when the change landed.
- If the pipeline was entered mid-way — spec written by hand, no interview —
  say which stages were skipped.

Codex cannot publish a Claude Artifact. Write `specs/NNN-<slug>/report.md`,
hand the human its path, and say the artifact step was skipped rather than
implying a link exists.

## Completion report

```
REPORT WRITTEN
feature: specs/NNN-<slug>   report: specs/NNN-<slug>/report.md
artifact: not published (Codex session)

STAGES: <n>/11 completed   SKIPPED: <list>
VERDICT CHAIN: review <verdict> -> verification <green|red> -> acceptance <accept|reject>
STILL OPEN: <n> items
```
