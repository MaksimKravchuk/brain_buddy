"""Discovery: what an agent card is allowed to tell BrainBuddy about itself.

A card is the first thing a stranger's server says, and everything downstream —
which URL receives the user's Task, which header carries their credential,
whether the product promises "guaranteed single start" — is decided from it. So
this module's job is to be *lenient about shape and strict about meaning*.

Lenient, because both reference runtimes are legitimately non-canonical: the
a2a-sdk sample serves the 1.0 shape, Hermes serves a legacy `securitySchemes`
entry, an unknown `capabilities.stateTransitionHistory`, and no top-level
protocol version at all. Refusing either would fail FR-017 while proving
nothing.

Strict, because a card is untrusted input that gets to name a header, a host and
a promise. The cases below are the ones where being accommodating would cost
something real: a card that names `Authorization` as its API-key header, a card
that requires an extension BrainBuddy has not implemented, an interface on a
host that resolves inward, a version that is not 1.0.

014-FR-001, 014-FR-002, 014-FR-003, 014-FR-011. AC-001..AC-005, AC-037.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from app.modules.agents.a2a.card import (
    A2A_AUTH_SCHEME_UNSUPPORTED,
    A2A_NO_SUPPORTED_INTERFACE,
    A2A_NOT_AN_AGENT,
    A2A_PROTOCOL_VERSION_UNSUPPORTED,
    A2A_UNREACHABLE,
    CARD_DEADLINE_MARGIN_SECONDS,
    CARD_PATH,
    MAX_CARD_DESCRIPTION_CHARS,
    MAX_EXTENSIONS,
    MAX_SKILL_TEXT_CHARS,
    MAX_SKILLS,
    SINGLE_START_EXTENSION_URI,
    card_fingerprint,
    card_url_for,
    fetch_card,
    interpret_card,
)
from app.modules.agents.egress import DestinationRejected

# --- card fixtures ----------------------------------------------------------
#
# Two shapes, both taken from a real runtime rather than invented: `V1_CARD` is
# the a2a-sdk 1.0 shape, `LEGACY_CARD` is what the vendored Hermes plugin
# actually served in the T007 harness smoke run.

V1_CARD: dict[str, Any] = {
    "name": "Sample Agent",
    "version": "1.2.3",
    "description": "A sample agent.",
    "supportedInterfaces": [
        {
            "url": "https://agent.example.com/rpc",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    "capabilities": {"streaming": True, "pushNotifications": True},
    "securitySchemes": {
        "bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}},
    },
    "securityRequirements": [{"bearer": []}],
    "skills": [{"id": "s1", "name": "Search", "description": "Finds things."}],
}

LEGACY_CARD: dict[str, Any] = {
    "name": "hermes-vm",
    "version": "0.9",
    "description": "Hermes Agent.",
    "url": "https://agent.example.com/",
    "supportedInterfaces": [
        {
            "url": "https://agent.example.com/",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ],
    # Unknown to A2A 1.0; Hermes sends both of these.
    "capabilities": {
        "streaming": True,
        "pushNotifications": True,
        "stateTransitionHistory": False,
        "extendedAgentCard": False,
    },
    "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
    "security": [{"bearer": []}],
    "skills": [],
}


def _card(**overrides: Any) -> dict[str, Any]:
    payload = copy.deepcopy(V1_CARD)
    payload.update(overrides)
    return payload


def _allow_any_host(url: str) -> None:
    """Interface-host validator that approves everything (the default case)."""


def _refuse_host(url: str) -> None:
    raise DestinationRejected(
        "destination_network_not_allowed", "The agent endpoint must be public."
    )


class TestCardShapes:
    """Both accepted shapes parse, and unknown fields are ignored."""

    @pytest.mark.parametrize(
        ("payload", "expected_url"),
        [
            (V1_CARD, "https://agent.example.com/rpc"),
            (LEGACY_CARD, "https://agent.example.com/"),
        ],
        ids=["v1", "legacy-hermes"],
    )
    def test_014_FR_001_both_card_shapes_parse_and_select_their_interface(
        self, payload: dict[str, Any], expected_url: str
    ) -> None:
        """AC-001: the two reference runtimes serve different shapes, and both
        have to work — otherwise FR-017's conformance evidence is unreachable."""

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code is None
        assert result.interface_url == expected_url
        assert result.summary is not None
        assert result.summary.protocol_version == "1.0"

    def test_014_FR_001_unknown_card_fields_are_ignored_not_rejected(self) -> None:
        """An agent adding a field is not an attack; refusing it is a bug.

        AC-001: Hermes already sends two capability fields A2A 1.0 does not
        define, so strictness here would reject a runtime BrainBuddy is
        required to interoperate with.
        """

        payload = _card(
            unknownTopLevel={"anything": True},
            capabilities={
                "streaming": True,
                "pushNotifications": False,
                "somethingNew": 42,
            },
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code is None
        assert result.summary is not None
        assert result.summary.streaming is True
        assert result.summary.push_notifications is False

    def test_014_FR_001_a_legacy_card_without_a_top_level_version_still_parses(
        self,
    ) -> None:
        """The per-interface version is authoritative; the top level is a
        fallback, exactly as the Hermes harness serves it."""

        payload = copy.deepcopy(LEGACY_CARD)
        payload.pop("protocolVersion", None)

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code is None
        assert result.summary is not None
        assert result.summary.protocol_version == "1.0"


class TestInterfaceSelection:
    """Which endpoint receives the user's Task, and why."""

    def test_014_FR_001_the_first_matching_jsonrpc_1_0_interface_wins(self) -> None:
        """Deterministic selection: two runs of discovery on one card must pick
        the same endpoint, or a run could be dispatched somewhere its own
        observations never look."""

        payload = _card(
            supportedInterfaces=[
                {
                    "url": "https://agent.example.com/grpc",
                    "protocolBinding": "GRPC",
                    "protocolVersion": "1.0",
                },
                {
                    "url": "https://agent.example.com/first",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0.7",
                },
                {
                    "url": "https://agent.example.com/second",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                },
            ]
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.interface_url == "https://agent.example.com/first"
        assert result.summary is not None
        assert result.summary.protocol_version == "1.0.7"

    @pytest.mark.parametrize("version", ["2.0", "0.9", "1.1", "1", "", "abc"])
    def test_014_FR_002_a_non_1_0_version_names_the_version_it_found(
        self, version: str
    ) -> None:
        """AC-003: "unsupported" without the version is a dead end for the user.

        The closed detail shape is `{"found_version": str}` — coarse metadata,
        never card prose.
        """

        payload = _card(
            supportedInterfaces=[
                {
                    "url": "https://agent.example.com/rpc",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": version,
                }
            ]
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_PROTOCOL_VERSION_UNSUPPORTED
        assert result.failure_detail == {"found_version": version}
        assert result.interface_url is None

    def test_014_FR_002_no_jsonrpc_interface_at_all_is_a_different_failure(
        self,
    ) -> None:
        """An agent that speaks only gRPC is not a wrong-version agent; telling
        the user to "upgrade the version" would send them nowhere."""

        payload = _card(
            supportedInterfaces=[
                {
                    "url": "https://agent.example.com/grpc",
                    "protocolBinding": "GRPC",
                    "protocolVersion": "1.0",
                }
            ]
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_NO_SUPPORTED_INTERFACE
        assert result.failure_detail is None

    def test_014_FR_001_the_interface_host_is_validated_separately(self) -> None:
        """FR-004: the card may name a *different* host than the one the user
        typed, so the endpoint that will receive their Task and credential gets
        its own destination check. A card is not a permission slip."""

        result = interpret_card(
            V1_CARD, auth_scheme="bearer", validate_interface_host=_refuse_host
        )

        assert result.failure_code == A2A_NO_SUPPORTED_INTERFACE
        assert result.interface_url is None


class TestSecuritySchemes:
    """Which header carries the user's credential — chosen by the card, never
    by the user, and never one the transport already owns."""

    def test_014_FR_002_bearer_is_recognised_in_both_shapes(self) -> None:
        for payload in (V1_CARD, LEGACY_CARD):
            result = interpret_card(
                payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
            )
            assert result.failure_code is None
            # A bearer connection stores no header name at all: the header is
            # derived from the scheme at request time, and storing
            # "Authorization" would be refused by the connection model itself.
            assert result.auth_header_name is None

    @pytest.mark.parametrize(
        "scheme_payload",
        [
            {"apiKeySecurityScheme": {"location": "header", "name": "X-Agent-Key"}},
            {"type": "apiKey", "in": "header", "name": "X-Agent-Key"},
        ],
        ids=["v1", "legacy"],
    )
    def test_014_FR_002_an_api_key_header_name_comes_from_the_card(
        self, scheme_payload: dict[str, Any]
    ) -> None:
        """AC-002: the user never types a header name in 014. It is discovered,
        which is what makes the reserved-name check below meaningful."""

        payload = _card(
            securitySchemes={"apikey": scheme_payload},
            securityRequirements=[{"apikey": []}],
        )

        result = interpret_card(
            payload, auth_scheme="api_key", validate_interface_host=_allow_any_host
        )

        assert result.failure_code is None
        assert result.auth_header_name == "X-Agent-Key"

    @pytest.mark.parametrize(
        "header_name",
        ["Authorization", "authorization", "Host", "Content-Length", "A2A-Version"],
    )
    def test_014_FR_002_a_reserved_api_key_header_is_refused_naming_the_scheme(
        self, header_name: str
    ) -> None:
        """AC-004: a card that names a transport-structural header is asking
        BrainBuddy to overwrite its own framing or its own auth. Honouring it
        would let a card redirect a credential, corrupt a request, or replace
        the protocol version the wire contract pins. Refused, in any casing."""

        payload = _card(
            securitySchemes={
                "apikey": {
                    "type": "apiKey",
                    "in": "header",
                    "name": header_name,
                }
            },
            securityRequirements=[{"apikey": []}],
        )

        result = interpret_card(
            payload, auth_scheme="api_key", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_AUTH_SCHEME_UNSUPPORTED
        assert result.failure_detail == {"scheme": "apikey"}
        assert result.auth_header_name is None

    @pytest.mark.parametrize(
        "header_name", ["X Agent Key", "X-Agent-Key\r\n", "Ключ", ""]
    )
    def test_014_FR_002_a_non_token_api_key_header_is_refused(
        self, header_name: str
    ) -> None:
        """A field name that is not an RFC 9110 token cannot be sent safely;
        the CRLF case is header injection outright."""

        payload = _card(
            securitySchemes={
                "apikey": {"type": "apiKey", "in": "header", "name": header_name}
            },
            securityRequirements=[{"apikey": []}],
        )

        result = interpret_card(
            payload, auth_scheme="api_key", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_AUTH_SCHEME_UNSUPPORTED
        assert result.failure_detail == {"scheme": "apikey"}

    @pytest.mark.parametrize(
        ("scheme_name", "scheme_payload"),
        [
            ("oauth", {"type": "oauth2", "flows": {}}),
            ("oidc", {"type": "openIdConnect"}),
            ("mtls", {"type": "mutualTLS"}),
            ("query", {"type": "apiKey", "in": "query", "name": "key"}),
            ("digest", {"type": "http", "scheme": "digest"}),
        ],
    )
    def test_014_FR_002_an_unsupported_scheme_is_named_rather_than_generic(
        self, scheme_name: str, scheme_payload: dict[str, Any]
    ) -> None:
        """AC-004: "unsupported" alone leaves the owner guessing which of their
        agent's schemes to change. An API key in a *query string* is refused for
        a second reason: a credential in a URL is logged by every hop."""

        payload = _card(
            securitySchemes={scheme_name: scheme_payload},
            securityRequirements=[{scheme_name: []}],
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_AUTH_SCHEME_UNSUPPORTED
        assert result.failure_detail == {"scheme": scheme_name}

    def test_014_FR_002_the_owners_chosen_scheme_must_be_one_the_card_offers(
        self,
    ) -> None:
        """Sending a bearer token to an agent that only accepts an API key
        would leak the credential to an endpoint that will reject it — a
        pointless disclosure BrainBuddy can refuse before it happens."""

        payload = _card(
            securitySchemes={
                "apikey": {"type": "apiKey", "in": "header", "name": "X-Agent-Key"}
            },
            securityRequirements=[{"apikey": []}],
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_AUTH_SCHEME_UNSUPPORTED

    def test_014_FR_017_a_card_declaring_no_scheme_asks_for_no_authentication(
        self,
    ) -> None:
        """An agent that declares nothing is not refusing — it is open.

        The official a2a-sdk `helloworld` sample publishes no `securitySchemes`
        at all, and FR-017 requires BrainBuddy to interoperate with the
        unmodified sample. "No scheme offered" and "a scheme that is not the
        one you chose" are different facts: the second is a mismatch worth
        refusing before a credential leaves, the first is an agent saying it
        wants none. Discovery therefore succeeds and says so, and the caller is
        the one that must then send nothing (014-FR-002, 014-FR-017).
        """

        payload = _card()
        payload.pop("securitySchemes", None)
        payload.pop("securityRequirements", None)
        payload.pop("security", None)

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.ok, result.failure_code
        assert result.authenticated is False
        assert result.auth_header_name is None
        assert result.summary is not None
        assert result.summary.auth_schemes_offered == []

    def test_014_FR_002_a_card_that_offers_a_scheme_still_has_to_offer_yours(
        self,
    ) -> None:
        """The negative case, so the allowance above cannot be read as a hole.

        One declared scheme is enough to make silence meaningful again: an
        agent that named `apiKey` and nothing else has refused bearer, and the
        refusal must survive the "no schemes at all" allowance.
        """

        payload = _card(
            securitySchemes={
                "apikey": {"type": "apiKey", "in": "header", "name": "X-Agent-Key"}
            },
            securityRequirements=[{"apikey": []}],
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_AUTH_SCHEME_UNSUPPORTED
        assert result.authenticated is True

    def test_014_FR_002_every_offered_scheme_is_reported_for_the_owner_to_see(
        self,
    ) -> None:
        """AC-002: the discovery panel shows what the agent accepts, so the
        owner can pick the right one rather than guess."""

        payload = _card(
            securitySchemes={
                "bearer": {"type": "http", "scheme": "bearer"},
                "apikey": {"type": "apiKey", "in": "header", "name": "X-Agent-Key"},
                "oauth": {"type": "oauth2"},
            },
            securityRequirements=[{"bearer": []}],
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.summary is not None
        offered = {
            offer.name: offer.kind for offer in result.summary.auth_schemes_offered
        }
        assert offered == {"bearer": "bearer", "apikey": "api_key", "oauth": "oauth2"}


class TestGuaranteeTier:
    """The promise the product makes to the user about duplicate starts."""

    def test_014_FR_011_declaring_the_extension_earns_the_guaranteed_tier(
        self,
    ) -> None:
        """AC-005: the tier is read from the card, never assumed. It is the
        difference between telling a user a retry is safe and telling them it
        might start their work twice."""

        payload = _card(
            capabilities={
                "streaming": False,
                "pushNotifications": False,
                "extensions": [{"uri": SINGLE_START_EXTENSION_URI, "required": False}],
            }
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.guarantee_tier == "guaranteed"

    @pytest.mark.parametrize(
        "extensions",
        [
            [],
            [{"uri": "https://example.com/other/v1.md"}],
            [{"uri": SINGLE_START_EXTENSION_URI + "?x=1"}],
            [{"uri": SINGLE_START_EXTENSION_URI.replace("v1", "v2")}],
        ],
        ids=["none", "other", "near-miss-query", "different-version"],
    )
    def test_014_FR_011_anything_short_of_the_exact_uri_is_best_effort(
        self, extensions: list[dict[str, Any]]
    ) -> None:
        """AC-005: a near miss is not a promise. The identifier is versioned
        precisely so a v2 agent cannot be read as having made v1's guarantee."""

        payload = _card(
            capabilities={
                "streaming": False,
                "pushNotifications": False,
                "extensions": extensions,
            }
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.guarantee_tier == "best_effort"

    def test_014_FR_003_a_required_extension_we_do_not_implement_is_refused(
        self,
    ) -> None:
        """AC-005: `required: true` means the agent will not behave correctly
        without it. Connecting anyway would produce runs whose semantics
        BrainBuddy cannot vouch for, so the connection is refused instead."""

        payload = _card(
            capabilities={
                "streaming": False,
                "pushNotifications": False,
                "extensions": [
                    {"uri": "https://example.com/mandatory/v1.md", "required": True}
                ],
            }
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_NO_SUPPORTED_INTERFACE

    def test_014_FR_011_our_own_extension_marked_required_is_still_accepted(
        self,
    ) -> None:
        """BrainBuddy does implement this one, so requiring it is satisfiable."""

        payload = _card(
            capabilities={
                "streaming": False,
                "pushNotifications": False,
                "extensions": [{"uri": SINGLE_START_EXTENSION_URI, "required": True}],
            }
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code is None
        assert result.guarantee_tier == "guaranteed"


class TestCardFingerprint:
    """Drift detection: what counts as "the agent changed"."""

    def test_014_FR_003_the_fingerprint_covers_only_the_drift_relevant_subset(
        self,
    ) -> None:
        """A renamed agent has not changed where the user's data goes; a moved
        endpoint has. Fingerprinting prose would make every cosmetic edit
        invalidate a working connection and train users to click through the
        warning that matters."""

        moved = interpret_card(
            _card(description="Totally new description", name="Renamed"),
            auth_scheme="bearer",
            validate_interface_host=_allow_any_host,
        )
        original = interpret_card(
            V1_CARD, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert moved.card_fingerprint == original.card_fingerprint

    @pytest.mark.parametrize(
        "overrides",
        [
            {
                "supportedInterfaces": [
                    {
                        "url": "https://elsewhere.example.com/rpc",
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "1.0",
                    }
                ]
            },
            {
                "supportedInterfaces": [
                    {
                        "url": "https://agent.example.com/rpc",
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "1.0.4",
                    }
                ]
            },
            {
                "securitySchemes": {
                    "bearer": {"type": "apiKey", "in": "header", "name": "X-Agent-Key"}
                },
                "securityRequirements": [{"bearer": []}],
            },
            {"securityRequirements": [{"bearer": []}, {"other": []}]},
            {
                "capabilities": {
                    "streaming": True,
                    "pushNotifications": True,
                    "extensions": [{"uri": SINGLE_START_EXTENSION_URI}],
                }
            },
        ],
        ids=["endpoint", "version", "scheme", "requirements", "extensions"],
    )
    def test_014_FR_003_every_drift_relevant_change_moves_the_fingerprint(
        self, overrides: dict[str, Any]
    ) -> None:
        """AC-012: each of these changes where a credential goes, what it looks
        like, or what BrainBuddy has promised the user — so each must force a
        re-test and fresh reauthentication rather than pass silently."""

        original = interpret_card(
            V1_CARD,
            auth_scheme="api_key" if "securitySchemes" in overrides else "bearer",
            validate_interface_host=_allow_any_host,
        )
        changed = interpret_card(
            _card(**overrides),
            auth_scheme="api_key" if "securitySchemes" in overrides else "bearer",
            validate_interface_host=_allow_any_host,
        )

        assert changed.card_fingerprint != original.card_fingerprint

    def test_014_FR_003_the_fingerprint_is_a_stable_sha256_hex_digest(self) -> None:
        """It is stored and compared across processes, so it cannot depend on
        dict ordering or on a per-process hash seed."""

        result = interpret_card(
            V1_CARD, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.card_fingerprint is not None
        assert len(result.card_fingerprint) == 64
        assert set(result.card_fingerprint) <= set("0123456789abcdef")

        reshuffled = json.loads(json.dumps(V1_CARD))
        reshuffled["capabilities"] = dict(
            reversed(list(reshuffled["capabilities"].items()))
        )
        again = interpret_card(
            reshuffled, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )
        assert again.card_fingerprint == result.card_fingerprint

    def test_014_FR_003_the_fingerprint_helper_is_callable_on_a_summary(self) -> None:
        """The run pins a copy at dispatch, so the same value has to be
        derivable from a stored summary and not only during a fetch."""

        result = interpret_card(
            V1_CARD, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )
        assert result.summary is not None

        assert card_fingerprint(result.summary) == result.card_fingerprint


class TestSummaryBounds:
    """A card is agent-controlled text, so every copied field is bounded."""

    def test_014_FR_001_card_text_is_bounded_field_by_field(self) -> None:
        """AC-031: an unbounded copy lets a stranger's server decide how large
        a BrainBuddy row is. The bound is applied here, once, so no surface has
        to defend itself."""

        payload = _card(
            name="n" * 500,
            version="v" * 200,
            description="d" * (MAX_CARD_DESCRIPTION_CHARS + 1000),
            skills=[
                {
                    "id": "i" * 400,
                    "name": "s" * 500,
                    "description": "x" * (MAX_SKILL_TEXT_CHARS + 100),
                }
                for _ in range(MAX_SKILLS + 25)
            ],
            capabilities={
                "streaming": False,
                "pushNotifications": False,
                "extensions": [
                    {"uri": f"https://example.com/{index}"}
                    for index in range(MAX_EXTENSIONS + 10)
                ],
            },
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )
        summary = result.summary
        assert summary is not None

        assert len(summary.name or "") == 200
        assert len(summary.version or "") == 64
        assert len(summary.description or "") == MAX_CARD_DESCRIPTION_CHARS
        assert len(summary.skills) == MAX_SKILLS
        assert len(summary.skills[0].id or "") == 128
        assert len(summary.skills[0].name or "") == 200
        assert len(summary.skills[0].description or "") == MAX_SKILL_TEXT_CHARS
        assert len(summary.extension_uris) == MAX_EXTENSIONS
        assert all(len(uri) <= 512 for uri in summary.extension_uris)

    def test_014_FR_001_card_text_is_copied_verbatim_within_its_bounds(self) -> None:
        """AC-031: no escaping, no stripping, no linkifying. The string is
        stored as the agent sent it and rendered inertly by both clients;
        transforming it here would hide what the agent actually claims."""

        markup = "<script>alert(1)</script> **bold** [x](javascript:alert(1))"
        payload = _card(description=markup, name=markup)

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.summary is not None
        assert result.summary.description == markup
        assert result.summary.name == markup[:200]


class TricklingStream(httpx.SyncByteStream):
    """A card body that never ends, a byte at a time.

    The shape no configured limit catches: each chunk restarts httpx's read
    timeout and the total stays far under the byte cap, so nothing but the
    absolute wall-clock deadline ever closes it.
    """

    def __init__(self, interval_seconds: float) -> None:
        self.interval_seconds = interval_seconds

    def __iter__(self) -> Iterator[bytes]:
        while True:  # pragma: no branch - closed by the deadline, never by us
            time.sleep(self.interval_seconds)
            yield b"{"


class TestFetchFailures:
    """What a failed discovery tells the user, and what it never tells them."""

    @staticmethod
    def _fetch(
        handler: Any,
        address: str = "https://agent.example.com",
        *,
        timeout_seconds: float = 5.0,
        deadline_margin_seconds: float = CARD_DEADLINE_MARGIN_SECONDS,
    ) -> Any:
        def client_factory(**kwargs: Any) -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

        return fetch_card(
            address,
            auth_scheme="bearer",
            timeout_seconds=timeout_seconds,
            max_response_bytes=64_000,
            resolver=lambda host, port: ["93.184.216.34"],
            client_factory=client_factory,
            deadline_margin_seconds=deadline_margin_seconds,
        )

    def test_014_FR_002_a_card_that_trickles_past_the_deadline_is_unreachable(
        self,
    ) -> None:
        """AC-003. A server that answers slowly for ever is not a 500.

        The connection succeeded and the bytes are arriving, so neither the
        read timeout nor the byte cap fires; only the absolute deadline does.
        Letting that escape `fetch_card` turns an ordinary bad agent into a
        BrainBuddy server error with no corrective action for the owner.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, stream=TricklingStream(0.02))

        result = self._fetch(handler, timeout_seconds=0.2, deadline_margin_seconds=0.0)

        assert result.failure_code == A2A_UNREACHABLE
        assert result.failure_detail is None
        assert result.summary is None

    @pytest.mark.parametrize(
        ("address", "expected"),
        [
            ("https://agent.example.com", "https://agent.example.com" + CARD_PATH),
            ("https://agent.example.com/", "https://agent.example.com" + CARD_PATH),
            (
                "https://agent.example.com/base",
                "https://agent.example.com/base" + CARD_PATH,
            ),
            (
                "https://agent.example.com/.well-known/agent-card.json",
                "https://agent.example.com/.well-known/agent-card.json",
            ),
        ],
    )
    def test_014_FR_001_the_card_url_accepts_an_origin_or_a_full_card_url(
        self, address: str, expected: str
    ) -> None:
        """Owners paste both; guessing wrong sends the credential-free probe to
        a 404 and reports a working agent as "not an agent"."""

        assert card_url_for(address) == expected

    def test_014_FR_001_the_card_is_fetched_without_a_credential(self) -> None:
        """AC-001: discovery happens before the agent is trusted, so nothing
        secret may be sent to an address that has not yet proved anything."""

        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=V1_CARD)

        result = self._fetch(handler)

        assert result.failure_code is None
        assert len(seen) == 1
        assert "authorization" not in {k.lower() for k in seen[0].headers}
        assert seen[0].headers["accept"] == "application/json"

    def test_014_FR_002_a_transport_failure_is_unreachable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        result = self._fetch(handler)

        assert result.failure_code == A2A_UNREACHABLE
        assert result.failure_detail is None

    @pytest.mark.parametrize("status", [404, 410, 500])
    def test_014_FR_002_a_non_card_http_answer_is_not_an_agent(
        self, status: int
    ) -> None:
        """AC-003: an HTTP server that is not an agent is a different problem
        from an unreachable host, and the fix the owner needs differs too."""

        result = self._fetch(lambda request: httpx.Response(status, text="nope"))

        assert result.failure_code == A2A_NOT_AN_AGENT

    @pytest.mark.parametrize(
        "body",
        [
            "not json at all",
            "[]",
            '"a string"',
            "{}",
            '{"name": "no interfaces"}',
            '{"supportedInterfaces": [{"url": "https://a.example/x"}]}',
        ],
    )
    def test_014_FR_002_a_body_without_a_card_shape_is_not_an_agent(
        self, body: str
    ) -> None:
        """A 200 proves a socket answered, not that a card arrived."""

        result = self._fetch(
            lambda request: httpx.Response(
                200, content=body, headers={"content-type": "application/json"}
            )
        )

        assert result.failure_code == A2A_NOT_AN_AGENT

    def test_014_FR_002_an_over_cap_card_body_is_not_an_agent(self) -> None:
        """A truncated card is not a card. Parsing a prefix would let an agent
        choose which half of its own security schemes BrainBuddy reads."""

        oversized = json.dumps({**V1_CARD, "description": "x" * 200_000})
        result = self._fetch(
            lambda request: httpx.Response(
                200, content=oversized, headers={"content-type": "application/json"}
            )
        )

        assert result.failure_code == A2A_NOT_AN_AGENT

    def test_014_FR_002_a_redirected_card_fetch_is_refused(self) -> None:
        """Redirects are never followed on the relay's egress path; a card
        fetch is where a redirect would be cheapest to abuse."""

        result = self._fetch(
            lambda request: httpx.Response(302, headers={"location": "https://evil/"})
        )

        assert result.failure_code is not None
        assert result.summary is None

    def test_014_FR_002_a_private_destination_is_refused_before_any_request(
        self,
    ) -> None:
        """FR-004: the network-class check happens before the socket, so a
        rebinding answer cannot move the fetch after the decision."""

        called: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            called.append(request)
            return httpx.Response(200, json=V1_CARD)

        def client_factory(**kwargs: Any) -> httpx.Client:
            return httpx.Client(transport=httpx.MockTransport(handler), **kwargs)

        result = fetch_card(
            "https://internal.example.com",
            auth_scheme="bearer",
            timeout_seconds=5.0,
            max_response_bytes=64_000,
            resolver=lambda host, port: ["169.254.169.254"],
            client_factory=client_factory,
        )

        assert result.failure_code is not None
        assert result.failure_code.startswith("destination_")
        assert called == []

    def test_014_FR_002_no_failure_detail_ever_carries_card_prose(self) -> None:
        """AC-003: `last_test_error_detail` is coarse metadata with closed
        per-code shapes. Echoing an agent's error text into it would put
        untrusted prose on a surface that is not treated as untrusted."""

        payload = _card(
            supportedInterfaces=[
                {
                    "url": "https://agent.example.com/rpc",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "9.9",
                }
            ],
            description="<img src=x onerror=alert(1)>",
        )

        result = self._fetch(lambda request: httpx.Response(200, json=payload))

        assert result.failure_code == A2A_PROTOCOL_VERSION_UNSUPPORTED
        assert result.failure_detail == {"found_version": "9.9"}
        assert json.dumps(result.failure_detail) == '{"found_version": "9.9"}'


class TestDiscoveryResultEdges:
    """Cards that are shaped like cards but do not carry what one carries.

    Each case here is a way for discovery to end without a usable interface,
    and the thing being tested is which of the closed failure codes the owner
    is shown — because that code is the whole of the guidance they get.

    014-FR-001, 014-FR-002.
    """

    def test_014_FR_001_a_card_omitting_optional_text_keeps_those_fields_empty(
        self,
    ) -> None:
        """AC-001: absent is not the same as blank, and neither is a failure.

        A card is allowed to carry no description and no version. Copying
        `None` through rather than substituting a placeholder keeps the
        connection inspector honest: it shows nothing because the agent said
        nothing, not a string BrainBuddy made up.
        """

        payload = _card()
        del payload["description"]
        del payload["version"]

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.ok
        assert result.summary is not None
        assert result.summary.description is None
        assert result.summary.version is None
        assert result.summary.name == "Sample Agent"

    def test_014_FR_002_ok_is_the_single_reading_of_a_discovery_result(self) -> None:
        """One question, one answer, on every call site.

        `summary is not None` and `failure_code is None` are the same question
        asked two ways, and two ways is how a caller ends up treating a failure
        as a partial success.
        """

        good = interpret_card(
            _card(), auth_scheme="bearer", validate_interface_host=_allow_any_host
        )
        bad = interpret_card(
            {"not": "a card"},
            auth_scheme="bearer",
            validate_interface_host=_allow_any_host,
        )

        assert good.ok is True
        assert bad.ok is False
        assert bad.failure_code == A2A_NOT_AN_AGENT

    def test_014_FR_002_a_payload_of_the_wrong_types_is_not_an_agent(self) -> None:
        """A JSON object is not yet a card.

        The address answered 200 with valid JSON, so it is not unreachable; what
        it sent cannot be parsed as a card, so it is not an agent. Anything more
        specific would be a guess about someone else's server.
        """

        result = interpret_card(
            {"name": 12345, "supportedInterfaces": "not-a-list"},
            auth_scheme="bearer",
            validate_interface_host=_allow_any_host,
        )

        assert result.failure_code == A2A_NOT_AN_AGENT
        assert result.failure_detail is None

    def test_014_FR_002_the_first_unsupported_version_is_the_one_reported(
        self,
    ) -> None:
        """AC-002: several wrong versions are still one message to the owner.

        The report names the first version seen rather than a list, because the
        owner's next action is the same either way — upgrade the agent — and a
        list of every interface's version is detail they cannot use.
        """

        payload = _card(
            supportedInterfaces=[
                {
                    "url": "https://agent.example.com/old",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "0.9",
                },
                {
                    "url": "https://agent.example.com/older",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "0.8",
                },
            ]
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_PROTOCOL_VERSION_UNSUPPORTED
        assert result.failure_detail == {"found_version": "0.9"}

    def test_014_FR_002_a_refused_host_outranks_an_unsupported_version(self) -> None:
        """ "We will not talk to that address" is true whatever it claimed.

        Reporting the version instead would send the owner off to upgrade an
        agent BrainBuddy was never going to reach, and the upgrade would not
        change the answer.
        """

        payload = _card(
            supportedInterfaces=[
                {
                    "url": "https://agent.example.com/old",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "0.9",
                },
                {
                    "url": "https://internal.example.com/rpc",
                    "protocolBinding": "JSONRPC",
                    "protocolVersion": "1.0",
                },
            ]
        )

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_refuse_host
        )

        assert result.failure_code == A2A_NO_SUPPORTED_INTERFACE
        assert result.failure_detail is None

    def test_014_FR_001_a_card_that_states_its_transport_only_at_the_top_level(
        self,
    ) -> None:
        """AC-001: the pre-1.0 shape has no `supportedInterfaces` at all.

        Older A2A cards name one URL at the top level and say the transport
        beside it. Treating that as an interface here means selection has one
        shape to reason about; refusing it would report a working agent as
        having no supported interface, which is the least actionable message
        discovery can produce.
        """

        payload = _card()
        del payload["supportedInterfaces"]
        payload["url"] = "https://agent.example.com/legacy-rpc"
        payload["preferredTransport"] = "JSONRPC"
        payload["protocolVersion"] = "1.0"

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.ok
        assert result.interface_url == "https://agent.example.com/legacy-rpc"

    def test_014_FR_002_a_card_naming_no_url_at_all_is_not_an_agent(self) -> None:
        """Nothing to call is not a partial success.

        Without `supportedInterfaces` and without a top-level `url` there is no
        address, so there is no connection to make — and the owner's next move
        is to check the address they typed, not the agent.
        """

        payload = _card()
        del payload["supportedInterfaces"]

        result = interpret_card(
            payload, auth_scheme="bearer", validate_interface_host=_allow_any_host
        )

        assert result.failure_code == A2A_NOT_AN_AGENT
