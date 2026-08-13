"""Minimum admin portal routes: exact account lookup and session revoke.

Every route requires `require_operator` — a valid session AND allow-list
membership — checked before any account lookup or mutation runs, so a
denial never varies with whether the target account exists (009-FR-002).
The mutation additionally requires `require_same_origin`, an explicit check
on top of the repository's existing `SameSite=Lax` session-cookie posture
(009-FR-009).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.admin import (
    AdminAccountLookupRequest,
    AdminAccountResponse,
    AdminRevokeSessionsResponse,
)
from app.schemas.auth import User
from app.services import AdminService

from .contracts import error_responses
from .dependencies import get_admin_service, require_operator, require_same_origin

router = APIRouter(tags=["admin"])


def _account_response(user: User) -> AdminAccountResponse:
    return AdminAccountResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        deletion_requested=user.deletion_requested_at is not None,
    )


@router.post(
    "/accounts/lookup",
    response_model=AdminAccountResponse,
    responses=error_responses(401, 403, 404, 422),
)
def lookup_account(
    payload: AdminAccountLookupRequest,
    operator: User = Depends(require_operator),
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
    operator: User = Depends(require_operator),
    _same_origin: None = Depends(require_same_origin),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminRevokeSessionsResponse:
    revoked = admin_service.revoke_sessions(
        operator_id=operator.id, account_id=account_id
    )
    return AdminRevokeSessionsResponse(revoked_count=revoked)


__all__ = ["router"]
