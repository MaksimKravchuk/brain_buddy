"""The production rollout contract for the admin portal is pinned, not assumed.

`BRAIN_BUDDY_FEATURE_FLAGS` and `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` are
restaged from the deploy workflow on every release, so the workflow line — not
the code default and not a `flyctl secrets set` — is the authoritative
production state. Two properties therefore need a regression test rather than a
sentence: the operator allow-list is bound to the seeded admin identity (PD-2),
and the portal is staged OFF (009-FR-013).

`scripts/test_validate_trunk_delivery.py` proves the *validator* rejects a
workflow with either property removed; this proves the workflow the repository
actually ships still has them, and it runs inside the backend suite where the
requirement-coverage gate can see it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-fly-production.yml"


@pytest.fixture(scope="module")
def workflow_text() -> str:
    assert DEPLOY_WORKFLOW.is_file(), DEPLOY_WORKFLOW
    return DEPLOY_WORKFLOW.read_text(encoding="utf-8")


def test_009_FR_001_production_operators_are_exactly_the_seeded_admin_identity(
    workflow_text: str,
) -> None:
    """PD-2 made concrete: the binding, not just the variable name."""

    assert (
        'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_EMAIL}"'
        in workflow_text
    )


def test_009_FR_013_production_stages_the_admin_portal_flag_off(
    workflow_text: str,
) -> None:
    """The flag string is exhaustive, so an unnamed flag is OFF by omission.

    Staging `admin_portal=off` explicitly makes the initial production posture
    a stated decision that a reader (and this test) can check, rather than an
    inference from absence.
    """

    match = re.search(r'BRAIN_BUDDY_FEATURE_FLAGS="([^"]*)"', workflow_text)
    assert match is not None, "the deploy workflow no longer stages feature flags"
    entries = dict(
        entry.split("=", 1) for entry in match.group(1).split(",") if "=" in entry
    )
    assert entries.get("admin_portal") == "off"


def test_009_FR_013_enabling_the_portal_is_documented_as_a_workflow_edit(
    workflow_text: str,
) -> None:
    """The rollback story depends on this being written where it is changed."""

    assert "Change the rollout here, not out of band." in workflow_text
    assert "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS=`" in workflow_text
