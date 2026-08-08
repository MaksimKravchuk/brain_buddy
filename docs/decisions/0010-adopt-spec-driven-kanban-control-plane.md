# ADR-0010: Offer spec-driven-kanban for opt-in managed outcomes

Date: 2026-08-08
Status: Accepted
Decision owner: BrainBuddy
Supersedes within explicitly managed outcomes only: the active delivery-control-plane and planning-review portions of ADR-0009
Related: ADR-0005, ADR-0008, `.hermes.md`, `docs/spec-driven-kanban.md`, `docs/spec-kit-workflow.md`

## Context

BrainBuddy uses Spec Kit for portable, versioned requirements and architecture
artifacts under `specs/`. Developers and standalone agents must be able to use
those artifacts without Hermes, a Kanban board, plugin tools, managed-lane
metadata, or workflow receipts.

For selected larger outcomes, Hermes has a standalone `spec-driven-kanban`
plugin that can bind frozen Spec Kit artifacts to an exact hash, run an isolated
requirements panel and independent ratification, create compact delivery lanes,
and gate QA, release, and acceptance on canonical receipts. Those guarantees
are valuable when the outcome is intentionally enrolled, but imposing the
plugin on every repository task would couple portable project instructions to
one execution runtime.

## Decision

`spec-driven-kanban` is an **opt-in control plane for managed outcomes**, not the
mandatory path for all BrainBuddy work.

A managed outcome is activated only when one of these explicit signals exists:

1. the user requests `spec-driven-kanban` management; or
2. a root Hermes task is created with
   `workflow_contract: spec-driven-delivery/v1`; or
3. an already-managed root/lane has a valid plugin workflow manifest.

The presence of `.hermes.md`, the installed plugin, the `brain-buddy` board, or
`.specify/workflows/` alone does not activate managed mode.

Outside an activated managed outcome:

- `AGENTS.md`, `CLAUDE.md`, the constitution, and core Spec Kit templates remain
  portable and runtime-neutral;
- developers and standalone agents may plan and implement directly from the
  validated Spec Kit artifacts;
- no plugin tool, Hermes profile, managed annotation, lane, or receipt is
  required;
- ADR-0009 remains applicable within its original scope.

Within an activated managed outcome:

1. One root outcome card on the `brain-buddy` board owns managed planning
   through acceptance.
2. Spec Kit remains the product-planning source of truth under
   `specs/NNN-feature/`; plugin start calls pass explicit `spec_path`,
   `plan_path`, and `tasks_path` overrides.
3. The plugin Requirements Panel, Architect adjudication, and Ratifier replace
   the ADR-0009 planning-review campaign for that outcome.
4. The managed task overlay adds owner/platform/kind/deps/req/scope metadata for
   that outcome. `spec_workflow_build_handoff` is the only path that creates its
   implementation, platform-QA, integrated-QA, and release cards.
5. The plugin manifest and receipts under `.specify/workflows/` are authoritative
   workflow state for that managed outcome. Historical `hermes-handoff.json`
   files remain valid evidence when present.
6. Product-code edits in signed implementation lanes are authored through
   Claude Code CLI. Hermes independently inspects the diff, executes checks,
   validates evidence, and owns the Kanban result.
7. ADR-0008 remains authoritative for SHIP/SHOW/ASK landing and production
   release. The plugin grants no additional commit, push, merge, deployment,
   secret, or ruleset authority.

## Runtime configuration for managed outcomes

- Hermes board: `brain-buddy`
- Hermes project: `brain-buddy`, bound to that board
- default repository: `/home/max/Code/brain_buddy`
- root and initial lane assignee: `default`
- dispatcher: gateway-owned, one in-progress card per profile
- automatic Kanban decomposition: disabled
- forced root skill: `spec-driven-kanban:spec-architect`

These settings are runtime configuration, not repository-wide instructions for
standalone agents.

## Consequences

- Ordinary work remains usable from Claude Code, Codex, an IDE, or a developer
  shell without pretending Hermes is present.
- Managed outcomes retain exact-hash ratification, compact lanes, canonical
  evidence, reconciliation, and bounded human escalation.
- The main Spec Kit task template stays portable. Managed metadata is documented
  only in `.hermes.md` and `docs/spec-driven-kanban.md`, and is added only to an
  enrolled outcome.
- A changed managed `spec.md` invalidates prior ratification; changed frozen
  artifacts invalidate its signed delivery handoff.
- QA and release prose is not evidence inside managed mode: completion requires
  the plugin's canonical receipts and exact full commit SHA.

## Verification

- run `python3 -m unittest scripts/test_check_spec_kit_specs.py -v`;
- run `python3 scripts/check_spec_kit_specs.py`;
- verify portable instruction files contain no mandatory plugin calls or managed
  task grammar;
- parse the runbook's managed task example with the installed
  `spec_driven_kanban.handoff.parser`;
- create no live outcome during repository setup.
