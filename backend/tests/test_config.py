"""Tests for application configuration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import DEFAULT_SCHEMA_VERSION, get_config


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


def test_build_container_uses_openai_reconciler_outside_test(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.container import build_container
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", "gpt-4o")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_config.cache_clear()  # type: ignore[attr-defined]

    container = build_container(get_config())

    assert isinstance(container.task_service.text_reconciler, OpenAITextReconciler)
    assert container.task_service.text_reconciler.model == "gpt-4o"
