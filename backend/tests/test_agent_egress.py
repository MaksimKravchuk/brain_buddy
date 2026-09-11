"""Destination-class safety for outbound external-agent traffic (FR-004, FR-014).

Every one of these cases must be decided *before* a credential or task content
ever reaches a socket, so they exercise ``validate_destination`` directly with an
injected resolver rather than touching the network.
"""

from __future__ import annotations

import gzip
import socket
import traceback
import zlib
from typing import Any

import httpx
import pytest

from app.modules.agents.egress import (
    DestinationRejected,
    EgressDeadlineExceeded,
    _bounded_response_body,
    interactive_result_link,
    pinned_request,
    validate_destination,
)


def _resolver(mapping: dict[str, list[str]]):
    def resolve(host: str, port: int) -> list[str]:
        try:
            return mapping[host]
        except KeyError:  # pragma: no cover - guards test-fixture mistakes
            raise DestinationRejected(
                "destination_unresolvable", "Host could not be resolved."
            ) from None

    return resolve


PUBLIC = _resolver({"agent.example.com": ["93.184.216.34"]})
ASCII_URL_CONTROLS = [*(chr(codepoint) for codepoint in range(0x20)), "\x7f"]


@pytest.mark.parametrize(
    "authority",
    [
        "agent.example.com:",
        "127.1",
        "2130706433",
        "0x7f.0.0.1",
        "0x7f000001",
        "0x7f.1",
        "127.0x0.0.1",
        "999.999.999.999",
        "127.000.000.001",
        f"{'a' * 64}.example.com",
        f"{'a' * 63}.{'b' * 63}.{'c' * 63}.{'d' * 62}",
        "two..labels.example",
        "bad_host.example",
        "-leading.example",
        "trailing-.example",
        "[fe80::1%25eth0]",
        "agent.example.com/bad%escape",
    ],
)
def test_invalid_authority_grammar_is_rejected_before_resolution(
    authority: str,
) -> None:
    resolution_attempts = 0

    def resolver(host: str, port: int) -> list[str]:
        nonlocal resolution_attempts
        resolution_attempts += 1
        return ["93.184.216.34"]

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(f"https://{authority}/hooks", resolver=resolver)

    assert excinfo.value.code == "destination_invalid"
    assert resolution_attempts == 0
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


@pytest.mark.parametrize(
    ("url", "expected_host", "expected_port"),
    [
        ("https://93.184.216.34/hooks", "93.184.216.34", 443),
        ("https://[2606:4700:4700::1111]/hooks", "2606:4700:4700::1111", 443),
        (
            "https://[2606:4700:4700::1111]:8443/hooks",
            "2606:4700:4700::1111",
            8443,
        ),
        ("https://agent.example.com:8443/hooks", "agent.example.com", 8443),
        (f"https://{'a' * 63}.example.com/hooks", f"{'a' * 63}.example.com", 443),
    ],
)
def test_canonical_bounded_authorities_are_accepted(
    url: str, expected_host: str, expected_port: int
) -> None:
    resolved = validate_destination(
        url,
        resolver=_resolver(
            {
                "agent.example.com": ["93.184.216.34"],
                f"{'a' * 63}.example.com": ["93.184.216.34"],
            }
        ),
    )

    assert resolved.host == expected_host
    assert resolved.port == expected_port
    if ":" in expected_host and expected_port != 443:
        assert resolved.host_header == f"[{expected_host}]:{expected_port}"


def test_public_https_destination_is_accepted_and_pinned() -> None:
    """A public HTTPS destination resolves to pinned addresses."""

    resolved = validate_destination(
        "https://agent.example.com/hooks/start", resolver=PUBLIC
    )

    assert resolved.host == "agent.example.com"
    assert resolved.port == 443
    assert resolved.addresses == ("93.184.216.34",)
    assert resolved.url == "https://agent.example.com/hooks/start"


