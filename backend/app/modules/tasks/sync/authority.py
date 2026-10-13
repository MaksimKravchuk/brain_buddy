"""Current Identity admission for the sync receipt boundary (spec 026 PR-30).

026-FR-010/011/012: every read, write and receipt replay asks Identity again,
under the owner lock, whether the owner may still be served. The generations come
from server state (the scope row, minted once), never from a caller claim, so a
forged or stale request cannot choose its own feed or access generation.
"""

from __future__ import annotations

from collections.abc import Callable
from sqlite3 import Connection
from typing import Any, Protocol
from uuid import uuid4

from app.core.logging import get_correlation_id
from app.schemas.auth import User

from .receipts import Authority, ScopeAuthority, SyncCommandError
from .unit_of_work import OwnerUnitOfWork

NOT_FOUND = "RESOURCE_NOT_FOUND"
_NOT_FOUND_MESSAGE = "The requested resource was not found."


class UserReader(Protocol):
    """The one Identity read the authority needs."""

    def get_by_id(self, user_id: str) -> User | None: ...


def resource_not_found() -> SyncCommandError:
    """The single failure for an unknown or foreign scope/device/snapshot/transfer."""
    return SyncCommandError(NOT_FOUND)


def not_found_response() -> tuple[int, dict[str, Any]]:
    """The owner-safe 404 body; it never names the resource it was asked for."""
    return 404, {
        "error": NOT_FOUND,
        "message": _NOT_FOUND_MESSAGE,
        "correlation_id": get_correlation_id(),
    }


def require_scope(owner_id: str, scope_id: str) -> None:
    """A scope is the owner's own; any other ID reads as unknown."""
    if scope_id != owner_id:
        raise resource_not_found()


def require_owned(owner_id: str, resource_owner: str | None) -> None:
    """A snapshot, transfer or device owned by someone else reads as unknown."""
    if resource_owner is None or resource_owner != owner_id:
        raise resource_not_found()


class IdentityScopeAuthority:
    """``Authority`` backed by Identity; call it with the open owner unit."""

    def __init__(
        self,
        users: UserReader,
        *,
        mint: Callable[[], str] = lambda: str(uuid4()),
        auth_version: int | None = None,
    ) -> None:
        self._users = users
        self._mint = mint
        self._auth_version = auth_version

    def bound_to(self, auth_version: int) -> Authority[Connection]:
        """Authority for a credential issued at ``auth_version``.

        A later credential change closes it, which is how a device or token
        loses receipt reads after revocation. Unbound legacy writers are
        unaffected by credential rotation.
        """
        return IdentityScopeAuthority(
            self._users, mint=self._mint, auth_version=auth_version
        )

    def __call__(self, unit: OwnerUnitOfWork[Connection]) -> ScopeAuthority:
        user = self._users.get_by_id(unit.owner_id)
        live = (
            user is not None
            # A deletion that has begun ends current-owner writes, but the
            # retention cleanup unit must still run to purge the owner's data.
            and (user.deletion_requested_at is None or unit.cleanup)
            and (self._auth_version is None or user.auth_version == self._auth_version)
        )
        row = unit.connection.execute(
            "SELECT * FROM sync_scopes WHERE owner_id = ?", (unit.owner_id,)
        ).fetchone()
        if row is None:
            return ScopeAuthority(
                unit.owner_id,
                self._mint(),
                self._mint(),
                self._mint(),
                self._mint(),
                admission_open=live,
            )
        return ScopeAuthority(
            unit.owner_id,
            row["server_generation"],
            row["feed_generation"],
            row["access_generation"],
            row["storage_epoch"],
            admission_open=live and bool(row["admission_open"]),
        )
