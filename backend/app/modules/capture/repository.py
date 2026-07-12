"""Filesystem repository for CaptureSession and AtomicCaptureSource.

Layout per ADR-0001:
    captures/{owner_id}/{capture_session_id}.json
    captures/{owner_id}/sources/{atomic_capture_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.modules.capture.domain import AtomicCaptureSource, CaptureSession
from app.repositories.base import BaseRepository
from app.utils.file_ops import ensure_directory

SESSION_FILENAME = "session.json"
SOURCES_DIRNAME = "sources"


class CaptureRepository(BaseRepository):
    """Persist and retrieve capture sessions and atomic sources."""

    def _owner_dir(self, owner_id: str) -> Path:
        return ensure_directory(self.resolve(owner_id))

    def _session_path(self, owner_id: str, session_id: str) -> Path:
        return self._owner_dir(owner_id) / session_id / SESSION_FILENAME

    def _session_dir(self, owner_id: str, session_id: str) -> Path:
        return ensure_directory(self._session_path(owner_id, session_id).parent)

    def _sources_dir(self, owner_id: str, session_id: str) -> Path:
        return ensure_directory(self._session_dir(owner_id, session_id) / SOURCES_DIRNAME)

    def _source_path(self, owner_id: str, source_id: str) -> Path:
        """Sources are stored under a flat owner-scoped directory for direct lookup."""
        return self._owner_dir(owner_id) / "sources" / f"{source_id}.json"

    # --- Session ---

    def save_session(self, session: CaptureSession) -> None:
        path = self._session_path(session.owner_id, session.id)
        self.dump_model(path, session)

    def load_session(self, owner_id: str, session_id: str) -> CaptureSession:
        path = self._session_path(owner_id, session_id)
        if not path.exists():
            raise NotFoundError("CaptureSession", session_id)
        return self.load_model(path, CaptureSession)

    # --- Sources ---

    def save_source(self, source: AtomicCaptureSource) -> None:
        path = self._source_path(source.owner_id, source.id)
        ensure_directory(path.parent)
        self.dump_model(path, source)

    def load_source(self, owner_id: str, source_id: str) -> AtomicCaptureSource:
        path = self._source_path(owner_id, source_id)
        if not path.exists():
            raise NotFoundError("AtomicCaptureSource", source_id)
        return self.load_model(path, AtomicCaptureSource)

    def load_sources_for_session(
        self, owner_id: str, session_id: str
    ) -> list[AtomicCaptureSource]:
        """Load all atomic sources for a session, ordered by ordinal."""
        session = self.load_session(owner_id, session_id)
        sources: list[AtomicCaptureSource] = []
        for source_id in session.atomic_capture_ids:
            try:
                sources.append(self.load_source(owner_id, source_id))
            except NotFoundError:
                continue
        sources.sort(key=lambda s: s.ordinal)
        return sources

    def list_sessions(self, owner_id: str) -> list[CaptureSession]:
        """List all sessions for an owner, ordered by created_at descending."""
        owner_dir = self._owner_dir(owner_id)
        sessions: list[CaptureSession] = []
        for child in owner_dir.iterdir():
            if not child.is_dir():
                continue
            session_path = child / SESSION_FILENAME
            if session_path.exists():
                try:
                    sessions.append(self.load_model(session_path, CaptureSession))
                except Exception:  # noqa: BLE001 - skip corrupted entries
                    continue
        sessions.sort(key=lambda s: s.created_at, reverse=True)
        return sessions


__all__ = ["CaptureRepository"]
