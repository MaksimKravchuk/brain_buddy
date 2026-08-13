"""The generic HTTP connector: the only thing that talks to a user's agent.

These tests drive the real ``pinned_request`` egress path through an httpx mock
transport, so the pinned address, the ``Host`` header, redirect refusal, and
response bounding are all exercised rather than stubbed.
"""

from __future__ import annotations

import dataclasses
import gzip
import json
import logging
import pprint
import traceback
import zlib
from typing import Any

import httpx
import pytest

from app.modules.agents.connector import (
    ConnectorTarget,
    GenericHttpConnector,
)
from app.modules.agents.domain import PROTOCOL_VERSION
from app.modules.agents.egress import (
    DestinationRejected,
    _bounded_response_body,
    pinned_request,
    validate_destination,
)

TARGET = ConnectorTarget(
    endpoint_url="https://agent.example.com/hooks",
    auth_header_name="X-Hermes-Key",
    credential="Bearer super-secret-token",
)


def _resolver(host: str, port: int) -> list[str]:
    return {"agent.example.com": ["93.184.216.34"]}[host]


def build_connector(
    handler: Any, *, allow_private_destinations: bool = False
) -> tuple[GenericHttpConnector, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client_factory(**kwargs: Any) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(recording_handler), **kwargs)

    connector = GenericHttpConnector(
        timeout_seconds=5.0,
        max_response_bytes=64_000,
        allow_private_destinations=allow_private_destinations,
        resolver=_resolver,
        client_factory=client_factory,
    )
    return connector, seen


def json_handler(payload: dict[str, Any], status_code: int = 200) -> Any:
    return lambda request: httpx.Response(status_code, json=payload)


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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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
        "https://agent.example.com/hooks", resolver=_resolver
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


