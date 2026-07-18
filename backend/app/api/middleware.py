"""Custom FastAPI middleware for Brain Buddy."""

from __future__ import annotations

import uuid
from time import perf_counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.logging import get_logger, reset_correlation_id, set_correlation_id

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensure every request-response cycle carries a correlation ID for tracing."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger(__name__)

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

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (perf_counter() - start) * 1000
            self.logger.exception(
                "api_request_failed method=%s path=%s duration_ms=%.1f",
                request.method,
                request.url.path,
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
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


__all__ = ["CorrelationIdMiddleware", "CORRELATION_HEADER"]
