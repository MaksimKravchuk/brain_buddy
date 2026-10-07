"""Hashed opaque session facade over Identity's transactional SQLite store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.exceptions import ConflictError, RepositoryError
from app.schemas.auth import Session
from app.utils.file_ops import ensure_directory
from app.utils.time import utcnow

from .auth_store import AuthStore
from .base import BaseRepository

SESSIONS_DIRNAME = "sessions"


class SessionRepository(BaseRepository):
    """Persist only token digests, with real owner and binding foreign keys."""

    def __init__(self, root: Path, store: AuthStore | None = None) -> None:
        super().__init__(root)
        self.store = store if store is not None else AuthStore(self.root)
        self.sessions_dir = ensure_directory(self.resolve(SESSIONS_DIRNAME))

    def _session_path(self, token_hash: str) -> Path:
        return self.sessions_dir / f"{token_hash}.json"

    @staticmethod
    def _decode(row: sqlite3.Row) -> tuple[Session, dict[str, Any]]:
        try:
            payload = json.loads(row["payload_json"])
            if not isinstance(payload, dict):
                raise ValueError("Invalid session payload shape.")
            session = Session.model_validate(payload)
            if (
                session.token_hash != row["token_hash"]
                or session.user_id != row["user_id"]
                or session.auth_version != row["auth_version"]
                or session.auth_method != row["auth_method"]
                or session.provider_binding_id != row["provider_binding_id"]
                or session.model_dump(mode="json")["expires_at"] != row["expires_at"]
            ):
                raise ValueError("Session payload disagrees with indexed authority.")
        except (ValueError, ValidationError, TypeError) as exc:
            raise RepositoryError("Authentication session record is invalid.") from exc
        return session, payload

    def create(self, session: Session) -> None:
        stored = Session.model_validate(session.model_dump())
        fields = stored.model_dump(mode="json")
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE token_hash=?", (stored.token_hash,)
            ).fetchone()
            payload: dict[str, Any] = {}
            if row is not None:
                current, payload = self._decode(row)
                if (
                    current.user_id != stored.user_id
                    or stored.auth_version < current.auth_version
                ):
                    raise ConflictError(
                        "Session", stored.token_hash, "Session authority has changed."
                    )
            connection.execute(
                "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,auth_version,auth_method,confirmed_at,provider_binding_id,payload_json) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(token_hash) DO UPDATE SET "
                "created_at=excluded.created_at,expires_at=excluded.expires_at,auth_version=excluded.auth_version,"
                "auth_method=excluded.auth_method,confirmed_at=excluded.confirmed_at,"
                "provider_binding_id=excluded.provider_binding_id,payload_json=excluded.payload_json",
                (
                    stored.token_hash,
                    stored.user_id,
                    fields["created_at"],
                    fields["expires_at"],
                    stored.auth_version,
                    stored.auth_method,
                    fields["confirmed_at"],
                    stored.provider_binding_id,
                    json.dumps(
                        payload | fields, ensure_ascii=False, separators=(",", ":")
                    ),
                ),
            )

    def get(self, token_hash: str) -> Session | None:
        """Read current state and remove expired sessions atomically."""
        with self.store.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE token_hash=?", (token_hash,)
            ).fetchone()
            if row is None:
                return None
            session, _payload = self._decode(row)
            if session.expires_at <= utcnow():
                connection.execute(
                    "DELETE FROM sessions WHERE token_hash=?", (token_hash,)
                )
                return None
            return session

    def delete(self, token_hash: str) -> None:
        with self.store.transaction() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def delete_all_for_user(self, user_id: str, *, keep: str | None = None) -> int:
        with self.store.transaction() as connection:
            if keep is None:
                result = connection.execute(
                    "DELETE FROM sessions WHERE user_id=?", (user_id,)
                )
            else:
                result = connection.execute(
                    "DELETE FROM sessions WHERE user_id=? AND token_hash<>?",
                    (user_id, keep),
                )
            return result.rowcount


__all__ = ["SessionRepository"]
