"""Application configuration helpers."""

from __future__ import annotations

import logging
import math
import os
from enum import Enum
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

load_dotenv()

APP_DIR = Path(__file__).resolve().parent.parent
BACKEND_ROOT = APP_DIR.parent
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"
SCHEMA_VERSION_FILENAME = "schema_version"
DEFAULT_SCHEMA_VERSION = "0.1.0"


class AppEnvironment(str, Enum):
    """Deployment environment flags."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


class LoggingSettings(BaseModel):
    """Logging configuration values."""

    level: str = Field(default="INFO", description="Root log level")

    model_config = ConfigDict(frozen=True)

    @property
    def normalized_level(self) -> str:
        """Upper-case log level for logging APIs."""
        return self.level.upper()


class SessionSettings(BaseModel):
    """Cookie-based session configuration."""

    cookie_name: str = Field(
        default="brainbuddy_session", description="Cookie name carrying the session."
    )
    max_age_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        description="How long a session cookie lives, in seconds.",
    )
    secure: bool = Field(
        default=False,
        description=(
            "Whether the session cookie is marked Secure (HTTPS only). "
            "Enabled automatically in production."
        ),
    )

    model_config = ConfigDict(frozen=True)


class PasswordPolicy(BaseModel):
    """Bounds for accepted user passwords."""

    min_length: int = Field(default=12, ge=1)
    max_length: int = Field(default=128, ge=1)

    model_config = ConfigDict(frozen=True)


class DataSettings(BaseModel):
    """Filesystem layout for the application."""

    root_dir: Path = Field(default=DEFAULT_DATA_DIR)
    schema_version: str = Field(default=DEFAULT_SCHEMA_VERSION)

    model_config = ConfigDict(frozen=True)

    @property
    def schema_version_path(self) -> Path:
        """Return the schema version file path."""
        return self.root_dir / SCHEMA_VERSION_FILENAME


class VoiceProviderSettings(BaseModel):
    """Bounded configuration for one voice-processing provider role."""

    provider: str = "disabled"
    model: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0)
    max_cost_usd_per_operation: float = Field(default=0.50, gt=0, le=100)
    estimated_cost_usd_per_megabyte: float = Field(default=0.01, gt=0, le=10)
    endpoint: str = ""

    model_config = ConfigDict(frozen=True)

    @field_validator("retry_backoff_seconds")
    @classmethod
    def validate_retry_backoff_seconds(
        cls, values: tuple[float, ...]
    ) -> tuple[float, ...]:
        if not values or len(values) > 5:
            raise ValueError("retry backoff must contain between one and five delays")
        if any(not math.isfinite(value) or value < 0 or value > 300 for value in values):
            raise ValueError("retry backoff delays must be finite values from 0 to 300 seconds")
        return values


class VoiceRetentionSettings(BaseModel):
    raw_audio_seconds: int = Field(default=86_400, ge=0)
    working_artifacts_seconds: int = Field(default=604_800, ge=0)

    model_config = ConfigDict(frozen=True)


class VoiceAudioLimits(BaseModel):
    """Configuration-backed bounds enforced before any audio byte persists."""

    allowed_mime_types: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                "audio/wav",
                "audio/wave",
                "audio/x-wav",
                "audio/ogg",
                "audio/webm",
                "application/octet-stream",
            }
        )
    )
    max_chunk_bytes: int = Field(default=10_485_760, ge=1, le=104_857_600)
    max_total_bytes: int = Field(default=104_857_600, ge=1, le=1_073_741_824)
    max_chunk_count: int = Field(default=1024, ge=1, le=10_000)
    max_duration_seconds: float = Field(default=1800.0, gt=0, le=10_800)
    assumed_chunk_duration_seconds: float = Field(default=5.0, gt=0, le=600)

    model_config = ConfigDict(frozen=True)


class VoiceSettings(BaseModel):
    accurate_stt: VoiceProviderSettings = Field(default_factory=VoiceProviderSettings)
    fast_stt: VoiceProviderSettings = Field(default_factory=VoiceProviderSettings)
    reconciler: VoiceProviderSettings = Field(default_factory=VoiceProviderSettings)
    retention: VoiceRetentionSettings = Field(default_factory=VoiceRetentionSettings)
    audio_limits: VoiceAudioLimits = Field(default_factory=VoiceAudioLimits)
    max_operation_recoveries: int = Field(default=2, ge=0, le=5)
    max_cumulative_cost_usd_per_operation: float = Field(default=1.00, gt=0, le=200)
    lease_recovery_margin_seconds: float = Field(default=30.0, ge=0, le=600)


class AppConfig(BaseModel):
    """Top-level Brain Buddy application configuration."""

    environment: AppEnvironment = Field(default=AppEnvironment.DEVELOPMENT)
    api_prefix: str = Field(default="/api")
    data: DataSettings = Field(default_factory=DataSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    password_policy: PasswordPolicy = Field(default_factory=PasswordPolicy)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)

    model_config = ConfigDict(frozen=True)

    @property
    def data_dir(self) -> Path:
        return self.data.root_dir

    @property
    def log_level(self) -> str:
        return self.logging.normalized_level


def _read_schema_version(data_dir: Path) -> str:
    schema_path = data_dir / SCHEMA_VERSION_FILENAME
    if schema_path.exists():
        return schema_path.read_text(encoding="utf-8").strip() or DEFAULT_SCHEMA_VERSION
    return DEFAULT_SCHEMA_VERSION


def _build_config() -> AppConfig:
    env_value = os.getenv("BRAIN_BUDDY_ENV", AppEnvironment.DEVELOPMENT.value)
    api_prefix = os.getenv("BRAIN_BUDDY_API_PREFIX", "/api")
    log_level = os.getenv("BRAIN_BUDDY_LOG_LEVEL", "INFO")
    data_dir_value = os.getenv("BRAIN_BUDDY_DATA_DIR", str(DEFAULT_DATA_DIR))

    data_dir = Path(data_dir_value).expanduser().resolve()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback_dir = DEFAULT_DATA_DIR.resolve()
        fallback_dir.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).warning(
            "Data dir %s is not writable; falling back to %s", data_dir, fallback_dir
        )
        data_dir = fallback_dir

    schema_version = _read_schema_version(data_dir)

    try:
        environment = AppEnvironment(env_value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unsupported environment '{env_value}'.") from exc

    logging_config = LoggingSettings(level=log_level)
    data_config = DataSettings(root_dir=data_dir, schema_version=schema_version)
    session_config = SessionSettings(
        secure=environment is AppEnvironment.PRODUCTION,
    )
    password_policy = PasswordPolicy()
    accurate_provider = os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER")
    if not accurate_provider:
        accurate_provider = (
            "deterministic"
            if environment is AppEnvironment.TEST
            else "openai"
            if os.getenv("OPENAI_API_KEY")
            else "disabled"
        )
    if environment is AppEnvironment.PRODUCTION and accurate_provider == "deterministic":
        raise ValueError(
            "Production cannot use deterministic accurate STT."
        )

    retry_backoff = tuple(
        float(value.strip())
        for value in os.getenv(
            "BRAIN_BUDDY_VOICE_ACCURATE_STT_RETRY_BACKOFF_SECONDS", "1,2"
        ).split(",")
        if value.strip()
    )
    accurate_stt = VoiceProviderSettings(
        provider=accurate_provider,
        model=os.getenv(
            "BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL", "gpt-4o-mini-transcribe"
        ),
        api_key_env=os.getenv(
            "BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV", "OPENAI_API_KEY"
        ),
        timeout_seconds=float(
            os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_TIMEOUT_SECONDS", "60")
        ),
        max_retries=int(
            os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES", "2")
        ),
        retry_backoff_seconds=retry_backoff,
        max_cost_usd_per_operation=float(
            os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_COST_USD", "0.50")
        ),
        estimated_cost_usd_per_megabyte=float(
            os.getenv(
                "BRAIN_BUDDY_VOICE_ACCURATE_STT_ESTIMATED_COST_USD_PER_MB", "0.01"
            )
        ),
    )
    reconciler_retry_backoff = tuple(
        float(value.strip())
        for value in os.getenv(
            "BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", "1,2"
        ).split(",")
        if value.strip()
    )
    voice = VoiceSettings(
        accurate_stt=accurate_stt,
        fast_stt=VoiceProviderSettings(provider="disabled"),
        reconciler=VoiceProviderSettings(
            provider=os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "disabled"),
            model=os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", "gpt-4o"),
            api_key_env=os.getenv(
                "BRAIN_BUDDY_VOICE_RECONCILER_API_KEY_ENV", "OPENAI_API_KEY"
            ),
            endpoint=os.getenv(
                "BRAIN_BUDDY_VOICE_RECONCILER_ENDPOINT",
                "https://api.openai.com/v1/chat/completions",
            ),
            timeout_seconds=float(
                os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS", "30")
            ),
            max_retries=int(
                os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES", "2")
            ),
            retry_backoff_seconds=reconciler_retry_backoff,
            max_cost_usd_per_operation=float(
                os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD", "0.50")
            ),
            estimated_cost_usd_per_megabyte=float(
                os.getenv(
                    "BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB", "0.01"
                )
            ),
        ),
        retention=VoiceRetentionSettings(
            raw_audio_seconds=int(
                os.getenv("BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS", "86400")
            ),
            working_artifacts_seconds=int(
                os.getenv(
                    "BRAIN_BUDDY_VOICE_WORKING_ARTIFACT_RETENTION_SECONDS", "604800"
                )
            ),
        ),
        audio_limits=VoiceAudioLimits(
            allowed_mime_types=frozenset(
                value.strip()
                for value in os.getenv(
                    "BRAIN_BUDDY_VOICE_AUDIO_ALLOWED_MIME_TYPES",
                    "audio/wav,audio/wave,audio/x-wav,audio/ogg,audio/webm,"
                    "application/octet-stream",
                ).split(",")
                if value.strip()
            ),
            max_chunk_bytes=int(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES", "10485760")
            ),
            max_total_bytes=int(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_TOTAL_BYTES", "104857600")
            ),
            max_chunk_count=int(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_COUNT", "1024")
            ),
            max_duration_seconds=float(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_DURATION_SECONDS", "1800")
            ),
            assumed_chunk_duration_seconds=float(
                os.getenv(
                    "BRAIN_BUDDY_VOICE_AUDIO_ASSUMED_CHUNK_DURATION_SECONDS", "5"
                )
            ),
        ),
        max_operation_recoveries=int(
            os.getenv("BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES", "2")
        ),
        max_cumulative_cost_usd_per_operation=float(
            os.getenv("BRAIN_BUDDY_VOICE_MAX_CUMULATIVE_COST_USD", "1.00")
        ),
        lease_recovery_margin_seconds=float(
            os.getenv("BRAIN_BUDDY_VOICE_LEASE_RECOVERY_MARGIN_SECONDS", "30")
        ),
    )

    return AppConfig(
        environment=environment,
        api_prefix=api_prefix,
        data=data_config,
        logging=logging_config,
        session=session_config,
        password_policy=password_policy,
        voice=voice,
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return a cached configuration instance."""

    return _build_config()


__all__ = [
    "AppConfig",
    "AppEnvironment",
    "PasswordPolicy",
    "SessionSettings",
    "VoiceAudioLimits",
    "VoiceProviderSettings",
    "VoiceRetentionSettings",
    "VoiceSettings",
    "get_config",
]
