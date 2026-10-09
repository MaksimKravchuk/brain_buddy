"""Additive proof-bound login and account management endpoints."""

from __future__ import annotations

import re
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse

from app.api.account import _check_sensitive_rate_limit
from app.api.auth import _clear_session_cookie, _me_response, _set_session_cookie
from app.api.contracts import error_responses
from app.api.dependencies import get_container, get_feature_flag_service
from app.container import Container
from app.schemas.account import AccountDeleteResponse
from app.schemas.modern_auth import (
    AccountActionRequest,
    AccountMethodsResponse,
    AccountPasswordRequest,
    AppleNativeCompleteRequest,
    AppleNotificationRequest,
    AuthCompletion,
    ChallengeResponse,
    Client,
    EmailRequest,
    EmailResendRequest,
    EmailVerifyRequest,
    MethodsResponse,
    PasswordConfirmRequest,
    Provider,
    ProviderCompleteRequest,
    ProviderStartRequest,
    ProviderStartResponse,
    ReauthenticatedResult,
    ResetRequest,
    UnlinkResponse,
)
from app.services.feature_flag_service import FeatureFlagService
from app.services.modern_auth_service import (
    AuthResult,
    ModernAuthError,
    ModernAuthService,
)

router = APIRouter(tags=["modern auth"])
_FAILURES = error_responses(400, 401, 403, 404, 409, 422, 429, 503)
_BINDER = "brainbuddy_auth_binder"


def service(container: Container = Depends(get_container)) -> ModernAuthService:
    return container.modern_auth_service


def json_origin(request: Request) -> None:
    config = request.app.state.config
    origin = request.headers.get("origin")
    site = request.headers.get("sec-fetch-site")
    if (origin is not None and origin != config.modern_auth.public_origin) or (
        site is not None and site not in {"same-origin", "none"}
    ):
        raise ModernAuthError("invalid_proof", 403)
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise ModernAuthError("invalid_proof", 400)


def raw_token(request: Request) -> str | None:
    return request.cookies.get(request.app.state.config.session.cookie_name)


