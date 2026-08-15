"""Tests for application configuration helpers."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from app import core as app_core
from app.container import _build_accurate_stt, _build_text_reconciler, build_container
from app.core.config import (
    BACKEND_ROOT,
    CANONICAL_PUBLIC_CALLBACK_HOSTS,
    DEFAULT_SCHEMA_VERSION,
    AppConfig,
    AppEnvironment,
    VoiceProviderSettings,
    VoiceSettings,
    get_config,
    public_callback_host_is_reachable,
)
from app.main import create_app
from app.modules.agents.domain import AgentAuditEntryDocument
from app.modules.agents.repository import AgentRepository
from app.modules.agents.secrets import SealedSecret, SecretsUnavailable
from app.utils.time import utcnow
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


def test_relay_manifest_callback_uses_the_configured_api_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://relay.example.test")
    monkeypatch.setenv("BRAIN_BUDDY_API_PREFIX", "/custom")

    config = get_config()
    container = build_container(config)

    assert config.agent_relay.public_base_url == "https://relay.example.test"
    assert container.agent_relay_service.callback_url == (
        "https://relay.example.test/custom/agent-events"
    )


def test_relay_manifest_callback_defaults_to_api_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://relay.example.test")
    monkeypatch.delenv("BRAIN_BUDDY_API_PREFIX", raising=False)

    container = build_container(get_config())

    assert container.agent_relay_service.callback_url == (
        "https://relay.example.test/api/agent-events"
    )


def test_get_config_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAIN_BUDDY_ENV", raising=False)
    monkeypatch.delenv("BRAIN_BUDDY_DATA_DIR", raising=False)

    # Point to a clean temp directory without a schema file.
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))

    config = get_config()

    assert config.environment.value == "development"
    assert config.data_dir == tmp_path.resolve()
    assert config.data.schema_version == DEFAULT_SCHEMA_VERSION
    assert (
        "audio/x-brain-buddy-test-text"
        not in config.voice.audio_limits.allowed_mime_types
    )
    assert config.agent_relay.retention_sweep_interval_seconds == 60


def test_relay_retention_interval_is_independent_bounded_and_cannot_be_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "test")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_SWEEP_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS", "17")

    assert get_config().agent_relay.retention_sweep_interval_seconds == 17

    get_config.cache_clear()
    monkeypatch.setenv("BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError, match="greater than or equal to 1"):
        get_config()


def test_voice_stt_configuration_is_bounded_and_resolves_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    # Production refuses to start without a canonical HTTPS callback origin.
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
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
    # Production refuses to start without a canonical HTTPS callback origin.
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
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
    # Production refuses to start without a canonical HTTPS callback origin.
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert get_config().voice.accurate_stt.provider == "disabled"


def test_openai_configuration_without_named_credential_wires_disabled_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    # Production refuses to start without a canonical HTTPS callback origin.
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
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
    """The Compose Playwright harness's discovery reports the configured
    categories -- ``deterministic`` accurate STT plus the ``openai`` reconciler
    the runner script sets -- and the frontend names exactly those in consent.
    Reproduce the Compose backend's configuration (``BRAIN_BUDDY_ENV=test`` plus
    ``BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER=openai``) and confirm the container
    genuinely allowlists both categories for consent while the reconciler adapter
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

    # Both configured categories are nameable in consent: "deterministic" (the
    # accurate-STT category the discovery endpoint now reports and the client
    # names) and "openai" (the reconciler category), the latter kept as legacy
    # compatibility for the deterministic accurate STT as well.
    assert (
        container.voice_brain_dump_service.allowed_external_provider_categories
        == frozenset({"deterministic", "openai"})
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

    assert isinstance(
        container.voice_brain_dump_service.text_reconciler, OpenAITextReconciler
    )
    assert container.voice_brain_dump_service.text_reconciler.model == "gpt-4o"


def test_voice_reconciler_configuration_is_bounded_and_resolves_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    # Production refuses to start without a canonical HTTPS callback origin.
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "openai")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_API_KEY_ENV", "RECONCILER_API_KEY")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES", "3")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", "1,4")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD", "0.10")
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB", "0.02")
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
    monkeypatch.setenv("BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB", "0.03")
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
    assert (
        container.voice_brain_dump_service.provider_run_lease_seconds
        == pytest.approx(63.0)
    )


