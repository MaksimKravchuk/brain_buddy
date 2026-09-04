"""Agent discovery: read a card, decide what it is allowed to mean.

A card is the first thing a stranger's server says, and it gets to name the URL
that will receive the user's Task, the header that will carry their credential,
and the promise the product makes about duplicate starts. So this module is
deliberately **lenient about shape and strict about meaning**.

Lenient, because both reference runtimes are legitimately non-canonical: the
a2a-sdk sample serves the 1.0 shape, Hermes serves a legacy ``securitySchemes``
entry, two undefined capability fields and no top-level protocol version.
Rejecting either would fail FR-017 while proving nothing — an unknown field is
not a threat, an unbounded one is, and bounds are applied here.

Strict where accommodation costs something:

* the interface host is validated **separately**, because a card may name a
  different host than the user typed and a card is not a permission slip;
* an API-key header name comes from the card and never from the user, and is
  refused when it collides with a transport-structural name or is not an RFC
  9110 token — honouring one would let a card redirect a credential or inject a
  header;
* a ``required: true`` extension BrainBuddy has not implemented refuses the
  connection rather than producing runs whose semantics it cannot vouch for;
* the guarantee tier is read from an exact URI. A near miss is not a promise.

Failure codes are closed, and their details are coarse metadata with fixed
shapes — never the agent's own prose, which would put untrusted text on a
surface that does not treat it as untrusted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import Field, ValidationError

from app.modules.agents.a2a.types import AgentCard, CardInterface, CardSecurityScheme
from app.modules.agents.egress import (
    DestinationRejected,
    PinnedResponse,
    Resolver,
    pinned_request,
    validate_destination,
)
from app.modules.agents.headers import (
    RESERVED_AUTH_HEADER_NAMES,
    validate_auth_header_name,
)
from app.schemas.common import StrictBaseModel
from app.utils.time import utcnow

CARD_PATH = "/.well-known/agent-card.json"
"""Where A2A §14.3 says a card lives, below the agent's origin."""

SINGLE_START_EXTENSION_URI = (
    "https://github.com/MaksimKravchuk/brain_buddy/blob/main/"
    "docs/a2a-extensions/single-start/v1.md"
)
"""The one extension BrainBuddy implements. Frozen: a v2 agent has not made
v1's promise, so matching is exact rather than by prefix."""

SUPPORTED_EXTENSION_URIS: frozenset[str] = frozenset({SINGLE_START_EXTENSION_URI})

JSONRPC_BINDING = "JSONRPC"

# --- failure categories (contracts/a2a-wire.md, FR-002) ---------------------

A2A_UNREACHABLE = "a2a_unreachable"
A2A_NOT_AN_AGENT = "a2a_not_an_agent"
A2A_NO_SUPPORTED_INTERFACE = "a2a_no_supported_interface"
A2A_PROTOCOL_VERSION_UNSUPPORTED = "a2a_protocol_version_unsupported"
A2A_AUTH_SCHEME_UNSUPPORTED = "a2a_auth_scheme_unsupported"
AGENT_CARD_CHANGED = "agent_card_changed"

# --- bounds on copied agent text (data-model.md §1) -------------------------

MAX_CARD_NAME_CHARS = 200
MAX_CARD_VERSION_CHARS = 64
MAX_CARD_DESCRIPTION_CHARS = 2_000
MAX_SKILLS = 50
MAX_SKILL_ID_CHARS = 128
MAX_SKILL_NAME_CHARS = 200
MAX_SKILL_TEXT_CHARS = 500
MAX_EXTENSIONS = 20
MAX_EXTENSION_URI_CHARS = 512
MAX_SCHEME_NAME_CHARS = 128

AuthScheme = Literal["bearer", "api_key"]
SchemeKind = Literal["bearer", "api_key", "oauth2", "oidc", "mtls", "other"]
GuaranteeTier = Literal["guaranteed", "best_effort"]

#: Protocol versions this build speaks: 1.0 and its patch releases.
_SUPPORTED_MAJOR_MINOR = "1.0"


