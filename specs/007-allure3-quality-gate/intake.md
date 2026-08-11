# Business Intake: Allure 3 aggregate Quality Gate and single-file report

**Feature**: `specs/007-allure3-quality-gate/` · **Date**: 2026-08-11
**Interviewee**: BrainBuddy founder, via written brief (Hermes → Claude Code)

No live elicitation: this run is non-interactive, so `AskUserQuestion` is
unavailable. Everything below is transcribed from the brief.

## The ask, as given

> Allure Report 3 has recently added many features, including some form of
> simple preview/hosting and Quality Gates. Introduce the useful new Allure 3
> capabilities into BrainBuddy, and use this as a canary of the new orchestrated
> development flow.

Bounding instructions, transcribed: preserve the existing per-lane uploads,
taxonomy validators and multi-file HTML artifact; add a repository-owned Allure
3 configuration and a real aggregate Quality Gate that fails the required CI
verdict, while still producing the diagnostic reports when the gate fails; add
an Awesome single-file report as an *additional* artifact, not a replacement;
evaluate storage/hosting and retries as separate slices; "do not blindly add
every Allure feature."

A first implementation was rejected as disproportionate (7,199 added lines for a
one-rule gate). This package is the re-scoped, smallest production-safe slice.

## 1. Problem

`allure-report` publishes the aggregate report and never judges it. A failed or
broken test can reach the artifact while `Full CI` stays green — the report is
evidence nobody is required to read. Separately, the only report artifact is a
multi-file directory that needs a local server, so in practice it is downloaded
rarely and read less.

## 2. Who is affected

The founder reading a CI run, and the delivery agents that cite its evidence.
There is **no product user-visible surface** and no effect on the product loop.

## 3. Success, in the founder's terms

A red test in any lane turns the run red at the gate; the report explaining it is
still downloadable; and the easy-open version is one file.

## 4. Out of scope (explicit)

Storage/hosting, rerun policy, environment labels, lane-completeness/freshness/
duplicate detection, artifact size ceilings, any generic gate framework, and all
product code. Recorded here so a later reader knows these were declined, not
missed. See [spec.md](spec.md).
