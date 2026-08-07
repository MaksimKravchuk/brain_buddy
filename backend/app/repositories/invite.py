"""Repository for signup invite codes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.exceptions import ConflictError, NotFoundError
from app.schemas.auth import Invite
from app.utils.file_ops import ensure_directory

from .base import BaseRepository

INVITES_DIRNAME = "invites"


class InviteRepository(BaseRepository):
    """Persist invite codes as one JSON file per code."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.invites_dir = ensure_directory(self.resolve(INVITES_DIRNAME))

    def _invite_path(self, code: str) -> Path:
        return self.invites_dir / f"{code}.json"

    def create(self, invite: Invite) -> None:
        path = self._invite_path(invite.code)
        if path.exists():
            raise ConflictError("Invite", invite.code)
        self.dump_model(path, invite)

    def get(self, code: str) -> Invite | None:
        path = self._invite_path(code)
        if not path.exists():
            return None
        return self.load_model(path, Invite)

    def save(self, invite: Invite) -> None:
        """Overwrite an existing invite (used when marking consumed)."""

        self.dump_model(self._invite_path(invite.code), invite)

    def scrub_user(self, user_id: str) -> int:
        """Detach a purged user from any invite they consumed; return the count.

        GDPR erasure support: `used_by_user_id` must stay non-null so the
        invite remains consumed (`is_used`), but it must no longer identify
        the deleted account. Idempotent.
        """

        scrubbed = 0
        for path in self.invites_dir.glob("*.json"):
            invite = self.load_model(path, Invite)
            if invite.used_by_user_id != user_id:
                continue
            self.save(invite.model_copy(update={"used_by_user_id": "deleted-user"}))
            scrubbed += 1
        return scrubbed

    def mark_used(self, code: str, *, user_id: str, used_at: datetime) -> Invite:
        """Mark an invite as consumed by a user.

        Raises `NotFoundError` if the invite doesn't exist and
        `ConflictError` if it was already used by someone else.
        """

        invite = self.get(code)
        if invite is None:
            raise NotFoundError("Invite", code)
        if invite.is_used:
            raise ConflictError("Invite", code)
        updated = invite.model_copy(
            update={"used_by_user_id": user_id, "used_at": used_at}
        )
        self.save(updated)
        return updated
