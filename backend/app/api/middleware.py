"""Custom FastAPI middleware for Brain Buddy."""

from __future__ import annotations

import uuid
from time import perf_counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import get_config
from app.core.logging import (
    REDACTED_PATH_MARKER,
    get_logger,
    reset_correlation_id,
    sanitize_log_path,
    set_correlation_id,
)

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensure every request-response cycle carries a correlation ID for tracing."""

    def __init__(self, app: ASGIApp, api_prefix: str | None = None) -> None:
        super().__init__(app)
        self.logger = get_logger(__name__)
        self.api_prefix = (
            api_prefix if api_prefix is not None else get_config().api_prefix
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = request.headers.get(CORRELATION_HEADER) or request.headers.get(
            "X-Request-ID"
        )
        correlation_id = incoming or uuid.uuid4().hex
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        start = perf_counter()
        # Computed once, before either log call. Both lines below log this
        # value and never `request.url.path`: one unsanitised call is a full
        # disclosure, and the exception line is the one most likely to be
        # forgotten and the one most likely to be pasted into a ticket.
        logged_path = sanitize_log_path(request.url.path, api_prefix=self.api_prefix)

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (perf_counter() - start) * 1000
            self.logger.exception(
                "api_request_failed method=%s path=%s duration_ms=%.1f",
                request.method,
                logged_path,
                duration_ms,
            )
            raise
        finally:
            reset_correlation_id(token)

        response.headers[CORRELATION_HEADER] = correlation_id
        duration_ms = (perf_counter() - start) * 1000
        log = self.logger.warning if response.status_code >= 400 else self.logger.info
        log(
            "api_request method=%s path=%s status=%s duration_ms=%.1f",
            request.method,
            logged_path,
            response.status_code,
            duration_ms,
        )
        return response


__all__ = [
    "CORRELATION_HEADER",
    "REDACTED_PATH_MARKER",
    "CorrelationIdMiddleware",
    "sanitize_log_path",
]
