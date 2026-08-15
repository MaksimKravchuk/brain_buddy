"""Tests for server-owned, allow-listed, fail-closed feature flags."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import allure
import pytest
from fastapi.testclient import TestClient

from app.container import Container
from app.core.config import (
    ALL_FEATURE_FLAGS,
    ENVIRONMENT_OWNED_FLAGS,
    KNOWN_FEATURE_FLAGS,
    RUNTIME_MANAGED_FLAGS,
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

# Feature 006 (mobile task classification) gates its exposure on this flag.
MOBILE_CLASSIFICATION_FLAG = "mobile_task_classification"


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


def test_010_DD_15_runtime_states_hold_only_the_environment_owned_flag() -> None:
    """Single authority (DD-15): this configuration is not a second answer.

    Three properties, because a managed flag can leak back into runtime
    configuration three ways: by being materialized as a default state, by an
    aggregate resolver projecting it, or by being accepted from a caller. All
    three must be structurally impossible, not merely unused — an unused
    second source of truth is still a source of truth the next call site can
    reach for (ADR-0019, DD-15).
    """

    settings = FeatureFlagSettings()

    assert set(settings.states) == set(ENVIRONMENT_OWNED_FLAGS) == {"delivery_canary"}
    assert settings.states["delivery_canary"] is FeatureFlagState.OFF
    assert not hasattr(FeatureFlagSettings, "effective_flags")
    with pytest.raises(ValueError, match="managed"):
        FeatureFlagSettings(states={"voice_brain_dump": FeatureFlagState.ON})


def test_default_settings_turn_every_known_flag_off() -> None:
    """All declared flags default OFF with an empty internal cohort.

    One product promise, now enforced in the two places ADR-0019 split it
    between: the runtime state map for `delivery_canary`, and the migration
    seed the SQLite store is populated from for the other three (DD-15). The
    union is still exactly `ALL_FEATURE_FLAGS`, so no flag has fallen between
    the two halves and lost its default.
    """

    settings = FeatureFlagSettings()
    assert set(settings.states) == set(ENVIRONMENT_OWNED_FLAGS)
    assert all(state is FeatureFlagState.OFF for state in settings.states.values())
    assert settings.internal_users == frozenset()

    seed = settings.load_managed_migration_seed()
    assert set(seed.states) == set(RUNTIME_MANAGED_FLAGS)
    assert all(state is FeatureFlagState.OFF for state in seed.states.values())
    assert set(settings.states) | set(seed.states) == set(ALL_FEATURE_FLAGS)


def test_partial_states_fill_missing_flags_as_off() -> None:
    """A configured subset leaves every other environment-owned flag OFF — and
    materializes no key at all for a flag this configuration does not own."""

    settings = FeatureFlagSettings(states={"delivery_canary": FeatureFlagState.ON})
    assert settings.states["delivery_canary"] is FeatureFlagState.ON
    for name in ENVIRONMENT_OWNED_FLAGS:
        if name != "delivery_canary":
            assert settings.states[name] is FeatureFlagState.OFF
    assert set(settings.states).isdisjoint(RUNTIME_MANAGED_FLAGS)


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
    assert settings.delivery_canary_effective(OUTSIDER_EMAIL) is False


def test_states_are_decoupled_from_the_constructor_input() -> None:
    """Mutating the mapping passed in cannot change validated settings."""

    raw = {"delivery_canary": FeatureFlagState.ON}
    settings = FeatureFlagSettings(states=raw)
    raw["delivery_canary"] = FeatureFlagState.OFF
    assert settings.states["delivery_canary"] is FeatureFlagState.ON


# ---------------------------------------------------------------------------
# Effective flag evaluation — `delivery_canary_effective` is the whole resolver
# API this configuration has left (DD-15). The `KNOWN_FEATURE_FLAGS`-shaped
# payload the retired aggregate resolver used to build is now assembled by
# `FeatureFlagService.effective_flags`, and its key set and boolean shape are
# asserted where they are produced: `test_feature_flag_service.py::
# test_010_FR_003_key_set_is_exactly_known_feature_flags`, and
# `test_me_includes_default_off_flag_payload` at the bottom of this module.
# ---------------------------------------------------------------------------


def test_off_flag_is_disabled_for_everyone() -> None:
    settings = FeatureFlagSettings(
        states={"delivery_canary": FeatureFlagState.OFF},
        internal_users=frozenset({INTERNAL_EMAIL}),
    )
    assert settings.delivery_canary_effective(INTERNAL_EMAIL) is False
    assert settings.delivery_canary_effective(OUTSIDER_EMAIL) is False


def test_on_flag_is_enabled_for_every_authenticated_user() -> None:
    settings = FeatureFlagSettings(states={"delivery_canary": FeatureFlagState.ON})
    assert settings.delivery_canary_effective(OUTSIDER_EMAIL) is True


def test_internal_flag_is_enabled_only_for_the_cohort() -> None:
    settings = FeatureFlagSettings(
        states={"delivery_canary": FeatureFlagState.INTERNAL},
        internal_users=frozenset({INTERNAL_EMAIL}),
    )
    assert settings.delivery_canary_effective(INTERNAL_EMAIL) is True
    assert settings.delivery_canary_effective(INTERNAL_EMAIL.upper()) is True
    assert settings.delivery_canary_effective(OUTSIDER_EMAIL) is False


def test_internal_flag_is_disabled_for_missing_or_blank_email() -> None:
    settings = FeatureFlagSettings(
        states={"delivery_canary": FeatureFlagState.INTERNAL},
        internal_users=frozenset({INTERNAL_EMAIL}),
    )
    assert settings.delivery_canary_effective(None) is False
    assert settings.delivery_canary_effective("  ") is False


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
        "delivery_canary=on,delivery_canary=off",
    ],
)
def test_env_invalid_flag_configuration_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Startup fails loudly instead of guessing at invalid flag config.

    Narrowed by the ADR-0019 correction (2026-08-15) to the one flag this
    configuration still owns at runtime: an invalid `delivery_canary` entry
    is a startup failure exactly as before. Managed-flag, unknown and
    anonymous entries moved to the migration-only loader below (DD-15) —
    they are no longer parsed when the app boots.
    """

    _configure_env(monkeypatch, tmp_path, flags=raw)
    with pytest.raises(ValueError):
        get_config()


