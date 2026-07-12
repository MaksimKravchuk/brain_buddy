"""Filesystem repository for Organize records.

Layout per ADR-0001:
    organize/{owner_id}/{atomic_capture_id}.json  (CaptureItem)
    organize/{owner_id}/decisions/{decision_id}.json
    organize/{owner_id}/routes/{route_id}.json
"""

from __future__ import annotations

from pathlib import Path

from app.exceptions import NotFoundError
from app.modules.organize.domain import (
    CaptureItem,
    OrganizeDecision,
    RouteRecord,
)
from app.repositories.base import BaseRepository
from app.utils.file_ops import ensure_directory

ITEM_SUFFIX = ".json"
DECISIONS_DIRNAME = "decisions"
ROUTES_DIRNAME = "routes"


class OrganizeRepository(BaseRepository):
    """Persist and retrieve capture items, decisions, and routes."""

    def _owner_dir(self, owner_id: str) -> Path:
        return ensure_directory(self.resolve(owner_id))

    def _decisions_dir(self, owner_id: str) -> Path:
        return ensure_directory(self._owner_dir(owner_id) / DECISIONS_DIRNAME)

    def _routes_dir(self, owner_id: str) -> Path:
        return ensure_directory(self._owner_dir(owner_id) / ROUTES_DIRNAME)

    # --- CaptureItem ---

    def save_item(self, item: CaptureItem) -> None:
        path = self._owner_dir(item.owner_id) / f"{item.id}{ITEM_SUFFIX}"
        self.dump_model(path, item)

    def load_item(self, owner_id: str, item_id: str) -> CaptureItem:
        path = self._owner_dir(owner_id) / f"{item_id}{ITEM_SUFFIX}"
        if not path.exists():
            raise NotFoundError("CaptureItem", item_id)
        return self.load_model(path, CaptureItem)

    def list_items(
        self, owner_id: str, *, exclude_terminal: bool = True
    ) -> list[CaptureItem]:
        """List capture items for an owner.

        If exclude_terminal, skip completed/deleted items.
        """
        owner_dir = self._owner_dir(owner_id)
        items: list[CaptureItem] = []
        for child in owner_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    item = self.load_model(child, CaptureItem)
                except Exception:  # noqa: BLE001
                    continue
                if exclude_terminal and item.review_state in ("completed", "deleted"):
                    continue
                items.append(item)
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items

    def list_decisions_for_item(
        self, owner_id: str, item_id: str
    ) -> list[OrganizeDecision]:
        """List all decisions for a capture item, chronologically."""
        decisions_dir = self._decisions_dir(owner_id)
        decisions: list[OrganizeDecision] = []
        for child in decisions_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    decision = self.load_model(child, OrganizeDecision)
                except Exception:  # noqa: BLE001
                    continue
                if decision.atomic_capture_id == item_id:
                    decisions.append(decision)
        decisions.sort(key=lambda d: d.created_at)
        return decisions

    # --- Decisions ---

    def save_decision(self, decision: OrganizeDecision) -> None:
        path = self._decisions_dir(decision.owner_id) / f"{decision.id}.json"
        self.dump_model(path, decision)

    def load_decision(self, owner_id: str, decision_id: str) -> OrganizeDecision:
        path = self._decisions_dir(owner_id) / f"{decision_id}.json"
        if not path.exists():
            raise NotFoundError("OrganizeDecision", decision_id)
        return self.load_model(path, OrganizeDecision)

    def find_decision_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> OrganizeDecision | None:
        """Find a decision by its idempotency key (for deduplication)."""
        decisions_dir = self._decisions_dir(owner_id)
        for child in decisions_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    decision = self.load_model(child, OrganizeDecision)
                except Exception:  # noqa: BLE001
                    continue
                if decision.idempotency_key == idempotency_key:
                    return decision
        return None

    # --- RouteRecord ---

    def save_route(self, route: RouteRecord) -> None:
        path = self._routes_dir(route.owner_id) / f"{route.id}.json"
        self.dump_model(path, route)

    def load_route(self, owner_id: str, route_id: str) -> RouteRecord:
        path = self._routes_dir(owner_id) / f"{route_id}.json"
        if not path.exists():
            raise NotFoundError("RouteRecord", route_id)
        return self.load_model(path, RouteRecord)

    def find_route_by_idempotency_key(
        self, owner_id: str, idempotency_key: str
    ) -> RouteRecord | None:
        """Find a route by its idempotency key."""
        routes_dir = self._routes_dir(owner_id)
        for child in routes_dir.iterdir():
            if child.is_file() and child.suffix == ".json":
                try:
                    route = self.load_model(child, RouteRecord)
                except Exception:  # noqa: BLE001
                    continue
                if hasattr(route, "idempotency_key"):
                    return route
        return None


__all__ = ["OrganizeRepository"]
