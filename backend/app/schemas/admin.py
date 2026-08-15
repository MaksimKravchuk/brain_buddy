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
    """The three runtime states one managed flag may hold (010-FR-003).

    Always present, never null: ADR-0019 (DD-3, DD-15) retired the
    inherited-baseline/"deploy default" split, so a managed flag's stored
    `mode` is the entire answer.
    """

    OFF = "off"
    ON = "on"
    SELECTED_USERS = "selected_users"


class AdminFeatureFlagSelectedUser(StrictBaseModel):
    """One cohort row. `email` is resolved live and never stored (DD-5)."""

    account_id: str = Field(description="Immutable account identifier.")
    email: str | None = Field(
        default=None,
        description="Canonical email, or null when the ID resolves to no account.",
    )


class AdminFeatureFlagState(StrictBaseModel):
    """One managed flag: its stored mode and its retained cohort."""

    name: str = Field(description="Managed feature-flag name.")
    mode: AdminFeatureFlagMode = Field(description="The flag's stored runtime mode.")
    selected_users: list[AdminFeatureFlagSelectedUser] = Field(
        default_factory=list,
        description="The retained cohort, shown even while the mode is off or on.",
    )


class AdminFeatureFlagsResponse(StrictBaseModel):
    """Every managed flag plus the runtime store's health (010-FR-004)."""

    degraded: bool = Field(
        description="True when the SQLite store exists but could not be read."
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
    "AdminFeatureFlagMode",
    "AdminFeatureFlagModeRequest",
    "AdminFeatureFlagSelectedUser",
    "AdminFeatureFlagSelectedUserRequest",
    "AdminFeatureFlagState",
    "AdminFeatureFlagsResponse",
    "AdminRevokeSessionsResponse",
    "AdminStatusResponse",
]