class TestConnectionTest:
    def test_a_conforming_connector_is_ready_and_discloses_capabilities(self) -> None:
        """A healthy connector reports exactly what it can do."""

        connector, seen = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": False},
                    "idempotent_start": True,
                    "idempotent_reply": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert outcome.capabilities.progress is True
        assert outcome.capabilities.reply is True
        assert outcome.capabilities.cancel is False
        body = json.loads(seen[0].content)
        assert body["type"] == "capabilities"
        assert body["protocol_version"] == PROTOCOL_VERSION

    def test_the_credential_travels_in_the_configured_header(self) -> None:
        """The connector sends the saved credential where the user configured it."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        connector.test(
            ConnectorTarget(
                endpoint_url="https://agent.example.com/hooks",
                auth_header_name="X-Hermes-Key",
                credential="hermes-key-value",
            )
        )

        assert seen[0].headers["X-Hermes-Key"] == "hermes-key-value"

    def test_query_string_destination_never_reaches_the_http_client(self) -> None:
        """A signed endpoint URL is rejected without serializing its credential."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        outcome = connector.test(
            ConnectorTarget(
                endpoint_url="https://agent.example.com/hooks?token=signed-secret",
                auth_header_name="X-Hermes-Key",
                credential="Bearer super-secret-token",
            )
        )

        assert outcome.status == "unreachable"
        assert outcome.error_code == "destination_invalid"
        assert seen == []

    def test_the_request_goes_to_the_pinned_address_with_the_original_host(
        self,
    ) -> None:
        """A rebinding answer cannot move the connection after validation."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        connector.test(TARGET)

        assert seen[0].url.host == "93.184.216.34"
        assert seen[0].headers["Host"] == "agent.example.com"
        assert seen[0].extensions["sni_hostname"] == "agent.example.com"

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_an_authentication_rejection_is_reported_as_invalid_credentials(
        self, status_code: int
    ) -> None:
        """Bad credentials are distinguishable from an unreachable endpoint."""

        connector, _ = build_connector(json_handler({}, status_code))

        outcome = connector.test(TARGET)

        assert outcome.status == "invalid_credentials"

    @pytest.mark.parametrize("status_code", [404, 500, 503])
    def test_other_http_failures_are_reported_as_unreachable(
        self, status_code: int
    ) -> None:
        """Any other failure is honestly 'we could not reach a working agent'."""

        connector, _ = build_connector(json_handler({}, status_code))

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == f"connector_http_{status_code}"

    def test_a_transport_failure_is_reported_as_unreachable(self) -> None:
        """A dead endpoint never looks like a working one."""

        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host", request=request)

        connector, _ = build_connector(explode)

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == "connector_unreachable"

    def test_a_timeout_is_reported_as_unreachable(self) -> None:
        """An endpoint that never answers is not 'ready'."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        connector, _ = build_connector(stall)

        assert connector.test(TARGET).status == "unreachable"

    def test_a_connector_without_start_idempotency_is_not_ready(self) -> None:
        """FR-006: no dedup guarantee means the connector cannot take a hand-off."""

        connector, _ = build_connector(
            json_handler(
                {"capabilities": {"progress": True}, "idempotent_start": False}
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "unsupported"
        assert outcome.error_code == "connector_start_not_idempotent"

    @pytest.mark.parametrize(
        ("capability", "guarantee"),
        [("reply", "idempotent_reply"), ("cancel", "idempotent_cancel")],
    )
    def test_a_command_capability_without_its_dedup_promise_is_suppressed(
        self, capability: str, guarantee: str
    ) -> None:
        """FR-006/FR-007: a control BrainBuddy cannot replay safely is not offered.

        Reply and cancel are retried on an ambiguous send, reusing one command
        ID. A connector that advertises the control but never promises to
        deduplicate that ID could act twice on one user request, so the control
        is withheld rather than exposed with a caveat.
        """

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": True},
                    "idempotent_start": True,
                    guarantee: False,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert getattr(outcome.capabilities, capability) is False
        assert outcome.capabilities.progress is True

    def test_a_missing_dedup_promise_is_not_a_promise(self) -> None:
        """Silence is not a guarantee: both controls stay off by default."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": True},
                    "idempotent_start": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert outcome.capabilities.reply is False
        assert outcome.capabilities.cancel is False

    def test_a_dedup_promise_without_the_capability_grants_nothing(self) -> None:
        """The guarantee qualifies a capability; it cannot conjure one."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {
                        "progress": False,
                        "reply": False,
                        "cancel": False,
                    },
                    "idempotent_start": True,
                    "idempotent_reply": True,
                    "idempotent_cancel": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.capabilities.reply is False
        assert outcome.capabilities.cancel is False

    def test_both_controls_survive_when_both_are_guaranteed(self) -> None:
        """A fully conforming connector keeps everything it advertised."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"progress": True, "reply": True, "cancel": True},
                    "idempotent_start": True,
                    "idempotent_reply": True,
                    "idempotent_cancel": True,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "ready"
        assert outcome.capabilities.reply is True
        assert outcome.capabilities.cancel is True

    @pytest.mark.parametrize("truthy", ["yes", 1, {}, None])
    def test_only_an_explicit_boolean_true_counts_as_a_promise(
        self, truthy: Any
    ) -> None:
        """A truthy-looking value is not the documented guarantee."""

        connector, _ = build_connector(
            json_handler(
                {
                    "capabilities": {"reply": True, "cancel": True},
                    "idempotent_start": True,
                    "idempotent_reply": truthy,
                    "idempotent_cancel": truthy,
                }
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.capabilities.reply is False
        assert outcome.capabilities.cancel is False

    def test_an_unparseable_body_is_not_ready(self) -> None:
        """A 200 that is not the agreed envelope proves nothing."""

        connector, _ = build_connector(lambda request: httpx.Response(200, text="hi"))

        outcome = connector.test(TARGET)

        assert outcome.status == "unsupported"
        assert outcome.error_code == "connector_response_invalid"

    def test_a_redirect_is_refused_rather_than_followed(self) -> None:
        """Redirects can move a credential off the validated destination."""

        connector, _ = build_connector(
            lambda request: httpx.Response(
                302, headers={"Location": "https://evil.example.com/steal"}
            )
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == "destination_redirect_not_allowed"

    def test_an_unsafe_destination_never_reaches_the_network(self) -> None:
        """Destination class is checked before the credential is serialized."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        outcome = connector.test(
            ConnectorTarget(
                endpoint_url="https://169.254.169.254/latest",
                auth_header_name="X-Hermes-Key",
                credential="Bearer super-secret-token",
            )
        )

        assert outcome.status == "unreachable"
        assert outcome.error_code == "destination_network_not_allowed"
        assert seen == []

    @pytest.mark.parametrize(
        "auth_header_name", ["Host", "x-brainbuddy-run-id", "X Bad"]
    )
    def test_an_unsafe_auth_header_is_refused_before_network_io(
        self, auth_header_name: str
    ) -> None:
        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        with pytest.raises(ValueError):
            connector.test(
                ConnectorTarget(
                    endpoint_url="https://agent.example.com/hooks",
                    auth_header_name=auth_header_name,
                    credential="Bearer super-secret-token",
                )
            )

        assert seen == []