def test_env_invalid_internal_user_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed cohort entry fails startup when `delivery_canary=internal`
    is the setting that actually consults it at runtime (DD-15)."""

    _configure_env(
        monkeypatch,
        tmp_path,
        flags="delivery_canary=internal",
        internal_users="not-an-email",
    )
    with pytest.raises(ValueError):
        get_config()


# ---------------------------------------------------------------------------
# ADR-0019 correction (2026-08-15), DD-15: the deploy-staged environment input
# for the three *managed* flags is migration-only. It is preserved raw at
# configuration construction and parsed exactly once, inside the serialized
# first-migration path, so a stale or malformed managed entry can never block
# startup of an already-migrated deployment. `delivery_canary` is unaffected:
# it stays environment-owned and is validated normally, above.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "voice_brain_dump=sideways",
        "unknown_flag=on",
        "=on",
        "voice_brain_dump=on,voice_brain_dump=off",
        "mobile_task_classification",
    ],
)
def test_010_FR_003_an_invalid_managed_flag_entry_no_longer_blocks_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """A managed-flag entry is never parsed at configuration construction, so
    a malformed, unknown or duplicated one cannot fail an already-migrated
    deployment's startup (DD-15)."""

    _configure_env(monkeypatch, tmp_path, flags=raw)

    config = get_config()

    assert config.feature_flags.states["delivery_canary"] is FeatureFlagState.OFF


def test_010_FR_003_a_managed_entry_never_reaches_the_runtime_state_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a *well-formed* managed entry is inert at runtime: SQLite is the
    sole source of truth for those three flags after migration (DD-15).

    Absent from the map, not merely OFF in it: an OFF entry is still an answer
    this configuration could hand to a call site that disagrees with the store.
    """

    _configure_env(monkeypatch, tmp_path, flags="voice_brain_dump=on")

    states = get_config().feature_flags.states

    assert "voice_brain_dump" not in states
    assert states["delivery_canary"] is FeatureFlagState.OFF


def test_010_FR_003_delivery_canary_still_parses_alongside_a_broken_managed_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`delivery_canary` keeps resolving normally even when a managed entry in
    the same variable is malformed."""

    _configure_env(
        monkeypatch,
        tmp_path,
        flags="voice_brain_dump=sideways,delivery_canary=on",
    )

    assert get_config().feature_flags.states["delivery_canary"] is FeatureFlagState.ON


