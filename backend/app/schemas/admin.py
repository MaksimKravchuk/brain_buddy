"""Admin-portal request/response schemas (009-FR-003, 009-FR-004, 010-FR-010)."""

from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from .common import StrictBaseModel


class AdminAccountLookupRequest(StrictBaseModel):
    """Exactly one of `account_id` or `email` must be given (009-FR-003)."""

    account_id: str | None = Field(
        default=None, min_length=1, description="Immutable account identifier."
    )
    email: str | None = Field(
        default=None, min_length=1, description="Canonical email address."
    )

    @model_validator(mode="after")
    def _exactly_one_lookup_key(self) -> AdminAccountLookupRequest:
        if (self.account_id is None) == (self.email is None):
            raise ValueError("Provide exactly one of account_id or email.")
        return self


class AdminAccountResponse(StrictBaseModel):
    """The only fields an operator may see (009-FR-004)."""

    id: str = Field(description="Account identifier.")
    email: str = Field(description="Canonical (normalized) email address.")
    display_name: str | None = Field(default=None, description="Optional display name.")
    deletion_requested: bool = Field(
        description="Whether the account has a pending deletion request."
    )


class AdminRevokeSessionsResponse(StrictBaseModel):
    """Result of a session-revoke mutation; zero is success (009-FR-007)."""

    revoked_count: int = Field(ge=0, description="Number of sessions revoked.")


class AdminStatusResponse(StrictBaseModel):
    """Server-issued operator capability check (009-FR-002).

    Only ever reachable after `require_operator` succeeds, so `is_operator`
    is always `true`; a caller who is not an operator gets 401/403 instead
    of a response body. Separate from the shared signup/login/me payload,
    which stays byte-shape compatible with no admin field.
    """

    is_operator: bool = Field(description="Always true when this response is returned.")


class AdminFeatureFlagMode(str, Enum):
    """The three runtime-override states one managed flag may hold (010-FR-003)."""

    OFF = "off"
    ON = "on"
    SELECTED_USERS = "selected_users"


class AdminFeatureFlagDeployState(str, Enum):
    """The environment baseline's own vocabulary — never a mode (DD-3).

    Deliberately a separate type from :class:`AdminFeatureFlagMode`: `internal`
    is a deploy stage with no runtime-override equivalent, and collapsing the
    two would force the screen to render an inherited `internal` baseline as one
    of the three override radios, which DD-3 forbids.
    """

    OFF = "off"
    INTERNAL = "internal"
    ON = "on"


class AdminFeatureFlagSource(str, Enum):
    """Whether a flag's current answer comes from the overlay or the baseline."""

    RUNTIME = "runtime"
    DEPLOY_DEFAULT = "deploy_default"


class AdminFeatureFlagSelectedUser(StrictBaseModel):
    """One cohort row. `email` is resolved live and never stored (DD-5)."""

    account_id: str = Field(description="Immutable account identifier.")
    email: str | None = Field(
        default=None,
        description="Canonical email, or null when the ID resolves to no account.",
    )


class AdminFeatureFlagState(StrictBaseModel):
    """One managed flag, as DD-3's three independent fields."""

    name: str = Field(description="Managed feature-flag name.")
    override_mode: AdminFeatureFlagMode | None = Field(
        description="The runtime override's mode, or null while inheriting."
    )
    source: AdminFeatureFlagSource = Field(
        description="Where the current answer comes from."
    )
    deploy_default_state: AdminFeatureFlagDeployState = Field(
        description="The environment baseline, always present even under an override."
    )
    selected_users: list[AdminFeatureFlagSelectedUser] = Field(
        default_factory=list,
        description="The retained cohort, shown even while the mode is off or on.",
    )


class AdminFeatureFlagsResponse(StrictBaseModel):
    """Every managed flag plus the runtime store's health (010-FR-004)."""

    degraded: bool = Field(
        description="True when the runtime document exists but could not be read."
    )
    flags: list[AdminFeatureFlagState] = Field(
        description="Exactly the runtime-manageable flags, in a stable order."
    )


class AdminFeatureFlagModeRequest(StrictBaseModel):
    """Set one managed flag's runtime mode."""

    mode: AdminFeatureFlagMode = Field(description="The mode to store.")


class AdminFeatureFlagSelectedUserRequest(StrictBaseModel):
    """Exactly one of `account_id` or `email`, mirroring the 009 lookup shape."""

    account_id: str | None = Field(
        default=None, min_length=1, description="Immutable account identifier."
    )
    email: str | None = Field(
        default=None, min_length=1, description="Canonical email address."
    )

    @model_validator(mode="after")
    def _exactly_one_lookup_key(self) -> AdminFeatureFlagSelectedUserRequest:
        if (self.account_id is None) == (self.email is None):
            raise ValueError("Provide exactly one of account_id or email.")
        return self


__all__ = [
    "AdminAccountLookupRequest",
    "AdminAccountResponse",
    "AdminFeatureFlagDeployState",
    "AdminFeatureFlagMode",
    "AdminFeatureFlagModeRequest",
    "AdminFeatureFlagSelectedUser",
    "AdminFeatureFlagSelectedUserRequest",
    "AdminFeatureFlagSource",
    "AdminFeatureFlagState",
    "AdminFeatureFlagsResponse",
    "AdminRevokeSessionsResponse",
    "AdminStatusResponse",
]