def test_unsupported_reconciler_provider_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    # Production refuses to start without a canonical HTTPS callback origin.
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
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


class TestAgentRelayCallbackOrigin:
    """The origin an external agent is told to call back to (FR-002).

    Every dispatched hand-off carries this URL into a third-party system that
    BrainBuddy does not control, and each report it produces is authenticated
    only by signature — so a wrong or unreachable origin is not a cosmetic
    misconfiguration, it silently strands every run in production. Production
    therefore refuses to start on anything but a canonical HTTPS origin.
    """

    @pytest.mark.parametrize(
        "raw",
        [
            "http://brain-buddy-backend.fly.dev",
            "https://localhost:8000",
            "https://127.0.0.1",
            "https://[::1]",
            "https://10.0.0.5",
            "https://192.168.1.10",
            "https://169.254.169.254",
            "https://agent:secret@brain-buddy-backend.fly.dev",
            "https://brain-buddy-backend.fly.dev?token=abc",
            "https://brain-buddy-backend.fly.dev#frag",
            "https://brain-buddy-backend.fly.dev/nested/prefix",
            "https://",
            "not a url",
            "",
            "   ",
        ],
    )
    def test_production_refuses_a_non_canonical_https_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """Startup fails loudly rather than handing agents a bad callback."""

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", raw)

        with pytest.raises(ValueError, match="public base URL"):
            get_config()

    def test_production_accepts_the_deployed_origin_and_derives_the_callback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The value `fly.backend.toml` sets is exactly what production wants."""

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv(
            "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
        )

        config = get_config()

        assert (
            config.agent_relay.public_base_url == "https://brain-buddy-backend.fly.dev"
        )
        assert (
            config.agent_relay_callback_url
            == "https://brain-buddy-backend.fly.dev/api/agent-events"
        )

    def test_a_trailing_slash_still_yields_exactly_one_callback_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`https://host/` and `https://host` must not differ on the wire."""

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv(
            "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev/"
        )

        config = get_config()

        assert (
            config.agent_relay_callback_url
            == "https://brain-buddy-backend.fly.dev/api/agent-events"
        )

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("http://localhost:8000", "http://localhost:8000/api/agent-events"),
            ("http://127.0.0.1:8000", "http://127.0.0.1:8000/api/agent-events"),
            ("https://dev.example.test", "https://dev.example.test/api/agent-events"),
        ],
    )
    def test_development_still_allows_a_local_origin(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        raw: str,
        expected: str,
    ) -> None:
        """Running the stack locally must not require a public HTTPS name."""

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", raw)

        assert get_config().agent_relay_callback_url == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "http://user:pw@localhost:8000",
            "http://localhost:8000?token=abc",
            "http://localhost:8000#frag",
            "ftp://localhost:8000",
            "not a url",
        ],
    )
    def test_a_structurally_broken_origin_is_refused_everywhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
    ) -> None:
        """Credentials, queries, fragments and junk are wrong in any environment."""

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "development")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", raw)

        with pytest.raises(ValueError, match="public base URL"):
            get_config()


