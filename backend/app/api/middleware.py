"""Custom FastAPI middleware for Brain Buddy."""

from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import get_logger, reset_correlation_id, set_correlation_id

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensure every request-response cycle carries a correlation ID for tracing."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger(__name__)

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(CORRELATION_HEADER) or request.headers.get(
            "X-Request-ID"
        )
        correlation_id = incoming or uuid.uuid4().hex
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id

        try:
            response = await call_next(request)
        except Exception:
            self.logger.exception(
                "Unhandled exception for %s %s", request.method, request.url.path
            )
            raise
        finally:
            reset_correlation_id(token)

        response.headers[CORRELATION_HEADER] = correlation_id
        return response


__all__ = ["CorrelationIdMiddleware", "CORRELATION_HEADER"]
