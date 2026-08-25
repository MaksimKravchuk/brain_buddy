"""Minimum admin portal routes: exact account lookup, session revoke, and
runtime feature-flag management.

Every route requires `require_operator` — a valid session AND allow-list
membership, deny-before-touch (009-FR-002) — directly. There is no more
`admin_portal` rollout flag layered on top: the Admin Portal is key
functionality and is always reachable by an authenticated, allow-listed
operator (ADR-0019, DD-14). The mutation relies on the repository's existing
`SameSite=Lax` session-cookie posture like every other mutating route
(009-FR-009); no additional origin check is added.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.admin import (
    AdminAccountCreateRequest,
    AdminAccountDeleteResponse,
    AdminAccountListResponse,
    AdminAccountLookupRequest,
    AdminAccountResponse,
    AdminAccountUpdateRequest,
    AdminFeatureFlagMode,
    AdminFeatureFlagModeRequest,
    AdminFeatureFlagSelectedUser,
    AdminFeatureFlagSelectedUserRequest,
    AdminFeatureFlagsResponse,
    AdminFeatureFlagState,
    AdminRevokeSessionsResponse,
    AdminStatusResponse,
)
from app.schemas.auth import User
from app.services import AdminService, FeatureFlagService, SelectedUserNotFoundError
from app.services.feature_flag_service import (
    DegradedRuntimeFlagsError,
    RuntimeFlagsView,
)

from .contracts import error_responses
from .dependencies import get_admin_service, get_feature_flag_service, require_operator

router = APIRouter(tags=["admin"])

_DEGRADED_DETAIL = (
    "Runtime flag state could not be read. Every flag is resolving as "
    "ineffective, and changes are disabled until this is repaired."
)


def _flags_response(view: RuntimeFlagsView) -> AdminFeatureFlagsResponse:
    """Project the service's authoritative view onto the wire contract.

    Every mutation returns the *full* post-mutation state so the screen can
    re-render from the server's own answer rather than optimistic local state
    (010-FR-010).
    """

    return AdminFeatureFlagsResponse(
        degraded=view.degraded,
        flags=[
            AdminFeatureFlagState(
                name=flag.name,
                mode=AdminFeatureFlagMode(flag.mode.value),
                selected_users=[
                    AdminFeatureFlagSelectedUser(
                        account_id=member.account_id, email=member.email
                    )
                    for member in flag.selected_users
                ],
            )
            for flag in view.flags
        ],
    )


def _degraded() -> HTTPException:
    """A store nobody could parse is refused, never overwritten (010-FR-004)."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_DEGRADED_DETAIL
    )


def _account_response(user: User) -> AdminAccountResponse:
    return AdminAccountResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        deletion_requested=user.deletion_requested_at is not None,
    )


@router.get(
    "/accounts",
    response_model=AdminAccountListResponse,
    responses=error_responses(401, 403),
)
def list_accounts(
    operator: User = Depends(require_operator),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountListResponse:
    accounts = admin_service.list_accounts(operator_id=operator.id)
    return AdminAccountListResponse(
        accounts=[_account_response(user) for user in accounts]
    )


@router.post(
    "/accounts",
    response_model=AdminAccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 409, 422),
)
def create_account(
    payload: AdminAccountCreateRequest,
    operator: User = Depends(require_operator),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountResponse:
    return _account_response(
        admin_service.create_account(operator_id=operator.id, **payload.model_dump())
    )


@router.put(
    "/accounts/{account_id}",
    response_model=AdminAccountResponse,
    responses=error_responses(401, 403, 404, 409, 422),
)
def update_account(
    account_id: str,
    payload: AdminAccountUpdateRequest,
    operator: User = Depends(require_operator),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountResponse:
    return _account_response(
        admin_service.update_account(
            operator_id=operator.id, account_id=account_id, **payload.model_dump()
        )
    )


@router.delete(
    "/accounts/{account_id}",
    response_model=AdminAccountDeleteResponse,
    status_code=status.HTTP_200_OK,
    responses=error_responses(401, 403, 404, 422),
)
def delete_account(
    account_id: str,
    operator: User = Depends(require_operator),
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminAccountDeleteResponse:
    admin_service.delete_account(operator_id=operator.id, account_id=account_id)
    return AdminAccountDeleteResponse(account_id=account_id)


@router.get(
    "/status",
    response_model=AdminStatusResponse,
    responses=error_responses(401, 403),
)
def admin_status(_operator: User = Depends(require_operator)) -> AdminStatusResponse:
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
    admin_service: AdminService = Depends(get_admin_service),
) -> AdminRevokeSessionsResponse:
    revoked = admin_service.revoke_sessions(
        operator_id=operator.id, account_id=account_id
    )
    return AdminRevokeSessionsResponse(revoked_count=revoked)


@router.get(
    "/feature-flags",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(401, 403),
)
def list_feature_flags(
    operator: User = Depends(require_operator),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Read every runtime-manageable flag's mode and cohort (010-FR-010).

    Behind the same gate as every mutation, deliberately: FR-006 counts this
    route among the four, so a denial performs no repository read here
    either.
    """

    return _flags_response(feature_flags.describe(operator_id=operator.id))


@router.put(
    "/feature-flags/{flag}/mode",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(400, 401, 403, 422, 503),
)
def set_feature_flag_mode(
    flag: str,
    payload: AdminFeatureFlagModeRequest,
    operator: User = Depends(require_operator),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Put one managed flag into OFF, ON or SELECTED_USERS (010-FR-005)."""

    try:
        view = feature_flags.set_mode(flag, payload.mode.value, operator_id=operator.id)
    except DegradedRuntimeFlagsError as exc:
        raise _degraded() from exc
    return _flags_response(view)


@router.post(
    "/feature-flags/{flag}/selected-users",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(400, 401, 403, 404, 422, 503),
)
def add_feature_flag_selected_user(
    flag: str,
    payload: AdminFeatureFlagSelectedUserRequest,
    operator: User = Depends(require_operator),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Add one exactly-matched account to a SELECTED_USERS cohort (010-FR-007).

    Resolution goes through `AdminService.find_account`, so 009-FR-003's
    exact-match semantics are inherited rather than re-implemented — and its
    "Admin lookup" record fires here exactly as it does for the lookup route.
    """

    try:
        view = feature_flags.add_selected_user(
            flag,
            operator_id=operator.id,
            account_id=payload.account_id,
            email=payload.email,
        )
    except SelectedUserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No account found."
        ) from exc
    except DegradedRuntimeFlagsError as exc:
        raise _degraded() from exc
    return _flags_response(view)


@router.delete(
    "/feature-flags/{flag}/selected-users/{account_id}",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(400, 401, 403, 422, 503),
)
def remove_feature_flag_selected_user(
    flag: str,
    account_id: str,
    operator: User = Depends(require_operator),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Remove one stored account ID. Idempotent by ID, with no lookup (DD-7).

    Deliberately performs no account resolution: a stored ID that no longer
    names an account must still be removable, and a second removal of the same
    ID must still report success.
    """

    try:
        view = feature_flags.remove_selected_user(
            flag, account_id, operator_id=operator.id
        )
    except DegradedRuntimeFlagsError as exc:
        raise _degraded() from exc
    return _flags_response(view)


__all__ = ["router"]
