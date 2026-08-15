"""The runtime overlay resolver: fallback parity, per-flag overlay, refusals.

Requirement ids live on the individual tests below, deliberately **not** in
this docstring: `scripts/check_requirement_coverage.py` scans file text, so an
id parked in a module header reports covered while nothing asserts it.
"""

from __future__ import annotations

import itertools
import json
import logging
import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core.config import (
    ALL_FEATURE_FLAGS,
    KNOWN_FEATURE_FLAGS,
    PRIVATE_FEATURE_FLAGS,
    AppConfig,
    get_config,
)
from app.exceptions import ValidationFailure
from app.main import create_app
from app.repositories import SessionRepository, UserRepository
from app.repositories.feature_flag import (
    MANAGED_FLAGS,
    FeatureFlagOverrideRepository,
    FlagMode,
    FlagOverride,
)
from app.schemas.auth import Invite, User
from app.services import AdminService
from app.services.feature_flag_service import FeatureFlagService
from app.utils.time import utcnow

SERVICE_LOGGER = "app.services.feature_flag_service"

COHORT_EMAIL = "cohort@example.com"
OUTSIDER_EMAIL = "outsider@example.com"
PASSWORD = "correct-horse-battery-staple"

_CONSENT_BODY = {
    "consent": {
        "microphone": True,
        "external_processing_allowed": False,
        "provider": None,
        "language_hints": [],
        "vocabulary": [],
    }
}


@pytest.fixture(autouse=True)
def _reset_config_cache() -> Generator[None, None, None]:
    get_config.cache_clear()  # type: ignore[attr-defined]
    yield
    get_config.cache_clear()  # type: ignore[attr-defined]


def _config(
    monkeypatch: pytest.MonkeyPatch,
    data_dir: Path,
    *,
    flags: str,
    internal_users: str | None = None,
) -> AppConfig:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", flags)
    if internal_users is None:
        monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", raising=False)
    else:
        monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", internal_users)
    get_config.cache_clear()  # type: ignore[attr-defined]
    return get_config()


def _user(user_id: str, email: str) -> User:
    return User(
        id=user_id,
        email=email,
        password_hash="argon2-not-used-here",
        created_at=utcnow(),
    )


def _service(config: AppConfig, data_dir: Path) -> FeatureFlagService:
    user_repo = UserRepository(data_dir)
    return FeatureFlagService(
        repository=FeatureFlagOverrideRepository(data_dir),
        config=config,
        user_repo=user_repo,
        admin_service=AdminService(
            user_repo=user_repo,
            session_repo=SessionRepository(data_dir),
            operator_emails=frozenset(),
        ),
    )


# ---------------------------------------------------------------------------
# B1 — fallback parity with the environment-only implementation
# ---------------------------------------------------------------------------


