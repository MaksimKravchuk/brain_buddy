"""Logging configuration for the Brain Buddy backend."""

from __future__ import annotations

import logging
import logging.config
from contextvars import ContextVar, Token
from typing import Any

from .config import AGENT_PUSH_PATH, AppConfig, get_config

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


REDACTED_PATH_MARKER = "[redacted]"


def sanitize_log_path(path: str, *, api_prefix: str) -> str:
    """Hide the A2A push token in a request path before it is logged.

    The token has to travel in the path -- Hermes stores only the URL of a push
    config and signs with a secret BrainBuddy cannot know, so a header-only
    token would leave its pushes unverifiable (research.md Decision D). An
    agent's own logs are outside our control and the token's power is bounded
    by design: it can trigger one authenticated observation BrainBuddy would
    perform anyway. Repeating it in *our* logs, though, would be a disclosure we
    chose, so it is removed at the two in-process edges that see it -- this
    module's ``uvicorn.access`` filter and ``CorrelationIdMiddleware``.

    It lives here rather than beside the middleware so the filter below can use
    it without importing upward into ``app.api``.

    The run id is deliberately kept: it is what makes the line useful to whoever
    is reading it, and it is not the secret.

    Pure, total, and never raises. This runs inside a logging call on the
    request's exception path, and a sanitiser that could raise would turn a
    redaction into a 500 exactly when something has already gone wrong.
    """

    try:
        marker = f"{api_prefix.rstrip('/')}{AGENT_PUSH_PATH}/"
        if not path.startswith(marker):
            return path
        run_id, separator, _token = path[len(marker) :].partition("/")
        if not separator:
            # No token segment yet. Inventing one would make a plain 404 look
            # like a redacted hit.
            return path
        return f"{marker}{run_id}/{REDACTED_PATH_MARKER}"
    except Exception:  # pragma: no cover - defensive; the body cannot raise
        return REDACTED_PATH_MARKER


class PushCallbackAccessFilter(logging.Filter):
    """Strip the A2A push token from ``uvicorn.access`` lines (spec 014).

    ``CorrelationIdMiddleware`` sanitises BrainBuddy's own request log, but
    uvicorn writes an access line of its own *below* the middleware, and this
    module routes ``uvicorn.access`` to the same console handler. Without this
    filter a token redacted one line up would be printed verbatim the next.

    uvicorn's record shape is not something BrainBuddy controls across versions,
    so every access is defensive: a logging filter that raises takes the log
    with it, and a log that dies during a push flood is the worst possible time
    to lose one.
    """

    #: Position of the request path in uvicorn's access-log args tuple
    #: ``(client_addr, method, full_path, http_version, status_code)``.
    _PATH_INDEX = 2

    def __init__(self, api_prefix: str | None = None) -> None:
        super().__init__()
        self._api_prefix = api_prefix

    @property
    def api_prefix(self) -> str:
        if self._api_prefix is None:
            # Resolved lazily, not at construction: the logging dict is built
            # during startup, and reading configuration while it is being
            # assembled would fix the prefix before it is settled.
            self._api_prefix = get_config().api_prefix
        return self._api_prefix

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if not isinstance(args, tuple) or len(args) <= self._PATH_INDEX:
                return True
            path = args[self._PATH_INDEX]
            if not isinstance(path, str):
                return True
            sanitized = sanitize_log_path(path, api_prefix=self.api_prefix)
            if sanitized != path:
                mutable = list(args)
                mutable[self._PATH_INDEX] = sanitized
                record.args = tuple(mutable)
        except Exception:  # pragma: no cover - a filter must never break logging
            return True
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
            },
            # Attached to `uvicorn.access` below rather than to the handler: a
            # filter on the handler would also see every application record and
            # pay its cost for nothing.
            "push_callback": {
                "()": "app.core.logging.PushCallbackAccessFilter",
            },
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
                # Spec 014, SC-009: uvicorn writes its own access line below
                # the middleware, so the push token has to be removed here too.
                "filters": ["push_callback"],
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
    "REDACTED_PATH_MARKER",
    "PushCallbackAccessFilter",
    "sanitize_log_path",
    "configure_logging",
    "get_logger",
    "set_correlation_id",
    "reset_correlation_id",
    "get_correlation_id",
]
