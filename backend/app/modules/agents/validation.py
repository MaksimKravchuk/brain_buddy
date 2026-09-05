"""Scoped Pydantic validation helpers for sensitive agent endpoint inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import ValidationError

_REDACTED = "[REDACTED]"


def sanitize_endpoint_input(
    model_name: str,
    data: object,
    endpoint_validator: Callable[[str], str],
    *,
    field: str = "endpoint_url",
) -> object:
    """Validate an endpoint without retaining its rejected value in diagnostics.

    ``field`` exists because feature 014 renamed the *API* field to
    ``agent_address`` while deliberately keeping the *storage* key as
    ``endpoint_url`` (the 007 image must still parse a 014 row on rollback). One
    sanitiser serves both rather than two near-identical copies drifting apart.
    """

    if not isinstance(data, Mapping) or field not in data:
        return data

    endpoint = data[field]
    message: str | None = None
    if not isinstance(endpoint, str):
        message = "Input should be a valid string"
    else:
        try:
            if not 1 <= len(endpoint) <= 2_000:
                raise ValueError("agent endpoint is not a valid URL")
            endpoint_validator(endpoint)
        except ValueError as error:
            message = str(error)

    if message is None:
        return data

    validation_error = ValidationError.from_exception_data(
        model_name,
        [
            {
                "type": "value_error",
                "loc": (field,),
                "input": _REDACTED,
                "ctx": {"error": ValueError(message)},
            }
        ],
        hide_input=True,
    )
    raise validation_error from None
