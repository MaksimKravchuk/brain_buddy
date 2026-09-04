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
import re
import socket
import time
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from .authority import validate_endpoint_authority

Resolver = Callable[[str, int], list[str]]
DecoderFactory = Callable[[str], Any]

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_SECURE_SCHEME = "https"
_DEFAULT_PORTS = {"http": 80, "https": 443}

# Compressed responses have budgets independent of decoded output.  A valid
# payload may have framing overhead even when the configured decoded cap is
# zero, so raw input gets 64 KiB of fixed headroom; it may otherwise be at most
# the decoded cap plus that headroom. Network chunk boundaries are deliberately
# irrelevant: transports may partition the same bytes in any number of chunks.
_COMPRESSED_RAW_HEADROOM_BYTES = 64 * 1024
_MAX_DECOMPRESS_CALLS = 128
_ASCII_PATH_RE = re.compile(r"(?:/(?:[A-Za-z0-9._~!$&'()*+,;=:@%-])*)*")


# Every code here is safe to log and to show a user: none of them can encode a
# credential or relayed content (FR-017).
DESTINATION_INVALID = "destination_invalid"
DESTINATION_SCHEME_NOT_ALLOWED = "destination_scheme_not_allowed"
DESTINATION_NETWORK_NOT_ALLOWED = "destination_network_not_allowed"
DESTINATION_UNRESOLVABLE = "destination_unresolvable"
DESTINATION_REDIRECT_NOT_ALLOWED = "destination_redirect_not_allowed"
DESTINATION_DEADLINE_EXCEEDED = "destination_deadline_exceeded"


