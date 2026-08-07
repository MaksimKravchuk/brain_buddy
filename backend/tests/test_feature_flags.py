"""Tests for server-owned, allow-listed, fail-closed feature flags."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core.config import (
    KNOWN_FEATURE_FLAGS,
    FeatureFlagSettings,
    FeatureFlagState,
    get_config,
)
from app.main import create_app
from app.schemas.auth import Invite
from app.utils.time import utcnow

INTERNAL_EMAIL = "cohort-member@example.com"
OUTSIDER_EMAIL = "outsider@example.com"
PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def reset_config_cache() -> Generator[None, None, None]:
    """Ensure configuration cache is cleared between tests."""

    get_config.cache_clear()  # type: ignore[attr-defined]
    yield
    get_config.cache_clear()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Typed settings model
# ---------------------------------------------------------------------------


def test_registry_declares_at_least_one_allow_listed_flag() -> None:
    """The allow-list is explicit and non-empty so rollout is testable."""

    assert KNOWN_FEATURE_FLAGS
    assert "delivery_canary" in KNOWN_FEATURE_FLAGS


def test_default_settings_turn_every_known_flag_off() -> None:
    """All declared flags default OFF with an empty internal cohort."""

    settings = FeatureFlagSettings()
    assert set(settings.states) == set(KNOWN_FEATURE_FLAGS)
    assert all(state is FeatureFlagState.OFF for state in settings.states.values())
    assert settings.internal_users == frozenset()


def test_partial_states_fill_missing_flags_as_off() -> None:
    """A configured subset leaves every other known flag OFF."""

    settings = FeatureFlagSettings(states={"delivery_canary": FeatureFlagState.ON})
    assert settings.states["delivery_canary"] is FeatureFlagState.ON
    for name in KNOWN_FEATURE_FLAGS:
        if name != "delivery_canary":
            assert settings.states[name] is FeatureFlagState.OFF


def test_unknown_flag_name_fails_closed() -> None:
    """A flag outside the allow-list is a configuration error."""

    with pytest.raises(ValueError, match="not_a_known_flag"):
        FeatureFlagSettings(states={"not_a_known_flag": FeatureFlagState.ON})


def test_invalid_state_value_fails_closed() -> None:
    """A state outside off/internal/on is rejected."""

    with pytest.raises(ValueError):
        FeatureFlagSettings(states={"delivery_canary": "maybe"})


def test_internal_users_are_normalized_lowercase() -> None:
    """Cohort emails compare case-insensitively."""

    settings = FeatureFlagSettings(internal_users=frozenset({"Dev@Example.COM"}))
    assert settings.internal_users == frozenset({"dev@example.com"})


def test_internal_user_without_at_sign_fails_closed() -> None:
    """A cohort entry that is not email-shaped is a configuration error."""

    with pytest.raises(ValueError, match="not-an-email"):
        FeatureFlagSettings(internal_users=frozenset({"not-an-email"}))


def test_settings_are_frozen() -> None:
    """The settings model is immutable like the rest of the config."""

    settings = FeatureFlagSettings()
    with pytest.raises(ValueError, match="frozen"):
        settings.internal_users = frozenset()  # type: ignore[misc]


def test_states_mapping_rejects_item_mutation() -> None:
    """states is genuinely read-only: item assignment/deletion must fail."""

    settings = FeatureFlagSettings()
    with pytest.raises(TypeError):
        settings.states["delivery_canary"] = FeatureFlagState.ON  # type: ignore[index]
    with pytest.raises(TypeError):
        del settings.states["delivery_canary"]  # type: ignore[attr-defined]
    assert settings.effective_flags(OUTSIDER_EMAIL)["delivery_canary"] is False


def test_states_are_decoupled_from_the_constructor_input() -> None:
    """Mutating the mapping passed in cannot change validated settings."""

    raw = {"delivery_canary": FeatureFlagState.ON}
    settings = FeatureFlagSettings(states=raw)
    raw["delivery_canary"] = FeatureFlagState.OFF
    assert settings.states["delivery_canary"] is FeatureFlagState.ON


# ---------------------------------------------------------------------------
# Effective flag evaluation
# ---------------------------------------------------------------------------


def test_off_flag_is_disabled_for_everyone() -> None:
    settings = FeatureFlagSettings(
        states={"delivery_canary": FeatureFlagState.OFF},
        internal_users=frozenset({INTERNAL_EMAIL}),
    )
    assert settings.effective_flags(INTERNAL_EMAIL)["delivery_canary"] is False
    assert settings.effective_flags(OUTSIDER_EMAIL)["delivery_canary"] is False


def test_on_flag_is_enabled_for_every_authenticated_user() -> None:
    settings = FeatureFlagSettings(states={"delivery_canary": FeatureFlagState.ON})
    assert settings.effective_flags(OUTSIDER_EMAIL)["delivery_canary"] is True


def test_internal_flag_is_enabled_only_for_the_cohort() -> None:
    settings = FeatureFlagSettings(
        states={"delivery_canary": FeatureFlagState.INTERNAL},
        internal_users=frozenset({INTERNAL_EMAIL}),
    )
    assert settings.effective_flags(INTERNAL_EMAIL)["delivery_canary"] is True
    assert settings.effective_flags(INTERNAL_EMAIL.upper())["delivery_canary"] is True
    assert settings.effective_flags(OUTSIDER_EMAIL)["delivery_canary"] is False


def test_internal_flag_is_disabled_for_missing_or_blank_email() -> None:
    settings = FeatureFlagSettings(
        states={"delivery_canary": FeatureFlagState.INTERNAL},
        internal_users=frozenset({INTERNAL_EMAIL}),
    )
    assert settings.effective_flags(None)["delivery_canary"] is False
    assert settings.effective_flags("  ")["delivery_canary"] is False


def test_effective_flags_cover_every_known_flag() -> None:
    """The payload always contains every allow-listed flag, no more, no less."""

    settings = FeatureFlagSettings()
    effective = settings.effective_flags(OUTSIDER_EMAIL)
    assert set(effective) == set(KNOWN_FEATURE_FLAGS)
    assert all(isinstance(value, bool) for value in effective.values())


# ---------------------------------------------------------------------------
# Environment parsing (fail closed on invalid configuration)
# ---------------------------------------------------------------------------


def _configure_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    flags: str | None = None,
    internal_users: str | None = None,
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    for name, value in (
        ("BRAIN_BUDDY_FEATURE_FLAGS", flags),
        ("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", internal_users),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    get_config.cache_clear()  # type: ignore[attr-defined]


def test_env_defaults_to_all_flags_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(monkeypatch, tmp_path)
    config = get_config()
    assert all(
        state is FeatureFlagState.OFF for state in config.feature_flags.states.values()
    )
    assert config.feature_flags.internal_users == frozenset()


def test_env_parses_states_and_internal_cohort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(
        monkeypatch,
        tmp_path,
        flags=" delivery_canary = internal ",
        internal_users=f" {INTERNAL_EMAIL.upper()} , ",
    )
    config = get_config()
    assert config.feature_flags.states["delivery_canary"] is FeatureFlagState.INTERNAL
    assert config.feature_flags.internal_users == frozenset({INTERNAL_EMAIL})


def test_env_empty_string_means_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(monkeypatch, tmp_path, flags="", internal_users="")
    config = get_config()
    assert all(
        state is FeatureFlagState.OFF for state in config.feature_flags.states.values()
    )
    assert config.feature_flags.internal_users == frozenset()


@pytest.mark.parametrize(
    "raw",
    [
        "delivery_canary",
        "delivery_canary=maybe",
        "unknown_flag=on",
        "delivery_canary=on,delivery_canary=off",
        "=on",
    ],
)
def test_env_invalid_flag_configuration_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Startup fails loudly instead of guessing at invalid flag config."""

    _configure_env(monkeypatch, tmp_path, flags=raw)
    with pytest.raises(ValueError):
        get_config()


