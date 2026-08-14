"""The server-owned operator allow-list and the private admin_portal flag.

009-FR-001 and 009-FR-013; the ids are on the individual tests so the
requirement-coverage gate tracks assertions rather than a module header.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.core.config import (
    ALL_FEATURE_FLAGS,
    KNOWN_FEATURE_FLAGS,
    AdminSettings,
    FeatureFlagSettings,
    FeatureFlagState,
    get_config,
)


@pytest.fixture(autouse=True)
def reset_config_cache() -> Generator[None, None, None]:
    get_config.cache_clear()  # type: ignore[attr-defined]
    yield
    get_config.cache_clear()  # type: ignore[attr-defined]


def test_009_FR_001_default_operator_allow_list_is_empty() -> None:
    """Fail closed: no operator is admitted unless explicitly configured."""

    settings = AdminSettings()
    assert settings.operator_emails == frozenset()


def test_009_FR_001_operator_emails_are_normalized() -> None:
    """Whitespace and casing collapse to one canonical lowercase form."""

    settings = AdminSettings(operator_emails=frozenset({" Ops@Example.com "}))
    assert settings.operator_emails == frozenset({"ops@example.com"})


def test_009_FR_001_a_non_email_operator_entry_fails_closed() -> None:
    """A malformed allow-list entry raises rather than silently admitting it."""

    with pytest.raises(ValueError, match="not an email address"):
        AdminSettings(operator_emails=frozenset({"not-an-email"}))


def test_009_FR_001_app_config_reads_the_operator_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS` populates `AppConfig.admin`."""

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv(
        "BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", "One@Example.com, two@example.com"
    )
    get_config.cache_clear()  # type: ignore[attr-defined]
    config = get_config()
    assert config.admin.operator_emails == frozenset(
        {"one@example.com", "two@example.com"}
    )
    monkeypatch.delenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", raising=False)


# ---------------------------------------------------------------------------
# 009-FR-013 — the private, default-OFF admin_portal rollout flag
# ---------------------------------------------------------------------------


def test_009_FR_013_admin_portal_is_a_configurable_flag_that_defaults_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BRAIN_BUDDY_FEATURE_FLAGS", raising=False)
    settings = FeatureFlagSettings()

    assert "admin_portal" in ALL_FEATURE_FLAGS
    assert (
        settings.private_flag_effective("admin_portal", "anyone@example.com") is False
    )


def test_009_FR_013_admin_portal_can_be_turned_on_through_the_flag_string() -> None:
    settings = FeatureFlagSettings(states={"admin_portal": FeatureFlagState.ON})

    assert settings.private_flag_effective("admin_portal", "op@example.com") is True


def test_009_FR_013_admin_portal_internal_stage_honors_the_internal_cohort() -> None:
    settings = FeatureFlagSettings(
        states={"admin_portal": FeatureFlagState.INTERNAL},
        internal_users=frozenset({"op@example.com"}),
    )

    assert settings.private_flag_effective("admin_portal", "op@example.com") is True
    assert settings.private_flag_effective("admin_portal", "other@example.com") is False


def test_009_FR_013_admin_portal_is_absent_from_the_member_facing_payload() -> None:
    """009-FR-010: adding it to KNOWN_FEATURE_FLAGS would change every member's
    `/api/auth/me` response shape and broadcast the rollout state."""

    settings = FeatureFlagSettings(states={"admin_portal": FeatureFlagState.ON})

    assert "admin_portal" not in settings.effective_flags("op@example.com")
    assert "admin_portal" not in KNOWN_FEATURE_FLAGS
    assert set(settings.effective_flags("op@example.com")) == set(KNOWN_FEATURE_FLAGS)


def test_009_FR_013_effective_flags_is_not_a_way_to_read_a_private_flag() -> None:
    settings = FeatureFlagSettings(states={"admin_portal": FeatureFlagState.ON})

    with pytest.raises(ValueError, match="not a private feature flag"):
        settings.private_flag_effective("voice_brain_dump", "op@example.com")


def test_009_FR_013_an_unknown_flag_name_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown feature flag"):
        FeatureFlagSettings(states={"admin_portal_v2": FeatureFlagState.ON})
