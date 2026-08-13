"""HTTP routes for the external-agent relay.

Two auth models meet here. Owner routes use the ordinary session cookie; only
operations that create or enable future external work use the
``external_agent_relay`` rollout flag. The single inbound route is called by the
user's own agent, which has no session at all — it authenticates by signing the
complete request with the connection's signing secret, and every rejection is
returned as one indistinguishable refusal so a prober cannot map connections or
runs by reading error messages.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)

from app.api.contracts import error_responses
from app.api.dependencies import (
    get_agent_relay_service,
    get_auth_service,
    get_current_user,
    require_external_agent_relay_enabled,
)
from app.core.rate_limit import sensitive_action_rate_limiter
from app.exceptions import ReauthFailedError, ValidationFailure
from app.modules.agents.service import AgentRelayService, EventRejected
from app.schemas.agents import (
    AgentConnectionCreatedResponse,
    AgentConnectionCreateRequest,
    AgentConnectionDisconnectRequest,
    AgentConnectionResponse,
    AgentConnectionRotateRequest,
    AgentConnectionRotateSigningSecretRequest,
    AgentConnectionSigningSecretResponse,
    AgentConnectionUpdateRequest,
    AgentEventIngestResponse,
    AgentHandoffConfirmRequest,
    AgentHandoffPreviewRequest,
    AgentManifestResponse,
    AgentReplyRequest,
    AgentRunResponse,
    AgentRunSummaryResponse,
)
from app.schemas.auth import User
from app.services import AuthService

router = APIRouter(tags=["agents"])

MAX_EVENT_BODY_BYTES = 64_000


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if not idempotency_key:
        raise ValidationFailure("Idempotency-Key header is required.")
    return idempotency_key


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail="Event payload is too large.",
    )


def _declared_body_length(request: Request) -> int | None:
    """The caller's own ``Content-Length``, or ``None`` if it is unusable.

    A malformed or negative value is treated as "not declared" rather than as
    an error: the streaming bound below is the real defence, so a junk header
    cannot be used either to bypass the cap or to force a different response.
    """

    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        declared = int(raw)
    except ValueError:
        return None
    return declared if declared >= 0 else None


async def _bounded_event_body(request: Request) -> bytes:
    """Read an inbound event body without ever buffering more than the cap.

    This route is unauthenticated by design, so the size limit has to hold
    against a caller who is not merely careless. A declared length over the cap
    is refused on the header alone, before a single byte is read, and a caller
    that declares nothing (or lies) is cut off the moment the accumulated body
    passes the cap.
    """

    declared = _declared_body_length(request)
    if declared is not None and declared > MAX_EVENT_BODY_BYTES:
        raise _too_large()

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_EVENT_BODY_BYTES:
            raise _too_large()
        chunks.append(chunk)
    return b"".join(chunks)


def _verify_password(
    auth_service: AuthService, user: User, raw_password: str | None
) -> bool:
    """Re-check the account password for a sensitive relay action (FR-003).

    Mirrors the account module's existing ceremony rather than inventing a new
    session-stamp subsystem: proving possession *with the request itself* is
    strictly stronger than proving it within the previous 15 minutes.
    """

    if not raw_password:
        return False
    if not sensitive_action_rate_limiter.check(user.id):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
        )
    if not auth_service.verify_password(user, raw_password):
        raise ReauthFailedError()
    return True


# --- connections ------------------------------------------------------------


@router.get(
    "/agent-connections",
    response_model=list[AgentConnectionResponse],
    responses=error_responses(401, 404),
)
def list_agent_connections(
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> list[AgentConnectionResponse]:
    return service.list_connections(owner_id=current_user.id)


@router.post(
    "/agent-connections",
    response_model=AgentConnectionCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 404, 409, 422, 429),
)
def create_agent_connection(
    payload: AgentConnectionCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AgentConnectionCreatedResponse:
    key = _require_idempotency_key(idempotency_key)
    reauthenticated = _verify_password(
        auth_service, current_user, payload.current_password
    )
    return service.create_connection(
        payload,
        owner_id=current_user.id,
        idempotency_key=key,
        reauthenticated=reauthenticated,
    )


@router.get(
    "/agent-connections/{connection_id}",
    response_model=AgentConnectionResponse,
    responses=error_responses(401, 404, 422),
)
def get_agent_connection(
    connection_id: str,
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentConnectionResponse:
    return service.get_connection(connection_id, owner_id=current_user.id)


@router.put(
    "/agent-connections/{connection_id}",
    response_model=AgentConnectionResponse,
    responses=error_responses(400, 401, 403, 404, 409, 422, 429),
)
def update_agent_connection(
    connection_id: str,
    payload: AgentConnectionUpdateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AgentConnectionResponse:
    reauthenticated = (
        _verify_password(auth_service, current_user, payload.current_password)
        if payload.current_password
        else False
    )
    return service.update_connection(
        connection_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
        reauthenticated=reauthenticated,
    )


@router.post(
    "/agent-connections/{connection_id}/test",
    response_model=AgentConnectionResponse,
    responses=error_responses(400, 401, 404, 422),
)
def test_agent_connection(
    connection_id: str,
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentConnectionResponse:
    return service.test_connection(connection_id, owner_id=current_user.id)


@router.post(
    "/agent-connections/{connection_id}/credential",
    response_model=AgentConnectionResponse,
    responses=error_responses(400, 401, 403, 404, 409, 422, 429),
)
def rotate_agent_credential(
    connection_id: str,
    payload: AgentConnectionRotateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AgentConnectionResponse:
    key = _require_idempotency_key(idempotency_key)
    reauthenticated = _verify_password(
        auth_service, current_user, payload.current_password
    )
    return service.rotate_credential(
        connection_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=key,
        reauthenticated=reauthenticated,
    )


@router.post(
    "/agent-connections/{connection_id}/signing-secret",
    response_model=AgentConnectionSigningSecretResponse,
    responses=error_responses(400, 401, 403, 404, 409, 422, 429),
)
def rotate_agent_signing_secret(
    connection_id: str,
    payload: AgentConnectionRotateSigningSecretRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AgentConnectionSigningSecretResponse:
    """Replace the inbound signing secret when the create response was lost.

    The 201 from registration is the only place that secret is shown, so this
    is the sole way back from losing it. Retrying with the same Idempotency-Key
    returns the same replacement rather than a blank success — the old secret
    is already dead by then, so an empty answer would strand the caller.
    """

    key = _require_idempotency_key(idempotency_key)
    reauthenticated = _verify_password(
        auth_service, current_user, payload.current_password
    )
    return service.rotate_signing_secret(
        connection_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=key,
        reauthenticated=reauthenticated,
    )


@router.post(
    "/agent-connections/{connection_id}/disconnect",
    response_model=AgentConnectionResponse,
    responses=error_responses(400, 401, 403, 404, 409, 422, 429),
)
def disconnect_agent_connection(
    connection_id: str,
    payload: AgentConnectionDisconnectRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AgentConnectionResponse:
    """Disconnect remains available while rollout is OFF as a safe owner control."""

    key = _require_idempotency_key(idempotency_key)
    reauthenticated = _verify_password(
        auth_service, current_user, payload.current_password
    )
    return service.disconnect_connection(
        connection_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=key,
        reauthenticated=reauthenticated,
    )


# --- hand-off and runs ------------------------------------------------------


@router.post(
    "/tasks/{task_id}/agent-runs/preview",
    response_model=AgentManifestResponse,
    responses=error_responses(400, 401, 404, 422),
)
def preview_agent_handoff(
    task_id: str,
    payload: AgentHandoffPreviewRequest,
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentManifestResponse:
    return service.preview_handoff(task_id, payload, owner_id=current_user.id)


@router.post(
    "/tasks/{task_id}/agent-runs",
    response_model=AgentRunResponse,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 404, 409, 422, 429),
)
def dispatch_agent_run(
    task_id: str,
    payload: AgentHandoffConfirmRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(require_external_agent_relay_enabled),
    service: AgentRelayService = Depends(get_agent_relay_service),
    auth_service: AuthService = Depends(get_auth_service),
) -> AgentRunResponse:
    key = _require_idempotency_key(idempotency_key)
    # The password is optional here: it is only required for the first
    # content-bearing dispatch in a destination/credential scope the owner has
    # not proved possession for recently, and the service decides that.
    reauthenticated = (
        _verify_password(auth_service, current_user, payload.current_password)
        if payload.current_password
        else False
    )
    return service.dispatch_run(
        task_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=key,
        reauthenticated=reauthenticated,
    )


@router.get(
    "/tasks/{task_id}/agent-runs",
    response_model=list[AgentRunResponse],
    responses=error_responses(401, 404, 422),
)
def list_agent_runs_for_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> list[AgentRunResponse]:
    return service.list_runs_for_task(task_id, owner_id=current_user.id)


@router.get(
    "/agent-run-summaries",
    response_model=dict[str, AgentRunSummaryResponse],
    responses=error_responses(401, 404, 422),
)
def list_agent_run_summaries(
    task_id: list[str] = Query(default_factory=list, max_length=200),
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> dict[str, AgentRunSummaryResponse]:
    """Latest run per task, for the compact Task surface (FR-010).

    Keyed by task ID and sparse: a task with no hand-off is simply absent, so a
    list page renders no agent affordance for it. Bounded so a page of tasks
    cannot turn into an unbounded scan.
    """

    return service.latest_run_summaries(owner_id=current_user.id, task_ids=task_id)


@router.get(
    "/agent-runs/{run_id}",
    response_model=AgentRunResponse,
    responses=error_responses(401, 404, 422),
)
def get_agent_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentRunResponse:
    return service.get_run(run_id, owner_id=current_user.id)


@router.post(
    "/agent-runs/{run_id}/reply",
    response_model=AgentRunResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def reply_to_agent_run(
    run_id: str,
    payload: AgentReplyRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentRunResponse:
    return service.reply_to_run(
        run_id,
        payload,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )


@router.post(
    "/agent-runs/{run_id}/cancel",
    response_model=AgentRunResponse,
    responses=error_responses(400, 401, 404, 409, 422),
)
def cancel_agent_run(
    run_id: str,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentRunResponse:
    return service.cancel_run(
        run_id,
        owner_id=current_user.id,
        idempotency_key=_require_idempotency_key(idempotency_key),
    )


# --- inbound connector events -----------------------------------------------


@router.post(
    "/agent-events",
    response_model=AgentEventIngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=error_responses(400, 403, 413, 422),
)
async def ingest_agent_event(
    request: Request,
    response: Response,
    connection_id: str | None = Header(default=None, alias="X-BrainBuddy-Connection"),
    timestamp: str | None = Header(default=None, alias="X-BrainBuddy-Timestamp"),
    signature: str | None = Header(default=None, alias="X-BrainBuddy-Signature"),
    service: AgentRelayService = Depends(get_agent_relay_service),
) -> AgentEventIngestResponse:
    """Accept one signed report from a user's agent.

    Not gated on the rollout flag: a run that was already dispatched must remain
    able to report even if the owner's flag is later turned off, otherwise the
    user is left with a run frozen mid-flight and no way to learn its outcome.
    """

    raw_body = await _bounded_event_body(request)
    if not connection_id or not timestamp or not signature:
        # Same shape as a bad signature: an unsigned probe learns nothing.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event rejected.",
        )
    try:
        return service.ingest_event(
            raw_body=raw_body,
            connection_id=connection_id,
            timestamp=timestamp,
            signature=signature,
        )
    except EventRejected as exc:
        # One opaque refusal for every failure mode. The specific reason is in
        # the owner's audit trail, never in the response.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event rejected.",
        ) from exc
