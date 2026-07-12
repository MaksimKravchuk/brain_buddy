"""FastAPI routes for the vNext capture workflow.

Implements the HTTP API from ADR-0001:
  POST /capture-sessions          - text or voice capture
  GET  /capture-sessions/{id}     - session detail with items
  POST /capture-sessions/{id}/retry - retry failed session
  POST /captures/{id}/decisions   - edit/clarify/approve/defer/delete
  POST /captures/{id}/routes      - request routing
  GET  /captures/{id}/results     - linked evidence/results
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)

from app.api.dependencies import get_current_user
from app.core.logging import get_correlation_id
from app.exceptions import NotFoundError
from app.schemas.auth import User
from app.schemas.capture import (
    AtomicCaptureSourceResponse,
    CaptureItemResponse,
    CaptureSessionDetailResponse,
    CaptureSessionResponse,
    DecisionRequest,
    DecisionResponse,
    EvidenceResultResponse,
    RouteDetailResponse,
    RouteRequest,
    RouteResponse,
    TextCaptureRequest,
)
from app.workflows.capture_review import CaptureReviewWorkflow

router = APIRouter(tags=["capture"])


def _get_workflow(request: Request) -> CaptureReviewWorkflow:
    workflow = getattr(request.app.state, "capture_workflow", None)
    if workflow is None:
        raise RuntimeError("Capture workflow has not been configured.")
    return workflow


def _correlation_id() -> str:
    return get_correlation_id() or str(uuid.uuid4())


def _session_to_response(session) -> CaptureSessionResponse:  # type: ignore[no-untyped-def]
    return CaptureSessionResponse(
        id=session.id,
        owner_id=session.owner_id,
        input_kind=session.input_kind,
        status=session.status,
        transcript=(
            {
                "provider": session.transcript.provider,
                "confidence": session.transcript.confidence,
                "completed_at": session.transcript.completed_at.isoformat(),
            }
            if session.transcript
            else None
        ),
        attempt_count=session.attempt_count,
        last_error=(
            {
                "code": session.last_error.code,
                "retryable": session.last_error.retryable,
                "stage": session.last_error.stage,
            }
            if session.last_error
            else None
        ),
        atomic_capture_ids=session.atomic_capture_ids,
        created_at=session.created_at,
        updated_at=session.updated_at,
        revision=session.revision,
    )


def _source_to_response(source) -> AtomicCaptureSourceResponse:  # type: ignore[no-untyped-def]
    return AtomicCaptureSourceResponse(
        id=source.id,
        capture_session_id=source.capture_session_id,
        ordinal=source.ordinal,
        kind=source.kind,
        source_text=source.source_text,
        classification=(
            {
                "confidence": source.classification.confidence,
                "model": source.classification.model,
                "reasons": source.classification.reasons,
            }
        ),
        created_at=source.created_at,
    )


def _item_to_response(item) -> CaptureItemResponse:  # type: ignore[no-untyped-def]
    return CaptureItemResponse(
        id=item.id,
        source_capture_id=item.source_capture_id,
        current_text=item.current_text,
        review_state=item.review_state,
        clarification=(
            {
                "question": item.clarification.question,
                "answer": item.clarification.answer,
                "resolved_at": item.clarification.resolved_at.isoformat()
                if item.clarification.resolved_at
                else None,
            }
            if item.clarification
            else None
        ),
        destination_intent=item.destination_intent,
        route_id=item.route_id,
        crt_candidate_id=item.crt_candidate_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        revision=item.revision,
    )


# --- Capture session endpoints ---


@router.post(
    "/capture-sessions",
    response_model=CaptureSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_capture_session(
    payload: TextCaptureRequest,
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> CaptureSessionResponse:
    """Submit a text brain dump capture."""
    session = workflow.submit_text_capture(
        owner_id=current_user.id,
        text=payload.text,
        consent=payload.consent.external_processing_allowed,
    )
    return _session_to_response(session)


@router.post(
    "/capture-sessions/voice",
    response_model=CaptureSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_voice_capture_session(
    file: UploadFile = File(...),
    consent: str = Form("false"),
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> CaptureSessionResponse:
    """Submit a voice brain dump capture (multipart upload)."""
    media_bytes = await file.read()
    session = workflow.submit_voice_capture(
        owner_id=current_user.id,
        media_bytes=media_bytes,
        mime_type=file.content_type or "audio/webm",
        consent=consent.lower() in ("true", "1", "yes"),
    )
    return _session_to_response(session)


@router.get("/capture-sessions/{session_id}")
def get_capture_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> CaptureSessionDetailResponse:
    """Get capture session detail with sources and items."""
    session = workflow.get_capture_session(
        owner_id=current_user.id,
        session_id=session_id,
    )
    sources = workflow.get_capture_sources(
        owner_id=current_user.id,
        session_id=session_id,
    )

    items = []
    for source in sources:
        try:
            item = workflow.get_capture_item(
                owner_id=current_user.id,
                capture_id=source.id,
            )
            items.append(_item_to_response(item))
        except NotFoundError:
            pass

    return CaptureSessionDetailResponse(
        id=session.id,
        owner_id=session.owner_id,
        input_kind=session.input_kind,
        status=session.status,
        transcript=(
            {
                "text": session.transcript.text,
                "provider": session.transcript.provider,
                "confidence": session.transcript.confidence,
                "completed_at": session.transcript.completed_at.isoformat(),
            }
            if session.transcript
            else None
        ),
        attempt_count=session.attempt_count,
        last_error=(
            {
                "code": session.last_error.code,
                "retryable": session.last_error.retryable,
                "stage": session.last_error.stage,
            }
            if session.last_error
            else None
        ),
        atomic_captures=[_source_to_response(s) for s in sources],
        items=items,
        created_at=session.created_at,
        updated_at=session.updated_at,
        revision=session.revision,
    )


@router.post(
    "/capture-sessions/{session_id}/retry",
    response_model=CaptureSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_capture_session(
    session_id: str,
    payload: dict | None = None,
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> CaptureSessionResponse:
    """Retry a failed capture session.

    Accepts an optional JSON body with `text` for text sessions that need
    new input to succeed.
    """
    text_input = None
    media_bytes = None
    if payload:
        text_input = payload.get("text")
        if text_input:
            media_bytes = text_input.encode("utf-8")

    session = workflow.retry_capture(
        owner_id=current_user.id,
        session_id=session_id,
        media_bytes=media_bytes,
        text_input=text_input,
    )
    return _session_to_response(session)


# --- Capture decision endpoints ---


@router.post(
    "/captures/{capture_id}/decisions",
    response_model=DecisionResponse,
)
def create_decision(
    capture_id: str,
    payload: DecisionRequest,
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> DecisionResponse:
    """Record a capture decision (edit/clarify/approve/defer/delete)."""
    corr = _correlation_id()
    idem_key = f"dec:{current_user.id}:{capture_id}:{payload.action}:{uuid.uuid4().hex[:8]}"

    if payload.action == "edit":
        if not payload.new_text:
            raise HTTPException(
                status_code=400, detail="new_text is required for edit action."
            )
        item, decision_id = workflow.edit_capture(
            owner_id=current_user.id,
            capture_id=capture_id,
            new_text=payload.new_text,
            actor_id=current_user.id,
            correlation_id=corr,
            idempotency_key=idem_key,
            expected_revision=payload.expected_revision,
        )
    elif payload.action == "clarify":
        if not payload.question:
            raise HTTPException(
                status_code=400, detail="question is required for clarify action."
            )
        item, decision_id = workflow.clarify_capture(
            owner_id=current_user.id,
            capture_id=capture_id,
            question=payload.question,
            answer=payload.answer,
            actor_id=current_user.id,
            correlation_id=corr,
            idempotency_key=idem_key,
            expected_revision=payload.expected_revision,
        )
    elif payload.action == "delete":
        item, decision_id = workflow.delete_capture(
            owner_id=current_user.id,
            capture_id=capture_id,
            actor_id=current_user.id,
            correlation_id=corr,
            idempotency_key=idem_key,
            expected_revision=payload.expected_revision,
            reason=payload.reason,
            avoidance_reason=payload.avoidance_reason,
        )
    elif payload.action in ("approve", "defer"):
        if payload.action == "approve":
            item, decision_id = workflow.approve_capture(
                owner_id=current_user.id,
                capture_id=capture_id,
                actor_id=current_user.id,
                correlation_id=corr,
                idempotency_key=idem_key,
                expected_revision=payload.expected_revision,
            )
        else:
            item, decision_id = workflow.defer_capture(
                owner_id=current_user.id,
                capture_id=capture_id,
                actor_id=current_user.id,
                correlation_id=corr,
                idempotency_key=idem_key,
                expected_revision=payload.expected_revision,
            )
    else:
        raise HTTPException(
            status_code=400, detail=f"Unknown action '{payload.action}'."
        )

    return DecisionResponse(
        item=_item_to_response(item),
        decision_id=decision_id,
    )


# --- Capture routing endpoints ---


@router.post(
    "/captures/{capture_id}/routes",
    response_model=RouteDetailResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_route(
    capture_id: str,
    payload: RouteRequest,
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> RouteDetailResponse:
    """Request routing of a capture to an external destination."""
    idem_key = f"route:{current_user.id}:{capture_id}:{payload.destination}:{uuid.uuid4().hex[:8]}"

    route, item = workflow.route_capture(
        owner_id=current_user.id,
        capture_id=capture_id,
        destination=payload.destination,
        actor_id=current_user.id,
        idempotency_key=idem_key,
    )

    return RouteDetailResponse(
        route=RouteResponse(
            id=route.id,
            atomic_capture_id=route.atomic_capture_id,
            destination=route.destination,
            status=route.status,
            external_ref=route.external_ref,
            attempt_count=route.attempt_count,
            last_error=(
                {
                    "code": route.last_error.code,
                    "retryable": route.last_error.retryable,
                }
                if route.last_error
                else None
            ),
            requested_at=route.requested_at,
            completed_at=route.completed_at,
            revision=route.revision,
        ),
        item=_item_to_response(item),
    )


# --- Capture results endpoint ---


@router.get("/captures/{capture_id}/results")
def get_capture_results(
    capture_id: str,
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> list[EvidenceResultResponse]:
    """Get evidence/results linked to a capture."""
    results = workflow.get_capture_results(
        owner_id=current_user.id,
        capture_id=capture_id,
    )
    return [
        EvidenceResultResponse(
            id=r.id,
            source=r.source,
            kind=r.kind,
            status=r.status,
            title=r.title,
            summary=r.summary,
            uri=r.uri,
            atomic_capture_ids=r.atomic_capture_ids,
            route_id=r.route_id,
            tree_id=r.tree_id,
            node_ids=r.node_ids,
            observed_at=r.observed_at,
            recorded_at=r.recorded_at,
        )
        for r in results
    ]


# --- Capture inbox endpoint ---


@router.get("/captures")
def list_captures(
    current_user: User = Depends(get_current_user),
    workflow: CaptureReviewWorkflow = Depends(_get_workflow),
) -> list[CaptureItemResponse]:
    """List the current user's open capture items (inbox)."""
    items = workflow.list_capture_items(owner_id=current_user.id)
    return [_item_to_response(item) for item in items]


__all__ = ["router"]