def network(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def finish(
    result: AuthResult,
    request: Request,
    response: Response,
    flags: FeatureFlagService,
    auth: ModernAuthService,
) -> AuthCompletion:
    if result.raw_token:
        _set_session_cookie(response, result.raw_token, request.app.state.config)
    payload = result.payload
    if hasattr(payload, "user"):
        user = auth.completion_user(payload.user.id)
        payload = payload.model_copy(
            update={
                "user": _me_response(
                    user,
                    flags,
                    deletion_cancelled=getattr(payload, "deletion_cancelled", False),
                )
            }
        )
    return payload


@router.get(
    "/auth/methods", response_model=MethodsResponse, responses=error_responses(422)
)
def methods(
    client: Client = "web", auth: ModernAuthService = Depends(service)
) -> MethodsResponse:
    return auth.methods(client)


@router.post(
    "/auth/email/request",
    response_model=ChallengeResponse,
    status_code=202,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def request_email(
    payload: EmailRequest, request: Request, auth: ModernAuthService = Depends(service)
) -> ChallengeResponse:
    return auth.request_email(
        payload, network=network(request), raw_token=raw_token(request)
    )


@router.post(
    "/auth/email/resend",
    response_model=ChallengeResponse,
    status_code=202,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def resend_email(
    payload: EmailResendRequest,
    request: Request,
    auth: ModernAuthService = Depends(service),
) -> ChallengeResponse:
    return auth.resend_email(
        payload, network=network(request), raw_token=raw_token(request)
    )


@router.post(
    "/auth/email/verify",
    response_model=AuthCompletion,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def verify_email(
    payload: EmailVerifyRequest,
    request: Request,
    response: Response,
    auth: ModernAuthService = Depends(service),
    flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AuthCompletion:
    return finish(
        auth.verify_email(
            payload, network=network(request), raw_token=raw_token(request)
        ),
        request,
        response,
        flags,
        auth,
    )


@router.post(
    "/auth/recovery/reset",
    status_code=204,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def reset_password(
    payload: ResetRequest, auth: ModernAuthService = Depends(service)
) -> None:
    auth.reset_password(payload)


@router.post(
    "/auth/confirm/password",
    response_model=ReauthenticatedResult,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def confirm_password(
    payload: PasswordConfirmRequest,
    request: Request,
    auth: ModernAuthService = Depends(service),
) -> ReauthenticatedResult:
    _check_sensitive_rate_limit(
        auth.caller(raw_token(request), payload.expected_account_id)
    )
    return auth.confirm_password(payload, raw_token=raw_token(request))


@router.post(
    "/auth/providers/{provider}/start",
    response_model=ProviderStartResponse,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def start_provider(
    provider: Provider,
    payload: ProviderStartRequest,
    request: Request,
    response: Response,
    auth: ModernAuthService = Depends(service),
) -> ProviderStartResponse:
    result = auth.start_provider(
        provider, payload, raw_token=raw_token(request), network=network(request)
    )
    if result.binder:
        response.set_cookie(
            _BINDER,
            result.binder,
            max_age=600,
            httponly=True,
            secure=True,
            samesite="none",
            path=f"{request.app.state.config.api_prefix}/auth/providers",
        )
    return result.payload


def returned(request: Request, url: str) -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    response.delete_cookie(
        _BINDER,
        path=f"{request.app.state.config.api_prefix}/auth/providers",
        secure=True,
        httponly=True,
        samesite="none",
    )
    return response


def valid_provider_callback(code: str, state: str, error: str) -> bool:
    """Accept one bounded provider outcome with its original state."""
    return bool(
        re.fullmatch(r"[A-Za-z0-9_-]{43}", state)
        and bool(code) != bool(error)
        and (
            1 <= len(code) <= 4096
            if code
            else re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", error)
        )
    )


@router.get(
    "/auth/providers/google/callback",
    responses=error_responses(400, 403, 404, 409, 422, 429, 503),
    status_code=303,
)
def google_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    auth: ModernAuthService = Depends(service),
) -> RedirectResponse:
    if not valid_provider_callback(code, state, error):
        raise ModernAuthError()
    result = auth.provider_callback(
        "google",
        code=code,
        state=state,
        error=error,
        binder=request.cookies.get(_BINDER),
    )
    return returned(request, result.url)


@router.post(
    "/auth/providers/apple/callback",
    responses=error_responses(400, 403, 404, 409, 422, 429, 503),
    status_code=303,
)
async def apple_callback(
    request: Request, auth: ModernAuthService = Depends(service)
) -> RedirectResponse:
    if (
        request.headers.get("content-type", "").split(";", 1)[0]
        != "application/x-www-form-urlencoded"
    ):
        raise ModernAuthError()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 32768:
            raise ModernAuthError()
    try:
        fields = parse_qs(body.decode("ascii"), strict_parsing=True, max_num_fields=5)
        if any(len(value) != 1 for value in fields.values()):
            raise ValueError()
        code, state = fields.get("code", [""])[0], fields.get("state", [""])[0]
        error = fields.get("error", [""])[0]
        if (
            not valid_provider_callback(code, state, error)
            or len(fields.get("id_token", [""])[0]) > 16384
        ):
            raise ValueError()
    except ValueError, UnicodeError:
        raise ModernAuthError() from None
    result = auth.provider_callback(
        "apple",
        code=code,
        state=state,
        error=error,
        binder=request.cookies.get(_BINDER),
    )
    return returned(request, result.url)


@router.post(
    "/auth/providers/complete",
    response_model=AuthCompletion,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def complete_provider(
    payload: ProviderCompleteRequest,
    request: Request,
    response: Response,
    auth: ModernAuthService = Depends(service),
    flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AuthCompletion:
    return finish(
        auth.complete_provider(
            payload, raw_token=raw_token(request), network=network(request)
        ),
        request,
        response,
        flags,
        auth,
    )


@router.post(
    "/auth/providers/apple/native/complete",
    response_model=AuthCompletion,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def native_apple(
    payload: AppleNativeCompleteRequest,
    request: Request,
    response: Response,
    auth: ModernAuthService = Depends(service),
    flags: FeatureFlagService = Depends(get_feature_flag_service),
) -> AuthCompletion:
    return finish(
        auth.complete_native_apple(
            payload, raw_token=raw_token(request), network=network(request)
        ),
        request,
        response,
        flags,
        auth,
    )


@router.post(
    "/auth/providers/apple/notifications",
    status_code=204,
    responses=error_responses(400, 401, 422, 429, 503),
)
def apple_notification(
    payload: AppleNotificationRequest, auth: ModernAuthService = Depends(service)
) -> None:
    auth.process_apple_notification(payload.payload)


@router.get(
    "/account/auth-methods",
    response_model=AccountMethodsResponse,
    responses=error_responses(401, 404, 503),
)
def account_methods(
    request: Request, auth: ModernAuthService = Depends(service)
) -> AccountMethodsResponse:
    return auth.account_methods(raw_token=raw_token(request))


@router.post(
    "/account/auth-methods/{provider}/unlink",
    response_model=UnlinkResponse,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def unlink(
    provider: Provider,
    payload: AccountActionRequest,
    request: Request,
    response: Response,
    auth: ModernAuthService = Depends(service),
) -> UnlinkResponse:
    result = auth.unlink(provider, payload, raw_token=raw_token(request))
    if result.signed_out:
        _clear_session_cookie(response, request.app.state.config)
    return result


@router.post(
    "/account/auth-password",
    status_code=204,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def set_password(
    payload: AccountPasswordRequest,
    request: Request,
    auth: ModernAuthService = Depends(service),
) -> None:
    auth.set_password(payload, raw_token=raw_token(request))


@router.post(
    "/account/auth-export",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Safe account-owned archive.",
        },
        **_FAILURES,
    },
    dependencies=[Depends(json_origin)],
)
def export_account(
    payload: AccountActionRequest,
    request: Request,
    auth: ModernAuthService = Depends(service),
) -> StreamingResponse:
    filename, stream = auth.export_account(payload, raw_token=raw_token(request))
    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/account/auth-delete",
    response_model=AccountDeleteResponse,
    status_code=202,
    responses=_FAILURES,
    dependencies=[Depends(json_origin)],
)
def delete_account(
    payload: AccountActionRequest,
    request: Request,
    response: Response,
    auth: ModernAuthService = Depends(service),
) -> AccountDeleteResponse:
    user = auth.delete_account(payload, raw_token=raw_token(request))
    _clear_session_cookie(response, request.app.state.config)
    purge_at = auth.account.purge_at_for(user)
    assert user.deletion_requested_at is not None and purge_at is not None
    return AccountDeleteResponse(
        deletion_requested_at=user.deletion_requested_at, purge_at=purge_at
    )
