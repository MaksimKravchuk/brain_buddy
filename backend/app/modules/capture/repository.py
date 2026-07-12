"""Filesystem repository for Capture module records.

Layout (per ADR-0001):
  captures/{owner_id}/sessions/{session_id}.json
  captures/{owner_id}/items/{item_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.utils.file_ops import ensure_directory

from .domain import AtomicCaptureSource, CaptureItem, CaptureSession


class CaptureRepository:
    """Persist and retrieve capture records from the filesystem."""

    def __init__(self, data_root: Path) -> None:
        self._root = ensure_directory(data_root / "captures")

    # -- CaptureSession --

    def _session_dir(self, owner_id: str, session_id: str) -> Path:
        return ensure_directory(self._root / owner_id / "sessions" / session_id)

    def save_session(self, session: CaptureSession) -> None:
        d = self._session_dir(session.owner_id, session.id)
        path = d / "session.json"
        from app.utils.file_ops import write_json

        write_json(path, session.model_dump(mode="json"))

    def load_session(self, owner_id: str, session_id: str) -> CaptureSession:
        path = self._session_dir(owner_id, session_id) / "session.json"
        if not path.exists():
            raise NotFoundError("CaptureSession", session_id)
        from app.utils.file_ops import read_json

        return CaptureSession.model_validate(read_json(path))

    # -- AtomicCaptureSource + CaptureItem (shared ID) --

    def _item_path(self, owner_id: str, item_id: str) -> Path:
        d = ensure_directory(self._root / owner_id / "items")
        return d / f"{item_id}.json"

    def save_capture(
        self, source: AtomicCaptureSource, item: CaptureItem
    ) -> None:
        """Persist an immutable source + its mutable item as a single file.

        The shared-ID one-to-one mapping means we store both in one JSON
        document, keyed by the capture ID. This simplifies loading and
        preserves the invariant.
        """

        path = self._item_path(source.owner_id, source.id)
        from app.utils.file_ops import write_json

        payload = {
            "source": source.model_dump(mode="json"),
            "item": item.model_dump(mode="json"),
        }
        write_json(path, payload)

    def load_capture(self, owner_id: str, capture_id: str) -> tuple[AtomicCaptureSource, CaptureItem]:
        path = self._item_path(owner_id, capture_id)
        if not path.exists():
            raise NotFoundError("CaptureItem", capture_id)
        from app.utils.file_ops import read_json

        payload = read_json(path)
        return (
            AtomicCaptureSource.model_validate(payload["source"]),
            CaptureItem.model_validate(payload["item"]),
        )

    def load_item(self, owner_id: str, capture_id: str) -> CaptureItem:
        _, item = self.load_capture(owner_id, capture_id)
        return item

    def save_item(self, item: CaptureItem) -> None:
        """Persist only the mutable item (source is immutable)."""

        path = self._item_path(item.owner_id, item.id)
        from app.utils.file_ops import read_json, write_json

        if not path.exists():
            raise NotFoundError("CaptureItem", item.id)
        payload = read_json(path)
        payload["item"] = item.model_dump(mode="json")
        write_json(path, payload)

    # -- Listing --

    def list_items_for_owner(self, owner_id: str) -> list[CaptureItem]:
        items_dir = self._root / owner_id / "items"
        if not items_dir.exists():
            return []
        results: list[CaptureItem] = []
        for path in sorted(items_dir.glob("*.json")):
            from app.utils.file_ops import read_json

            payload = read_json(path)
            results.append(CaptureItem.model_validate(payload["item"]))
        return results

    def list_sessions_for_owner(self, owner_id: str) -> list[CaptureSession]:
        sessions_dir = self._root / owner_id / "sessions"
        if not sessions_dir.exists():
            return []
        results: list[CaptureSession] = []
        for path in sorted(sessions_dir.glob("*/session.json")):
            from app.utils.file_ops import read_json

            results.append(CaptureSession.model_validate(read_json(path)))
        return results
