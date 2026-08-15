"""The production rollout contract for the admin portal is pinned, not assumed.

`BRAIN_BUDDY_FEATURE_FLAGS` and `BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` are
restaged from the deploy workflow on every release, so the workflow line — not
the code default and not a `flyctl secrets set` — is the authoritative
production state. Two properties therefore need a regression test rather than a
sentence: the operator allow-list is staged from its own dedicated secret,
never aliased to the smoke admin identity (PD-2), and the staged flag string
stays **rollback-compatible** while it rolls the portal out to the internal
operator (009-FR-013).

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
import os
import re
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from app.core.config import (
    FeatureFlagSettings,
    FeatureFlagState,
    ManagedFlagMigrationInput,
    _parse_feature_flag_states,
)

_BASH_EXECUTABLE = shutil.which("bash")
assert _BASH_EXECUTABLE, "bash must be on PATH to run the extracted workflow steps"
_GIT_EXECUTABLE = shutil.which("git")
assert _GIT_EXECUTABLE, "git must be on PATH to build the synthetic marker repo"

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
    }
)

#: The exact rollout this release stages, as one string. Pinned whole so that a
#: dropped name, an added name or a downgraded state all fail here.
#:
#: ADR-0019 (2026-08-15): `admin_portal` is deleted outright and
#: `voice_brain_dump`/`mobile_task_classification`/`external_agent_relay` are
#: now managed live through the admin portal's SQLite store, so none of them
#: is staged any more — `delivery_canary` is the only entry left (DD-14, DD-15).
AUTHORIZED_STAGED_FEATURE_FLAGS = "delivery_canary=internal"

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


ROOT_DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def test_ADR_0019_dockerignore_excludes_local_runtime_data() -> None:
    """`backend/data/` holds each service's local SQLite state, gitignored but
    still present on disk, and the backend Dockerfile's ``COPY backend /app``
    obeys only ``.dockerignore`` -- not ``.gitignore``. Without this exclusion
    the image bakes in a ``feature_flags.sqlite3`` with an already-applied
    migration ledger and OFF rows; a fresh named volume then seeds from that
    baked ``/app/data``, so ``BRAIN_BUDDY_FEATURE_FLAGS=...=on`` can never run
    its migration. The exclusion must cover the whole directory, not one
    filename -- the next store added under ``backend/data/`` would otherwise
    reopen this exact seam.
    """

    assert ROOT_DOCKERIGNORE.is_file(), ROOT_DOCKERIGNORE
    lines = {
        line.strip()
        for line in ROOT_DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    }
    assert "backend/data/" in lines, (
        "root .dockerignore must exclude the entire backend/data/ directory "
        "(a 'backend/data/' line), not just today's sqlite filenames"
    )


def test_009_FR_001_production_operators_come_from_the_dedicated_operator_secret(
    workflow_text: str,
) -> None:
    """PD-2 made concrete: a durable operator identity, not the smoke alias.

    The smoke admin identity (``BRAIN_BUDDY_ADMIN_EMAIL``) rotates with every
    deploy that changes it; aliasing the operator allow-list to it meant every
    production deploy silently overwrote the real operator with the smoke
    identity. The dedicated ``BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS`` secret is
    staged instead, and the alias must never reappear.
    """

    assert (
        'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS}"'
        in workflow_text
    )
    assert "secrets.BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS" in workflow_text
    assert (
        'BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS="${BRAIN_BUDDY_ADMIN_EMAIL}"'
        not in workflow_text
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


def test_010_DD_14_the_staged_string_never_names_admin_portal(
    workflow_text: str,
) -> None:
    """`admin_portal` is deleted outright (DD-14): the Admin Portal is always
    reachable by an authenticated, allow-listed operator (`require_operator`)
    and no flag — staged or otherwise — could hide it any more."""

    staged = _staged_flag_string(workflow_text)

    assert "admin_portal" not in staged
    with pytest.raises(ValueError, match="Unknown feature flag"):
        FeatureFlagSettings(
            states=_parse_feature_flag_states(f"{staged},admin_portal=internal")
        )


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
        migration_input=ManagedFlagMigrationInput(
            raw_states=_staged_flag_string(workflow_text),
            raw_internal_users=smoke,
        ),
    )
    seed = settings.load_managed_migration_seed()

    assert seed.states["external_agent_relay"] is FeatureFlagState.OFF


def test_009_FR_013_enabling_the_portal_is_documented_as_a_workflow_edit(
    workflow_text: str,
) -> None:
    """The rollback story depends on this being written where it is changed."""

    assert "Change the rollout here, not out of band." in workflow_text
    assert "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS=`" in workflow_text


# ---------------------------------------------------------------------------
# ADR-0019 first-transition seeding (BLOCKER 1): the first SQLite-aware boot
# must not lose a pre-migration rollout. These tests execute the exact bash
# and Python the deploy workflow ships — extracted from the real file, not
# reimplemented — against a stub `flyctl`, so a change to the shipped script
# is what is under test, not a paraphrase of it.
# ---------------------------------------------------------------------------

DETECT_FIRST_TRANSITION_STEP = "Detect the first SQLite-managed feature-flag transition"
STAGE_FIRST_TRANSITION_SEED_STEP = "Stage the first-transition feature-flag seed"
CLEANUP_FIRST_TRANSITION_STEP = (
    "Restage delivery-only rollout after a first-transition deploy"
)


@pytest.fixture(scope="module")
def validator() -> ModuleType:
    return _load_validator()


def _step_script(workflow_text: str, validator: ModuleType, step_name: str) -> str:
    """Reconstruct one step's exact ``run:`` shell script from the real YAML.

    Reuses the validator's own step-block extraction rather than a second
    YAML parser, then dedents the fixed 10-space ``run: |`` indentation this
    file uses throughout. What is returned is byte-for-byte what the Actions
    runner would execute.
    """

    block = validator._step_block(workflow_text, step_name)
    assert block is not None, f"missing step: {step_name!r} in the deploy workflow"
    marker = "        run: |\n"
    start = block.index(marker) + len(marker)
    lines: list[str] = []
    for line in block[start:].splitlines():
        if line == "":
            lines.append("")
        elif line.startswith(" " * 10):
            lines.append(line[10:])
        else:
            break
    return "\n".join(lines)


@pytest.fixture()
def fake_flyctl(tmp_path: Path) -> Path:
    """A stub ``flyctl`` that records every invocation's arguments and exits 0.

    Placed first on PATH so the extracted script's real ``flyctl secrets
    set --stage`` calls are observable without touching Fly.
    """

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_file = tmp_path / "flyctl_calls.txt"
    stub = bin_dir / "flyctl"
    stub.write_text(
        "#!/bin/sh\n" f'printf "%s\\n" "$*" >> "{calls_file}"\n' "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return bin_dir


def _run_step(
    script: str, *, env: dict[str, str], fake_flyctl: Path
) -> subprocess.CompletedProcess[str]:
    full_env = dict(os.environ)
    full_env.update(env)
    full_env["PATH"] = f"{fake_flyctl}:{full_env.get('PATH', '')}"
    # S603: this repository's own extracted workflow step is the script being
    # executed, not untrusted input.
    return subprocess.run(  # noqa: S603
        [_BASH_EXECUTABLE, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        env=full_env,
        check=False,
    )


def test_ADR_0019_first_transition_seed_retains_voice_brain_dump_and_drops_admin_portal(
    workflow_text: str, validator: ModuleType, fake_flyctl: Path, tmp_path: Path
) -> None:
    """The exact bug this contract exists to prevent: a bare
    ``delivery_canary=internal`` seed would lose ``voice_brain_dump=on`` from
    before ADR-0019. The retired ``admin_portal`` must not survive either."""

    script = _step_script(workflow_text, validator, STAGE_FIRST_TRANSITION_SEED_STEP)
    calls_file = tmp_path / "flyctl_calls.txt"
    result = _run_step(
        script,
        env={
            "BACKEND_APP": "brain-buddy-backend",
            "PREVIOUS_FEATURE_FLAGS": (
                "delivery_canary=internal,voice_brain_dump=on,admin_portal=internal"
            ),
        },
        fake_flyctl=fake_flyctl,
    )

    assert result.returncode == 0, result.stderr
    staged_call = calls_file.read_text(encoding="utf-8")
    assert (
        "BRAIN_BUDDY_FEATURE_FLAGS=delivery_canary=internal,voice_brain_dump=on"
        in staged_call
    )
    assert "admin_portal" not in staged_call


def test_ADR_0019_first_transition_seed_never_prints_the_rollout_outside_the_mask(
    workflow_text: str, validator: ModuleType, fake_flyctl: Path
) -> None:
    script = _step_script(workflow_text, validator, STAGE_FIRST_TRANSITION_SEED_STEP)
    result = _run_step(
        script,
        env={
            "BACKEND_APP": "brain-buddy-backend",
            "PREVIOUS_FEATURE_FLAGS": "delivery_canary=internal,voice_brain_dump=on",
        },
        fake_flyctl=fake_flyctl,
    )

    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stdout.splitlines() if "voice_brain_dump" in line]
    assert lines == ["::add-mask::delivery_canary=internal,voice_brain_dump=on"], (
        "the rollout must appear only on the mask-registration line; every "
        "other line — including the final success message — must stay "
        "value-free"
    )


def test_ADR_0019_first_transition_seed_fails_closed_on_a_malformed_entry(
    workflow_text: str, validator: ModuleType, fake_flyctl: Path, tmp_path: Path
) -> None:
    script = _step_script(workflow_text, validator, STAGE_FIRST_TRANSITION_SEED_STEP)
    calls_file = tmp_path / "flyctl_calls.txt"
    result = _run_step(
        script,
        env={
            "BACKEND_APP": "brain-buddy-backend",
            "PREVIOUS_FEATURE_FLAGS": "delivery_canary=internal,not_a_valid_entry",
        },
        fake_flyctl=fake_flyctl,
    )

    assert result.returncode != 0
    assert not calls_file.exists(), "a malformed seed must never reach flyctl"


def test_ADR_0019_first_transition_seed_fails_closed_when_delivery_canary_is_dropped(
    workflow_text: str, validator: ModuleType, fake_flyctl: Path, tmp_path: Path
) -> None:
    """If sanitizing leaves nothing the new image can parse as
    ``delivery_canary``, guessing one in would be exactly the silent loss of
    managed state this contract must refuse."""

    script = _step_script(workflow_text, validator, STAGE_FIRST_TRANSITION_SEED_STEP)
    calls_file = tmp_path / "flyctl_calls.txt"
    result = _run_step(
        script,
        env={
            "BACKEND_APP": "brain-buddy-backend",
            "PREVIOUS_FEATURE_FLAGS": "admin_portal=internal",
        },
        fake_flyctl=fake_flyctl,
    )

    assert result.returncode != 0
    assert not calls_file.exists()


def test_ADR_0019_later_deploy_cleanup_restages_delivery_only_without_a_second_deploy(
    workflow_text: str, validator: ModuleType, fake_flyctl: Path, tmp_path: Path
) -> None:
    script = _step_script(workflow_text, validator, CLEANUP_FIRST_TRANSITION_STEP)
    calls_file = tmp_path / "flyctl_calls.txt"
    result = _run_step(
        script,
        env={
            "BACKEND_APP": "brain-buddy-backend",
            "AUTHORIZED_STAGED_FEATURE_FLAGS": "delivery_canary=internal",
        },
        fake_flyctl=fake_flyctl,
    )

    assert result.returncode == 0, result.stderr
    calls = calls_file.read_text(encoding="utf-8")
    assert "BRAIN_BUDDY_FEATURE_FLAGS=delivery_canary=internal" in calls
    assert "secrets" in calls and "--stage" in calls
    assert "deploy" not in calls, "cleanup must only stage, never deploy a second image"


def test_ADR_0019_automatic_rollback_still_restages_the_exact_previous_string(
    workflow_text: str, validator: ModuleType, fake_flyctl: Path, tmp_path: Path
) -> None:
    """Unchanged by the first-transition seeding: rollback must keep restaging
    the literal captured ``PREVIOUS_FEATURE_FLAGS``, never a sanitized or
    guessed value."""

    script = _step_script(workflow_text, validator, validator.ROLLBACK_STEP)
    calls_file = tmp_path / "flyctl_calls.txt"
    result = _run_step(
        script,
        env={
            "BACKEND_APP": "brain-buddy-backend",
            "FRONTEND_APP": "brain-buddy-frontend",
            "PREVIOUS_FEATURE_FLAGS": (
                "delivery_canary=internal,voice_brain_dump=on,admin_portal=internal"
            ),
            "PREVIOUS_FRONTEND_IMAGE": "registry.fly.io/brain-buddy-frontend:previous",
            "PREVIOUS_BACKEND_IMAGE": "registry.fly.io/brain-buddy-backend:previous",
            "TESTED_SHA": "0" * 40,
        },
        fake_flyctl=fake_flyctl,
    )

    assert result.returncode == 0, result.stderr
    calls = calls_file.read_text(encoding="utf-8")
    assert (
        "BRAIN_BUDDY_FEATURE_FLAGS=delivery_canary=internal,voice_brain_dump=on,"
        "admin_portal=internal" in calls
    ), "the exact previous string — including the retired name — must be restaged verbatim"


def _write_marker_repo(tmp_path: Path, marker: str) -> tuple[Path, str, str, str]:
    """A tiny synthetic repo with a pre-transition, transition and later commit."""

    repo = tmp_path / "marker_repo"
    package = repo / "backend" / "app" / "repositories"
    package.mkdir(parents=True)
    flag_file = package / "feature_flag.py"

    def _commit(text: str, message: str) -> str:
        flag_file.write_text(text, encoding="utf-8")
        # S603: fixed args against the resolved local git executable, building this
        # test's own synthetic repository fixture.
        subprocess.run(  # noqa: S603
            [_GIT_EXECUTABLE, "add", "-A"], cwd=repo, check=True, capture_output=True
        )
        subprocess.run(  # noqa: S603
            [_GIT_EXECUTABLE, "commit", "-q", "-m", message],
            cwd=repo,
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@t.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@t.com",
            },
        )
        return subprocess.run(  # noqa: S603
            [_GIT_EXECUTABLE, "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    # S603: fixed args against the resolved local git executable, building this
    # test's own synthetic repository fixture.
    subprocess.run(  # noqa: S603
        [_GIT_EXECUTABLE, "init", "-q"], cwd=repo, check=True, capture_output=True
    )
    before_sha = _commit("no marker here\n", "before sqlite")
    transition_sha = _commit(f"{marker}\n", "sqlite transition")
    later_sha = _commit(f"{marker}\nfoo = 1\n", "ordinary later deploy")
    return repo, before_sha, transition_sha, later_sha


def test_ADR_0019_detection_uses_only_immutable_git_content(
    workflow_text: str, validator: ModuleType, tmp_path: Path
) -> None:
    """Proves the detect step against a real (synthetic) git history, not a
    paraphrase of the marker check: the transition commit reads true, the
    commit before it and the ordinary commit after it both read false."""

    script = _step_script(workflow_text, validator, DETECT_FIRST_TRANSITION_STEP)
    repo, before_sha, transition_sha, later_sha = _write_marker_repo(
        tmp_path, validator.FIRST_TRANSITION_MARKER
    )

    def _detect(sha: str) -> str:
        github_env = tmp_path / f"env-{sha}"
        github_env.write_text("", encoding="utf-8")
        # S603: this repository's own extracted workflow step is the script being
        # executed, not untrusted input.
        result = subprocess.run(  # noqa: S603
            [_BASH_EXECUTABLE, "-c", script],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "TESTED_SHA": sha, "GITHUB_ENV": str(github_env)},
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return github_env.read_text(encoding="utf-8").strip()

    assert _detect(transition_sha) == "FIRST_TRANSITION=true"
    assert _detect(before_sha) == "FIRST_TRANSITION=false"
    assert _detect(later_sha) == "FIRST_TRANSITION=false"