def test_010_SC_003_no_runtime_document_matches_the_environment_answer_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no runtime document the overlay is invisible for every flag state."""

    states = ("off", "internal", "on")
    for index, combination in enumerate(
        itertools.product(states, repeat=len(KNOWN_FEATURE_FLAGS))
    ):
        data_dir = tmp_path / f"case-{index}"
        data_dir.mkdir()
        flags = ",".join(
            f"{name}={state}"
            for name, state in zip(KNOWN_FEATURE_FLAGS, combination, strict=True)
        )
        config = _config(
            monkeypatch, data_dir, flags=flags, internal_users=COHORT_EMAIL
        )
        service = _service(config, data_dir)
        for user in (
            _user("user_cohort", COHORT_EMAIL),
            _user("user_outsider", OUTSIDER_EMAIL),
        ):
            assert service.effective_flags(
                user
            ) == config.feature_flags.effective_flags(user.email), flags


def test_010_FR_008_unmanaged_flags_always_match_the_environment_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`delivery_canary`/`external_agent_relay` never gain a runtime entry."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags="delivery_canary=internal,external_agent_relay=on,voice_brain_dump=off",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")

    for user in (
        _user("user_cohort", COHORT_EMAIL),
        _user("user_outsider", OUTSIDER_EMAIL),
    ):
        resolved = service.effective_flags(user)
        environment = config.feature_flags.effective_flags(user.email)
        assert resolved["delivery_canary"] == environment["delivery_canary"]
        assert resolved["external_agent_relay"] == environment["external_agent_relay"]
        assert resolved["voice_brain_dump"] is True


def test_010_FR_003_key_set_is_exactly_known_feature_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resolver never adds or removes a key from the member-facing payload."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")

    assert set(service.effective_flags(_user("user_a", OUTSIDER_EMAIL))) == set(
        KNOWN_FEATURE_FLAGS
    )


# ---------------------------------------------------------------------------
# B2 — rollback equivalence (the pre-010 code path)
# ---------------------------------------------------------------------------


def test_010_SC_003_pre_010_evaluation_ignores_an_existing_runtime_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment-only path is inert to a document a newer build wrote."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags="voice_brain_dump=internal,mobile_task_classification=on",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")
    service.set_mode("mobile_task_classification", FlagMode.OFF, operator_id="user_op")

    outsider = _user("user_outsider", OUTSIDER_EMAIL)
    # `config.feature_flags.effective_flags` is the pre-010 code path verbatim:
    # it has no knowledge of the document, so it must neither read it nor raise.
    environment_only = config.feature_flags.effective_flags(outsider.email)

    assert environment_only == {
        "delivery_canary": False,
        "voice_brain_dump": False,
        "mobile_task_classification": True,
        "external_agent_relay": False,
    }
    assert service.effective_flags(outsider)["voice_brain_dump"] is True


# ---------------------------------------------------------------------------
# B3 — per-flag overlay, never a merge
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_003_runtime_off_beats_an_environment_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """A runtime OFF override is effective for nobody, whatever the baseline says."""

    config = _config(monkeypatch, tmp_path, flags=f"{flag}=on")
    service = _service(config, tmp_path)
    service.set_mode(flag, FlagMode.OFF, operator_id="user_op")

    assert service.effective_flags(_user("user_a", OUTSIDER_EMAIL))[flag] is False
    assert service.effective_flags(_user("user_b", COHORT_EMAIL))[flag] is False


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_003_runtime_on_beats_an_environment_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """A runtime ON override is effective for every authenticated user."""

    config = _config(monkeypatch, tmp_path, flags=f"{flag}=off")
    service = _service(config, tmp_path)
    service.set_mode(flag, FlagMode.ON, operator_id="user_op")

    assert service.effective_flags(_user("user_a", OUTSIDER_EMAIL))[flag] is True


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_007_selected_users_admits_exactly_the_stored_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """SELECTED_USERS admits its own IDs and nobody else, cohort user included."""

    config = _config(
        monkeypatch, tmp_path, flags=f"{flag}=internal", internal_users=COHORT_EMAIL
    )
    service = _service(config, tmp_path)
    service.set_mode(flag, FlagMode.SELECTED_USERS, operator_id="user_op")
    service.repository.mutate(
        lambda current: {
            **current,
            flag: FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_chosen",)
            ),
        }
    )

    assert service.effective_flags(_user("user_chosen", OUTSIDER_EMAIL))[flag] is True
    # In the environment INTERNAL cohort, but not in the runtime set: the
    # overlay answers alone and never blends the two sources.
    assert service.effective_flags(_user("user_cohort", COHORT_EMAIL))[flag] is False


@pytest.mark.parametrize("flag", MANAGED_FLAGS)
def test_010_FR_007_a_stored_id_belonging_to_no_account_grants_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """An ID in a set that belongs to no account makes the flag effective for nobody."""

    config = _config(monkeypatch, tmp_path, flags=f"{flag}=off")
    service = _service(config, tmp_path)
    service.repository.mutate(
        lambda current: {
            **current,
            flag: FlagOverride(
                mode=FlagMode.SELECTED_USERS, selected_users=("user_ghost",)
            ),
        }
    )

    assert service.effective_flags(_user("user_real", OUTSIDER_EMAIL))[flag] is False


# ---------------------------------------------------------------------------
# B4 — scope refusal
# ---------------------------------------------------------------------------


_REFUSED_FLAGS = (
    "admin_portal",
    "delivery_canary",
    "external_agent_relay",
    "not_a_flag_at_all",
)


@pytest.mark.parametrize("flag", _REFUSED_FLAGS)
def test_010_FR_002_every_mutation_refuses_an_unmanaged_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """Every mutation refuses a flag outside the two-flag managed set."""

    config = _config(monkeypatch, tmp_path, flags="admin_portal=on,delivery_canary=on")
    service = _service(config, tmp_path)

    with pytest.raises(ValidationFailure):
        service.set_mode(flag, FlagMode.ON, operator_id="user_op")
    with pytest.raises(ValidationFailure):
        service.clear_override(flag, operator_id="user_op")
    with pytest.raises(ValidationFailure):
        service.add_selected_user(flag, operator_id="user_op", account_id="user_a")
    with pytest.raises(ValidationFailure):
        service.remove_selected_user(flag, "user_a", operator_id="user_op")

    assert service.repository.document_path.exists() is False


def test_010_SC_006_a_refused_flag_keeps_its_environment_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused flag's effective value stays exactly the environment answer."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags="admin_portal=internal,delivery_canary=on,external_agent_relay=internal",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    for flag in _REFUSED_FLAGS:
        with pytest.raises(ValidationFailure):
            service.set_mode(flag, FlagMode.OFF, operator_id="user_op")

    cohort = _user("user_cohort", COHORT_EMAIL)
    resolved = service.effective_flags(cohort)
    environment = config.feature_flags.effective_flags(cohort.email)
    for name in KNOWN_FEATURE_FLAGS:
        assert resolved[name] == environment[name]
    for name in PRIVATE_FEATURE_FLAGS:
        assert config.feature_flags.private_flag_effective(name, cohort.email) is True
    assert set(ALL_FEATURE_FLAGS) == set(KNOWN_FEATURE_FLAGS) | set(
        PRIVATE_FEATURE_FLAGS
    )


def test_010_FR_002_an_unknown_mode_value_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mode outside the closed vocabulary is refused with no partial write."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)

    with pytest.raises(ValidationFailure):
        service.set_mode("voice_brain_dump", "sideways", operator_id="user_op")

    assert service.repository.document_path.exists() is False


# ---------------------------------------------------------------------------
# B5 — cohort retention across mode changes (DD-6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("inactive_mode", [FlagMode.OFF, FlagMode.ON])
def test_010_FR_005_a_cohort_survives_a_mode_change_and_is_restored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inactive_mode: FlagMode
) -> None:
    """A cohort is retained through OFF/ON and reactivated exactly on return."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )

    service.set_mode("voice_brain_dump", inactive_mode, operator_id="user_op")
    view = service.describe(operator_id="user_op")
    retained = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert [u.account_id for u in retained.selected_users] == ["user_chosen"]

    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    assert (
        service.effective_flags(_user("user_chosen", "chosen@example.com"))[
            "voice_brain_dump"
        ]
        is True
    )


