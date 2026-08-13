"""Tests for the server-owned admin operator allow-list (009-FR-001)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.core.config import AdminSettings, get_config


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
