"""HTTP routes of the guided review flow (spec 020, contracts/http.md §6).

Thin routes over ``ReviewFlowService`` (``Depends()``). The exposure reads
(``GET /review/sessions/{id}``, ``GET /review/queues/{step}``) depend on
``require_weekly_review_enabled``; the writes that finish a run a client
already started, and bulk releases, depend on ``get_current_user`` alone, so a
device's queued review never fails while the flag is off (http "Gate").
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_current_user,
    get_review_flow_service,
    get_review_service,
    require_weekly_review_enabled,
)
from app.api.middleware import CORRELATION_HEADER
from app.api.review import (
    require_idempotency_key,
    session_response,
    tasks_with_formulation,
)
from app.modules.tasks.review_domain import ReviewBulkReleaseDocument
from app.modules.tasks.review_flow import (
    OpenSessionExistsError,
    QueueView,
    ReviewFlowService,
    StepOutsideRunError,
)
from app.modules.tasks.review_service import ReviewService
from app.schemas.api import ErrorResponse
from app.schemas.auth import User
from app.schemas.review import (
    BulkReleaseRef,
    BulkReleaseRequest,
    BulkReleaseResponse,
    BulkReleaseUndoResponse,
    DatesQueueMeta,
    DecisionsQueueMeta,
    EmptyQueueMeta,
    QueueResponse,
    RestOfNextQueueMeta,
    SessionFinishRequest,
    SessionProgressRequest,
    SessionRef,
    SessionResponse,
    SessionStartRequest,
    SomedayQueueMeta,
    StepCode,
    WinsQueueMeta,
)

router = APIRouter(tags=["review"])


def _open_session_conflict(
    request: Request, exc: OpenSessionExistsError
) -> JSONResponse:
    """409 ``open_session_exists`` naming the open run (http §6)."""

    correlation_id = getattr(request.state, "correlation_id", None)
    payload = ErrorResponse(
        message=exc.message,
        detail={"reason": exc.reason, "session_id": exc.session_id},
        reference_id=correlation_id,
    )
    response = JSONResponse(
        status_code=exc.status_code, content=payload.model_dump(by_alias=True)
    )
    if correlation_id:
        response.headers[CORRELATION_HEADER] = correlation_id
    return response


def _queue_meta(
    view: QueueView,
) -> (
    WinsQueueMeta
    | RestOfNextQueueMeta
    | SomedayQueueMeta
    | DatesQueueMeta
    | DecisionsQueueMeta
    | EmptyQueueMeta
):
    meta: dict[str, Any] = view.meta
    if view.step == "wins":
        return WinsQueueMeta.model_validate(meta)
    if view.step == "rest_of_next":
        return RestOfNextQueueMeta.model_validate(meta)
    if view.step == "someday":
        return SomedayQueueMeta.model_validate(meta)
    if view.step == "dates":
        return DatesQueueMeta.model_validate(meta)
    if view.step == "decisions":
        return DecisionsQueueMeta.model_validate(meta)
    return EmptyQueueMeta()


def _bulk_response(release: ReviewBulkReleaseDocument) -> BulkReleaseResponse:
    return BulkReleaseResponse.model_validate(
        {
            "id": release.id,
            "released": [
                {"task_id": item.task_id, "revision_after": item.revision_after}
                for item in release.released
            ],
            "skipped": [
                {"task_id": item.task_id, "reason": item.reason}
                for item in release.skipped
            ],
        }
    )


@router.post(
    "/review/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 409, 422),
)
def start_review_session(
    request: Request,
    payload: SessionStartRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    flow: ReviewFlowService = Depends(get_review_flow_service),
) -> SessionResponse | JSONResponse:
    """Start a quick or full review at any time (FR-027); not gated."""

    try:
        session = flow.start_session(
            payload,
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    except OpenSessionExistsError as exc:
        return _open_session_conflict(request, exc)
    return session_response(session)


@router.get(
    "/review/sessions/{session_id}",
    response_model=SessionResponse,
    responses=error_responses(401, 404, 422),
)
def get_review_session(
    session_id: SessionRef,
    current_user: User = Depends(require_weekly_review_enabled),
    flow: ReviewFlowService = Depends(get_review_flow_service),
) -> SessionResponse:
    return session_response(flow.get_session(session_id, owner_id=current_user.id))


@router.patch(
    "/review/sessions/{session_id}",
    response_model=SessionResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def progress_review_session(
    session_id: SessionRef,
    payload: SessionProgressRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    flow: ReviewFlowService = Depends(get_review_flow_service),
) -> SessionResponse:
    """Merged progress, replay-safe by ``progress_id`` (http §6); not gated.

    A step code outside the run's mode is 422 with the same envelope as a
    schema validation failure (``loc`` ``["body", field, "code"]``).
    """

    try:
        session = flow.progress_session(
            session_id,
            payload,
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    except StepOutsideRunError as exc:
        raise RequestValidationError(
            [
                {
                    "type": "step_outside_run",
                    "loc": ("body", exc.field, "code"),
                    "msg": "The step is not part of this review's mode.",
                }
            ]
        ) from exc
    return session_response(session)


@router.post(
    "/review/sessions/{session_id}/finish",
    response_model=SessionResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def finish_review_session(
    session_id: SessionRef,
    payload: SessionFinishRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    flow: ReviewFlowService = Depends(get_review_flow_service),
) -> SessionResponse:
    """Done on the summary (FR-029); idempotent; not gated."""

    return session_response(
        flow.finish_session(
            session_id,
            payload or SessionFinishRequest(),
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    )


@router.get(
    "/review/queues/{step}",
    response_model=QueueResponse,
    responses=error_responses(401, 404, 422),
)
def get_review_queue(
    step: StepCode,
    session_id: SessionRef | None = Query(default=None),
    current_user: User = Depends(require_weekly_review_enabled),
    flow: ReviewFlowService = Depends(get_review_flow_service),
    review_service: ReviewService = Depends(get_review_service),
) -> QueueResponse:
    """One step's items in order, with its meta (http §6).

    ``session_id`` is a ``SessionRef`` (http "Client-supplied ids"): any other
    shape is 422 before a lookup, so no free text reaches a query or a log.
    """

    view = flow.queue(step, owner_id=current_user.id, session_id=session_id)
    items = tasks_with_formulation(review_service, current_user.id, None, *view.items)
    return QueueResponse(
        items=[item for item in items if item is not None], meta=_queue_meta(view)
    )


@router.post(
    "/review/bulk-releases",
    response_model=BulkReleaseResponse,
    responses=error_responses(400, 401, 409, 422),
)
def bulk_release(
    payload: BulkReleaseRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    flow: ReviewFlowService = Depends(get_review_flow_service),
) -> BulkReleaseResponse:
    """Restart (FR-017) or Inbox-remainder (FR-030) release; partial is 200."""

    return _bulk_response(
        flow.bulk_release(
            payload,
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    )


@router.post(
    "/review/bulk-releases/{bulk_id}/undo",
    response_model=BulkReleaseUndoResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def undo_bulk_release(
    bulk_id: BulkReleaseRef,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    flow: ReviewFlowService = Depends(get_review_flow_service),
) -> BulkReleaseUndoResponse:
    """Clock-exact Undo; an already undone release answers its stored result."""

    return BulkReleaseUndoResponse.model_validate(
        flow.undo_bulk_release(
            bulk_id,
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    )
