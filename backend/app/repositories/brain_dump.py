"""Filesystem repository for brain dump sessions.

Sessions are stored as one JSON file per session under
``brain_dumps/{owner_id}/{session_id}.json``. Owner isolation is enforced
at the repository level: a cross-owner load returns ``None``.
"""

from __future__ import annotations

from pathlib import Path

from app.schemas.brain_dump import BrainDumpSession, SessionStatus
from app.utils.file_ops import ensure_directory

from .base import BaseRepository

BRAIN_DUMP_DIRNAME = "brain_dumps"


class BrainDumpRepository(BaseRepository):
    """Persist brain dump sessions to the filesystem."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)

    def _session_path(self, owner_id: str, session_id: str) -> Path:
        owner_dir = ensure_directory(self.resolve(BRAIN_DUMP_DIRNAME, owner_id))
        return owner_dir / f"{session_id}.json"

    def _find_session_file(self, session_id: str) -> Path | None:
        """Search across all owner directories for a session file."""

        brain_dump_root = self.resolve(BRAIN_DUMP_DIRNAME)
        if not brain_dump_root.exists():
            return None
        for owner_dir in brain_dump_root.iterdir():
            if not owner_dir.is_dir():
                continue
            candidate = owner_dir / f"{session_id}.json"
            if candidate.exists():
                return candidate
        return None

    def save(self, session: BrainDumpSession) -> None:
        """Create or update a brain dump session."""

        path = self._session_path(session.owner_id, session.id)
        self.dump_model(path, session)

    def load(self, session_id: str, *, owner_id: str) -> BrainDumpSession | None:
        """Load a session by ID for the given owner.

        Returns ``None`` if the session does not exist or belongs to a
        different owner.
        """

        path = self._session_path(owner_id, session_id)
        if not path.exists():
            return None
        session = self.load_model(path, BrainDumpSession)
        # Guard against any path manipulation that could bypass owner scoping.
        if session.owner_id != owner_id:
            return None
        return session

    def get_active_session(self, *, owner_id: str) -> BrainDumpSession | None:
        """Return the owner's active (non-completed) session, if any."""

        owner_dir = self.resolve(BRAIN_DUMP_DIRNAME, owner_id)
        if not owner_dir.exists():
            return None
        for file_path in sorted(owner_dir.glob("*.json")):
            session = self.load_model(file_path, BrainDumpSession)
            if session.owner_id != owner_id:
                continue
            if session.status != SessionStatus.COMPLETED:
                return session
        return None
