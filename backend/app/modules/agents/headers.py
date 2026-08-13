"""Validation for user-selected outbound credential header names."""

from __future__ import annotations

import re

from pydantic_core import PydanticCustomError

# RFC 9110 field-name = token. Keep this ASCII-explicit: Unicode letters are not
# valid HTTP field-name characters even when Python considers them alphanumeric.
_FIELD_NAME_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

# These names are populated, framed, routed, or interpreted by the relay and its
# HTTP transport. A credential name may not replace any of them, regardless of
# casing.
RESERVED_AUTH_HEADER_NAMES: frozenset[str] = frozenset(
    name.casefold()
    for name in (
        "Accept",
        "Authorization",
        "Connection",
        "Content-Length",
        "Content-Type",
        "Host",
        "Idempotency-Key",
        "Keep-Alive",
        "Proxy-Authenticate",
        "Proxy-Authorization",
        "TE",
        "Trailer",
        "Transfer-Encoding",
        "Upgrade",
        "User-Agent",
        "X-BrainBuddy-Run-Id",
    )
)


def validate_auth_header_name(value: str) -> str:
    """Return a safe credential field-name or raise ``ValueError``."""

    if _FIELD_NAME_TOKEN.fullmatch(value) is None:
        raise PydanticCustomError(
            "auth_header_name_invalid", "must be a valid HTTP field-name token"
        )
    if value.casefold() in RESERVED_AUTH_HEADER_NAMES:
        raise PydanticCustomError(
            "auth_header_name_reserved", "is reserved by the relay or HTTP transport"
        )
    return value


__all__ = ["RESERVED_AUTH_HEADER_NAMES", "validate_auth_header_name"]