def test_plaintext_http_is_refused_for_credential_bearing_traffic() -> None:
    """Plain HTTP is refused so credentials never cross the wire in the clear."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination("http://agent.example.com/hooks", resolver=PUBLIC)

    assert excinfo.value.code == "destination_scheme_not_allowed"


@pytest.mark.parametrize(
    "scheme",
    ["file", "gopher", "ftp", "data", "javascript"],
)
def test_non_http_schemes_are_refused(scheme: str) -> None:
    """Only HTTPS may ever carry relayed content."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(f"{scheme}://agent.example.com/x", resolver=PUBLIC)

    assert excinfo.value.code == "destination_scheme_not_allowed"


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/hooks",
        "https://localhost/hooks",
        "https://169.254.169.254/latest/meta-data/",
        "https://10.1.2.3/hooks",
        "https://192.168.1.10/hooks",
        "https://172.16.4.5/hooks",
        "https://[::1]/hooks",
        "https://[fd00::1]/hooks",
        "https://[fe80::1]/hooks",
        "https://[::ffff:127.0.0.1]/hooks",
        "https://0.0.0.0/hooks",
        "https://[::]/hooks",
    ],
)
def test_disallowed_network_classes_are_refused(url: str) -> None:
    """Loopback, link-local, metadata, and private destinations are refused."""

    resolver = _resolver({"localhost": ["127.0.0.1"]})
    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(url, resolver=resolver)

    assert excinfo.value.code == "destination_network_not_allowed"


def test_dns_name_resolving_into_a_private_range_is_refused() -> None:
    """A public-looking name that resolves inward is a rebinding attempt."""

    resolver = _resolver({"sneaky.example.com": ["169.254.169.254"]})
    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination("https://sneaky.example.com/hooks", resolver=resolver)

    assert excinfo.value.code == "destination_network_not_allowed"


def test_any_disallowed_address_in_a_multi_record_answer_refuses_the_whole_host() -> (
    None
):
    """One inward address poisons the whole answer; we never pick a 'safe' one."""

    resolver = _resolver({"mixed.example.com": ["93.184.216.34", "10.0.0.9"]})
    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination("https://mixed.example.com/hooks", resolver=resolver)

    assert excinfo.value.code == "destination_network_not_allowed"


def test_unresolvable_host_is_reported_as_unresolvable() -> None:
    """An unknown host is distinguishable from an unsafe one."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination("https://nowhere.example.com/hooks", resolver=PUBLIC)

    assert excinfo.value.code == "destination_unresolvable"


def test_system_dns_failure_is_translated_without_leaking_socket_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default DNS errors become the bounded external-agent rejection contract."""

    def fail_resolution(*args: object, **kwargs: object) -> object:
        raise OSError("sensitive resolver detail")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination("https://missing.example.com/hooks")

    assert excinfo.value.code == "destination_unresolvable"
    assert "sensitive resolver detail" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


