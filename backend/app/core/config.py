"""Application configuration helpers."""

from __future__ import annotations

import logging
import math
import os
import socket
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

load_dotenv()

APP_DIR = Path(__file__).resolve().parent.parent
BACKEND_ROOT = APP_DIR.parent
DEFAULT_DATA_DIR = BACKEND_ROOT / "data"
SCHEMA_VERSION_FILENAME = "schema_version"
DEFAULT_SCHEMA_VERSION = "0.1.0"


class AppEnvironment(str, Enum):
    """Deployment environment flags."""

    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TEST = "test"


# Explicit allow-list of server-owned feature flags. A flag must be declared
# here before configuration may reference it; anything else fails closed at
# startup. Flags gate exposure/rollout only — they are never authorization.
#
# ``voice_brain_dump`` (ADR-0008) gates the native voice Brain Dump feature:
# the backend brain-dump commands and provider discovery, plus the frontend
# route (which reads the effective flag from ``/api/auth/me``). It ships
# default OFF and rolls out OFF → INTERNAL → ON like every other flag.
#
# ``mobile_task_classification`` (spec 006, FR-015) gates assigning a project
# and Tags from the mobile task detail screen. It is purely client-side
# exposure: no route, service or stored shape changes with it, and the mobile
# client reads the effective value from ``/api/auth/me`` exactly as the
# frontend reads ``voice_brain_dump``. Default OFF means the task screen keeps
# today's presentation until the flag is deliberately turned on.
#
# ``external_agent_relay`` (ADR-0008) gates the bring-your-own-agent relay:
# connection management, hand-off, and the owner-facing run projection. Inbound
# connector events are deliberately *not* flag-gated — a run already dispatched
# must keep being able to report even if the flag is later turned off for its
# owner, or the user would be left with a run frozen mid-flight.
#
# Runtime-manageable subset (spec 010, DD-1, DD-15, DD-16, superseded
# 2026-08-15): ``voice_brain_dump``, ``mobile_task_classification`` and
# ``external_agent_relay`` are managed exclusively by the SQLite-backed
# ``FeatureFlagOverrideRepository`` once the one-time migration has run
# (ADR-0019). Their deploy-staged environment text reaches this module only as
# the raw ``ManagedFlagMigrationInput`` below, parsed solely by the one-time
# migration; they have no runtime state here at all, because the normal
# per-request resolver is `FeatureFlagService`, not this class.
# ``delivery_canary`` (a production release-smoke input) is the only flag
# that still resolves from this configuration on every request.
#
# ``admin_portal`` no longer exists as a flag at all (DD-14): the Admin
# Portal is key functionality and is always reachable by an authenticated,
# allow-listed operator (`require_operator`), never gated by a flag that
# could lock the only operator out.
KNOWN_FEATURE_FLAGS: tuple[str, ...] = (
    "delivery_canary",
    "voice_brain_dump",
    "mobile_task_classification",
    "external_agent_relay",
)

# Every flag name ``BRAIN_BUDDY_FEATURE_FLAGS`` may configure. There is no
# more private subset (DD-14): ``PRIVATE_FEATURE_FLAGS`` held only
# ``admin_portal``, which is deleted outright, not merely excluded.
ALL_FEATURE_FLAGS: tuple[str, ...] = KNOWN_FEATURE_FLAGS

# The flags this configuration still owns *at runtime*: the only ones whose
# environment entry is parsed and validated when the application boots, and the
# only ones `FeatureFlagSettings.states` may hold or accept. Everything else
# ``BRAIN_BUDDY_FEATURE_FLAGS`` may name is managed migration input (DD-15) —
# see ``ManagedFlagMigrationInput`` below.
ENVIRONMENT_OWNED_FLAGS: tuple[str, ...] = ("delivery_canary",)

# The complement: the flags SQLite owns after the one-time migration. Derived
# rather than restated so the two sets cannot drift apart, and mirrored by
# `app.repositories.feature_flag.MANAGED_FLAGS`, which is where they are
# actually resolved.
RUNTIME_MANAGED_FLAGS: tuple[str, ...] = tuple(
    name for name in KNOWN_FEATURE_FLAGS if name not in ENVIRONMENT_OWNED_FLAGS
)


class FeatureFlagState(str, Enum):
    """Rollout stage of one allow-listed feature flag."""

    OFF = "off"
    INTERNAL = "internal"
    ON = "on"


def _normalize_internal_users(users: frozenset[str]) -> frozenset[str]:
    """Normalize a cohort of internal-user emails, rejecting a non-email."""

    normalized: set[str] = set()
    for user in users:
        candidate = user.strip().lower()
        if not candidate or "@" not in candidate:
            raise ValueError(
                f"Internal feature-flag user '{user}' is not an email address."
            )
        normalized.add(candidate)
    return frozenset(normalized)