@pytest.mark.parametrize("inactive_mode", [FlagMode.OFF, FlagMode.ON])
def test_010_FR_010_cohort_mutations_are_refused_outside_selected_users_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inactive_mode: FlagMode
) -> None:
    """Add and remove are accepted only while the flag's mode is SELECTED_USERS."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )
    service.set_mode("voice_brain_dump", inactive_mode, operator_id="user_op")
    before = service.repository.document_path.read_bytes()

    with pytest.raises(ValidationFailure):
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
        )
    with pytest.raises(ValidationFailure):
        service.remove_selected_user(
            "voice_brain_dump", "user_chosen", operator_id="user_op"
        )

    assert service.repository.document_path.read_bytes() == before


def test_010_FR_005_clearing_an_override_deletes_the_retained_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clearing deletes the whole entry, cohort included, unlike a mode change."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=internal")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )

    service.clear_override("voice_brain_dump", operator_id="user_op")

    view = service.describe(operator_id="user_op")
    cleared = next(f for f in view.flags if f.name == "voice_brain_dump")
    assert cleared.override_mode is None
    assert cleared.source == "deploy_default"
    assert cleared.deploy_default_state == "internal"
    assert cleared.selected_users == ()


# ---------------------------------------------------------------------------
# B6 — cache invalidation
# ---------------------------------------------------------------------------


def test_010_FR_005_a_mutation_is_visible_to_the_very_next_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No stale cache survives a mutation made through the service itself."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=on")
    service = _service(config, tmp_path)
    user = _user("user_a", OUTSIDER_EMAIL)
    assert service.effective_flags(user)["voice_brain_dump"] is True

    service.set_mode("voice_brain_dump", FlagMode.OFF, operator_id="user_op")

    assert service.effective_flags(user)["voice_brain_dump"] is False


def test_010_FR_005_a_document_replaced_underneath_the_service_is_picked_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-size replacement with a newer mtime is re-read, not served stale."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=off")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_aaa", "aaa@example.com")
    _seed_account(tmp_path, "user_bbb", "bbb@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_aaa"
    )
    user = _user("user_aaa", "aaa@example.com")
    assert service.effective_flags(user)["voice_brain_dump"] is True

    path = service.repository.document_path
    original = path.read_text(encoding="utf-8")
    document = json.loads(original)
    document["voice_brain_dump"]["selected_users"] = ["user_bbb"]
    replacement = json.dumps(document, indent=2, ensure_ascii=True) + "\n"
    # Same byte length, new modification time: a size-only cache key would
    # keep serving the stale answer forever.
    assert len(replacement) == len(original)
    stat_before = path.stat()
    path.write_text(replacement, encoding="utf-8")
    os.utime(path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns + 1_000_000))

    assert service.effective_flags(user)["voice_brain_dump"] is False


# ---------------------------------------------------------------------------
# B7 — degraded behaviour
# ---------------------------------------------------------------------------


def test_010_FR_004_degraded_falls_back_and_refuses_every_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A degraded document resolves from the baseline and refuses every write."""

    config = _config(
        monkeypatch,
        tmp_path,
        flags="voice_brain_dump=internal",
        internal_users=COHORT_EMAIL,
    )
    service = _service(config, tmp_path)
    path = service.repository.document_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    before = path.read_bytes()

    assert (
        service.effective_flags(_user("user_cohort", COHORT_EMAIL))["voice_brain_dump"]
        is True
    )
    assert (
        service.effective_flags(_user("user_out", OUTSIDER_EMAIL))["voice_brain_dump"]
        is False
    )
    assert service.describe(operator_id="user_op").degraded is True

    from app.repositories.feature_flag import DegradedRuntimeFlagsError

    with pytest.raises(DegradedRuntimeFlagsError):
        service.set_mode("voice_brain_dump", FlagMode.ON, operator_id="user_op")
    with pytest.raises(DegradedRuntimeFlagsError):
        service.clear_override("voice_brain_dump", operator_id="user_op")
    assert path.read_bytes() == before