def test_system_dns_answers_are_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """The non-injected resolver preserves every validated socket address."""

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )

    resolved = validate_destination("https://agent.example.com/hooks")

    assert resolved.addresses == ("93.184.216.34",)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@agent.example.com/hooks",
        "https://agent.example.com:0/hooks",
        "https://agent.example.com:not-a-port/hooks",
        "https://[::1/hooks",
        "https:///hooks",
        "not-a-url",
        "https://agent.example.com/hooks#fragment",
        "https://agent.example.com/hooks#",
        "https://agent.example.com/ho\noks",
        "https://agent.example.com/ho\roks",
        "https://agent.example.com/ho\toks",
    ],
)
def test_malformed_or_credential_bearing_urls_are_refused(url: str) -> None:
    """Embedded credentials, missing hosts, and fragments are refused outright."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(url, resolver=PUBLIC)

    assert excinfo.value.code == "destination_invalid"


def test_parser_rejection_is_constant_and_does_not_chain_secret_details() -> None:
    """Malformed URL values cannot enter the egress error or traceback chain."""

    secret = "parser" + "-secret"
    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(
            f"https://agent.example.com:{secret}/hooks", resolver=PUBLIC
        )

    assert str(excinfo.value) == "The agent endpoint port is not valid."
    rendered = "".join(
        traceback.format_exception(
            type(excinfo.value), excinfo.value, excinfo.value.__traceback__
        )
    )
    assert "parser-secret" not in str(excinfo.value)
    assert "parser-secret" not in repr(excinfo.value)
    assert "parser-secret" not in rendered
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None
    assert excinfo.value.__suppress_context__ is True


@pytest.mark.parametrize("whitespace", [" ", "\u00a0"])
@pytest.mark.parametrize("position", ["leading", "trailing"])
def test_literal_outer_whitespace_is_rejected_before_urlsplit_normalizes_it(
    whitespace: str, position: str
) -> None:
    endpoint = "https://agent.example.com/hooks"
    raw_url = whitespace + endpoint if position == "leading" else endpoint + whitespace
    resolution_attempts = 0

    def resolver(host: str, port: int) -> list[str]:
        nonlocal resolution_attempts
        resolution_attempts += 1
        return ["93.184.216.34"]

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(raw_url, resolver=resolver)

    assert excinfo.value.code == "destination_invalid"
    assert resolution_attempts == 0


@pytest.mark.parametrize("control", ASCII_URL_CONTROLS)
@pytest.mark.parametrize("position", ["leading", "embedded", "trailing"])
def test_every_literal_ascii_control_is_rejected_by_egress(
    control: str, position: str
) -> None:
    """C0 and DEL never reach URL normalization, resolution, or network I/O."""

    endpoint_parts = {
        "leading": (control, "https://agent.example.com/hooks"),
        "embedded": ("https://agent.example.com/ho", control, "oks"),
        "trailing": ("https://agent.example.com/hooks", control),
    }
    resolution_attempts = 0

    def resolver(host: str, port: int) -> list[str]:
        nonlocal resolution_attempts
        resolution_attempts += 1
        return ["93.184.216.34"]

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination("".join(endpoint_parts[position]), resolver=resolver)

    assert excinfo.value.code == "destination_invalid"
    assert str(excinfo.value) == "The agent endpoint is not a valid URL."
    assert resolution_attempts == 0


@pytest.mark.parametrize(
    "unsafe",
    [
        "https://agent.example.com/space here",
        "https://agent.example.com\\hooks",
        "https://agent.example.com/zero\u200bwidth",
        "https://éxample.com/hooks",
        "https://agent.example.com/café",
    ],
)
def test_non_ascii_space_and_backslash_url_syntax_never_reaches_resolution(
    unsafe: str,
) -> None:
    resolution_attempts = 0

    def resolver(host: str, port: int) -> list[str]:
        nonlocal resolution_attempts
        resolution_attempts += 1
        return ["93.184.216.34"]

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(unsafe, resolver=resolver)

    assert excinfo.value.code == "destination_invalid"
    assert resolution_attempts == 0


@pytest.mark.parametrize(
    "url",
    [
        "https://agent.example.com/hooks?token=secret",
        "https://agent.example.com/hooks?X-Amz-Signature=signed-secret",
        "https://agent.example.com/hooks?one=1&two=2",
        "https://agent.example.com/hooks?",
    ],
)
def test_query_strings_are_refused_before_dns_or_network_io(url: str) -> None:
    """Secret-bearing endpoint queries never reach resolution or a connector."""

    resolution_attempts = 0

    def resolver(host: str, port: int) -> list[str]:
        nonlocal resolution_attempts
        resolution_attempts += 1
        return ["93.184.216.34"]

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(url, resolver=resolver)

    assert excinfo.value.code == "destination_invalid"
    assert resolution_attempts == 0


def test_governed_deployment_may_enable_the_private_network_class() -> None:
    """A deployment that explicitly opts in may target its own private network."""

    resolver = _resolver({"agent.internal": ["10.0.0.4"]})
    resolved = validate_destination(
        "https://agent.internal/hooks",
        resolver=resolver,
        allow_private_destinations=True,
    )

    assert resolved.addresses == ("10.0.0.4",)


@pytest.mark.parametrize(
    ("network_class", "address"),
    [("public", "93.184.216.34"), ("private", "10.0.0.4"), ("loopback", "127.0.0.1")],
)
@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("allow_private", [False, True])
def test_scheme_network_class_and_private_opt_in_matrix(
    network_class: str, address: str, scheme: str, allow_private: bool
) -> None:
    """HTTP is local/private-only; the opt-in never weakens public transport."""

    resolver = _resolver({"agent.test": [address]})
    accepted = scheme == "https" and (network_class == "public" or allow_private)
    accepted = accepted or (
        scheme == "http" and network_class != "public" and allow_private
    )

    if not accepted:
        with pytest.raises(DestinationRejected):
            validate_destination(
                f"{scheme}://agent.test:8099/hooks",
                resolver=resolver,
                allow_private_destinations=allow_private,
            )
        return

    resolved = validate_destination(
        f"{scheme}://agent.test:8099/hooks",
        resolver=resolver,
        allow_private_destinations=allow_private,
    )
    assert resolved.addresses == (address,)
    assert resolved.host_header == "agent.test:8099"


def test_empty_dns_answer_is_refused_as_unresolvable() -> None:
    """An empty resolver answer cannot produce an unpinned network request."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(
            "https://empty.example.com/hooks",
            resolver=_resolver({"empty.example.com": []}),
        )

    assert excinfo.value.code == "destination_unresolvable"


