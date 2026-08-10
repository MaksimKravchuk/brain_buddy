# BrainBuddy Spec Kit workflow

BrainBuddy uses the official GitHub Spec Kit as the mandatory authoring workflow
for every new or materially changed feature specification.

- Spec Kit version: `github/spec-kit` `v0.15.0`
- Installed integrations: Claude Code skills under `.claude/skills/` and Codex
  skills under `.agents/skills/`
- Scope: feature specification and planning artifacts under `specs/`, plus the
  BrainBuddy-local stages that bracket them — business intake, design, the
  portable spec review gate (ADR-0011), acceptance and the delivery report
- Non-scope: CI, merge, release, or deploy

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

Do not run an unscoped `specify extension update`: extensions have independent
versions and require their own source review. Update each pinned extension
explicitly by id.

### Extension policy

`specify extension search` returns ~150 entries, but the shape of that catalog
matters more than its size:

| catalog | count | installable |
|---|---|---|
| `default` (all `spec-kit-core`) | 4 | yes |
| `community` | ~146 | **no — discovery only** |

The community catalog cannot be installed from. Adopting one of its entries
means adding a custom catalog (`.specify/extension-catalogs.yml`) or installing
from a third-party repository, each requiring its own source review and version
pin. None is BrainBuddy-aware: our review lenses cite the constitution,
ADR-0006 vocabulary, the Allure taxonomy and `classify_path_risk.py`, and a
generic extension knows none of that.

Decisions on the four installable extensions:

- **`assess` — INSTALLED.** Stage 0 of the pipeline: intake → research →
  define → shape → decide, writing
  `.specify/assessments/<slug>/decision.md` with a
  `go / needs-clarification / kill` verdict. It supplies the one capability the
  hand-built pipeline lacked — closing an idea *before* requirements are
  elicited. `/speckit-interview` reads that verdict and refuses to proceed on a
  `kill`, which is what makes the gate load-bearing.
  It ships Claude skills only (`.claude/skills/speckit-assess-*`), so it is
  **not** registered under `hooks` in `.specify/extensions.yml`: a hooked
  command with no `.agents/skills/` twin breaks Codex runs.

- **`git` — NOT INSTALLED**, and the reason is specific rather than blanket.
  It provides five commands; the extension installs all or none:
  `speckit.git.commit` auto-commits after each Spec Kit command, which breaks
  ADR-0008 — `scripts/submit_to_trunk.sh` requires exactly one non-merge commit
  whose parent equals current `origin/main`. `speckit.git.feature` duplicates
  `.specify/scripts/bash/create-new-feature.sh` and fights worktree ownership.
  `speckit.git.initialize` is irrelevant here. The two read-only commands
  (`speckit.git.validate`, `speckit.git.remote`) are harmless but add nothing:
  branch naming is already a repository convention and remote detection is
  already done by `speckit-taskstoissues`.

- **`agent-context` — NOT INSTALLED.** It manages `CLAUDE.md` with generated
  plan references and markers. `CLAUDE.md` here is hand-maintained and
  authoritative; a generator editing it would fight every manual change.

- **`bug` — not installed, but not rejected.** Bug triage under
  `.specify/bugs/<slug>/` is outside the feature-delivery pipeline. Worth
  revisiting on its own merits.

**`specify extension add` rewrites `.specify/extensions.yml` and strips its
comments.** After any install, restore the header from git history — it
documents the hook contract and the Codex-parity requirement.

`.specify/extensions.yml` is **not** a third-party extension install. It is
first-party repository configuration that the ten v0.15.0 skills already read:
each checks `hooks.before_<stage>` and `hooks.after_<stage>` and, for a
mandatory hook, emits `EXECUTE_COMMAND` and waits. Chaining the BrainBuddy
stages through it is what lets intake, design, review, acceptance and report
attach to the standard flow **without forking a single upstream skill body**.
It adds no new runtime, no scheduler, and no upstream dependency. Review it
like product code; it is not covered by the extension prohibition above.

Before a forced integration refresh, preserve every file in the
preserved-overrides table below. Restore them after the refresh, inspect
`git diff`, and accept only understood project-specific overrides. The current
refresh installs v0.15.0 shared assets under `.specify/`, Claude Code skills
under `.claude/skills/`, and Codex skills under `.agents/skills/`.

### Preserved overrides

`specify integration upgrade <agent> --force` overwrites installed assets with
upstream content, silently reverting each of these. Nothing used to verify them
afterwards, so a refresh could quietly undo a policy decision.
`scripts/check_speckit_manifests.py` now guards them — each file carries a
marker string that upstream cannot contain — and runs in `make check-specs`.

| file | why it diverges from upstream |
|---|---|
| `.specify/templates/spec-template.md` | consent/local-first and mobile-first callouts required by the constitution |
| `.specify/templates/plan-template.md` | real repository source tree; Constitution Check including the requirement to cite `design.md` |
| `.specify/templates/tasks-template.md` | delivery gates restated: worktree, TDD, independent acceptance, ADR-0008 landing |
| `.specify/templates/checklist-template.md` | BrainBuddy constitution gates |
| `.claude/skills/speckit-implement/SKILL.md` | implements directly from `tasks.md`; upstream has no such policy, and the previous local version refused to run at all |
| `.agents/skills/speckit-implement/SKILL.md` | Codex twin of the same policy |

