"""Scoped Pydantic validation helpers for sensitive agent endpoint inputs."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from pydantic import ValidationError

_REDACTED = "[REDACTED]"


def sanitize_endpoint_input(
    model_name: str,
    data: object,
    endpoint_validator: Callable[[str], str],
) -> object:
    """Validate an endpoint without retaining its rejected value in diagnostics."""

    if not isinstance(data, Mapping) or "endpoint_url" not in data:
        return data

    endpoint = data["endpoint_url"]
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
                "loc": ("endpoint_url",),
                "input": _REDACTED,
                "ctx": {"error": ValueError(message)},
            }
        ],
        hide_input=True,
    )
    raise validation_error from None
