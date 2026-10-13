"""Sync v1 foreground SSE hints route (spec 026 PR-58).

Contract: ``specs/026-rust-core-sync/contracts/sync-v1.md`` section 11. The
publisher lives in ``app.modules.tasks.sync.hints``; this module only checks
current authority before opening and hands the stream a per-connection
admission it re-runs on every watcher pass. PR-63 mounts ``router``.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from sqlite3 import Connection
from typing import cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_container
from app.api.sync import SyncGateway, SyncRoute, get_sync_gateway, sync_user
from app.container import Container
from app.core.logging import get_correlation_id
from app.modules.tasks.sync import wire
from app.modules.tasks.sync.authority import require_scope
from app.modules.tasks.sync.hints import (
    STREAM_HEADERS,
    Admission,
    Generations,
    HintHub,
    SqliteCommitCounter,
)
from app.modules.tasks.sync.unit_of_work import OwnerUnitOfWork
from app.schemas.auth import User

_BUILD = threading.Lock()

router = APIRouter(
    prefix="/sync/v1", tags=["sync"], route_class=SyncRoute, include_in_schema=False
)


@dataclass(frozen=True, slots=True)
class _ReadUnit:
    """What ``IdentityScopeAuthority`` reads of a unit; no lock, no writes."""

    owner_id: str
    connection: Connection
    cleanup: bool = False


def get_hint_hub(
    request: Request,
    gateway: SyncGateway = Depends(get_sync_gateway),
    container: Container = Depends(get_container),
) -> HintHub:
    with _BUILD:
        hub = getattr(request.app.state, "sync_hint_hub", None)
        if hub is None:
            hub = HintHub(
                SqliteCommitCounter(container.task_repo.db_path), gateway.clock
            )
            request.app.state.sync_hint_hub = hub
        return hub


def _admission(gateway: SyncGateway, container: Container, user: User) -> Admission:
    """Current Identity, flag and scope admission for this caller's credential."""
    authority = gateway.authorize(user)
    db_path = container.task_repo.db_path

    def current() -> Generations | None:
        fresh = container.user_repo.get_by_id(user.id)
        if fresh is None or not gateway.enabled(fresh):
            return None
        with closing(sqlite3.connect(db_path, timeout=5)) as conn:
            conn.row_factory = sqlite3.Row
            scope = authority(
                cast(OwnerUnitOfWork[Connection], _ReadUnit(user.id, conn))
            )
        if not scope.admission_open:
            return None
        return Generations(
            scope.server_generation,
            scope.feed_generation,
            scope.access_generation,
            scope.storage_epoch,
        )

    return current


@router.get("/hints")
async def stream_hints(
    scope_id: str = Query(),
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
    container: Container = Depends(get_container),
    hub: HintHub = Depends(get_hint_hub),
) -> StreamingResponse:
    # ``Last-Event-ID`` is never read: it grants neither authority nor a position.
    def open_scope() -> Admission:
        require_scope(user.id, scope_id)
        with gateway.units.begin(user.id) as unit:
            gateway.receipts.admit(unit, gateway.authorize(user))
        if not gateway.enabled(user):
            raise wire.ProtocolFailure("ACCESS_DENIED")
        return _admission(gateway, container, user)

    admission = await run_in_threadpool(open_scope)
    return StreamingResponse(
        hub.stream(scope_id, admission, get_correlation_id()),
        media_type="text/event-stream",
        headers=STREAM_HEADERS,
    )
