# BrainBuddy Spec Kit workflow

BrainBuddy uses the official GitHub Spec Kit as the mandatory authoring workflow
for every new or materially changed feature specification.

- Spec Kit version: `github/spec-kit` `v0.15.0`
- Installed integrations: Claude Code skills under `.claude/skills/` and Codex
  skills under `.agents/skills/`
- Scope: feature specification and planning artifacts under `specs/`
- Non-scope: execution orchestration, code review, CI, merge, release, or deploy

Spec Kit artifacts are portable and do not require Hermes. Outcomes explicitly
enrolled in the optional Hermes managed-delivery mode additionally follow
ADR-0010 and `docs/spec-driven-kanban.md`; that overlay does not apply to ordinary
developer or standalone-agent work.

## Install and verify prerequisites

Use isolated uv tooling. Do not install Spec Kit with pip inside the application
backend/frontend environments.

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
automatic feature branches, hooks, and commits conflict with repository
worktree ownership and delivery gates.

Before a forced integration refresh, preserve the four customized templates.
Restore them after the refresh, inspect `git diff`, and accept only understood
project-specific overrides. The current refresh installs v0.15.0 shared assets
under `.specify/`, Claude Code skills under `.claude/skills/`, and Codex skills
under `.agents/skills/`.

After any future refresh:

1. Inspect `git diff` before accepting changes.
2. Preserve `.specify/memory/constitution.md` and project-specific template gates.
3. Confirm `.specify/init-options.json` keeps `speckit_version` at the intended
   version and `ai_skills`/`integration` for Claude.
4. Confirm project-specific templates remain portable and planning-focused.
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
6. Use `/speckit-checklist` after planning. Under the pinned v0.15.0 workflow,
   checklist setup requires `plan.md`; do not run checklist as a pre-plan command.
7. Use `/speckit-tasks` to generate logical implementation tasks grouped by
   independently testable user story, then run `/speckit-analyze`.
8. Implement directly from the validated artifacts or, when explicitly enrolled,
   apply the optional managed-outcome overlay from `docs/spec-driven-kanban.md`.
9. Amend spec/plan/tasks and rerun affected validation whenever
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

The generated artifacts do not prescribe a specific agent runtime. Standalone
Claude Code, Codex, other agents, or a developer may implement them while
preserving repository quality and release gates.

## Optional managed-outcome overlay

When an outcome is explicitly activated under ADR-0010, follow
`docs/spec-driven-kanban.md`. That runbook adds the requirements panel,
ratification, managed task metadata, signed lanes, canonical evidence, and
Hermes reconciliation for that outcome only. Do not infer managed mode from the
presence of plugin files or a Hermes installation.

## Artifact minimum for new specs

New non-grandfathered directories under `specs/` must use
`NNN-kebab-case-feature` naming and include at least:

```text
spec.md
checklists/requirements.md
plan.md
tasks.md
```

Additional Spec Kit artifacts such as `research.md`, `data-model.md`,
`quickstart.md`, and `contracts/` should be present when the feature needs them.
Run the deterministic check before opening a PR:

```bash
python3 scripts/check_spec_kit_specs.py
# or
make check-specs
```

The repository check validates the durable, portable Spec Kit minimum. If a
legacy `hermes-handoff.json` is present it still validates that historical
contract. Managed outcomes have additional runtime validation defined by their
separate runbook.

## Legacy founder acceptance

This section applies only to historical `hermes-handoff.json` packages. It does
not alter the separate gates of an explicitly managed outcome.

A historical high-risk planning-review campaign was a bounded quality tool, not an oracle:
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

## Boundary with execution tooling

Spec Kit generates and maintains portable planning artifacts. Developers and
standalone agents may execute them directly. For an explicitly managed outcome,
Hermes Kanban and `spec-driven-kanban` provide the optional durable task,
dependency, retry, and evidence runtime described in ADR-0010.

Generated `tasks.md` is planning input only. It is not permission to bypass:

- assigned ownership and agreed scope;
- isolated worktrees and branch discipline;
- tests-before-implementation expectations;
- independent review and `review-required` handoffs;
- CI, merge, and Fly release gates.

Spec changes should be committed and reviewed like product code changes.
