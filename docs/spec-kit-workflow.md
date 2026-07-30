# BrainBuddy Spec Kit workflow

BrainBuddy uses the official GitHub Spec Kit as the mandatory authoring workflow
for every new or materially changed feature specification.

- Spec Kit version: `github/spec-kit` `v0.15.0`
- Installed integrations: Claude Code skills under `.claude/skills/` and Codex
  skills under `.agents/skills/`
- Scope: feature specification and planning artifacts under `specs/`
- Non-scope: execution orchestration, code review, CI, merge, release, or deploy

## Install and verify prerequisites

Use isolated uv tooling. Do not install Spec Kit with pip inside the Hermes
runtime or the application backend/frontend environments.

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v0.15.0
specify --version
specify check
specify integration list
```

Expected version output:

```text
specify 0.15.0
```

`specify check` should show both Claude Code and Codex CLI as available.
If the CLI needs to be refreshed without modifying the global uv tool install,
use the same pinned release through `uvx`:

```bash
uvx --from git+https://github.com/github/spec-kit.git@v0.15.0 specify --version
```

## Refreshing Spec Kit in this repository

This repository is refreshed from the official pinned release with the
manifest-aware upgrade path:

```bash
specify integration status --json
specify integration upgrade claude --force
specify integration upgrade codex --force
# If reviewed extensions are installed, update each pinned extension explicitly:
# specify extension update <extension-id>
```

Do not run an unscoped `specify extension update`: community extensions have
independent versions and require their own source review. No extensions are
installed in BrainBuddy. In particular, do not install the Git extension:
automatic feature branches, hooks, and commits conflict with Hermes Kanban
worktree ownership and delivery gates.

Before a forced integration refresh, preserve the BrainBuddy-specific disabled
`speckit-implement` stubs for both integrations and the four customized
templates. Restore them after the refresh, inspect `git diff`, and accept the
expected integration-status warnings for those six deliberate overrides. The
current refresh installs v0.15.0 shared assets under `.specify/`, Claude Code
skills under `.claude/skills/`, and Codex skills under `.agents/skills/`.

After any future refresh:

1. Inspect `git diff` before accepting changes.
2. Preserve `.specify/memory/constitution.md` and project-specific template gates.
3. Confirm `.specify/init-options.json` keeps `speckit_version` at the intended
   version and `ai_skills`/`integration` for Claude.
4. Confirm the local `speckit` workflow remains planning-only and does not call
   `speckit.implement`.
5. Run `python3 scripts/check_spec_kit_specs.py`.
6. Run any affected backend/frontend checks before opening a PR.

## Canonical feature-spec path

For every new or materially changed BrainBuddy feature:

1. Read `.specify/memory/constitution.md`, `AGENTS.md`, `CLAUDE.md`, and relevant
   ADRs under `docs/decisions/`.
2. Use `/speckit-constitution` only when governance principles or dependent
   templates need a real amendment.
3. Use `/speckit-specify` to create or update the feature's `spec.md` with the
   what and why. Do not include implementation design here except as constraints.
4. Use `/speckit-clarify` to resolve ambiguous requirements before planning.
5. Use `/speckit-plan` to describe architecture, module ownership, contracts,
   tests, data handling, observability, mobile/resilience, and release gates.
6. Run the bounded planning-review workflow after `plan.md`; the Architect resolves
   technical findings and uses a Kanban `needs_input` block only for product
   decisions.
7. Use `/speckit-checklist` after review. Under the pinned v0.15.0 workflow,
   checklist setup requires `plan.md`; do not run checklist as a pre-plan command.
8. Use `/speckit-tasks` to generate logical implementation tasks grouped by
   independently testable user story, then run `/speckit-analyze`.
9. Create and validate `hermes-handoff.json`; hand its 1–6 coarse lanes to the
   Kanban Orchestrator instead of executing implementation in Spec Kit.
10. Amend spec/plan/tasks and rerun affected review/validation whenever
    implementation intent changes.

For Claude Code and Hermes Agent in this repository, Spec Kit is installed as
skills, so the invocation names use hyphens:

```text
/speckit-constitution
/speckit-specify
/speckit-clarify
/speckit-plan
/speckit-checklist
/speckit-tasks
/speckit-analyze
```

Codex exposes the same planning skills with `$` skill invocations:

```text
$speckit-constitution
$speckit-specify
$speckit-clarify
$speckit-plan
$speckit-checklist
$speckit-tasks
$speckit-analyze
```

The Claude and Codex integrations keep `speckit-implement` only as a disabled
compatibility stub. The Hermes architect profile receives only the planning
skills listed above through `/speckit-analyze`; it does not receive
`speckit-implement` or `speckit-taskstoissues`. Neither command may run
implementation tasks, publish one issue/card per task line, execute hooks,
commit, or edit product source. Implementation starts only when Hermes Kanban
dispatches the owning specialist profile into an isolated worktree with TDD,
review, CI, PR, and release gates.

## Architect-owned Kanban path

When a BrainBuddy architecture or feature spec is new or materially changed, the
architect profile owns the full planning lane before implementation begins:

1. Create or claim one architect-owned Kanban card. In that card's isolated
   worktree, use the official Hermes Spec Kit skills for constitution,
   `/speckit-specify`, `/speckit-clarify`, and `/speckit-plan`. The current
   Architect session is the authoritative writer; Workflow Engine must not spawn
   a nested Architect or a competing implementation agent.
2. After `spec.md` and `plan.md` exist, run the repository workflow:

   ```bash
   SPECIFY_FEATURE_DIRECTORY=specs/NNN-feature \
     specify workflow run .specify/workflows/speckit/workflow.yml \
     -i risk=standard --json
   ```

   Use `risk=high` for auth/privacy, destructive data/schema, public-contract,
   security, migration, concurrency, or irreversible changes. Standard mode runs
   three isolated Codex review sessions (`requirements-consistency`,
   `architecture-consistency`, and `testability-evidence`) with an enforced
   read-only sandbox. High-risk mode additionally requires a Fable adversarial
   review in plan mode with only `Read,Grep,Glob`; unavailable quota or malformed
   output fails closed.
3. Read
   `.specify/workflows/runs/<run-id>/planning-review-summary.json`. Reviewers
   cannot edit product or planning files. The Architect resolves technical
   findings itself and may rerun the bounded campaign once. Framework, database,
   API shape, module boundaries, test strategy, and migration mechanics are
   technical decisions and never user escalations.
4. If the summary says `product-decision-required`, block only the owning
   Architect Kanban card with `needs_input`. Ask only about scope, UX, priority,
   privacy, permissions, pricing, safety/compliance, or observable acceptance
   behavior. Record the answer in the spec and final handoff, then rerun reviews.
   Workflow run state stays local and is ignored by Git; Kanban remains the
   durable user-conversation and execution state.
5. When review status is `approved`, run `/speckit-checklist`, `/speckit-tasks`,
   and `/speckit-analyze`, then create
   `specs/NNN-feature/hermes-handoff.json` conforming to
   `.specify/workflows/speckit/handoff.schema.json`. Validate it with:

   ```bash
   SPECIFY_FEATURE_DIRECTORY=specs/NNN-feature \
     python3 scripts/spec_kit_planning_review.py validate-handoff
   ```

6. The handoff contains one root outcome and 1–6 coarse, acyclic, independently
   mergeable lanes with task references, dependency order, exclusive writer
   scopes, and acceptance evidence. The Orchestrator compiles these lanes into
   Hermes cards in waves with at most four writable lanes active. Never publish
   one card per `tasks.md` line.
7. Commit only versioned planning artifacts and the validated handoff. Hermes
   Kanban remains authoritative for claims, worktrees, retries, implementation,
   review, CI, landing, deploy, and release evidence.

The Workflow Engine is therefore a persistent **planning-review scheduler**, not
a second Kanban. It owns bounded fan-out/fan-in and local run state; the Architect
owns semantic decisions and artifact edits; Hermes owns writable execution.

## Artifact minimum for new specs

New non-grandfathered directories under `specs/` must use
`NNN-kebab-case-feature` naming and include at least:

```text
spec.md
checklists/requirements.md
plan.md
tasks.md
hermes-handoff.json
```

Additional Spec Kit artifacts such as `research.md`, `data-model.md`,
`quickstart.md`, and `contracts/` should be present when the feature needs them.
Run the deterministic check before opening a PR:

```bash
python3 scripts/check_spec_kit_specs.py
# or
make check-specs
```

The check does not merely assert that `hermes-handoff.json` exists: it validates
its contents with the same `validate_handoff` contract used by
`scripts/spec_kit_planning_review.py validate-handoff`, so an unparseable,
schema-violating, unapproved, under-reviewed, or cyclic-lane handoff fails the
mandatory CI spec gate.

## Founder acceptance

A high-risk planning-review campaign is a bounded quality tool, not an oracle:
fresh reviewer sessions re-litigate artifacts from scratch, and on a large,
actively-amended package the blocking-finding count may diverge across
campaigns even as every verified defect is fixed. When the repo owner judges
that the loop has stopped converging, the review may be closed by explicit
founder acceptance: `planning_review.status: founder-accepted`, carrying a
`founder_acceptance` record with `accepted_by`, `accepted_on`, a substantive
`rationale`, and the complete `campaign_history` (every run id and its true
status). The validators accept this status only with that full record — it
documents more than an approval does, never less. Findings that motivated
fixes must be fixed or tracked in open handoff lanes before acceptance;
fabricating an `approved` status remains prohibited. First recorded use:
spec 005 (2026-07-29), five campaigns, nine product decisions, every verified
defect fixed, closed by the founder for a single-user deployment.

## Historical grandfathering

Existing history is preserved rather than regenerated blindly.

- `specs/001-relation-linking-refactor/` and
  `specs/003-smart-add-classification/` contain complete pre-ADR-0009 Spec Kit
  packages. Their normative planning files are hash-pinned and remain valid
  without a fabricated `hermes-handoff.json`; any material change invalidates
  that grandfathering and requires the current workflow.
- `specs/002-async-voice-workflows/` began before the initial v0.12.17
  adoption and was materially completed before ADR-0009 with acceptance,
  checklist, plan, tasks, and readiness evidence. Its current normative package
  is hash-pinned; a later material change requires the current handoff workflow.
- `specs/004-verified-trunk-delivery/` is likewise a complete pre-ADR-0009
  package with a hash-pinned planning baseline.
- `requirements/` remains historical context. Where it conflicts with the
  current constitution, ADRs, auth docs, live schemas, or `specs/`, the latter
  sources win.

## Boundary with Hermes Kanban

Spec Kit generates and maintains planning artifacts. Hermes Kanban remains the
execution/orchestration and PR-review system.

Generated `tasks.md` is planning input only. It is not permission to bypass:

- assigned Kanban cards and specialist ownership;
- isolated worktrees and branch discipline;
- tests-before-implementation expectations;
- independent review and `review-required` handoffs;
- CI, merge, and Fly release gates.

Spec changes should be committed and reviewed like product code changes.
