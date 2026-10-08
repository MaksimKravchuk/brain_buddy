"""Logging configuration for the Brain Buddy backend."""

from __future__ import annotations

import logging
import logging.config
import posixpath
import re
from contextvars import ContextVar, Token
from typing import Any, cast
from urllib.parse import unquote, urlsplit

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
_SAFE_UVICORN_MESSAGES = frozenset(
    {
        "Waiting for application startup.",
        "Application startup complete.",
        "Waiting for application shutdown.",
        "Application shutdown complete.",
        "Shutting down",
    }
)


def sanitize_log_path(path: str, *, api_prefix: str) -> str:
    """Hide auth query/fragment credentials and the A2A push path token.

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
        if not isinstance(path, str) or any(ord(char) < 32 for char in path):
            return REDACTED_PATH_MARKER
        parsed = urlsplit(path)
        if parsed.scheme == "brainbuddy" and parsed.hostname == "auth":
            return "brainbuddy://auth/callback"
        decoded = parsed.path
        for _ in range(3):
            candidate = unquote(decoded, errors="strict")
            if candidate == decoded:
                break
            decoded = candidate
        # Bound decoding work, but never treat a still-encoded credential
        # target as an unrelated URL and retain its raw query.
        if unquote(decoded, errors="strict") != decoded or any(
            ord(char) < 32 for char in decoded
        ):
            return REDACTED_PATH_MARKER
        decoded = decoded.split("?", 1)[0].split("#", 1)[0]
        normalized = posixpath.normpath(decoded)
        roots = (
            f"{api_prefix.rstrip('/')}/auth",
            f"{api_prefix.rstrip('/')}/account",
            "/auth",
            "/settings/account",
        )
        if any(
            normalized == root or normalized.startswith(root + "/") for root in roots
        ):
            return normalized
        marker = f"{api_prefix.rstrip('/')}{AGENT_PUSH_PATH}/"
        if not normalized.startswith(marker):
            return path
        run_id, separator, _token = normalized[len(marker) :].partition("/")
        if not separator:
            # No token segment yet. Inventing one would make a plain 404 look
            # like a redacted hit.
            return path
        return f"{marker}{run_id}/{REDACTED_PATH_MARKER}"
    except Exception:
        return REDACTED_PATH_MARKER


class PushCallbackAccessFilter(logging.Filter):
    """Protect auth targets and A2A tokens at the server logging edges.

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
        # configure_logging injects the settled configuration. Filtering must
        # never load config, touch data or resolve DNS while logging a failure.
        return self._api_prefix if self._api_prefix is not None else "/api"

    @staticmethod
    def _clear_details(record: logging.LogRecord) -> None:
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.__dict__.pop("color_message", None)
        record.__dict__.pop("message", None)
        correlation_id = getattr(record, "correlation_id", "-")
        # nginx supplies a random 32-hex ID and the application generates
        # UUIDs. An inbound header must not echo email, proof or log injection.
        if not isinstance(correlation_id, str) or not re.fullmatch(
            r"(?:-|[0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            correlation_id,
        ):
            record.correlation_id = REDACTED_PATH_MARKER

    @classmethod
    def _redact_record(cls, record: logging.LogRecord) -> None:
        record.msg = f"server_log_payload {REDACTED_PATH_MARKER}"
        record.args = ()
        cls._clear_details(record)

    @staticmethod
    def _valid_middleware_record(record: logging.LogRecord) -> bool:
        # Spec 021 added the ``client`` fields (before the duration); the
        # shorter shapes stay accepted.
        expected = {
            "api_request method=%s path=%s status=%s duration_ms=%.1f": 4,
            "api_request_failed method=%s path=%s duration_ms=%.1f": 3,
            "api_request method=%s path=%s status=%s "
            "client=%s client_version=%s duration_ms=%.1f": 6,
            "api_request_failed method=%s path=%s "
            "client=%s client_version=%s duration_ms=%.1f": 5,
        }
        if not isinstance(record.msg, str):
            return False
        fields = expected.get(record.msg)
        args = record.args
        if not isinstance(args, tuple) or len(args) != fields:
            return False
        if (
            not isinstance(args[0], str)
            or not re.fullmatch(r"[A-Z]{1,16}", args[0])
            or not isinstance(args[1], str)
            or not isinstance(args[-1], (int, float))
            or isinstance(args[-1], bool)
        ):
            return False
        if fields >= 5 and not (
            args[-3] in {"web", "ios", "macos", "other"}
            and isinstance(args[-2], str)
            and re.fullmatch(r"[0-9A-Za-z.+-]{1,32}", args[-2])
        ):
            return False
        return fields in (3, 5) or (
            isinstance(args[2], int)
            and not isinstance(args[2], bool)
            and 100 <= args[2] <= 599
        )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            args = record.args
            if record.name == "uvicorn.access":
                if (
                    record.msg != '%s - "%s %s HTTP/%s" %d'
                    or not isinstance(args, tuple)
                    or len(args) != 5
                    or not all(isinstance(value, str) for value in args[:4])
                    or not isinstance(args[4], int)
                    or isinstance(args[4], bool)
                    or not 100 <= args[4] <= 599
                ):
                    self._redact_record(record)
                    return True
                typed = cast(tuple[str, str, str, str, int], args)
                if (
                    not re.fullmatch(r"[0-9A-Fa-f:.\[\]-]+", typed[0])
                    or not re.fullmatch(r"[A-Z]{1,16}", typed[1])
                    or not re.fullmatch(r"[0-9](?:\.[0-9])?", typed[3])
                ):
                    self._redact_record(record)
                    return True
                mutable = list(typed)
                mutable[self._PATH_INDEX] = sanitize_log_path(
                    typed[2], api_prefix=self.api_prefix
                )
                record.args = tuple(mutable)
                self._clear_details(record)
            elif record.name == "app.api.middleware":
                if not self._valid_middleware_record(record):
                    self._redact_record(record)
                    return True
                middleware_args = cast(tuple[Any, ...], args)
                sanitized = sanitize_log_path(
                    middleware_args[1], api_prefix=self.api_prefix
                )
                mutable = list(middleware_args)
                mutable[1] = sanitized
                record.args = tuple(mutable)
                # The safe request message retains outcome/correlation data.
                # Auth handler exceptions may echo rejected assertions/inputs.
                if (
                    sanitized != middleware_args[1]
                    or "/auth" in sanitized
                    or "/account" in sanitized
                    or REDACTED_PATH_MARKER in sanitized
                ):
                    self._clear_details(record)
            elif record.name.startswith("uvicorn"):
                if (
                    not isinstance(record.msg, str)
                    or record.msg not in _SAFE_UVICORN_MESSAGES
                    or record.args
                    or record.exc_info
                    or record.exc_text
                    or record.stack_info
                ):
                    self._redact_record(record)
                else:
                    self._clear_details(record)
        except Exception:
            self._redact_record(record)
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


def build_logging_dict(level: str, *, api_prefix: str = "/api") -> dict[str, Any]:
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
            "push_callback": {
                "()": "app.core.logging.PushCallbackAccessFilter",
                "api_prefix": api_prefix,
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": level,
                "filters": ["correlation", "push_callback"],
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
    logging.config.dictConfig(
        build_logging_dict(config.log_level, api_prefix=config.api_prefix)
    )


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