class TestPublicCallbackHostPolicy:
    """Production's host policy, driven with an injected resolver.

    Real DNS in a unit test is both flaky and a live network dependency, so the
    resolver is a seam. What is under test is the decision, not the lookup:
    unresolvable names and special-use suffixes are refused outright, and a name
    that resolves is admitted only if *every* answer is globally routable — one
    private answer among public ones is a split-horizon name, which is exactly
    the case a "does it have a public address?" check would wave through.
    """

    def test_a_resolvable_public_host_is_reachable(self) -> None:
        """The ordinary case: one public answer, accepted."""

        assert (
            public_callback_host_is_reachable(
                "agent.example.com", resolver=lambda host: ["93.184.216.34"]
            )
            is True
        )

    def test_every_answer_must_be_public(self) -> None:
        """A public answer does not excuse a private one alongside it."""

        assert (
            public_callback_host_is_reachable(
                "split.example.com",
                resolver=lambda host: ["93.184.216.34", "10.0.0.5"],
            )
            is False
        )

    def test_a_private_only_host_is_refused(self) -> None:
        """A name that only points inward is not a public callback origin."""

        assert (
            public_callback_host_is_reachable(
                "internal.example.com", resolver=lambda host: ["192.168.1.10"]
            )
            is False
        )

    def test_a_nonexistent_host_is_refused(self) -> None:
        """Fail closed: a name that does not resolve is not "probably fine"."""

        def unresolvable(host: str) -> list[str]:
            raise OSError("NXDOMAIN")

        assert (
            public_callback_host_is_reachable(
                "no-such-host.example.com", resolver=unresolvable
            )
            is False
        )

    def test_an_empty_answer_set_is_refused(self) -> None:
        """A resolver that answers with nothing has resolved nothing."""

        assert (
            public_callback_host_is_reachable(
                "empty.example.com", resolver=lambda host: []
            )
            is False
        )

    @pytest.mark.parametrize(
        "host",
        [
            "localhost",
            "agent.localhost",
            "agent.local",
            "agent.invalid",
            "agent.test",
            "agent.example",
            "agent.internal",
            "agent.intranet",
            "agent.lan",
            "agent.corp",
            "agent.home.arpa",
            "backend",
        ],
    )
    def test_a_special_use_or_internal_name_is_refused_without_resolving(
        self, host: str
    ) -> None:
        """These names are meaningless outside one network, so DNS is not asked.

        Resolving them would be worse than pointless: a split-horizon resolver
        can return a perfectly public-looking answer for `agent.corp`.
        """

        def never(host: str) -> list[str]:
            raise AssertionError("special-use names must not be resolved")

        assert public_callback_host_is_reachable(host, resolver=never) is False

    @pytest.mark.parametrize(
        ("host", "expected"),
        [
            ("93.184.216.34", True),
            ("2606:2800:220:1:248:1893:25c8:1946", True),
            ("127.0.0.1", False),
            ("10.0.0.5", False),
            ("169.254.169.254", False),
            ("::1", False),
            ("::ffff:127.0.0.1", False),
        ],
    )
    def test_an_address_literal_is_judged_without_resolving(
        self, host: str, expected: bool
    ) -> None:
        """A literal is already an answer; asking DNS about it is nonsense."""

        def never(host: str) -> list[str]:
            raise AssertionError("literals must not be resolved")

        assert public_callback_host_is_reachable(host, resolver=never) is expected

    def test_the_canonical_production_host_needs_no_lookup(self) -> None:
        """The one governed allowlist entry, so production start-up is offline.

        `fly.backend.toml` names this host and CI has no outbound DNS; making
        the deployed origin depend on a lookup would make start-up flaky for the
        single value we already control.
        """

        def never(host: str) -> list[str]:
            raise AssertionError("the canonical host must not be resolved")

        assert frozenset({"brain-buddy-backend.fly.dev"}) == (
            CANONICAL_PUBLIC_CALLBACK_HOSTS
        )
        assert (
            public_callback_host_is_reachable(
                "brain-buddy-backend.fly.dev", resolver=never
            )
            is True
        )

    def test_a_neighbouring_fly_host_is_not_allowlisted(self) -> None:
        """The allowlist is one exact host, not a suffix."""

        assert (
            public_callback_host_is_reachable(
                "evil-brain-buddy-backend.fly.dev", resolver=lambda host: ["10.0.0.5"]
            )
            is False
        )


