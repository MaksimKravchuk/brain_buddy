# Cross-Artifact Analysis

Non-destructive consistency pass over [spec.md](spec.md), [plan.md](plan.md) and
[tasks.md](tasks.md), re-run after the scope reduction.

## Coverage

| Requirement | Task | Executable check |
| --- | --- | --- |
| 008-FR-001 | T003, T009 | canary + `_quality_gate_errors` (verdict present, explicit config) |
| 008-FR-002 | T006 | `REQUIRED_ARTIFACTS["allure-report-html"]`, unchanged generate step |
| 008-FR-003 | T006, T007 | `REQUIRED_ARTIFACTS["allure-report-single-file"] = allure-report-single/index.html`; `--single-file` required |
| 008-FR-004 | T005, T007 | ordering + last-step assertions |
| 008-FR-005 | T010 | `scripts/allure_quality_gate_selftest.sh`, real CLI, both exit codes |
| 008-FR-006 | T005 | warn-only and gate-replacing arguments rejected |
| 008-FR-007 | T001, T004 | `test_classify_path_risk.py` ASK list |
| 008-FR-008 | T008 | comment copy asserted against the workflow's retention expression |

No requirement is unimplemented; no task serves no requirement.

## Findings

1. **Diff-only and browser-usability claims are manual acceptance checks**, not
   formal machine-traceable requirements. Promoting them to FR/SC identifiers
   would make the traceability gate claim automation that does not exist.
2. **Requirement ids are machine-traceable through focused executable checks in
   the canonical backend test tree.** The bridge validates each tagged contract
   directly without widening the repository-wide requirement scanner.
3. **Lane completeness is out of scope and stated as such** in spec.md, so no
   artifact claims a guarantee the implementation does not make.

## Verdict

Consistent. No blocking issue; ready for independent verification (T013).
