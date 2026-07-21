"""Repository for authenticated sessions.

Sessions are keyed by the SHA-256 digest of the opaque session token — the
raw token is never stored on disk, so a data/ directory leak can't be
replayed back as a valid cookie.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from app.exceptions import StorageUnavailableError
from app.schemas.auth import Session
from app.utils.file_ops import ensure_directory
from app.utils.time import utcnow

from .base import BaseRepository

SESSIONS_DIRNAME = "sessions"


@contextmanager
def _file_guard() -> Iterator[None]:
    """Translate raw filesystem failures into the app's domain exceptions.

    Mirrors the sqlite guard used by the SQLite-backed repositories: an
    ``OSError`` here (disk full, permission denied, unavailable mount) is a
    transient persistence outage, not a bug, so mobile/browser session
    creation can surface a correlated 503 instead of an opaque 500.
    """

    try:
        yield
    except OSError as exc:
        raise StorageUnavailableError(
            "Session storage is temporarily unavailable; retry the request."
        ) from exc


class SessionRepository(BaseRepository):
    """Persist sessions as one JSON file per token hash."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.sessions_dir = ensure_directory(self.resolve(SESSIONS_DIRNAME))

    def _session_path(self, token_hash: str) -> Path:
        return self.sessions_dir / f"{token_hash}.json"

    def create(self, session: Session) -> None:
        with _file_guard():
            self.dump_model(self._session_path(session.token_hash), session)

    def get(self, token_hash: str) -> Session | None:
        """Return the session if valid, deleting it lazily if expired."""

        path = self._session_path(token_hash)
        if not path.exists():
            return None
        with _file_guard():
            session = self.load_model(path, Session)
        if session.expires_at <= utcnow():
            # Expired — clean up and behave as if missing.
            with suppress(FileNotFoundError):  # pragma: no cover - race
                path.unlink()
            return None
        return session

    def delete(self, token_hash: str) -> None:
        path = self._session_path(token_hash)
        with _file_guard(), suppress(FileNotFoundError):
            path.unlink()
