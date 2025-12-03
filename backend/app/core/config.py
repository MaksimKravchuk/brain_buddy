"""Application configuration helpers."""
from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from pathlib import Path
import logging
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

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


class SecuritySettings(BaseModel):
    """Security-related toggles for API hardening."""

    api_key: str | None = Field(default=None, description="Static API key required for requests.")
    api_key_header: str = Field(default="X-API-Key", description="Header used for the static API key.")

    model_config = ConfigDict(frozen=True)

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


class DataSettings(BaseModel):
    """Filesystem layout for the application."""

    root_dir: Path = Field(default=DEFAULT_DATA_DIR)
    schema_version: str = Field(default=DEFAULT_SCHEMA_VERSION)

    model_config = ConfigDict(frozen=True)

    @property
    def schema_version_path(self) -> Path:
        """Return the schema version file path."""
        return self.root_dir / SCHEMA_VERSION_FILENAME


class AppConfig(BaseModel):
    """Top-level Brain Buddy application configuration."""

    environment: AppEnvironment = Field(default=AppEnvironment.DEVELOPMENT)
    api_prefix: str = Field(default="/api")
    data: DataSettings = Field(default_factory=DataSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)

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
    api_key = os.getenv("BRAIN_BUDDY_API_KEY")
    api_key_header = os.getenv("BRAIN_BUDDY_API_KEY_HEADER", "X-API-Key")

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

    logging_config = LoggingSettings(level=log_level)
    data_config = DataSettings(root_dir=data_dir, schema_version=schema_version)
    security_config = SecuritySettings(api_key=api_key, api_key_header=api_key_header)

    try:
        environment = AppEnvironment(env_value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unsupported environment '{env_value}'.") from exc

    return AppConfig(
        environment=environment,
        api_prefix=api_prefix,
        data=data_config,
        logging=logging_config,
        security=security_config,
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return a cached configuration instance."""

    return _build_config()


__all__ = ["AppConfig", "AppEnvironment", "get_config", "SecuritySettings"]