def test_010_SC_008_an_absent_document_describes_as_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An absent document is healthy, not degraded (DD-2)."""

    config = _config(monkeypatch, tmp_path, flags="voice_brain_dump=on")
    service = _service(config, tmp_path)

    view = service.describe(operator_id="user_op")

    assert view.degraded is False
    assert [flag.name for flag in view.flags] == list(MANAGED_FLAGS)
    for flag in view.flags:
        assert flag.override_mode is None
        assert flag.source == "deploy_default"


def test_010_FR_006_describe_emits_exactly_one_aggregate_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One aggregate, content-free record per cohort-resolving read (DD-10)."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")
    service.add_selected_user(
        "voice_brain_dump", operator_id="user_op", account_id="user_chosen"
    )

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        service.describe(operator_id="user_op")

    records = [r for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operator=user_op" in message
    assert "flags=2" in message
    assert "resolved_accounts=1" in message
    assert "chosen@example.com" not in message


def test_010_FR_006_each_mutation_emits_exactly_one_content_free_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One dedicated record per mutation, naming the target account when there is one."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    _seed_account(tmp_path, "user_chosen", "chosen@example.com")

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        service.set_mode(
            "voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op"
        )
        service.add_selected_user(
            "voice_brain_dump", operator_id="user_op", email="chosen@example.com"
        )
        service.remove_selected_user(
            "voice_brain_dump", "user_chosen", operator_id="user_op"
        )
        service.clear_override("voice_brain_dump", operator_id="user_op")

    records = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER]
    assert len(records) == 4
    assert "action=set_mode" in records[0]
    assert "action=add_selected_user" in records[1]
    assert "account=user_chosen" in records[1]
    assert "action=remove_selected_user" in records[2]
    assert "account=user_chosen" in records[2]
    assert "action=clear_override" in records[3]
    for message in records:
        assert "operator=user_op" in message
        assert "outcome=" in message
        assert "chosen@example.com" not in message


def test_010_FR_006_a_removal_of_a_non_account_shaped_id_is_not_logged_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A removal target that is not account-ID shaped is redacted, never echoed."""

    config = _config(monkeypatch, tmp_path, flags="")
    service = _service(config, tmp_path)
    service.set_mode("voice_brain_dump", FlagMode.SELECTED_USERS, operator_id="user_op")

    caplog.clear()
    with caplog.at_level(logging.INFO, logger=SERVICE_LOGGER):
        service.remove_selected_user(
            "voice_brain_dump", "someone@example.com", operator_id="user_op"
        )

    message = [r.getMessage() for r in caplog.records if r.name == SERVICE_LOGGER][-1]
    assert "someone@example.com" not in message
    assert "account=-" in message


