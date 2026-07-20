"""Reusable, explicit OpenAPI error-response definitions."""

from __future__ import annotations

from typing import Any

from app.schemas import ErrorResponse

_ERROR_DESCRIPTIONS = {
    400: "The command violates a domain invariant.",
    401: "Authentication is required or the session is invalid.",
    404: "The requested resource is absent or belongs to another owner.",
    409: "The request conflicts with the current resource state.",
    422: "The request path, query, or body does not match the API schema.",
    429: "Too many requests were made within the configured limit.",
    503: "The persistence layer is temporarily unavailable.",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Return the intentional error statuses for one public operation."""

    return {
        status_code: {
            "model": ErrorResponse,
            "description": _ERROR_DESCRIPTIONS[status_code],
        }
        for status_code in status_codes
    }
