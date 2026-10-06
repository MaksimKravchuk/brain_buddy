"""HTTP routes of the weekly review (spec 020, contracts/http.md §3 – §5).

Thin routes: every one gets ``ReviewService`` through ``Depends()`` and maps
its result. Only the exposure reads depend on
``require_weekly_review_enabled``; the writes that finish work a client already
started depend on ``get_current_user`` alone (http "Gate").
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, FastAPI, Header, Request, status
from fastapi.responses import JSONResponse

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_current_user,
    get_feature_flag_service,
    get_review_service,
    require_weekly_review_enabled,
    weekly_review_enabled,
)
from app.api.middleware import CORRELATION_HEADER
from app.api.task_mapping import task_response
from app.exceptions import ValidationFailure
from app.modules.tasks.domain import TaskDocument
from app.modules.tasks.review_domain import (
    DecisionResultDocument,
    ReviewReceiptDocument,
    ReviewRequestError,
    ReviewSessionDocument,
    ReviewSettingsDocument,
)
from app.modules.tasks.review_service import ReviewService, ReviewStateView
from app.schemas.api import ErrorResponse
from app.schemas.auth import User
from app.schemas.review import (
    AutoParkRequest,
    AutoParkResponse,
    DecisionRecordResponse,
    DecisionRequest,
    DecisionResponse,
    ExplainerAcknowledgeRequest,
    LastCountedReviewResponse,
    ParkAcknowledgeRequest,
    ReviewReceiptResponse,
    ReviewSettingsResponse,
    ReviewSettingsUpdateRequest,
    ReviewStateCounts,
    ReviewStateResponse,
    SessionCounts,
    SessionResponse,
    UndoDecisionRequest,
    UndoDecisionResponse,
    UnseenParkResponse,
)
from app.schemas.tasks import TaskResponse
from app.services import FeatureFlagService

router = APIRouter(tags=["review"])


# ----------------------------------------------------------------- errors
def register_review_exception_handlers(app: FastAPI) -> None:
    """Render ``ReviewRequestError`` as the standard envelope with a reason."""

    @app.exception_handler(ReviewRequestError)
    async def handle_review_request_error(
        request: Request, exc: ReviewRequestError
    ) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        payload = ErrorResponse(
            message=exc.message,
            detail={"reason": exc.reason},
            reference_id=correlation_id,
        )
        response = JSONResponse(
            status_code=exc.status_code, content=payload.model_dump(by_alias=True)
        )
        if correlation_id:
            response.headers[CORRELATION_HEADER] = correlation_id
        return response


# ----------------------------------------------------------------- mapping
def settings_response(settings: ReviewSettingsDocument) -> ReviewSettingsResponse:
    return ReviewSettingsResponse(
        threshold_days=settings.threshold_days,
        review_weekday=settings.review_weekday,
        review_time=settings.review_time,
        time_zone=settings.time_zone,
        onboarded_at=settings.onboarded_at,
        activated_at=settings.activated_at,
        owner_park_floor_at=settings.owner_park_floor_at,
        revision=settings.revision,
    )


def session_response(session: ReviewSessionDocument) -> SessionResponse:
    """The exact http §6 wire subset of a stored session."""

    return SessionResponse.model_validate(
        {
            "id": session.id,
            "mode": session.mode,
            "entry": session.entry,
            "origin": session.origin,
            "status": session.status,
            "started_at": session.started_at,
            "last_activity_at": session.last_activity_at,
            "ended_at": session.ended_at,
            "current_step": session.current_step,
            "steps": {code: step.status for code, step in session.steps.items()},
            "active_seconds_by_step": session.active_seconds_by_step,
            "counts": session.counts.model_dump(),
            "set_aside_count": len(session.set_aside_task_ids),
            "qualifying_activity": session.qualifying_activity,
            "clear_start": session.clear_start,
            "revision": session.revision,
        }
    )


def receipt_response(receipt: ReviewReceiptDocument) -> ReviewReceiptResponse:
    return ReviewReceiptResponse(
        task_id=receipt.task_id,
        kind=receipt.kind,
        hidden_until=receipt.hidden_until,
        task_revision=receipt.task_revision,
    )


def state_response(state: ReviewStateView) -> ReviewStateResponse:
    last = state.last_counted_review
    return ReviewStateResponse(
        settings=settings_response(state.settings),
        explainer_seen=state.explainer_seen,
        grace_until=state.grace_until,
        last_counted_review_at=state.last_counted_review_at,
        last_counted_review=(
            None
            if last is None
            else LastCountedReviewResponse.model_validate(
                {
                    "session_id": last.id,
                    "status": last.status,
                    "origin": last.origin,
                    "ended_at": last.ended_at,
                    "counts": last.counts.model_dump(),
                    "clear_start": last.clear_start,
                }
            )
        ),
        next_review_at=state.next_review_at,
        restart_mode=state.restart_mode,
        open_session=(
            None if state.open_session is None else session_response(state.open_session)
        ),
        unseen_parks=[
            UnseenParkResponse(
                task_id=park.task_id,
                formulation_id=park.formulation_id,
                parked_at=park.parked_at,
            )
            for park in state.unseen_parks
        ],
        counts=ReviewStateCounts(
            asks_for_decision=state.asks_for_decision,
            moves_tomorrow=state.moves_tomorrow,
        ),
        receipts=[receipt_response(receipt) for receipt in state.receipts],
        server_now=state.server_now,
    )


def require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise ValidationFailure("Idempotency-Key header is required.")
    return idempotency_key


def tasks_with_formulation(
    review_service: ReviewService, owner_id: str, *tasks: TaskDocument | None
) -> list[TaskResponse | None]:
    """Map tasks with one settings read for all of them (http §2)."""

    present = [task for task in tasks if task is not None]
    views = review_service.formulation_views(owner_id, present)
    return [
        None if task is None else task_response(task, formulation=views.get(task.id))
        for task in tasks
    ]


def decision_response(
    result: DecisionResultDocument, review_service: ReviewService, owner_id: str
) -> DecisionResponse:
    decision = result.decision
    task, created = tasks_with_formulation(
        review_service, owner_id, result.task, result.created_task
    )
    assert task is not None
    return DecisionResponse(
        decision=DecisionRecordResponse(
            id=decision.id,
            type=decision.type,
            task_id=decision.task_id,
            session_id=decision.session_id,
            decided_at=decision.decided_at,
            substantive=decision.substantive,
            stall_reason=decision.stall_reason,
            ai_use=decision.ai_use,
            yielded_auto_park=decision.yielded_auto_park,
        ),
        task=task,
        created_task=created,
        receipt=None if result.receipt is None else receipt_response(result.receipt),
        session_counts=(
            None
            if result.session_counts is None
            else SessionCounts.model_validate(result.session_counts.model_dump())
        ),
    )


# ----------------------------------------------------------------- routes
@router.post(
    "/tasks/{task_id}/decisions",
    response_model=DecisionResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def decide_task(
    task_id: str,
    payload: DecisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    review_service: ReviewService = Depends(get_review_service),
) -> DecisionResponse:
    """A decision card choice (http §3); not gated, so queued work never fails."""

    result = review_service.decide(
        task_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=require_idempotency_key(idempotency_key),
    )
    return decision_response(result, review_service, current_user.id)


@router.post(
    "/review/decisions/{decision_id}/undo",
    response_model=UndoDecisionResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def undo_decision(
    decision_id: str,
    payload: UndoDecisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    review_service: ReviewService = Depends(get_review_service),
) -> UndoDecisionResponse:
    """Undo a decision while nothing changed since (FR-048)."""

    result = review_service.undo_decision(
        decision_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=require_idempotency_key(idempotency_key),
    )
    (task,) = tasks_with_formulation(review_service, current_user.id, result.task)
    assert task is not None
    return UndoDecisionResponse(
        task=task,
        undone_decision_id=result.undone_decision_id,
        deleted_task_id=result.deleted_task_id,
        session_counts=(
            None
            if result.session_counts is None
            else SessionCounts.model_validate(result.session_counts.model_dump())
        ),
    )


@router.post(
    "/tasks/{task_id}/auto-park",
    response_model=AutoParkResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def auto_park_task(
    task_id: str,
    payload: AutoParkRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
    review_service: ReviewService = Depends(get_review_service),
) -> AutoParkResponse:
    """A park a device observed (http §4); ``applied: false`` while the flag is off."""

    result = review_service.auto_park(
        task_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=require_idempotency_key(idempotency_key),
        exposed=weekly_review_enabled(current_user, feature_flags),
    )
    (task,) = tasks_with_formulation(review_service, current_user.id, result.task)
    assert task is not None
    return AutoParkResponse(applied=result.applied, task=task)


@router.post(
    "/review/parks/acknowledge",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 409, 422),
)
def acknowledge_parks(
    payload: ParkAcknowledgeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    review_service: ReviewService = Depends(get_review_service),
) -> None:
    """Mark parks seen ("Continue" on While you were away, FR-015); not gated."""

    review_service.acknowledge_parks(
        payload,
        owner_id=current_user.id,
        idempotency_key=require_idempotency_key(idempotency_key),
    )


@router.put(
    "/review/settings",
    response_model=ReviewSettingsResponse,
    responses=error_responses(400, 401, 409, 422),
)
def update_review_settings(
    payload: ReviewSettingsUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewSettingsResponse:
    """Threshold, schedule, time zone and onboarding (http §5); not gated."""

    return settings_response(
        review_service.update_settings(
            payload,
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/review/explainer/acknowledge",
    response_model=ReviewStateResponse,
    responses=error_responses(400, 401, 409, 422),
)
def acknowledge_explainer(
    payload: ExplainerAcknowledgeRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewStateResponse:
    """The only way an owner becomes activated (FR-051); not gated."""

    review_service.acknowledge_explainer(
        payload,
        owner_id=current_user.id,
        idempotency_key=require_idempotency_key(idempotency_key),
    )
    return state_response(review_service.state(owner_id=current_user.id))


@router.get(
    "/review/state",
    response_model=ReviewStateResponse,
    responses=error_responses(401, 404),
)
def get_review_state(
    current_user: User = Depends(require_weekly_review_enabled),
    review_service: ReviewService = Depends(get_review_service),
) -> ReviewStateResponse:
    return state_response(review_service.state(owner_id=current_user.id))
