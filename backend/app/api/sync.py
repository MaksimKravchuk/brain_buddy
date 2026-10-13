"""Sync v1 device, command and capability routes (spec 026 PR-31).

Contract: ``specs/026-rust-core-sync/contracts/sync-v1.md`` section 11. Auth is
the session cookie like every ``/api`` route; services come from ``Depends()``.
``SyncRoute`` renders every refusal as the contract's ``ErrorBody``. Later sync
routes (delta, snapshots, hints) reuse ``SyncRoute``, ``sync_user`` and
``get_sync_gateway`` on their own routers.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies import get_container, get_current_user
from app.container import Container
from app.exceptions import ValidationFailure
from app.modules.tasks.rust_adapter import RustBridgeError, RustCore
from app.modules.tasks.sync import wire
from app.modules.tasks.sync.authority import IdentityScopeAuthority, require_scope
from app.modules.tasks.sync.device_executor import build_executor
from app.modules.tasks.sync.devices import DeviceEpochs
from app.modules.tasks.sync.receipts import (
    STABLE_REPLAY_BYTES,
    Authority,
    CommandRequest,
    ReceiptStore,
    SyncCommandError,
)
from app.modules.tasks.sync.unit_of_work import TaskUnitOfWork
from app.schemas.auth import User

logger = logging.getLogger(__name__)
_BUILD = threading.Lock()
_KNOWN = wire.ERROR_CODES - {"AUTH_REQUIRED", "ACCESS_DENIED"}


_REQUEST_FAULTS = frozenset({"TRUSTED_ORIGIN_REQUIRED"})


def _code_of(error: SyncCommandError) -> str:
    """The contract code for a boundary failure; unknown ones are retryable 503."""
    if error.code in _REQUEST_FAULTS:
        return "INVALID_REQUEST"
    return error.code if error.code in _KNOWN else "TEMPORARILY_UNAVAILABLE"


class SyncRoute(APIRoute):
    """Renders protocol failures as ``ErrorBody`` with the contract's statuses."""

    def get_route_handler(self) -> Callable[[Request], Any]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Any:
            try:
                return await handler(request)
            except wire.ProtocolFailure as failure:
                return _refusal(failure)
            except SyncCommandError as error:
                if error.code not in _KNOWN | _REQUEST_FAULTS:
                    logger.warning("sync_command_failed code=%s", error.code)
                return _refusal(wire.ProtocolFailure(_code_of(error)))
            except RequestValidationError, ValidationFailure:
                return _refusal(wire.ProtocolFailure("INVALID_REQUEST"))
            except RustBridgeError:
                return _refusal(wire.ProtocolFailure("TEMPORARILY_UNAVAILABLE"))
            except StarletteHTTPException as error:
                if error.status_code != 401:
                    raise
                return _refusal(wire.ProtocolFailure("AUTH_REQUIRED"))

        return guarded


def _refusal(failure: wire.ProtocolFailure) -> JSONResponse:
    status, body = wire.error_body(failure)
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


# The sync contract is the frozen sync-v1.openapi.yaml, not the legacy REST schema.
router = APIRouter(
    prefix="/sync/v1", tags=["sync"], route_class=SyncRoute, include_in_schema=False
)


@dataclass(frozen=True, slots=True)
class SyncGateway:
    """The receipt boundary the sync routes share, built once per application."""

    units: TaskUnitOfWork
    receipts: ReceiptStore
    authority: IdentityScopeAuthority
    devices: DeviceEpochs
    core: RustCore
    enabled: Callable[[User], bool]
    clock: Callable[[], datetime]

    def authorize(self, user: User) -> Authority[Any]:
        """Identity authority bound to this caller's credential generation."""
        return self.authority.bound_to(user.auth_version)


def get_sync_gateway(
    request: Request, container: Container = Depends(get_container)
) -> SyncGateway:
    with _BUILD:
        gateway = getattr(request.app.state, "sync_gateway", None)
        if gateway is None:
            core = container.rust_core
            receipts = ReceiptStore(core)
            flags = container.feature_flag_service
            gateway = SyncGateway(
                container.task_unit_of_work,
                receipts,
                IdentityScopeAuthority(container.user_repo),
                DeviceEpochs(receipts),
                core,
                lambda user: flags.is_effective("rust_core_sync", user),
                container.task_service.clock,
            )
            request.app.state.sync_gateway = gateway
        return gateway