def _reject_unknown_flags(names: Iterable[str]) -> None:
    unknown = sorted(set(names) - set(ALL_FEATURE_FLAGS))
    if unknown:
        raise ValueError(
            f"Unknown feature flag(s) {unknown}; allowed flags are "
            f"{sorted(ALL_FEATURE_FLAGS)}."
        )


@dataclass(frozen=True, slots=True)
class ManagedFlagMigrationSeed:
    """The parsed deploy-staged baseline for the three managed flags.

    Produced only by :meth:`FeatureFlagSettings.load_managed_migration_seed`,
    and only consumed by the repository's one-time migration (DD-15).
    """

    states: Mapping[str, FeatureFlagState]
    internal_users: frozenset[str] = frozenset()


class ManagedFlagMigrationInput(BaseModel):
    """The raw, **deliberately unparsed** managed-flag environment text.

    ADR-0019 leaves the three managed flags entirely to SQLite once the
    one-time migration has run, but the deploy still stages their baseline in
    ``BRAIN_BUDDY_FEATURE_FLAGS`` for a first start. Parsing that text while
    building the configuration made every later boot depend on it: a stale or
    malformed managed entry raised before the repository could even look at
    its ledger, so an already-migrated deployment could not start at all.

    The text is therefore carried verbatim here and parsed exactly once, by
    :meth:`FeatureFlagSettings.load_managed_migration_seed`, inside the
    serialized first-migration path. Post-migration it is never parsed, and so
    can never affect startup or runtime (DD-15).
    """

    raw_states: str = Field(default="", description="Raw BRAIN_BUDDY_FEATURE_FLAGS.")
    raw_internal_users: str = Field(
        default="", description="Raw BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS."
    )

    model_config = ConfigDict(frozen=True)


class FeatureFlagSettings(BaseModel):
    """The environment-owned rollout flags: default OFF, fail closed.

    Post-ADR-0019 this class is **not** an answer for the three managed flags,
    in any form: `states` holds exactly `ENVIRONMENT_OWNED_FLAGS` and refuses a
    managed key outright, and there is no aggregate resolver over
    `KNOWN_FEATURE_FLAGS` to project one (DD-15). A managed flag's only runtime
    answer is its SQLite row, read through `FeatureFlagService`. The
    deploy-staged managed text still arrives here, but only as the unparsed
    `migration_input` below.
    """

    states: Mapping[str, FeatureFlagState] = Field(
        default_factory=dict,
        validate_default=True,
        description="Rollout stage per environment-owned flag; missing are OFF.",
    )
    internal_users: frozenset[str] = Field(
        default_factory=frozenset,
        description="Normalized emails eligible for INTERNAL-stage flags.",
    )
    migration_input: ManagedFlagMigrationInput = Field(
        default_factory=ManagedFlagMigrationInput,
        description="Raw managed-flag env text, parsed only by migration.",
    )

    model_config = ConfigDict(frozen=True)

    @field_validator("states")
    @classmethod
    def validate_states(
        cls, states: Mapping[str, FeatureFlagState]
    ) -> Mapping[str, FeatureFlagState]:
        _reject_unknown_flags(states)
        # A managed key is refused rather than stored or silently dropped: a
        # caller passing one believes it is setting that flag, and either
        # materializing it or ignoring it would leave them with an answer that
        # the SQLite store — the only authority for those three — disagrees
        # with (DD-15).
        managed = sorted(set(states) & set(RUNTIME_MANAGED_FLAGS))
        if managed:
            raise ValueError(
                f"Feature flag(s) {managed} are managed at runtime by the "
                "SQLite feature-flag store (ADR-0019) and cannot be set in "
                "runtime configuration; this configuration owns "
                f"{sorted(ENVIRONMENT_OWNED_FLAGS)} only."
            )
        # The frozen model only blocks attribute assignment; the proxy makes
        # the mapping itself read-only so items cannot be mutated either.
        return MappingProxyType(
            {
                name: states.get(name, FeatureFlagState.OFF)
                for name in ENVIRONMENT_OWNED_FLAGS
            }
        )

    @field_serializer("states")
    def _serialize_states(
        self, states: Mapping[str, FeatureFlagState]
    ) -> dict[str, FeatureFlagState]:
        # MappingProxyType is not serializable by pydantic-core; dumping a
        # copy keeps model_dump/model_dump_json working without exposing the
        # internal read-only mapping.
        return dict(states)

    @field_validator("internal_users")
    @classmethod
    def validate_internal_users(cls, users: frozenset[str]) -> frozenset[str]:
        return _normalize_internal_users(users)

    def load_managed_migration_seed(self) -> ManagedFlagMigrationSeed:
        """Parse the deploy-staged managed-flag baseline, failing closed.

        The sole parser of the raw managed input, and the only place a managed
        flag's environment value exists in parsed form at all — the runtime
        `states` map above cannot hold one (DD-15). It projects exactly
        `RUNTIME_MANAGED_FLAGS`: `delivery_canary` may appear in the same
        variable and is validated at startup, but seeding it here would hand
        the migration a fourth row for a flag SQLite does not own. It keeps
        the full pre-correction strictness — malformed, unknown and duplicated
        entries all raise, and a cohort entry that is not an email raises —
        because a first start must not seed rows from input nobody validated.
        Callers hand this method to the repository as a callback so it runs
        inside the serialized first-migration transaction, never at import or
        boot time.
        """

        states = _parse_feature_flag_states(self.migration_input.raw_states)
        _reject_unknown_flags(states)
        return ManagedFlagMigrationSeed(
            states=MappingProxyType(
                {
                    name: states.get(name, FeatureFlagState.OFF)
                    for name in RUNTIME_MANAGED_FLAGS
                }
            ),
            internal_users=_normalize_internal_users(
                _split_env_list(self.migration_input.raw_internal_users)
            ),
        )

    def _is_effective(self, name: str, email: str | None) -> bool:
        """Resolve one *environment-owned* flag. Anything else raises KeyError.

        Reachable only through `delivery_canary_effective`; `states` holds no
        managed key, so this cannot answer for one even if a later caller
        tried (DD-15).
        """

        normalized = (email or "").strip().lower()
        state = self.states[name]
        if state is FeatureFlagState.ON:
            return True
        if state is FeatureFlagState.INTERNAL:
            return bool(normalized) and normalized in self.internal_users
        return False

    def delivery_canary_effective(self, email: str | None) -> bool:
        """Effective `delivery_canary` value — this class's whole resolver API.

        There is deliberately no aggregate `effective_flags(email)` over
        `KNOWN_FEATURE_FLAGS` any more: it evaluated an environment baseline
        for the three flags SQLite owns, so its mere existence was a second
        answer waiting for a call site. The member-facing payload is assembled
        by `FeatureFlagService.effective_flags`, which combines this one value
        with the three SQLite rows (DD-15, 010-FR-003, 010-FR-008).
        """

        return self._is_effective("delivery_canary", email)