@pytest.mark.parametrize(
    ("relay_state", "has_data", "boots"),
    [
        ("off", False, True),
        ("off", True, False),
        ("internal", False, False),
        ("on", False, False),
    ],
)
def test_production_relay_key_startup_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relay_state: str,
    has_data: bool,
    boots: bool,
) -> None:
    """Dark empty production boots; enabled or persisted relay state needs a key."""

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.setenv(
        "BRAIN_BUDDY_FEATURE_FLAGS", f"external_agent_relay={relay_state}"
    )
    monkeypatch.delenv("BRAIN_BUDDY_AGENT_RELAY_KEYS", raising=False)
    config = get_config()
    if has_data:
        AgentRepository(config.data.root_dir).append_audit(
            AgentAuditEntryDocument(
                id="audit_existing",
                owner_id="owner_existing",
                action="run_dispatched",
                outcome="ok",
                created_at=utcnow(),
            )
        )

    if not boots:
        with pytest.raises(SecretsUnavailable):
            build_container(config)
        return

    container = build_container(config)
    assert container.agent_repo.has_any_relay_data() is False


def test_dark_production_relay_secret_boundary_never_materializes_a_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The empty/OFF boot placeholder fails every secret-bearing operation closed."""

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", "external_agent_relay=off")
    monkeypatch.delenv("BRAIN_BUDDY_AGENT_RELAY_KEYS", raising=False)
    secret_box = build_container(get_config()).agent_relay_service.secret_box

    assert repr(secret_box) == "UnavailableRelaySecretBox()"
    operations = (
        lambda: secret_box.active_key_id,
        lambda: secret_box.seal("secret", aad="scope"),
        lambda: secret_box.fingerprint("secret"),
        lambda: secret_box.fingerprint_candidates("secret"),
        lambda: secret_box.fingerprint_matches("stored", "secret"),
        lambda: secret_box.open(
            SealedSecret(key_id="missing", ciphertext="not-secret"), aad="scope"
        ),
    )
    for operation in operations:
        with pytest.raises(SecretsUnavailable, match="required before relay data"):
            operation()


def _corrupt_feature_flag_store(config: AppConfig) -> None:
    """Overwrite the migrated SQLite file with bytes no connection can open,
    forcing every subsequent read of it to come back degraded (DD-2)."""

    db_path = config.data_dir / "feature_flags.sqlite3"
    db_path.write_bytes(b"not a sqlite database")


def test_degraded_flag_store_dark_production_still_boots_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A corrupt/locked flag store must not crash boot: a degraded read is
    conservative for *rollout* (every managed flag ineffective, every mutation
    refused) but must not be conflated with "confirmed ON" for the relay's
    key requirement when there is no persisted relay data to protect."""

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", "external_agent_relay=off")
    monkeypatch.delenv("BRAIN_BUDDY_AGENT_RELAY_KEYS", raising=False)
    config = get_config()

    # Prime a healthy migrated store (external_agent_relay=off, no data) before
    # corrupting it, so the degraded read below is the only variable in play.
    build_container(config)
    _corrupt_feature_flag_store(config)
    get_config.cache_clear()  # type: ignore[attr-defined]
    config = get_config()

    container = build_container(config)

    assert container.feature_flag_repo.read().degraded is True
    assert container.agent_repo.has_any_relay_data() is False
    secret_box = container.agent_relay_service.secret_box
    assert repr(secret_box) == "UnavailableRelaySecretBox()"
    operations = (
        lambda: secret_box.active_key_id,
        lambda: secret_box.seal("secret", aad="scope"),
        lambda: secret_box.fingerprint("secret"),
        lambda: secret_box.fingerprint_candidates("secret"),
        lambda: secret_box.fingerprint_matches("stored", "secret"),
        lambda: secret_box.open(
            SealedSecret(key_id="missing", ciphertext="not-secret"), aad="scope"
        ),
    )
    for operation in operations:
        with pytest.raises(SecretsUnavailable, match="required before relay data"):
            operation()