def test_env_invalid_internal_user_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_env(monkeypatch, tmp_path, internal_users="not-an-email")
    with pytest.raises(ValueError):
        get_config()


# ---------------------------------------------------------------------------
# Authenticated exposure via /api/auth endpoints
# ---------------------------------------------------------------------------


def _signed_up_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    email: str,
    flags: str | None = None,
    internal_users: str | None = None,
) -> TestClient:
    _configure_env(monkeypatch, tmp_path, flags=flags, internal_users=internal_users)
    app = create_app()
    container: Container = app.state.container
    invite_code = f"invite_{email.split('@', 1)[0]}"
    container.invite_repo.create(Invite(code=invite_code, created_at=utcnow()))
    client = TestClient(app)
    resp = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "invite_code": invite_code},
    )
    assert resp.status_code == 201, resp.text
    return client


def test_me_includes_default_off_flag_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An authenticated user sees every allow-listed flag, all defaulting off."""

    client = _signed_up_client(tmp_path, monkeypatch, email=OUTSIDER_EMAIL)
    body = client.get("/api/auth/me").json()
    assert body["feature_flags"] == {name: False for name in KNOWN_FEATURE_FLAGS}


def test_signup_and_login_payloads_include_feature_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path, monkeypatch, email=OUTSIDER_EMAIL, flags="delivery_canary=on"
    )
    login = client.post(
        "/api/auth/login", json={"email": OUTSIDER_EMAIL, "password": PASSWORD}
    )
    assert login.status_code == 200
    assert login.json()["feature_flags"]["delivery_canary"] is True


def test_internal_rollout_is_visible_only_to_cohort_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path,
        monkeypatch,
        email=INTERNAL_EMAIL,
        flags="delivery_canary=internal",
        internal_users=INTERNAL_EMAIL,
    )
    assert client.get("/api/auth/me").json()["feature_flags"]["delivery_canary"] is True


def test_internal_rollout_is_hidden_from_non_cohort_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _signed_up_client(
        tmp_path,
        monkeypatch,
        email=OUTSIDER_EMAIL,
        flags="delivery_canary=internal",
        internal_users=INTERNAL_EMAIL,
    )
    assert (
        client.get("/api/auth/me").json()["feature_flags"]["delivery_canary"] is False
    )


def test_me_payload_never_leaks_cohort_or_rollout_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only effective booleans are exposed — no stages, no cohort membership."""

    client = _signed_up_client(
        tmp_path,
        monkeypatch,
        email=OUTSIDER_EMAIL,
        flags="delivery_canary=internal",
        internal_users=INTERNAL_EMAIL,
    )
    resp = client.get("/api/auth/me")
    body = resp.json()
    assert set(body) == {
        "id",
        "email",
        "display_name",
        "deletion_cancelled",
        "feature_flags",
    }
    assert all(isinstance(value, bool) for value in body["feature_flags"].values())
    assert INTERNAL_EMAIL not in resp.text
    assert "internal" not in resp.text.lower()


def test_unauthenticated_me_stays_401_without_flag_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Flags are only exposed to an authenticated session."""

    _configure_env(monkeypatch, tmp_path, flags="delivery_canary=on")
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert "feature_flags" not in resp.text