class AdminSettings(BaseModel):
    """Server-owned allow-list of operators for the `/admin` portal (009-FR-001).

    Deliberately separate from `FeatureFlagSettings.internal_users`: that list
    gates feature *exposure* for a rollout cohort, this one gates a real
    authorization decision (account lookup, session revoke). Reusing one list
    for both would let a feature-flag test cohort silently gain admin power.
    """

    operator_emails: frozenset[str] = Field(
        default_factory=frozenset,
        description="Normalized emails authorized to use the admin portal.",
    )

    model_config = ConfigDict(frozen=True)

    @field_validator("operator_emails")
    @classmethod
    def validate_operator_emails(cls, emails: frozenset[str]) -> frozenset[str]:
        normalized: set[str] = set()
        for email in emails:
            candidate = email.strip().lower()
            if not candidate or "@" not in candidate:
                raise ValueError(
                    f"Admin operator email '{email}' is not an email address."
                )
            normalized.add(candidate)
        return frozenset(normalized)


class LoggingSettings(BaseModel):
    """Logging configuration values."""

    level: str = Field(default="INFO", description="Root log level")

    model_config = ConfigDict(frozen=True)

    @property
    def normalized_level(self) -> str:
        """Upper-case log level for logging APIs."""
        return self.level.upper()


class SessionSettings(BaseModel):
    """Cookie-based session configuration."""

    cookie_name: str = Field(
        default="brainbuddy_session", description="Cookie name carrying the session."
    )
    max_age_seconds: int = Field(
        default=30 * 24 * 60 * 60,
        description="How long a session cookie lives, in seconds.",
    )
    secure: bool = Field(
        default=False,
        description=(
            "Whether the session cookie is marked Secure (HTTPS only). "
            "Enabled automatically in production."
        ),
    )

    model_config = ConfigDict(frozen=True)


class PasswordPolicy(BaseModel):
    """Bounds for accepted user passwords."""

    min_length: int = Field(default=12, ge=1)
    max_length: int = Field(default=128, ge=1)

    model_config = ConfigDict(frozen=True)


class DataSettings(BaseModel):
    """Filesystem layout for the application."""

    root_dir: Path = Field(default=DEFAULT_DATA_DIR)
    schema_version: str = Field(default=DEFAULT_SCHEMA_VERSION)

    model_config = ConfigDict(frozen=True)

    @property
    def schema_version_path(self) -> Path:
        """Return the schema version file path."""
        return self.root_dir / SCHEMA_VERSION_FILENAME


