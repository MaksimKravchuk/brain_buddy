"""Self-serve account management: profile, credentials, and GDPR data rights.

Password hashing and verification stay inside `AuthService` — this service
only orchestrates re-auth checks, repository writes, and session revocation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.exceptions import ConflictError, ReauthFailedError, ValidationFailure
from app.repositories import SessionRepository, UserRepository
from app.schemas.auth import User
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

DELETION_GRACE = timedelta(days=14)

# The one message every failed email change returns. A conflicting address
# must be indistinguishable from any other rejection, or the endpoint becomes
# an account-enumeration oracle.
_EMAIL_REJECTED_MESSAGE = "That email address can't be used."


class AccountService:
    """Coordinate account reads and mutations for the authenticated owner."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        auth_service: AuthService,
        deletion_grace: timedelta = DELETION_GRACE,
    ) -> None:
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.auth_service = auth_service
        self.deletion_grace = deletion_grace

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_current_password(self, user: User, raw: str) -> None:
        if not self.auth_service.verify_password(user, raw):
            raise ReauthFailedError()

    def purge_at_for(self, user: User) -> datetime | None:
        if user.deletion_requested_at is None:
            return None
        return user.deletion_requested_at + self.deletion_grace

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_account(self, user: User) -> User:
        """Return a fresh read of the caller's account record."""

        fresh = self.user_repo.get_by_id(user.id)
        return fresh if fresh is not None else user

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def update_profile(self, user: User, *, display_name: str) -> User:
        """Set (or clear, via empty string) the display name."""

        cleaned = display_name.strip()
        updated = user.model_copy(update={"display_name": cleaned or None})
        self.user_repo.save(updated)
        return updated

    def change_email(
        self, user: User, *, new_email: str, current_password: str
    ) -> User:
        """Move the account to a new address after re-checking the password.

        A conflict with another account is collapsed into the same generic
        `ValidationFailure` as any other rejection (see module note).
        """

        self._require_current_password(user, current_password)
        try:
            return self.user_repo.update_email(user.id, new_email)
        except ConflictError as exc:
            raise ValidationFailure(_EMAIL_REJECTED_MESSAGE) from exc

    def change_password(
        self,
        user: User,
        *,
        current_password: str,
        new_password: str,
        keep_token_hash: str | None,
    ) -> None:
        """Rotate the password and revoke every other session.

        The caller's own session (`keep_token_hash`) survives so the change
        doesn't log the user out of the device they made it from.
        """

        self._require_current_password(user, current_password)
        self.auth_service.validate_password_format(new_password)
        updated = user.model_copy(
            update={"password_hash": self.auth_service.hash_password(new_password)}
        )
        self.user_repo.save(updated)
        revoked = self.session_repo.delete_all_for_user(user.id, keep=keep_token_hash)
        logger.info(
            "Password changed for %s; revoked %s other session(s)", user.id, revoked
        )


__all__ = ["AccountService", "DELETION_GRACE"]
