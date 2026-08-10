"""Repository for authenticated sessions.

Sessions are keyed by the SHA-256 digest of the opaque session token — the
raw token is never stored on disk, so a data/ directory leak can't be
replayed back as a valid cookie.
"""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from app.schemas.auth import Session
from app.utils.file_ops import ensure_directory
from app.utils.time import utcnow

from .base import BaseRepository

SESSIONS_DIRNAME = "sessions"


class SessionRepository(BaseRepository):
    """Persist sessions as one JSON file per token hash."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.sessions_dir = ensure_directory(self.resolve(SESSIONS_DIRNAME))

    def _session_path(self, token_hash: str) -> Path:
        return self.sessions_dir / f"{token_hash}.json"

    def create(self, session: Session) -> None:
        self.dump_model(self._session_path(session.token_hash), session)

    def get(self, token_hash: str) -> Session | None:
        """Return the session if valid, deleting it lazily if expired."""

        path = self._session_path(token_hash)
        if not path.exists():
            return None
        session = self.load_model(path, Session)
        if session.expires_at <= utcnow():
            # Expired — clean up and behave as if missing.
            with suppress(FileNotFoundError):  # pragma: no cover - race
                path.unlink()
            return None
        return session

    def delete(self, token_hash: str) -> None:
        path = self._session_path(token_hash)
        with suppress(FileNotFoundError):
            path.unlink()

    def delete_all_for_user(self, user_id: str, *, keep: str | None = None) -> int:
        """Revoke every session belonging to `user_id`; return the count.

        Sessions are keyed by token hash, so this scans the whole directory —
        fine at this scale. `keep` preserves one token hash (the caller's own
        session, e.g. after a password change). Unreadable files are skipped.
        """

        removed = 0
        for path in self.sessions_dir.glob("*.json"):
            if keep is not None and path.stem == keep:
                continue
            try:
                session = self.load_model(path, Session)
            # S112: continuing without logging is deliberate here -- a corrupt
            # entry must not block revocation, and the path is on the auth hot
            # path where a log line per bad file would be noise.
            except Exception:  # noqa: BLE001, S112 - corrupt entry must not block revocation
                continue
            if session.user_id != user_id:
                continue
            with suppress(FileNotFoundError):
                path.unlink()
                removed += 1
        return removed
