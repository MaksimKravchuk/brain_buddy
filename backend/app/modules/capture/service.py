"""Capture service: session creation, text splitting, item lifecycle.

Implements ADR-0001 Capture pipeline for text input. Voice/transcription
is deferred to ADR-0002. The service also handles CaptureItem decision
transitions (Organize module is merged here for MVP simplicity).
"""

from __future__ import annotations

from app.exceptions import NotFoundError, ValidationFailure
from app.utils.identifiers import generate_id
from app.utils.time import utcnow

from .domain import (
    AtomicCaptureSource,
    CaptureItem,
    CaptureItemState,
    CaptureKind,
    CaptureSession,
)
from .repository import CaptureRepository

# States eligible for Weekly Review (ADR-0001).
REVIEW_ELIGIBLE_STATES: frozenset[CaptureItemState] = frozenset(
    {"proposed", "needs_clarification", "approved", "deferred"}
)

# Terminal states — ineligible for review.
TERMINAL_STATES: frozenset[CaptureItemState] = frozenset({"completed", "deleted"})

# Valid transitions per ADR-0001.
ALLOWED_TRANSITIONS: dict[CaptureItemState, frozenset[CaptureItemState]] = {
    "proposed": frozenset({"needs_clarification", "approved", "deferred", "deleted"}),
    "needs_clarification": frozenset({"proposed", "approved", "deferred", "deleted"}),
    "deferred": frozenset({"proposed", "approved", "deleted"}),
    "approved": frozenset({"approved", "completed", "deleted"}),
    "completed": frozenset(),  # terminal
    "deleted": frozenset(),  # terminal
}


class CaptureService:
    """Manage capture sessions and capture item lifecycle."""

    def __init__(self, repo: CaptureRepository) -> None:
        self._repo = repo

    # -- Session creation (text-only MVP) --

    def create_text_session(
        self,
        *,
        owner_id: str,
        text: str,
    ) -> tuple[CaptureSession, list[CaptureItem]]:
        """Create a text capture session and split into atomic items.

        For the MVP, splitting is simple: each non-empty line is one atomic
        capture. Classification is heuristic-based.
        """
        text = text.strip()
        if not text:
            raise ValidationFailure(
                "Cannot create a capture session from empty text.",
                detail={"reason": "empty_text"},
            )

        session_id = generate_id("cs")
        session = CaptureSession(
            id=session_id,
            owner_id=owner_id,
            input_kind="text",
            status="received",
        )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        items: list[CaptureItem] = []
        for ordinal, line in enumerate(lines, start=1):
            capture_id = generate_id("cap")
            kind = self._classify(line)
            source = AtomicCaptureSource(
                id=capture_id,
                owner_id=owner_id,
                capture_session_id=session_id,
                ordinal=ordinal,
                kind=kind,
                source_text=line,
                classification={"method": "heuristic"},
            )
            item = CaptureItem(
                id=capture_id,
                owner_id=owner_id,
                source_capture_id=session_id,
                current_text=line,
                review_state="proposed",
            )
            self._repo.save_capture(source, item)
            items.append(item)
            session.atomic_capture_ids.append(capture_id)

        session.status = "ready"
        session.updated_at = utcnow()
        self._repo.save_session(session)
        return session, items

    # -- Item queries --

    def get_item(self, owner_id: str, capture_id: str) -> CaptureItem:
        return self._repo.load_item(owner_id, capture_id)

    def get_capture(
        self, owner_id: str, capture_id: str
    ) -> tuple[AtomicCaptureSource, CaptureItem]:
        return self._repo.load_capture(owner_id, capture_id)

    def list_items_for_owner(self, owner_id: str) -> list[CaptureItem]:
        return self._repo.list_items_for_owner(owner_id)

    def list_eligible_for_review(self, owner_id: str) -> list[CaptureItem]:
        """Return items eligible for Weekly Review.

        Per ADR-0001: items in proposed, needs_clarification, approved,
        or deferred state. Completed and deleted are ineligible.
        Approved items with a succeeded route are also excluded
        (convergence guard) — but since routing is not yet implemented,
        this is a no-op for now.
        """
        return [
            item
            for item in self.list_items_for_owner(owner_id)
            if item.review_state in REVIEW_ELIGIBLE_STATES
        ]

    def get_session(self, owner_id: str, session_id: str) -> CaptureSession:
        return self._repo.load_session(owner_id, session_id)

    def list_sessions_for_owner(self, owner_id: str) -> list[CaptureSession]:
        return self._repo.list_sessions_for_owner(owner_id)

    # -- Item decisions (Organize module merged for MVP) --

    def apply_decision(
        self,
        owner_id: str,
        capture_id: str,
        *,
        action: str,
        new_text: str | None = None,
        expected_revision: int | None = None,
    ) -> CaptureItem:
        """Apply a decision to a capture item.

        Actions: edit, clarify, approve, defer, complete, delete.
        """
        item = self._repo.load_item(owner_id, capture_id)

        if item.owner_id != owner_id:
            raise NotFoundError("CaptureItem", capture_id)

        if expected_revision is not None and item.revision != expected_revision:
            from app.exceptions import ConflictError

            raise ConflictError("CaptureItem", capture_id)

        target_state = self._resolve_target_state(action)
        if target_state not in ALLOWED_TRANSITIONS.get(item.review_state, frozenset()):
            raise ValidationFailure(
                f"Cannot {action} capture in state '{item.review_state}'.",
                detail={
                    "reason": "invalid_transition",
                    "from_state": item.review_state,
                    "action": action,
                },
            )

        if action == "edit" and new_text is not None:
            item.current_text = new_text
            # edit keeps approved state, or transitions from proposed to approved
            if item.review_state in ("proposed", "needs_clarification"):
                target_state = "approved"

        if action == "edit" and item.review_state == "approved":
            target_state = "approved"  # edit on approved stays approved

        item.review_state = target_state
        item.revision += 1
        item.updated_at = utcnow()
        self._repo.save_item(item)
        return item

    # -- Internal helpers --

    @staticmethod
    def _resolve_target_state(action: str) -> CaptureItemState:
        mapping: dict[str, CaptureItemState] = {
            "edit": "approved",
            "clarify": "needs_clarification",
            "approve": "approved",
            "defer": "deferred",
            "complete": "completed",
            "delete": "deleted",
        }
        if action not in mapping:
            raise ValidationFailure(
                f"Unknown action '{action}'.",
                detail={"reason": "unknown_action", "action": action},
            )
        return mapping[action]

    @staticmethod
    def _classify(text: str) -> CaptureKind:
        """Heuristic capture classification for MVP."""
        lower = text.lower()
        if any(w in lower for w in ("?", "how to", "why", "what if", "should i")):
            return "question"
        if any(
            w in lower
            for w in (
                "fix",
                "build",
                "deploy",
                "test",
                "implement",
                "create",
                "update",
                "refactor",
                "todo",
            )
        ):
            return "task"
        if any(w in lower for w in ("problem", "issue", "bug", "error", "broken")):
            return "problem_candidate"
        result: CaptureKind = "note"
        return result
