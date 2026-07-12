"""Application workflow layer for capture-to-review.

Coordinates Capture, Organize, and Execution modules. Per ADR-0001:
- modules must not reach into another module's repository
- the application service coordinates cross-module writes
- persist the initiating state, invoke the next module idempotently,
  then persist the returned reference
"""

from __future__ import annotations

import logging

from app.exceptions import ConflictError, ValidationFailure
from app.modules.capture.domain import AtomicCaptureSource, CaptureSession
from app.modules.capture.service import CaptureService
from app.modules.execution.service import ExecutionService
from app.modules.organize.domain import CaptureItem, RouteRecord
from app.modules.organize.service import OrganizeService
from app.modules.thinking.service import ThinkingService
from app.utils.time import utcnow

logger = logging.getLogger(__name__)


class CaptureReviewWorkflow:
    """Coordinates the capture -> organize -> execution pipeline."""

    def __init__(
        self,
        capture_service: CaptureService,
        organize_service: OrganizeService,
        execution_service: ExecutionService,
        thinking_service: ThinkingService,
    ) -> None:
        self._capture = capture_service
        self._organize = organize_service
        self._execution = execution_service
        self._thinking = thinking_service

    def submit_text_capture(
        self,
        *,
        owner_id: str,
        text: str,
        consent: bool = False,
    ) -> CaptureSession:
        """Submit a text capture (non-voice input).

        Transcribes (trivially for text), splits, and creates CaptureItems.
        """
        from app.modules.capture.domain import ConsentRecord

        consent_record = ConsentRecord(
            external_processing_allowed=consent,
            recorded_at=utcnow(),
            provider=None,
        )

        session = self._capture.create_session(
            owner_id=owner_id,
            input_kind="text",
            text_input=text,
            consent=consent_record,
        )

        if session.status == "ready":
            self._create_items_for_session(session)

        return session

    def submit_voice_capture(
        self,
        *,
        owner_id: str,
        media_bytes: bytes,
        mime_type: str = "audio/webm",
        consent: bool = False,
    ) -> CaptureSession:
        """Submit a voice capture (multipart upload).

        For the MVP, the mock transcriber decodes media_bytes as text.
        """
        from app.modules.capture.domain import ConsentRecord, MediaInfo

        consent_record = ConsentRecord(
            external_processing_allowed=consent,
            recorded_at=utcnow(),
            provider="mock",
        )

        media_info = MediaInfo(
            mime_type=mime_type,
            byte_size=len(media_bytes),
            duration_ms=None,
            sha256=None,
        )

        session = self._capture.create_session(
            owner_id=owner_id,
            input_kind="voice",
            media_bytes=media_bytes,
            media_info=media_info,
            consent=consent_record,
        )

        if session.status == "ready":
            self._create_items_for_session(session)

        return session

    def retry_capture(
        self,
        *,
        owner_id: str,
        session_id: str,
        media_bytes: bytes | None = None,
        text_input: str | None = None,
    ) -> CaptureSession:
        """Retry a failed capture session."""
        session = self._capture.retry_session(
            owner_id=owner_id,
            session_id=session_id,
            media_bytes=media_bytes,
            text_input=text_input,
        )

        if session.status == "ready":
            self._create_items_for_session(session)

        return session

    def cancel_capture(self, *, owner_id: str, session_id: str) -> CaptureSession:
        """Cancel a capture session."""
        return self._capture.cancel_session(
            owner_id=owner_id,
            session_id=session_id,
        )

    def _create_items_for_session(self, session: CaptureSession) -> list[CaptureItem]:
        """Create CaptureItems for all atomic sources in a ready session."""
        items: list[CaptureItem] = []
        sources = self._capture.get_sources(
            owner_id=session.owner_id,
            session_id=session.id,
        )

        for source in sources:
            needs_clarification = self._capture.is_low_confidence(source)
            item = self._organize.create_item_from_source(
                source_id=source.id,
                owner_id=session.owner_id,
                capture_session_id=session.id,
                source_text=source.source_text,
                needs_clarification=needs_clarification,
                clarification_question=(
                    "Low confidence classification. Please review."
                    if needs_clarification
                    else None
                ),
            )
            items.append(item)

        logger.info(
            "Created %d capture items for session %s",
            len(items),
            session.id,
        )
        return items

    # --- Decision actions ---

    def edit_capture(
        self,
        *,
        owner_id: str,
        capture_id: str,
        new_text: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, str]:
        """Edit a capture item's text. Returns (item, decision_id)."""
        item, decision = self._organize.edit_item(
            owner_id=owner_id,
            item_id=capture_id,
            new_text=new_text,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return item, decision.id

    def clarify_capture(
        self,
        *,
        owner_id: str,
        capture_id: str,
        question: str,
        answer: str | None,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, str]:
        """Set or resolve a clarification on a capture item."""
        item, decision = self._organize.clarify_item(
            owner_id=owner_id,
            item_id=capture_id,
            question=question,
            answer=answer,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return item, decision.id

    def approve_capture(
        self,
        *,
        owner_id: str,
        capture_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, str]:
        """Approve a capture item."""
        item, decision = self._organize.approve_item(
            owner_id=owner_id,
            item_id=capture_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return item, decision.id

    def defer_capture(
        self,
        *,
        owner_id: str,
        capture_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
    ) -> tuple[CaptureItem, str]:
        """Defer a capture item."""
        item, decision = self._organize.defer_item(
            owner_id=owner_id,
            item_id=capture_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
        )
        return item, decision.id

    def delete_capture(
        self,
        *,
        owner_id: str,
        capture_id: str,
        actor_id: str,
        correlation_id: str,
        idempotency_key: str,
        expected_revision: int,
        reason: str | None = None,
        avoidance_reason: str | None = None,
    ) -> tuple[CaptureItem, str]:
        """Delete a capture item."""
        item, decision = self._organize.delete_item(
            owner_id=owner_id,
            item_id=capture_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            expected_revision=expected_revision,
            reason=reason,
            avoidance_reason=avoidance_reason,  # type: ignore[arg-type]
        )
        return item, decision.id

    # --- Routing ---

    def route_capture(
        self,
        *,
        owner_id: str,
        capture_id: str,
        destination: str,
        actor_id: str,
        idempotency_key: str,
    ) -> tuple[RouteRecord, CaptureItem]:
        """Route an approved capture to an external destination.

        Creates a route, dispatches it, and if successful, completes the item.
        """
        item = self._organize.get_item(owner_id=owner_id, item_id=capture_id)

        if item.review_state != "approved":
            raise ValidationFailure(
                f"Cannot route item in state '{item.review_state}'. Item must be approved first.",
                detail={"current_state": item.review_state},
            )

        route = self._organize.create_route(
            owner_id=owner_id,
            item_id=capture_id,
            destination=destination,
            idempotency_key=idempotency_key,
        )

        attempt, updated_route = self._execution.dispatch_route(
            owner_id=owner_id,
            route=route,
            capture_text=item.current_text,
            idempotency_key=f"{idempotency_key}::dispatch",
        )

        if updated_route.status == "succeeded":
            # Reload the item to get the current revision before completing.
            current_item = self._organize.get_item(
                owner_id=owner_id, item_id=capture_id
            )
            try:
                self._organize.complete_item(
                    owner_id=owner_id,
                    item_id=capture_id,
                    actor_id=actor_id,
                    correlation_id=idempotency_key,
                    idempotency_key=f"{idempotency_key}::complete",
                    expected_revision=current_item.revision,
                )
            except ConflictError:
                pass

        final_item = self._organize.get_item(owner_id=owner_id, item_id=capture_id)
        return updated_route, final_item

    # --- Queries ---

    def get_capture_session(
        self, *, owner_id: str, session_id: str
    ) -> CaptureSession:
        return self._capture.get_session(owner_id=owner_id, session_id=session_id)

    def get_capture_sources(
        self, *, owner_id: str, session_id: str
    ) -> list[AtomicCaptureSource]:
        return self._capture.get_sources(owner_id=owner_id, session_id=session_id)

    def get_capture_item(self, *, owner_id: str, capture_id: str) -> CaptureItem:
        return self._organize.get_item(owner_id=owner_id, item_id=capture_id)

    def list_capture_items(self, *, owner_id: str) -> list[CaptureItem]:
        return self._organize.list_items(owner_id=owner_id)

    def list_capture_sessions(self, *, owner_id: str) -> list[CaptureSession]:
        return self._capture.list_sessions(owner_id=owner_id)

    def get_capture_results(
        self,
        *,
        owner_id: str,
        capture_id: str,
    ) -> list:
        return self._execution.list_results_for_capture(
            owner_id=owner_id,
            capture_id=capture_id,
        )


__all__ = ["CaptureReviewWorkflow"]
