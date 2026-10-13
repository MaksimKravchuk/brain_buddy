"""Sync v1 delta feed and oversized-transaction transfer routes (spec 026 PR-32).

Contract: ``sync-v1.md`` sections 6 and 11. The router shares ``SyncRoute``
(protocol ``ErrorBody`` refusals), ``sync_user`` and ``get_sync_gateway`` with
``app/api/sync.py``. The application mounts it (PR-63); until then it is not in
``main.py``. Every page is admitted under the owner's current Identity
authority; cursors and page tokens never authorize.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.sync import SyncGateway, SyncRoute, get_sync_gateway, sync_user
from app.modules.tasks.sync import wire
from app.modules.tasks.sync.authority import require_scope
from app.modules.tasks.sync.delta import MAX_PAGE_TRANSACTIONS, Feed, read_changes
from app.modules.tasks.sync.transfers import TransferStore
from app.schemas.auth import User

router = APIRouter(
    prefix="/sync/v1", tags=["sync"], route_class=SyncRoute, include_in_schema=False
)
_FEED = Feed()
_TRANSFERS = TransferStore()


@router.get("/changes")
def get_changes(
    scope_id: str = Query(),
    cursor: str = Query(),
    limit: int = Query(default=MAX_PAGE_TRANSACTIONS, ge=1),
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
) -> dict[str, Any]:
    require_scope(user.id, scope_id)
    with gateway.units.begin(user.id) as unit:
        current = gateway.receipts.admit(unit, gateway.authorize(user))
        if not gateway.enabled(user):
            raise wire.ProtocolFailure("ACCESS_DENIED")
        return read_changes(
            unit,
            current,
            cursor,
            limit,
            now=gateway.clock(),
            feed=_FEED,
            transfers=_TRANSFERS,
        )


@router.get("/transactions/{transfer_id}")
def get_transaction_transfer_page(
    transfer_id: str,
    page_token: str = Query(),
    user: User = Depends(sync_user),
    gateway: SyncGateway = Depends(get_sync_gateway),
) -> dict[str, Any]:
    with gateway.units.begin(user.id) as unit:
        current = gateway.receipts.admit(unit, gateway.authorize(user))
        if not gateway.enabled(user):
            raise wire.ProtocolFailure("ACCESS_DENIED")
        return _TRANSFERS.page(
            unit, current, transfer_id, page_token, now=gateway.clock()
        )
