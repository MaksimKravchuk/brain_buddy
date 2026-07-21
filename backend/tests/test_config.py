"""Tests for application configuration helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.container import _build_accurate_stt, _build_text_reconciler
from app.core.config import (
    DEFAULT_SCHEMA_VERSION,
    AppConfig,
    AppEnvironment,
    VoiceProviderSettings,
    VoiceSettings,
    get_config,
)
from app.workflows.voice_brain_dump.providers import (
    DisabledAccurateStt,
    DisabledTextReconciler,
)


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
    assert "audio/x-brain-buddy-test-text" not in config.voice.audio_limits.allowed_mime_types


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


def test_production_rejects_deterministic_stt_even_with_legacy_escape_hatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deterministic")
    monkeypatch.setenv("BRAINBUDDY_ALLOW_DETERMINISTIC_STT", "1")

    with pytest.raises(ValueError, match="deterministic accurate STT"):
        get_config()


def test_container_defensively_disables_deterministic_stt_outside_test() -> None:
    config = AppConfig(
        environment=AppEnvironment.DEVELOPMENT,
        voice=VoiceSettings(
            accurate_stt=VoiceProviderSettings(provider="deterministic")
        ),
    )

    provider = _build_accurate_stt(config)

    assert isinstance(provider, DisabledAccurateStt)
    assert provider.reason == "STT_DETERMINISTIC_PROVIDER_TEST_ONLY"


def test_voice_operation_recovery_budget_is_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES", "3")

    assert get_config().voice.max_operation_recoveries == 3


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


def test_compose_e2e_runs_backend_in_test_environment() -> None:
    """Compose product tests must opt into the deterministic test-only STT provider."""

    runner = Path(__file__).parents[2] / "scripts" / "run_playwright_e2e.sh"

    assert "BRAIN_BUDDY_ENV=test" in runner.read_text(encoding="utf-8")


def test_compose_e2e_configures_a_genuinely_allowlisted_openai_category(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Compose Playwright harness names ``openai`` in its consent flows
    (matching the frontend's only supported provider category). Reproduce the
    Compose backend's configuration -- ``BRAIN_BUDDY_ENV=test`` plus the
    reconciler provider the runner script sets -- and confirm the container
    genuinely allowlists "openai" for consent while the reconciler adapter
    stays the deterministic, no-network stand-in (never a real OpenAI call).
    """

    from app.container import build_container
    from app.workflows.voice_brain_dump.providers import DeterministicTextReconciler

    runner = Path(__file__).parents[2] / "scripts" / "run_playwright_e2e.sh"
    assert "BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER=openai" in runner.read_text(
        encoding="utf-8"
    )

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    container = build_container(get_config())

    assert container.voice_brain_dump_service.allowed_external_provider_categories == frozenset(
        {"openai"}
    )
    assert isinstance(
        container.voice_brain_dump_service.text_reconciler, DeterministicTextReconciler
    )


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

    assert isinstance(container.voice_brain_dump_service.text_reconciler, OpenAITextReconciler)
    assert container.voice_brain_dump_service.text_reconciler.model == "gpt-4o"


def test_voice_reconciler_configuration_is_bounded_and_resolves_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_API_KEY_ENV", "RECONCILER_API_KEY")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES", "3")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", "1,4")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD", "0.10")
    monkeypatch.setenv(
        "BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB", "0.02"
    )
    monkeypatch.setenv("RECONCILER_API_KEY", "not-returned-from-config")

    config = get_config()

    assert config.voice.reconciler.provider == "openai"
    assert config.voice.reconciler.model == "gpt-4o-mini"
    assert config.voice.reconciler.api_key_env == "RECONCILER_API_KEY"
    assert config.voice.reconciler.timeout_seconds == 12
    assert config.voice.reconciler.max_retries == 3
    assert config.voice.reconciler.retry_backoff_seconds == (1.0, 4.0)
    assert config.voice.reconciler.max_cost_usd_per_operation == 0.10
    assert config.voice.reconciler.estimated_cost_usd_per_megabyte == 0.02
    assert "not-returned-from-config" not in config.model_dump_json()


def test_build_container_forwards_bounded_reconciler_settings_to_the_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.container import build_container

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES", "4")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", "0.5,1.5")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD", "0.05")
    monkeypatch.setenv(
        "BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB", "0.03"
    )
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS", "123")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    get_config.cache_clear()  # type: ignore[attr-defined]

    container = build_container(get_config())

    reconciler = container.voice_brain_dump_service.text_reconciler
    assert reconciler.max_retries == 4
    assert reconciler.retry_backoff_seconds == (0.5, 1.5)
    assert reconciler.max_cost_usd_per_operation == 0.05
    assert reconciler.estimated_cost_usd_per_megabyte == 0.03
    assert container.voice_brain_dump_service.raw_audio_retention.total_seconds() == 123


