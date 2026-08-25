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
from typing import Any, cast

from app.exceptions import (
    AdminAuthorizationError,
    ConflictError,
    NotFoundError,
)
from app.repositories import SessionRepository, UserRepository
from app.schemas.auth import User

logger = logging.getLogger(__name__)

ACCOUNT_ID_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{1,128}\Z")
UNKNOWN_TARGET_ACCOUNT_ID = "unknown-target"
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
        auth_service: Any = None,
        account_service: Any = None,
    ) -> None:
        self.user_repo = user_repo
        self.session_repo = session_repo
        self.operator_emails = operator_emails
        self.auth_service = auth_service
        self.account_service = account_service

    def set_mutation_services(self, *, auth_service: Any, account_service: Any) -> None:
        self.auth_service = auth_service
        self.account_service = account_service

    def list_accounts(self, *, operator_id: str) -> list[User]:
        try:
            accounts = sorted(
                self.user_repo.list_users(), key=lambda user: (user.email, user.id)
            )
        except Exception:
            self._audit(operator_id, "list", "-", "error")
            raise
        self._audit(operator_id, "list", "-", "success")
        return accounts

    def create_account(
        self,
        *,
        operator_id: str,
        email: str,
        password: str,
        display_name: str | None,
    ) -> User:
        if self.auth_service is None:
            self._audit(operator_id, "create", "-", "error")
            raise RuntimeError("Admin account creation is not configured")
        try:
            user = self.auth_service.create_admin_user(
                email=email, password=password, display_name=display_name
            )
        except ConflictError:
            self._audit(operator_id, "create", "-", "conflict")
            raise ConflictError("User", "account") from None
        except Exception:
            self._audit(operator_id, "create", "-", "error")
            raise
        self._audit(operator_id, "create", user.id, "success")
        return cast(User, user)

    def update_account(
        self, *, operator_id: str, account_id: str, email: str, display_name: str | None
    ) -> User:
        try:
            target = self._get_by_exact_id(account_id)
        except Exception:
            self._audit(operator_id, "update", UNKNOWN_TARGET_ACCOUNT_ID, "error")
            raise
        if target is None:
            self._audit(operator_id, "update", UNKNOWN_TARGET_ACCOUNT_ID, "not_found")
            raise NotFoundError("Account", account_id)
        normalized = self.user_repo.normalize_email(email)
        if normalized != target.email and (
            target.email in self.operator_emails
            or (target.id == operator_id and normalized not in self.operator_emails)
        ):
            self._audit(operator_id, "update", target.id, "forbidden")
            raise AdminAuthorizationError("Account update is not allowed.")
        if normalized != target.email and normalized in self.operator_emails:
            self._audit(operator_id, "update", target.id, "conflict")
            raise ConflictError("User", "account")
        try:
            updated = self.user_repo.update_profile(
                target.id,
                email=normalized,
                display_name=display_name.strip() or None if display_name else None,
            )
        except ConflictError:
            self._audit(operator_id, "update", target.id, "conflict")
            raise ConflictError("User", "account") from None
        except Exception:
            self._audit(operator_id, "update", target.id, "error")
            raise
        self._audit(operator_id, "update", target.id, "success")
        return updated

    def delete_account(self, *, operator_id: str, account_id: str) -> None:
        try:
            target = self._get_by_exact_id(account_id)
        except Exception:
            self._audit(operator_id, "delete", UNKNOWN_TARGET_ACCOUNT_ID, "error")
            raise
        if target is None:
            self._audit(operator_id, "delete", UNKNOWN_TARGET_ACCOUNT_ID, "not_found")
            raise NotFoundError("Account", account_id)
        if target.id == operator_id or target.email in self.operator_emails:
            self._audit(operator_id, "delete", target.id, "forbidden")
            raise AdminAuthorizationError("Account deletion is not allowed.")
        if self.account_service is None:
            self._audit(operator_id, "delete", target.id, "error")
            raise RuntimeError("Admin account deletion is not configured")
        try:
            self.account_service.purge_account(target.id)
        except Exception:
            self._audit(operator_id, "delete", target.id, "error")
            raise
        self._audit(operator_id, "delete", target.id, "success")

    def _audit(
        self, operator_id: str, operation: str, account_id: str, outcome: str
    ) -> None:
        if account_id == UNKNOWN_TARGET_ACCOUNT_ID or not ACCOUNT_ID_PATTERN.fullmatch(
            account_id
        ):
            account_id = UNKNOWN_TARGET_ACCOUNT_ID
        logger.info(
            "admin_audit operation=%s operator_account=%s target_account=%s outcome=%s",
            operation,
            operator_id,
            account_id,
            outcome,
        )

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

        try:
            target = self._get_by_exact_id(account_id)
        except Exception:
            self._audit(operator_id, "revoke", UNKNOWN_TARGET_ACCOUNT_ID, "error")
            raise
        if target is None:
            self._audit(operator_id, "revoke", UNKNOWN_TARGET_ACCOUNT_ID, "not_found")
            raise NotFoundError("Account", account_id)
        try:
            revoked = self.session_repo.delete_all_for_user(target.id)
        except Exception:
            self._audit(operator_id, "revoke", target.id, "error")
            raise
        logger.info(
            "Admin session revoke admin_audit operation=%s operator=%s account=%s "
            "operator_account=%s target_account=%s outcome=%s",
            "revoke",
            operator_id,
            target.id,
            operator_id,
            target.id,
            "revoked",
        )
        return revoked


__all__ = ["AdminService"]