# ---------------------------------------------------------------------------
# Shared helper for account-backed cohorts
# ---------------------------------------------------------------------------


def _seed_account(data_dir: Path, user_id: str, email: str) -> User:
    repo = UserRepository(data_dir)
    user = User(
        id=user_id,
        email=email,
        password_hash="argon2-not-used-here",
        created_at=utcnow(),
    )
    repo.create(user)
    return user


# ---------------------------------------------------------------------------
# B8 / B8a — call-site coverage and the consent boundary, at the HTTP boundary
# ---------------------------------------------------------------------------


def _app_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
    flags: str,
    internal_users: str | None = None,
) -> tuple[TestClient, Container, dict]:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", flags)
    if internal_users is None:
        monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", raising=False)
    else:
        monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", internal_users)
    get_config.cache_clear()  # type: ignore[attr-defined]
    app = create_app()
    container: Container = app.state.container
    container.invite_repo.create(Invite(code="invite_flags", created_at=utcnow()))
    client = TestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "invite_code": "invite_flags"},
    )
    assert resp.status_code == 201, resp.text
    return client, container, resp.json()


def _override(container: Container, flag: str, entry: FlagOverride) -> None:
    container.feature_flag_repo.mutate(lambda current: {**current, flag: entry})


def test_010_FR_008_runtime_off_closes_every_voice_brain_dump_call_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runtime OFF override closes the capture gate and the command route."""

    client, container, me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=on"
    )
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["voice_brain_dump"] is True
    )

    _override(container, "voice_brain_dump", FlagOverride(mode=FlagMode.OFF))

    assert client.get("/api/brain-dump-providers").status_code == 404
    assert (
        client.post(
            "/api/brain-dump-operations",
            headers={"Idempotency-Key": "flag-start"},
            json=_CONSENT_BODY,
        ).status_code
        == 404
    )
    commanded = client.post(
        "/api/brain-dump-operations/does-not-exist/commit",
        headers={"Idempotency-Key": "flag-commit"},
        json={"expected_revision": 1},
    )
    assert commanded.status_code == 404
    assert "not available" in commanded.text.lower()
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["voice_brain_dump"] is False
    )
    assert me["feature_flags"]["voice_brain_dump"] is True


def test_010_FR_008_runtime_cohort_opens_every_voice_brain_dump_call_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SELECTED_USERS override naming the caller admits every gated call site."""

    client, container, me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    assert client.get("/api/brain-dump-providers").status_code == 404

    _override(
        container,
        "voice_brain_dump",
        FlagOverride(mode=FlagMode.SELECTED_USERS, selected_users=(me["id"],)),
    )

    assert client.get("/api/brain-dump-providers").status_code == 200
    started = client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "flag-start"},
        json=_CONSENT_BODY,
    )
    assert started.status_code == 201, started.text
    operation = started.json()
    commanded = client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "flag-commit"},
        json={"expected_revision": operation["revision"]},
    )
    # Admitted past the flag gate: the answer is now about the operation's own
    # state machine, never the fail-closed "not available" refusal.
    assert "not available" not in commanded.text.lower()
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["voice_brain_dump"] is True
    )