Run `python3 scripts/check_speckit_manifests.py --list` to see the markers.

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
8. Implement directly from the validated artifacts with `/speckit-implement`,
   or, when explicitly enrolled, apply the optional managed-outcome overlay
   from `docs/spec-driven-kanban.md`.
9. Amend spec/plan/tasks and rerun affected validation whenever
    implementation intent changes.

### BrainBuddy stages around the Spec Kit core

`.specify/extensions.yml` chains five local stages onto the flow above. The
full path for a feature that starts from an abstract ask:

```text
/speckit-interview   business requirements from the human -> intake.md
/speckit-specify     what and why -> spec.md
/speckit-clarify     disambiguate
/speckit-design      screens + numbered state inventory -> design.md   [human sign-off]
/speckit-plan        how and architecture -> plan.md  (MUST cite design.md)
/speckit-review      five-lens review gate (ADR-0011) -> verdict
/speckit-checklist   requirements quality
/speckit-tasks       -> tasks.md
/speckit-analyze     cross-artifact consistency
/speckit-implement   direct implementation via an isolated worktree
/speckit-accept      criterion -> test traceability -> accept | reject
/speckit-report      the end-to-end report for the human
```

Human-in-the-loop gates: the interview, clarification, design sign-off, any
product decision raised by review, ASK-class landing, and the final report.

### The review gate

`/speckit-review` is the single front door; do not invoke
`scripts/spec_kit_planning_review.py` ad hoc. ADR-0011 governs it.

**Risk classes** (ADR-0012): `low | medium | high`, derived by the preflight.
An ASK-class surface derives `high` and additionally requires a recorded human
sign-off. An entirely inert change — every named path under `docs/`, `specs/`,
`requirements/` or `*.md` — derives `low`. **Everything else, including a
change no path could be extracted from, derives `medium`.** Unknown risk is
never `low`: treating silence as safety would let exactly the work nobody could
classify take the cheapest path. Risk escalates and never de-escalates.

**Aggregation rule**, in order:

1. Any configured lens produced no review → `escalated`. Missing mandatory
   evidence never resolves to a pass, and it is checked first.
2. Any `product_decisions`, or any reviewer verdict of
   `product-decision-required` → `product-decision-required`. Needs the human.
3. Any reviewer verdict of `changes-required`, or any `blocking` finding →
   `technical-changes-required`.
4. Risk `high` with no recorded human sign-off → `escalated`.
5. Otherwise → `approved`.

A reviewer's verdict is gate-blocking on its own; the aggregator does not
re-derive it from finding severities. A malformed review still raises — absence
and corruption are different.

**Panel independence.** No model covers a majority of the five lenses and the
panel spans two providers, both asserted by tests. Three lenses sharing one
model is one opinion counted three times, which the aggregation rule would read
as corroboration.

**Campaign cap: two.** Fresh reviewer sessions re-litigate artifacts from
scratch, so finding counts diverge between runs even as every verified defect
is fixed. Carry campaign 1's findings forward into campaign 2. After campaign
2: land the fixes, defer the residue into explicit open lanes, or close by
founder acceptance with the full record (see below).

**Degraded runs.** Two of the five lenses shell out to the `codex` CLI. Where
it is absent they cannot run and the campaign returns `escalated`, naming the
missing lenses. A partial campaign is never reported as a clean one.

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

Codex exposes the same skills with `$` skill invocations, including the five
BrainBuddy stages:

```text
$speckit-constitution
$speckit-interview
$speckit-specify
$speckit-clarify
$speckit-design
$speckit-plan
$speckit-review
$speckit-checklist
$speckit-tasks
$speckit-analyze
$speckit-implement
$speckit-accept
$speckit-report
```

`.specify/extensions.yml` is shared by both agent trees, so **every hooked
command must exist in both**. A mandatory hook whose skill lives only under
`.claude/skills/` makes a Codex run emit `EXECUTE_COMMAND` for a command that
tree cannot invoke, stopping the pipeline at that stage.
`scripts/test_check_speckit_manifests.py` enforces the parity.

The Codex twins are thin adapters: Codex has no subagent runtime, so where the
Claude skill delegates to an agent under `.claude/agents/`, the twin applies
that agent file's contract inline. Those agent files are plain markdown and
remain the single source of truth for rubrics and procedures — do not fork them
per runtime.

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
intake.md                    # /speckit-interview
spec.md                      # /speckit-specify
checklists/requirements.md   # /speckit-checklist
design.md                    # /speckit-design (a no-UI feature says so in two lines)
plan.md                      # /speckit-plan
tasks.md                     # /speckit-tasks
```

Once every task in `tasks.md` is checked off, the feature counts as delivered
and must additionally carry:

```text
acceptance.md        # /speckit-accept — explicit accept | reject verdict
traceability.md      # criterion -> named test matrix
report.md            # /speckit-report
```

Those three are deliberately **not** required at planning time. Demanding an
acceptance verdict for work that does not exist yet would force an agent to
fabricate one, which is worse than not requiring it.
`scripts/check_spec_kit_specs.py` reads delivery mechanically off `tasks.md`:
no unchecked `- [ ]` task lines left, and at least one ticked box.

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
