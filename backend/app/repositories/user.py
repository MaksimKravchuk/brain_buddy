"""Legacy user facade over Identity's authoritative SQLite records."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.exceptions import ConflictError, NotFoundError, RepositoryError
from app.schemas.auth import User
from app.utils.file_ops import ensure_directory

from .auth_store import AuthStore
from .base import BaseRepository

USERS_DIRNAME = "users"
BY_EMAIL_INDEX_FILENAME = "_by_email.json"
PROFILE_TRANSACTION_FILENAME = "_profile_transaction.json"


class UserRepository(BaseRepository):
    """Persist model fields and preserved legacy fields together in one row."""

    def __init__(self, root: Path, store: AuthStore | None = None) -> None:
        super().__init__(root)
        self.store = store if store is not None else AuthStore(self.root)
        # Retained for migration tooling and fixture paths, never an authority.
        self.users_dir = ensure_directory(self.resolve(USERS_DIRNAME))
        self.index_path = self.users_dir / BY_EMAIL_INDEX_FILENAME
        self.transaction_path = self.users_dir / PROFILE_TRANSACTION_FILENAME

    def _user_path(self, user_id: str) -> Path:
        return self.users_dir / f"{user_id}.json"

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _decode(row: sqlite3.Row) -> tuple[User, dict[str, Any]]:
        try:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                raise ValueError("Invalid user payload shape.")
            user = User.model_validate(payload)
            if (
                user.id != row["id"]
                or user.email != row["email"]
                or user.password_hash != row["password_hash"]
                or user.auth_version != row["auth_version"]
                or user.model_dump(mode="json")["email_verified_at"]
                != row["email_verified_at"]
            ):
                raise ValueError("User payload disagrees with indexed authority.")
        except (ValueError, ValidationError, TypeError) as exc:
            raise RepositoryError("Authentication user record is invalid.") from exc
        return user, payload

    @staticmethod
    def _values(user: User, payload: dict[str, Any]) -> tuple[Any, ...]:
        fields = user.model_dump(mode="json")
        preserved = payload | fields
        return (
            user.email,
            user.password_hash,
            fields["email_verified_at"],
            user.auth_version,
            fields["created_at"],
            fields["deletion_requested_at"],
            json.dumps(preserved, ensure_ascii=False, separators=(",", ":")),
            user.id,
        )

    def get_by_id(self, user_id: str) -> User | None:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id=?", (user_id,)
            ).fetchone()
            return None if row is None else self._decode(row)[0]

    def get_by_email(self, email: str) -> User | None:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE email=?", (self.normalize_email(email),)
            ).fetchone()
            return None if row is None else self._decode(row)[0]

    def create(self, user: User) -> User:
        stored = User.model_validate(
            user.model_dump() | {"email": self.normalize_email(user.email)}
        )
        with self.store.transaction() as connection:
            connection.execute(
                "INSERT INTO users(email,password_hash,email_verified_at,auth_version,created_at,deletion_requested_at,payload_json,id) VALUES(?,?,?,?,?,?,?,?)",
                self._values(stored, {}),
            )
        return stored

    def _update(
        self,
        connection: sqlite3.Connection,
        current: User,
        updated: User,
        payload: dict[str, Any],
    ) -> User:
        if updated.id != current.id:
            raise ConflictError(
                "User", current.id, "Account identifiers are immutable."
            )
        if updated.auth_version < current.auth_version:
            raise ConflictError("User", current.id, "Account authority has changed.")
        normalized = self.normalize_email(updated.email)
        email_changed = normalized != current.email
        authority_changed = (
            email_changed or updated.password_hash != current.password_hash
        )
        changes: dict[str, Any] = {"email": normalized}
        if authority_changed:
            changes["auth_version"] = max(
                current.auth_version + 1, updated.auth_version
            )
        if email_changed:
            changes["email_verified_at"] = None
        stored = User.model_validate(updated.model_dump() | changes)
        connection.execute(
            "UPDATE users SET email=?,password_hash=?,email_verified_at=?,auth_version=?,created_at=?,deletion_requested_at=?,payload_json=? WHERE id=?",
            self._values(stored, payload),
        )
        if authority_changed:
            connection.execute("DELETE FROM auth_proofs WHERE user_id=?", (stored.id,))
            connection.execute(
                "DELETE FROM auth_challenges WHERE user_id=?", (stored.id,)
            )
            connection.execute(
                "DELETE FROM auth_attempts WHERE user_id=?", (stored.id,)
            )
        return stored

    def _require_row(
        self, connection: sqlite3.Connection, user_id: str
    ) -> tuple[User, dict[str, Any]]:
        row = connection.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("User", user_id)
        return self._decode(row)

    def save(self, user: User) -> None:
        """Update an existing account; reject snapshots of older authority."""
        with self.store.transaction() as connection:
            current, payload = self._require_row(connection, user.id)
            self._update(connection, current, user, payload)

    def mutate(self, user_id: str, mutator: Callable[[User], User]) -> User:
        """Read the current row, mutate it and update it in one write transaction."""
        with self.store.transaction() as connection:
            current, payload = self._require_row(connection, user_id)
            return self._update(connection, current, mutator(current), payload)

    def update_email(self, user_id: str, new_email: str) -> User:
        return self.mutate(
            user_id, lambda user: user.model_copy(update={"email": new_email})
        )

    def update_profile(
        self, user_id: str, *, email: str, display_name: str | None
    ) -> User:
        return self.mutate(
            user_id,
            lambda user: user.model_copy(
                update={"email": email, "display_name": display_name}
            ),
        )

    def delete(self, user_id: str) -> None:
        """Idempotently remove the user and cascade account-owned auth records."""
        with self.store.transaction() as connection:
            bindings = connection.execute(
                "SELECT namespace,subject FROM auth_identity_bindings WHERE user_id=? AND provider='apple'",
                (user_id,),
            ).fetchall()
            for binding in bindings:
                fingerprint = hashlib.sha256(
                    f"{binding['namespace']}\0{binding['subject']}".encode()
                ).hexdigest()
                connection.execute(
                    "DELETE FROM auth_apple_notification_receipts WHERE namespace=? AND subject_fingerprint=?",
                    (binding["namespace"], fingerprint),
                )
            connection.execute("DELETE FROM users WHERE id=?", (user_id,))

    def list_users(self) -> list[User]:
        with self.store.connection() as connection:
            rows = connection.execute("SELECT * FROM users ORDER BY id").fetchall()
            return [self._decode(row)[0] for row in rows]


__all__ = ["UserRepository"]
