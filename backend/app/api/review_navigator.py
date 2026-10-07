"""HTTP routes of the review navigator (spec 020, contracts/http.md §7).

Thin routes over ``NavigatorService`` (``Depends(get_navigator_service)``).
The status read and the consent revoke are privacy authority and depend on
``get_current_user`` alone, so a stored cloud consent can always be seen and
revoked, also while ``weekly_review`` is off (FR-024). The consent grant and
the suggestions are exposure and depend on ``require_weekly_review_enabled``.

The suggestions route is read-like: no ``Idempotency-Key``, no idempotency
record, nothing persisted but the content-free usage counters (navigator §6).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_container,
    get_current_user,
    require_weekly_review_enabled,
)
from app.api.middleware import CORRELATION_HEADER
from app.api.review import require_idempotency_key
from app.container import Container
from app.modules.tasks.navigator import (
    NavigatorRateLimited,
    NavigatorService,
    NavigatorStatus,
)
from app.schemas.api import ErrorResponse
from app.schemas.auth import User
from app.schemas.review import (
    NavigatorConsentGrantRequest,
    NavigatorConsentResponse,
    NavigatorStatusResponse,
    NavigatorSuggestionRequest,
    NavigatorSuggestionResponse,
)

router = APIRouter(tags=["review"])


def get_navigator_service(
    container: Container = Depends(get_container),
) -> NavigatorService:
    """The container's one ``NavigatorService`` (routes never build services)."""

    return container.navigator_service


def status_response(navigator: NavigatorStatus) -> NavigatorStatusResponse:
    consent = navigator.consent
    return NavigatorStatusResponse.model_validate(
        {
            "provider": navigator.provider,
            "consent": (
                None
                if consent is None
                else NavigatorConsentResponse(
                    granted_at=consent.granted_at,
                    revoked_at=consent.revoked_at,
                    consent_text_version=consent.consent_text_version,
                )
            ),
            "consent_current": navigator.consent_current,
            "consent_text_version": navigator.consent_text_version,
            "available": navigator.available,
        }
    )


def rate_limited_response(request: Request, exc: NavigatorRateLimited) -> JSONResponse:
    """429 in the standard envelope, plus ``Retry-After`` (http §7)."""

    correlation_id = getattr(request.state, "correlation_id", None)
    payload = ErrorResponse(
        message=exc.message, detail={"reason": exc.reason}, reference_id=correlation_id
    )
    response = JSONResponse(
        status_code=exc.status_code,
        content=payload.model_dump(by_alias=True),
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )
    if correlation_id:
        response.headers[CORRELATION_HEADER] = correlation_id
    return response


@router.get(
    "/review/navigator",
    response_model=NavigatorStatusResponse,
    responses=error_responses(401),
)
def get_navigator_status(
    current_user: User = Depends(get_current_user),
    navigator: NavigatorService = Depends(get_navigator_service),
) -> NavigatorStatusResponse:
    """Provider, consent and availability; never gated (privacy authority)."""

    return status_response(navigator.status(current_user.id))


@router.post(
    "/review/navigator/consent",
    response_model=NavigatorStatusResponse,
    responses=error_responses(400, 401, 404, 422),
)
def grant_navigator_consent(
    payload: NavigatorConsentGrantRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_weekly_review_enabled),
    navigator: NavigatorService = Depends(get_navigator_service),
) -> NavigatorStatusResponse:
    """One-time cloud consent (FR-024); the key replays for 24 h."""

    return status_response(
        navigator.grant_consent(
            payload,
            owner_id=current_user.id,
            idempotency_key=require_idempotency_key(idempotency_key),
        )
    )


@router.delete(
    "/review/navigator/consent",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 422),
)
def revoke_navigator_consent(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    navigator: NavigatorService = Depends(get_navigator_service),
) -> None:
    """Revoke at once for every later request; never gated (FR-024).

    The key replays for 24 h, so a late retry never revokes a newer grant.
    """

    navigator.revoke_consent(
        owner_id=current_user.id,
        idempotency_key=require_idempotency_key(idempotency_key),
    )


@router.post(
    "/review/navigator/suggestions",
    response_model=NavigatorSuggestionResponse,
    responses=error_responses(400, 401, 404, 422, 429, 503),
)
def suggest_next_steps(
    payload: NavigatorSuggestionRequest,
    request: Request,
    current_user: User = Depends(require_weekly_review_enabled),
    navigator: NavigatorService = Depends(get_navigator_service),
) -> NavigatorSuggestionResponse | JSONResponse:
    """1–3 grounded proposals or one clarifying question (FR-019 – FR-021)."""

    try:
        suggestion = navigator.suggest(current_user.id, payload)
    except NavigatorRateLimited as exc:
        return rate_limited_response(request, exc)
    return NavigatorSuggestionResponse(
        request_id=suggestion.request_id,
        provider=suggestion.provider,
        notes_truncated=suggestion.notes_truncated,
        proposals=(
            None if suggestion.proposals is None else list(suggestion.proposals)
        ),
        clarifying_question=suggestion.clarifying_question,
    )