class DestinationRejected(ValueError):
    """A destination or its response was refused at a known delivery phase."""

    def __init__(
        self, code: str, message: str, *, delivery_attempted: bool = False
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.delivery_attempted = delivery_attempted


class EgressDeadlineExceeded(Exception):
    """One request outlived its absolute wall-clock deadline (spec 014).

    Deliberately **not** a ``DestinationRejected``. The two mean different
    things and map to different run states: a rejection says BrainBuddy refused
    to talk to the address at all, a deadline breach says it talked and got no
    answer in time. Collapsing them would let an exchange timeout be reported as
    "not sent" — the one claim that must never be made when the message may
    already be sitting at the agent. Every caller therefore has to decide:
    exchange ⇒ delivery unconfirmed (lookup before any resend), observation ⇒
    contact not refreshed, cancel ⇒ unconfirmed, test ⇒ unreachable.
    """

    code = DESTINATION_DEADLINE_EXCEEDED

    def __init__(
        self,
        message: str,
        *,
        deadline_seconds: float,
        elapsed_seconds: float,
        delivery_attempted: bool = True,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.deadline_seconds = deadline_seconds
        self.elapsed_seconds = elapsed_seconds
        self.delivery_attempted = delivery_attempted


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

        host = f"[{self.host}]" if ":" in self.host else self.host
        if self.port == _DEFAULT_PORTS[self.scheme]:
            return host
        return f"{host}:{self.port}"


@dataclass(frozen=True, slots=True)
class PinnedResponse:
    """A bounded response body plus its status, from a pinned connection."""

    status_code: int
    body: bytes


def _system_resolver(host: str, port: int) -> list[str]:
    failed = False
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        failed = True
        infos = []
    if failed:
        raise DestinationRejected(
            DESTINATION_UNRESOLVABLE, "The agent host could not be resolved."
        )
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


def _is_governed_private(address: str) -> bool:
    """Whether policy may opt this address into private connector egress."""

    parsed = _normalize(address)
    if parsed is None:
        return False
    return (
        (parsed.is_private or parsed.is_loopback)
        and not parsed.is_link_local
        and not parsed.is_multicast
        and not parsed.is_reserved
        and not parsed.is_unspecified
    )


def _split_destination(raw_url: str) -> tuple[str, str, int, str]:
    """Return ``(scheme, host, port, normalized_url)`` or refuse the input."""

    if (
        any(not 0x21 <= ord(character) <= 0x7E for character in raw_url)
        or "\\" in raw_url
    ):
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint is not a valid URL."
        )
    if "#" in raw_url:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint must not contain a fragment."
        )
    try:
        parts = urlsplit(raw_url)
    except ValueError:
        parts = None
    if parts is None:
        rejection = DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint is not a valid URL."
        )
        raise rejection from None

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
    if "?" in raw_url:
        raise DestinationRejected(
            DESTINATION_INVALID,
            "The agent endpoint must not contain a query string.",
        )
    host = parts.hostname
    if not host:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint must name a host."
        )
    authority_rejection: DestinationRejected | None
    try:
        validate_endpoint_authority(parts.netloc, host)
    except ValueError:
        authority_rejection = DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint is not a valid URL."
        )
    else:
        authority_rejection = None
    if authority_rejection is not None:
        raise authority_rejection from None
    if _ASCII_PATH_RE.fullmatch(parts.path) is None or re.search(
        r"%(?![0-9A-Fa-f]{2})", parts.path
    ):
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint is not a valid URL."
        )

    explicit_port = None
    invalid_port = True
    try:
        explicit_port = parts.port
    except ValueError:
        pass
    else:
        invalid_port = False
    if invalid_port:
        rejection = DestinationRejected(
            DESTINATION_INVALID, "The agent endpoint port is not valid."
        )
        raise rejection from None
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
    FR-004/AC-005. It permits private/loopback connectors and permits HTTP only
    for those explicitly governed local classes. Public destinations remain
    HTTPS-only even when the private-network policy is enabled.
    """

    resolve = resolver if resolver is not None else _system_resolver
    scheme, host, port, normalized = _split_destination(raw_url)

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
        publicly_routable = _is_publicly_routable(address)
        governed_private = _is_governed_private(address)
        if not publicly_routable and not (
            allow_private_destinations and governed_private
        ):
            # Deliberately identical for a literal and for a name that resolves
            # inward: naming the resolved address back to the user would turn
            # this check into an internal-network scanner.
            raise DestinationRejected(
                DESTINATION_NETWORK_NOT_ALLOWED,
                "The agent endpoint must be a public address. Loopback, "
                "link-local, metadata, and private destinations are not allowed.",
            )

    if scheme != _SECURE_SCHEME and not (
        allow_private_destinations
        and all(_is_governed_private(address) for address in addresses)
    ):
        raise DestinationRejected(
            DESTINATION_SCHEME_NOT_ALLOWED,
            "The agent endpoint must use HTTPS unless it is an explicitly "
            "governed private or loopback destination.",
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
    decoder_factory: DecoderFactory | None = None,
    deadline_seconds: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> PinnedResponse:
    """Send one request to a pre-validated destination, over a pinned address.

    The connection is made to the address ``validate_destination`` approved,
    while SNI and certificate verification still use the original hostname — so
    a rebinding answer arriving between check and connect cannot redirect the
    credential. Redirects are refused and the response body is bounded.

    ``deadline_seconds`` adds an **absolute wall-clock** bound on the whole
    exchange, enforced here rather than left to httpx. It has to be: an httpx
    read timeout is per *chunk*, so a server emitting one byte every few hundred
    seconds never trips it, and the byte budget below bounds bytes rather than
    time. Between them a drip-feeding agent holds a worker open indefinitely
    while every configured limit reports itself satisfied. On breach the stream
    is closed — the resource being protected is a bounded pool worker, not
    memory — and :class:`EgressDeadlineExceeded` is raised.

    ``monotonic`` is injectable so the behaviour is testable without a suite
    that waits five minutes to find out whether a clock works.
    """

    factory = client_factory if client_factory is not None else httpx.Client
    address = destination.addresses[0]
    request_headers = {**dict(headers), "Host": destination.host_header}
    started = monotonic()

    def enforce_deadline() -> None:
        if deadline_seconds is None:
            return
        elapsed = monotonic() - started
        if elapsed > deadline_seconds:
            raise EgressDeadlineExceeded(
                "The agent did not answer within the allowed time.",
                deadline_seconds=deadline_seconds,
                elapsed_seconds=elapsed,
            )

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
        # Checked before the body is touched: an agent that accepts the
        # connection and then says nothing has already spent the window.
        enforce_deadline()
        if 300 <= response.status_code < 400:
            raise DestinationRejected(
                DESTINATION_REDIRECT_NOT_ALLOWED,
                "The agent endpoint answered with a redirect, which is not "
                "followed for credential-bearing requests.",
                delivery_attempted=True,
            )
        try:
            body = _bounded_response_body(
                response,
                max_response_bytes=max_response_bytes,
                decoder_factory=decoder_factory,
                enforce_deadline=enforce_deadline if deadline_seconds else None,
            )
        except DestinationRejected as exc:
            raise DestinationRejected(
                exc.code, exc.message, delivery_attempted=True
            ) from None
        return PinnedResponse(status_code=response.status_code, body=bytes(body))


def _default_decoder(encoding: str) -> Any:
    if encoding == "gzip":
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj()
    raise DestinationRejected(
        DESTINATION_INVALID, "The agent response encoding is not supported."
    )


def _bounded_response_body(
    response: httpx.Response,
    *,
    max_response_bytes: int,
    decoder_factory: DecoderFactory | None,
    enforce_deadline: Callable[[], None] | None = None,
) -> bytearray:
    """Read raw bytes and cap each decompressor allocation before it happens.

    ``enforce_deadline`` is called once per network chunk. That is the only
    place a drip-feeding server can be caught: every chunk restarts httpx's read
    timeout, so time is never exceeded from httpx's point of view, and the byte
    budget is never exceeded from the body's.
    """

    encoding = response.headers.get("content-encoding", "").strip().lower()
    body = bytearray()
    if hasattr(response, "_content"):
        # httpx may have already decoded an encoded preloaded response, making
        # the original framing unavailable for integrity and bomb checks.
        if encoding and encoding != "identity":
            raise DestinationRejected(
                DESTINATION_INVALID, "The agent response body is not valid."
            )
        if len(response.content) > max_response_bytes:
            raise DestinationRejected(
                DESTINATION_INVALID, "The agent response body is not valid."
            )
        body.extend(response.content)
        return body
    decoder = None
    if encoding and encoding != "identity":
        decoder = (decoder_factory or _default_decoder)(encoding)
    raw_budget = max_response_bytes + _COMPRESSED_RAW_HEADROOM_BYTES
    raw_bytes = 0
    decompress_calls = 0
    compressed = bytearray()
    zlib_failed = False
    try:
        for raw_chunk in response.iter_raw():
            if enforce_deadline is not None:
                try:
                    enforce_deadline()
                except EgressDeadlineExceeded:
                    # Close before propagating: the socket is what the deadline
                    # exists to release, and leaving it to a finaliser would let
                    # a bounded worker stay held for an unbounded time.
                    response.close()
                    raise
            if decoder is None:
                if len(body) + len(raw_chunk) > max_response_bytes:
                    raise DestinationRejected(
                        DESTINATION_INVALID, "The agent response body is not valid."
                    )
                body.extend(raw_chunk)
                continue
            raw_bytes += len(raw_chunk)
            if raw_bytes > raw_budget:
                raise DestinationRejected(
                    DESTINATION_INVALID, "The agent response body is not valid."
                )
            compressed.extend(raw_chunk)
        for offset in range(0, len(compressed), 64 * 1024):
            assert decoder is not None
            remaining = max_response_bytes - len(body)
            pending = bytes(compressed[offset : offset + 64 * 1024])
            while pending:
                decompress_calls += 1
                if decompress_calls > _MAX_DECOMPRESS_CALLS:
                    raise DestinationRejected(
                        DESTINATION_INVALID, "The agent response body is not valid."
                    )
                request_size = min(remaining + 1, 64 * 1024)
                decoded = decoder.decompress(pending, request_size)
                if len(decoded) > remaining:
                    raise DestinationRejected(
                        DESTINATION_INVALID, "The agent response body is not valid."
                    )
                body.extend(decoded)
                remaining = max_response_bytes - len(body)
                pending = decoder.unconsumed_tail
                if decoder.unused_data:
                    raise DestinationRejected(
                        DESTINATION_INVALID, "The agent response body is not valid."
                    )
        if decoder is not None:
            if not decoder.eof:
                raise DestinationRejected(
                    DESTINATION_INVALID, "The agent response body is not valid."
                )
            remaining = max_response_bytes - len(body)
            flushed = decoder.flush(min(remaining + 1, 64 * 1024))
            if len(flushed) > remaining:
                raise DestinationRejected(
                    DESTINATION_INVALID, "The agent response body is not valid."
                )
            body.extend(flushed)
    except zlib.error:
        zlib_failed = True
    if zlib_failed:
        raise DestinationRejected(
            DESTINATION_INVALID, "The agent response body is not valid."
        )
    return body


__all__ = [
    "DESTINATION_INVALID",
    "DESTINATION_NETWORK_NOT_ALLOWED",
    "DESTINATION_REDIRECT_NOT_ALLOWED",
    "DESTINATION_SCHEME_NOT_ALLOWED",
    "DESTINATION_DEADLINE_EXCEEDED",
    "DESTINATION_UNRESOLVABLE",
    "DestinationRejected",
    "EgressDeadlineExceeded",
    "PinnedResponse",
    "ResolvedDestination",
    "Resolver",
    "interactive_result_link",
    "pinned_request",
    "validate_destination",
]