def _supported_version(raw: str | None) -> bool:
    """``1.0`` or ``1.0.<digits>`` — nothing else.

    Written out rather than regex-matched so the accepted set is readable: a
    permissive pattern here would silently admit ``1.0-beta`` or ``1.00``, and
    an agent speaking a different protocol would be discovered only mid-run.
    """

    if not raw:
        return False
    if raw == _SUPPORTED_MAJOR_MINOR:
        return True
    prefix = _SUPPORTED_MAJOR_MINOR + "."
    return raw.startswith(prefix) and raw[len(prefix) :].isdigit()


def _bounded(value: str | None, limit: int) -> str | None:
    """Copy agent text within its bound, verbatim otherwise.

    No escaping, no stripping, no linkifying: both clients render this inertly,
    and transforming it here would hide what the agent actually claims.
    """

    if value is None:
        return None
    return value[:limit]


# --- the discovery result ----------------------------------------------------


class AgentSkillSummary(StrictBaseModel):
    """One advertised skill, bounded. Untrusted agent text."""

    id: str | None = None
    name: str | None = None
    description: str | None = None


class AgentAuthSchemeOffer(StrictBaseModel):
    """One security scheme the agent offers, normalised across both shapes."""

    name: str
    kind: SchemeKind
    header_name: str | None = None


class AgentCardSummary(StrictBaseModel):
    """The bounded copy of a card BrainBuddy keeps on a connection.

    Every string here is untrusted agent text: both clients render it as inert
    plain text, never an anchor or ``Linking`` target, never HTML- or
    markdown-interpreted, never auto-linkified (FR-016, AC-031). The bounds
    above are the only processing it receives.
    """

    name: str | None = None
    version: str | None = None
    description: str | None = None
    protocol_version: str | None = None
    interface_url: str | None = None
    streaming: bool = False
    push_notifications: bool = False
    skills: list[AgentSkillSummary] = Field(default_factory=list)
    auth_schemes_offered: list[AgentAuthSchemeOffer] = Field(default_factory=list)
    security_required: bool = False
    extension_uris: list[str] = Field(default_factory=list)
    security_requirements: list[list[str]] = Field(default_factory=list)
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class CardDiscovery:
    """The outcome of one discovery attempt: a summary, or a named failure.

    Never both. A partially-usable card is not a thing the product can act on:
    it would connect a user to an endpoint whose security scheme or protocol
    version BrainBuddy could not vouch for.
    """

    summary: AgentCardSummary | None = None
    interface_url: str | None = None
    auth_header_name: str | None = None
    guarantee_tier: GuaranteeTier | None = None
    card_fingerprint: str | None = None
    failure_code: str | None = None
    failure_detail: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.failure_code is None


def _failure(code: str, detail: dict[str, Any] | None = None) -> CardDiscovery:
    return CardDiscovery(failure_code=code, failure_detail=detail)


# --- URL handling ------------------------------------------------------------


def card_url_for(address: str) -> str:
    """The card URL for an agent address.

    Owners paste both an origin and a full card URL, and guessing wrong sends
    the credential-free probe to a 404 — reporting a working agent as "not an
    agent", which is the least actionable message the product has.
    """

    candidate = address.strip()
    if candidate.rstrip("/").endswith(CARD_PATH):
        return candidate
    return candidate.rstrip("/") + CARD_PATH


# --- security schemes --------------------------------------------------------


#: Legacy ``type`` values that map straight to a kind BrainBuddy cannot use but
#: can still *name* back to the owner, which is the whole point of reporting an
#: unsupported scheme rather than a generic failure.
_LEGACY_TYPE_KINDS: dict[str, SchemeKind] = {
    "oauth2": "oauth2",
    "openidconnect": "oidc",
    "oidc": "oidc",
    "mutualtls": "mtls",
    "mtls": "mtls",
}


def _http_scheme_kind(raw_scheme: str | None) -> SchemeKind:
    """Only ``bearer`` is usable; ``basic``, ``digest`` and friends are not."""

    return "bearer" if (raw_scheme or "").strip().lower() == "bearer" else "other"


def _api_key_kind(location: str | None, name: object) -> tuple[SchemeKind, str | None]:
    """An API key is usable only in a header.

    A key in a *query string* is deliberately refused: a credential in a URL is
    logged by every hop between here and the agent, including ones neither
    party controls.
    """

    if (location or "").strip().lower() == "header" and isinstance(name, str):
        return "api_key", name
    return "other", None


