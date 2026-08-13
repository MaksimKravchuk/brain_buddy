"""Minimum admin portal: operator authorization, exact lookup, session revoke.

Reuses `UserRepository` reads and `SessionRepository.delete_all_for_user`
exactly as `AccountService` does for self-serve deletion — no new storage,
no new subsystem. Every method that touches an account logs through the
standard library logger, content-free: operator/account identifiers and an
outcome only, never email, display name, credentials, tokens, or session
hashes (009-FR-008).
"""

from __future__ import annotations

import logging

from app.exceptions import NotFoundError
from app.repositories import SessionRepository, UserRepository
from app.schemas.auth import User

logger = logging.getLogger(__name__)


class AdminService:
    """Operator allow-list check, exact account lookup, session revoke."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        operator_emails: frozenset[str],
    ) -> None:
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.operator_emails = operator_emails

    def is_operator(self, email: str) -> bool:
        """Whether `email` is on the server-owned operator allow-list."""

        normalized = self.user_repo.normalize_email(email)
        return normalized in self.operator_emails

    def find_account(
        self, *, operator_id: str, account_id: str | None, email: str | None
    ) -> User | None:
        """Exact lookup by immutable account ID or canonical email.

        Exactly one of `account_id`/`email` is expected — the API layer
        enforces that shape before calling this.
        """

        if account_id is not None:
            user = self.user_repo.get_by_id(account_id)
        else:
            assert email is not None
            user = self.user_repo.get_by_email(email)
        logger.info(
            "Admin lookup by operator %s: found=%s", operator_id, user is not None
        )
        return user

    def revoke_sessions(self, *, operator_id: str, account_id: str) -> int:
        """Revoke every current session for `account_id`. Idempotent.

        Requires the account to exist -- an unknown id raises `NotFoundError`
        rather than silently reporting a zero-count "success", which would
        make a typo indistinguishable from a real account with no active
        sessions.
        """

        if self.user_repo.get_by_id(account_id) is None:
            raise NotFoundError("Account", account_id)
        revoked = self.session_repo.delete_all_for_user(account_id)
        logger.info(
            "Admin session revoke by operator %s for account %s: revoked=%s",
            operator_id,
            account_id,
            revoked,
        )
        return revoked


__all__ = ["AdminService"]
