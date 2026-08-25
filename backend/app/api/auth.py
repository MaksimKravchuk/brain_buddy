"""Authentication routes: signup, login, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_auth_service,
    get_config_dep,
    get_current_user,
    get_feature_flag_service,
)
from app.core.config import AppConfig
from app.core.rate_limit import login_rate_limiter
from app.exceptions import ConflictError
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    SignupRequest,
    User,
)
from app.services import (
    AuthService,
    FeatureFlagService,
    InvalidCredentialsError,
    InvalidInviteError,
)

router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str:
    if request.client is None:  # pragma: no cover - TestClient always sets this
        return "unknown"
    return request.client.host


def _set_session_cookie(response: Response, raw_token: str, config: AppConfig) -> None:
    session_cfg = config.session
    response.set_cookie(
        key=session_cfg.cookie_name,
        value=raw_token,
        max_age=session_cfg.max_age_seconds,
        httponly=True,
        secure=session_cfg.secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, config: AppConfig) -> None:
    session_cfg = config.session
    response.delete_cookie(
        key=session_cfg.cookie_name,
        path="/",
    )


def _me_response(
    user: User,
    feature_flags: FeatureFlagService,
    *,
    deletion_cancelled: bool = False,
) -> MeResponse:
    """The one place the member-facing `feature_flags` payload is built.

    Covers `/auth/me`, `/auth/login` and `/auth/signup` in a single call. The
    resolver overlays all three **managed** flags (`voice_brain_dump`,
    `mobile_task_classification`, `external_agent_relay`) from the shared
    SQLite-backed `FeatureFlagService`; `delivery_canary` alone remains the
    environment-owned deployment control, and the key set stays exactly
    `KNOWN_FEATURE_FLAGS` (010-FR-008).
    """

    return MeResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        deletion_cancelled=deletion_cancelled,
        feature_flags=feature_flags.effective_flags(user),
    )


@router.post(
    "/signup",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 409, 422),
)
def signup(
    payload: SignupRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> MeResponse:
    try:
        user, raw_token = auth_service.signup(
            email=payload.email,
            password=payload.password,
            invite_code=payload.invite_code,
        )
    except InvalidInviteError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        ) from exc

    _set_session_cookie(response, raw_token, config)
    return _me_response(user, feature_flags)


@router.post(
    "/login", response_model=MeResponse, responses=error_responses(401, 422, 429)
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> MeResponse:
    client_ip = _client_ip(request)
    reservation = login_rate_limiter.reserve(client_ip)
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a few minutes.",
        )
    try:
        user, raw_token, deletion_cancelled = auth_service.login(
            email=payload.email, password=payload.password
        )
    except InvalidCredentialsError as exc:
        login_rate_limiter.record(client_ip, reservation)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    finally:
        login_rate_limiter.release(client_ip, reservation)
    _set_session_cookie(response, raw_token, config)
    return _me_response(user, feature_flags, deletion_cancelled=deletion_cancelled)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
) -> Response:
    raw_token = request.cookies.get(config.session.cookie_name)
    auth_service.logout(raw_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response, config)
    return response


@router.get("/me", response_model=MeResponse, responses=error_responses(401))
def me(
    current_user: User = Depends(get_current_user),
    feature_flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> MeResponse:
    return _me_response(current_user, feature_flags)