def test_non_ip_dns_answer_is_refused_as_unresolvable() -> None:
    """Every pinned resolver result must itself be a valid IP address."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(
            "https://invalid.example.com/hooks",
            resolver=_resolver({"invalid.example.com": ["not-an-ip"]}),
        )

    assert excinfo.value.code == "destination_unresolvable"


def test_default_port_is_derived_from_the_scheme() -> None:
    """A URL without an explicit port still pins a concrete port."""

    resolved = validate_destination("https://agent.example.com/hooks", resolver=PUBLIC)

    assert resolved.port == 443


class TestInteractiveResultLink:
    """FR-014 (v1): a reported result link is never clickable.

    Click-time safety of an agent-controlled URL cannot be guaranteed from the
    server: the syntax check runs now, the browser resolves later, and nothing
    stops the name from answering with a private or metadata address in between.
    Since BrainBuddy must not fetch the URL to find out, v1 fails closed and
    shows every reported link as inert text.
    """

    @pytest.mark.parametrize(
        "url",
        [
            # Syntactically fine, publicly named, and still not interactive:
            # only click-time resolution decides where this actually goes.
            "https://results.example.com/run/1",
            "https://sub.deep.results.example.com/run/1?token=abc",
            # Rebinding-style names: a public answer now, a private one later.
            "https://rebind.7f000001.nip.io/run/1",
            "https://localtest.me/run/1",
            "https://something.localhost/run/1",
            # Literal addresses across every unsafe class.
            "https://127.0.0.1/run/1",
            "https://localhost/run/1",
            "https://169.254.169.254/latest/meta-data/",
            "https://[fe80::1]/run/1",
            "https://[::ffff:127.0.0.1]/run/1",
            "https://[::ffff:169.254.169.254]/run/1",
            "https://10.0.0.1/run/1",
            "https://192.168.1.1/run/1",
            "https://172.16.0.1/run/1",
            "https://[::1]/run/1",
            "https://0.0.0.0/run/1",
            "https://[64:ff9b::7f00:1]/run/1",
            # Non-HTTPS schemes and junk stay inert too.
            "http://results.example.com/run/1",
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "file:///etc/passwd",
            "https://user:pw@results.example.com/run/1",
            "not a url at all",
            "",
        ],
    )
    def test_no_reported_link_is_ever_interactive(self, url: str) -> None:
        """Every reported link — safe-looking or not — stays inert text."""

        assert interactive_result_link(url) is False

    def test_link_check_never_resolves_dns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rendering a run must not trigger a server-side lookup or fetch."""

        def exploding_getaddrinfo(*args: object, **kwargs: object) -> object:
            raise AssertionError("rendering a result link must not resolve DNS")

        monkeypatch.setattr(socket, "getaddrinfo", exploding_getaddrinfo)

        assert interactive_result_link("https://results.example.com/run/1") is False