def test_010_DD_15_the_migration_seed_loader_parses_the_managed_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The migration-only loader is where managed entries are finally read."""

    _configure_env(
        monkeypatch,
        tmp_path,
        flags="voice_brain_dump=on,mobile_task_classification=internal",
        internal_users=INTERNAL_EMAIL.upper(),
    )

    seed = get_config().feature_flags.load_managed_migration_seed()

    assert seed.states["voice_brain_dump"] is FeatureFlagState.ON
    assert seed.states["mobile_task_classification"] is FeatureFlagState.INTERNAL
    assert seed.states["external_agent_relay"] is FeatureFlagState.OFF
    assert seed.internal_users == frozenset({INTERNAL_EMAIL})


def test_010_DD_15_the_migration_seed_covers_exactly_the_managed_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seed is the migration's whole input, so its key set is a contract.

    Exactly the three SQLite-owned flags, every one present so the migration
    seeds a row for each with an explicit default rather than an absence, and
    `delivery_canary` absent even though it is staged in the very same
    variable: it stays environment-owned, and a seeded row for it would be the
    second answer this split exists to prevent (DD-15).
    """

    _configure_env(
        monkeypatch,
        tmp_path,
        flags="delivery_canary=on,voice_brain_dump=internal",
        internal_users=INTERNAL_EMAIL,
    )

    seed = get_config().feature_flags.load_managed_migration_seed()

    assert set(seed.states) == set(RUNTIME_MANAGED_FLAGS)
    assert "delivery_canary" not in seed.states
    assert seed.states["voice_brain_dump"] is FeatureFlagState.INTERNAL
    assert seed.states["mobile_task_classification"] is FeatureFlagState.OFF


@pytest.mark.parametrize(
    "raw",
    [
        "voice_brain_dump=sideways",
        "unknown_flag=on",
        "=on",
        "voice_brain_dump=on,voice_brain_dump=off",
        "mobile_task_classification",
    ],
)
def test_010_DD_15_the_migration_seed_loader_fails_closed_on_invalid_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Deferring the parse does not weaken it: every entry the pre-correction
    startup rejected is still rejected, just at the migration boundary."""

    _configure_env(monkeypatch, tmp_path, flags=raw)
    config = get_config()

    with pytest.raises(ValueError):
        config.feature_flags.load_managed_migration_seed()


def test_010_DD_15_the_migration_seed_loader_fails_closed_on_a_cohort_email(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS` follows the same rule: not
    validated at startup, still validated before it can seed a cohort."""

    _configure_env(monkeypatch, tmp_path, internal_users="not-an-email")
    config = get_config()

    assert config.feature_flags.internal_users == frozenset()
    with pytest.raises(ValueError):
        config.feature_flags.load_managed_migration_seed()


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
    assert body["feature_flags"] == dict.fromkeys(KNOWN_FEATURE_FLAGS, False)


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


# ---------------------------------------------------------------------------
# Feature 006 — mobile task classification rollout flag
# ---------------------------------------------------------------------------


@allure.story("006-FR-015 mobile task classification rollout flag")
def test_006_FR_015_mobile_classification_flag_defaults_off_in_me_response(
    api_client: TestClient,
) -> None:
    """006-FR-015: the mobile classification flag ships OFF and reaches /auth/me.

    Default OFF is what makes the mobile task screen render exactly today's
    presentation until the flag is deliberately turned on. Asserted at both
    ends: the typed configuration, and the only channel the mobile client can
    read the flag through.

    ADR-0019 moved the configuration end from the runtime state map to the
    migration seed — this flag is SQLite-managed now, so the default it ships
    with is the row the store is seeded with, not a state this config holds.
    """

    assert MOBILE_CLASSIFICATION_FLAG in KNOWN_FEATURE_FLAGS
    assert MOBILE_CLASSIFICATION_FLAG in RUNTIME_MANAGED_FLAGS
    assert (
        FeatureFlagSettings()
        .load_managed_migration_seed()
        .states[MOBILE_CLASSIFICATION_FLAG]
        is FeatureFlagState.OFF
    )

    with allure.step("GET /api/auth/me delivers the flag, resolved off"):
        body = api_client.get("/api/auth/me").json()
        flags = body["feature_flags"]
        # Delivered, not merely absent-and-therefore-falsy on the client: a
        # missing key and an explicit ``false`` are indistinguishable to a
        # client that reads ``=== true``, and only one of them proves the
        # rollout channel works.
        assert set(flags) == set(KNOWN_FEATURE_FLAGS)
        assert flags[MOBILE_CLASSIFICATION_FLAG] is False


@allure.story("006-FR-015 mobile task classification rollout flag")
def test_006_FR_015_mobile_classification_flag_is_exposed_once_rolled_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """006-FR-015: turning the flag on exposes it to the authenticated user.

    Without this the default-off assertion above would also pass for a name
    that is merely allow-listed and wired to nothing.
    """

    client = _signed_up_client(
        tmp_path,
        monkeypatch,
        email=OUTSIDER_EMAIL,
        flags=f"{MOBILE_CLASSIFICATION_FLAG}=on",
    )
    with allure.step("GET /api/auth/me after the flag is rolled out"):
        flags = client.get("/api/auth/me").json()["feature_flags"]
        assert flags[MOBILE_CLASSIFICATION_FLAG] is True
        # Exposure only: other flags are untouched by this one's rollout.
        assert flags["delivery_canary"] is False