def _scheme_kind_and_header(
    scheme: CardSecurityScheme,
) -> tuple[SchemeKind, str | None]:
    """Normalise one scheme across the 1.0 and legacy shapes.

    Returns the kind BrainBuddy recognises plus the header name for an API key.
    The 1.0 shape nests its detail; the legacy shape is flat. Both are read
    here so no caller has to know which one arrived.
    """

    if scheme.http_auth is not None:
        return _http_scheme_kind(str(scheme.http_auth.get("scheme") or "")), None
    if scheme.api_key is not None:
        return _api_key_kind(
            str(scheme.api_key.get("location") or scheme.api_key.get("in") or ""),
            scheme.api_key.get("name"),
        )

    declared = (scheme.type or "").strip().lower()
    if declared == "http":
        return _http_scheme_kind(scheme.scheme), None
    if declared == "apikey":
        return _api_key_kind(scheme.location, scheme.name)
    return _LEGACY_TYPE_KINDS.get(declared, "other"), None


def _offered_schemes(card: AgentCard) -> list[tuple[str, SchemeKind, str | None]]:
    return [
        (name[:MAX_SCHEME_NAME_CHARS], *_scheme_kind_and_header(scheme))
        for name, scheme in card.security_schemes.items()
    ]


def _requirement_names(card: AgentCard) -> list[list[str]]:
    """Requirement alternatives as sorted scheme-name lists.

    Sorted so the fingerprint below cannot move because an agent reordered a
    JSON object; the *set* of accepted schemes is what matters.
    """

    return [
        sorted(str(name) for name in requirement)
        for requirement in card.declared_requirements
        if isinstance(requirement, dict)
    ]


#: Names the A2A envelope itself occupies (``contracts/a2a-wire.md``, Request
#: envelope). They sit here rather than in ``headers.py`` because they are this
#: protocol's framing, not the relay's generic transport reservations, and a
#: card that named one would be asking BrainBuddy to let the agent choose its
#: own protocol version or activate its own extensions.
_A2A_PROTOCOL_HEADERS: frozenset[str] = frozenset(
    {"a2a-version", "a2a-extensions", "x-correlation-id"}
)


def _usable_header_name(raw: str | None) -> str | None:
    """An API-key header name, or ``None`` when it may not be sent.

    Refuses a reserved transport-structural name in any casing and anything
    that is not an RFC 9110 token — the second check is header injection
    protection, not tidiness.
    """

    if not raw:
        return None
    folded = raw.casefold()
    if folded in RESERVED_AUTH_HEADER_NAMES or folded in _A2A_PROTOCOL_HEADERS:
        return None
    try:
        return validate_auth_header_name(raw)
    except ValueError:
        return None


def _select_scheme(
    card: AgentCard, auth_scheme: AuthScheme
) -> tuple[str | None, str | None]:
    """Pick the card scheme satisfying the owner's choice.

    Returns ``(header_name, failing_scheme_name)``; ``header_name`` is ``None``
    for bearer, which derives ``Authorization`` at request time and therefore
    stores no header name at all.

    Sending a bearer token to an agent that only accepts an API key would leak
    the credential to an endpoint certain to reject it, so a mismatch is refused
    before the disclosure rather than after.
    """

    offered = _offered_schemes(card)
    for name, kind, header in offered:
        if kind != auth_scheme:
            continue
        if kind == "bearer":
            return None, None
        usable = _usable_header_name(header)
        if usable is not None:
            return usable, None
        return None, name

    # Nothing matched. Name the scheme the owner would have to change: a bare
    # "unsupported" leaves them guessing which of their agent's schemes is the
    # problem.
    return None, (offered[0][0] if offered else auth_scheme)


# --- interface selection ------------------------------------------------------


def _select_interface(
    card: AgentCard, validate_interface_host: Callable[[str], None]
) -> tuple[CardInterface | None, str | None, str | None]:
    """First JSONRPC interface on a supported version whose host is allowed.

    Returns ``(interface, failure_code, found_version)``. Three distinct
    outcomes, because the fix the owner needs differs: no JSON-RPC transport at
    all, a JSON-RPC transport on the wrong protocol version, or a JSON-RPC 1.0
    transport pointed at a host BrainBuddy refuses to dial.
    """

    jsonrpc = [
        interface
        for interface in card.interfaces
        if interface.binding.upper() == JSONRPC_BINDING and interface.url
    ]
    if not jsonrpc:
        return None, A2A_NO_SUPPORTED_INTERFACE, None

    found_version: str | None = None
    host_refused = False
    for interface in jsonrpc:
        version = interface.protocol_version or card.protocol_version
        if not _supported_version(version):
            if found_version is None:
                found_version = version or ""
            continue
        try:
            validate_interface_host(interface.url)
        except DestinationRejected:
            host_refused = True
            continue
        return interface, None, version

    if host_refused:
        return None, A2A_NO_SUPPORTED_INTERFACE, None
    if found_version is not None:
        return None, A2A_PROTOCOL_VERSION_UNSUPPORTED, found_version
    return None, A2A_NO_SUPPORTED_INTERFACE, None