# ---------------------------------------------------------------------------
# Bounded response bodies over a pinned connection.
#
# These cases were written for spec 007 against ``test_agent_connector.py`` but
# they never exercised the connector: every one of them drives ``pinned_request``
# and ``_bounded_response_body`` directly. Spec 014 deletes the bespoke connector
# (FR-012), and a decompression-bomb budget is not a thing to delete with it, so
# they move here to the module that actually owns the behaviour.
# ---------------------------------------------------------------------------


def _pinned_resolver(host: str, port: int) -> list[str]:
    return {"agent.example.com": ["93.184.216.34"]}[host]


@pytest.mark.parametrize(
    ("encoding", "content"),
    [
        ("gzip", gzip.compress(b"complete response")[:-1]),
        ("gzip", gzip.compress(b"complete response") + b"trailing"),
        ("gzip", gzip.compress(b"first") + gzip.compress(b"second")),
        ("br", b"opaque"),
        ("gzip", gzip.compress(b"x" * 1_000_000)),
    ],
)
def test_preloaded_encoded_response_fails_closed(encoding: str, content: bytes) -> None:
    """Decoded/preloaded bytes cannot bypass encoding-integrity and bomb checks."""

    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": encoding},
            content=content,
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=4096,
            client_factory=factory,
        )

    assert excinfo.value.code == "destination_invalid"
    assert str(excinfo.value) == "The agent response body is not valid."


def test_preloaded_unencoded_response_above_cap_is_rejected_not_truncated() -> None:
    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"sixsix")

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=5,
            client_factory=factory,
        )

    assert excinfo.value.code == "destination_invalid"
    assert str(excinfo.value) == "The agent response body is not valid."


def test_raw_compressed_network_work_is_bounded_when_output_limit_is_zero() -> None:
    """Arbitrarily many empty deflate blocks cannot cause unbounded reads/calls."""

    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )
    chunks_requested = 0

    class EndlessEmptyDeflateBlocks(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal chunks_requested
            while True:
                chunks_requested += 1
                yield b"\x00\x00\x00\xff\xff"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "deflate"},
            stream=EndlessEmptyDeflateBlocks(),
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=0,
            client_factory=factory,
        )

    assert excinfo.value.code == "destination_invalid"
    # The raw-byte budget, not sender-chosen partitioning, bounds the read.
    assert chunks_requested <= (64 * 1024) // 5 + 1


def test_valid_compressed_response_accepts_more_than_128_network_partitions() -> None:
    compressed = gzip.compress(b"bounded response")

    class HighlyPartitionedStream(httpx.SyncByteStream):
        def __iter__(self):
            for byte in compressed:
                yield bytes([byte])
            for _ in range(129):
                yield b""

    response = httpx.Response(
        200,
        headers={"Content-Encoding": "gzip"},
        stream=HighlyPartitionedStream(),
    )

    assert (
        _bounded_response_body(response, max_response_bytes=4096, decoder_factory=None)
        == b"bounded response"
    )


def test_compressed_raw_byte_budget_is_independent_of_decoded_output() -> None:
    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )
    chunks_requested = 0

    class OversizedRawStream(httpx.SyncByteStream):
        def __iter__(self):
            nonlocal chunks_requested
            while True:
                chunks_requested += 1
                yield b"\x00" * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "deflate"},
            stream=OversizedRawStream(),
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected):
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=0,
            client_factory=factory,
        )

    assert chunks_requested <= 65


