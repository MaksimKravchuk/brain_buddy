"""Destination-class safety for outbound external-agent traffic (FR-004, FR-014).

Every one of these cases must be decided *before* a credential or task content
ever reaches a socket, so they exercise ``validate_destination`` directly with an
injected resolver rather than touching the network.
"""

from __future__ import annotations

import socket

import pytest

from app.modules.agents.egress import (
    DestinationRejected,
    interactive_result_link,
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
        "https:///hooks",
        "not-a-url",
        "https://agent.example.com/hooks#fragment",
    ],
)
def test_malformed_or_credential_bearing_urls_are_refused(url: str) -> None:
    """Embedded credentials, missing hosts, and fragments are refused outright."""

    with pytest.raises(DestinationRejected) as excinfo:
        validate_destination(url, resolver=PUBLIC)

    assert excinfo.value.code == "destination_invalid"


def test_governed_deployment_may_enable_the_private_network_class() -> None:
    """A deployment that explicitly opts in may target its own private network."""

    resolver = _resolver({"agent.internal": ["10.0.0.4"]})
    resolved = validate_destination(
        "https://agent.internal/hooks",
        resolver=resolver,
        allow_private_destinations=True,
    )

    assert resolved.addresses == ("10.0.0.4",)


def test_private_network_opt_in_also_permits_plaintext_for_local_development() -> None:
    """The same governed opt-in is what permits HTTP against a local connector."""

    resolver = _resolver({"localhost": ["127.0.0.1"]})
    resolved = validate_destination(
        "http://localhost:8099/hooks",
        resolver=resolver,
        allow_private_destinations=True,
    )

    assert resolved.port == 8099
    assert resolved.addresses == ("127.0.0.1",)
    assert resolved.host_header == "localhost:8099"


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
