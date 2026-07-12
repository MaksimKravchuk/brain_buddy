"""FastAPI routes for vNext capture/review/thinking/execution modules.

Implements ADR-0001 minimal HTTP API. All routes are under /api,
require the existing session cookie, and follow existing patterns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.api.dependencies import get_container, get_current_user
from app.container import Container
from app.exceptions import NotFoundError, ValidationFailure
from app.modules.capture.domain import AtomicCaptureSource, CaptureItem
from app.schemas.auth import User
from app.schemas.vnext import (
    CandidateCreateRequest,
    CaptureDecisionRequest,
    CaptureItemResponse,
    CaptureSessionCreateRequest,
    CaptureSessionDetailResponse,
    CaptureSessionResponse,
    CrtPromotionResponse,
    EvidenceResultCreateRequest,
    EvidenceResultResponse,
    ProblemCandidateResponse,
    ReviewOutcomeRequest,
    ReviewOutcomeResponse,
    ReviewSummaryResponse,
    WeeklyReviewDetailResponse,
    WeeklyReviewResponse,
)

router = APIRouter(tags=["vnext"])


def _item_to_response(
    source: AtomicCaptureSource, item: CaptureItem
) -> CaptureItemResponse:
    return CaptureItemResponse(
        id=item.id,
        source_capture_id=item.source_capture_id,
        current_text=item.current_text,
        review_state=item.review_state,
        kind=source.kind,
        source_text=source.source_text,
        created_at=item.created_at,
        updated_at=item.updated_at,
        revision=item.revision,
    )


def _get_capture_service(container: Container):
    return container.capture_service


# -- Capture endpoints --


@router.post(
    "/capture-sessions",
    response_model=CaptureSessionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_capture_session(
    payload: CaptureSessionCreateRequest,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> CaptureSessionDetailResponse:
    """Create a text capture session and split into atomic items."""
    session, items = container.capture_service.create_text_session(
        owner_id=current_user.id,
        text=payload.text,
    )
    captures = []
    for item in items:
        source, _ = container.capture_service.get_capture(
            current_user.id, item.id
        )
        captures.append(_item_to_response(source, item))

    return CaptureSessionDetailResponse(
        session=CaptureSessionResponse(
            id=session.id,
            status=session.status,
            input_kind=session.input_kind,
            atomic_capture_ids=session.atomic_capture_ids,
            created_at=session.created_at,
            updated_at=session.updated_at,
        ),
        captures=captures,
    )


@router.get(
    "/capture-sessions/{session_id}",
    response_model=CaptureSessionDetailResponse,
)
def get_capture_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> CaptureSessionDetailResponse:
    """Get a capture session with its items."""
    session = container.capture_service.get_session(
        current_user.id, session_id
    )
    captures = []
    for capture_id in session.atomic_capture_ids:
        source, item = container.capture_service.get_capture(
            current_user.id, capture_id
        )
        captures.append(_item_to_response(source, item))

    return CaptureSessionDetailResponse(
        session=CaptureSessionResponse(
            id=session.id,
            status=session.status,
            input_kind=session.input_kind,
            atomic_capture_ids=session.atomic_capture_ids,
            created_at=session.created_at,
            updated_at=session.updated_at,
        ),
        captures=captures,
    )


@router.get("/captures", response_model=list[CaptureItemResponse])
def list_captures(
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> list[CaptureItemResponse]:
    """List all capture items for the current user."""
    items = container.capture_service.list_items_for_owner(current_user.id)
    results = []
    for item in items:
        source, _ = container.capture_service.get_capture(
            current_user.id, item.id
        )
        results.append(_item_to_response(source, item))
    return results


@router.post(
    "/captures/{capture_id}/decisions",
    response_model=CaptureItemResponse,
)
def apply_capture_decision(
    capture_id: str,
    payload: CaptureDecisionRequest,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> CaptureItemResponse:
    """Apply a decision (edit/clarify/approve/defer/complete/delete) to a capture."""
    item = container.capture_service.apply_decision(
        current_user.id,
        capture_id,
        action=payload.action,
        new_text=payload.new_text,
        expected_revision=payload.expected_revision,
    )
    source, _ = container.capture_service.get_capture(
        current_user.id, capture_id
    )
    return _item_to_response(source, item)


@router.get(
    "/captures/{capture_id}/results",
    response_model=list[EvidenceResultResponse],
)
def get_capture_results(
    capture_id: str,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> list[EvidenceResultResponse]:
    """Get evidence/results linked to a capture."""
    results = container.execution_service.list_results_for_capture(
        current_user.id, capture_id
    )
    return [
        EvidenceResultResponse(
            id=r.id,
            source=r.source,
            kind=r.kind,
            title=r.title,
            summary=r.summary,
            uri=r.uri,
            atomic_capture_ids=r.atomic_capture_ids,
            tree_id=r.tree_id,
            observed_at=r.observed_at,
            recorded_at=r.recorded_at,
        )
        for r in results
    ]


# -- Weekly Review endpoints --


@router.post(
    "/weekly-reviews",
    response_model=WeeklyReviewDetailResponse,
)
def start_weekly_review(
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> WeeklyReviewDetailResponse:
    """Start or resume a Weekly Review."""
    eligible = container.capture_service.list_eligible_for_review(
        current_user.id
    )
    review = container.review_service.start_or_resume_review(
        owner_id=current_user.id,
        eligible_items=[item.id for item in eligible],
    )
    # Build item responses from eligible items
    items = []
    for item in eligible:
        source, _ = container.capture_service.get_capture(
            current_user.id, item.id
        )
        items.append(_item_to_response(source, item))
    return _build_review_detail(review, items, container, current_user.id)


@router.get(
    "/weekly-reviews/{review_id}",
    response_model=WeeklyReviewDetailResponse,
)
def get_weekly_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> WeeklyReviewDetailResponse:
    """Get a Weekly Review with items and outcomes."""
    review = container.review_service.get_review(current_user.id, review_id)
    items = []
    for capture_id in review.item_ids:
        try:
            item = container.capture_service.get_item(
                current_user.id, capture_id
            )
            source, _ = container.capture_service.get_capture(
                current_user.id, capture_id
            )
            items.append(_item_to_response(source, item))
        except NotFoundError:
            # Item may have been hard-deleted; skip.
            pass
    return _build_review_detail(review, items, container, current_user.id)


@router.get("/weekly-reviews", response_model=list[WeeklyReviewResponse])
def list_weekly_reviews(
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> list[WeeklyReviewResponse]:
    """List all weekly reviews for the current user."""
    reviews = container.review_service.list_reviews_for_owner(current_user.id)
    return [_review_to_response(r) for r in reviews]


@router.post(
    "/weekly-reviews/{review_id}/items/{capture_id}/outcomes",
    response_model=ReviewOutcomeResponse,
)
def record_review_outcome(
    review_id: str,
    capture_id: str,
    payload: ReviewOutcomeRequest,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> ReviewOutcomeResponse:
    """Record a per-item outcome in a Weekly Review.

    Per ADR-0001, the outcome composes Organize commands:
    - keep: approves the item without a destination
    - edit: updates text and then approves it
    - delete: deletes the item
    - defer: defers the item
    - route: approves and requests the selected destination (MVP: no-op)
    - promote_to_crt: approves, creates/uses a candidate, and requests promotion
    """
    # Apply the underlying capture decision first.
    organize_decision_id: str | None = None
    promotion_id: str | None = None

    if payload.action == "keep":
        container.capture_service.apply_decision(
            current_user.id, capture_id, action="approve"
        )
    elif payload.action == "edit":
        if not payload.new_text:
            raise ValidationFailure(
                "edit action requires new_text.",
                detail={"reason": "missing_new_text"},
            )
        container.capture_service.apply_decision(
            current_user.id,
            capture_id,
            action="edit",
            new_text=payload.new_text,
        )
    elif payload.action == "delete":
        container.capture_service.apply_decision(
            current_user.id,
            capture_id,
            action="delete",
        )
    elif payload.action == "defer":
        container.capture_service.apply_decision(
            current_user.id, capture_id, action="defer"
        )
    elif payload.action == "route":
        # MVP: no external task tracker configured. Approve only.
        container.capture_service.apply_decision(
            current_user.id, capture_id, action="approve"
        )
    elif payload.action == "promote_to_crt":
        container.capture_service.apply_decision(
            current_user.id, capture_id, action="approve"
        )
        # Create a candidate and request promotion.
        item = container.capture_service.get_item(current_user.id, capture_id)
        source, _ = container.capture_service.get_capture(
            current_user.id, capture_id
        )
        candidate = container.thinking_service.create_candidate(
            owner_id=current_user.id,
            title=item.current_text,
            context=source.source_text,
            source_capture_ids=[capture_id],
            signal="manual",
            signal_reasons=["weekly_review_promotion"],
        )
        promotion = container.thinking_service.request_promotion(
            current_user.id, candidate.id
        )
        promotion_id = promotion.id

    outcome = container.review_service.record_outcome(
        owner_id=current_user.id,
        review_id=review_id,
        capture_id=capture_id,
        action=payload.action,
        reason=payload.reason,
        avoidance_reason=payload.avoidance_reason,
        organize_decision_id=organize_decision_id,
        promotion_id=promotion_id,
    )

    return ReviewOutcomeResponse(
        id=outcome.id,
        weekly_review_id=outcome.weekly_review_id,
        atomic_capture_id=outcome.atomic_capture_id,
        action=outcome.action,
        reason=outcome.reason,
        avoidance_reason=outcome.avoidance_reason,
        decided_at=outcome.decided_at,
    )


@router.post(
    "/weekly-reviews/{review_id}/complete",
    response_model=ReviewSummaryResponse,
)
def complete_weekly_review(
    review_id: str,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> ReviewSummaryResponse:
    """Validate coverage and complete a Weekly Review."""
    summary = container.review_service.complete_review(
        owner_id=current_user.id,
        review_id=review_id,
    )
    return ReviewSummaryResponse(
        review_id=summary.review_id,
        total_items=summary.total_items,
        kept=summary.kept,
        edited=summary.edited,
        deferred=summary.deferred,
        deleted=summary.deleted,
        routed=summary.routed,
        promoted=summary.promoted,
        completed_at=summary.completed_at,
    )


# -- Problem Candidate / CRT endpoints --


@router.post(
    "/problem-candidates",
    response_model=ProblemCandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_candidate(
    payload: CandidateCreateRequest,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> ProblemCandidateResponse:
    """Create a problem candidate manually."""
    candidate = container.thinking_service.create_candidate(
        owner_id=current_user.id,
        title=payload.title,
        context=payload.context,
        source_capture_ids=payload.source_capture_ids,
        signal=payload.signal,
        signal_reasons=payload.signal_reasons,
    )
    return _candidate_to_response(candidate)


@router.get(
    "/problem-candidates",
    response_model=list[ProblemCandidateResponse],
)
def list_candidates(
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> list[ProblemCandidateResponse]:
    """List problem candidates for the current user."""
    candidates = container.thinking_service.list_candidates_for_owner(
        current_user.id
    )
    return [_candidate_to_response(c) for c in candidates]


@router.post(
    "/problem-candidates/{candidate_id}/promotions",
    response_model=CrtPromotionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_promotion(
    candidate_id: str,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> CrtPromotionResponse:
    """Request CRT promotion for a problem candidate."""
    promotion = container.thinking_service.request_promotion(
        current_user.id, candidate_id
    )
    return CrtPromotionResponse(
        id=promotion.id,
        problem_candidate_id=promotion.problem_candidate_id,
        status=promotion.status,
        tree_id=promotion.tree_id,
        root_node_id=promotion.root_node_id,
        source_capture_ids=promotion.source_capture_ids,
        requested_at=promotion.requested_at,
        completed_at=promotion.completed_at,
    )


# -- Evidence/Result endpoints --


@router.post(
    "/results",
    response_model=EvidenceResultResponse,
    status_code=status.HTTP_201_CREATED,
)
def record_result(
    payload: EvidenceResultCreateRequest,
    current_user: User = Depends(get_current_user),
    container: Container = Depends(get_container),
) -> EvidenceResultResponse:
    """Manually record a linked evidence/result."""
    result = container.execution_service.record_result(
        owner_id=current_user.id,
        source=payload.source,
        kind=payload.kind,
        title=payload.title,
        summary=payload.summary,
        uri=payload.uri,
        atomic_capture_ids=payload.atomic_capture_ids,
        tree_id=payload.tree_id,
    )
    return EvidenceResultResponse(
        id=result.id,
        source=result.source,
        kind=result.kind,
        title=result.title,
        summary=result.summary,
        uri=result.uri,
        atomic_capture_ids=result.atomic_capture_ids,
        tree_id=result.tree_id,
        observed_at=result.observed_at,
        recorded_at=result.recorded_at,
    )


# -- Helpers --


def _review_to_response(review) -> WeeklyReviewResponse:
    return WeeklyReviewResponse(
        id=review.id,
        status=review.status,
        period_start=review.period_start,
        period_end=review.period_end,
        item_ids=review.item_ids,
        outcome_count=len(review.outcomes),
        started_at=review.started_at,
        completed_at=review.completed_at,
    )


def _build_review_detail(review, items, container, owner_id) -> WeeklyReviewDetailResponse:
    outcomes = [
        {
            "id": o.id,
            "atomic_capture_id": o.atomic_capture_id,
            "action": o.action,
            "reason": o.reason,
            "avoidance_reason": o.avoidance_reason,
            "decided_at": o.decided_at.isoformat(),
        }
        for o in review.outcomes
    ]
    return WeeklyReviewDetailResponse(
        review=_review_to_response(review),
        items=items,
        outcomes=outcomes,
    )


def _candidate_to_response(candidate) -> ProblemCandidateResponse:
    return ProblemCandidateResponse(
        id=candidate.id,
        source_capture_ids=candidate.source_capture_ids,
        title=candidate.title,
        context=candidate.context,
        signal=candidate.signal,
        signal_reasons=candidate.signal_reasons,
        status=candidate.status,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )
