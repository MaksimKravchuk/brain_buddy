"""Destination-class safety for every outbound external-agent connection.

This module is the single choke point between BrainBuddy and a user-operated
agent. Nothing here trusts a hostname: a destination is refused unless its
*resolved* addresses are all publicly routable, and the eventual request is then
made against those pinned addresses so a second, hostile DNS answer cannot move
the connection somewhere else between the check and the connect (FR-004).

Redirects are never followed. Re-validating each hop would be possible, but a
connector that answers a signed, credential-bearing request with a redirect has
no legitimate need we must serve in v1, and refusing outright removes a whole
class of bypass.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

Resolver = Callable[[str, int], list[str]]

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_SECURE_SCHEME = "https"
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Every code here is safe to log and to show a user: none of them can encode a
# credential or relayed content (FR-017).
DESTINATION_INVALID = "destination_invalid"
DESTINATION_SCHEME_NOT_ALLOWED = "destination_scheme_not_allowed"
DESTINATION_NETWORK_NOT_ALLOWED = "destination_network_not_allowed"
DESTINATION_UNRESOLVABLE = "destination_unresolvable"
DESTINATION_REDIRECT_NOT_ALLOWED = "destination_redirect_not_allowed"


class DestinationRejected(ValueError):
    """A destination was refused before any credential or content was sent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ResolvedDestination:
    """A checked destination plus the exact addresses we may connect to."""

    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]

    @property
    def host_header(self) -> str:
        """The ``Host`` value to send when connecting to a pinned address."""

        if self.port == _DEFAULT_PORTS[self.scheme]:
            return self.host
        return f"{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class PinnedResponse:
    """A bounded response body plus its status, from a pinned connection."""

    status_code: int
    body: bytes


def _system_resolver(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise DestinationRejected(
            DESTINATION_UNRESOLVABLE, "The agent host could not be resolved."
        ) from exc
    return [str(info[4][0]) for info in infos]


def _normalize(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse an address, unwrapping IPv4-mapped IPv6 so it cannot hide a class."""

    # getaddrinfo can hand back a scoped literal such as ``fe80::1%eth0``.
    candidate = address.split("%", 1)[0]
    try:
        parsed = ipaddress.ip_address(candidate)
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        return parsed.ipv4_mapped
    return parsed


def _is_publicly_routable(address: str) -> bool:
    parsed = _normalize(address)
    if parsed is None:
        return False
    # ``is_global`` alone is close, but it does not exclude multicast for IPv4,
    # so each disallowed class is also named explicitly rather than inferred.
    return (
        parsed.is_global
        and not parsed.is_multicast
        and not parsed.is_loopback
        and not parsed.is_link_local
        and not parsed.is_private
        and not parsed.is_reserved
        and not parsed.is_unspecified
    )


def _split_destination(raw_url: str) -> tuple[str, str, int, str]:
    """Return ``(scheme, host, port, normalized_url)`` or refuse the input."""

    try:
        parts = urlsplit(raw_url.strip())
    except ValueError as exc:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint is not a valid URL."
        ) from exc

    if not parts.scheme:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint must be an absolute URL."
        )
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise DestinationRejected(
            DESTINATION_SCHEME_NOT_ALLOWED,
            "The agent endpoint must use HTTPS.",
        )

    if parts.username is not None or parts.password is not None:
        raise DestinationRejected(
            DESTINATION_INVALID,
            "The agent endpoint must not embed credentials in its URL.",
        )
    if parts.fragment:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint must not contain a fragment."
        )

    host = parts.hostname
    if not host:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint must name a host."
        )

    try:
        explicit_port = parts.port
    except ValueError as exc:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint port is not valid."
        ) from exc
    port = explicit_port if explicit_port is not None else _DEFAULT_PORTS[scheme]
    if not 1 <= port <= 65535:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint port is not valid."
        )

    normalized = urlunsplit((scheme, parts.netloc, parts.path, parts.query, ""))
    return scheme, host, port, normalized


def validate_destination(
    raw_url: str,
    *,
    allow_private_destinations: bool = False,
    resolver: Resolver | None = None,
) -> ResolvedDestination:
    """Check scheme and network class, then pin the addresses we may use.

    ``allow_private_destinations`` is the single governed deployment opt-in from
    FR-004/AC-005. It is what lets an operator point BrainBuddy at a connector on
    their own private network, and — because such a connector is typically a
    local development process without a public certificate — it is also what
    permits plaintext HTTP. An ordinary deployment leaves it off and neither is
    reachable.
    """

    resolve = resolver if resolver is not None else _system_resolver
    scheme, host, port, normalized = _split_destination(raw_url)

    if scheme != _SECURE_SCHEME and not allow_private_destinations:
        raise DestinationRejected(
            DESTINATION_SCHEME_NOT_ALLOWED,
            "The agent endpoint must use HTTPS.",
        )

    literal = _normalize(host)
    if literal is not None:
        addresses = [host]
    else:
        addresses = resolve(host, port)
        if not addresses:
            raise DestinationRejected(
                DESTINATION_UNRESOLVABLE, "The agent host could not be resolved."
            )

    for address in addresses:
        if _normalize(address) is None:
            raise DestinationRejected(
                DESTINATION_UNRESOLVABLE, "The agent host could not be resolved."
            )
        if not allow_private_destinations and not _is_publicly_routable(address):
            # Deliberately identical for a literal and for a name that resolves
            # inward: naming the resolved address back to the user would turn
            # this check into an internal-network scanner.
            raise DestinationRejected(
                DESTINATION_NETWORK_NOT_ALLOWED,
                "The agent endpoint must be a public address. Loopback, "
                "link-local, metadata, and private destinations are not allowed.",
            )

    return ResolvedDestination(
        url=normalized,
        scheme=scheme,
        host=host,
        port=port,
        addresses=tuple(addresses),
    )


def interactive_result_link(url: str) -> bool:
    """Whether an agent-reported link may be rendered as a clickable link.

    In v1 the answer is always no (FR-014). Displaying a run must never cause
    BrainBuddy to resolve or fetch an agent-controlled URL, so the only evidence
    available here is syntax — and syntax cannot answer the question that
    matters, which is where the *browser* will end up when the user clicks
    minutes later. A publicly-named host can answer with a loopback, private, or
    metadata address at click time, and a syntax-only allowance would hand that
    navigation the user's own browser context.

    The link is still shown; it is shown as inert text the user can read and
    copy deliberately. Widening this needs a real click-time guarantee, not a
    better parser.
    """

    return False


def _pinned_url(destination: ResolvedDestination, address: str) -> str:
    parts = urlsplit(destination.url)
    parsed = _normalize(address)
    assert parsed is not None  # validate_destination already proved this
    literal = f"[{address}]" if parsed.version == 6 else address
    return urlunsplit(
        (parts.scheme, f"{literal}:{destination.port}", parts.path, parts.query, "")
    )


def pinned_request(
    *,
    method: str,
    destination: ResolvedDestination,
    headers: Mapping[str, str],
    json_body: Any,
    timeout_seconds: float,
    max_response_bytes: int,
    client_factory: Callable[..., httpx.Client] | None = None,
) -> PinnedResponse:
    """Send one request to a pre-validated destination, over a pinned address.

    The connection is made to the address ``validate_destination`` approved,
    while SNI and certificate verification still use the original hostname — so
    a rebinding answer arriving between check and connect cannot redirect the
    credential. Redirects are refused and the response body is bounded.
    """

    factory = client_factory if client_factory is not None else httpx.Client
    address = destination.addresses[0]
    request_headers = {**dict(headers), "Host": destination.host_header}

    with (
        factory(timeout=timeout_seconds, follow_redirects=False) as client,
        client.stream(
            method,
            _pinned_url(destination, address),
            headers=request_headers,
            json=json_body,
            extensions={"sni_hostname": destination.host},
        ) as response,
    ):
        if 300 <= response.status_code < 400:
            raise DestinationRejected(
                DESTINATION_REDIRECT_NOT_ALLOWED,
                "The agent endpoint answered with a redirect, which is not "
                "followed for credential-bearing requests.",
            )
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > max_response_bytes:
                del body[max_response_bytes:]
                break
        return PinnedResponse(status_code=response.status_code, body=bytes(body))


__all__ = [
    "DESTINATION_INVALID",
    "DESTINATION_NETWORK_NOT_ALLOWED",
    "DESTINATION_REDIRECT_NOT_ALLOWED",
    "DESTINATION_SCHEME_NOT_ALLOWED",
    "DESTINATION_UNRESOLVABLE",
    "DestinationRejected",
    "PinnedResponse",
    "ResolvedDestination",
    "Resolver",
    "interactive_result_link",
    "pinned_request",
    "validate_destination",
]
