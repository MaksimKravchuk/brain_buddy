"""Validation for the outbound credential header name a card may name.

Under the A2A wire contract this name is never typed by a person: it is copied
off the agent's own card for an ``api_key`` connection, and a bearer connection
has none at all. That makes this module's job narrower and sharper than it was —
it is the one place that decides whether a *stranger's card* may put a value
into a header BrainBuddy's own transport populates (spec 014, FR-001, FR-004).
"""

from __future__ import annotations

import re

from pydantic_core import PydanticCustomError

# RFC 9110 field-name = token. Keep this ASCII-explicit: Unicode letters are not
# valid HTTP field-name characters even when Python considers them alphanumeric.
_FIELD_NAME_TOKEN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")

# These names are populated, framed, routed, or interpreted by the relay and its
# HTTP transport. A credential name may not replace any of them, regardless of
# casing.
#
# Two groups, and the distinction matters. The first is transport-structural:
# letting a card choose `Content-Length` or `Transfer-Encoding` is request
# smuggling, and letting it choose `Authorization` would let an API-key card
# overwrite the bearer header the client derives from the scheme. The second is
# the A2A protocol's own headers, which BrainBuddy sets on every call: a card
# that captured `A2A-Extensions` could suppress the single-start activation and
# silently downgrade its own guarantee.
#
# `Idempotency-Key` and `X-BrainBuddy-Run-Id` are gone: both belonged to the
# bespoke 007 outbound envelope, which no longer exists. Reserving a header no
# request carries would refuse a legitimate card for a collision that cannot
# happen.
RESERVED_AUTH_HEADER_NAMES: frozenset[str] = frozenset(
    name.casefold()
    for name in (
        # Transport-structural.
        "Accept",
        "Authorization",
        "Connection",
        "Content-Length",
        "Content-Type",
        "Host",
        "Keep-Alive",
        "Proxy-Authenticate",
        "Proxy-Authorization",
        "TE",
        "Trailer",
        "Transfer-Encoding",
        "Upgrade",
        "User-Agent",
        # The A2A wire's own headers (contracts/a2a-wire.md).
        "A2A-Version",
        "A2A-Extensions",
        "X-Correlation-ID",
    )
)


def is_reserved_auth_header_name(value: str) -> bool:
    """Whether a name collides with one the relay or its transport owns."""

    return value.casefold() in RESERVED_AUTH_HEADER_NAMES


def usable_auth_header_name(value: str | None) -> str | None:
    """A card-sourced header name BrainBuddy may send, or ``None``.

    The non-raising counterpart of ``validate_auth_header_name``: discovery
    turns an unusable name into the ``a2a_auth_scheme_unsupported`` category the
    owner can act on, and an exception would have to be caught and translated at
    every call site to say the same thing.
    """

    if not value:
        return None
    if is_reserved_auth_header_name(value):
        return None
    if _FIELD_NAME_TOKEN.fullmatch(value) is None:
        return None
    return value


def validate_auth_header_name(value: str) -> str:
    """Return a safe credential field-name or raise ``ValueError``."""

    if _FIELD_NAME_TOKEN.fullmatch(value) is None:
        raise PydanticCustomError(
            "auth_header_name_invalid", "must be a valid HTTP field-name token"
        )
    if is_reserved_auth_header_name(value):
        raise PydanticCustomError(
            "auth_header_name_reserved", "is reserved by the relay or HTTP transport"
        )
    return value


__all__ = [
    "RESERVED_AUTH_HEADER_NAMES",
    "is_reserved_auth_header_name",
    "usable_auth_header_name",
    "validate_auth_header_name",
]
