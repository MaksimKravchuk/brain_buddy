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
    AdminFeatureFlagDeployState,
    AdminFeatureFlagMode,
    AdminFeatureFlagModeRequest,
    AdminFeatureFlagSelectedUser,
    AdminFeatureFlagSelectedUserRequest,
    AdminFeatureFlagSource,
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
from .dependencies import (
    get_admin_service,
    get_feature_flag_service,
    require_admin_portal_enabled,
)

router = APIRouter(tags=["admin"])

_DEGRADED_DETAIL = (
    "Runtime flag state could not be read. Every flag is resolving from the "
    "deploy default, and changes are disabled until this is repaired."
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
                override_mode=(
                    None
                    if flag.override_mode is None
                    else AdminFeatureFlagMode(flag.override_mode.value)
                ),
                source=AdminFeatureFlagSource(flag.source),
                deploy_default_state=AdminFeatureFlagDeployState(
                    flag.deploy_default_state
                ),
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


@router.get(
    "/feature-flags",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(401, 403, 404),
)
def list_feature_flags(
    operator: User = Depends(require_admin_portal_enabled),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Read every runtime-manageable flag's mode, source and cohort (010-FR-010).

    Behind the same 009 gate as every mutation, deliberately: FR-006 counts
    this route among the five, so a denial performs no repository read here
    either.
    """

    return _flags_response(feature_flags.describe(operator_id=operator.id))


@router.put(
    "/feature-flags/{flag}/mode",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(400, 401, 403, 404, 422, 503),
)
def set_feature_flag_mode(
    flag: str,
    payload: AdminFeatureFlagModeRequest,
    operator: User = Depends(require_admin_portal_enabled),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Put one managed flag into OFF, ON or SELECTED_USERS (010-FR-005)."""

    try:
        view = feature_flags.set_mode(flag, payload.mode.value, operator_id=operator.id)
    except DegradedRuntimeFlagsError as exc:
        raise _degraded() from exc
    return _flags_response(view)


@router.delete(
    "/feature-flags/{flag}",
    response_model=AdminFeatureFlagsResponse,
    responses=error_responses(400, 401, 403, 404, 503),
)
def clear_feature_flag_override(
    flag: str,
    operator: User = Depends(require_admin_portal_enabled),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AdminFeatureFlagsResponse:
    """Delete one flag's whole runtime entry, cohort included (DD-3).

    Distinct from setting a mode: only deleting the entry restores actual
    environment inheritance, including the `internal`-stage cohort.
    """

    try:
        view = feature_flags.clear_override(flag, operator_id=operator.id)
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
    operator: User = Depends(require_admin_portal_enabled),
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
    responses=error_responses(400, 401, 403, 404, 503),
)
def remove_feature_flag_selected_user(
    flag: str,
    account_id: str,
    operator: User = Depends(require_admin_portal_enabled),
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
