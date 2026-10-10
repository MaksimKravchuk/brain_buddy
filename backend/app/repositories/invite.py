"""Repository for signup invite codes."""

from __future__ import annotations

import fcntl
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import datetime
from pathlib import Path
from typing import ClassVar, TextIO

from app.exceptions import ConflictError, NotFoundError, RepositoryError
from app.schemas.auth import Invite
from app.utils.file_ops import ensure_directory

from .base import BaseRepository

INVITES_DIRNAME = "invites"


class InviteRepository(BaseRepository):
    """Persist invite codes as one JSON file per code."""

    _thread_state: ClassVar[threading.local] = threading.local()
    _process_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.invites_dir = ensure_directory(self.resolve(INVITES_DIRNAME))

    def _invite_path(self, code: str) -> Path:
        return self.invites_dir / f"{code}.json"

    @contextmanager
    def _mutation_guard(self) -> Iterator[None]:
        """Serialize invite mutations across threads and repository processes."""

        root = self.root.expanduser().resolve()
        active: tuple[Path, int, TextIO] | None = getattr(
            self._thread_state, "mutation_guard", None
        )
        if active is not None:
            active_root, depth, active_lock_file = active
            if active_root != root:
                raise RepositoryError(
                    "Invite storage locks cannot nest for different repositories."
                )
            self._thread_state.mutation_guard = (
                active_root,
                depth + 1,
                active_lock_file,
            )
            try:
                yield
            finally:
                self._thread_state.mutation_guard = (
                    active_root,
                    depth,
                    active_lock_file,
                )
            return

        self._process_lock.acquire()
        lock_file: TextIO | None = None
        try:
            lock_path = root / ".invite-repository.lock"
            try:
                lock_file = lock_path.open("a+", encoding="utf-8")
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                if lock_file is not None:
                    with suppress(OSError):
                        lock_file.close()
                raise RepositoryError(
                    "Invite storage lock is temporarily unavailable."
                ) from exc

            self._thread_state.mutation_guard = (root, 1, lock_file)
            try:
                yield
            finally:
                del self._thread_state.mutation_guard
        finally:
            try:
                if lock_file is not None and not lock_file.closed:
                    lock_file.close()
            finally:
                self._process_lock.release()

    def create(self, invite: Invite) -> None:
        with self._mutation_guard():
            path = self._invite_path(invite.code)
            if path.exists():
                raise ConflictError("Invite", invite.code)
            self._save_unlocked(invite)

    def get(self, code: str) -> Invite | None:
        path = self._invite_path(code)
        if not path.exists():
            return None
        return self.load_model(path, Invite)

    def save(self, invite: Invite) -> None:
        """Overwrite an existing invite (used when marking consumed)."""

        with self._mutation_guard():
            self._save_unlocked(invite)

    def _save_unlocked(self, invite: Invite) -> None:
        self.dump_model(self._invite_path(invite.code), invite)

    def scrub_user(self, user_id: str) -> int:
        """Detach a purged user from any invite they consumed; return the count.

        GDPR erasure support: `used_by_user_id` must stay non-null so the
        invite remains consumed (`is_used`), but it must no longer identify
        the deleted account. Idempotent.
        """

        with self._mutation_guard():
            scrubbed = 0
            for path in self.invites_dir.glob("*.json"):
                invite = self.load_model(path, Invite)
                if invite.used_by_user_id != user_id:
                    continue
                self._save_unlocked(
                    invite.model_copy(update={"used_by_user_id": "deleted-user"})
                )
                scrubbed += 1
            return scrubbed

    def mark_used(self, code: str, *, user_id: str, used_at: datetime) -> Invite:
        """Mark an invite as consumed by a user.

        Raises `NotFoundError` if the invite doesn't exist and
        `ConflictError` if it was already used by someone else.
        """

        with self._mutation_guard():
            invite = self.get(code)
            if invite is None:
                raise NotFoundError("Invite", code)
            if invite.is_used:
                raise ConflictError("Invite", code)
            updated = invite.model_copy(
                update={"used_by_user_id": user_id, "used_at": used_at}
            )
            self._save_unlocked(updated)
            return updated