# --- fingerprint --------------------------------------------------------------


def _fingerprint_subset(summary: AgentCardSummary) -> dict[str, Any]:
    """The drift-relevant subset of a card (data-model.md §1).

    Prose is excluded on purpose. A renamed agent has not changed where the
    user's data goes; a moved endpoint has. Fingerprinting the description
    would make every cosmetic edit invalidate a working connection and train
    users to click through the one warning that matters.
    """

    return {
        "interface_url": summary.interface_url,
        "protocol_version": summary.protocol_version,
        "security_schemes": {
            offer.name: {"kind": offer.kind, "header": offer.header_name}
            for offer in summary.auth_schemes_offered
        },
        "security_requirements": summary.security_requirements,
        "extension_uris": summary.extension_uris,
    }


def card_fingerprint(summary: AgentCardSummary) -> str:
    """Stable sha256 over the drift-relevant subset.

    Canonical JSON with sorted keys: the value is stored and compared across
    processes, so it must not depend on dict ordering or a per-process hash
    seed.
    """

    canonical = json.dumps(
        _fingerprint_subset(summary),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- interpretation -----------------------------------------------------------


def interpret_card(
    payload: Any,
    *,
    auth_scheme: AuthScheme,
    validate_interface_host: Callable[[str], None],
    now: datetime | None = None,
) -> CardDiscovery:
    """Turn a parsed card body into a discovery result or a named failure.

    Pure apart from ``validate_interface_host``, which is injected so the
    network-class check stays in ``egress`` and this function stays testable
    over the whole card space without DNS.
    """

    if not isinstance(payload, dict):
        return _failure(A2A_NOT_AN_AGENT)
    try:
        card = AgentCard.model_validate(payload)
    except ValidationError:
        return _failure(A2A_NOT_AN_AGENT)
    if not card.name or not card.interfaces:
        # A 200 proves a socket answered, not that a card arrived.
        return _failure(A2A_NOT_AN_AGENT)

    extensions = card.capabilities.extensions[:MAX_EXTENSIONS]
    unimplemented_required = [
        extension
        for extension in extensions
        if extension.required and extension.uri not in SUPPORTED_EXTENSION_URIS
    ]
    if unimplemented_required:
        # `required: true` means the agent will not behave correctly without it.
        # Connecting anyway would produce runs whose semantics BrainBuddy cannot
        # vouch for.
        return _failure(A2A_NO_SUPPORTED_INTERFACE)

    interface, failure, found_version = _select_interface(card, validate_interface_host)
    if interface is None:
        detail = (
            {"found_version": found_version}
            if failure == A2A_PROTOCOL_VERSION_UNSUPPORTED
            else None
        )
        return _failure(failure or A2A_NO_SUPPORTED_INTERFACE, detail)

    header_name, failing_scheme = _select_scheme(card, auth_scheme)
    if failing_scheme is not None:
        return _failure(A2A_AUTH_SCHEME_UNSUPPORTED, {"scheme": failing_scheme})

    summary = AgentCardSummary(
        name=_bounded(card.name, MAX_CARD_NAME_CHARS),
        version=_bounded(card.version, MAX_CARD_VERSION_CHARS),
        description=_bounded(card.description, MAX_CARD_DESCRIPTION_CHARS),
        protocol_version=found_version,
        interface_url=interface.url,
        streaming=card.capabilities.streaming,
        push_notifications=card.capabilities.push_notifications,
        skills=[
            AgentSkillSummary(
                id=_bounded(skill.id, MAX_SKILL_ID_CHARS),
                name=_bounded(skill.name, MAX_SKILL_NAME_CHARS),
                description=_bounded(skill.description, MAX_SKILL_TEXT_CHARS),
            )
            for skill in card.skills[:MAX_SKILLS]
        ],
        auth_schemes_offered=[
            AgentAuthSchemeOffer(name=name, kind=kind, header_name=header)
            for name, kind, header in _offered_schemes(card)
        ],
        security_required=bool(card.declared_requirements),
        extension_uris=[
            extension.uri[:MAX_EXTENSION_URI_CHARS] for extension in extensions
        ],
        security_requirements=_requirement_names(card),
        fetched_at=now or utcnow(),
    )

    tier: GuaranteeTier = (
        "guaranteed"
        if SINGLE_START_EXTENSION_URI in summary.extension_uris
        else "best_effort"
    )

    return CardDiscovery(
        summary=summary,
        interface_url=interface.url,
        auth_header_name=header_name,
        guarantee_tier=tier,
        card_fingerprint=card_fingerprint(summary),
    )


# --- fetch --------------------------------------------------------------------


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def fetch_card(
    address: str,
    *,
    auth_scheme: AuthScheme,
    timeout_seconds: float,
    max_response_bytes: int,
    allow_private_destinations: bool = False,
    resolver: Resolver | None = None,
    client_factory: Callable[..., httpx.Client] | None = None,
    now: datetime | None = None,
) -> CardDiscovery:
    """Fetch and interpret an agent card. No credential is ever sent.

    Discovery happens before the agent has proved anything, so the probe is
    credential-free: a wrong address must not be able to collect a secret.
    """

    card_url = card_url_for(address)
    try:
        destination = validate_destination(
            card_url,
            allow_private_destinations=allow_private_destinations,
            resolver=resolver,
        )
    except DestinationRejected as exc:
        # The network-class check runs before the socket, so a rebinding answer
        # cannot move the fetch after the decision was made.
        return _failure(exc.code)

    try:
        response: PinnedResponse = pinned_request(
            method="GET",
            destination=destination,
            headers={"Accept": "application/json"},
            json_body=None,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            client_factory=client_factory,
            deadline_seconds=timeout_seconds + 5,
        )
    except DestinationRejected as exc:
        # An over-cap or malformed body is "not an agent": a truncated card is
        # not a card, and parsing a prefix would let the agent choose which half
        # of its own security schemes BrainBuddy reads.
        return _failure(
            A2A_NOT_AN_AGENT if exc.code == "destination_invalid" else exc.code
        )
    except httpx.HTTPError:
        return _failure(A2A_UNREACHABLE)

    if response.status_code != 200:
        return _failure(A2A_NOT_AN_AGENT)

    try:
        payload = json.loads(response.body)
    except (ValueError, UnicodeDecodeError):
        return _failure(A2A_NOT_AN_AGENT)

    def _validate_interface_host(url: str) -> None:
        validate_destination(
            url,
            allow_private_destinations=allow_private_destinations,
            resolver=resolver,
        )

    result = interpret_card(
        payload,
        auth_scheme=auth_scheme,
        validate_interface_host=_validate_interface_host,
        now=now,
    )
    if result.summary is not None and result.summary.interface_url is None:
        # Defensive: an interface-less success is not representable, but the
        # origin is what a caller would fall back to and it must not be silent.
        return _failure(A2A_NO_SUPPORTED_INTERFACE)
    return result


__all__ = [
    "A2A_AUTH_SCHEME_UNSUPPORTED",
    "A2A_NOT_AN_AGENT",
    "A2A_NO_SUPPORTED_INTERFACE",
    "A2A_PROTOCOL_VERSION_UNSUPPORTED",
    "A2A_UNREACHABLE",
    "AGENT_CARD_CHANGED",
    "CARD_PATH",
    "MAX_CARD_DESCRIPTION_CHARS",
    "MAX_EXTENSIONS",
    "MAX_SKILLS",
    "MAX_SKILL_TEXT_CHARS",
    "SINGLE_START_EXTENSION_URI",
    "SUPPORTED_EXTENSION_URIS",
    "AgentAuthSchemeOffer",
    "AgentCardSummary",
    "AgentSkillSummary",
    "AuthScheme",
    "CardDiscovery",
    "GuaranteeTier",
    "card_fingerprint",
    "card_url_for",
    "fetch_card",
    "interpret_card",
]