class TestStart:
    def _envelope(self) -> dict[str, Any]:
        return {
            "type": "start",
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "agentrun_1",
            "task_id": "task_1",
            "idempotency_key": "idem-1",
            "title": "Draft the migration plan",
            "details": None,
            "context": [],
            "reporting": {
                "callback_url": "https://brainbuddy.example/api/agent-events",
                "instructions": "Report progress to the callback URL.",
                "instructions_version": "v1",
            },
        }

    def test_an_accepted_start_is_reported_as_sent(self) -> None:
        """A 2xx means the agent took the work."""

        connector, seen = build_connector(json_handler({"accepted": True}, 202))

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "sent"
        assert json.loads(seen[0].content)["run_id"] == "agentrun_1"
        assert seen[0].headers["Idempotency-Key"] == "idem-1"

    def test_a_timeout_is_delivery_unconfirmed_not_failed(self) -> None:
        """FR-006: ambiguous loss must never be called failure."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        connector, _ = build_connector(stall)

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "delivery_unconfirmed"

    def test_a_server_error_is_delivery_unconfirmed(self) -> None:
        """A 5xx may or may not have started work; we must not guess."""

        connector, _ = build_connector(json_handler({}, 500))

        assert (
            connector.start(TARGET, envelope=self._envelope()).status
            == "delivery_unconfirmed"
        )

    def test_a_connection_error_proves_nothing_was_sent(self) -> None:
        """A refused connection is definitive evidence of non-delivery."""

        def refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        connector, _ = build_connector(refuse)

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "not_sent"

    def test_destination_rejection_proves_start_was_not_sent(self) -> None:
        """A revalidated unsafe destination cannot become ambiguous delivery."""

        connector, seen = build_connector(json_handler({"accepted": True}, 202))
        unsafe = ConnectorTarget(
            endpoint_url="https://169.254.169.254/latest",
            auth_header_name="X-Hermes-Key",
            credential="Bearer super-secret-token",
        )

        outcome = connector.start(unsafe, envelope=self._envelope())

        assert outcome.status == "not_sent"
        assert outcome.error_code == "destination_network_not_allowed"
        assert seen == []

    def test_a_client_rejection_proves_nothing_was_started(self) -> None:
        """A 4xx is a definitive refusal, so the run was never accepted."""

        connector, _ = build_connector(json_handler({"error": "bad"}, 400))

        outcome = connector.start(TARGET, envelope=self._envelope())

        assert outcome.status == "not_sent"
        assert outcome.error_code == "connector_http_400"


class TestCommand:
    def _envelope(self) -> dict[str, Any]:
        return {
            "type": "reply",
            "protocol_version": PROTOCOL_VERSION,
            "run_id": "agentrun_1",
            "command_id": "agentcmd_1",
            "message": "Use the staging database.",
        }

    def test_an_acknowledgement_correlated_to_the_command_confirms_delivery(
        self,
    ) -> None:
        """FR-007: only an explicit command-ID echo confirms delivery."""

        connector, _ = build_connector(json_handler({"command_id": "agentcmd_1"}))

        outcome = connector.command(TARGET, envelope=self._envelope())

        assert outcome.status == "confirmed"

    def test_a_success_without_the_command_id_stays_unconfirmed(self) -> None:
        """A bare 200 is not evidence the agent received this command."""

        connector, _ = build_connector(json_handler({"ok": True}))

        outcome = connector.command(TARGET, envelope=self._envelope())

        assert outcome.status == "unconfirmed"

    def test_an_acknowledgement_for_a_different_command_does_not_confirm(self) -> None:
        """Correlation is checked, not assumed."""

        connector, _ = build_connector(json_handler({"command_id": "agentcmd_other"}))

        assert connector.command(TARGET, envelope=self._envelope()).status == (
            "unconfirmed"
        )

    def test_a_non_success_response_leaves_the_command_unconfirmed(self) -> None:
        """A connector rejection is not an acknowledgement of command delivery."""

        connector, _ = build_connector(json_handler({"error": "rejected"}, 409))

        outcome = connector.command(TARGET, envelope=self._envelope())

        assert outcome.status == "unconfirmed"
        assert outcome.error_code == "connector_http_409"

    def test_a_timeout_leaves_the_command_visibly_unconfirmed(self) -> None:
        """A command that times out is never claimed as delivered."""

        def stall(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timed out", request=request)

        connector, _ = build_connector(stall)

        assert connector.command(TARGET, envelope=self._envelope()).status == (
            "unconfirmed"
        )

    def test_destination_rejection_leaves_a_command_unconfirmed(self) -> None:
        """A command blocked by egress policy is never claimed as delivered."""

        connector, seen = build_connector(json_handler({"command_id": "agentcmd_1"}))
        unsafe = ConnectorTarget(
            endpoint_url="https://127.0.0.1/hooks",
            auth_header_name="X-Hermes-Key",
            credential="Bearer super-secret-token",
        )

        outcome = connector.command(unsafe, envelope=self._envelope())

        assert outcome.status == "unconfirmed"
        assert outcome.error_code == "destination_network_not_allowed"
        assert seen == []


class TestResponseBounding:
    def test_an_oversized_preloaded_response_is_rejected(self) -> None:
        """A preloaded body above the cap cannot masquerade as valid content."""

        def flood(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"x" * 500_000)

        seen: list[httpx.Request] = []

        def client_factory(**kwargs: Any) -> httpx.Client:
            def handler(request: httpx.Request) -> httpx.Response:
                seen.append(request)
                return flood(request)

            return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

        connector = GenericHttpConnector(
            timeout_seconds=5.0,
            max_response_bytes=1_024,
            allow_private_destinations=False,
            resolver=_resolver,
            client_factory=client_factory,
        )

        outcome = connector.test(TARGET)

        assert outcome.status == "unreachable"
        assert outcome.error_code == "destination_invalid"


# A value no other fixture uses, so any leak into a rendered string is this
# credential and not an incidental substring of the endpoint or header name.
CANARY_CREDENTIAL = "Bearer zq7-canary-credential-9f31"


def canary_target(credential: str = CANARY_CREDENTIAL) -> ConnectorTarget:
    return ConnectorTarget(
        endpoint_url="https://agent.example.com/hooks",
        auth_header_name="X-Hermes-Key",
        credential=credential,
    )


class TestCredentialIsNeverRendered:
    """007-FR-003: the opened credential must not reach any rendered text.

    ``ConnectorTarget`` is the one object that holds a decrypted credential, and
    it is passed as an argument through the connector — so it lands in
    tracebacks, log records and debugger output. Its representation is part of
    the security contract, not a formatting detail.
    """

    def test_007_FR_003_the_representation_is_stable_and_omits_the_credential(
        self,
    ) -> None:
        """Identity stays legible for debugging; the secret is simply absent."""

        assert repr(canary_target()) == (
            "ConnectorTarget("
            "endpoint_url='https://agent.example.com/hooks', "
            "auth_header_name='X-Hermes-Key')"
        )

    def test_007_FR_003_every_string_conversion_hides_the_credential(self) -> None:
        """``str``, f-strings and ``format`` all route through the same repr."""

        target = canary_target()

        rendered = [
            str(target),
            repr(target),
            f"{target}",
            f"{target!r}",
            f"{target!s}",
            "{}".format(target),  # noqa: UP032 - exercises format() explicitly
            format(target),
        ]

        for text in rendered:
            assert CANARY_CREDENTIAL not in text
            assert "zq7-canary" not in text
            # The non-secret identity is still allowed, and useful.
            assert "agent.example.com" in text
            assert "X-Hermes-Key" in text

    def test_007_FR_003_a_container_or_pretty_print_hides_the_credential(self) -> None:
        """Nested rendering delegates to the same repr, so it leaks nothing."""

        target = canary_target()

        assert CANARY_CREDENTIAL not in repr([target])
        assert CANARY_CREDENTIAL not in repr({"target": target})
        assert CANARY_CREDENTIAL not in repr((target,))
        assert CANARY_CREDENTIAL not in pprint.pformat({"target": target})

    def test_007_FR_003_an_exception_carrying_the_target_hides_the_credential(
        self,
    ) -> None:
        """A crash report is the likeliest accidental disclosure path."""

        target = canary_target()

        try:
            raise RuntimeError("connector dispatch failed", target)
        except RuntimeError as exc:
            rendered = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
            assert CANARY_CREDENTIAL not in rendered
            assert CANARY_CREDENTIAL not in repr(exc)
            assert CANARY_CREDENTIAL not in str(exc)
            assert "agent.example.com" in rendered

    def test_007_FR_003_a_log_record_of_the_target_hides_the_credential(self) -> None:
        """Logging a target formats it, so the same guarantee has to hold."""

        record = logging.LogRecord(
            name="app.modules.agents.connector",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="dispatch to %s failed",
            args=(canary_target(),),
            exc_info=None,
        )

        formatted = logging.Formatter("%(message)s").format(record)

        assert CANARY_CREDENTIAL not in formatted
        assert "agent.example.com" in formatted

    def test_007_FR_003_hiding_the_credential_does_not_hide_it_from_equality(
        self,
    ) -> None:
        """Redaction is presentational: the credential is still part of state."""

        assert canary_target() == canary_target()
        assert canary_target() != canary_target(credential="a-different-credential")
        assert hash(canary_target()) == hash(canary_target())
        assert hash(canary_target()) != hash(
            canary_target(credential="a-different-credential")
        )
        assert dataclasses.asdict(canary_target())["credential"] == CANARY_CREDENTIAL
        assert canary_target().credential == CANARY_CREDENTIAL

    def test_007_FR_003_the_connector_still_sends_the_hidden_credential(self) -> None:
        """The header the owner configured still carries the real secret."""

        connector, seen = build_connector(
            json_handler({"capabilities": {}, "idempotent_start": True})
        )

        outcome = connector.test(canary_target())

        assert outcome.status == "ready"
        assert seen[0].headers["X-Hermes-Key"] == CANARY_CREDENTIAL
