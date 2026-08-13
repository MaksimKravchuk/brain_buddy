"""Canonical executable checks for the bounded Allure 3 CI slice.

The deeper mutation cases remain beside the workflow validator in
``scripts/test_validate_ci_artifacts.py``. These focused checks validate the
shipped files directly so canonical requirement traceability does not rely on
docstring-only markers or a widened repository scanner.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate_ci_artifacts.py"
CLASSIFIER = REPO_ROOT / "scripts" / "classify_path_risk.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CONFIG = REPO_ROOT / "allurerc.mjs"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_008_FR_001_native_zero_failure_gate_is_final_and_explicit() -> None:
    """008-FR-001 008-FR-006."""

    validator = _load(VALIDATOR, "validate_ci_artifacts")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    config = CONFIG.read_text(encoding="utf-8")

    assert "maxFailures: 0" in config
    assert validator._quality_gate_errors(workflow) == []


def test_008_FR_002_both_reports_precede_the_verdict() -> None:
    """008-FR-002 008-FR-003 008-FR-004 008-SC-002."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    verdict = workflow.index("npx allure quality-gate")
    assert "npx allure generate ../allure-results -o ../allure-report" in workflow
    assert "npx allure awesome ../allure-results --single-file" in workflow
    assert "name: allure-report-html\n          path: allure-report" in workflow
    assert "name: allure-report-single-file\n          path: allure-report-single/index.html" in workflow
    assert workflow.index("name: allure-report-html") < verdict
    assert workflow.index("name: allure-report-single-file") < verdict


def test_008_FR_007_gate_config_is_ask_classified() -> None:
    """008-FR-007."""

    classifier = _load(CLASSIFIER, "classify_path_risk")
    change_class, _ = classifier.classify_path("allurerc.mjs")
    assert change_class == classifier.ASK


def test_008_FR_008_comment_is_truthful_and_actionable() -> None:
    """008-FR-008."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "- **Start here: `allure-report-single-file`**" in workflow
    assert "- **`allure-report-html`**" in workflow
    assert "open the single `index.html`. No local server needed." in workflow
    assert "complete report, including test attachments" in workflow
    assert "retained for **7 days** on a pull request and **30 days** on a push" in workflow