@pytest.mark.parametrize("failure", ["unused_data", "incomplete", "flush_overflow"])
def test_compressed_integrity_terminal_failures_are_rejected(failure: str) -> None:
    """Each terminal framing check independently fails closed."""

    class TerminalDecoder:
        unconsumed_tail = b""

        @property
        def unused_data(self) -> bytes:
            return b"trailing" if failure == "unused_data" else b""

        @property
        def eof(self) -> bool:
            return failure != "incomplete"

        def decompress(self, data: bytes, max_length: int) -> bytes:
            return b""

        def flush(self, length: int) -> bytes:
            return b"x" if failure == "flush_overflow" else b""

    response = httpx.Response(
        200,
        headers={"Content-Encoding": "deflate"},
        stream=httpx.ByteStream(b"encoded"),
    )

    with pytest.raises(DestinationRejected):
        _bounded_response_body(
            response,
            max_response_bytes=0,
            decoder_factory=lambda encoding: TerminalDecoder(),
        )


def test_decompress_call_budget_rejects_nonprogressing_decoder() -> None:
    class NonProgressingDecoder:
        unused_data = b""
        eof = False

        def __init__(self) -> None:
            self.unconsumed_tail = b""

        def decompress(self, data: bytes, max_length: int) -> bytes:
            self.unconsumed_tail = data
            return b""

        def flush(self, length: int) -> bytes:
            return b""

    response = httpx.Response(
        200,
        headers={"Content-Encoding": "deflate"},
        stream=httpx.ByteStream(b"encoded"),
    )

    with pytest.raises(DestinationRejected):
        _bounded_response_body(
            response,
            max_response_bytes=0,
            decoder_factory=lambda encoding: NonProgressingDecoder(),
        )


def test_zlib_error_translation_has_no_exception_chain() -> None:
    response = httpx.Response(
        200,
        headers={"Content-Encoding": "gzip"},
        stream=httpx.ByteStream(b"not-gzip"),
    )

    with pytest.raises(DestinationRejected) as excinfo:
        _bounded_response_body(response, max_response_bytes=4096, decoder_factory=None)

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


@pytest.mark.parametrize("limit", [0, 4096])
def test_compressed_response_over_limit_stops_in_constant_decoder_calls(
    limit: int,
) -> None:
    """A compressed bomb is rejected without draining expansion byte by byte."""

    compressed = gzip.compress(b"x" * 1_000_000)

    class TrackingDecoder:
        def __init__(self) -> None:
            import zlib

            self.inner = zlib.decompressobj(16 + zlib.MAX_WBITS)
            self.largest_requested = 0
            self.calls = 0

        @property
        def unconsumed_tail(self) -> bytes:
            return self.inner.unconsumed_tail

        @property
        def unused_data(self) -> bytes:
            return self.inner.unused_data

        @property
        def eof(self) -> bool:
            return self.inner.eof

        def decompress(self, data: bytes, max_length: int) -> bytes:
            self.calls += 1
            self.largest_requested = max(self.largest_requested, max_length)
            return self.inner.decompress(data, max_length)

        def flush(self, length: int) -> bytes:
            self.largest_requested = max(self.largest_requested, length)
            return self.inner.flush(length)

    decoder = TrackingDecoder()
    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "gzip"},
            stream=httpx.ByteStream(compressed),
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=limit,
            client_factory=factory,
            decoder_factory=lambda encoding: decoder,
        )

    assert excinfo.value.code == "destination_invalid"
    assert decoder.calls <= 2
    assert decoder.largest_requested <= limit + 1


@pytest.mark.parametrize(
    ("encoding", "compressed"),
    [
        ("gzip", gzip.compress(b"bounded response")),
        ("deflate", __import__("zlib").compress(b"bounded response")),
    ],
)
def test_supported_stream_encodings_decode_normally(
    encoding: str, compressed: bytes
) -> None:
    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": encoding},
            stream=httpx.ByteStream(compressed),
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    response = pinned_request(
        method="GET",
        destination=destination,
        headers={},
        json_body=None,
        timeout_seconds=5,
        max_response_bytes=4096,
        client_factory=factory,
    )

    assert response.body == b"bounded response"


