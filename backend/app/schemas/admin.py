"""Admin-portal request/response schemas (009-FR-003, 009-FR-004)."""

from __future__ import annotations

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


__all__ = [
    "AdminAccountLookupRequest",
    "AdminAccountResponse",
    "AdminRevokeSessionsResponse",
]