class VoiceProviderSettings(BaseModel):
    """Bounded configuration for one voice-processing provider role."""

    provider: str = "disabled"
    model: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: tuple[float, ...] = (1.0, 2.0)
    max_cost_usd_per_operation: float = Field(default=0.50, gt=0, le=100)
    estimated_cost_usd_per_megabyte: float = Field(default=0.01, gt=0, le=10)
    endpoint: str = ""

    model_config = ConfigDict(frozen=True)

    @field_validator("retry_backoff_seconds")
    @classmethod
    def validate_retry_backoff_seconds(
        cls, values: tuple[float, ...]
    ) -> tuple[float, ...]:
        if not values or len(values) > 5:
            raise ValueError("retry backoff must contain between one and five delays")
        if any(
            not math.isfinite(value) or value < 0 or value > 300 for value in values
        ):
            raise ValueError(
                "retry backoff delays must be finite values from 0 to 300 seconds"
            )
        return values


class VoiceRetentionSettings(BaseModel):
    raw_audio_seconds: int = Field(default=86_400, ge=0)
    working_artifacts_seconds: int = Field(default=604_800, ge=0)

    model_config = ConfigDict(frozen=True)


class VoiceAudioLimits(BaseModel):
    """Configuration-backed bounds enforced before any audio byte persists."""

    allowed_mime_types: frozenset[str] = Field(
        default_factory=lambda: frozenset(
            {
                "audio/wav",
                "audio/wave",
                "audio/x-wav",
                "audio/ogg",
                "audio/webm",
                "audio/mp4",
                "audio/aac",
            }
        )
    )
    max_chunk_bytes: int = Field(default=10_485_760, ge=1, le=104_857_600)
    max_total_bytes: int = Field(default=104_857_600, ge=1, le=1_073_741_824)
    max_chunk_count: int = Field(default=1024, ge=1, le=10_000)
    max_duration_seconds: float = Field(default=1800.0, gt=0, le=10_800)
    assumed_chunk_duration_seconds: float = Field(default=5.0, gt=0, le=600)

    model_config = ConfigDict(frozen=True)


class VoiceSettings(BaseModel):
    accurate_stt: VoiceProviderSettings = Field(default_factory=VoiceProviderSettings)
    fast_stt: VoiceProviderSettings = Field(default_factory=VoiceProviderSettings)
    reconciler: VoiceProviderSettings = Field(default_factory=VoiceProviderSettings)
    retention: VoiceRetentionSettings = Field(default_factory=VoiceRetentionSettings)
    audio_limits: VoiceAudioLimits = Field(default_factory=VoiceAudioLimits)
    max_operation_recoveries: int = Field(default=2, ge=0, le=5)
    max_cumulative_cost_usd_per_operation: float = Field(default=1.00, gt=0, le=200)
    lease_recovery_margin_seconds: float = Field(default=30.0, ge=0, le=600)


AGENT_EVENTS_PATH = "/agent-events"
"""The relay endpoint path below the application's configured API prefix."""


def _canonical_public_base_url(raw: str, *, environment: AppEnvironment) -> str:
    """Normalise the callback origin, or refuse to build a configuration.

    This value is baked into every hand-off manifest and travels into a
    third-party system BrainBuddy does not control, so a wrong one is not
    recoverable by a later fix: agents already told to report somewhere else
    simply never arrive. Structural nonsense (credentials, a query, a fragment,
    an unsupported scheme, junk) is refused in every environment, and production
    additionally requires a canonical public HTTPS origin. Development keeps
    localhost so the stack still runs on a laptop.
    """

    candidate = raw.strip()
    reject = f"Invalid external-agent relay public base URL: {environment.value} "

    if not candidate:
        raise ValueError(reject + "requires a non-empty public base URL.")
    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise ValueError(reject + "could not parse the public base URL.") from exc

    if parts.scheme not in {"http", "https"} or not host:
        raise ValueError(reject + "needs an http(s) public base URL with a host.")
    if parts.username or parts.password:
        raise ValueError(reject + "forbids credentials in the public base URL.")
    if parts.query or parts.fragment:
        raise ValueError(reject + "forbids a query or fragment in the public base URL.")
    if parts.path not in {"", "/"}:
        raise ValueError(
            reject + "needs a bare origin as the public base URL, with no path."
        )

    host = host.lower()
    if environment is AppEnvironment.PRODUCTION:
        if parts.scheme != "https":
            raise ValueError(reject + "requires an https public base URL.")
        if not public_callback_host_is_reachable(host):
            raise ValueError(
                reject
                + "requires a public base URL host that resolves to publicly "
                + "routable addresses only."
            )

    netloc = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{netloc}" + (f":{port}" if port is not None else "")


