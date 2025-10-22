"""Logging configuration for the Brain Buddy backend."""
from __future__ import annotations

import logging
import logging.config
from typing import Any, Mapping

from .config import AppConfig, get_config

DEFAULT_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def build_logging_dict(level: str) -> Mapping[str, Any]:
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
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": level,
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


__all__ = ["configure_logging", "get_logger"]
