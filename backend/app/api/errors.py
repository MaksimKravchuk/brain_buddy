"""Exception handlers for API errors."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import (
    BrainBuddyError,
    ConflictError,
    NotFoundError,
    RepositoryError,
    ValidationFailure,
)
from app.schemas import ErrorResponse


def register_exception_handlers(app: FastAPI) -> None:
    """Attach exception handlers for known error types."""

    @app.exception_handler(NotFoundError)
    async def handle_not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        payload = ErrorResponse(
            message=str(exc), detail={"resource": exc.resource, "id": exc.identifier}
        )
        return JSONResponse(status_code=404, content=payload.model_dump())

    @app.exception_handler(ConflictError)
    async def handle_conflict(request: Request, exc: ConflictError) -> JSONResponse:
        payload = ErrorResponse(
            message=str(exc), detail={"resource": exc.resource, "id": exc.identifier}
        )
        return JSONResponse(status_code=409, content=payload.model_dump())

    @app.exception_handler(ValidationFailure)
    async def handle_validation_failure(
        request: Request, exc: ValidationFailure
    ) -> JSONResponse:
        payload = ErrorResponse(message=str(exc))
        # Treat validation issues as bad requests rather than unprocessable entity to align with contract.
        return JSONResponse(status_code=400, content=payload.model_dump())

    @app.exception_handler(RepositoryError)
    async def handle_repository_error(
        request: Request, exc: RepositoryError
    ) -> JSONResponse:  # pragma: no cover
        payload = ErrorResponse(message="Internal storage error.")
        return JSONResponse(status_code=500, content=payload.model_dump())

    @app.exception_handler(BrainBuddyError)
    async def handle_generic_error(
        request: Request, exc: BrainBuddyError
    ) -> JSONResponse:  # pragma: no cover
        payload = ErrorResponse(message=str(exc))
        return JSONResponse(status_code=400, content=payload.model_dump())
