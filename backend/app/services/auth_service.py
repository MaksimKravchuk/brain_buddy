"""Authentication service: signup, login, logout, session lookup.

This module is the single place in the backend that touches passwords and
session tokens. All password hashing goes through Argon2id (via argon2-cffi).
Session tokens are opaque random strings; only their SHA-256 hash is ever
persisted.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import PasswordPolicy, SessionSettings
from app.exceptions import BrainBuddyError, ConflictError, ValidationFailure
from app.repositories import (
    InviteRepository,
    SessionRepository,
    UserRepository,
)
from app.schemas.auth import Session, User
from app.utils.time import utcnow

logger = logging.getLogger(__name__)

ACCOUNT_DELETION_GRACE = timedelta(days=14)
"""How long a requested account deletion stays cancellable before purge."""


class InvalidCredentialsError(BrainBuddyError):
    """Raised when a login attempt fails. Always uses the same message so
    we never leak whether the email exists."""

    def __init__(self) -> None:
        super().__init__("Invalid email or password.")


class InvalidInviteError(BrainBuddyError):
    """Raised when signup is attempted with a missing or used invite."""

    def __init__(self) -> None:
        super().__init__("Invite code is invalid or already used.")


class AuthService:
    """Coordinate user, session, and invite state."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        invite_repo: InviteRepository,
        password_policy: PasswordPolicy,
        session_settings: SessionSettings,
        deletion_grace: timedelta = ACCOUNT_DELETION_GRACE,
    ) -> None:
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.invite_repo = invite_repo
        self.password_policy = password_policy
        self.session_settings = session_settings
        self.deletion_grace = deletion_grace
        self._hasher = PasswordHasher()
        # Precomputed dummy hash used to equalize login timing in the
        # "no such user" branch — prevents timing-based account enumeration.
        self._dummy_hash = self._hasher.hash("dummy-password-for-timing-equalization")

    # ------------------------------------------------------------------
    # Password helpers
    # ------------------------------------------------------------------

    def hash_password(self, raw: str) -> str:
        return self._hasher.hash(raw)

    def verify_password(self, user: User, raw: str) -> bool:
        """Re-check a user's current password (sensitive-action re-auth)."""

        return self._verify_password(raw, user.password_hash)

    def validate_password_format(self, raw: str) -> None:
        """Enforce the password policy; raises `ValidationFailure` on breach."""

        self._validate_password_format(raw)

    def _verify_password(self, raw: str, hashed: str) -> bool:
        try:
            self._hasher.verify(hashed, raw)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False

    def _validate_password_format(self, raw: str) -> None:
        policy = self.password_policy
        if len(raw) < policy.min_length:
            raise ValidationFailure(
                f"Password must be at least {policy.min_length} characters."
            )
        if len(raw) > policy.max_length:
            raise ValidationFailure(
                f"Password must be at most {policy.max_length} characters."
            )

    # ------------------------------------------------------------------
    # Session helpers
    # ------------------------------------------------------------------

    @staticmethod
    def hash_session_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _create_session(self, user_id: str) -> tuple[str, Session]:
        raw_token = secrets.token_urlsafe(32)
        token_hash = self.hash_session_token(raw_token)
        now = utcnow()
        session = Session(
            token_hash=token_hash,
            user_id=user_id,
            created_at=now,
            expires_at=now + timedelta(seconds=self.session_settings.max_age_seconds),
        )
        self.session_repo.create(session)
        return raw_token, session

    def get_user_for_token(self, raw_token: str | None) -> User | None:
        if not raw_token:
            return None
        token_hash = self.hash_session_token(raw_token)
        session = self.session_repo.get(token_hash)
        if session is None:
            return None
        return self.user_repo.get_by_id(session.user_id)

    def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        token_hash = self.hash_session_token(raw_token)
        self.session_repo.delete(token_hash)

    # ------------------------------------------------------------------
    # Signup / login
    # ------------------------------------------------------------------

    def signup(
        self, *, email: str, password: str, invite_code: str
    ) -> tuple[User, str]:
        """Create a new user and return `(user, raw_session_token)`.

        Order of operations is important:
        1. Validate password format (cheap, no state change).
        2. Look up the invite and refuse immediately if missing/used.
        3. Create the user (this hashes the password — expensive).
        4. Mark the invite as consumed, re-checking it's still unused.
        5. Issue a session.

        If step 4 fails because someone raced us on the invite, the user
        account is still created but the invite rejects further use. That's
        acceptable — a leftover account with no way for someone else to
        sign up under the same invite is strictly safer than the reverse.
        """

        self._validate_password_format(password)

        normalized_email = self.user_repo.normalize_email(email)
        invite = self.invite_repo.get(invite_code)
        if invite is None or invite.is_used:
            raise InvalidInviteError()

        if self.user_repo.get_by_email(normalized_email) is not None:
            raise ConflictError("User", normalized_email)

        user_id = f"user_{uuid.uuid4().hex[:12]}"
        now = utcnow()
        user = User(
            id=user_id,
            email=normalized_email,
            password_hash=self.hash_password(password),
            created_at=now,
        )
        try:
            self.user_repo.create(user)
        except ConflictError:
            # Race: another request registered the same email between
            # our check and the write. Surface the same duplicate error.
            raise

        try:
            self.invite_repo.mark_used(invite_code, user_id=user_id, used_at=utcnow())
        except (ConflictError, BrainBuddyError) as exc:
            # Invite became unusable between our first check and now.
            # The user account has already been persisted; leave it and
            # raise so the caller gets a clear error.
            raise InvalidInviteError() from exc

        raw_token, _ = self._create_session(user_id)
        return user, raw_token

    def login(self, *, email: str, password: str) -> tuple[User, str, bool]:
        """Authenticate and return `(user, raw_session_token, deletion_cancelled)`.

        Always raises `InvalidCredentialsError` on failure — the caller
        maps that to a generic "Invalid email or password." response so
        we never leak whether the email exists.

        A pending account deletion still inside its grace period is
        cancelled by a successful login (`deletion_cancelled=True`). A
        deletion already past its grace period refuses the login with the
        same generic error, before any session is created: the account is
        past the point of no return and must never be resurrected mid-purge.
        """

        normalized_email = self.user_repo.normalize_email(email)
        user = self.user_repo.get_by_email(normalized_email)
        if user is None:
            # Run a dummy verify to equalize timing against the
            # "user exists but password is wrong" branch below.
            self._verify_password(password, self._dummy_hash)
            raise InvalidCredentialsError()

        if not self._verify_password(password, user.password_hash):
            raise InvalidCredentialsError()

        deletion_cancelled = False
        if user.deletion_requested_at is not None:
            if utcnow() >= user.deletion_requested_at + self.deletion_grace:
                raise InvalidCredentialsError()
            user = user.model_copy(update={"deletion_requested_at": None})
            self.user_repo.save(user)
            deletion_cancelled = True
            logger.info("Login cancelled pending deletion for %s", user.id)

        raw_token, _ = self._create_session(user.id)
        return user, raw_token, deletion_cancelled

    # ------------------------------------------------------------------
    # Admin seeding
    # ------------------------------------------------------------------

    def seed_admin(self, *, email: str, password: str) -> User:
        """Create or update a pre-seeded admin account.

        Driven by ``BRAIN_BUDDY_ADMIN_EMAIL`` and ``BRAIN_BUDDY_ADMIN_PASSWORD``
        in production. The environment is the source of truth: if the user
        already exists and the password in the environment differs from the
        stored hash, the stored hash is rotated. This makes it possible to
        rotate the admin password by updating the Fly secret and redeploying.

        Password policy is enforced — if the seeded password is too short or
        too long, we raise at startup rather than silently skipping. That way
        a misconfigured deploy fails loudly instead of leaving the admin
        account unseeded.

        Bypasses the invite flow entirely: the admin account is created
        directly without consuming an invite.
        """

        self._validate_password_format(password)
        normalized = self.user_repo.normalize_email(email)
        existing = self.user_repo.get_by_email(normalized)

        if existing is None:
            user_id = f"user_{uuid.uuid4().hex[:12]}"
            user = User(
                id=user_id,
                email=normalized,
                password_hash=self.hash_password(password),
                created_at=utcnow(),
            )
            created = self.user_repo.create(user)
            logger.info("Seeded admin account %s", normalized)
            return created

        if not self._verify_password(password, existing.password_hash):
            updated = existing.model_copy(
                update={"password_hash": self.hash_password(password)}
            )
            self.user_repo.save(updated)
            logger.info("Rotated admin password for %s", normalized)
            return updated

        logger.debug("Admin account %s already up to date", normalized)
        return existing


__all__ = [
    "ACCOUNT_DELETION_GRACE",
    "AuthService",
    "InvalidCredentialsError",
    "InvalidInviteError",
]
