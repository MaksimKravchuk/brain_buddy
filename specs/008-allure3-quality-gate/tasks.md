# Tasks: Allure 3 aggregate Quality Gate and single-file report

Vertical RED → GREEN. See [plan.md](plan.md) for why each exists.

## Phase 1 — the gate

- [x] **T001** RED: extend `scripts/test_classify_path_risk.py`'s ASK list with
  `allurerc.mjs`. Fails: `'SHIP' != 'ASK'`. *(008-FR-007)*
- [x] **T002** RED: add `AllureQualityGateWorkflowTests` to
  `scripts/test_validate_ci_artifacts.py` — the shipped workflow grades the
  aggregate, the verdict is last, diagnostics precede it, warn-only and
  gate-replacing flags are rejected. Fails: no `_quality_gate_errors`.
  *(008-FR-004, 008-FR-006)*
- [x] **T003** GREEN: write `allurerc.mjs` with the single `maxFailures: 0` rule.
  *(008-FR-001)*
- [x] **T004** GREEN: add one `ASK_EXACT_PATHS` entry; re-record
  `.specify/gate-integrity.json`. *(008-FR-007)*
- [x] **T005** GREEN: add `_quality_gate_errors` and the
  `allure-report-single-file` entry in `REQUIRED_ARTIFACTS`; wire into
  `validate_workflow`. *(008-FR-004, 008-FR-006)*

## Phase 2 — the workflow

- [x] **T006** Add the single-file generation step; keep the multi-file step
  byte-identical. *(008-FR-002, 008-FR-003)*
- [x] **T007** Upload `allure-report-single/index.html` as
  `allure-report-single-file`, `if: always()`, existing retention expression;
  add `if: always()` to the multi-file upload. *(008-FR-003, 008-FR-004)*
- [x] **T008** Rewrite the PR comment: both artifacts, which to open first and
  how, 7/30 retention. *(008-FR-008)*
- [x] **T009** Add the canary step, then the verdict as the job's last step.
  *(008-FR-001, 008-FR-005)*

## Phase 3 — the canary

- [x] **T010** Write `scripts/allure_quality_gate_selftest.sh` and the two
  fixtures in `scripts/fixtures/allure-quality-gate/`, differing in one `status`
  field. Prove clean → 0 and dirty → non-zero with the installed CLI.
  *(008-FR-005, 008-SC-001)*

## Phase 4 — docs and verification

- [x] **T011** Write `docs/allure-quality-gate.md`; point `CLAUDE.md` at it.
- [x] **T012** Run Docker actionlint, the focused suites, the canary,
  `validate_ci_artifacts.py workflow`, `check_gate_integrity.py`,
  `check_spec_kit_specs.py`, and `git diff --check`.
- [ ] **T013** Independent verification and landing (owned by Hermes; not done
  in the authoring session, which does not commit, push or open a PR).
