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
import re

from app.exceptions import NotFoundError
from app.repositories import SessionRepository, UserRepository
from app.schemas.auth import User

logger = logging.getLogger(__name__)

ACCOUNT_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
"""Every character an account id may contain.

`UserRepository` stores one JSON file per account and builds that path by
interpolating the id, so the admin routes — the only place a *client-supplied*
id reaches it, everywhere else the id comes from the session — must reject
anything outside this charset **before** any path is constructed. Without it
`../users/user_abc123` resolves to the same file as `user_abc123`, i.e. a
non-exact variant of a real id would match, which 009-FR-003 forbids and
PD-3's 404-for-unknown decision exists to prevent.
"""


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

    def _get_by_exact_id(self, account_id: str) -> User | None:
        """Fetch by id, matching the submitted key byte-for-byte or not at all.

        Two guards, both required by 009-FR-003:

        * the charset check runs **before** `get_by_id`, so a traversal or
          separator variant never reaches filesystem path construction;
        * the identity re-check after the fetch, because a case-insensitive
          filesystem would otherwise resolve `USER_ABC` to `user_abc`.
        """

        if not ACCOUNT_ID_PATTERN.fullmatch(account_id):
            return None
        user = self.user_repo.get_by_id(account_id)
        if user is None or user.id != account_id:
            return None
        return user

    def _get_by_exact_email(self, email: str) -> User | None:
        """Fetch by email, requiring the submitted key to be the canonical one.

        `UserRepository.get_by_email` normalizes (strips and lowercases)
        before the index read, so on its own a case or whitespace variant of a
        real address would match. 009-FR-003 requires those variants to return
        no match, so the stored canonical address must equal the submitted one
        exactly. A server-accepted address without a dotted domain
        (`admin@localhost`) is unaffected: it is canonical, so it matches.
        """

        user = self.user_repo.get_by_email(email)
        if user is None or user.email != email:
            return None
        return user

    def find_account(
        self, *, operator_id: str, account_id: str | None, email: str | None
    ) -> User | None:
        """Exact lookup by immutable account ID or canonical email.

        Exactly one of `account_id`/`email` is expected — the API layer
        enforces that shape before calling this.

        The record names the **resolved** account id (009-FR-008): the
        submitted key is raw request input and may itself be an email, so it
        can never be logged, and a lookup that logged only `found=<bool>`
        would be unattributable.
        """

        if account_id is not None:
            user = self._get_by_exact_id(account_id)
        else:
            assert email is not None
            user = self._get_by_exact_email(email)
        logger.info(
            "Admin lookup: operator=%s account=%s outcome=%s",
            operator_id,
            user.id if user is not None else "-",
            "found" if user is not None else "no_match",
        )
        return user

    def revoke_sessions(self, *, operator_id: str, account_id: str) -> int:
        """Revoke every current session for `account_id`. Idempotent.

        Requires the account to exist -- an unknown id raises `NotFoundError`
        rather than silently reporting a zero-count "success", which would
        make a typo indistinguishable from a real account with no active
        sessions.
        """

        target = self._get_by_exact_id(account_id)
        if target is None:
            raise NotFoundError("Account", account_id)
        revoked = self.session_repo.delete_all_for_user(target.id)
        logger.info(
            "Admin session revoke: operator=%s account=%s outcome=%s revoked=%s",
            operator_id,
            target.id,
            "revoked",
            revoked,
        )
        return revoked


__all__ = ["AdminService"]