def test_build_container_derives_recovery_lease_from_worst_case_provider_timing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F5: the persisted recovery lease must cover the configured provider
    timeout, its bounded retry/backoff schedule, and a safe margin -- not a
    fixed 30 seconds -- so no valid ongoing call can be recovered early."""

    from app.container import build_container

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES", "2")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_RETRY_BACKOFF_SECONDS", "1,2")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES", "1")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", "3")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_LEASE_RECOVERY_MARGIN_SECONDS", "30")
    get_config.cache_clear()  # type: ignore[attr-defined]

    container = build_container(get_config())

    # accurate_stt worst case: 3 attempts * 10s timeout + (1 + 2)s backoff = 33s
    # reconciler worst case: 2 attempts * 5s timeout + 3s backoff = 13s
    # lease = max(33, 13) + 30s margin = 63s
    assert container.voice_brain_dump_service.provider_run_lease_seconds == pytest.approx(63.0)


def test_unsupported_reconciler_provider_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "unknown")

    provider = _build_text_reconciler(get_config())

    assert isinstance(provider, DisabledTextReconciler)


@pytest.mark.parametrize(
    "backoff",
    ["-1", "nan", "inf", "301", "1,2,3,4,5,6"],
)
def test_reconciler_retry_backoff_rejects_non_finite_negative_or_unbounded_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backoff: str
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", backoff)

    with pytest.raises(ValueError, match="retry backoff"):
        get_config()


def test_deepgram_is_the_credentialed_mvp_default_accurate_stt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MVP default: Deepgram Nova-3 multilingual, chosen automatically over
    ``openai`` when both credentials happen to be present, and never an
    automatic escalation -- purely a static default-selection preference."""

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", raising=False)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "not-returned-from-config")
    monkeypatch.setenv("OPENAI_API_KEY", "also-not-returned-from-config")

    config = get_config()

    assert config.voice.accurate_stt.provider == "deepgram"
    assert config.voice.accurate_stt.model == "nova-3"
    assert config.voice.accurate_stt.api_key_env == "DEEPGRAM_API_KEY"
    assert "not-returned-from-config" not in config.model_dump_json()


def test_container_wires_deepgram_adapter_when_credentialed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.container import build_container
    from app.workflows.voice_brain_dump.adapters import DeepgramAccurateStt

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-deepgram-key")
    get_config.cache_clear()  # type: ignore[attr-defined]

    container = build_container(get_config())

    accurate_stt = container.voice_brain_dump_service.accurate_stt
    assert isinstance(accurate_stt, DeepgramAccurateStt)
    assert accurate_stt.model == "nova-3"


def test_deepgram_without_credentials_wires_disabled_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deepgram")
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)

    provider = _build_accurate_stt(get_config())

    assert isinstance(provider, DisabledAccurateStt)
    assert provider.reason == "STT_PROVIDER_CREDENTIALS_MISSING"


def test_reconciler_mvp_default_is_luna_product_operation_v1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.delenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_VOICE_RECONCILER_TEMPLATE_VERSION", raising=False)

    config = get_config()

    assert config.voice.reconciler.model == "gpt-5.6-luna"
    assert config.voice.reconciler.template_version == "product-operation-v1"


def test_reconciler_never_sends_a_temperature_parameter() -> None:
    from app.workflows.voice_brain_dump.adapters import OpenAITextReconciler
    from app.workflows.voice_brain_dump.providers import ReconcileTextRequest

    reconciler = OpenAITextReconciler(api_key="test-key", model="gpt-5.6-luna")
    payload = reconciler._payload(  # noqa: SLF001 - contract check, not a public API
        ReconcileTextRequest(
            operation_id="op_1",
            transcript_segments=[],
            active_proposals=[],
        )
    )

    assert "temperature" not in payload
    assert payload["model"] == "gpt-5.6-luna"


@pytest.mark.parametrize("forbidden_model", ["gpt-5.6-terra", "gpt-5.6-sol", "gpt-5.6-fable"])
def test_forbidden_reconciler_tiers_are_rejected_as_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forbidden_model: str
) -> None:
    """Terra is 1.75x more expensive and not an authorized default or
    automatic fallback; Sol and Fable are not authorized at all."""

    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", forbidden_model)

    with pytest.raises(ValueError, match="not authorized"):
        get_config()


def test_deepgram_accurate_stt_requires_a_nova_family_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER", "deepgram")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL", "whisper-large-v3")

    with pytest.raises(ValueError, match="Unauthorized accurate_stt model"):
        get_config()


def test_validate_voice_provider_authorization_accepts_the_mvp_defaults() -> None:
    from app.core.config import (
        VoiceProviderSettings,
        VoiceSettings,
        validate_voice_provider_authorization,
    )

    voice = VoiceSettings(
        accurate_stt=VoiceProviderSettings(provider="deepgram", model="nova-3"),
        reconciler=VoiceProviderSettings(
            provider="openai",
            model="gpt-5.6-luna",
            template_version="product-operation-v1",
        ),
    )

    validate_voice_provider_authorization(voice)  # must not raise