@pytest.mark.parametrize(
    ("encoding", "compressed"),
    [
        ("gzip", gzip.compress(b"complete response")[:-1]),
        ("deflate", zlib.compress(b"complete response")[:-1]),
        ("gzip", gzip.compress(b"complete response") + b"trailing"),
        ("deflate", zlib.compress(b"complete response") + b"trailing"),
        ("gzip", gzip.compress(b"first") + gzip.compress(b"second")),
    ],
)
def test_compressed_response_requires_one_complete_stream(
    encoding: str, compressed: bytes
) -> None:
    """Truncation, trailing bytes, and concatenated gzip members fail closed."""

    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": encoding},
            stream=httpx.ByteStream(compressed),
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=4,
            client_factory=factory,
        )

    assert excinfo.value.code == "destination_invalid"
    assert str(excinfo.value) == "The agent response body is not valid."


def test_unsupported_stream_encoding_is_rejected() -> None:
    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Encoding": "br"},
            stream=httpx.ByteStream(b"opaque"),
        )

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected):
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=4096,
            client_factory=factory,
        )


@pytest.mark.parametrize("limit", [0, 5])
@pytest.mark.parametrize("encoding", [None, "identity"])
def test_unencoded_stream_is_bounded_before_accumulation(
    limit: int, encoding: str | None
) -> None:
    destination = validate_destination(
        "https://agent.example.com/hooks", resolver=_pinned_resolver
    )

    class ChunkStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"first"
            yield b"second"

    def handler(request: httpx.Request) -> httpx.Response:
        headers = {} if encoding is None else {"Content-Encoding": encoding}
        return httpx.Response(200, headers=headers, stream=ChunkStream())

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=destination,
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=limit,
            client_factory=factory,
        )

    assert excinfo.value.code == "destination_invalid"


# ---------------------------------------------------------------------------
# The absolute wall-clock deadline (spec 014 FR-007, FR-008; AC-034).
#
# httpx's read timeout is per *chunk*, so a server that emits one byte every few
# hundred seconds never trips it, and ``_bounded_response_body``'s budget bounds
# bytes rather than time. Between them a drip-feeding agent can hold a worker
# open indefinitely while every configured limit reports itself satisfied — the
# exchange pool drains, the cancel that would end it queues behind the exchanges
# it is meant to end, and the product cannot tell pool saturation from agent
# behaviour. The deadline is the bound that actually closes the socket.
#
# The clock is injected rather than slept through: a timing test that waits is a
# flaky test, and 315 s of real waiting is not a suite anyone runs.
# ---------------------------------------------------------------------------


def _clock(*values: float):
    """A monotonic stand-in that returns each value once, then repeats the last.

    The first value is what ``pinned_request`` records as its start; the rest
    are what each successive deadline check sees.
    """

    remaining = list(values)
    last = [0.0]

    def now() -> float:
        if remaining:
            last[0] = remaining.pop(0)
        return last[0]

    return now


class _RecordingStream(httpx.SyncByteStream):
    """A stream that never ends, and remembers whether it was closed."""

    def __init__(self) -> None:
        self.closed = False
        self.chunks_yielded = 0

    def __iter__(self):
        while True:
            self.chunks_yielded += 1
            yield b"x"

    def close(self) -> None:
        self.closed = True


def _deadline_destination():
    return validate_destination(
        "https://agent.example.com/rpc", resolver=_pinned_resolver
    )


def test_014_FR_007_the_deadline_trips_while_still_waiting_for_headers() -> None:
    """An agent that accepts the connection and then says nothing.

    AC-034: without this check the request would sit in the header phase for as
    long as the read timeout allows on every chunk that never comes, holding an
    exchange worker that one connection is only allowed two of.
    """

    stream = _RecordingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(EgressDeadlineExceeded) as excinfo:
        pinned_request(
            method="POST",
            destination=_deadline_destination(),
            headers={},
            json_body={"jsonrpc": "2.0"},
            timeout_seconds=5,
            max_response_bytes=4096,
            client_factory=factory,
            deadline_seconds=1.0,
            monotonic=_clock(0.0, 100.0),
        )

    assert excinfo.value.deadline_seconds == 1.0
    assert stream.chunks_yielded == 0, "the body must not be read after a breach"


