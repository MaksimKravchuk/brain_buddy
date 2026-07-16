# BrainBuddy Spec Kit workflow

BrainBuddy uses the official GitHub Spec Kit as the mandatory authoring workflow
for every new or materially changed feature specification.

- Spec Kit version: `github/spec-kit` `v0.12.17`
- Verified release date: 2026-07-16
- Installed integration: Claude Code skills under `.claude/skills/`
- Scope: feature specification and planning artifacts under `specs/`
- Non-scope: execution orchestration, code review, CI, merge, release, or deploy

## Install and verify prerequisites

Use isolated uv tooling. Do not install Spec Kit with pip inside the Hermes
runtime or the application backend/frontend environments.

```bash
uv tool install specify-cli --force --from git+https://github.com/github/spec-kit.git@v0.12.17
specify --version
specify check
specify integration list
```

Expected version output:

```text
specify 0.12.17
```

`specify check` should show Claude Code as available for the Claude workflow.
If the CLI needs to be refreshed without modifying the global uv tool install,
use the same pinned release through `uvx`:

```bash
uvx --from git+https://github.com/github/spec-kit.git@v0.12.17 specify --version
```

## Refreshing Spec Kit in this repository

This repository was safely refreshed from the official pinned release with:

```bash
uvx --from git+https://github.com/github/spec-kit.git@v0.12.17 specify init --here --integration claude --force
```

The command preserves the existing constitution file, installs the v0.12.17
shared scripts/templates/workflow metadata under `.specify/`, and installs
Claude Code skills under `.claude/skills/`.

After any future refresh:

1. Inspect `git diff` before accepting changes.
2. Preserve `.specify/memory/constitution.md` and project-specific template gates.
3. Confirm `.specify/init-options.json` keeps `speckit_version` at the intended
   version and `ai_skills`/`integration` for Claude.
4. Run `python3 scripts/check_spec_kit_specs.py`.
5. Run any affected backend/frontend checks before opening a PR.

## Canonical feature-spec path

For every new or materially changed BrainBuddy feature:

1. Read `.specify/memory/constitution.md`, `AGENTS.md`, `CLAUDE.md`, and relevant
   ADRs under `docs/decisions/`.
2. Use `/speckit-constitution` only when governance principles or dependent
   templates need a real amendment.
3. Use `/speckit-specify` to create or update the feature's `spec.md` with the
   what and why. Do not include implementation design here except as constraints.
4. Use `/speckit-clarify` and/or `/speckit-checklist` to de-risk ambiguous
   requirements before planning.
5. Use `/speckit-plan` to describe architecture, module ownership, contracts,
   tests, data handling, observability, mobile/resilience, and release gates.
6. Use `/speckit-tasks` to generate implementation tasks grouped by independently
   testable user story.
7. Amend the spec/plan/tasks first whenever implementation intent changes.

For Claude Code in this repository, Spec Kit is installed as skills, so the
invocation names use hyphens:

```text
/speckit-constitution
/speckit-specify
/speckit-clarify
/speckit-checklist
/speckit-plan
/speckit-tasks
/speckit-analyze
/speckit-implement
/speckit-converge
```

`/speckit-implement` is optional and does not replace BrainBuddy delivery rules.
If used, it must still operate inside the assigned branch/worktree and obey TDD,
review, CI, PR, and release gates.

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

## Historical grandfathering

Existing history is preserved rather than regenerated blindly.

- `specs/001-relation-linking-refactor/` already contains a complete historical
  Spec Kit-style artifact set and remains valid.
- `specs/002-async-voice-workflows/` predates this v0.12.17 adoption and is
  grandfathered with `spec.md` plus `acceptance-tests.md`. Its acceptance tests
  are normative for ADR-0002. Do not fabricate missing generated files unless
  the feature is materially changed.
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