def test_010_FR_008_external_agent_relay_keeps_reading_the_environment_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`external_agent_relay` is untouched by the resolver and by any override."""

    from app.api.dependencies import external_agent_relay_enabled

    client, container, me = _app_client(
        tmp_path,
        monkeypatch,
        email=OUTSIDER_EMAIL,
        flags="external_agent_relay=on,voice_brain_dump=off",
    )
    _override(container, "voice_brain_dump", FlagOverride(mode=FlagMode.ON))
    # A runtime entry for an unmanaged flag can only be planted by bypassing the
    # repository's own managed-flag reconciliation, and even then it is ignored.
    container.feature_flag_repo.document_path.write_text(
        json.dumps({"external_agent_relay": {"mode": "off"}}, indent=2) + "\n",
        encoding="utf-8",
    )

    config = container.feature_flag_service.config
    user = container.user_repo.get_by_id(me["id"])
    assert user is not None
    assert external_agent_relay_enabled(user, config) is True
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["external_agent_relay"]
        is True
    )


def test_010_FR_008_a_cohort_admission_does_not_move_the_consent_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A newly admitted caller still fails visibly without per-recording consent."""

    client, container, me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=off"
    )
    _override(
        container,
        "voice_brain_dump",
        FlagOverride(mode=FlagMode.SELECTED_USERS, selected_users=(me["id"],)),
    )

    refused = client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "no-consent"},
        json={
            "consent": {
                "microphone": False,
                "external_processing_allowed": False,
                "provider": None,
                "language_hints": [],
                "vocabulary": [],
            }
        },
    )

    assert refused.status_code == 400, refused.text
    assert "consent" in refused.text.lower()


def test_010_FR_008_a_runtime_off_override_keeps_owner_authority_routes_reachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Withdraw/cancel/delete stay reachable under a runtime OFF override."""

    client, container, _me = _app_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="voice_brain_dump=on"
    )
    started = client.post(
        "/api/brain-dump-operations",
        headers={"Idempotency-Key": "authority-start"},
        json=_CONSENT_BODY,
    )
    assert started.status_code == 201, started.text
    operation = started.json()

    _override(container, "voice_brain_dump", FlagOverride(mode=FlagMode.OFF))

    cancelled = client.post(
        f"/api/brain-dump-operations/{operation['id']}/cancel",
        headers={"Idempotency-Key": "authority-cancel"},
        json={"expected_revision": operation["revision"]},
    )
    assert cancelled.status_code == 200, cancelled.text
    blocked = client.post(
        f"/api/brain-dump-operations/{operation['id']}/commit",
        headers={"Idempotency-Key": "authority-commit"},
        json={"expected_revision": cancelled.json()["revision"]},
    )
    assert blocked.status_code == 404
    assert "not available" in blocked.text.lower()
