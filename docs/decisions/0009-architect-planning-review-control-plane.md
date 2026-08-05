# ADR-0009: Architect-owned planning review control plane

Date: 2026-07-25
Status: Accepted (mandatory-gate scope partially superseded by ADR-0011)
Decision owner: BrainBuddy
Related: ADR-0005, `.specify/workflows/speckit/`, `docs/spec-kit-workflow.md`, `scripts/spec_kit_planning_review.py`

## Context

ADR-0005 made Spec Kit mandatory for feature planning and kept Hermes Kanban as
the implementation orchestrator. The initial workflow delegated authoring steps
to the project integration and used generic approve/reject gates. That shape had
three weaknesses:

1. a nested CLI agent could become the de facto planner instead of the assigned
   Hermes Architect card;
2. generic gates could escalate technical choices to the product owner; and
3. Spec Kit Workflow Engine lacks Hermes guarantees for claims, worktrees,
   heartbeats, retries, merge state, and delivery evidence.

We still want persistent, bounded fan-out/fan-in for independent planning review
without creating a second writable scheduler.

## Decision

The assigned Hermes Architect session is the sole planning writer and semantic
decision owner. It authors `spec.md` and `plan.md` through repository-pinned Spec
Kit skills, then invokes `.specify/workflows/speckit/workflow.yml` as a
planning-review sub-pipeline.

The Workflow Engine:

- resolves the current feature without persisting `.specify/feature.json`;
- runs three standard review sessions with `max_concurrency: 3`;
- enforces Codex `--sandbox read-only --ephemeral` for standard reviews;
- adds a Fable review for explicit high-risk runs with Claude plan mode and only
  `Read,Grep,Glob` tools;
- validates every response against a strict JSON contract;
- fails closed on unavailable CLIs/quota, timeout, malformed output, role
  mismatch, or unsupported product-decision categories; and
- persists local run state and a deterministic review summary under
  `.specify/workflows/runs/<run-id>/`.

Reviewers never edit source or planning artifacts. The Architect reads the
summary, resolves technical findings, updates the planning artifacts, and reruns
the campaign at most once when needed.

Only these categories can produce a user-facing product gate: scope, UX,
priority, privacy, permissions, pricing, safety/compliance, and observable
acceptance behavior. The Architect blocks its own Kanban card with `needs_input`;
it does not use a generic terminal gate. Framework, database, API shape, module
boundaries, tests, migration mechanics, and implementation sequencing remain
technical decisions.

After an approved review, the Architect completes checklist/tasks/analyze and
writes `specs/NNN-feature/hermes-handoff.json` using
`speckit-hermes-handoff/v1`. The validated handoff contains 1–6 coarse acyclic
lanes with task references, dependencies, exclusive writer scopes, and
acceptance evidence. The Kanban Orchestrator compiles those lanes into execution
cards in waves, with at most four writable lanes active.

## Control-plane boundary

```text
Architect + Spec Kit skills  = authoritative semantic planning and file edits
Spec Kit Workflow Engine     = bounded read-only review scheduling and run state
Hermes Kanban                = sole writable implementation/delivery scheduler
```

Workflow Engine must not create implementation cards, branches, worktrees,
retries, merge/deploy state, or run `speckit.implement`/`taskstoissues`.
`tasks.md` remains a logical work breakdown, not the runtime graph.

## Consequences

Positive:

- independent planning checks are repeatable and resumable without relying on
  one model's conversational memory;
- reviewers are mechanically read-only and return machine-validated evidence;
- product-owner attention is reserved for observable product choices;
- a compact handoff prevents task-per-line Kanban swarms; and
- Hermes remains the single authority for writable execution lifecycle.

Tradeoffs:

- standard reviews currently use independent Codex sessions rather than three
  different model families;
- high-risk planning fails closed when Fable subscription quota is unavailable;
- Workflow Engine run files are local/ignored, so the versioned handoff records
  the accepted review run ID, reviewer set, resolved decisions, and lane contract;
- hard enforcement of all Kanban mutations still requires a future transaction-
  level Hermes core policy seam; this ADR does not claim plugin-level security.

## Verification

- `specify workflow info .specify/workflows/speckit/workflow.yml` parses version
  `2.0.0` with bounded fan-out/fan-in and no implementation command or gate step.
- `python3 scripts/test_spec_kit_planning_review.py -v` covers sandbox flags,
  response validation, product/technical routing, aggregation, handoff DAG
  validation, and workflow contract constraints.
- An engine smoke run with deterministic reviewer stand-ins must complete three
  parallel reviews, preserve the nested `inputs.json` envelope, write an
  `approved` summary, and leave `.specify/feature.json` absent.
- `python3 scripts/check_spec_kit_specs.py` and its unit suite remain green. The
  deterministic CI check for committed Spec Kit packages loads `validate_handoff` from
  `scripts/spec_kit_planning_review.py` and fails closed on malformed JSON, an
  empty object, a wrong schema version, a non-`approved` planning-review status,
  a missing required reviewer role, or a cyclic/overlapping lane DAG — a present
  `hermes-handoff.json` is never accepted on file existence alone.