CANONICAL_PUBLIC_CALLBACK_HOSTS: frozenset[str] = frozenset(
    {"brain-buddy-backend.fly.dev"}
)
"""The deployment's own callback host, admitted without a lookup.

Deliberately one exact hostname, matched whole and never as a suffix. It is the
value `fly.backend.toml` sets, so it is already governed by review; resolving it
at start-up would only make the deploy depend on DNS being answerable from
wherever the process happens to boot, including CI.
"""

_SPECIAL_USE_CALLBACK_SUFFIXES: tuple[str, ...] = (
    # RFC 6761/8375 special-use names, plus the conventional private-network
    # suffixes. None of them mean anything outside one network, and a
    # split-horizon resolver can answer for them with a public-looking address,
    # so they are refused on the name and never resolved.
    ".localhost",
    ".local",
    ".invalid",
    ".test",
    ".example",
    ".internal",
    ".intranet",
    ".lan",
    ".private",
    ".corp",
    ".home",
    ".home.arpa",
)

_SPECIAL_USE_CALLBACK_NAMES: frozenset[str] = frozenset(
    {"localhost", "local", "invalid", "test", "example", "internal", "corp", "lan"}
)


def _resolve_callback_host(host: str) -> list[str]:
    """Every address this name currently answers with. Raises on failure."""

    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def public_callback_host_is_reachable(
    host: str, *, resolver: Callable[[str], list[str]] | None = None
) -> bool:
    """Whether an agent on the public internet could reach ``host`` at all.

    Fail-closed by construction. A hostname is admitted only when it resolves
    *and* every answer is globally routable — one private answer among public
    ones is a split-horizon name, and treating it as public would send hand-off
    reports to whatever lives at that private address. An unresolvable name is
    refused outright: production start-up is the last point at which a typo is
    cheap, and every run dispatched afterwards would report into nothing.

    ``resolver`` is injected by tests so the decision can be exercised without a
    live lookup; nothing else passes it.
    """

    if host in CANONICAL_PUBLIC_CALLBACK_HOSTS:
        return True

    literal = _normalize_callback_address(host)
    if literal is not None:
        return _is_globally_routable(literal)

    if host in _SPECIAL_USE_CALLBACK_NAMES or host.endswith(
        _SPECIAL_USE_CALLBACK_SUFFIXES
    ):
        return False
    if "." not in host:
        # A single label is a name only this network can resolve.
        return False

    resolve = resolver if resolver is not None else _resolve_callback_host
    try:
        addresses = resolve(host)
    except OSError:
        return False
    if not addresses:
        return False
    return all(
        (parsed := _normalize_callback_address(address)) is not None
        and _is_globally_routable(parsed)
        for address in addresses
    )


def _normalize_callback_address(
    value: str,
) -> IPv4Address | IPv6Address | None:
    """Parse an address, unwrapping IPv4-mapped IPv6 so it cannot hide a class."""

    try:
        parsed = ip_address(value.split("%", 1)[0])
    except ValueError:
        return None
    if isinstance(parsed, IPv6Address) and parsed.ipv4_mapped is not None:
        return parsed.ipv4_mapped
    return parsed


def _is_globally_routable(address: IPv4Address | IPv6Address) -> bool:
    """``is_global`` alone misses IPv4 multicast, so each class is named."""

    return (
        address.is_global
        and not address.is_multicast
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_private
        and not address.is_reserved
        and not address.is_unspecified
    )


class AgentRelaySettings(BaseModel):
    """Deployment policy for the external-agent relay.

    ``allow_private_destinations`` is the single governed opt-in from FR-004: it
    admits loopback/private network classes *and* plaintext HTTP, so it exists
    for local development and for an operator deliberately pointing BrainBuddy
    at a connector inside their own network. It must stay off in production.
    """

    public_base_url: str = Field(
        default="http://localhost:8000",
        description="Public origin agents call back to with signed run events.",
    )
    stale_after_seconds: int = Field(default=7 * 24 * 60 * 60, ge=60)
    reporting_window_seconds: int = Field(default=60 * 60, ge=60)
    content_retention_seconds: int = Field(
        default=30 * 24 * 60 * 60, ge=60, le=30 * 24 * 60 * 60
    )
    retention_sweep_interval_seconds: float = Field(default=60.0, ge=1, le=3_600)
    connector_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    connector_max_response_bytes: int = Field(default=64_000, ge=1_024, le=1_048_576)
    allow_private_destinations: bool = Field(default=False)

    model_config = ConfigDict(frozen=True)


