# Implementation Plan: Allure 3 aggregate Quality Gate and single-file report

**Spec**: [spec.md](spec.md) · **Design**: [design.md](design.md) · **Tasks**: [tasks.md](tasks.md)

## Approach

Use Allure Report 3's own quality gate. The CLI already installed under
`frontend/` reads a config file and exits non-zero when a rule fails, so the
entire enforcement mechanism is one config file plus one workflow step. No
validator framework, no threshold engine, no lane bookkeeping: every one of
those would be a second implementation of something the CLI already does.

## Changed surfaces

| File | Change |
| --- | --- |
| `allurerc.mjs` | new, ~17 lines: one rule, `maxFailures: 0` (007-FR-001) |
| `.github/workflows/ci.yml` | `allure-report` job only: generate the single-file report, upload it, truthful comment, canary, verdict last (007-FR-002…005, 008) |
| `scripts/allure_quality_gate_selftest.sh` + two fixtures | the canary (007-FR-005) |
| `scripts/classify_path_risk.py` | one entry: `allurerc.mjs` is ASK (007-FR-007) |
| `scripts/validate_ci_artifacts.py` | one function, `_quality_gate_errors`, wired into the existing `workflow` subcommand (007-FR-004, 006) |
| `.specify/gate-integrity.json` | re-record the classifier's hash — mechanical, required by the existing guard |
| `docs/allure-quality-gate.md`, `CLAUDE.md` | one short doc, one pointer to it |

## Key decisions

1. **Native gate, not a custom validator.** The rejected first attempt built a
   610-line admission framework around the CLI. Everything it enforced beyond
   `maxFailures: 0` was out of scope, and the parts in scope were duplicates of
   CLI behaviour.
2. **Verdict last, diagnostics first.** The uploads and the comment run before it
   and carry `if: always()`, so a red gate never removes its own explanation.
   `_quality_gate_errors` asserts the ordering, because a later reorder is the
   realistic way this property gets lost.
3. **Explicit `--config ../allurerc.mjs`.** Allure's defaults declare no gate, so
   an implicit lookup would turn a deleted config into a silent pass.
4. **A canary, not a unit test of the config.** A test that asserts the file
   contains `maxFailures: 0` proves nothing about the CLI. Running the real CLI
   over a clean and a dirty fixture proves the property itself (007-FR-005).
5. **ASK class only.** The config is a gate surface, so it must not land through
   automatic promotion. It is deliberately *not* added to the gate-integrity
   hash manifest: one enforcement mechanism per property.

## Constitution check

- No product code, no new dependency, action, permission, secret or job.
- The evidence rules that already exist (per-lane uploads, taxonomy validators,
  retention expression, job graph) are untouched; this only adds a verdict.

## Risks

- **The CLI's gate semantics change on upgrade.** The canary fails loudly on the
  next run rather than degrading to a silent pass.
- **A future step is appended after the verdict.** The validator rejects it.
