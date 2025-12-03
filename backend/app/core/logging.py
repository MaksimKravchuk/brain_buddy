"""Logging configuration for the Brain Buddy backend."""

from __future__ import annotations

import logging
import logging.config
from contextvars import ContextVar, Token
from typing import Any

from .config import AppConfig, get_config

DEFAULT_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)s | %(correlation_id)s | %(message)s"
)
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


class CorrelationIdFilter(logging.Filter):
    """Inject the current correlation ID into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id_var.get("-")
        return True


def set_correlation_id(value: str) -> Token[str]:
    """Bind a correlation ID to the current context."""

    return _correlation_id_var.set(value)


def reset_correlation_id(token: Token[str]) -> None:
    """Restore the correlation ID context to a previous state."""

    _correlation_id_var.reset(token)


def get_correlation_id() -> str:
    """Retrieve the active correlation ID for the current context."""

    return _correlation_id_var.get("-")


def build_logging_dict(level: str) -> dict[str, Any]:
    """Create a dictionary config for Python's logging module."""

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": DEFAULT_FORMAT,
                "datefmt": DEFAULT_DATE_FORMAT,
            }
        },
        "filters": {
            "correlation": {
                "()": "app.core.logging.CorrelationIdFilter",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": level,
                "filters": ["correlation"],
            }
        },
        "loggers": {
            "": {
                "handlers": ["console"],
                "level": level,
            },
            "uvicorn": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": ["console"],
                "level": level,
                "propagate": False,
            },
        },
    }


def configure_logging(config: AppConfig | None = None) -> None:
    """Configure logging for the application."""

    config = config or get_config()
    logging.config.dictConfig(build_logging_dict(config.log_level))


def get_logger(name: str) -> logging.Logger:
    """Convenience helper for retrieving a logger."""

    return logging.getLogger(name)


__all__ = [
    "configure_logging",
    "get_logger",
    "set_correlation_id",
    "reset_correlation_id",
    "get_correlation_id",
]
