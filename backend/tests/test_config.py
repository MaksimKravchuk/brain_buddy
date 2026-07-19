"""Tests for application configuration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.container import _build_accurate_stt
from app.core.config import DEFAULT_SCHEMA_VERSION, get_config
from app.workflows.voice_brain_dump.providers import DisabledAccurateStt


@pytest.fixture(autouse=True)
def reset_config_cache() -> None:
    """Ensure configuration cache is cleared between tests."""

    get_config.cache_clear()  # type: ignore[attr-defined]
    yield
    get_config.cache_clear()  # type: ignore[attr-defined]


def test_get_config_uses_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_LOG_LEVEL", "debug")
    monkeypatch.setenv("BRAIN_BUDDY_API_PREFIX", "/custom")

    schema_file = tmp_path / "schema_version"
    schema_file.write_text("2024.04", encoding="utf-8")

    config = get_config()

    assert config.environment.value == "test"
    assert config.data_dir == tmp_path.resolve()
    assert config.log_level == "DEBUG"
    assert config.api_prefix == "/custom"
    assert config.data.schema_version == "2024.04"


def test_get_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)

    # Point to a clean temp directory without a schema file.
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))

    config = get_config()

    assert config.environment.value == "development"
    assert config.data_dir == tmp_path.resolve()
    assert config.data.schema_version == DEFAULT_SCHEMA_VERSION


def test_voice_stt_configuration_is_bounded_and_resolves_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL", "gpt-4o-transcribe")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_TIMEOUT_SECONDS", "17")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES", "2")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_RETRY_BACKOFF_SECONDS", "1,3")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_COST_USD", "0.25")
    monkeypatch.setenv("OPENAI_API_KEY", "not-returned-from-config")

    config = get_config()

    assert config.voice.accurate_stt.provider == "openai"
    assert config.voice.accurate_stt.model == "gpt-4o-transcribe"
    assert config.voice.accurate_stt.api_key_env == "OPENAI_API_KEY"
    assert config.voice.accurate_stt.timeout_seconds == 17
    assert config.voice.accurate_stt.max_retries == 2
    assert config.voice.accurate_stt.retry_backoff_seconds == (1.0, 3.0)
    assert config.voice.accurate_stt.max_cost_usd_per_operation == 0.25
    assert "not-returned-from-config" not in config.model_dump_json()


def test_production_rejects_deterministic_stt_without_explicit_escape_hatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deterministic")
    monkeypatch.delenv("BRAINBUDDY_ALLOW_DETERMINISTIC_STT", raising=False)

    with pytest.raises(ValueError, match="deterministic accurate STT"):
        get_config()


def test_test_environment_uses_explicit_ci_fake_while_production_defaults_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.delenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", raising=False)
    assert get_config().voice.accurate_stt.provider == "deterministic"

    get_config.cache_clear()
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_config().voice.accurate_stt.provider == "disabled"


def test_openai_configuration_without_named_credential_wires_disabled_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "openai")
    monkeypatch.setenv(
        "BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV", "MISSING_STT_API_KEY"
    )
    monkeypatch.delenv("MISSING_STT_API_KEY", raising=False)

    provider = _build_accurate_stt(get_config())

    assert isinstance(provider, DisabledAccurateStt)
    assert provider.reason == "STT_PROVIDER_CREDENTIALS_MISSING"
