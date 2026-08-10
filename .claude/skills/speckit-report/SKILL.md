---
name: "speckit-report"
description: "Render the end-to-end delivery report for the human: intake, spec, design, every reviewer verdict, implementation, verification, acceptance and landing evidence in one place."
argument-hint: "Optional feature slug; defaults to the current feature branch"
compatibility: "Requires spec-kit project structure with .specify/ directory"
metadata:
  author: "brainbuddy"
  source: "brainbuddy pipeline stage 11"
user-invocable: true
disable-model-invocation: false
---

## User Input

```text
$ARGUMENTS
```

# Delivery report

The terminal stage. The human handed over an abstract ask and has not watched
the ten stages since; this report is how they find out what they got.

## Procedure

```bash
python3 scripts/render_feature_report.py specs/NNN-<slug>
```

The script aggregates what already exists on disk. It does not re-derive
anything, and it must not invent a value it cannot find — an absent artifact
is reported as absent.

## What the report must contain

1. **The ask, as given.** The human's original words, verbatim. They are the
   only thing in the report they can check against memory.
2. **What was agreed.** Scope in, scope out, KPI — from `intake.md`. Non-goals
   get equal billing with goals; they are what the human actually decided.
3. **What was specified.** Link `spec.md`; list `FR-###` and `SC-###` counts.
4. **What was designed.** Link `design.md`, the screen ids, and the HTML
   files. Note whether the human signed off, and when.
5. **What review found.** Every reviewer verdict from
   `planning-review-summary.json` — including the lenses that did **not** run
   and why. Number of campaigns. Every product decision the human answered,
   with the answer. If the gate closed by founder acceptance, print the full
   `founder_acceptance` record, not a summary of it.
6. **What was built.** Commit SHAs, files touched, tasks completed vs planned,
   and any deviation from the plan the implementer reported.
7. **What was verified.** Coverage numbers against the floors, which suites
   ran, which were skipped and why. Never present a skipped suite as passing.
8. **What was accepted.** The `acceptance.md` verdict, the criteria tally
   (covered / weak / missing), and the traceability matrix link.
9. **How it landed.** The trunk candidate SHA and CI run URL, or the PR link
   for an ASK-class change. When the mainline SHIP/SHOW path was used there is
   no PR object — write **"No PR object exists (SHIP/SHOW verified-trunk
   landing)"** rather than leaving the field blank. A blank field reads as an
   oversight; the explicit sentence reads as the fact it is.
10. **What is still open.** Deferred lanes, advisory findings not acted on,
    known gaps. This section is the one the human will act on; do not soften
    it and do not omit it when it is uncomfortable.

## Publish it

Write `specs/NNN-<slug>/report.md`, then publish it as an Artifact and hand
the human the link. A report that lives only in terminal scrollback has not
been delivered.

Keep the artifact's file path stable across reruns so updates redeploy to the
same URL instead of minting a new one.

## Honesty rules

These are the whole point of the stage:

- A stage that did not run is reported as **not run**, never omitted.
- A reviewer lens that could not run is named, with the reason.
- A lens that ran on a **fallback** oracle is named too. Read
  `degraded_lenses`, `panel_correlated` and `panel_oracles` from the summary
  and state them; a campaign that passed on a correlated panel is not reported
  as though it passed on the configured one (ADR-0014).
- `founder-accepted` is never rendered as `approved`.
- Coverage below a floor is stated as a failure even when the change landed.
- If the pipeline was entered mid-way — spec written by hand, no interview —
  say which stages were skipped.

## Completion report

```
REPORT PUBLISHED
feature:  specs/NNN-<slug>
report:   specs/NNN-<slug>/report.md
artifact: <url>

STAGES: <n>/11 completed    SKIPPED: <list>
VERDICT CHAIN: review <verdict> -> verification <green|red> -> acceptance <accept|reject>
STILL OPEN: <n> items
```
