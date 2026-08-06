"""Self-serve account management routes (GDPR data rights).

Always available — privacy rights are never feature-flag gated. The three
credential-sensitive actions (email change, password change, deletion) each
re-check the current password and share a per-user rate limit.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.core.config import AppConfig
from app.core.rate_limit import sensitive_action_rate_limiter
from app.schemas.account import (
    AccountResponse,
    EmailChangeRequest,
    PasswordChangeRequest,
    ProfileUpdateRequest,
)
from app.schemas.auth import User
from app.services import AccountService, AuthService

from .contracts import error_responses
from .dependencies import (
    get_account_service,
    get_auth_service,
    get_config_dep,
    get_current_user,
)

router = APIRouter(tags=["account"])


def _check_sensitive_rate_limit(user: User) -> None:
    if not sensitive_action_rate_limiter.check(user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again in a few minutes.",
        )


def _account_response(user: User, account_service: AccountService) -> AccountResponse:
    return AccountResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        created_at=user.created_at,
        deletion_requested_at=user.deletion_requested_at,
        purge_at=account_service.purge_at_for(user),
    )


@router.get("", response_model=AccountResponse, responses=error_responses(401))
def get_account(
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountResponse:
    user = account_service.get_account(current_user)
    return _account_response(user, account_service)


@router.patch(
    "/profile",
    response_model=AccountResponse,
    responses=error_responses(400, 401, 422),
)
def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountResponse:
    user = account_service.update_profile(
        current_user, display_name=payload.display_name
    )
    return _account_response(user, account_service)


@router.post(
    "/email",
    response_model=AccountResponse,
    responses=error_responses(400, 401, 403, 422, 429),
)
def change_email(
    payload: EmailChangeRequest,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
) -> AccountResponse:
    _check_sensitive_rate_limit(current_user)
    user = account_service.change_email(
        current_user,
        new_email=payload.new_email,
        current_password=payload.current_password,
    )
    return _account_response(user, account_service)


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400, 401, 403, 422, 429),
)
def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    account_service: AccountService = Depends(get_account_service),
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
) -> None:
    _check_sensitive_rate_limit(current_user)
    raw_token = request.cookies.get(config.session.cookie_name)
    keep_token_hash = auth_service.hash_session_token(raw_token) if raw_token else None
    account_service.change_password(
        current_user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        keep_token_hash=keep_token_hash,
    )