def test_014_FR_008_a_drip_feeding_body_trips_the_deadline_and_closes_the_stream() -> (
    None
):
    """One byte per interval satisfies every per-chunk timeout forever.

    AC-034: this is the shape the byte budget cannot catch — the response stays
    far under the cap while the socket stays open. The stream is closed on
    breach rather than left to a garbage collector, because the resource being
    protected is a bounded worker, not memory.
    """

    stream = _RecordingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    with pytest.raises(EgressDeadlineExceeded):
        pinned_request(
            method="POST",
            destination=_deadline_destination(),
            headers={},
            json_body={"jsonrpc": "2.0"},
            timeout_seconds=5,
            max_response_bytes=1_000_000,
            client_factory=factory,
            deadline_seconds=1.0,
            monotonic=_clock(0.0, 0.1, 0.2, 100.0),
        )

    assert stream.chunks_yielded >= 1, "the breach must happen inside the body loop"
    assert stream.closed is True


def test_014_FR_007_an_answer_inside_the_deadline_is_still_received() -> None:
    """SC-006: an agent replying at the very edge of its window is on time.

    A deadline that fired early would report a compliant agent as unreachable —
    a false claim about someone else's system caused by BrainBuddy's own clock.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": {}})

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    response = pinned_request(
        method="POST",
        destination=_deadline_destination(),
        headers={},
        json_body={"jsonrpc": "2.0"},
        timeout_seconds=5,
        max_response_bytes=4096,
        client_factory=factory,
        deadline_seconds=10.0,
        # Every check lands exactly on the deadline: on time is not late.
        monotonic=_clock(0.0, 10.0, 10.0, 10.0),
    )

    assert response.status_code == 200


def test_014_FR_008_without_a_deadline_the_per_chunk_timeout_behaviour_is_unchanged() -> (
    None
):
    """The deadline is additive. Every 007 caller passes no deadline and must
    keep the exact behaviour it has today, including the byte cap."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 10)

    def factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

    assert (
        pinned_request(
            method="GET",
            destination=_deadline_destination(),
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=4096,
            client_factory=factory,
        ).body
        == b"x" * 10
    )

    with pytest.raises(DestinationRejected) as excinfo:
        pinned_request(
            method="GET",
            destination=_deadline_destination(),
            headers={},
            json_body=None,
            timeout_seconds=5,
            max_response_bytes=5,
            client_factory=factory,
        )
    assert excinfo.value.code == "destination_invalid"


def test_014_FR_016_a_deadline_breach_is_not_a_destination_rejection() -> None:
    """They mean different things and map to different run states.

    A destination rejection says BrainBuddy refused to talk to the address; a
    deadline breach says it talked and got no answer in time. Collapsing them
    would let an exchange timeout be reported as "not sent" — the one claim that
    must never be made when a message may already be at the agent.
    """

    assert not issubclass(EgressDeadlineExceeded, DestinationRejected)


@pytest.mark.parametrize(
    "url",
    [
        "https://agent.example.com/result",
        "https://public.example/looks-fine",
        "http://169.254.169.254/latest/meta-data/",
        "javascript:alert(1)",
    ],
)
def test_014_FR_016_result_links_are_never_interactive_under_the_deadline_work(
    url: str,
) -> None:
    """AC-016 (product-owner decision, 2026-09-04): unchanged by feature 014.

    Only syntax is available server-side, and syntax cannot answer where the
    browser lands when the user clicks minutes later — a publicly-named host can
    resolve to a private or metadata address at click time. The link is shown as
    inert text the user copies deliberately.
    """

    assert interactive_result_link(url) is False
