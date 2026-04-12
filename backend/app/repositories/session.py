"""Repository for authenticated sessions.

Sessions are keyed by the SHA-256 digest of the opaque session token — the
raw token is never stored on disk, so a data/ directory leak can't be
replayed back as a valid cookie.
"""

from __future__ import annotations

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
            try:
                path.unlink()
            except FileNotFoundError:  # pragma: no cover - race
                pass
            return None
        return session

    def delete(self, token_hash: str) -> None:
        path = self._session_path(token_hash)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
