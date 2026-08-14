"""The production rollout contract for the admin portal is pinned, not assumed.

`BRAIN_BUDDY_FEATURE_FLAGS` and `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` are
restaged from the deploy workflow on every release, so the workflow line — not
the code default and not a `flyctl secrets set` — is the authoritative
production state. Two properties therefore need a regression test rather than a
sentence: the operator allow-list is bound to the seeded admin identity (PD-2),
and the staged flag string stays **rollback-compatible** while it rolls the
portal out to the internal operator (009-FR-013).

Rollback compatibility is the sharp edge, and it has already cut once. Fly
secrets are app-scoped and survive an image swap, so a secret staged by a
release is still pending when a rollback restores the captured image. That
image raises at startup on an unknown flag name — so staging a name it does
not know turns a rollback into a crash loop, and does the same if staging
itself partially succeeds and rollback then runs.

Deploy run 31775660872 proved this in production: it staged
`external_agent_relay=internal`, the candidate failed the public reachability
gate, and the automatic rollback restored an image that could not parse the
name. The allow-list pinned below is read from the *current* rollback target,
not from a source SHA and not from this tree.

That target has since moved on: the default-OFF baseline release made a 009
image the healthy current one, so both `admin_portal` and `external_agent_relay`
are now rollback-parseable. Parseable is not the same as authorized — only
`admin_portal` is being rolled out, and the relay stays omitted, which is the
OFF state every image agrees on.

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
#: verifiable: by the release image ref, not by a source SHA. The default-OFF
#: baseline deployment (run 31798252344 for exact main d9ec122f, authenticated
#: production smoke passed) left this image running and healthy, so it — not
#: any commit the repository believes is deployed — defines the contract.
ROLLBACK_TARGET_IMAGE = (
    "registry.fly.io/brain-buddy-backend:deployment-01M00243625JAFN5S6G4CVZ7DH"
)

#: The flag names that image can parse. It was built from the 009 revision, so
#: it knows `admin_portal` and `external_agent_relay` as well as the three the
#: pre-009 image knew — which is exactly the precondition that makes staging
#: `admin_portal` rollback-safe. Pinned as a literal on purpose: reading it
#: from the current tree would make this test agree with whatever the candidate
#: does, which is the failure run 31775660872 was. Widening it is only honest
#: once a *successful* deployment has made a newer image the captured rollback
#: target, as that baseline release did.
#:
#: This is a safety allow-list. It says nothing about which rollouts are
#: authorized — `external_agent_relay` is parseable here and still must not be
#: staged.
ROLLBACK_KNOWN_FEATURE_FLAGS = frozenset(
    {
        "delivery_canary",
        "mobile_task_classification",
        "voice_brain_dump",
        "external_agent_relay",
        "admin_portal",
    }
)

#: The exact rollout this release stages, as one string. Pinned whole so that a
#: dropped name, an added name or a downgraded state all fail here.
AUTHORIZED_STAGED_FEATURE_FLAGS = (
    "delivery_canary=internal,voice_brain_dump=on,admin_portal=internal"
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
    assert validator.AUTHORIZED_STAGED_FEATURE_FLAGS == AUTHORIZED_STAGED_FEATURE_FLAGS
    assert ROLLBACK_TARGET_IMAGE in VALIDATOR.read_text(encoding="utf-8"), (
        "the validator must name the image whose allow-list it encodes, so the "
        "provenance is auditable rather than assumed"
    )


def test_009_FR_013_the_release_stages_exactly_the_authorized_rollout(
    workflow_text: str,
) -> None:
    """Turning the portal on is an edit to this line, so pin the whole line.

    An equality rather than a set of `in` checks, so that adding a name,
    dropping one, or downgrading `admin_portal` all fail here.
    """

    assert _staged_flag_string(workflow_text) == AUTHORIZED_STAGED_FEATURE_FLAGS


def test_009_FR_013_the_portal_is_effective_only_for_the_internal_operator(
    workflow_text: str,
) -> None:
    """`internal` means the seeded cohort and nobody else — not ON by another
    name, and still not visible to any member.

    The flag is exposure control layered on top of `require_operator`
    (009-FR-002 precedence), so this asserts only its own reach. It stays a
    `PRIVATE_FEATURE_FLAGS` entry, so enabling it changes no member-facing
    response shape (009-FR-010).
    """

    operator = "operator@example.com"
    settings = FeatureFlagSettings(
        states=_parse_feature_flag_states(_staged_flag_string(workflow_text)),
        internal_users=frozenset({operator}),
    )

    assert settings.private_flag_effective("admin_portal", operator) is True
    assert (
        settings.private_flag_effective("admin_portal", "member@example.com") is False
    )
    assert settings.private_flag_effective("admin_portal", None) is False

    assert "admin_portal" in PRIVATE_FEATURE_FLAGS
    assert "admin_portal" not in settings.effective_flags(operator)


def test_009_FR_013_the_relay_rollout_stays_omitted_and_off(
    workflow_text: str,
) -> None:
    """Rollback-parseable is not authorized to ship.

    The current rollback target parses `external_agent_relay`, so nothing about
    compatibility stops it being staged; spec 007's rollout is separately
    governed and this release does not grant it. Omission is OFF.
    """

    assert "external_agent_relay" in ROLLBACK_KNOWN_FEATURE_FLAGS
    assert "external_agent_relay" not in AUTHORIZED_STAGED_FEATURE_FLAGS

    smoke = "smoke@example.com"
    settings = FeatureFlagSettings(
        states=_parse_feature_flag_states(_staged_flag_string(workflow_text)),
        internal_users=frozenset({smoke}),
    )

    assert settings.effective_flags(smoke)["external_agent_relay"] is False
    assert settings.effective_flags(None)["external_agent_relay"] is False


def test_009_FR_013_enabling_the_portal_is_documented_as_a_workflow_edit(
    workflow_text: str,
) -> None:
    """The rollback story depends on this being written where it is changed."""

    assert "Change the rollout here, not out of band." in workflow_text
    assert "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS=`" in workflow_text
