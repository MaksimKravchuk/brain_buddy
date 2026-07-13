"""Exception handlers for API errors."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions import (
    BrainBuddyError,
    ConflictError,
    NotFoundError,
    RepositoryError,
    ValidationFailure,
)
from app.schemas import ErrorResponse

from .middleware import CORRELATION_HEADER


def register_exception_handlers(app: FastAPI) -> None:
    """Attach exception handlers for known error types."""

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(
            message="Request validation failed.",
            detail=exc.errors(),
            reference_id=correlation_id,
        )
        response = JSONResponse(
            status_code=422, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request, exc: HTTPException
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        detail = exc.detail if not isinstance(exc.detail, str) else None
        payload = ErrorResponse(
            message=str(exc.detail), detail=detail, reference_id=correlation_id
        )
        response = JSONResponse(
            status_code=exc.status_code,
            content=payload.model_dump(by_alias=True),
            headers=exc.headers,
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.exception_handler(NotFoundError)
    async def handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(
            message=str(exc),
            detail={"resource": exc.resource, "id": exc.identifier},
            reference_id=correlation_id,
        )
        response = JSONResponse(
            status_code=404, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.exception_handler(ConflictError)
    async def handle_conflict(request: Request, exc: ConflictError) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(
            message=str(exc),
            detail={"resource": exc.resource, "id": exc.identifier},
            reference_id=correlation_id,
        )
        response = JSONResponse(
            status_code=409, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.exception_handler(ValidationFailure)
    async def handle_validation_failure(
        request: Request, exc: ValidationFailure
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(
            message=str(exc),
            detail=getattr(exc, "detail", None),
            reference_id=correlation_id,
        )
        # Treat validation issues as bad requests rather than unprocessable
        # entity to align with contract.
        response = JSONResponse(
            status_code=400, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.exception_handler(RepositoryError)
    async def handle_repository_error(
        request: Request, exc: RepositoryError
    ) -> JSONResponse:  # pragma: no cover
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(
            message="Internal storage error.", reference_id=correlation_id
        )
        response = JSONResponse(
            status_code=500, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response

    @app.exception_handler(BrainBuddyError)
    async def handle_generic_error(
        request: Request, exc: BrainBuddyError
    ) -> JSONResponse:  # pragma: no cover
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(message=str(exc), reference_id=correlation_id)
        response = JSONResponse(
            status_code=400, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response
