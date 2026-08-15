"""The server-owned operator allow-list (009-FR-001) and the ADR-0019
deletion of the `admin_portal` flag (DD-14, superseding 009-FR-013).

The ids are on the individual tests so the requirement-coverage gate tracks
assertions rather than a module header.
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
# DD-14 (2026-08-15, supersedes 009-FR-013) — `admin_portal` is deleted
# outright, not merely excluded: it is not a configurable flag name anywhere.
# ---------------------------------------------------------------------------


def test_010_DD_14_admin_portal_is_not_a_configurable_flag_name() -> None:
    """`admin_portal` does not exist in `ALL_FEATURE_FLAGS`/`KNOWN_FEATURE_FLAGS`
    at all — there is no flag left that could hide `/admin` behind it."""

    assert "admin_portal" not in ALL_FEATURE_FLAGS
    assert "admin_portal" not in KNOWN_FEATURE_FLAGS
    assert ALL_FEATURE_FLAGS == KNOWN_FEATURE_FLAGS


def test_010_DD_14_configuring_admin_portal_fails_closed_like_any_unknown_name() -> (
    None
):
    """Staging `admin_portal=on` fails application startup exactly like any
    other undeclared flag name — DD-14 gives it no distinct code path."""

    with pytest.raises(ValueError, match="Unknown feature flag"):
        FeatureFlagSettings(states={"admin_portal": FeatureFlagState.ON})


def test_010_DD_14_an_unknown_flag_name_still_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown feature flag"):
        FeatureFlagSettings(states={"admin_portal_v2": FeatureFlagState.ON})
