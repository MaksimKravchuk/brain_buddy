"""API schemas for self-serve account management (GDPR data rights)."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from .common import StrictBaseModel

DISPLAY_NAME_MAX_LENGTH = 64


class AccountResponse(StrictBaseModel):
    """Response payload describing the caller's account."""

    id: str = Field(description="User identifier.")
    email: str = Field(description="Normalized email address.")
    display_name: str | None = Field(
        default=None, description="Optional display name chosen by the user."
    )
    created_at: datetime = Field(description="UTC timestamp when the account was made.")
    deletion_requested_at: datetime | None = Field(
        default=None,
        description="When account deletion was requested, or null if not pending.",
    )
    purge_at: datetime | None = Field(
        default=None,
        description=(
            "When the account and all its data will be permanently erased, "
            "or null if no deletion is pending."
        ),
    )


class ProfileUpdateRequest(StrictBaseModel):
    """Request payload for `PATCH /account/profile`."""

    display_name: str = Field(
        description=(
            "New display name. Whitespace is stripped; an empty result clears "
            "the display name."
        ),
        max_length=DISPLAY_NAME_MAX_LENGTH,
    )


class EmailChangeRequest(StrictBaseModel):
    """Request payload for `POST /account/email`."""

    new_email: EmailStr = Field(description="The address to move the account to.")
    current_password: str = Field(description="Current password, re-checked.")


class PasswordChangeRequest(StrictBaseModel):
    """Request payload for `POST /account/password`."""

    current_password: str = Field(description="Current password, re-checked.")
    new_password: str = Field(description="New password; policy enforced.")


class AccountDeleteRequest(StrictBaseModel):
    """Request payload for `POST /account/delete`."""

    current_password: str = Field(description="Current password, re-checked.")


class AccountDeleteResponse(StrictBaseModel):
    """Response payload after scheduling account deletion."""

    deletion_requested_at: datetime = Field(
        description="When the deletion was requested."
    )
    purge_at: datetime = Field(
        description="When the account and all its data will be permanently erased."
    )


__all__ = [
    "AccountDeleteRequest",
    "AccountDeleteResponse",
    "AccountResponse",
    "DISPLAY_NAME_MAX_LENGTH",
    "EmailChangeRequest",
    "PasswordChangeRequest",
    "ProfileUpdateRequest",
]
