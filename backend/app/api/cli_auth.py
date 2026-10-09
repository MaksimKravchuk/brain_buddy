"""Bounded, nonreflecting device-flow endpoints; no navigation can approve."""

import json
import logging

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.auth import _me_response, _set_session_cookie
from app.api.contracts import error_responses
from app.api.dependencies import get_container
from app.core.logging import get_correlation_id
from app.schemas.cli_auth import DeviceDecision, DeviceRequest, DeviceStart, DeviceToken
from app.services.cli_auth import CliAuthError, CliAuthService

router = APIRouter(prefix="/auth/device", tags=["CLI authorization"])
logger = logging.getLogger(__name__)


async def _body[T: BaseModel](request: Request, schema: type[T]) -> T:
    if (
        request.headers.get("Content-Type", "").split(";", 1)[0].lower()
        != "application/json"
    ):
        raise CliAuthError("invalid_request", 415)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 1024:
            raise CliAuthError("invalid_request", 413)
        body.extend(chunk)
    try:
        return schema.model_validate(json.loads(body))
    except ValueError, ValidationError, TypeError:
        raise CliAuthError("invalid_request", 422) from None


def _service(request: Request, *, browser: bool = False) -> CliAuthService:
    service = get_container(request).cli_auth_service
    service.available()
    if browser and request.headers.get("Origin") != service.origin:
        raise CliAuthError("invalid_origin", 403)
    return service


def _admit(request: Request, service: CliAuthService, *, browser: bool = False) -> str:
    ip = request.client.host if request.client else "unknown"
    if browser:
        token = request.cookies.get(request.app.state.config.session.cookie_name)
        user = service.auth.get_user_for_token(token)
        if user is None:
            raise CliAuthError("cli_auth_unavailable", 404)
        service.available(user)
        limiter, global_limit = service.browser_limit, service.browser_global
        key = ip + ":" + user.id
    else:
        limiter, global_limit, key = service.start_limit, service.start_global, ip
    if not global_limit.check("all") or not (
        limiter.is_allowed(key) if browser else limiter.check(key)
    ):
        raise CliAuthError("rate_limited", 429, 60)
    return key


def _browser(
    request: Request,
    service: CliAuthService,
    code: str,
    decision: str | None = None,
    expected_owner: str | None = None,
) -> dict[str, object]:
    with service.browser_admission:
        key = _admit(request, service, browser=True)
        try:
            return service.browser(
                code,
                request.cookies.get(request.app.state.config.session.cookie_name),
                decision,
                expected_owner,
            )
        except CliAuthError as error:
            if error.status_code == 404:
                service.browser_limit.check(key)
            raise


def _log(operation: str) -> None:
    logger.info(
        "CLI authorization: operation=%s outcome=success correlation=%s",
        operation,
        get_correlation_id(),
    )


@router.post("/start", responses=error_responses(404, 413, 415, 422, 429, 503))
async def start(request: Request) -> dict[str, object]:
    service = _service(request)
    await _body(request, DeviceStart)

    def execute() -> dict[str, object]:
        _admit(request, service)
        result = service.start()
        _log("start")
        return result

    return await run_in_threadpool(execute)


@router.post("/request", responses=error_responses(403, 404, 413, 415, 422, 429, 503))
async def lookup(request: Request) -> dict[str, object]:
    service = _service(request, browser=True)
    payload = await _body(request, DeviceRequest)

    def execute() -> dict[str, object]:
        result = _browser(request, service, payload.user_code)
        _log("request")
        return result

    return await run_in_threadpool(execute)


@router.post(
    "/decision", responses=error_responses(403, 404, 409, 413, 415, 422, 429, 503)
)
async def decision(request: Request) -> dict[str, object]:
    service = _service(request, browser=True)
    payload = await _body(request, DeviceDecision)

    def execute() -> dict[str, object]:
        result = _browser(
            request,
            service,
            payload.user_code,
            payload.decision,
            payload.expected_owner,
        )
        _log("decision")
        return result

    return await run_in_threadpool(execute)


@router.post(
    "/token", responses=error_responses(400, 403, 404, 409, 413, 415, 422, 503)
)
async def token(request: Request, response: Response) -> dict[str, object]:
    service = _service(request)
    payload = await _body(request, DeviceToken)

    def execute() -> dict[str, object]:
        user, raw, session = service.token(payload.device_code)
        config = request.app.state.config
        _set_session_cookie(response, raw, config)
        _log("token")
        return {
            "account": _me_response(user, service.flags),
            "credential_type": "session_cookie",
            "cookie_name": config.session.cookie_name,
            "expires_at": session.expires_at,
        }

    return await run_in_threadpool(execute)