def get_device_executor(
    request: Request,
    gateway: SyncGateway = Depends(get_sync_gateway),
    container: Container = Depends(get_container),
) -> wire.DeviceCommandExecutor:
    """The injected executor, else the registry of family executors (built once)."""
    state = request.app.state
    with _BUILD:
        if getattr(state, "sync_device_executor", None) is None:
            state.sync_device_executor = build_executor(container, gateway.core)
        return state.sync_device_executor  # type: ignore[no-any-return]


def get_version_policy(request: Request) -> wire.VersionPolicy:
    found = getattr(request.app.state, "sync_version_policy", None)
    return found if found is not None else wire.VersionPolicy()


def sync_user(user: User = Depends(get_current_user)) -> User:
    return user


async def read_body(request: Request, limit: int) -> bytes:
    """The request body, refused past ``limit`` bytes before it is buffered."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise wire.ProtocolFailure("COMMAND_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/devices")
async def register_device(
    request: Request,
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
) -> dict[str, Any]:
    body = wire.registration_request(await read_body(request, 64 * 1024))

    def register() -> dict[str, Any]:
        require_scope(user.id, body["scope_id"])
        if not gateway.enabled(user):
            raise wire.ProtocolFailure("ACCESS_DENIED")
        return gateway.devices.register(
            gateway.units,
            user.id,
            gateway.authorize(user),
            device_id=body["device_id"],
            device_epoch=body["device_epoch"],
            protocol_version=str(body["protocol_version"]),
            now=gateway.clock(),
        )

    return await run_in_threadpool(register)


@router.post("/commands")
async def submit_command(
    request: Request,
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
    executor: wire.DeviceCommandExecutor = Depends(get_device_executor),
    policy: wire.VersionPolicy = Depends(get_version_policy),
) -> dict[str, Any]:
    raw = await read_body(request, STABLE_REPLAY_BYTES)
    wire.strict_object(raw)

    def submit() -> dict[str, Any]:
        now = gateway.clock()
        command_request = CommandRequest.device(user.id, raw)
        with gateway.receipts.command(
            gateway.units, command_request, gateway.authorize(user), now=now
        ) as command:
            if command.replay is not None:
                # Recovery precedes every tighter execution rule below.
                return wire.public_receipt(command.replay)
            if not gateway.enabled(user):
                raise wire.ProtocolFailure("ACCESS_DENIED")
            if len(raw) > wire.COMMAND_BYTES:
                raise wire.ProtocolFailure("COMMAND_TOO_LARGE")
            decoded = gateway.core.decode_command(raw)
            if not (
                decoded.executable
                and policy.executes(decoded.command_version, now)
                and executor.supports(decoded.command_type)
            ):
                reason = decoded.unsupported_reason or "command_version"
                raise wire.ProtocolFailure(
                    "UPGRADE_REQUIRED", details={"reason": reason}
                )
            gateway.devices.admit_unseen(command)
            return wire.public_receipt(
                executor.execute(command, wire.strict_object(raw))
            )

    return await run_in_threadpool(submit)


@router.get("/commands/{command_id}")
def lookup_command(
    command_id: UUID,
    scope_id: str = Query(),
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
) -> dict[str, Any]:
    require_scope(user.id, scope_id)
    now, authority = gateway.clock(), gateway.authorize(user)
    with gateway.units.begin(user.id) as unit:
        current = gateway.receipts.admit(unit, authority)
        receipt = gateway.receipts.lookup(unit, str(command_id), authority, now=now)
    return wire.lookup_body(str(command_id), receipt, current, now)


@router.get("/capabilities")
def get_capabilities(
    scope_id: str = Query(),
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
    executor: wire.DeviceCommandExecutor = Depends(get_device_executor),
    policy: wire.VersionPolicy = Depends(get_version_policy),
) -> Mapping[str, Any]:
    require_scope(user.id, scope_id)
    now = gateway.clock()
    with gateway.units.begin(user.id) as unit:
        current = gateway.receipts.admit(unit, gateway.authorize(user))
    return wire.capabilities_body(
        current,
        now,
        enabled=gateway.enabled(user),
        policy=policy,
        executor=executor,
    )