class AppConfig(BaseModel):
    """Top-level Brain Buddy application configuration."""

    environment: AppEnvironment = Field(default=AppEnvironment.DEVELOPMENT)
    api_prefix: str = Field(default="/api")
    data: DataSettings = Field(default_factory=DataSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    password_policy: PasswordPolicy = Field(default_factory=PasswordPolicy)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    agent_relay: AgentRelaySettings = Field(default_factory=AgentRelaySettings)
    feature_flags: FeatureFlagSettings = Field(default_factory=FeatureFlagSettings)
    admin: AdminSettings = Field(default_factory=AdminSettings)

    model_config = ConfigDict(frozen=True)

    @property
    def data_dir(self) -> Path:
        return self.data.root_dir

    @property
    def log_level(self) -> str:
        return self.logging.normalized_level

    @property
    def agent_relay_callback_url(self) -> str:
        """Build the callback from the same prefix mounted by FastAPI."""

        return (
            f"{self.agent_relay.public_base_url.rstrip('/')}"
            f"{self.api_prefix.rstrip('/')}{AGENT_EVENTS_PATH}"
        )


def _parse_feature_flag_entry(entry: str) -> tuple[str, FeatureFlagState]:
    """Parse one ``flag_name=state`` pair, failing closed on any oddity."""

    name, separator, state_value = entry.partition("=")
    name = name.strip()
    state_value = state_value.strip().lower()
    if not separator or not name or not state_value:
        raise ValueError(
            f"Feature flag entry '{entry}' must look like 'flag_name=state'."
        )
    try:
        return name, FeatureFlagState(state_value)
    except ValueError as exc:
        raise ValueError(
            f"Feature flag '{name}' has invalid state '{state_value}'; "
            "expected one of off, internal, on."
        ) from exc


def _parse_feature_flag_states(raw: str) -> dict[str, FeatureFlagState]:
    """Parse ``name=state,name=state`` pairs, failing closed on any oddity."""

    states: dict[str, FeatureFlagState] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, state = _parse_feature_flag_entry(entry)
        if name in states:
            raise ValueError(f"Feature flag '{name}' is configured more than once.")
        states[name] = state
    return states


def _parse_environment_owned_states(raw: str) -> dict[str, FeatureFlagState]:
    """Parse only the entries this configuration still owns at runtime.

    An entry naming anything other than an `ENVIRONMENT_OWNED_FLAGS` member —
    a managed flag, an unknown name, or an anonymous ``=on`` — is skipped
    here, not accepted: it is migration input, validated by
    `FeatureFlagSettings.load_managed_migration_seed` at the one moment it can
    still matter (DD-15). Skipping it is what lets an already-migrated
    deployment boot with a stale or malformed managed entry still staged, and
    `delivery_canary` is still parsed with the full pre-correction strictness
    so a malformed release-smoke input fails startup exactly as before.
    """

    states: dict[str, FeatureFlagState] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry.partition("=")[0].strip() not in ENVIRONMENT_OWNED_FLAGS:
            continue
        name, state = _parse_feature_flag_entry(entry)
        if name in states:
            raise ValueError(f"Feature flag '{name}' is configured more than once.")
        states[name] = state
    return states


def _split_env_list(raw: str) -> frozenset[str]:
    return frozenset(value.strip() for value in raw.split(",") if value.strip())


def _build_feature_flags() -> FeatureFlagSettings:
    raw_states = os.getenv("BRAIN_BUDDY_FEATURE_FLAGS", "")
    raw_internal_users = os.getenv("BRAIN_BUDDY_FEATURE_FLAG_INTERNAL_USERS", "")
    states = _parse_environment_owned_states(raw_states)
    # The cohort list is migration input too, with one exception: it is a real
    # runtime input while `delivery_canary=internal` resolves against it, and
    # is then validated at startup exactly as before (DD-15).
    internal_users = (
        _split_env_list(raw_internal_users)
        if states.get("delivery_canary") is FeatureFlagState.INTERNAL
        else frozenset()
    )
    return FeatureFlagSettings(
        states=states,
        internal_users=internal_users,
        migration_input=ManagedFlagMigrationInput(
            raw_states=raw_states,
            raw_internal_users=raw_internal_users,
        ),
    )


def _build_admin_settings() -> AdminSettings:
    operator_emails = frozenset(
        value.strip()
        for value in os.getenv("BRAIN_BUDDY_ADMIN_OPERATOR_EMAILS", "").split(",")
        if value.strip()
    )
    return AdminSettings(operator_emails=operator_emails)


def _read_schema_version(data_dir: Path) -> str:
    schema_path = data_dir / SCHEMA_VERSION_FILENAME
    if schema_path.exists():
        return schema_path.read_text(encoding="utf-8").strip() or DEFAULT_SCHEMA_VERSION
    return DEFAULT_SCHEMA_VERSION


def _build_config() -> AppConfig:
    env_value = os.getenv("BRAIN_BUDDY_ENV", AppEnvironment.DEVELOPMENT.value)
    api_prefix = os.getenv("BRAIN_BUDDY_API_PREFIX", "/api")
    log_level = os.getenv("BRAIN_BUDDY_LOG_LEVEL", "INFO")
    data_dir_value = os.getenv("BRAIN_BUDDY_DATA_DIR", str(DEFAULT_DATA_DIR))

    data_dir = Path(data_dir_value).expanduser().resolve()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback_dir = DEFAULT_DATA_DIR.resolve()
        fallback_dir.mkdir(parents=True, exist_ok=True)
        logging.getLogger(__name__).warning(
            "Data dir %s is not writable; falling back to %s", data_dir, fallback_dir
        )
        data_dir = fallback_dir

    schema_version = _read_schema_version(data_dir)

    try:
        environment = AppEnvironment(env_value)
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"Unsupported environment '{env_value}'.") from exc

    logging_config = LoggingSettings(level=log_level)
    data_config = DataSettings(root_dir=data_dir, schema_version=schema_version)
    session_config = SessionSettings(
        secure=environment is AppEnvironment.PRODUCTION,
    )
    password_policy = PasswordPolicy()
    accurate_provider = os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_PROVIDER")
    if not accurate_provider:
        accurate_provider = (
            "deterministic"
            if environment is AppEnvironment.TEST
            else "openai" if os.getenv("OPENAI_API_KEY") else "disabled"
        )
    if (
        environment is AppEnvironment.PRODUCTION
        and accurate_provider == "deterministic"
    ):
        raise ValueError("Production cannot use deterministic accurate STT.")

    retry_backoff = tuple(
        float(value.strip())
        for value in os.getenv(
            "BRAIN_BUDDY_VOICE_ACCURATE_STT_RETRY_BACKOFF_SECONDS", "1,2"
        ).split(",")
        if value.strip()
    )
    # Provider-specific defaults: Deepgram (multilingual STT) uses the nova-3
    # model and a DEEPGRAM_API_KEY credential; OpenAI keeps its transcribe
    # model and OPENAI_API_KEY. Either default is overridable via the explicit
    # env vars below.
    accurate_stt_is_deepgram = accurate_provider == "deepgram"
    default_accurate_model = (
        "nova-3" if accurate_stt_is_deepgram else "gpt-4o-mini-transcribe"
    )
    default_accurate_api_key_env = (
        "DEEPGRAM_API_KEY" if accurate_stt_is_deepgram else "OPENAI_API_KEY"
    )
    accurate_stt = VoiceProviderSettings(
        provider=accurate_provider,
        model=os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MODEL", default_accurate_model),
        api_key_env=os.getenv(
            "BRAIN_BUDDY_VOICE_ACCURATE_STT_API_KEY_ENV", default_accurate_api_key_env
        ),
        timeout_seconds=float(
            os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_TIMEOUT_SECONDS", "180")
        ),
        max_retries=int(os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_RETRIES", "2")),
        retry_backoff_seconds=retry_backoff,
        max_cost_usd_per_operation=float(
            os.getenv("BRAIN_BUDDY_VOICE_ACCURATE_STT_MAX_COST_USD", "0.50")
        ),
        estimated_cost_usd_per_megabyte=float(
            os.getenv(
                "BRAIN_BUDDY_VOICE_ACCURATE_STT_ESTIMATED_COST_USD_PER_MB", "0.01"
            )
        ),
    )
    reconciler_retry_backoff = tuple(
        float(value.strip())
        for value in os.getenv(
            "BRAIN_BUDDY_VOICE_RECONCILER_RETRY_BACKOFF_SECONDS", "1,2"
        ).split(",")
        if value.strip()
    )
    voice = VoiceSettings(
        accurate_stt=accurate_stt,
        fast_stt=VoiceProviderSettings(provider="disabled"),
        reconciler=VoiceProviderSettings(
            provider=os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_PROVIDER", "disabled"),
            model=os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_MODEL", "gpt-4o"),
            api_key_env=os.getenv(
                "BRAIN_BUDDY_VOICE_RECONCILER_API_KEY_ENV", "OPENAI_API_KEY"
            ),
            endpoint=os.getenv(
                "BRAIN_BUDDY_VOICE_RECONCILER_ENDPOINT",
                "https://api.openai.com/v1/chat/completions",
            ),
            timeout_seconds=float(
                os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_TIMEOUT_SECONDS", "30")
            ),
            max_retries=int(os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_RETRIES", "2")),
            retry_backoff_seconds=reconciler_retry_backoff,
            max_cost_usd_per_operation=float(
                os.getenv("BRAIN_BUDDY_VOICE_RECONCILER_MAX_COST_USD", "0.50")
            ),
            estimated_cost_usd_per_megabyte=float(
                os.getenv(
                    "BRAIN_BUDDY_VOICE_RECONCILER_ESTIMATED_COST_USD_PER_MB", "0.01"
                )
            ),
        ),
        retention=VoiceRetentionSettings(
            raw_audio_seconds=int(
                os.getenv("BRAIN_BUDDY_VOICE_RAW_AUDIO_RETENTION_SECONDS", "86400")
            ),
            working_artifacts_seconds=int(
                os.getenv(
                    "BRAIN_BUDDY_VOICE_WORKING_ARTIFACT_RETENTION_SECONDS", "604800"
                )
            ),
        ),
        audio_limits=VoiceAudioLimits(
            allowed_mime_types=frozenset(
                value.strip()
                for value in os.getenv(
                    "BRAIN_BUDDY_VOICE_AUDIO_ALLOWED_MIME_TYPES",
                    "audio/wav,audio/wave,audio/x-wav,audio/ogg,audio/webm,"
                    "audio/mp4,audio/aac"
                    + (
                        ",audio/x-brain-buddy-test-text"
                        if environment is AppEnvironment.TEST
                        else ""
                    ),
                ).split(",")
                if value.strip()
            ),
            max_chunk_bytes=int(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_BYTES", "10485760")
            ),
            max_total_bytes=int(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_TOTAL_BYTES", "104857600")
            ),
            max_chunk_count=int(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_CHUNK_COUNT", "1024")
            ),
            max_duration_seconds=float(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_MAX_DURATION_SECONDS", "1800")
            ),
            assumed_chunk_duration_seconds=float(
                os.getenv("BRAIN_BUDDY_VOICE_AUDIO_ASSUMED_CHUNK_DURATION_SECONDS", "5")
            ),
        ),
        max_operation_recoveries=int(
            os.getenv("BRAIN_BUDDY_VOICE_MAX_OPERATION_RECOVERIES", "2")
        ),
        max_cumulative_cost_usd_per_operation=float(
            os.getenv("BRAIN_BUDDY_VOICE_MAX_CUMULATIVE_COST_USD", "1.00")
        ),
        lease_recovery_margin_seconds=float(
            os.getenv("BRAIN_BUDDY_VOICE_LEASE_RECOVERY_MARGIN_SECONDS", "30")
        ),
    )

    agent_relay = AgentRelaySettings(
        public_base_url=_canonical_public_base_url(
            os.getenv("BRAIN_BUDDY_PUBLIC_BASE_URL", "http://localhost:8000"),
            environment=environment,
        ),
        stale_after_seconds=int(
            os.getenv("BRAIN_BUDDY_AGENT_STALE_AFTER_SECONDS", str(7 * 24 * 60 * 60))
        ),
        reporting_window_seconds=int(
            os.getenv("BRAIN_BUDDY_AGENT_REPORTING_WINDOW_SECONDS", str(60 * 60))
        ),
        content_retention_seconds=int(
            os.getenv(
                "BRAIN_BUDDY_AGENT_CONTENT_RETENTION_SECONDS", str(30 * 24 * 60 * 60)
            )
        ),
        retention_sweep_interval_seconds=float(
            os.getenv("BRAIN_BUDDY_AGENT_RETENTION_SWEEP_INTERVAL_SECONDS", "60")
        ),
        connector_timeout_seconds=float(
            os.getenv("BRAIN_BUDDY_AGENT_CONNECTOR_TIMEOUT_SECONDS", "10")
        ),
        connector_max_response_bytes=int(
            os.getenv("BRAIN_BUDDY_AGENT_CONNECTOR_MAX_RESPONSE_BYTES", "64000")
        ),
        # Fails closed: only the exact string "1" opts a deployment in, and
        # production is never allowed to, whatever the environment says.
        allow_private_destinations=(
            os.getenv("BRAIN_BUDDY_AGENT_ALLOW_PRIVATE_DESTINATIONS", "").strip() == "1"
            and environment is not AppEnvironment.PRODUCTION
        ),
    )

    return AppConfig(
        environment=environment,
        api_prefix=api_prefix,
        data=data_config,
        logging=logging_config,
        session=session_config,
        password_policy=password_policy,
        voice=voice,
        agent_relay=agent_relay,
        feature_flags=_build_feature_flags(),
        admin=_build_admin_settings(),
    )


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Return a cached configuration instance."""

    return _build_config()


__all__ = [
    "ALL_FEATURE_FLAGS",
    "CANONICAL_PUBLIC_CALLBACK_HOSTS",
    "ENVIRONMENT_OWNED_FLAGS",
    "KNOWN_FEATURE_FLAGS",
    "RUNTIME_MANAGED_FLAGS",
    "AdminSettings",
    "AgentRelaySettings",
    "AppConfig",
    "AppEnvironment",
    "FeatureFlagSettings",
    "FeatureFlagState",
    "ManagedFlagMigrationInput",
    "ManagedFlagMigrationSeed",
    "PasswordPolicy",
    "SessionSettings",
    "VoiceAudioLimits",
    "VoiceProviderSettings",
    "VoiceRetentionSettings",
    "VoiceSettings",
    "get_config",
    "public_callback_host_is_reachable",
]
