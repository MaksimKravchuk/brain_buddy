"""Auth-related domain and API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from .common import StorageBaseModel, StrictBaseModel


class User(StorageBaseModel):
    """Stored representation of a user account."""

    id: str = Field(description="Unique user identifier.")
    email: str = Field(description="Normalized (lowercased) email address.")
    password_hash: str = Field(description="Argon2id hash of the user's password.")
    created_at: datetime = Field(description="UTC timestamp when the account was made.")


class Session(StorageBaseModel):
    """Stored representation of an authenticated session.

    The raw session token is never persisted — only a SHA-256 digest, so a
    disk leak can't be replayed back as a valid cookie.
    """

    token_hash: str = Field(
        description="Hex-encoded SHA-256 digest of the opaque session token."
    )
    user_id: str = Field(description="ID of the user the session belongs to.")
    created_at: datetime = Field(description="UTC timestamp when the session was made.")
    expires_at: datetime = Field(description="UTC timestamp when the session expires.")


class Invite(StorageBaseModel):
    """Stored representation of an invite code that unlocks signup."""

    code: str = Field(description="Opaque URL-safe invite code.")
    created_at: datetime = Field(description="UTC timestamp when the invite was made.")
    used_by_user_id: str | None = Field(
        default=None,
        description="User ID that consumed the invite, or null if unused.",
    )
    used_at: datetime | None = Field(
        default=None, description="Timestamp the invite was consumed, if any."
    )

    @property
    def is_used(self) -> bool:
        return self.used_by_user_id is not None


class SignupRequest(StrictBaseModel):
    """Request payload for `POST /auth/signup`."""

    email: EmailStr = Field(description="Email address for the new account.")
    password: str = Field(description="Password for the new account.")
    invite_code: str = Field(description="Invite code unlocking signup.")


class LoginRequest(StrictBaseModel):
    """Request payload for `POST /auth/login`."""

    email: EmailStr = Field(description="Email address of the account.")
    password: str = Field(description="Password of the account.")


class MeResponse(StrictBaseModel):
    """Response payload describing the currently authenticated user."""

    id: str = Field(description="User identifier.")
    email: str = Field(description="Normalized email address.")


class SessionCredentialResponse(StrictBaseModel):
    """One-time mobile transport for an existing server-owned Session."""

    session_token: str = Field(repr=False, description="Opaque session credential.")
    token_type: str = Field(default="Bearer", pattern="^Bearer$")
    expires_at: datetime
    user: MeResponse


__all__ = [
    "Invite",
    "LoginRequest",
    "MeResponse",
    "SessionCredentialResponse",
    "Session",
    "SignupRequest",
    "User",
]
