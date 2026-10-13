"""Review result → public response mapping, free of the web framework.

Shared by the Review routers and the device command executor, so a device
receipt has exactly the REST body's shape (spec 026 PR-31).
"""

from __future__ import annotations

from app.api.task_mapping import task_response
from app.modules.tasks.domain import FormulationSettingsDocument, TaskDocument
from app.modules.tasks.review_domain import (
    AutoParkResultDocument,
    DecisionResultDocument,
    ReviewReceiptDocument,
    UndoResultDocument,
)
from app.modules.tasks.review_service import ReviewService
from app.schemas.review import (
    AutoParkResponse,
    DecisionRecordResponse,
    DecisionResponse,
    ReviewReceiptResponse,
    SessionCounts,
    UndoDecisionResponse,
)
from app.schemas.tasks import TaskResponse


def receipt_response(receipt: ReviewReceiptDocument) -> ReviewReceiptResponse:
    return ReviewReceiptResponse(
        task_id=receipt.task_id,
        kind=receipt.kind,
        hidden_until=receipt.hidden_until,
        task_revision=receipt.task_revision,
    )


def tasks_with_formulation(
    review_service: ReviewService,
    owner_id: str,
    settings: FormulationSettingsDocument | None,
    *tasks: TaskDocument | None,
) -> list[TaskResponse | None]:
    """Map tasks with one settings read for all of them (http §2).

    ``settings`` is the stored result's snapshot, so a same-key replay returns
    the original projection (http "Mutations"); ``None`` reads live settings.
    """

    present = [task for task in tasks if task is not None]
    views = review_service.formulation_views(owner_id, present, settings=settings)
    return [
        None if task is None else task_response(task, formulation=views.get(task.id))
        for task in tasks
    ]


def decision_response(
    result: DecisionResultDocument, review_service: ReviewService, owner_id: str
) -> DecisionResponse:
    decision = result.decision
    task, created = tasks_with_formulation(
        review_service,
        owner_id,
        result.formulation_settings,
        result.task,
        result.created_task,
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


def undo_response(
    result: UndoResultDocument, review_service: ReviewService, owner_id: str
) -> UndoDecisionResponse:
    (task,) = tasks_with_formulation(
        review_service, owner_id, result.formulation_settings, result.task
    )
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


def auto_park_response(
    result: AutoParkResultDocument, review_service: ReviewService, owner_id: str
) -> AutoParkResponse:
    (task,) = tasks_with_formulation(
        review_service, owner_id, result.formulation_settings, result.task
    )
    assert task is not None
    return AutoParkResponse(applied=result.applied, task=task)
