"""The production rollout contract for the admin portal is pinned, not assumed.

`BRAIN_BUDDY_FEATURE_FLAGS` and `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` are
restaged from the deploy workflow on every release, so the workflow line — not
the code default and not a `flyctl secrets set` — is the authoritative
production state. Two properties therefore need a regression test rather than a
sentence: the operator allow-list is bound to the seeded admin identity (PD-2),
and the staged flag string stays **rollback-compatible** while the portal is
OFF (009-FR-013).

Rollback compatibility is the sharp edge, and it has already cut once. Fly
secrets are app-scoped and survive an image swap, so a secret staged by a
release is still pending when a rollback restores the captured image. That
image raises at startup on an unknown flag name — so staging a name it does
not know turns a rollback into a crash loop, and does the same if staging
itself partially succeeds and rollback then runs.

Deploy run 31775660872 proved this in production: it staged
`external_agent_relay=internal`, the candidate failed the public reachability
gate, and the automatic rollback restored an image that knows only
`delivery_canary`, `mobile_task_classification` and `voice_brain_dump`. The
allow-list pinned below is read from that image's startup logs, not from a
source SHA and not from this tree. The release therefore names no flag either
image is unsure of: OFF by omission, which both agree on.

`scripts/test_validate_trunk_delivery.py` proves the *validator* rejects a
workflow with either property removed; this proves the workflow the repository
actually ships still has them, and it runs inside the backend suite where the
requirement-coverage gate can see it.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import (
    PRIVATE_FEATURE_FLAGS,
    FeatureFlagSettings,
    _parse_feature_flag_states,
)

#: The image a rollback actually restores, identified the only way that is
#: verifiable: by the release image ref, not by a source SHA. Deploy run
#: 31775660872 rolled production back to this exact image, so it — not any
#: commit the repository believes is deployed — defines the contract.
ROLLBACK_TARGET_IMAGE = (
    "registry.fly.io/brain-buddy-backend:deployment-01KZXF74W98F1NVPHYKGD8QD0S"
)

#: `KNOWN_FEATURE_FLAGS` as it exists in that image, read from the machine
#: startup logs of run 31775660872: the image accepted these three names and
#: crashed at startup on `external_agent_relay`. Pinned as a literal on
#: purpose — reading it from the current tree would make this test agree with
#: whatever the candidate does, which is exactly the failure being guarded.
#: Widening this set is only honest once a *successful* deployment has made a
#: newer, known-compatible image the captured rollback target.
ROLLBACK_KNOWN_FEATURE_FLAGS = frozenset(
    {
        "delivery_canary",
        "mobile_task_classification",
        "voice_brain_dump",
    }
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "deploy-fly-production.yml"
VALIDATOR = REPO_ROOT / "scripts" / "validate_trunk_delivery.py"


def _load_validator() -> ModuleType:
    """Import the CI validator by path; it lives outside the backend package."""

    assert VALIDATOR.is_file(), VALIDATOR
    spec = importlib.util.spec_from_file_location("validate_trunk_delivery", VALIDATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _staged_flag_string(workflow_text: str) -> str:
    match = re.search(r'BRAIN_BUDDY_FEATURE_FLAGS="([^"]*)"', workflow_text)
    assert match is not None, "the deploy workflow no longer stages feature flags"
    return match.group(1)


def test_009_FR_013_staged_flags_stay_parseable_by_the_rollback_image(
    workflow_text: str,
) -> None:
    """A pending staged secret must not crash-loop the image we roll back to.

    Fly secrets are app-scoped and outlive the image, so this string is what
    the pre-009 backend reads if a rollback restores it. That backend rejects
    any name outside its allow-list at startup, which would make the documented
    rollback lever unusable at the moment it is needed.
    """

    staged = _staged_flag_string(workflow_text)
    names = set(_parse_feature_flag_states(staged))

    unknown_to_rollback_image = sorted(names - ROLLBACK_KNOWN_FEATURE_FLAGS)
    assert unknown_to_rollback_image == [], (
        f"{unknown_to_rollback_image} would crash {ROLLBACK_TARGET_IMAGE} at "
        "startup after a rollback; a release must not stage a flag that the "
        "captured rollback image has never heard of"
    )


def test_009_FR_013_the_validator_pins_the_same_rollback_allow_list() -> None:
    """One contract, stated twice, must not drift into two.

    The CI validator and this test both encode the captured rollback image's
    allow-list. Run 31775660872 failed because they agreed with each other on
    a set neither had checked against the deployed image; keeping them equal
    at least makes one honest correction fix both.
    """

    validator = _load_validator()

    assert validator.ROLLBACK_KNOWN_FEATURE_FLAGS == ROLLBACK_KNOWN_FEATURE_FLAGS
    assert ROLLBACK_TARGET_IMAGE in VALIDATOR.read_text(encoding="utf-8"), (
        "the validator must name the image whose allow-list it encodes, so the "
        "provenance is auditable rather than assumed"
    )


def test_009_FR_013_omission_keeps_both_unstaged_rollouts_off(
    workflow_text: str,
) -> None:
    """The names dropped from the staged string are OFF in the candidate too.

    `external_agent_relay` (removed after run 31775660872) and `admin_portal`
    (never staged) both remain in the candidate runtime; neither is enabled by
    the release, including for the internal smoke cohort, because an unnamed
    flag defaults to OFF.
    """

    staged = _staged_flag_string(workflow_text)
    names = set(_parse_feature_flag_states(staged))
    assert "external_agent_relay" not in names
    assert "admin_portal" not in names

    smoke = "smoke@example.com"
    settings = FeatureFlagSettings(
        states=_parse_feature_flag_states(staged),
        internal_users=frozenset({smoke}),
    )

    assert settings.effective_flags(smoke)["external_agent_relay"] is False
    assert settings.effective_flags(None)["external_agent_relay"] is False
    assert settings.private_flag_effective("admin_portal", smoke) is False


def test_009_FR_013_no_private_flag_is_named_in_the_first_release(
    workflow_text: str,
) -> None:
    """Every flag this feature added is new, so none may be staged yet.

    Generalized past `admin_portal` deliberately: the next private flag has
    the same rollback problem, and should fail here rather than in production.
    """

    names = set(_parse_feature_flag_states(_staged_flag_string(workflow_text)))
    assert names.isdisjoint(PRIVATE_FEATURE_FLAGS)


def test_009_FR_013_omission_is_off_for_the_new_code(workflow_text: str) -> None:
    """Omission is not a gap in the contract — it is how the portal ships OFF.

    The candidate defaults an unnamed flag to OFF, so the staged string and the
    runtime posture agree without either image having to name it.
    """

    staged = _staged_flag_string(workflow_text)
    settings = FeatureFlagSettings(states=_parse_feature_flag_states(staged))

    for flag in PRIVATE_FEATURE_FLAGS:
        assert settings.private_flag_effective(flag, "operator@example.com") is False
        assert settings.private_flag_effective(flag, None) is False


def test_009_FR_013_enabling_later_means_naming_the_flag_here(
    workflow_text: str,
) -> None:
    """Turning the portal on is an audited ASK edit to this line, not a secret.

    It is safe only once rollback compatibility is deliberately handled — the
    rollback target must already know the name before it is ever staged.
    """

    assert "admin_portal" in workflow_text  # documented, not staged
    assert "admin_portal=" not in _staged_flag_string(workflow_text)


def test_009_FR_013_enabling_the_portal_is_documented_as_a_workflow_edit(
    workflow_text: str,
) -> None:
    """The rollback story depends on this being written where it is changed."""

    assert "Change the rollout here, not out of band." in workflow_text
    assert "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS=`" in workflow_text
