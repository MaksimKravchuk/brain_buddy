# BrainBuddy spec-driven Kanban runbook

This is the Hermes-only operational runbook for a BrainBuddy outcome explicitly
enrolled in the optional managed-delivery mode defined by ADR-0010. It does not
apply to ordinary developer work or standalone agents. Spec Kit owns `specs/`;
the Hermes `spec-driven-kanban` plugin owns governed workflow state, Kanban
handoff, delivery evidence, and acceptance only for the enrolled outcome.

## Activation boundary

Use this runbook only when the user explicitly requests managed delivery, the
root task contains `workflow_contract: spec-driven-delivery/v1`, or an existing
managed task has a valid plugin manifest. The installed plugin, board, project,
or `.hermes.md` alone is not an activation signal.

## Runtime boundary

```text
Spec Kit artifacts                  specs/NNN-feature/{spec.md,plan.md,tasks.md}
spec-driven-kanban manifest         .specify/workflows/<root-task-id>/
Hermes board                        brain-buddy
Hermes project                      brain-buddy
root + initial lane profile         default
product-code writer                 Claude Code CLI
independent verifier/runtime owner  Hermes
release authority                   ADR-0008
```

Inside a managed outcome, Hermes owns execution: do not generate
`hermes-handoff.json` for a new managed outcome by hand, and never create
delivery siblings manually. Implementation for a managed outcome flows through
Kanban cards, not through a direct `/speckit-implement` run — the skill routes
there itself when the invoking task carries explicit ADR-0010 activation.

Two former prohibitions in this section no longer apply:

- **`/speckit-implement` is no longer disabled.** It implements directly from
  `tasks.md` outside a managed outcome, which is what `CLAUDE.md`, the
  constitution and `docs/spec-kit-workflow.md` always said. The disabled
  version contradicted all three and stalled any agent that read skills first.
- **`.specify/workflows/speckit/workflow.yml` is no longer legacy.** ADR-0011
  makes it the portable spec review gate that runs for every feature, managed
  or not. Run it via `/speckit-review`.

## Create one root outcome

Choose the next unused `NNN-feature` slug, classify risk, and list every affected surface from `backend_data`, `frontend_ux`, and `ios_mobile`.

```bash
hermes kanban --board brain-buddy create \
  "Outcome: <measurable user result>" \
  --project brain-buddy \
  --workspace worktree \
  --assignee default \
  --skill spec-driven-kanban:spec-architect \
  --goal --goal-max-turns 20 \
  --max-retries 2 \
  --idempotency-key "brainbuddy:<NNN-feature>:outcome" \
  --body '<paste the intake body below>'
```

Do not use `--triage`: `kanban.auto_decompose` is disabled and the plugin owns decomposition.

### Intake body

```yaml
workflow_contract: spec-driven-delivery/v1
feature: NNN-feature
risk: standard
allowed_risk_values: [low, standard, high]
affected_surfaces:
  - backend_data
  - frontend_ux

outcome: <observable result>
acceptance:
  - <observable criterion>

plugin_start:
  spec_path: specs/NNN-feature/spec.md
  plan_path: specs/NNN-feature/plan.md
  tasks_path: specs/NNN-feature/tasks.md

agent_procedure:
  - load spec-driven-kanban:spec-architect
  - call spec_workflow_start for this root card with the explicit paths above
  - on every run call state, then reconcile, then perform only allowed_next
  - use Spec Kit only for artifact authoring; never call speckit-implement
  - let spec_workflow_build_handoff create every delivery/QA/release card
  - use Claude Code CLI for product-code writing and Hermes for independent verification
  - obey ADR-0008; do not commit, push, submit, merge, change rulesets, or deploy without the authority that ADR requires
```

Use `standard` by default. Use `high` for auth/privacy, destructive schema or data changes, billing/provider credentials, security/CI/CD/infra, migrations with irreversible effects, or other ASK-class work. Agents may raise risk, never lower it.

## Planning and handoff

The root agent follows the plugin state, not prose memory:

```text
state → reconcile → allowed_next → produce artifact/evidence → submit step
```

BrainBuddy's non-default Spec Kit paths must be supplied to `spec_workflow_start` exactly as shown above. Requirements review and ratification happen before architecture planning. For this enrolled outcome only, extend the portable `tasks.md` entries with this managed grammar:

```text
[ID] [P?] [owner:*] [platform:*] [kind:*] [deps:*] [req:*] [scope:*] Description
```

The managed parser uses `req` for traceability, so replace the portable
`[Story]` token rather than retaining it as an additional bracketed attribute.

- `owner`: an existing Hermes profile; the initial rollout uses `default`;
- `platform`: `backend`, `frontend`, `ios`, `integrated`, or `release`;
- `kind`: `implementation`, `qa`, `integrated_qa`, `release`, or `non_implementation`;
- `deps`: comma-separated task ids; omit only when no dependency exists;
- `req`: comma-separated `FR-*`/`AC-*` ids from the current spec;
- `scope`: comma-separated, non-overlapping repo-relative writer globs for implementation tasks; QA/release tasks normally omit it.

Example:

```text
- [ ] T010 [owner:default] [platform:backend] [kind:implementation] [req:FR-001] [scope:backend/**] Implement the backend behavior with tests
- [ ] T020 [owner:default] [platform:backend] [kind:qa] [deps:T010] [req:FR-001] Verify backend behavior and persist a canonical QA receipt
- [ ] T030 [owner:default] [platform:integrated] [kind:integrated_qa] [deps:T020] [req:FR-001] Verify the integrated outcome and persist a canonical QA receipt
- [ ] T040 [owner:default] [platform:release] [kind:release] [deps:T030] [req:FR-001] Follow ADR-0008 and persist the canonical release receipt
```

The managed package must include:

- implementation tasks for each affected surface;
- one platform-QA task after each implementation lane;
- one integrated-QA task after all platform QA;
- one release task after integrated QA;
- existing owner profile (`default` during the initial rollout);
- requirement references and non-overlapping writer scopes.

`spec_workflow_build_handoff` validates and imports the compact DAG, then parks the root until release finishes.

## Human decisions

Only product/privacy/legal/cost/safety/irreversible authority decisions should block the root. Answer a plugin request with:

```text
/spec-flow decide <task-id> --id <decision-id> --question "<question>" --choice "<choice>" --rationale "<why>" --owner "Max"
```

The receipt is bound to that decision and the exact current spec hash. An agent cannot mint it.

## Delivery and evidence

Implementation lanes obey their signed scopes and dependencies. Product code is written through Claude Code CLI; the Hermes lane worker independently reviews the resulting diff and runs the required tests.

QA and release lanes must complete with the canonical JSON receipts described by the forced plugin skill. Required properties include:

- exact root outcome id and lane key;
- full lowercase Git SHA;
- PASS verdict and unique check ids;
- canonical HTTPS CI/evidence URLs;
- for release: production environment, succeeded deployment, and smoke result.

ADR-0008 still controls landing and deployment. SHIP/SHOW use exact-SHA Full CI + Docker and the main-only landing identity. ASK requires explicit recorded approval and the audited temporary ruleset procedure. The plugin observes and validates this evidence; it does not bypass it.

## Observe and recover

Use Dashboard → **Outcomes** for the governed stage and the BrainBuddy board for runtime cards.

```bash
hermes kanban --board brain-buddy list
hermes kanban --board brain-buddy show <task-id>
```

Operator commands:

```text
/spec-flow status <task-id>
/spec-flow reconcile <task-id>
/spec-flow resume <task-id>
```

Reconcile is safe and idempotent. If a gate refuses, fix the named violation; do not drag the card around the gate or create replacement lanes.
