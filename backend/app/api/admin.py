"""Minimum admin portal routes: exact account lookup and session revoke.

Every route requires `require_admin_portal_enabled`, which composes
`require_operator` — a valid session AND allow-list membership — checked
before any account lookup or mutation runs, so a denial never varies with
whether the target account exists (009-FR-002). Authorization is evaluated
*before* the default-OFF `admin_portal` rollout flag: with the flag OFF an
unauthenticated caller still gets 401 and a non-operator still gets 403, and
only an allow-listed operator sees the fail-closed 404 (009-FR-013).
The mutation relies on the repository's existing `SameSite=Lax`
session-cookie posture like every other mutating route (009-FR-009); no
additional origin check is added.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.admin import (
    AdminAccountLookupRequest,
    AdminAccountResponse,
    AdminRevokeSessionsResponse,
    AdminStatusResponse,
)
from app.schemas.auth import User
from app.services import AdminService

from .contracts import error_responses
from .dependencies import get_admin_service, require_admin_portal_enabled

router = APIRouter(tags=["admin"])


def _account_response(user: User) -> AdminAccountResponse:
    return AdminAccountResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        deletion_requested=user.deletion_requested_at is not None,
    )


@router.get(
    "/status",
    response_model=AdminStatusResponse,
    responses=error_responses(401, 403, 404),
)
def admin_status(
    _operator: User = Depends(require_admin_portal_enabled),
) -> AdminStatusResponse:
    """Server-issued operator capability check for the frontend (009-FR-002).

    Kept off the shared signup/login/me payload so a non-operator's response
    shape never signals the allow-list's existence; a caller only ever learns
    `is_operator` by reaching this route, which itself requires being one.
    """

    return AdminStatusResponse(is_operator=True)


@router.post(
    "/accounts/lookup",
    response_model=AdminAccountResponse,
    responses=error_responses(401, 403, 404, 422),
)
def lookup_account(
    payload: AdminAccountLookupRequest,
    operator: User = Depends(require_admin_portal_enabled),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountResponse:
    user = admin_service.find_account(
        operator_id=operator.id, account_id=payload.account_id, email=payload.email
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No account found."
        )
    return _account_response(user)


@router.post(
    "/accounts/{account_id}/revoke-sessions",
    response_model=AdminRevokeSessionsResponse,
    responses=error_responses(401, 403, 404, 422),
)
def revoke_sessions(
    account_id: str,
    operator: User = Depends(require_admin_portal_enabled),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminRevokeSessionsResponse:
    revoked = admin_service.revoke_sessions(
        operator_id=operator.id, account_id=account_id
    )
    return AdminRevokeSessionsResponse(revoked_count=revoked)


__all__ = ["router"]
