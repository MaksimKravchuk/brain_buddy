"""Repository for user accounts."""

from __future__ import annotations

from pathlib import Path

from app.exceptions import ConflictError
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
