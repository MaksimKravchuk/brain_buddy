"""Authentication routes: signup, login, logout, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_auth_service,
    get_config_dep,
    get_current_user,
    get_session_token,
)
from app.core.config import AppConfig
from app.core.rate_limit import login_rate_limiter
from app.exceptions import ConflictError
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    SessionCredentialResponse,
    SignupRequest,
    User,
)
from app.services import AuthService, InvalidCredentialsError, InvalidInviteError

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


@router.post(
    "/signup",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 409, 422, 503),
)
def signup(
    payload: SignupRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
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
    return MeResponse(id=user.id, email=user.email)


@router.post(
    "/login", response_model=MeResponse, responses=error_responses(401, 422, 429, 503)
)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
) -> MeResponse:
    if not login_rate_limiter.check(_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a few minutes.",
        )
    try:
        user, raw_token = auth_service.login(
            email=payload.email, password=payload.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    _set_session_cookie(response, raw_token, config)
    return MeResponse(id=user.id, email=user.email)


@router.post(
    "/mobile/sessions",
    response_model=SessionCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 422, 429, 503),
)
def create_mobile_session(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> SessionCredentialResponse:
    """Issue the existing opaque server Session once for native secure storage."""

    if not login_rate_limiter.check(_client_ip(request)):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again in a few minutes.",
        )
    try:
        user, raw_token, session = auth_service.login_with_session(
            email=payload.email, password=payload.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return SessionCredentialResponse(
        session_token=raw_token,
        expires_at=session.expires_at,
        user=MeResponse(id=user.id, email=user.email),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    config: AppConfig = Depends(get_config_dep),
) -> Response:
    raw_token = get_session_token(request, config)
    auth_service.logout(raw_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response, config)
    return response


@router.get("/me", response_model=MeResponse, responses=error_responses(401))
def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=current_user.id, email=current_user.email)