def test_degraded_flag_store_with_existing_relay_data_still_requires_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Degraded flags fail closed for rollout, but persisted relay data is
    never flag-gated on the way in and must remain decryptable: a degraded
    read must not waive the key requirement once relay data already exists,
    exactly like a healthy, confirmed-OFF store with data (see the ``off,
    True, False`` case of ``test_production_relay_key_startup_matrix``)."""

    monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
    monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv(
        "BRAIN_BUDDY_PUBLIC_BASE_URL", "https://brain-buddy-backend.fly.dev"
    )
    monkeypatch.setenv("BRAIN_BUDDY_FEATURE_FLAGS", "external_agent_relay=off")
    monkeypatch.delenv("BRAIN_BUDDY_AGENT_RELAY_KEYS", raising=False)
    config = get_config()

    build_container(config)  # prime a healthy migrated store, as above
    AgentRepository(config.data_dir).append_audit(
        AgentAuditEntryDocument(
            id="audit_existing",
            owner_id="owner_existing",
            action="run_dispatched",
            outcome="ok",
            created_at=utcnow(),
        )
    )
    _corrupt_feature_flag_store(config)
    get_config.cache_clear()  # type: ignore[attr-defined]
    config = get_config()

    with pytest.raises(SecretsUnavailable):
        build_container(config)


class TestAgentRelayCallbackStartup:
    """The same policy, observed where it actually bites: app startup."""

    def test_production_startup_fails_closed_on_a_bad_callback_origin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The app refuses to come up rather than stranding future runs."""

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "http://localhost:8000")

        with pytest.raises(ValueError, match="public base URL"):
            create_app()

    def test_the_deployed_fly_origin_is_what_production_accepts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`fly.backend.toml` and the production policy cannot drift apart."""

        fly_config = tomllib.loads(
            (BACKEND_ROOT.parent / "fly.backend.toml").read_text(encoding="utf-8")
        )
        deployed = fly_config["env"]["BRAIN_BUDDY_PUBLIC_BASE_URL"]

        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", deployed)

        config = get_config()

        assert config.agent_relay.public_base_url == deployed
        assert config.agent_relay_callback_url == f"{deployed}/api/agent-events"

    def test_production_resolves_a_non_allowlisted_origin_before_accepting_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A self-hosted deployment is admitted only on a public answer."""

        asked: list[str] = []

        def resolver(host: str) -> list[str]:
            asked.append(host)
            return ["93.184.216.34"]

        monkeypatch.setattr(app_core.config, "_resolve_callback_host", resolver)
        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://relay.example.com")

        config = get_config()

        assert asked == ["relay.example.com"]
        assert (
            config.agent_relay_callback_url
            == "https://relay.example.com/api/agent-events"
        )

    def test_production_refuses_an_origin_whose_name_does_not_resolve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A typo'd hostname stops the deploy instead of stranding every run."""

        def unresolvable(host: str) -> list[str]:
            raise OSError("NXDOMAIN")

        monkeypatch.setattr(app_core.config, "_resolve_callback_host", unresolvable)
        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://relay.example.com")

        with pytest.raises(ValueError, match="public base URL"):
            get_config()

    def test_production_refuses_a_dotted_internal_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dot is not evidence of anything, and never was."""

        monkeypatch.setattr(
            app_core.config,
            "_resolve_callback_host",
            lambda host: ["93.184.216.34"],
        )
        monkeypatch.setenv("BRAIN_BUDDY_ENV", "production")
        monkeypatch.setenv("BRAIN_BUDDY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "https://relay.corp")

        with pytest.raises(ValueError, match="public base URL"):
            get_config()
