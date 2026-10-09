"""Fail-closed deployment configuration for modern authentication."""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import SecretStr, ValidationError

from app.core.config import AppConfig, ModernAuthSettings, get_config


@pytest.fixture(autouse=True)
def isolated_auth_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[None]:
    for name in os.environ:
        if name.startswith("BRAIN_BUDDY_AUTH_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path / "data"))
    get_config.cache_clear()
    yield
    get_config.cache_clear()


def configured_values() -> dict[str, Any]:
    private_key = (
        ec.generate_private_key(ec.SECP256R1())
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode()
    )
    return {
        "public_origin": "https://app.example.com",
        "api_origin": "https://api.example.com",
        "current_key_id": "key-2",
        "keyring": {"key-2": SecretStr(base64.b64encode(b"2" * 32).decode())},
        "google_client_id": "web-client.apps.googleusercontent.com",
        "google_client_secret": SecretStr("synthetic-google-secret"),
        "apple_team_id": "TEAM123456",
        "apple_key_id": "KEY1234567",
        "apple_private_key": SecretStr(private_key),
        "apple_services_id": "com.example.web",
        "apple_native_app_id": "com.example.app",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_sender": "signin@example.com",
        "smtp_username": "synthetic-mail-user",
        "smtp_password": SecretStr("synthetic-mail-secret"),
        "smtp_tls": "starttls",
    }


def test_023_FR_003_missing_settings_leave_password_configuration_available() -> None:
    """Missing modern setup disables new methods and preserves password startup."""
    settings = get_config().modern_auth
    assert not settings.crypto_ready
    assert not settings.google_available
    assert not settings.apple_available
    assert not settings.email_available
    assert get_config().password_policy.min_length > 0
    assert AppConfig().modern_auth == ModernAuthSettings()


def test_023_FR_003_fully_configured_methods_and_distinct_apple_channels() -> None:
    """023-SC-008: direct provider configuration needs no auth SaaS credential.

    This checks the configuration/cost dependency only; live smoke and the
    complete required suite remain separate acceptance evidence.
    """
    values = configured_values()
    settings = ModernAuthSettings(**values)
    assert settings.crypto_ready
    assert settings.google_available and settings.email_available
    assert settings.apple_web_available and settings.apple_native_available
    values["apple_services_id"] = ""
    native_only = ModernAuthSettings(**values)
    assert native_only.apple_available and native_only.apple_native_available
    assert not native_only.apple_web_available
    values["apple_services_id"] = "com.example.web"
    values["apple_native_app_id"] = ""
    web_only = ModernAuthSettings(**values)
    assert web_only.apple_available and web_only.apple_web_available
    assert not web_only.apple_native_available


@pytest.mark.parametrize(
    "field,value",
    [
        ("public_origin", "http://app.example.com"),
        ("api_origin", "https://user:credential@api.example.com"),
        ("api_origin", "https://api.example.com/callback"),
        ("public_origin", "https://app.example.com?next=https://other.example.com"),
        ("public_origin", "https://app.example.com/#fragment"),
        ("public_origin", "https://*.example.com"),
        ("api_origin", "https://api.example.com:broken"),
        ("api_origin", "https://api.example.com:0"),
        ("public_origin", "https://app..example.com"),
        ("public_origin", "https://-app.example.com"),
        ("public_origin", "https://app.example.com\n"),
        ("current_key_id", "missing-key"),
        ("keyring", {"key-2": SecretStr("invalid-synthetic-key")}),
        ("keyring", {"key-2": SecretStr(base64.b64encode(b"short").decode())}),
        (
            "keyring",
            {
                "key-2": SecretStr(base64.b64encode(b"2" * 32).decode()),
                "old": SecretStr("invalid"),
            },
        ),
    ],
)
def test_023_FR_003_invalid_origins_or_keyring_disable_every_new_method(
    field: str, value: Any
) -> None:
    """Invalid fixed origins or any configured key fail closed without startup failure."""
    values = configured_values()
    values[field] = value
    settings = ModernAuthSettings(**values)
    assert not settings.google_available
    assert not settings.apple_available
    assert not settings.email_available


@pytest.mark.parametrize(
    "field,value,unavailable",
    [
        ("google_client_secret", "", "google_available"),
        ("apple_private_key", "synthetic-invalid-private-key", "apple_available"),
        ("apple_team_id", "bad", "apple_available"),
        ("smtp_port", "synthetic-invalid-port", "email_available"),
        ("smtp_tls", "none", "email_available"),
        ("smtp_sender", "address\r\nBcc: injected@example.com", "email_available"),
        ("smtp_host", "smtp.example.com\n", "email_available"),
        ("smtp_password", "", "email_available"),
    ],
)
def test_023_FR_003_invalid_provider_setup_only_hides_affected_method(
    field: str, value: Any, unavailable: str
) -> None:
    """Malformed optional credentials cannot disable unrelated configured methods."""
    values = configured_values()
    values[field] = value
    settings = ModernAuthSettings(**values)
    assert not getattr(settings, unavailable)
    assert settings.crypto_ready
    other = {"google_available", "apple_available", "email_available"} - {unavailable}
    assert all(getattr(settings, name) for name in other)


def test_023_FR_021_settings_are_frozen_and_secret_free_in_repr_and_dumps() -> None:
    """Settings expose safe metadata and omit secret fields from nested dumps."""
    settings = ModernAuthSettings(**configured_values())
    serialized = (
        repr(settings) + str(settings.model_dump()) + settings.model_dump_json()
    )
    serialized += AppConfig(modern_auth=settings).model_dump_json()
    for secret in (
        settings.google_client_secret,
        settings.apple_private_key,
        settings.smtp_password,
        *settings.keyring.values(),
    ):
        assert secret.get_secret_value() not in serialized
    assert "keyring" not in settings.model_dump()
    with pytest.raises(ValidationError) as error:
        settings.google_client_secret = SecretStr("new-sensitive-secret")
    assert "new-sensitive-secret" not in str(error.value)
    with pytest.raises(TypeError):
        settings.keyring["new"] = SecretStr("new-sensitive-secret")  # type: ignore[index]


def test_023_FR_023_environment_builder_reads_explicit_modern_auth_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit deployment environment names configure fixed origins and versioned keys."""
    values = configured_values()
    for name, value in values.items():
        if name == "keyring":
            value = json.dumps(
                {key: item.get_secret_value() for key, item in value.items()}
            )
        elif isinstance(value, SecretStr):
            value = value.get_secret_value()
        monkeypatch.setenv(f"BRAIN_BUDDY_AUTH_{name.upper()}", str(value))
    settings = get_config().modern_auth
    assert (
        settings.google_available
        and settings.apple_available
        and settings.email_available
    )
    assert settings.current_key_id == "key-2"
    assert settings.public_origin == values["public_origin"]


@pytest.mark.parametrize(
    "raw",
    [
        "synthetic-secret-not-json",
        '["synthetic-secret"]',
        '{"key-2": "synthetic-secret", "key-2": "other"}',
    ],
)
def test_023_FR_021_malformed_secret_environment_has_no_secret_validation_error(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    """Malformed secret inputs disable modern auth while get_config stays usable."""
    monkeypatch.setenv("BRAIN_BUDDY_AUTH_KEYRING", raw)
    monkeypatch.setenv("BRAIN_BUDDY_AUTH_SMTP_PORT", "synthetic-secret-invalid-port")
    settings = get_config().modern_auth
    assert not settings.crypto_ready
    assert not settings.email_available
    assert "synthetic-secret" not in repr(settings)
