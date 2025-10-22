"""Custom FastAPI middleware for Brain Buddy."""
from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.logging import get_logger, reset_correlation_id, set_correlation_id
from app.schemas import ErrorResponse

CORRELATION_HEADER = "X-Correlation-ID"


class ApiKeyMiddleware(BaseHTTPMiddleware):
    """Lightweight API key enforcement placeholder."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        api_key: str,
        header_name: str = "X-API-Key",
        exempt_paths: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(app)
        self.api_key = api_key
        self.header_name = header_name
        self.exempt_paths = exempt_paths or ("/health",)
        self.logger = get_logger(__name__)

    async def dispatch(self, request: Request, call_next):
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(exempt) for exempt in self.exempt_paths):
            return await call_next(request)

        provided = request.headers.get(self.header_name)
        if provided == self.api_key:
            return await call_next(request)

        self.logger.info("Blocked request without valid API key for %s", path)
        payload = ErrorResponse(message="Missing or invalid API key.", detail={"header": self.header_name})
        response = JSONResponse(status_code=401, content=payload.model_dump())
        response.headers["WWW-Authenticate"] = "API-Key"
        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Ensure every request-response cycle carries a correlation ID for tracing."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger(__name__)

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(CORRELATION_HEADER) or request.headers.get("X-Request-ID")
        correlation_id = incoming or uuid.uuid4().hex
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id

        try:
            response = await call_next(request)
        except Exception:
            self.logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
            raise
        finally:
            reset_correlation_id(token)

        response.headers[CORRELATION_HEADER] = correlation_id
        return response


__all__ = ["ApiKeyMiddleware", "CorrelationIdMiddleware", "CORRELATION_HEADER"]
