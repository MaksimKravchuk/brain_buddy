"""Sync v1 stable snapshot routes (spec 026 PR-33).

Contract: ``sync-v1.md`` sections 6 and 11. The router shares ``SyncRoute``
(protocol ``ErrorBody`` refusals), ``sync_user`` and ``get_sync_gateway`` with
``app/api/sync.py``. The application mounts it (PR-63); until then it is not in
``main.py``. Creating a snapshot and every page are admitted under the owner's
current Identity authority; page tokens never authorize.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_container
from app.api.sync import SyncGateway, SyncRoute, get_sync_gateway, read_body, sync_user
from app.container import Container
from app.modules.tasks.sync import wire
from app.modules.tasks.sync.authority import require_scope
from app.modules.tasks.sync.snapshots import SnapshotStore
from app.schemas.auth import User

router = APIRouter(
    prefix="/sync/v1", tags=["sync"], route_class=SyncRoute, include_in_schema=False
)


def get_snapshot_store(
    gateway: SyncGateway = Depends(get_sync_gateway),
    container: Container = Depends(get_container),
) -> SnapshotStore:
    return SnapshotStore(container.task_repo, gateway.core)


@router.post("/snapshots")
async def create_snapshot(
    request: Request,
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
    store: SnapshotStore = Depends(get_snapshot_store),
) -> dict[str, Any]:
    body = wire.snapshot_request(await read_body(request, 64 * 1024))

    def create() -> dict[str, Any]:
        require_scope(user.id, body["scope_id"])
        with gateway.units.begin(user.id) as unit:
            current = gateway.receipts.admit(unit, gateway.authorize(user))
            if not gateway.enabled(user):
                raise wire.ProtocolFailure("ACCESS_DENIED")
            return store.create(unit, current, now=gateway.clock())

    return await run_in_threadpool(create)


@router.get("/snapshots/{snapshot_id}")
def get_snapshot_page(
    snapshot_id: str,
    scope_id: str = Query(),
    page_token: str = Query(),
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
    store: SnapshotStore = Depends(get_snapshot_store),
) -> dict[str, Any]:
    require_scope(user.id, scope_id)
    with gateway.units.begin(user.id) as unit:
        current = gateway.receipts.admit(unit, gateway.authorize(user))
        if not gateway.enabled(user):
            raise wire.ProtocolFailure("ACCESS_DENIED")
        return store.page(unit, current, snapshot_id, page_token, now=gateway.clock())
