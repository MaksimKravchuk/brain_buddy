"""Repository for user accounts."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from app.exceptions import ConflictError, NotFoundError
from app.schemas.auth import User
from app.utils.file_ops import ensure_directory, read_json

from .base import BaseRepository

USERS_DIRNAME = "users"
BY_EMAIL_INDEX_FILENAME = "_by_email.json"


class UserRepository(BaseRepository):
    """Persist user accounts as one JSON file per user plus an email index."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.users_dir = ensure_directory(self.resolve(USERS_DIRNAME))
        self.index_path = self.users_dir / BY_EMAIL_INDEX_FILENAME

    def _user_path(self, user_id: str) -> Path:
        return self.users_dir / f"{user_id}.json"

    def _load_email_index(self) -> dict[str, str]:
        if not self.index_path.exists():
            return {}
        raw = read_json(self.index_path)
        if not isinstance(raw, dict):
            return {}
        return {str(k): str(v) for k, v in raw.items()}

    def _save_email_index(self, index: dict[str, str]) -> None:
        self.dump_payload(self.index_path, index)

    @staticmethod
    def normalize_email(email: str) -> str:
        return email.strip().lower()

    def get_by_id(self, user_id: str) -> User | None:
        path = self._user_path(user_id)
        if not path.exists():
            return None
        return self.load_model(path, User)

    def get_by_email(self, email: str) -> User | None:
        normalized = self.normalize_email(email)
        index = self._load_email_index()
        user_id = index.get(normalized)
        if user_id is None:
            return None
        return self.get_by_id(user_id)

    def create(self, user: User) -> User:
        """Persist a new user.

        Raises `ConflictError` if the email is already registered.
        """

        normalized = self.normalize_email(user.email)
        index = self._load_email_index()
        if normalized in index:
            raise ConflictError("User", normalized)

        stored = user.model_copy(update={"email": normalized})
        self.dump_model(self._user_path(stored.id), stored)
        index[normalized] = stored.id
        self._save_email_index(index)
        return stored

    def save(self, user: User) -> None:
        """Overwrite an existing user record in place.

        The email index is not touched — callers must not change the email
        here. Used for mutations like password rotation that keep identity
        stable. Email changes must go through `update_email`.
        """

        self.dump_model(self._user_path(user.id), user)

    def update_email(self, user_id: str, new_email: str) -> User:
        """Move an account to a new email address, keeping the index correct.

        Raises `NotFoundError` if the user doesn't exist and `ConflictError`
        if the address is already registered to another account. The index is
        rewritten first (new key added, old keys for this user removed) in a
        single atomic write, then the user file: if we crash between the two,
        the new address already resolves and the old one no longer does, so
        login behaves correctly and only the user file's `email` field is
        stale until the change is retried.
        """

        user = self.get_by_id(user_id)
        if user is None:
            raise NotFoundError("User", user_id)

        normalized = self.normalize_email(new_email)
        if normalized == user.email:
            return user

        index = self._load_email_index()
        existing_owner = index.get(normalized)
        if existing_owner is not None and existing_owner != user_id:
            raise ConflictError("User", normalized)

        updated_index = {
            key: value for key, value in index.items() if value != user_id
        }
        updated_index[normalized] = user_id
        self._save_email_index(updated_index)

        updated = user.model_copy(update={"email": normalized})
        self.dump_model(self._user_path(user_id), updated)
        return updated

    def delete(self, user_id: str) -> None:
        """Remove a user record and every email-index entry pointing at it.

        Idempotent. The index is scanned by value (not just the current email
        key) so a crash mid-`update_email` can never leave a resolvable
        address behind, and it is saved before the user file is unlinked so a
        crash never leaves an email resolving to a missing file.
        """

        index = self._load_email_index()
        pruned = {key: value for key, value in index.items() if value != user_id}
        if len(pruned) != len(index):
            self._save_email_index(pruned)
        with suppress(FileNotFoundError):
            self._user_path(user_id).unlink()

    def list_users(self) -> list[User]:
        """Return every stored user (used by the account purge sweep)."""

        users: list[User] = []
        for path in sorted(self.users_dir.glob("*.json")):
            if path.name == BY_EMAIL_INDEX_FILENAME:
                continue
            users.append(self.load_model(path, User))
        return users
